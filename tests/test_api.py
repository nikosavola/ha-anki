"""Tests for the AnkiConnect API client."""

from collections.abc import AsyncGenerator

import aiohttp
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ankiconnect.api import (
    AnkiConnectApiError,
    AnkiConnectClient,
    AnkiConnectConnectionError,
)
from custom_components.ankiconnect.const import CARD_QUERIES

from .conftest import TEST_HOST, TEST_PORT, TEST_URL, AnkiConnectResponder


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


async def test_find_cards_counts_batches_into_one_request(
    client: AnkiConnectClient,
    anki_responder: AnkiConnectResponder,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """All configured queries are fetched in a single batched request."""
    anki_responder.set_cards("is:due", [1, 2, 3])
    anki_responder.set_cards("is:new", [4])
    anki_responder.set_cards("is:review", [])

    counts = await client.find_cards_counts(CARD_QUERIES)

    assert counts == {"cards_due": 3, "new_cards": 1, "review_cards": 0}
    assert len(aioclient_mock.mock_calls) == 1


async def test_find_cards_counts_raises_on_error(
    client: AnkiConnectClient, anki_responder: AnkiConnectResponder
) -> None:
    """An error on the overall multi request raises AnkiConnectApiError."""
    anki_responder.set_multi_error("collection is not available")

    with pytest.raises(AnkiConnectApiError, match="collection is not available"):
        await client.find_cards_counts(CARD_QUERIES)


async def test_find_cards_counts_raises_on_query_error(
    client: AnkiConnectClient, anki_responder: AnkiConnectResponder
) -> None:
    """An error on a single query still raises, even if the others succeed."""
    anki_responder.set_cards("is:due", [1, 2])
    anki_responder.set_query_error("is:new", "invalid search")

    with pytest.raises(AnkiConnectApiError, match="invalid search"):
        await client.find_cards_counts(CARD_QUERIES)
