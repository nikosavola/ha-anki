"""DataUpdateCoordinator for the ha-anki integration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AnkiConnectClient, AnkiConnectError
from .const import (
    CARD_QUERIES,
    CONF_CUSTOM_QUERIES,
    CONF_QUERY,
    CUSTOM_QUERY_KEY_PREFIX,
    DOMAIN,
    MAX_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
    UPDATE_INTERVAL,
)
from .util import resolve_minutes_option

_LOGGER = logging.getLogger(__name__)

type AnkiConnectConfigEntry = ConfigEntry[AnkiConnectDataUpdateCoordinator]


def _resolve_update_interval(options: Mapping[str, Any]) -> timedelta:
    """Turn the options-configured scan interval into a timedelta."""
    minutes = resolve_minutes_option(
        options,
        CONF_SCAN_INTERVAL,
        minimum=MIN_SCAN_INTERVAL_MINUTES,
        maximum=MAX_INTERVAL_MINUTES,
        default=int(UPDATE_INTERVAL.total_seconds() // 60),
    )
    return timedelta(minutes=minutes)


class AnkiConnectDataUpdateCoordinator(DataUpdateCoordinator[dict[str, int | None]]):
    """Poll AnkiConnect for card counts, shared by all sensors of one entry."""

    config_entry: AnkiConnectConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: AnkiConnectConfigEntry,
        client: AnkiConnectClient,
    ) -> None:
        """Initialize the coordinator."""
        update_interval = _resolve_update_interval(config_entry.options)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, int | None]:
        """Fetch all sensor data, built-in and user-defined, in one batched request."""
        custom_queries = self.config_entry.options.get(CONF_CUSTOM_QUERIES, {})
        queries = {
            **CARD_QUERIES,
            **{
                f"{CUSTOM_QUERY_KEY_PREFIX}{slug}": data[CONF_QUERY]
                for slug, data in custom_queries.items()
            },
        }
        try:
            return await self.client.get_sensor_data(queries)
        except AnkiConnectError as err:
            raise UpdateFailed(f"Error communicating with AnkiConnect: {err}") from err
