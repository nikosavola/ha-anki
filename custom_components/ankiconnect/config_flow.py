"""Config flow for the AnkiConnect integration."""

from __future__ import annotations

import logging
from typing import Any, override

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import slugify
import voluptuous as vol

from .api import AnkiConnectClient, AnkiConnectConnectionError, AnkiConnectError
from .const import (
    CARD_QUERIES,
    CONF_CUSTOM_QUERIES,
    CONF_QUERY,
    DEFAULT_PORT,
    DOMAIN,
    REVIEWED_TODAY_KEY,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
    vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
        vol.Coerce(int), vol.Range(min=1, max=65535)
    ),
})


class AnkiConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AnkiConnect."""

    VERSION = 1

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the AnkiConnect host and port, then verify connectivity."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip().lower()
            port = user_input[CONF_PORT]
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            data = {CONF_HOST: host, CONF_PORT: port}
            client = AnkiConnectClient(async_get_clientsession(self.hass), host, port)
            try:
                await client.get_version()
            except AnkiConnectError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating AnkiConnect connection")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=f"Anki ({host})", data=data)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AnkiConnectOptionsFlow:  # ruff: ignore[unused-static-method-argument]
        """Return the options flow for managing custom query sensors."""
        return AnkiConnectOptionsFlow()


class AnkiConnectOptionsFlow(OptionsFlow):
    """Add or remove custom AnkiConnect search-query sensors.

    Each step persists immediately via async_create_entry rather than
    accumulating changes across a multi-step flow, so closing the dialog
    partway through never discards an already-added or already-removed query.
    """

    async def async_step_init(
        self, _user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a menu to add or remove a custom query."""
        menu_options = ["add_query"]
        if self.config_entry.options.get(CONF_CUSTOM_QUERIES):
            menu_options.append("remove_query")
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_add_query(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a name and AnkiConnect search query, then validate and save it."""
        errors: dict[str, str] = {}
        custom_queries = self.config_entry.options.get(CONF_CUSTOM_QUERIES, {})

        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            query = user_input[CONF_QUERY].strip()
            slug = slugify(name)

            if not slug:
                errors[CONF_NAME] = "invalid_name"
            elif (
                slug in custom_queries
                or slug in CARD_QUERIES
                or slug == REVIEWED_TODAY_KEY
            ):
                errors[CONF_NAME] = "name_exists"
            elif not query:
                errors[CONF_QUERY] = "empty_query"
            else:
                # Built fresh, not from self.config_entry.runtime_data: the
                # options flow can be opened even when the entry failed to
                # load (e.g. Anki was closed at startup), in which case
                # runtime_data is never set.
                client = AnkiConnectClient(
                    async_get_clientsession(self.hass),
                    self.config_entry.data[CONF_HOST],
                    self.config_entry.data[CONF_PORT],
                )
                try:
                    await client.count_cards(query)
                except AnkiConnectConnectionError:
                    errors["base"] = "cannot_connect"
                except AnkiConnectError:
                    errors[CONF_QUERY] = "invalid_query"
                except Exception:
                    _LOGGER.exception("Unexpected error validating custom query")
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(
                        title="",
                        data={
                            **self.config_entry.options,
                            CONF_CUSTOM_QUERIES: {
                                **custom_queries,
                                slug: {CONF_NAME: name, CONF_QUERY: query},
                            },
                        },
                    )

        return self.async_show_form(
            step_id="add_query",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_QUERY): str,
            }),
            errors=errors,
        )

    async def async_step_remove_query(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick one or more previously added custom queries to remove."""
        custom_queries = self.config_entry.options.get(CONF_CUSTOM_QUERIES, {})

        if user_input is not None:
            remaining = {
                slug: data
                for slug, data in custom_queries.items()
                if slug not in user_input[CONF_CUSTOM_QUERIES]
            }
            return self.async_create_entry(
                title="",
                data={**self.config_entry.options, CONF_CUSTOM_QUERIES: remaining},
            )

        return self.async_show_form(
            step_id="remove_query",
            data_schema=vol.Schema({
                vol.Required(CONF_CUSTOM_QUERIES): cv.multi_select({
                    slug: data[CONF_NAME] for slug, data in custom_queries.items()
                })
            }),
        )
