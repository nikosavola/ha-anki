#!/usr/bin/env bash
# Runs the full E2E setup locally: installs Anki + AnkiConnect, seeds a test
# collection, starts Anki, and leaves it running for `pytest tests/e2e
# --run-e2e` (or manual `curl` poking). Mirrors .github/workflows/e2e.yml
# step for step; run stop_anki.sh when done.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

./install_anki.sh
./bootstrap_profile.sh
./install_ankiconnect.sh
./seed_collection.sh
./start_anki.sh

source ./env.sh
echo
echo "Anki + AnkiConnect are running on 127.0.0.1:${ANKICONNECT_PORT}."
echo "Run the E2E suite with:"
echo "  uv run --dev pytest tests/e2e --run-e2e -v"
echo "Stop everything with:"
echo "  tests/e2e/scripts/stop_anki.sh"
