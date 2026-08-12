"""Tests for the ankiconnect.add_note domain service."""

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ankiconnect.const import ADD_NOTE_SERVICE, DOMAIN

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
