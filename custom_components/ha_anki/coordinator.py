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
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

type AnkiConnectConfigEntry = ConfigEntry[AnkiConnectDataUpdateCoordinator]


def _resolve_update_interval(options: Mapping[str, Any]) -> timedelta:
    """Turn the options-configured scan interval into a timedelta.

    Falls back to UPDATE_INTERVAL for a missing, non-integer, or out-of-range
    value rather than raising, since the options flow already enforces the
    valid range and this guards only against options edited outside of it
    (e.g. directly in storage) causing a setup crash or a runaway poll loop.

    Returns:
        The interval to poll AnkiConnect on.

    """
    minutes = options.get(CONF_SCAN_INTERVAL)
    if (
        not isinstance(minutes, int)
        or isinstance(minutes, bool)
        or not MIN_SCAN_INTERVAL_MINUTES <= minutes <= MAX_SCAN_INTERVAL_MINUTES
    ):
        if minutes is not None:
            _LOGGER.warning(
                "Ignoring invalid %s option %r, using the default",
                CONF_SCAN_INTERVAL,
                minutes,
            )
        return UPDATE_INTERVAL
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
