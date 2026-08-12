"""The AnkiConnect integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AnkiConnectClient
from .coordinator import AnkiConnectConfigEntry, AnkiConnectDataUpdateCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: AnkiConnectConfigEntry) -> bool:
    """Set up AnkiConnect from a config entry."""
    session = async_get_clientsession(hass)
    client = AnkiConnectClient(session, entry.data[CONF_HOST], entry.data[CONF_PORT])
    coordinator = AnkiConnectDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: AnkiConnectConfigEntry
) -> None:
    """Reload the entry when its options (custom queries) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: AnkiConnectConfigEntry
) -> bool:
    """Unload an AnkiConnect config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
