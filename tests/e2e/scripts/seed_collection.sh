#!/usr/bin/env bash
# Runs seed_collection.py with the pinned "anki" pylib version, isolated from
# this project's own dependency environment (anki pulls in a large, separate
# dependency set that has no business in pyproject.toml/uv.lock).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./env.sh

uv run --no-project --with "anki==${ANKI_PYLIB_VERSION}" python seed_collection.py "$ANKI_COLLECTION"
