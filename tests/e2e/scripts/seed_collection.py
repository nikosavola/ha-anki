"""Seed a fresh Anki collection with cards in known scheduling states.

Runs against the collection file directly via the `anki` pylib package,
while Anki itself is not running (see seed_collection.sh, which pins the
pylib version to match the desktop app and is what actually gets invoked).

Produces, in a dedicated "ha-anki-e2e" deck:
- 3 brand-new cards (is:new)
- 2 cards forced into the review queue, due today or earlier (is:due, is:review)
- 1 card forced into the review queue, due 30 days out (is:review only)

These counts are asserted here immediately after seeding, and are also
hardcoded as EXPECTED_COUNTS in tests/e2e/conftest.py -- if you change one,
change the other.
"""

from __future__ import annotations

import sys

from anki.collection import Collection

QUEUE_TYPE_REV = 2
CARD_TYPE_REV = 2

EXPECTED_NEW = 3
EXPECTED_DUE = 2
EXPECTED_REVIEW = 3


def _add_note(col: Collection, deck_id: int, front: str):
    model = col.models.by_name("Basic")
    note = col.new_note(model)
    note["Front"] = front
    note["Back"] = "back"
    col.add_note(note, deck_id)
    return note


def _force_review_state(col: Collection, note, *, ivl: int, due: int) -> None:
    (card_id,) = note.card_ids()
    card = col.get_card(card_id)
    card.queue = QUEUE_TYPE_REV
    card.type = CARD_TYPE_REV
    card.ivl = ivl
    card.due = due
    col.update_card(card)


def seed(path: str) -> None:
    """Populate the collection at `path` and verify the resulting card counts."""
    col = Collection(path)
    deck_id = col.decks.id("ha-anki-e2e", create=True)

    for i in range(EXPECTED_NEW):
        _add_note(col, deck_id, f"new {i}")

    for i in range(EXPECTED_DUE):
        # due=0 is always <= "today" (day 0) for a freshly created collection.
        _force_review_state(col, _add_note(col, deck_id, f"due {i}"), ivl=10, due=0)

    _force_review_state(col, _add_note(col, deck_id, "future review"), ivl=30, due=30)

    col.close()

    # Re-open and verify: a scheduler-semantics surprise should fail loudly
    # here, not show up as a confusing mismatch in the pytest suite later.
    col = Collection(path)
    counts = {
        "is:new": len(col.find_cards("is:new")),
        "is:due": len(col.find_cards("is:due")),
        "is:review": len(col.find_cards("is:review")),
    }
    col.close()

    print(f"Seeded collection at {path}: {counts}")
    expected = {
        "is:new": EXPECTED_NEW,
        "is:due": EXPECTED_DUE,
        "is:review": EXPECTED_REVIEW,
    }
    if counts != expected:
        msg = f"Seeded collection doesn't match expectations: got {counts}, expected {expected}"
        raise AssertionError(msg)


if __name__ == "__main__":
    seed(sys.argv[1])
