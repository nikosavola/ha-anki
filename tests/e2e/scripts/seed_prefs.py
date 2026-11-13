"""Write Anki's prefs21.db so a fresh profile opens without first-run dialogs.

Without prefs21.db Anki shows its language picker (qt/aqt/profiles.py, _loadMeta). The
defaults below copy what Anki 26.08.1 writes itself.
Usage: seed_prefs.py <base dir> <profile name>
"""

from pathlib import Path
import pickle  # ruff: ignore[suspicious-pickle-import]  # Anki stores its profile prefs as pickles
import random
import sqlite3
import sys
import time


def main(base: str, profile: str) -> None:
    """Create prefs21.db under base with a global entry and one profile."""
    base_dir = Path(base)
    base_dir.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    meta = {
        "ver": 0,
        "updates": False,
        "created": now,
        "id": random.randrange(0, 2**63),  # ruff: ignore[suspicious-non-cryptographic-random-usage]
        "lastMsg": 0,
        "suppressUpdate": False,
        "firstRun": False,
        "defaultLang": "en_US",
        "check_for_updates": False,
    }
    prof = {
        "mainWindowGeom": None,
        "mainWindowState": None,
        "numBackups": 50,
        "lastOptimize": now,
        "searchHistory": [],
        "syncKey": None,
        "syncMedia": True,
        "autoSync": False,
        "allowHTML": False,
        "importMode": 1,
        "lastColour": "#00f",
        "stripHTML": True,
        "deleteMedia": False,
    }
    con = sqlite3.connect(base_dir / "prefs21.db")
    con.execute(
        "create table if not exists profiles "
        "(name text primary key collate nocase, data blob not null)"
    )
    for name, data in (("_global", meta), (profile, prof)):
        con.execute(
            "insert or replace into profiles values (?, ?)",
            (name, pickle.dumps(data, protocol=4)),
        )
    con.commit()
    con.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
