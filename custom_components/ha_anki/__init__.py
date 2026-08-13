"""The ha-anki integration."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

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
from homeassistant.helpers.event import async_track_time_interval
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
    CONF_AUTO_SYNC_INTERVAL,
    CONF_CONFIG_ENTRY_ID,
    DOMAIN,
    MAX_INTERVAL_MINUTES,
    MIN_AUTO_SYNC_INTERVAL_MINUTES,
)
from .coordinator import AnkiConnectConfigEntry, AnkiConnectDataUpdateCoordinator
from .util import resolve_minutes_option

_LOGGER = logging.getLogger(__name__)

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
    _async_schedule_auto_sync(hass, entry)
    return True


def _async_schedule_auto_sync(
    hass: HomeAssistant, entry: AnkiConnectConfigEntry
) -> None:
    """Schedule a periodic AnkiConnect sync if entry.options requests one.

    A 0 (or missing) auto_sync_interval option means auto-sync is off, not a
    zero-length interval: the user calls the sync service themselves.
    """
    minutes = resolve_minutes_option(
        entry.options,
        CONF_AUTO_SYNC_INTERVAL,
        minimum=MIN_AUTO_SYNC_INTERVAL_MINUTES,
        maximum=MAX_INTERVAL_MINUTES,
        default=MIN_AUTO_SYNC_INTERVAL_MINUTES,
    )
    if minutes <= 0:
        return

    coordinator = entry.runtime_data
    # Keyed by entry_id in hass.data, not just a variable in this closure: a
    # reload replaces entry.runtime_data and rebuilds this closure, but HA's
    # unload only waits up to 10s for a still-running job, so a sync slower
    # than that can outlive the reload. The guard has to survive it too, or
    # the fresh closure can't tell a leftover sync is still in flight.
    entry_sync_state = hass.data.setdefault(DOMAIN, {}).setdefault(
        entry.entry_id, {"sync_in_progress": False}
    )
    was_failing = False

    async def _async_auto_sync(_now: datetime) -> None:
        """Trigger a sync, then refresh sensor state, logging rather than raising.

        There's no caller here to surface a HomeAssistantError to, unlike the
        sync service's async_sync in sensor.py.

        HA's interval scheduler reschedules the next tick immediately, not
        after this one finishes, so a sync slower than the configured
        interval would otherwise overlap the next tick; entry_sync_state
        skips a tick rather than starting a second concurrent sync. Repeated
        failures log once, not once per tick, matching how
        AnkiConnectDataUpdateCoordinator already handles the sibling poll
        failures.
        """
        nonlocal was_failing
        if entry_sync_state["sync_in_progress"]:
            _LOGGER.debug(
                "Skipping scheduled AnkiConnect sync: the previous one is still running"
            )
            return

        entry_sync_state["sync_in_progress"] = True
        try:
            await coordinator.client.sync()
        except AnkiConnectError as err:
            if not was_failing:
                _LOGGER.warning("Scheduled AnkiConnect sync failed: %s", err)
                was_failing = True
            return
        finally:
            entry_sync_state["sync_in_progress"] = False

        if was_failing:
            _LOGGER.info("Scheduled AnkiConnect sync recovered")
            was_failing = False
        await coordinator.async_request_refresh()

    entry.async_on_unload(
        async_track_time_interval(hass, _async_auto_sync, timedelta(minutes=minutes))
    )


async def _async_update_listener(
    hass: HomeAssistant, entry: AnkiConnectConfigEntry
) -> None:
    """Reload the entry when its options (intervals, custom queries) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: AnkiConnectConfigEntry
) -> bool:
    """Unload an AnkiConnect config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
