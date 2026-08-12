"""Tests for the AnkiConnect sensor platform and entry setup."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.ankiconnect.const import DOMAIN, UPDATE_INTERVAL

from .conftest import AnkiConnectResponder


def _maybe_entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, key: str
) -> str | None:
    """Look up a sensor's entity_id by its stable unique_id, if it exists."""
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{key}"
    )


def _state(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> str:
    """Return a sensor's current state string."""
    entity_id = _maybe_entity_id(hass, entry, key)
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    return state.state


async def test_sensors_report_card_counts(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Each sensor reports the card count for its own query."""
    anki_responder.set_cards("is:due", [1, 2])
    anki_responder.set_cards("is:new", [3, 4, 5])
    anki_responder.set_cards("is:review", [])
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _state(hass, mock_config_entry, "cards_due") == "2"
    assert _state(hass, mock_config_entry, "new_cards") == "3"
    assert _state(hass, mock_config_entry, "review_cards") == "0"


async def test_setup_retries_on_update_failure(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A failed first refresh leaves the entry in setup-retry, with no entities."""
    anki_responder.set_multi_error("collection is not available")
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert _maybe_entity_id(hass, mock_config_entry, "cards_due") is None


async def test_coordinator_polls_on_interval(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
    freezer,
) -> None:
    """The coordinator refreshes sensor state every UPDATE_INTERVAL."""
    anki_responder.set_cards("is:due", [1])
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _state(hass, mock_config_entry, "cards_due") == "1"

    anki_responder.set_cards("is:due", [1, 2, 3])
    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert _state(hass, mock_config_entry, "cards_due") == "3"


async def test_sensors_go_unavailable_then_recover(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
    freezer,
) -> None:
    """A poll failure marks sensors unavailable; a later successful poll recovers them."""
    anki_responder.set_cards("is:due", [1])
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert _state(hass, mock_config_entry, "cards_due") == "1"

    anki_responder.set_multi_error("collection is not available")
    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _state(hass, mock_config_entry, "cards_due") == "unavailable"

    anki_responder.set_multi_error(None)
    anki_responder.set_cards("is:due", [1, 2])
    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _state(hass, mock_config_entry, "cards_due") == "2"


async def test_unload_entry(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Unloading the entry removes its sensors."""
    anki_responder.set_cards("is:due", [1])
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    assert _state(hass, mock_config_entry, "cards_due") == "unavailable"
