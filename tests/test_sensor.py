"""Tests for the ha-anki sensor platform and entry setup."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.ha_anki.const import (
    CONF_CUSTOM_QUERIES,
    CONF_QUERY,
    DOMAIN,
    SYNC_SERVICE,
    UPDATE_INTERVAL,
)

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
    anki_responder.set_reviewed_today(7)
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _state(hass, mock_config_entry, "cards_due") == "2"
    assert _state(hass, mock_config_entry, "new_cards") == "3"
    assert _state(hass, mock_config_entry, "review_cards") == "0"
    assert _state(hass, mock_config_entry, "reviewed_today") == "7"


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


async def test_sync_service_refreshes_sensors(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The sync service triggers a sync, then an immediate sensor refresh."""
    anki_responder.set_cards("is:due", [1])
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert _state(hass, mock_config_entry, "cards_due") == "1"

    anki_responder.set_cards("is:due", [1, 2])
    entity_id = _maybe_entity_id(hass, mock_config_entry, "cards_due")
    assert entity_id is not None
    await hass.services.async_call(
        DOMAIN, SYNC_SERVICE, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert _state(hass, mock_config_entry, "cards_due") == "2"


async def test_sync_service_raises_on_error(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The sync service surfaces an AnkiConnect error as HomeAssistantError."""
    anki_responder.set_cards("is:due", [1])
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    anki_responder.set_sync_error("please log in to AnkiWeb first")
    entity_id = _maybe_entity_id(hass, mock_config_entry, "cards_due")
    assert entity_id is not None

    with pytest.raises(HomeAssistantError, match="please log in to AnkiWeb first"):
        await hass.services.async_call(
            DOMAIN, SYNC_SERVICE, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )


async def test_custom_query_sensor_is_created(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A custom query in entry.options gets its own sensor, named and reporting."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            CONF_CUSTOM_QUERIES: {
                "spanish_due": {
                    CONF_NAME: "Spanish due",
                    CONF_QUERY: "deck:Spanish is:due",
                }
            }
        },
    )
    anki_responder.set_cards("deck:Spanish is:due", [1, 2, 3])

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = _maybe_entity_id(hass, mock_config_entry, "custom_spanish_due")
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "3"
    assert state.attributes["friendly_name"] == "Anki (192.168.1.10) Spanish due"


async def test_removed_custom_query_prunes_stale_entity(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Removing a custom query from options removes its registry entry on reload."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            CONF_CUSTOM_QUERIES: {
                "spanish_due": {
                    CONF_NAME: "Spanish due",
                    CONF_QUERY: "deck:Spanish is:due",
                }
            }
        },
    )
    anki_responder.set_cards("deck:Spanish is:due", [1])
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert _maybe_entity_id(hass, mock_config_entry, "custom_spanish_due") is not None

    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_CUSTOM_QUERIES: {}}
    )
    await hass.async_block_till_done()

    assert _maybe_entity_id(hass, mock_config_entry, "custom_spanish_due") is None


async def test_failing_custom_query_does_not_affect_builtin_sensors(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A custom query AnkiConnect rejects goes unknown, without affecting the rest."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            CONF_CUSTOM_QUERIES: {
                "bad": {CONF_NAME: "Bad", CONF_QUERY: "not a real query"}
            }
        },
    )
    anki_responder.set_cards("is:due", [1, 2])
    anki_responder.set_query_error("not a real query", "invalid search")

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _state(hass, mock_config_entry, "cards_due") == "2"
    assert _state(hass, mock_config_entry, "custom_bad") == "unknown"
