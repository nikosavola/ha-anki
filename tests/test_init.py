"""Tests for the ha_anki.add_note domain service and scheduled auto-sync."""

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.ha_anki.const import (
    ADD_NOTE_SERVICE,
    CONF_AUTO_SYNC_INTERVAL,
    DOMAIN,
)

from .conftest import AnkiConnectResponder


async def test_add_note_service_returns_note_id_and_refreshes(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The add_note service returns the new note ID, then refreshes sensors."""
    anki_responder.set_cards("is:new", [1])
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    anki_responder.set_cards("is:new", [1, 2])
    response = await hass.services.async_call(
        DOMAIN,
        ADD_NOTE_SERVICE,
        {
            "config_entry_id": mock_config_entry.entry_id,
            "deck_name": "Default",
            "model_name": "Basic",
            "fields": {"Front": "Capital of France", "Back": "Paris"},
        },
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done()

    assert response == {"note_id": 12345}
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{mock_config_entry.entry_id}_new_cards"
    )
    assert entity_id is not None
    new_cards = hass.states.get(entity_id)
    assert new_cards is not None
    assert new_cards.state == "2"


async def test_add_note_service_calls_ankiconnect_exactly_once(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """One service call POSTs addNote exactly once, not once per sensor entity.

    add_note is a domain service keyed by config_entry_id rather than an
    entity service, specifically so it can't fan out into one call per
    targeted entity (which an entity service would, mutating the collection
    multiple times for a single user action).
    """
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN,
        ADD_NOTE_SERVICE,
        {
            "config_entry_id": mock_config_entry.entry_id,
            "deck_name": "Default",
            "model_name": "Basic",
            "fields": {"Front": "x", "Back": "y"},
        },
        blocking=True,
        return_response=True,
    )

    assert anki_responder.add_note_call_count == 1


async def test_add_note_service_raises_on_duplicate(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The add_note service surfaces an AnkiConnect error as HomeAssistantError."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    anki_responder.set_add_note_error("cannot create note because it is a duplicate")

    with pytest.raises(HomeAssistantError, match="duplicate"):
        await hass.services.async_call(
            DOMAIN,
            ADD_NOTE_SERVICE,
            {
                "config_entry_id": mock_config_entry.entry_id,
                "deck_name": "Default",
                "model_name": "Basic",
                "fields": {"Front": "x", "Back": "y"},
            },
            blocking=True,
            return_response=True,
        )


async def test_add_note_service_rejects_unknown_config_entry(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An unknown config_entry_id is rejected before touching AnkiConnect."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            ADD_NOTE_SERVICE,
            {
                "config_entry_id": "does-not-exist",
                "deck_name": "Default",
                "model_name": "Basic",
                "fields": {"Front": "x", "Back": "y"},
            },
            blocking=True,
            return_response=True,
        )


async def test_add_note_service_rejects_unloaded_config_entry(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A config_entry_id for an unloaded entry is rejected, not silently no-op'd."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            ADD_NOTE_SERVICE,
            {
                "config_entry_id": mock_config_entry.entry_id,
                "deck_name": "Default",
                "model_name": "Basic",
                "fields": {"Front": "x", "Back": "y"},
            },
            blocking=True,
            return_response=True,
        )


def _cards_due_state(hass: HomeAssistant, entry: MockConfigEntry) -> str | None:
    """Return the cards_due sensor's current state string, if it exists."""
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_cards_due"
    )
    if entity_id is None:
        return None
    state = hass.states.get(entity_id)
    return state.state if state is not None else None


async def test_auto_sync_disabled_by_default(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
    freezer,
) -> None:
    """With no auto_sync_interval option, AnkiConnect's sync action is never called."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    freezer.tick(timedelta(days=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert anki_responder.sync_call_count == 0


async def test_auto_sync_interval_zero_disables_it(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
    freezer,
) -> None:
    """An explicit auto_sync_interval of 0 behaves the same as leaving it unset."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_AUTO_SYNC_INTERVAL: 0}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    freezer.tick(timedelta(days=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert anki_responder.sync_call_count == 0


async def test_auto_sync_falls_back_on_invalid_interval_option(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
    freezer,
) -> None:
    """An out-of-range auto_sync_interval is treated as disabled, not fatal."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_AUTO_SYNC_INTERVAL: -5}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    freezer.tick(timedelta(days=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert anki_responder.sync_call_count == 0


async def test_auto_sync_runs_on_configured_interval(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
    freezer,
) -> None:
    """A configured interval triggers a sync, then refreshes sensor state."""
    anki_responder.set_cards("is:due", [1])
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={CONF_SCAN_INTERVAL: 5, CONF_AUTO_SYNC_INTERVAL: 1},
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert _cards_due_state(hass, mock_config_entry) == "1"

    anki_responder.set_cards("is:due", [1, 2])
    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert anki_responder.sync_call_count == 1
    assert _cards_due_state(hass, mock_config_entry) == "2"


async def test_auto_sync_error_is_logged_not_fatal(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
    freezer,
) -> None:
    """A failed scheduled sync is logged, and doesn't refresh or unload the entry."""
    anki_responder.set_cards("is:due", [1])
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_AUTO_SYNC_INTERVAL: 1}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    anki_responder.set_sync_error("please log in to AnkiWeb first")
    anki_responder.set_cards("is:due", [1, 2])
    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert anki_responder.sync_call_count == 1
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert _cards_due_state(hass, mock_config_entry) == "1"
