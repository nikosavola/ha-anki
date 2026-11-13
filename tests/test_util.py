"""Tests for the ha-anki helper functions."""

import pytest

from custom_components.ha_anki.util import normalize_host


@pytest.mark.parametrize(
    ("raw", "port", "expected"),
    [
        pytest.param(
            "http://192.168.1.20:8765", 8765, ("192.168.1.20", 8765), id="url"
        ),
        pytest.param("192.168.1.20:8765", 8765, ("192.168.1.20", 8765), id="host-port"),
        pytest.param(
            "192.168.1.20:8765/", 8765, ("192.168.1.20", 8765), id="trailing-slash"
        ),
        pytest.param(" MyPC.local ", 8765, ("mypc.local", 8765), id="whitespace"),
        pytest.param("192.168.1.20", 9000, ("192.168.1.20", 9000), id="port-field"),
        pytest.param("https://x/path", 8765, None, id="https-rejected"),
        pytest.param("ws://192.168.1.20", 8765, None, id="ws-rejected"),
        pytest.param("http://mypc.local", 8765, ("mypc.local", 8765), id="url-no-port"),
        pytest.param(
            "http://mypc.local:9000",
            8765,
            ("mypc.local", 9000),
            id="embedded-port-wins",
        ),
        pytest.param("[fe80::1]:8765", 8765, ("fe80::1", 8765), id="ipv6-bracket-port"),
        pytest.param("[fe80::1]", 8765, ("fe80::1", 8765), id="ipv6-bracket"),
        pytest.param("fe80::1", 8765, ("fe80::1", 8765), id="ipv6-bare"),
        pytest.param("", 8765, None, id="empty"),
        pytest.param("   ", 8765, None, id="blank"),
        pytest.param("http://", 8765, None, id="scheme-only"),
        pytest.param("host:abc", 8765, None, id="non-numeric-port"),
        pytest.param("host:99999", 8765, None, id="port-too-high"),
        pytest.param("host:0", 8765, None, id="port-zero"),
        pytest.param("[fe80::1", 8765, None, id="unclosed-bracket"),
    ],
)
def test_normalize_host(raw: str, port: int, expected: tuple[str, int] | None) -> None:
    """Pasted hosts and URLs reduce to a bare host and port, or None if unusable."""
    assert normalize_host(raw, port) == expected
