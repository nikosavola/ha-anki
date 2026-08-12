"""Fixtures for the AnkiConnect tests."""

from __future__ import annotations

from typing import Any

from homeassistant.const import CONF_HOST, CONF_PORT
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.ha_anki.const import DOMAIN

TEST_HOST = "192.168.1.10"
TEST_PORT = 8765
TEST_URL = f"http://{TEST_HOST}:{TEST_PORT}"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add --run-e2e, opting in to tests/e2e's real-Anki-instance tests."""
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="run end-to-end tests against a real Anki + AnkiConnect instance",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the "e2e" marker used by tests/e2e."""
    config.addinivalue_line(
        "markers", "e2e: end-to-end test requiring a real Anki + AnkiConnect instance"
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip e2e-marked tests unless --run-e2e is passed.

    A bare `pytest` run still collects tests/e2e (it's under the tests/
    testpaths), but nothing there can pass without a real running instance,
    so it's opt-in rather than deselected outright: skipped, not silently
    absent.
    """
    if config.getoption("--run-e2e"):
        return
    skip_e2e = pytest.mark.skip(reason="need --run-e2e to run")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading the integration from custom_components."""


class AnkiConnectResponder:
    """Programs canned AnkiConnect responses for the mocked aiohttp session.

    AiohttpClientMocker matches responses by URL alone, but every AnkiConnect
    action is POSTed to the same URL, so a side_effect callback dispatches on
    the request body's "action" field instead.
    """

    def __init__(self, aioclient_mock: AiohttpClientMocker) -> None:
        """Wire the responder into the aiohttp client mocker."""
        self._version: int = 6
        self._version_error: str | None = None
        self._multi_error: str | None = None
        self._sync_error: str | None = None
        self._cards_by_query: dict[str, list[int]] = {}
        self._query_errors: dict[str, str] = {}
        self._reviewed_today: int = 0
        self._add_note_result: int | None = 12345
        self._add_note_error: str | None = None
        self.add_note_call_count = 0
        aioclient_mock.post(TEST_URL, side_effect=self._respond)

    def set_version_error(self, error: str) -> None:
        """Make the "version" action return an AnkiConnect error."""
        self._version_error = error

    def set_multi_error(self, error: str | None) -> None:
        """Make the whole "multi" action return an AnkiConnect error, or clear it."""
        self._multi_error = error

    def set_sync_error(self, error: str | None) -> None:
        """Make the "sync" action return an AnkiConnect error, or clear it."""
        self._sync_error = error

    def set_cards(self, query: str, card_ids: list[int]) -> None:
        """Program the card IDs a findCards query, batched via multi, returns."""
        self._cards_by_query[query] = card_ids

    def set_query_error(self, query: str, error: str) -> None:
        """Make one findCards query, batched via multi, return an error."""
        self._query_errors[query] = error

    def set_reviewed_today(self, count: int) -> None:
        """Program the getNumCardsReviewedToday action's result."""
        self._reviewed_today = count

    def set_add_note_error(self, error: str | None) -> None:
        """Make the "addNote" action return an AnkiConnect error, or clear it."""
        self._add_note_error = error

    async def _respond(
        self, method: str, url: Any, data: dict[str, Any]
    ) -> AiohttpClientMockResponse:
        """Build the AnkiConnect-shaped JSON response for one request."""
        action = data["action"]
        if action == "version":
            body = (
                {"result": None, "error": self._version_error}
                if self._version_error
                else {"result": self._version, "error": None}
            )
        elif action == "sync":
            body = {"result": None, "error": self._sync_error}
        elif action == "multi":
            body = self._multi_body(data["params"]["actions"])
        elif action == "findCards":
            query = data["params"]["query"]
            if query in self._query_errors:
                body = {"result": None, "error": self._query_errors[query]}
            else:
                body = {"result": self._cards_by_query.get(query, []), "error": None}
        elif action == "addNote":
            self.add_note_call_count += 1
            body = (
                {"result": None, "error": self._add_note_error}
                if self._add_note_error
                else {"result": self._add_note_result, "error": None}
            )
        else:
            raise AssertionError(f"Unexpected AnkiConnect action in test: {action}")
        return AiohttpClientMockResponse(method, url, json=body)

    def _multi_body(self, actions: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the "multi" action's batched result array."""
        if self._multi_error:
            return {"result": None, "error": self._multi_error}

        sub_results = [self._sub_result(action) for action in actions]
        return {"result": sub_results, "error": None}

    def _sub_result(self, action: dict[str, Any]) -> dict[str, Any]:
        """Build one sub-action's result within a "multi" response."""
        if action["action"] == "getNumCardsReviewedToday":
            return {"result": self._reviewed_today, "error": None}

        query = action["params"]["query"]
        if query in self._query_errors:
            return {"result": None, "error": self._query_errors[query]}
        return {"result": self._cards_by_query.get(query, []), "error": None}


@pytest.fixture
def anki_responder(
    aioclient_mock: AiohttpClientMocker,
) -> AnkiConnectResponder:
    """Return a responder programming AnkiConnect replies for this test."""
    return AnkiConnectResponder(aioclient_mock)


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry for AnkiConnect."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Anki ({TEST_HOST})",
        unique_id=f"{TEST_HOST}:{TEST_PORT}",
        data={CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT},
    )
