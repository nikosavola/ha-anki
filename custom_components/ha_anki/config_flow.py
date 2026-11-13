"""Config flow for the ha-anki integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any, override

from homeassistant.config_entries import (
    SOURCE_HASSIO,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
from homeassistant.util import slugify
import voluptuous as vol

from .api import (
    AnkiConnectClient,
    AnkiConnectConnectionError,
    AnkiConnectError,
    AnkiConnectInvalidApiKeyError,
    AnkiConnectTimeoutError,
    AnkiConnectUnexpectedResponseError,
    AnkiConnectUnreachableError,
)
from .const import (
    CARD_QUERIES,
    CONF_AUTO_SYNC_INTERVAL,
    CONF_CUSTOM_QUERIES,
    CONF_QUERY,
    DEFAULT_DISCOVERY_AUTO_SYNC_MINUTES,
    DEFAULT_PORT,
    DOMAIN,
    MAX_INTERVAL_MINUTES,
    MIN_AUTO_SYNC_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
    REVIEWED_TODAY_KEY,
    UPDATE_INTERVAL,
)
from .util import normalize_host

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
    vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
        vol.Coerce(int), vol.Range(min=1, max=65535)
    ),
    vol.Optional(CONF_API_KEY): TextSelector(
        TextSelectorConfig(type=TextSelectorType.PASSWORD)
    ),
})

STEP_REAUTH_DATA_SCHEMA = vol.Schema({
    vol.Optional(CONF_API_KEY): TextSelector(
        TextSelectorConfig(type=TextSelectorType.PASSWORD)
    ),
})


async def _async_validate_connection(
    hass: HomeAssistant,
    raw_host: str,
    raw_port: int,
    raw_api_key: str | None,
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Normalize the connection fields, then check that AnkiConnect answers.

    Returns:
        The cleaned entry data, or None if validation failed, and a dict of
        form errors, empty on success.

    """
    normalized = normalize_host(raw_host, raw_port)
    if normalized is None:
        return None, {CONF_HOST: "invalid_host"}
    host, port = normalized
    api_key = (raw_api_key or "").strip() or None

    client = AnkiConnectClient(
        async_get_clientsession(hass), host, port, api_key=api_key
    )
    try:
        await client.get_version()
    except AnkiConnectUnreachableError:
        return None, {"base": "cannot_connect_refused"}
    except AnkiConnectTimeoutError:
        return None, {"base": "timeout_connect"}
    except AnkiConnectUnexpectedResponseError:
        return None, {"base": "not_ankiconnect"}
    except AnkiConnectInvalidApiKeyError:
        return None, {CONF_API_KEY: "invalid_api_key"}
    except AnkiConnectError:
        return None, {"base": "cannot_connect"}
    except Exception:
        _LOGGER.exception("Unexpected error validating AnkiConnect connection")
        return None, {"base": "unknown"}

    data: dict[str, Any] = {CONF_HOST: host, CONF_PORT: port}
    if api_key is not None:
        data[CONF_API_KEY] = api_key
    return data, {}


def _data_with_updates(
    entry: ConfigEntry, updates: Mapping[str, Any]
) -> dict[str, Any]:
    """Overlay `updates` on the entry's data, dropping an API key they leave out.

    async_update_reload_and_abort's data_updates merges instead, so a cleared
    key would otherwise survive.

    Returns:
        The merged entry data.

    """
    kept = {key: value for key, value in entry.data.items() if key != CONF_API_KEY}
    return {**kept, **updates}


def _discovered_connection(config: Mapping[str, Any]) -> tuple[str, int, str | None]:
    """Read the host, port, and API key the Anki app sent to Supervisor.

    Returns:
        The raw host, the port (DEFAULT_PORT if missing), and the stripped API
        key, or None if the app sent none.

    """
    host = str(config.get(CONF_HOST, ""))
    port = int(config.get(CONF_PORT, DEFAULT_PORT))
    api_key = str(config.get(CONF_API_KEY) or "").strip() or None
    return host, port, api_key


