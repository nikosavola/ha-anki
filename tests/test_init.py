"""Tests for the ha_anki.add_note domain service and scheduled auto-sync."""

import asyncio
from datetime import timedelta
import logging

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


async def test_auto_sync_repeated_failure_logs_once(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
    freezer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A persistent sync failure logs one warning, not one per tick, then recovers."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_AUTO_SYNC_INTERVAL: 1}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    anki_responder.set_sync_error("please log in to AnkiWeb first")
    with caplog.at_level(logging.WARNING, logger="custom_components.ha_anki"):
        for _ in range(3):
            freezer.tick(timedelta(minutes=1))
            async_fire_time_changed(hass)
            await hass.async_block_till_done()

    assert anki_responder.sync_call_count == 3
    failure_records = [
        r for r in caplog.records if "Scheduled AnkiConnect sync failed" in r.message
    ]
    assert len(failure_records) == 1

    anki_responder.set_sync_error(None)
    with caplog.at_level(logging.INFO, logger="custom_components.ha_anki"):
        freezer.tick(timedelta(minutes=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    assert any("recovered" in r.message for r in caplog.records)


async def test_auto_sync_cancelled_on_unload(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
    freezer,
) -> None:
    """Unloading the entry stops the scheduled sync from firing again."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_AUTO_SYNC_INTERVAL: 1}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    freezer.tick(timedelta(days=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert anki_responder.sync_call_count == 0


async def test_auto_sync_disable_via_options_stops_further_syncs(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
    freezer,
) -> None:
    """Disabling auto-sync through the options flow on a loaded entry takes effect."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_AUTO_SYNC_INTERVAL: 1}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert anki_responder.sync_call_count == 1

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "set_interval"}
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 5, CONF_AUTO_SYNC_INTERVAL: 0}
    )
    await hass.async_block_till_done()

    freezer.tick(timedelta(minutes=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert anki_responder.sync_call_count == 1


async def test_auto_sync_reschedule_via_options_uses_new_interval(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
    freezer,
) -> None:
    """Changing the auto-sync interval through the options flow reschedules it."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_AUTO_SYNC_INTERVAL: 1}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "set_interval"}
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 5, CONF_AUTO_SYNC_INTERVAL: 3}
    )
    await hass.async_block_till_done()

    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert anki_responder.sync_call_count == 0, "old 1-minute cadence must not fire"

    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert anki_responder.sync_call_count == 1


async def test_auto_sync_interval_unblocked_by_a_much_longer_poll_interval(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
    freezer,
) -> None:
    """A short auto-sync interval fires on its own cadence, not gated on the poll.

    Doesn't assert on sensor state: a successful scheduled sync also calls
    async_request_refresh, which reschedules the coordinator's own poll timer
    relative to itself, so poll and sync timing aren't fully independent of
    each other's side effects, only independently triggered.
    """
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={CONF_SCAN_INTERVAL: 10, CONF_AUTO_SYNC_INTERVAL: 1},
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert anki_responder.sync_call_count == 0

    for expected in range(1, 4):
        freezer.tick(timedelta(minutes=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert anki_responder.sync_call_count == expected


async def test_auto_sync_skips_overlapping_run(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
    freezer,
) -> None:
    """A sync slower than the interval isn't joined by the next scheduled tick."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_AUTO_SYNC_INTERVAL: 1}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    call_count = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_sync() -> None:
        nonlocal call_count
        call_count += 1
        started.set()
        await release.wait()

    mock_config_entry.runtime_data.client.sync = slow_sync

    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass)
    await started.wait()
    assert call_count == 1

    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass)
    # A bare yield, not a timed sleep: the frozen clock never advances in
    # real time, so anything that waits on a real delay would hang forever.
    for _ in range(10):
        await asyncio.sleep(0)
    assert call_count == 1, "a second tick must not start a concurrent sync"

    release.set()
    await hass.async_block_till_done()
    assert call_count == 1
