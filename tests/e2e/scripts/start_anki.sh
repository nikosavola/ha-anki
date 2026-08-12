#!/usr/bin/env bash
# Launches the seeded Anki profile for real, with AnkiConnect now installed,
# and waits for it to start answering HTTP requests. PIDs are written to
# files so stop_anki.sh can clean up from a separate step/shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./env.sh

Xvfb "$ANKI_DISPLAY" -screen 0 1280x1024x24 -nolisten tcp &
echo $! > "$XVFB_PID_FILE"
sleep 1

export DISPLAY="$ANKI_DISPLAY"
"$ANKI_BIN" -b "$ANKI_BASE" -p "$ANKI_PROFILE" > "$ANKI_LOG" 2>&1 &
echo $! > "$ANKI_PID_FILE"

echo "Waiting for AnkiConnect on port $ANKICONNECT_PORT..."
if ! timeout 60 bash -c "
  until curl -sf -X POST http://127.0.0.1:$ANKICONNECT_PORT \
      -d '{\"action\": \"version\", \"version\": 6}' > /dev/null; do
    sleep 2
  done
"; then
  echo "AnkiConnect never became ready. Anki log:" >&2
  cat "$ANKI_LOG" >&2
  exit 1
fi

echo "AnkiConnect is up on port $ANKICONNECT_PORT."
