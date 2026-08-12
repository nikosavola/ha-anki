"""Full config entry setup against a real Anki + AnkiConnect instance.

Exercises config_flow, the coordinator, and the sensor platform together
against a real backend, unlike tests/test_sensor.py which mocks aiohttp.
"""

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ankiconnect.const import DOMAIN

from .conftest import E2E_HOST, E2E_PORT, EXPECTED_COUNTS

pytestmark = pytest.mark.e2e


async def test_setup_entry_reports_real_card_counts(hass: HomeAssistant) -> None:
    """A config entry set up against the real instance reports seeded counts."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"Anki ({E2E_HOST})",
        unique_id=f"{E2E_HOST}:{E2E_PORT}",
        data={CONF_HOST: E2E_HOST, CONF_PORT: E2E_PORT},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    for key, expected in EXPECTED_COUNTS.items():
        entity_id = entity_registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{key}"
        )
        assert entity_id is not None
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == str(expected)
