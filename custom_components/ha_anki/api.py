"""Async client for the AnkiConnect HTTP API."""

from __future__ import annotations

from collections.abc import Set as AbstractSet
import logging
from typing import Any

import aiohttp

from .const import (
    ANKICONNECT_API_VERSION,
    ANKICONNECT_INVALID_KEY_ERROR,
    CUSTOM_QUERY_KEY_PREFIX,
    REVIEWED_TODAY_KEY,
)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)

# A real AnkiWeb sync (especially with media, or a large collection) routinely
# takes longer than REQUEST_TIMEOUT; sync() overrides it with this instead.
SYNC_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=300)

_LOGGER = logging.getLogger(__name__)


class AnkiConnectError(Exception):
    """Base error for AnkiConnect API failures."""


class AnkiConnectConnectionError(AnkiConnectError):
    """Raised when AnkiConnect cannot be reached."""


class AnkiConnectUnreachableError(AnkiConnectConnectionError):
    """Raised when the connection is refused or the host can't be reached."""


class AnkiConnectTimeoutError(AnkiConnectConnectionError):
    """Raised when AnkiConnect doesn't answer in time."""


class AnkiConnectUnexpectedResponseError(AnkiConnectConnectionError):
    """Raised when the host answers, but not like AnkiConnect does."""


class AnkiConnectApiError(AnkiConnectError):
    """Raised when AnkiConnect returns a non-null error field."""


class AnkiConnectInvalidApiKeyError(AnkiConnectApiError):
    """Raised when AnkiConnect rejects a missing or wrong apiKey."""


