"""DataUpdateCoordinator for the AnkiConnect integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AnkiConnectClient, AnkiConnectError
from .const import CARD_QUERIES, DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

type AnkiConnectConfigEntry = ConfigEntry[AnkiConnectDataUpdateCoordinator]


class AnkiConnectDataUpdateCoordinator(DataUpdateCoordinator[dict[str, int]]):
    """Poll AnkiConnect for card counts, shared by all sensors of one entry."""

    config_entry: AnkiConnectConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: AnkiConnectConfigEntry,
        client: AnkiConnectClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, int]:
        """Fetch card counts for every configured query in one batched request."""
        try:
            return await self.client.find_cards_counts(CARD_QUERIES)
        except AnkiConnectError as err:
            raise UpdateFailed(f"Error communicating with AnkiConnect: {err}") from err
