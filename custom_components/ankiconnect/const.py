"""Constants for the AnkiConnect integration."""

from datetime import timedelta

DOMAIN = "ankiconnect"

DEFAULT_PORT = 8765

UPDATE_INTERVAL = timedelta(minutes=5)

ANKICONNECT_API_VERSION = 6

# Sensor keys, also used as translation keys, mapped to their findCards query.
CARD_QUERIES = {
    "cards_due": "is:due",
    "new_cards": "is:new",
    "review_cards": "is:review",
}
