"""AnkiConnectClient against a real, seeded Anki + AnkiConnect instance.

Unlike tests/test_api.py, nothing here is mocked: this is the check that the
hand-written aiohttp mocks in tests/ actually match AnkiConnect's real wire
format, not just our own assumptions about it.
"""

from collections.abc import AsyncGenerator

import aiohttp
import pytest

from custom_components.ankiconnect.api import AnkiConnectClient
from custom_components.ankiconnect.const import CARD_QUERIES

from .conftest import E2E_HOST, E2E_PORT, EXPECTED_COUNTS

pytestmark = pytest.mark.e2e


@pytest.fixture
async def client() -> AsyncGenerator[AnkiConnectClient]:
    """Return a client pointed at the real, seeded AnkiConnect instance."""
    async with aiohttp.ClientSession() as session:
        yield AnkiConnectClient(session, E2E_HOST, E2E_PORT)


async def test_get_version(client: AnkiConnectClient) -> None:
    """The real AnkiConnect answers the "version" action."""
    assert await client.get_version() >= 6


async def test_get_sensor_data_matches_seeded_fixture(
    client: AnkiConnectClient,
) -> None:
    """The batched "multi" request returns exactly what was seeded."""
    assert await client.get_sensor_data(CARD_QUERIES) == EXPECTED_COUNTS
