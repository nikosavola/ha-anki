"""Config flow for the AnkiConnect integration."""

from __future__ import annotations

import logging
from typing import Any, override

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .api import AnkiConnectClient, AnkiConnectError
from .const import DEFAULT_PORT, DOMAIN

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
