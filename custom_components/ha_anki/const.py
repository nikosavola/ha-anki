"""Constants for the ha-anki integration."""

from datetime import timedelta

DOMAIN = "ha_anki"

DEFAULT_PORT = 8765

UPDATE_INTERVAL = timedelta(minutes=5)

MIN_SCAN_INTERVAL_MINUTES = 1
MAX_SCAN_INTERVAL_MINUTES = 1440

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

# Prefix for user-defined query sensor keys, so they can never collide with
# the fixed SENSOR_KEYS namespace above.
CUSTOM_QUERY_KEY_PREFIX = "custom_"

# entry.options key holding user-defined queries, keyed by slug:
# {slug: {CONF_NAME: str, CONF_QUERY: str}}.
CONF_CUSTOM_QUERIES = "custom_queries"
CONF_QUERY = "query"

SYNC_SERVICE = "sync"
ADD_NOTE_SERVICE = "add_note"

# add_note is a domain service, not an entity service: it mutates the
# collection, so it must run exactly once per call, which an entity service
# targeting a device or multiple entities can't guarantee.
CONF_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_DECK_NAME = "deck_name"
ATTR_MODEL_NAME = "model_name"
ATTR_FIELDS = "fields"
ATTR_TAGS = "tags"
ATTR_ALLOW_DUPLICATE = "allow_duplicate"
