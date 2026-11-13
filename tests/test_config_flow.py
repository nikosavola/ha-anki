"""Tests for the ha-anki config flow."""

from http import HTTPStatus
from typing import Any

import aiohttp
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntryState,
)
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ha_anki.const import (
    CONF_AUTO_SYNC_INTERVAL,
    CONF_CUSTOM_QUERIES,
    CONF_QUERY,
    DOMAIN,
)

from .conftest import (
    TEST_HOST,
    TEST_PORT,
    TEST_URL,
    AnkiConnectResponder,
    refused_connection_error,
)

NEW_HOST = "192.168.1.20"
NEW_URL = f"http://{NEW_HOST}:{TEST_PORT}"


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


async def test_user_flow_accepts_pasted_url(
    hass: HomeAssistant, anki_responder: AnkiConnectResponder
) -> None:
    """A pasted URL is split into host and port, and its port overrides the port field."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: f" http://{TEST_HOST}:{TEST_PORT}/ ", CONF_PORT: 1234},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT}
    assert result["result"].unique_id == f"{TEST_HOST}:{TEST_PORT}"


async def test_user_flow_rejects_host_without_name(
    hass: HomeAssistant, anki_responder: AnkiConnectResponder
) -> None:
    """A host field that is only a scheme re-shows the form with invalid_host on the field."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "http://", CONF_PORT: TEST_PORT}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOST: "invalid_host"}


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


async def test_user_flow_duplicate_aborts_while_anki_is_closed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Re-adding a configured host aborts instead of showing a connection error."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.post(TEST_URL, exc=refused_connection_error())

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: f"http://{TEST_HOST}:{TEST_PORT}/"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert aioclient_mock.call_count == 0


@pytest.mark.parametrize(
    ("mock_kwargs", "expected_error"),
    [
        pytest.param(
            {"exc": refused_connection_error()}, "cannot_connect_refused", id="refused"
        ),
        pytest.param(
            {"exc": aiohttp.ConnectionTimeoutError("timed out")},
            "timeout_connect",
            id="timeout",
        ),
        pytest.param(
            {"status": HTTPStatus.NOT_FOUND, "text": "Not Found"},
            "not_ankiconnect",
            id="http-error",
        ),
        pytest.param({"text": "<html>"}, "not_ankiconnect", id="not-json"),
    ],
)
async def test_user_flow_shows_specific_connection_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_kwargs: dict[str, Any],
    expected_error: str,
) -> None:
    """Each kind of connection failure re-shows the form with its own error."""
    aioclient_mock.post(TEST_URL, **mock_kwargs)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected_error}


async def test_user_flow_saves_api_key(
    hass: HomeAssistant, anki_responder: AnkiConnectResponder
) -> None:
    """An apiKey entered in the form is saved on the new entry."""
    anki_responder.require_key("secret")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT, CONF_API_KEY: "secret"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_HOST: TEST_HOST,
        CONF_PORT: TEST_PORT,
        CONF_API_KEY: "secret",
    }


async def test_user_flow_leaves_blank_api_key_out_of_entry(
    hass: HomeAssistant, anki_responder: AnkiConnectResponder
) -> None:
    """A blank apiKey field means no key, so none is saved."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT, CONF_API_KEY: "   "},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_API_KEY not in result["data"]


@pytest.mark.parametrize("api_key", ["wrong", ""], ids=["wrong-key", "missing-key"])
async def test_user_flow_invalid_api_key(
    hass: HomeAssistant, anki_responder: AnkiConnectResponder, api_key: str
) -> None:
    """A missing or wrong apiKey re-shows the form with an error on the field."""
    anki_responder.require_key("secret")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT, CONF_API_KEY: api_key},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_API_KEY: "invalid_api_key"}


async def test_options_flow_add_query_sends_api_key(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Validating a new query uses the entry's apiKey, so it works when one is required."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_API_KEY: "secret"},
    )
    anki_responder.require_key("secret")
    anki_responder.set_cards("deck:Spanish is:due", [1])

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_query"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NAME: "Spanish due", CONF_QUERY: "deck:Spanish is:due"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY


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
    await hass.async_block_till_done()

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


async def test_options_flow_set_interval(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Setting the intervals saves them under CONF_SCAN_INTERVAL/CONF_AUTO_SYNC_INTERVAL."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "set_interval"}
    )
    assert result["step_id"] == "set_interval"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 15, CONF_AUTO_SYNC_INTERVAL: 30}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_SCAN_INTERVAL: 15,
        CONF_AUTO_SYNC_INTERVAL: 30,
    }


async def test_options_flow_set_interval_defaults_auto_sync_to_disabled(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Leaving the auto-sync field alone keeps auto-sync disabled (0)."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "set_interval"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 15}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_SCAN_INTERVAL: 15,
        CONF_AUTO_SYNC_INTERVAL: 0,
    }


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


async def test_reconfigure_updates_host_and_reloads(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A new host updates the existing entry in place, keeps its custom queries, and reloads it."""
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
    anki_responder.serve(NEW_URL)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": mock_config_entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST, CONF_PORT: TEST_PORT}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data == {CONF_HOST: NEW_HOST, CONF_PORT: TEST_PORT}
    assert mock_config_entry.unique_id == f"{NEW_HOST}:{TEST_PORT}"
    assert mock_config_entry.title == f"Anki ({NEW_HOST})"
    assert mock_config_entry.options[CONF_CUSTOM_QUERIES] == {
        "spanish_due": {CONF_NAME: "Spanish due", CONF_QUERY: "deck:Spanish is:due"}
    }
    assert mock_config_entry.state is ConfigEntryState.LOADED


