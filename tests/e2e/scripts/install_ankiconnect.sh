#!/usr/bin/env bash
# Places the AnkiConnect add-on into the bootstrapped profile's addons21
# directory. Run after bootstrap_profile.sh (so a fresh-profile launch never
# has to load an add-on) and before seed_collection.sh / start_anki.sh.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./env.sh

mkdir -p "$ANKI_BASE/addons21"
rm -rf "$ANKI_BASE/addons21/2055492159"
cp -r "$ANKICONNECT_SRC_DIR/plugin" "$ANKI_BASE/addons21/2055492159"

echo "AnkiConnect $ANKICONNECT_REF installed into $ANKI_BASE/addons21/2055492159"
echo "config.json:"
cat "$ANKI_BASE/addons21/2055492159/config.json"
