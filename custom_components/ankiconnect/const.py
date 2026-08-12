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

# Not a findCards query; fetched via getNumCardsReviewedToday instead.
REVIEWED_TODAY_KEY = "reviewed_today"

# All sensor keys, in the order entities are created.
SENSOR_KEYS = (*CARD_QUERIES, REVIEWED_TODAY_KEY)

SYNC_SERVICE = "sync"
