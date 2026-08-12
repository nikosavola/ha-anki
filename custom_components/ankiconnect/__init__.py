"""The AnkiConnect integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType, VolDictType
import voluptuous as vol

from .api import AnkiConnectClient, AnkiConnectError
from .const import (
    ADD_NOTE_SERVICE,
    ATTR_ALLOW_DUPLICATE,
    ATTR_DECK_NAME,
    ATTR_FIELDS,
    ATTR_MODEL_NAME,
    ATTR_TAGS,
    CONF_CONFIG_ENTRY_ID,
    DOMAIN,
)
from .coordinator import AnkiConnectConfigEntry, AnkiConnectDataUpdateCoordinator

PLATFORMS = [Platform.SENSOR]

ADD_NOTE_SCHEMA: VolDictType = {
    vol.Required(CONF_CONFIG_ENTRY_ID): cv.string,
    vol.Required(ATTR_DECK_NAME): cv.string,
    vol.Required(ATTR_MODEL_NAME): cv.string,
    vol.Required(ATTR_FIELDS): vol.Schema({cv.string: cv.string}),
    vol.Optional(ATTR_TAGS): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(ATTR_ALLOW_DUPLICATE, default=False): cv.boolean,
}


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Register domain-wide services, once regardless of how many entries exist."""
    hass.services.async_register(
        DOMAIN,
        ADD_NOTE_SERVICE,
        _async_add_note,
        schema=vol.Schema(ADD_NOTE_SCHEMA),
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def _async_add_note(call: ServiceCall) -> ServiceResponse:
    """Create a new Anki note, then refresh that entry's sensor state.

    add_note is a domain service, keyed by config_entry_id, rather than an
    entity service targeted at a sensor: it mutates the collection, so unlike
    read-only polling it must run exactly once per call, which an entity
    service targeting a device or several entities can't guarantee.

    Returns:
        A dict with the newly created note's ID under "note_id".

    Raises:
        ServiceValidationError: If config_entry_id doesn't refer to a loaded
            AnkiConnect entry.
        HomeAssistantError: If AnkiConnect can't be reached, or rejects the
            note (e.g. missing deck/model, or a duplicate when
            allow_duplicate is false).

    """
    entry: AnkiConnectConfigEntry | None = call.hass.config_entries.async_get_entry(
        call.data[CONF_CONFIG_ENTRY_ID]
    )
    if (
        entry is None
        or entry.domain != DOMAIN
        or entry.state is not ConfigEntryState.LOADED
    ):
        raise ServiceValidationError(
            "config_entry_id must refer to a loaded AnkiConnect config entry"
        )

    coordinator = entry.runtime_data
    try:
        note_id = await coordinator.client.add_note(
            deck_name=call.data[ATTR_DECK_NAME],
            model_name=call.data[ATTR_MODEL_NAME],
            fields=call.data[ATTR_FIELDS],
            tags=call.data.get(ATTR_TAGS),
            allow_duplicate=call.data[ATTR_ALLOW_DUPLICATE],
        )
    except AnkiConnectError as err:
        raise HomeAssistantError(f"Failed to add note: {err}") from err
    await coordinator.async_request_refresh()
    return {"note_id": note_id}


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
