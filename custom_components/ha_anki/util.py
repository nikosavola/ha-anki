"""Small helpers shared across the ha-anki integration."""

from __future__ import annotations

from collections.abc import Mapping
import ipaddress
import logging
from typing import Any
from urllib.parse import urlsplit

_LOGGER = logging.getLogger(__name__)


def normalize_host(raw: str, port: int) -> tuple[str, int] | None:
    """Turn a pasted host, URL, or host:port into a bare host and port.

    A port embedded in the input replaces `port`.

    Returns:
        The lowercased host (IPv6 without brackets) and the port, or None if
        nothing usable is left.

    """
    text = raw.strip().lower()
    # Otherwise "ws://host" would parse as the host "ws". AnkiConnect is plain http only.
    if "://" in text and not text.startswith("http://"):
        return None
    text = text.removeprefix("http://")
    try:
        host, embedded_port = _split_host_port(text)
    except ValueError:
        return None

    if not host:
        return None
    if embedded_port is not None:
        port = embedded_port
    if not 1 <= port <= 65535:
        return None
    return host, port


def _split_host_port(text: str) -> tuple[str | None, int | None]:
    """Split the authority part of a host field, raising ValueError if malformed."""
    netloc = urlsplit(f"//{text}").netloc
    # A bare IPv6 address has colons but no port, and urlsplit would read
    # its last group as one.
    if netloc.count(":") > 1 and not netloc.startswith("["):
        ipaddress.IPv6Address(netloc)
        return netloc, None
    parts = urlsplit(f"//{netloc}")
    return parts.hostname, parts.port


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
