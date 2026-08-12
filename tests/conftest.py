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

from custom_components.ankiconnect.const import DOMAIN

TEST_HOST = "192.168.1.10"
TEST_PORT = 8765
TEST_URL = f"http://{TEST_HOST}:{TEST_PORT}"


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
        self._cards_by_query: dict[str, list[int]] = {}
        self._query_errors: dict[str, str] = {}
        aioclient_mock.post(TEST_URL, side_effect=self._respond)

    def set_version_error(self, error: str) -> None:
        """Make the "version" action return an AnkiConnect error."""
        self._version_error = error

    def set_multi_error(self, error: str | None) -> None:
        """Make the whole "multi" action return an AnkiConnect error, or clear it."""
        self._multi_error = error

    def set_cards(self, query: str, card_ids: list[int]) -> None:
        """Program the card IDs a findCards query, batched via multi, returns."""
        self._cards_by_query[query] = card_ids

    def set_query_error(self, query: str, error: str) -> None:
        """Make one findCards query, batched via multi, return an error."""
        self._query_errors[query] = error

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
        elif action == "multi":
            body = self._multi_body(data["params"]["actions"])
        else:
            raise AssertionError(f"Unexpected AnkiConnect action in test: {action}")
        return AiohttpClientMockResponse(method, url, json=body)

    def _multi_body(self, actions: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the "multi" action's batched result array."""
        if self._multi_error:
            return {"result": None, "error": self._multi_error}

        sub_results = [
            self._sub_result(action["params"]["query"]) for action in actions
        ]
        return {"result": sub_results, "error": None}

    def _sub_result(self, query: str) -> dict[str, Any]:
        """Build one findCards sub-result within a "multi" response."""
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
