#!/usr/bin/env bash
# Shared configuration for the E2E scripts. Source this at the top of every
# other script in this directory; each is invoked as its own step both
# locally and in .github/workflows/e2e.yml, so nothing here can rely on
# state exported by a previous script.

# Anki (desktop) and the "anki" PyPI package share one release cadence and
# collection file format; a pylib version newer than the desktop app can
# upgrade the seeded collection to a schema the desktop app then refuses.
# Keep these two moving together, and don't use "latest" for either.
export ANKI_VERSION="${ANKI_VERSION:-26.08.1}"
export ANKI_PYLIB_VERSION="${ANKI_PYLIB_VERSION:-26.8.1}"

# AnkiConnect has no versioned releases on PyPI-like infra; pin an upstream
# git tag instead of tracking a default branch, for reproducibility.
export ANKICONNECT_REF="${ANKICONNECT_REF:-25.11.9.0}"

export ANKICONNECT_PORT="${ANKICONNECT_PORT:-8765}"
export ANKI_PROFILE="${ANKI_PROFILE:-User 1}"
export ANKI_DISPLAY="${ANKI_DISPLAY:-:96}"

WORKDIR="${RUNNER_TEMP:-/tmp}/ha-anki-e2e"
mkdir -p "$WORKDIR"
export WORKDIR
export ANKI_INSTALL_DIR="${ANKI_INSTALL_DIR:-$WORKDIR/anki-install}"
export ANKI_BASE="${ANKI_BASE:-$WORKDIR/anki-base}"
export ANKICONNECT_SRC_DIR="${ANKICONNECT_SRC_DIR:-$WORKDIR/anki-connect-src}"
export ANKI_LOG="${ANKI_LOG:-$WORKDIR/anki.log}"
export ANKI_PID_FILE="${ANKI_PID_FILE:-$WORKDIR/anki.pid}"
export XVFB_PID_FILE="${XVFB_PID_FILE:-$WORKDIR/xvfb.pid}"
export ANKI_BIN="$ANKI_INSTALL_DIR/anki"
export ANKI_COLLECTION="$ANKI_BASE/$ANKI_PROFILE/collection.anki2"

# Anki's QtWebEngine review view refuses to start as root without this; a
# harmless no-op when already running as an unprivileged user. Needed for
# `act`'s default images, which run job containers as root.
export QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox"
