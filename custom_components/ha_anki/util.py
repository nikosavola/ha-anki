"""Small helpers shared across the ha-anki integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)


def resolve_minutes_option(
    options: Mapping[str, Any], key: str, *, minimum: int, maximum: int, default: int
) -> int:
    """Read a bounded integer-minutes option, falling back to a default.

    The options flow already enforces [minimum, maximum], so this only
    guards against a value edited outside of it (e.g. directly in storage),
    which would otherwise crash setup or produce a nonsensical interval.

    Returns:
        The option's value if it's an int within [minimum, maximum],
        otherwise `default`.

    """
    value = options.get(key)
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not minimum <= value <= maximum
    ):
        if value is not None:
            _LOGGER.warning(
                "Ignoring invalid %s option %r, using the default", key, value
            )
        return default
    return value