def _retitled(entry: ConfigEntry, new_host: str) -> str:
    """Follow the host in the default "Anki (<host>)" title, keeping a custom one.

    Returns:
        The entry's title with the host swapped in if it was the default.

    """
    if entry.title == f"Anki ({entry.data[CONF_HOST]})":
        return f"Anki ({new_host})"
    return entry.title


class AnkiConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ha-anki."""

    VERSION = 1

    _hassio_discovery: HassioServiceInfo | None = None

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the AnkiConnect host and port, then verify connectivity."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Checked before connecting, so a duplicate aborts even while Anki is closed.
            if normalized := normalize_host(
                user_input[CONF_HOST], user_input[CONF_PORT]
            ):
                await self.async_set_unique_id(f"{normalized[0]}:{normalized[1]}")
                self._abort_if_unique_id_configured()
            data, errors = await _async_validate_connection(
                self.hass,
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                user_input.get(CONF_API_KEY),
            )
            if data is not None:
                return self.async_create_entry(
                    title=f"Anki ({data[CONF_HOST]})", data=data
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the host, port, or API key, keeping the entry's custom queries."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            data, errors = await _async_validate_connection(
                self.hass,
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                user_input.get(CONF_API_KEY),
            )
            if data is not None:
                unique_id = f"{data[CONF_HOST]}:{data[CONF_PORT]}"
                existing = await self.async_set_unique_id(
                    unique_id, raise_on_progress=False
                )
                # Not _abort_if_unique_id_configured: that would also match this entry
                # when only the API key changed.
                if existing is not None and existing.entry_id != entry.entry_id:
                    return self.async_abort(reason="already_configured")

                # App entries stay keyed on the app slug so later discoveries still match.
                if entry.source == SOURCE_HASSIO:
                    unique_id = entry.unique_id
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id,
                    title=_retitled(entry, data[CONF_HOST]),
                    data=_data_with_updates(entry, data),
                )

        # Prefill from the entry on first show, and from the rejected input after that.
        suggested = user_input if user_input is not None else entry.data
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, suggested
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, _entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication after AnkiConnect rejects the stored API key."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API key, keeping the stored host and port."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            data, errors = await _async_validate_connection(
                self.hass,
                entry.data[CONF_HOST],
                entry.data[CONF_PORT],
                user_input.get(CONF_API_KEY),
            )
            if data is not None:
                return self.async_update_reload_and_abort(
                    entry, data=_data_with_updates(entry, data)
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_hassio(
        self, discovery_info: HassioServiceInfo
    ) -> ConfigFlowResult:
        """Handle the Anki app announcing itself to Supervisor."""
        raw_host, raw_port, api_key = _discovered_connection(discovery_info.config)
        normalized = normalize_host(raw_host, raw_port)
        if normalized is None:
            return self.async_abort(reason="invalid_host")
        host, port = normalized
        self._hassio_discovery = discovery_info

        # Keyed on the app slug, not host:port, so a changed hostname updates this entry.
        existing = await self.async_set_unique_id(discovery_info.slug)
        if existing is not None:
            data: dict[str, Any] = {CONF_HOST: host, CONF_PORT: port}
            if api_key is not None:
                data[CONF_API_KEY] = api_key
            new_data = _data_with_updates(existing, data)
            if new_data == existing.data:
                return self.async_abort(reason="already_configured")
            return self.async_update_reload_and_abort(
                existing,
                title=_retitled(existing, host),
                data=new_data,
                reason="already_configured",
                reload_even_if_entry_is_unchanged=False,
            )

        # A manual entry for the same address would otherwise get a second copy.
        self._async_abort_entries_match({CONF_HOST: host, CONF_PORT: port})
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to confirm the discovered app, then verify it answers."""
        discovery_info = self._hassio_discovery
        if discovery_info is None:
            return await self.async_step_user()
        errors: dict[str, str] = {}

        if user_input is not None:
            host, port, api_key = _discovered_connection(discovery_info.config)
            data, errors = await _async_validate_connection(
                self.hass, host, port, api_key
            )
            if data is not None:
                return self.async_create_entry(
                    title=f"Anki ({data[CONF_HOST]})",
                    data=data,
                    options={
                        CONF_AUTO_SYNC_INTERVAL: DEFAULT_DISCOVERY_AUTO_SYNC_MINUTES
                    },
                )
            # This form has no fields, so a field-keyed error would never render.
            errors = {"base": next(iter(errors.values()))}

        return self.async_show_form(
            step_id="hassio_confirm",
            description_placeholders={"addon": discovery_info.name},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AnkiConnectOptionsFlow:  # ruff: ignore[unused-static-method-argument]
        """Return the options flow for managing custom query sensors."""
        return AnkiConnectOptionsFlow()


def _validate_new_query(
    name: str, query: str, custom_queries: dict[str, Any]
) -> tuple[str, dict[str, str]]:
    """Check a new custom query's name/text against locally known constraints.

    Only the checks that don't need AnkiConnect: the search-syntax check
    happens separately, since it requires an await the caller's control flow
    needs to interleave with these.

    Returns:
        The slugified name, and a dict of errors (empty if valid).

    """
    slug = slugify(name)
    errors: dict[str, str] = {}
    if not slug:
        errors[CONF_NAME] = "invalid_name"
    elif slug in custom_queries or slug in CARD_QUERIES or slug == REVIEWED_TODAY_KEY:
        errors[CONF_NAME] = "name_exists"
    elif not query:
        errors[CONF_QUERY] = "empty_query"
    return slug, errors


class AnkiConnectOptionsFlow(OptionsFlowWithReload):
    """Add or remove custom AnkiConnect search-query sensors.

    Each step persists immediately via async_create_entry rather than
    accumulating changes across a multi-step flow, so closing the dialog
    partway through never discards an already-added or already-removed query.
    """

    async def async_step_init(
        self, _user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a menu to change the poll/sync intervals, or add/remove a custom query."""
        menu_options = ["set_interval", "add_query"]
        if self.config_entry.options.get(CONF_CUSTOM_QUERIES):
            menu_options.append("remove_query")
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_set_interval(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the poll interval and the optional auto-sync interval, in minutes."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    **self.config_entry.options,
                    CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                    CONF_AUTO_SYNC_INTERVAL: user_input[CONF_AUTO_SYNC_INTERVAL],
                },
            )

        current_scan_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, int(UPDATE_INTERVAL.total_seconds() // 60)
        )
        current_auto_sync_interval = self.config_entry.options.get(
            CONF_AUTO_SYNC_INTERVAL, MIN_AUTO_SYNC_INTERVAL_MINUTES
        )
        return self.async_show_form(
            step_id="set_interval",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_SCAN_INTERVAL, default=current_scan_interval
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL_MINUTES, max=MAX_INTERVAL_MINUTES),
                ),
                vol.Required(
                    CONF_AUTO_SYNC_INTERVAL, default=current_auto_sync_interval
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_AUTO_SYNC_INTERVAL_MINUTES, max=MAX_INTERVAL_MINUTES
                    ),
                ),
            }),
        )

    async def async_step_add_query(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a name and AnkiConnect search query, then validate and save it."""
        errors: dict[str, str] = {}
        custom_queries = self.config_entry.options.get(CONF_CUSTOM_QUERIES, {})

        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            query = user_input[CONF_QUERY].strip()
            slug, errors = _validate_new_query(name, query, custom_queries)

            if not errors:
                # Built fresh, not from self.config_entry.runtime_data: the
                # options flow can be opened even when the entry failed to
                # load (e.g. Anki was closed at startup), in which case
                # runtime_data is never set.
                client = AnkiConnectClient(
                    async_get_clientsession(self.hass),
                    self.config_entry.data[CONF_HOST],
                    self.config_entry.data[CONF_PORT],
                    api_key=self.config_entry.data.get(CONF_API_KEY),
                )
                try:
                    await client.count_cards(query)
                except AnkiConnectConnectionError:
                    errors["base"] = "cannot_connect"
                # Must come before AnkiConnectError, which it subclasses.
                except AnkiConnectInvalidApiKeyError:
                    errors["base"] = "invalid_api_key"
                    # The poll may not have failed yet, so start reauth here too.
                    self.config_entry.async_start_reauth(self.hass)
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
