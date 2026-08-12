#!/usr/bin/env bash
# Installs the system libraries Anki's Qt6 build needs under Xvfb, downloads
# and extracts the pinned Anki desktop release, and clones the pinned
# AnkiConnect source (staged, not yet placed into an Anki profile).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./env.sh

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
fi

$SUDO apt-get update -qq
$SUDO apt-get install -y -qq \
  xvfb curl zstd git xdotool mpv \
  libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-randr0 libxcb-render-util0 libxcb-xinerama0 libxcb-shape0 libxcb-shm0 \
  libglib2.0-0 libgl1 libegl1 libfontconfig1 libdbus-1-3 libxrandr2 libxi6 \
  libxcomposite1 libxdamage1 libxfixes3 libxrender1 libxtst6 libnspr4 libnss3
# Anki's audio setup crashes on startup (not a graceful "no player found"
# fallback) if neither mpv nor mplayer is on PATH, even though this test
# collection never plays any audio.
# libasound2's package name changed (libasound2t64) on newer Ubuntu; try both.
$SUDO apt-get install -y -qq libasound2t64 || $SUDO apt-get install -y -qq libasound2

rm -rf "$ANKI_INSTALL_DIR"
mkdir -p "$ANKI_INSTALL_DIR"
curl -sL -o "$WORKDIR/anki.tar.zst" \
  "https://github.com/ankitects/anki/releases/download/${ANKI_VERSION}/anki-${ANKI_VERSION}-linux-x86_64.tar.zst"
tar --zstd -xf "$WORKDIR/anki.tar.zst" -C "$ANKI_INSTALL_DIR" --strip-components=1
rm "$WORKDIR/anki.tar.zst"

rm -rf "$ANKICONNECT_SRC_DIR"
git clone --quiet --depth 1 --branch "$ANKICONNECT_REF" \
  https://git.sr.ht/~foosoft/anki-connect "$ANKICONNECT_SRC_DIR"

echo "Anki $ANKI_VERSION installed to $ANKI_INSTALL_DIR"
echo "AnkiConnect $ANKICONNECT_REF cloned to $ANKICONNECT_SRC_DIR"
