"""Async client for the AnkiConnect HTTP API."""

from __future__ import annotations

from collections.abc import Set as AbstractSet
import logging
from typing import Any

import aiohttp

from .const import ANKICONNECT_API_VERSION, CUSTOM_QUERY_KEY_PREFIX, REVIEWED_TODAY_KEY

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)

_LOGGER = logging.getLogger(__name__)


class AnkiConnectError(Exception):
    """Base error for AnkiConnect API failures."""


class AnkiConnectConnectionError(AnkiConnectError):
    """Raised when AnkiConnect cannot be reached."""


class AnkiConnectApiError(AnkiConnectError):
    """Raised when AnkiConnect returns a non-null error field."""


class AnkiConnectClient:
    """Thin async wrapper around the AnkiConnect JSON-RPC-style HTTP API."""

    def __init__(self, session: aiohttp.ClientSession, host: str, port: int) -> None:
        """Initialize the client with an existing aiohttp session."""
        self._session = session
        self._url = f"http://{host}:{port}"

    async def _request(self, action: str, params: dict[str, Any] | None = None) -> Any:
        """Send a single action request and return its result, raising on error.

        AnkiConnect replies with HTTP 200 even for application-level failures;
        the failure is only visible in the JSON body's "error" field.

        Returns:
            The action's "result" value, whose shape depends on the action.

        Raises:
            AnkiConnectConnectionError: If AnkiConnect can't be reached or
                times out.
            AnkiConnectApiError: If the response's "error" field is non-null.

        """
        payload: dict[str, Any] = {"action": action, "version": ANKICONNECT_API_VERSION}
        if params is not None:
            payload["params"] = params

        try:
            async with self._session.post(
                self._url, json=payload, timeout=REQUEST_TIMEOUT
            ) as response:
                response.raise_for_status()
                # content_type=None: AnkiConnect doesn't set a JSON content type.
                body = await response.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            raise AnkiConnectConnectionError(str(err)) from err

        if not isinstance(body, dict):
            raise AnkiConnectConnectionError(f"Unexpected response shape: {body!r}")
        if body.get("error") is not None:
            raise AnkiConnectApiError(body["error"])
        return body.get("result")

    async def get_version(self) -> int:
        """Return the AnkiConnect API version, also used as a connectivity check."""
        return await self._request("version")

    async def sync(self) -> None:
        """Trigger AnkiConnect's own sync with AnkiWeb.

        Errors (AnkiConnect unreachable, no AnkiWeb account configured, ...)
        propagate from `_request` as AnkiConnectError.
        """
        await self._request("sync")

    async def count_cards(self, query: str) -> int:
        """Return the number of cards matching a search query.

        Errors propagate from `_request` as AnkiConnectError, e.g. for
        invalid search syntax.

        Returns:
            The number of matching cards.

        """
        card_ids = await self._request("findCards", {"query": query})
        return len(card_ids)

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
            {
                "action": "findCards",
                "version": ANKICONNECT_API_VERSION,
                "params": {"query": query},
            }
            for query in queries.values()
        ]
        actions.append({
            "action": "getNumCardsReviewedToday",
            "version": ANKICONNECT_API_VERSION,
        })
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
            AnkiConnectConnectionError: If AnkiConnect can't be reached, or
                replies with an unexpected response shape.

        """
        results = await self._request("multi", {"actions": actions})
        if not isinstance(results, list) or len(results) != len(actions):
            raise AnkiConnectConnectionError(
                f"Unexpected multi response shape: {results!r}"
            )

        values: list[Any] = []
        for index, sub_result in enumerate(results):
            if not isinstance(sub_result, dict):
                raise AnkiConnectConnectionError(
                    f"Unexpected sub-result shape: {sub_result!r}"
                )
            error = sub_result.get("error")
            if error is not None:
                if index in tolerant_indices:
                    _LOGGER.warning("AnkiConnect action failed, ignoring: %s", error)
                    values.append(None)
                    continue
                raise AnkiConnectApiError(error)
            values.append(sub_result["result"])
        return values