class AnkiConnectClient:
    """Thin async wrapper around the AnkiConnect JSON-RPC-style HTTP API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        *,
        api_key: str | None = None,
    ) -> None:
        """Initialize the client with an existing aiohttp session."""
        self._session = session
        self._url = f"http://{host}:{port}"
        self._api_key = api_key

    def _action(
        self, action: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Build one action's payload, adding the apiKey when one is configured."""
        payload: dict[str, Any] = {"action": action, "version": ANKICONNECT_API_VERSION}
        if params is not None:
            payload["params"] = params
        # Left out when unset: AnkiConnect rejects any key it doesn't have configured.
        if self._api_key is not None:
            # multi checks the key on each sub-action, not only the outer request.
            payload["key"] = self._api_key
        return payload

    async def _request(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        request_timeout: aiohttp.ClientTimeout = REQUEST_TIMEOUT,
    ) -> Any:
        """Send a single action request and return its result, raising on error.

        AnkiConnect replies with HTTP 200 even for application-level failures;
        the failure is only visible in the JSON body's "error" field.

        Returns:
            The action's "result" value, whose shape depends on the action.

        Raises:
            AnkiConnectUnreachableError: If the connection is refused or the
                host can't be reached.
            AnkiConnectTimeoutError: If AnkiConnect doesn't respond in time.
            AnkiConnectUnexpectedResponseError: If the host answers with an
                HTTP error, a non-JSON body, or a body that isn't AnkiConnect's
                reply shape.
            AnkiConnectConnectionError: If the request fails for another
                network reason.
            AnkiConnectApiError: If the response's "error" field is non-null.
            AnkiConnectInvalidApiKeyError: If AnkiConnect rejects a missing or
                wrong apiKey.

        """
        payload = self._action(action, params)

        try:
            async with self._session.post(
                self._url, json=payload, timeout=request_timeout
            ) as response:
                response.raise_for_status()
                # content_type=None: AnkiConnect doesn't set a JSON content type.
                body = await response.json(content_type=None)
        except aiohttp.ClientConnectorError as err:
            raise AnkiConnectUnreachableError(str(err)) from err
        # Must come before ClientError: aiohttp's timeouts subclass both.
        except TimeoutError as err:
            raise AnkiConnectTimeoutError(str(err)) from err
        except (aiohttp.ClientResponseError, ValueError) as err:
            raise AnkiConnectUnexpectedResponseError(str(err)) from err
        except aiohttp.ClientError as err:
            raise AnkiConnectConnectionError(str(err)) from err

        if not isinstance(body, dict) or "result" not in body or "error" not in body:
            raise AnkiConnectUnexpectedResponseError(
                f"Unexpected response shape: {body!r}"
            )
        if body["error"] is not None:
            if body["error"] == ANKICONNECT_INVALID_KEY_ERROR:
                raise AnkiConnectInvalidApiKeyError(body["error"])
            raise AnkiConnectApiError(body["error"])
        return body["result"]

    async def get_version(self) -> int:
        """Return the AnkiConnect API version, also used as a connectivity check."""
        return await self._request("version")

    async def sync(self) -> None:
        """Trigger AnkiConnect's own sync with AnkiWeb.

        Uses SYNC_REQUEST_TIMEOUT rather than the default: assumes AnkiConnect
        doesn't respond until the AnkiWeb sync itself has finished, which
        matches its observed behavior but isn't documented by AnkiConnect
        itself.

        Errors (AnkiConnect unreachable, no AnkiWeb account configured, ...)
        propagate from `_request` as AnkiConnectError.
        """
        await self._request("sync", request_timeout=SYNC_REQUEST_TIMEOUT)

    async def count_cards(self, query: str) -> int:
        """Return the number of cards matching a search query.

        Errors propagate from `_request` as AnkiConnectError, e.g. for
        invalid search syntax.

        Returns:
            The number of matching cards.

        """
        card_ids = await self._request("findCards", {"query": query})
        return len(card_ids)

    async def add_note(
        self,
        *,
        deck_name: str,
        model_name: str,
        fields: dict[str, str],
        tags: list[str] | None = None,
        allow_duplicate: bool = False,
    ) -> int:
        """Create a new note, returning its note ID.

        Errors propagate from `_request` as AnkiConnectError, e.g. for a
        missing deck or model, or a duplicate note when allow_duplicate is
        false.

        Returns:
            The newly created note's ID.

        """
        note: dict[str, Any] = {
            "deckName": deck_name,
            "modelName": model_name,
            "fields": fields,
            "options": {"allowDuplicate": allow_duplicate},
        }
        if tags:
            note["tags"] = tags
        return await self._request("addNote", {"note": note})

    async def get_sensor_data(self, queries: dict[str, str]) -> dict[str, int | None]:
        """Return the card count for each named query, plus today's review count.

        Batched into one "multi" request, so polling costs a single HTTP round
        trip regardless of how many sensors are configured. A failing
        user-defined custom query (keyed with CUSTOM_QUERY_KEY_PREFIX) doesn't
        fail the whole batch, since it can't have been validated at add-query
        time against an Anki/AnkiConnect version change; it maps to None
        instead. The four built-in queries are hardcoded and can't fail on
        syntax, so an error there still propagates as AnkiConnectError, same
        as a whole-batch or connection failure.

        Returns:
            A mapping from each input key in `queries` to its matching card
            count (or None for a custom query AnkiConnect rejected), plus a
            "reviewed_today" key for the number of cards reviewed today.

        """
        names = [*queries, REVIEWED_TODAY_KEY]
        actions = [
            self._action("findCards", {"query": query}) for query in queries.values()
        ]
        actions.append(self._action("getNumCardsReviewedToday"))
        tolerant_indices = {
            index
            for index, name in enumerate(names)
            if name.startswith(CUSTOM_QUERY_KEY_PREFIX)
        }

        results = await self._multi(actions, tolerant_indices)
        data: dict[str, int | None] = {}
        for name, value in zip(names, results, strict=True):
            if value is None:
                data[name] = None
            else:
                data[name] = value if name == REVIEWED_TODAY_KEY else len(value)
        return data

    async def _multi(
        self,
        actions: list[dict[str, Any]],
        tolerant_indices: AbstractSet[int] = frozenset(),
    ) -> list[Any]:
        """Send a batch of actions via AnkiConnect's "multi" action.

        A sub-action whose index is in `tolerant_indices` yields None instead
        of raising when it errors; every other sub-action, and the request as
        a whole, still raises.

        Returns:
            The "result" value of each sub-action (or None for a tolerated
            error), in the same order.

        Raises:
            AnkiConnectApiError: If AnkiConnect reports an error for the
                overall request or for a non-tolerated sub-action.
            AnkiConnectInvalidApiKeyError: If AnkiConnect rejects a missing or
                wrong apiKey.
            AnkiConnectUnexpectedResponseError: If the reply doesn't have one
                result per action.

        """
        results = await self._request("multi", {"actions": actions})
        if not isinstance(results, list) or len(results) != len(actions):
            raise AnkiConnectUnexpectedResponseError(
                f"Unexpected multi response shape: {results!r}"
            )

        values: list[Any] = []
        for index, sub_result in enumerate(results):
            if not isinstance(sub_result, dict):
                raise AnkiConnectUnexpectedResponseError(
                    f"Unexpected sub-result shape: {sub_result!r}"
                )
            error = sub_result.get("error")
            if error is not None:
                if index in tolerant_indices:
                    _LOGGER.warning("AnkiConnect action failed, ignoring: %s", error)
                    values.append(None)
                    continue
                if error == ANKICONNECT_INVALID_KEY_ERROR:
                    raise AnkiConnectInvalidApiKeyError(error)
                raise AnkiConnectApiError(error)
            values.append(sub_result["result"])
        return values
