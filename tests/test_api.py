"""Tests for the AnkiConnect API client."""

from collections.abc import AsyncGenerator

import aiohttp
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ha_anki.api import (
    AnkiConnectApiError,
    AnkiConnectClient,
    AnkiConnectConnectionError,
)
from custom_components.ha_anki.const import CARD_QUERIES

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
