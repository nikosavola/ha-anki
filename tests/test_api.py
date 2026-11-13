"""Tests for the AnkiConnect API client."""

from collections.abc import AsyncGenerator, Callable
from functools import partial
from http import HTTPStatus
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.ha_anki.api import (
    SYNC_REQUEST_TIMEOUT,
    AnkiConnectApiError,
    AnkiConnectClient,
    AnkiConnectConnectionError,
    AnkiConnectInvalidApiKeyError,
    AnkiConnectTimeoutError,
    AnkiConnectUnexpectedResponseError,
    AnkiConnectUnreachableError,
)
from custom_components.ha_anki.const import CARD_QUERIES

from .conftest import (
    TEST_HOST,
    TEST_PORT,
    TEST_URL,
    AnkiConnectResponder,
    refused_connection_error,
)


@pytest.fixture
async def client(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> AsyncGenerator[AnkiConnectClient]:
    """Return a client backed by the mocked aiohttp session."""
    session = aioclient_mock.create_session(hass.loop)
    try:
        yield AnkiConnectClient(session, TEST_HOST, TEST_PORT)
    finally:
        await session.close()


@pytest.fixture
async def make_client(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> AsyncGenerator[Callable[..., AnkiConnectClient]]:
    """Return a factory for clients, with optional constructor kwargs like api_key."""
    session = aioclient_mock.create_session(hass.loop)
    try:
        yield partial(AnkiConnectClient, session, TEST_HOST, TEST_PORT)
    finally:
        await session.close()


async def test_get_version(
    client: AnkiConnectClient, anki_responder: AnkiConnectResponder
) -> None:
    """get_version returns the AnkiConnect API version."""
    assert await client.get_version() == 6


async def test_get_version_raises_on_error(
    client: AnkiConnectClient, anki_responder: AnkiConnectResponder
) -> None:
    """A non-null error field raises AnkiConnectApiError."""
    anki_responder.set_version_error("collection is not available")

    with pytest.raises(AnkiConnectApiError, match="collection is not available"):
        await client.get_version()


async def test_get_version_raises_on_connection_error(
    client: AnkiConnectClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A network-level failure raises AnkiConnectConnectionError, not a raw exception."""
    aioclient_mock.post(
        TEST_URL, exc=aiohttp.ClientConnectionError("Connection refused")
    )

    with pytest.raises(AnkiConnectConnectionError):
        await client.get_version()


async def test_get_version_raises_unreachable_when_connection_refused(
    client: AnkiConnectClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A refused connection raises AnkiConnectUnreachableError."""
    aioclient_mock.post(TEST_URL, exc=refused_connection_error())

    with pytest.raises(AnkiConnectUnreachableError):
        await client.get_version()


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(aiohttp.ConnectionTimeoutError("timed out"), id="connect"),
        pytest.param(TimeoutError(), id="total"),
    ],
)
async def test_get_version_raises_timeout(
    client: AnkiConnectClient, aioclient_mock: AiohttpClientMocker, exc: BaseException
) -> None:
    """A request that never gets a reply raises AnkiConnectTimeoutError."""
    aioclient_mock.post(TEST_URL, exc=exc)

    with pytest.raises(AnkiConnectTimeoutError):
        await client.get_version()


@pytest.mark.parametrize(
    ("status", "text"),
    [
        pytest.param(HTTPStatus.NOT_FOUND, "Not Found", id="http-error"),
        pytest.param(HTTPStatus.OK, "<html>not json</html>", id="not-json"),
        pytest.param(HTTPStatus.OK, "[]", id="json-list"),
        pytest.param(HTTPStatus.OK, '{"unexpected": true}', id="no-result-or-error"),
    ],
)
async def test_get_version_raises_unexpected_response(
    client: AnkiConnectClient,
    aioclient_mock: AiohttpClientMocker,
    status: HTTPStatus,
    text: str,
) -> None:
    """A reply that isn't AnkiConnect's shape raises AnkiConnectUnexpectedResponseError."""
    aioclient_mock.post(TEST_URL, status=status, text=text)

    with pytest.raises(AnkiConnectUnexpectedResponseError):
        await client.get_version()


async def test_get_sensor_data_batches_into_one_request(
    client: AnkiConnectClient,
    anki_responder: AnkiConnectResponder,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """All configured queries, plus reviewed_today, are fetched in one request."""
    anki_responder.set_cards("is:due", [1, 2, 3])
    anki_responder.set_cards("is:new", [4])
    anki_responder.set_cards("is:review", [])
    anki_responder.set_reviewed_today(7)

    data = await client.get_sensor_data(CARD_QUERIES)

    assert data == {
        "cards_due": 3,
        "new_cards": 1,
        "review_cards": 0,
        "reviewed_today": 7,
    }
    assert len(aioclient_mock.mock_calls) == 1


async def test_get_sensor_data_raises_on_error(
    client: AnkiConnectClient, anki_responder: AnkiConnectResponder
) -> None:
    """An error on the overall multi request raises AnkiConnectApiError."""
    anki_responder.set_multi_error("collection is not available")

    with pytest.raises(AnkiConnectApiError, match="collection is not available"):
        await client.get_sensor_data(CARD_QUERIES)


async def test_get_sensor_data_raises_on_query_error(
    client: AnkiConnectClient, anki_responder: AnkiConnectResponder
) -> None:
    """An error on a single query still raises, even if the others succeed."""
    anki_responder.set_cards("is:due", [1, 2])
    anki_responder.set_query_error("is:new", "invalid search")

    with pytest.raises(AnkiConnectApiError, match="invalid search"):
        await client.get_sensor_data(CARD_QUERIES)


async def test_get_sensor_data_tolerates_custom_query_error(
    client: AnkiConnectClient, anki_responder: AnkiConnectResponder
) -> None:
    """A failing custom_-prefixed query maps to None, without failing the batch."""
    anki_responder.set_cards("is:due", [1, 2])
    anki_responder.set_query_error("not a real query", "invalid search")

    data = await client.get_sensor_data({
        **CARD_QUERIES,
        "custom_bad": "not a real query",
    })

    assert data["cards_due"] == 2
    assert data["custom_bad"] is None


async def test_count_cards(
    client: AnkiConnectClient, anki_responder: AnkiConnectResponder
) -> None:
    """count_cards returns the number of matching card IDs."""
    anki_responder.set_cards("deck:Spanish is:due", [1, 2, 3])

    assert await client.count_cards("deck:Spanish is:due") == 3


async def test_count_cards_raises_on_error(
    client: AnkiConnectClient, anki_responder: AnkiConnectResponder
) -> None:
    """An invalid search query raises AnkiConnectApiError."""
    anki_responder.set_query_error("not a real query", "invalid search")

    with pytest.raises(AnkiConnectApiError, match="invalid search"):
        await client.count_cards("not a real query")


async def test_add_note(
    client: AnkiConnectClient, anki_responder: AnkiConnectResponder
) -> None:
    """add_note returns the newly created note's ID."""
    note_id = await client.add_note(
        deck_name="Default",
        model_name="Basic",
        fields={"Front": "Capital of France", "Back": "Paris"},
    )

    assert note_id == 12345


async def test_add_note_raises_on_duplicate(
    client: AnkiConnectClient, anki_responder: AnkiConnectResponder
) -> None:
    """A duplicate note raises AnkiConnectApiError when allow_duplicate is false."""
    anki_responder.set_add_note_error("cannot create note because it is a duplicate")

    with pytest.raises(AnkiConnectApiError, match="duplicate"):
        await client.add_note(
            deck_name="Default", model_name="Basic", fields={"Front": "x", "Back": "y"}
        )


async def test_sync(
    client: AnkiConnectClient, anki_responder: AnkiConnectResponder
) -> None:
    """Sync completes without raising when AnkiConnect reports no error."""
    await client.sync()


async def test_sync_raises_on_error(
    client: AnkiConnectClient, anki_responder: AnkiConnectResponder
) -> None:
    """Sync raises AnkiConnectApiError when AnkiConnect reports one."""
    anki_responder.set_sync_error("please log in to AnkiWeb first")

    with pytest.raises(AnkiConnectApiError, match="please log in to AnkiWeb first"):
        await client.sync()


async def test_sync_uses_a_longer_timeout(
    client: AnkiConnectClient,
    anki_responder: AnkiConnectResponder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sync() overrides the default per-request timeout with SYNC_REQUEST_TIMEOUT.

    A real AnkiWeb sync routinely outlasts the default timeout other actions
    use; this pins that override so it can't silently regress back to it.
    """
    original_request = client._request
    captured: dict[str, object] = {}

    async def _capturing_request(action: str, params=None, **kwargs):
        captured.update(kwargs)
        return await original_request(action, params, **kwargs)

    monkeypatch.setattr(client, "_request", _capturing_request)

    await client.sync()

    assert captured.get("request_timeout") is SYNC_REQUEST_TIMEOUT


async def test_request_sends_api_key(
    make_client: Callable[..., AnkiConnectClient],
    anki_responder: AnkiConnectResponder,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A configured apiKey is sent with the request, so AnkiConnect accepts it."""
    anki_responder.require_key("secret")

    assert await make_client(api_key="secret").get_version() == 6
    assert aioclient_mock.mock_calls[-1][2]["key"] == "secret"


async def test_request_omits_api_key_when_unset(
    client: AnkiConnectClient,
    anki_responder: AnkiConnectResponder,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """With no apiKey configured, the request carries no "key" field at all."""
    anki_responder.require_key(None)

    assert await client.get_version() == 6
    assert "key" not in aioclient_mock.mock_calls[-1][2]


async def test_multi_sends_api_key_on_every_action(
    make_client: Callable[..., AnkiConnectClient],
    anki_responder: AnkiConnectResponder,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Each batched action carries the apiKey, since AnkiConnect checks them one by one."""
    anki_responder.require_key("secret")
    anki_responder.set_cards("is:due", [1, 2])

    data = await make_client(api_key="secret").get_sensor_data(CARD_QUERIES)

    assert data["cards_due"] == 2
    sub_actions = aioclient_mock.mock_calls[-1][2]["params"]["actions"]
    assert all(sub_action["key"] == "secret" for sub_action in sub_actions)


async def test_request_raises_invalid_api_key_when_key_is_wrong(
    make_client: Callable[..., AnkiConnectClient],
    anki_responder: AnkiConnectResponder,
) -> None:
    """A wrong apiKey raises AnkiConnectInvalidApiKeyError."""
    anki_responder.require_key("secret")

    with pytest.raises(AnkiConnectInvalidApiKeyError):
        await make_client(api_key="wrong").get_version()


async def test_ipv6_host_is_bracketed_in_url(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An IPv6 host is sent in brackets, so its colons aren't read as the port."""
    aioclient_mock.post("http://[fe80::1]:8765", json={"result": 6, "error": None})
    session = aioclient_mock.create_session(hass.loop)
    try:
        client = AnkiConnectClient(session, "fe80::1", TEST_PORT)
        assert await client.get_version() == 6
    finally:
        await session.close()


async def test_request_raises_invalid_api_key_when_key_is_missing(
    client: AnkiConnectClient,
    anki_responder: AnkiConnectResponder,
) -> None:
    """A missing apiKey raises AnkiConnectInvalidApiKeyError if AnkiConnect requires one."""
    anki_responder.require_key("secret")

    with pytest.raises(AnkiConnectInvalidApiKeyError):
        await client.get_version()


async def test_request_retries_once_when_server_drops_pooled_connection(
    client: AnkiConnectClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A stale keep-alive socket gets one retry instead of failing the request."""
    calls = 0

    async def respond(
        method: str, url: Any, _data: dict[str, Any]
    ) -> AiohttpClientMockResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise aiohttp.ServerDisconnectedError
        return AiohttpClientMockResponse(method, url, json={"result": 6, "error": None})

    aioclient_mock.post(TEST_URL, side_effect=respond)

    assert await client.get_version() == 6
    assert calls == 2


async def test_request_gives_up_after_second_disconnect(
    client: AnkiConnectClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A server that keeps disconnecting still surfaces as a connection error."""
    aioclient_mock.post(TEST_URL, exc=aiohttp.ServerDisconnectedError())

    with pytest.raises(AnkiConnectConnectionError):
        await client.get_version()
    assert len(aioclient_mock.mock_calls) == 2
