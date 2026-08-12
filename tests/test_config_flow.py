"""Tests for the ha-anki config flow."""

import aiohttp
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ha_anki.const import CONF_CUSTOM_QUERIES, CONF_QUERY, DOMAIN

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


async def test_options_flow_add_query(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Adding a custom query validates it against AnkiConnect, then saves it."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    anki_responder.set_cards("deck:Spanish is:due", [1, 2])

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert "remove_query" not in result["menu_options"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_query"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NAME: "Spanish due", CONF_QUERY: "deck:Spanish is:due"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_CUSTOM_QUERIES: {
            "spanish_due": {CONF_NAME: "Spanish due", CONF_QUERY: "deck:Spanish is:due"}
        }
    }


async def test_options_flow_add_query_rejects_invalid_query(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A query AnkiConnect rejects re-shows the form with an error, not an entry."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    anki_responder.set_query_error("not a real query", "invalid search")

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_query"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NAME: "Bad", CONF_QUERY: "not a real query"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_QUERY: "invalid_query"}


async def test_options_flow_add_query_rejects_empty_query(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A blank query is rejected locally, without calling AnkiConnect."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_query"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NAME: "Blank", CONF_QUERY: "   "}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_QUERY: "empty_query"}


async def test_options_flow_add_query_reports_cannot_connect(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A network failure while validating the query is distinguished from a bad query."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_query"}
    )

    aioclient_mock.clear_requests()
    aioclient_mock.post(
        TEST_URL, exc=aiohttp.ClientConnectionError("Connection refused")
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NAME: "Spanish due", CONF_QUERY: "deck:Spanish is:due"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_options_flow_add_query_works_when_entry_not_loaded(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Adding a query doesn't depend on runtime_data, so it works on a NOT_LOADED entry.

    The options flow can be opened even when the config entry failed to set
    up (e.g. Anki was closed at startup), in which case runtime_data is never
    assigned.
    """
    mock_config_entry.add_to_hass(hass)
    anki_responder.set_cards("deck:Spanish is:due", [1])

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_query"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NAME: "Spanish due", CONF_QUERY: "deck:Spanish is:due"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_CUSTOM_QUERIES: {
            "spanish_due": {CONF_NAME: "Spanish due", CONF_QUERY: "deck:Spanish is:due"}
        }
    }


async def test_options_flow_add_query_rejects_duplicate_name(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A name that collides with a built-in sensor key is rejected."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_query"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NAME: "Cards due", CONF_QUERY: "is:due"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_NAME: "name_exists"}


async def test_options_flow_remove_query(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Removing a query clears it from options, and the menu offers it beforehand."""
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
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert "remove_query" in result["menu_options"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_query"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CUSTOM_QUERIES: ["spanish_due"]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {CONF_CUSTOM_QUERIES: {}}


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
