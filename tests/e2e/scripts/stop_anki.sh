#!/usr/bin/env bash
# Stops the Anki + Xvfb processes started by start_anki.sh. Safe to run even
# if they're already gone (e.g. a prior step failed before starting them).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./env.sh

for pid_file in "$ANKI_PID_FILE" "$XVFB_PID_FILE"; do
  if [ -f "$pid_file" ]; then
    kill "$(cat "$pid_file")" 2>/dev/null || true
    rm -f "$pid_file"
  fi
done

echo "Stopped."
