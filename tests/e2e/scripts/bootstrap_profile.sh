#!/usr/bin/env bash
# Launches Anki once against an empty base directory to create a fresh
# profile and collection.anki2, then stops it again. AnkiConnect isn't
# installed yet at this point (see install_ankiconnect.sh); this step only
# exists to get past Anki's two unavoidable first-run dialogs.
#
# A brand-new profile always shows a language picker, and confirming a
# non-English choice pops a second "are you sure" dialog; English is already
# the highlighted default here, so Enter plus one confirmation clears both.
# There is no supported flag to skip this, so it's done with synthetic key
# presses instead of user interaction.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./env.sh

rm -rf "$ANKI_BASE"
mkdir -p "$ANKI_BASE"

Xvfb "$ANKI_DISPLAY" -screen 0 1280x1024x24 -nolisten tcp &
xvfb_pid=$!
sleep 1

export DISPLAY="$ANKI_DISPLAY"
"$ANKI_BIN" -b "$ANKI_BASE" -p "$ANKI_PROFILE" > "$ANKI_LOG" 2>&1 &
anki_pid=$!

sleep 5
xdotool key Return
sleep 3
xdotool key alt+y

echo "Waiting for the profile to initialize..."
for _ in $(seq 1 30); do
  [[ -f "$ANKI_COLLECTION" ]] && break
  sleep 1
done

if [[ ! -f "$ANKI_COLLECTION" ]]; then
  echo "collection.anki2 never appeared; Anki log:" >&2
  cat "$ANKI_LOG" >&2
  kill "$anki_pid" "$xvfb_pid" 2>/dev/null || true
  exit 1
fi

kill "$anki_pid" 2>/dev/null || true
wait "$anki_pid" 2>/dev/null || true
kill "$xvfb_pid" 2>/dev/null || true

echo "Profile bootstrapped at $ANKI_BASE"