async def test_reconfigure_keeps_a_custom_title(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A title the user set isn't replaced by the default one when the host changes."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, title="Office Anki")
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    anki_responder.serve(NEW_URL)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": mock_config_entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST, CONF_PORT: TEST_PORT}
    )
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.title == "Office Anki"


async def test_reconfigure_changes_api_key_on_same_host(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Changing only the API key succeeds, so the entry doesn't collide with itself."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    anki_responder.require_key("secret")

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": mock_config_entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT, CONF_API_KEY: "secret"},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data == {
        CONF_HOST: TEST_HOST,
        CONF_PORT: TEST_PORT,
        CONF_API_KEY: "secret",
    }


async def test_reconfigure_blank_api_key_removes_it(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Clearing the API key field drops the saved key, since data updates would otherwise keep it."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_API_KEY: "secret"},
    )
    anki_responder.require_key("secret")
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    anki_responder.require_key(None)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": mock_config_entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT, CONF_API_KEY: ""},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert CONF_API_KEY not in mock_config_entry.data


async def test_reconfigure_prefills_current_values(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The form shows the entry's host, port, and API key as suggestions, not defaults."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_API_KEY: "secret"},
    )
    anki_responder.require_key("secret")
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": mock_config_entry.entry_id},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["data_schema"] is not None
    suggestions = {
        str(key.schema): key.description for key in result["data_schema"].schema
    }
    assert suggestions[CONF_HOST] == {"suggested_value": TEST_HOST}
    assert suggestions[CONF_PORT] == {"suggested_value": TEST_PORT}
    assert suggestions[CONF_API_KEY] == {"suggested_value": "secret"}


async def test_reconfigure_shows_error_and_keeps_entry(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A new address that fails the connection check re-shows the form and changes nothing."""
    mock_config_entry.add_to_hass(hass)
    anki_responder.serve(NEW_URL)
    anki_responder.set_version_error("collection is not available")

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": mock_config_entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST, CONF_PORT: TEST_PORT}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "cannot_connect"}
    assert mock_config_entry.data == {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT}


async def test_reconfigure_aborts_when_another_entry_has_the_address(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Moving an entry onto another entry's host and port aborts instead of duplicating it."""
    mock_config_entry.add_to_hass(hass)
    MockConfigEntry(
        domain=DOMAIN,
        title=f"Anki ({NEW_HOST})",
        unique_id=f"{NEW_HOST}:{TEST_PORT}",
        data={CONF_HOST: NEW_HOST, CONF_PORT: TEST_PORT},
    ).add_to_hass(hass)
    anki_responder.serve(NEW_URL)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": mock_config_entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST, CONF_PORT: TEST_PORT}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data == {CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT}


async def _start_rejected_key_entry(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
    *,
    required_key: str | None,
) -> str:
    """Set up an entry whose stored API key is rejected, returning its reauth flow ID."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, CONF_API_KEY: "wrong"}
    )
    anki_responder.require_key(required_key)
    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    (flow,) = mock_config_entry.async_get_active_flows(hass, {SOURCE_REAUTH})
    return flow["flow_id"]


async def test_reauth_saves_new_api_key(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A corrected API key is saved, and the entry loads with it."""
    flow_id = await _start_rejected_key_entry(
        hass, anki_responder, mock_config_entry, required_key="secret"
    )

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_API_KEY: "secret"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data == {
        CONF_HOST: TEST_HOST,
        CONF_PORT: TEST_PORT,
        CONF_API_KEY: "secret",
    }
    assert mock_config_entry.state is ConfigEntryState.LOADED


async def test_reauth_wrong_key_shows_error(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Another wrong key re-shows the reauth form, and the stored key is left alone."""
    flow_id = await _start_rejected_key_entry(
        hass, anki_responder, mock_config_entry, required_key="secret"
    )

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_API_KEY: "still-wrong"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {CONF_API_KEY: "invalid_api_key"}
    assert mock_config_entry.data[CONF_API_KEY] == "wrong"


async def test_reauth_blank_key_removes_it(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Leaving the key empty removes it when AnkiConnect no longer requires one."""
    flow_id = await _start_rejected_key_entry(
        hass, anki_responder, mock_config_entry, required_key=None
    )

    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_API_KEY: ""})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert CONF_API_KEY not in mock_config_entry.data


async def test_options_flow_add_query_reports_rejected_api_key(
    hass: HomeAssistant,
    anki_responder: AnkiConnectResponder,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A rejected API key while validating a query says so, rather than blaming the query."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, CONF_API_KEY: "wrong"}
    )
    anki_responder.require_key("secret")

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_query"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NAME: "Spanish due", CONF_QUERY: "deck:Spanish is:due"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_api_key"}
    assert (
        len(list(mock_config_entry.async_get_active_flows(hass, {SOURCE_REAUTH}))) == 1
    )
