"""Fixtures for the real-AnkiConnect end-to-end test suite."""

from __future__ import annotations

import os

import pytest

E2E_HOST = os.environ.get("E2E_ANKICONNECT_HOST", "127.0.0.1")
E2E_PORT = int(os.environ.get("E2E_ANKICONNECT_PORT", "8765"))

# Must match tests/e2e/scripts/seed_collection.py's EXPECTED_NEW/EXPECTED_DUE/EXPECTED_REVIEW.
# reviewed_today is 0 because seeding writes card rows directly rather than
# going through answerCard, so it never adds a review log entry.
EXPECTED_COUNTS = {
    "cards_due": 2,
    "new_cards": 3,
    "review_cards": 3,
    "reviewed_today": 0,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading the integration from custom_components."""


@pytest.fixture(autouse=True)
def _enable_real_sockets(socket_enabled: None) -> None:
    """Allow real network access.

    pytest-homeassistant-custom-component blocks sockets by default via
    pytest-socket, since regular tests must never hit the network; these
    tests are the deliberate exception.
    """
