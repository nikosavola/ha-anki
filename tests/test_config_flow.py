"""Tests for the AnkiConnect config flow."""

import aiohttp
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ankiconnect.const import DOMAIN

from .conftest import TEST_HOST, TEST_PORT, TEST_URL, AnkiConnectResponder


async def test_user_flow_success(
    hass: HomeAssistant, anki_responder: AnkiConnectResponder
) -> None:
    """A reachable AnkiConnect instance creates a config entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Anki ({TEST_HOST})"
    assert result["data"] == {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT}


async def test_user_flow_normalizes_host(
    hass: HomeAssistant, anki_responder: AnkiConnectResponder
) -> None:
    """Surrounding whitespace and casing in the host don't create distinct entries."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: f"  {TEST_HOST.upper()}  ", CONF_PORT: TEST_PORT}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == TEST_HOST


async def test_user_flow_api_error_cannot_connect(
    hass: HomeAssistant, anki_responder: AnkiConnectResponder
) -> None:
    """An AnkiConnect-level error re-shows the form with cannot_connect, not an entry."""
    anki_responder.set_version_error("collection is not available")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_network_error_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A network-level failure re-shows the form with cannot_connect, not an entry."""
    aioclient_mock.post(
        TEST_URL, exc=aiohttp.ClientConnectionError("Connection refused")
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_unexpected_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An error outside the AnkiConnect error hierarchy shows unknown, not a crash."""
    aioclient_mock.post(TEST_URL, exc=RuntimeError("boom"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A second entry for the same host and port aborts instead of duplicating."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
