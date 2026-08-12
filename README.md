![ha-anki](custom_components/ha_anki/brand/logo.svg)

[![Test](https://github.com/nikosavola/ha-anki/actions/workflows/test.yml/badge.svg)](https://github.com/nikosavola/ha-anki/actions/workflows/test.yml)
[![E2E](https://github.com/nikosavola/ha-anki/actions/workflows/e2e.yml/badge.svg)](https://github.com/nikosavola/ha-anki/actions/workflows/e2e.yml)
[![Validate](https://github.com/nikosavola/ha-anki/actions/workflows/validate.yml/badge.svg)](https://github.com/nikosavola/ha-anki/actions/workflows/validate.yml)
[![codecov](https://codecov.io/gh/nikosavola/ha-anki/graph/badge.svg)](https://codecov.io/gh/nikosavola/ha-anki)
[![License: Apache 2.0](https://img.shields.io/github/license/nikosavola/ha-anki)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/nikosavola/ha-anki)](https://github.com/nikosavola/ha-anki/releases)

______________________________________________________________________

Home Assistant custom integration that exposes [Anki](https://apps.ankiweb.net/) card
counts as sensors, via the [AnkiConnect](https://ankiweb.net/shared/info/2055492159)
add-on. Anki must be running with AnkiConnect installed and reachable over the local
network; this integration only polls its local HTTP API, it doesn't talk to AnkiWeb.

## Requirements

- Anki desktop, running, with the AnkiConnect add-on installed
- AnkiConnect reachable from Home Assistant over the network (default port `8765`)

Anki has to actually be running for AnkiConnect to answer, which usually means it's
running on someone's desktop. To run it unattended on a server instead, with no monitor,
starting on boot, and syncing to AnkiWeb on a schedule, see
[Running Anki on a headless server](#running-anki-on-a-headless-server) below.

## Installation

### HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=nikosavola&repository=ha-anki&category=integration)

1. Add this repository to HACS as a custom repository of type *Integration* (the badge
   above does this for you), then download **ha-anki** from HACS.
1. Restart Home Assistant.

### Manual

Copy `custom_components/ha_anki` into your Home Assistant `config/custom_components`
directory and restart Home Assistant.

## Configuration

Go to **Settings → Devices & services → Add integration**, pick **ha-anki**, and
enter the host and port of the machine running Anki. Home Assistant polls that host
every 5 minutes; it does not fetch on demand, so multiple sensors never generate
duplicate requests.

## Supported functionality

One config entry polls AnkiConnect once per interval, batched into a single
`multi` request, and exposes four sensors:

| Sensor         | AnkiConnect action             |
| -------------- | ------------------------------ |
| Cards due      | `findCards`, query `is:due`    |
| New cards      | `findCards`, query `is:new`    |
| Review cards   | `findCards`, query `is:review` |
| Reviewed today | `getNumCardsReviewedToday`     |

### Custom query sensors

Beyond those four, you can add a sensor for any AnkiConnect search query from
**Settings → Devices & services → ha-anki → Configure**. It's the same
query syntax as Anki's own card browser, documented in full at
[docs.ankiweb.net/searching.html](https://docs.ankiweb.net/searching.html);
AnkiConnect just runs it through `findCards` and counts the results, the same
as the built-in sensors above. Each custom query becomes its own sensor,
polled and batched alongside the built-in four, and can be removed later from
the same Configure dialog.

A query is scoped to a deck, tag, or anything else Anki's search supports by
combining terms, for example:

| Name        | Query                 |
| ----------- | --------------------- |
| Spanish due | `deck:Spanish is:due` |
| Leeches     | `tag:leech`           |
| Suspended   | `is:suspended`        |
| Added today | `added:1`             |

### Services

- `ha_anki.sync`, targeted at any one of this integration's sensors, asks
  AnkiConnect to sync with AnkiWeb, then immediately refreshes sensor state
  instead of waiting for the next poll. It's an entity service, so target
  exactly one sensor; targeting several (or a whole device) runs it once per
  targeted entity.

- `ha_anki.add_note` creates a new note via AnkiConnect's
  [`addNote`](https://git.sr.ht/~foosoft/anki-connect#codeaddnotecode) action
  (see the [supported actions](https://git.sr.ht/~foosoft/anki-connect#supported-actions)
  list on that same page for the full reference, including note types,
  fields, and duplicate handling), then refreshes sensor state and returns
  the new note's ID as `{"note_id": ...}`. Unlike `sync`, it's a plain action
  picking the AnkiConnect instance via a `config_entry_id` field instead of
  an entity target, since it mutates the collection and must run exactly
  once per call. Combined with Home Assistant's
  [AI Task](https://www.home-assistant.io/integrations/ai_task/) structured
  data generation, this turns arbitrary text into a flashcard automatically:

  ```yaml
  sequence:
    - action: ai_task.generate_data
      data:
        task_name: "Anki flashcard"
        instructions: >-
          Turn this into a concise Anki flashcard, front and back:
          "Mitochondria are the powerhouse of the cell."
        structure:
          front:
            selector:
              text:
            description: The flashcard's front (question) side.
          back:
            selector:
              text:
            description: The flashcard's back (answer) side.
      response_variable: flashcard
    - action: ha_anki.add_note
      data:
        config_entry_id: <pick the AnkiConnect entry in the UI>
        deck_name: Default
        model_name: Basic
        fields:
          Front: "{{ flashcard.data.front }}"
          Back: "{{ flashcard.data.back }}"
  ```

  Wire that sequence into a script or automation, e.g. triggered by a voice
  assistant intent or a note-taking shortcut, so a snippet of text becomes a
  card without opening Anki.

## Known limitations

- **Local network only.** AnkiConnect has no authentication beyond an optional origin
  allowlist, so only point this integration at an AnkiConnect instance on a network you
  trust.
- **Anki must be running.** AnkiConnect is an Anki add-on, not a standalone service; if
  Anki is closed, the sensors go unavailable until it's reopened.

## Running Anki on a headless server

This integration polls a running Anki desktop process through AnkiConnect; it doesn't run
Anki itself. If you don't already have Anki open on a machine on your network, this section
covers running it unattended on a Linux server: no monitor, no login session, syncing to
AnkiWeb on its own. "Headless" here means "running against a virtual display", since Anki is
a desktop (Qt) app with no dedicated headless mode.

The [Docker alternative](#docker-alternative) below is the faster path if you don't need
fine-grained control over the systemd units.

### Overview

1. Install Anki and a virtual display (Xvfb).
1. Install the AnkiConnect add-on.
1. Configure AnkiConnect to accept connections from your LAN.
1. Log in to AnkiWeb once, interactively, so sync credentials are cached.
1. Run Anki under systemd, restarting automatically if it crashes.
1. Add a systemd timer that periodically calls AnkiConnect's `sync` action, so the
   collection stays up to date with AnkiWeb without you opening Anki.

### 1. Install Anki and Xvfb

```bash
sudo apt update
sudo apt install xvfb libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 \
  libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
  libxcb-xinerama0
```

A system Anki package is often outdated; the
[official Linux install script](https://docs.ankiweb.net/platform/linux/installing.html)
installs the latest release to `/usr/local/bin/anki`. Releases are published per
architecture (`anki-<version>-linux-x86_64.tar.zst` or `-aarch64.tar.zst`, e.g. on a
Raspberry Pi), so resolve the right asset instead of hardcoding a filename:

```bash
arch=$(uname -m)
asset=$(curl -s https://api.github.com/repos/ankitects/anki/releases/latest \
  | grep -o "anki-[0-9.]*-linux-${arch}\.tar\.zst" | head -1)
curl -LO "https://github.com/ankitects/anki/releases/latest/download/${asset}"
tar --zstd -xf "$asset"
cd anki-*
sudo ./install.sh
```

If your architecture isn't `x86_64`, check first that Anki even publishes a compatible
build: as of this writing, Anki's aarch64 release needs glibc 2.39+, which recent
Debian/Ubuntu have but Debian 12 "bookworm"-based systems (including current Raspberry Pi
OS and DietPi) don't. `ldd --version` shows what you have. If it's too old, pin an older
`aqt`/`anki` release built against an older PyQt6 (see
[this issue](https://github.com/ankitects/anki/issues/4167)) instead of the packaged
binary:

```bash
sudo -u anki python3 -m venv /var/lib/anki/venv
sudo -u anki /var/lib/anki/venv/bin/pip install \
  anki==24.11 "aqt[qt6]==24.11" \
  PyQt6==6.7.1 PyQt6-Qt6==6.7.3 PyQt6-WebEngine==6.7.0 PyQt6-WebEngine-Qt6==6.7.3
```

That installs an `anki` launcher into the venv's `bin/`; use
`/var/lib/anki/venv/bin/anki` in place of `/usr/local/bin/anki` in step 5 below. You may
also need a few runtime libraries the wheels expect that your distro ships under a newer
soname (for example `libwebp.so.6`/`libtiff.so.5` on bookworm, symlinked to the installed
`libwebp.so.7`/`libtiff.so.6`); install what `ldd` on
`.../PyQt6/Qt6/lib/libQt6WebEngineCore.so.6` reports missing.

Then create a dedicated, unprivileged user to run it as:

```bash
sudo useradd --system --create-home --home-dir /var/lib/anki --shell /usr/sbin/nologin anki
```

### 2. Install the AnkiConnect add-on

AnkiConnect is add-on code [2055492159](https://ankiweb.net/shared/info/2055492159). Since
it's just Python source, place it directly without ever opening a GUI. The add-on itself
lives in the repository's `plugin/` subdirectory, not the repository root, so clone
somewhere temporary first and copy that subdirectory into place:

```bash
sudo -u anki mkdir -p /var/lib/anki/.local/share/Anki2/addons21
sudo -u anki git clone --branch 25.11.9.0 --depth 1 \
  https://git.sr.ht/~foosoft/anki-connect /tmp/anki-connect-src
sudo -u anki cp -r /tmp/anki-connect-src/plugin \
  /var/lib/anki/.local/share/Anki2/addons21/2055492159
sudo rm -rf /tmp/anki-connect-src
```

Pin a tag rather than tracking the branch: AnkiConnect's `main` branch is developed
against whatever Python version current Anki bundles, which can be newer than what your
Anki install actually uses (a syntax error importing the add-on, rather than a runtime
error, is the symptom). `25.11.9.0` is the tag this project's own end-to-end tests pin;
newer tags should work too as long as your Anki meets the tag's own minimum version check
in its `__init__.py`.

(Or install it through **Tools → Add-ons → Get Add-ons...** during the VNC session in step 4,
if you'd rather use the GUI.)

### 3. Configure AnkiConnect for LAN access

By default AnkiConnect binds to `127.0.0.1`, so nothing off the machine, including Home
Assistant, can reach it. Edit (or create)
`/var/lib/anki/.local/share/Anki2/addons21/2055492159/config.json`:

```json
{
  "apiKey": null,
  "apiLogPath": null,
  "webBindAddress": "0.0.0.0",
  "webBindPort": 8765,
  "webCorsOriginList": ["http://localhost"],
  "ignoreOriginList": []
}
```

`webBindAddress: 0.0.0.0` makes the port reachable from other hosts. There is no built-in
access control beyond `webCorsOriginList` (which only affects browser-originated requests, not
this integration's server-side ones) and the optional `apiKey`, so firewall the port to only
the Home Assistant host and don't expose it to the internet or an untrusted VLAN:

```bash
sudo ufw allow from <home-assistant-ip> to any port 8765 proto tcp
```

This matches the [Known limitations](#known-limitations) note above.

### 4. Log in to AnkiWeb once, interactively

AnkiConnect's `sync` action just calls Anki's normal sync, which needs an AnkiWeb account
already configured in the profile. That login only has to happen once: Anki caches the auth
token in the profile afterward, so later syncs, including ones triggered headlessly over the
API, don't prompt again. Do it over a temporary VNC session:

```bash
sudo apt install tigervnc-standalone-server openbox
sudo -u anki bash -c '
  vncserver :1 -geometry 1280x1024 -localhost yes
  DISPLAY=:1 openbox &
  DISPLAY=:1 anki &
'
```

SSH-tunnel to it (`ssh -L 5901:localhost:5901 your-server`), connect a VNC client to
`localhost:5901`, log in from Anki's **Sync** menu, and let the initial sync finish. Then close
Anki, kill the VNC server (`vncserver -kill :1`), and remove `tigervnc-standalone-server` and
`openbox`; they're only needed for this one-time login.

If you set up systemd (step 5) before doing this, or need to log in again later (e.g. after
changing your AnkiWeb password), it's simpler to share the already-running `xvfb-anki.service`
display instead of starting a separate one: `sudo apt install x11vnc`, then
`sudo -u anki x11vnc -display :99 -localhost -nopw -forever` and tunnel to port `5900` the
same way. Stop it (`Ctrl+C`, or `sudo pkill x11vnc`) once you're done logging in.

### 5. Run Anki under systemd

Two units, so systemd tracks the virtual display alongside Anki instead of it being an
untracked background process:

```ini
# /etc/systemd/system/xvfb-anki.service
[Unit]
Description=Virtual display for headless Anki

[Service]
User=anki
Group=anki
ExecStart=/usr/bin/Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/anki.service
[Unit]
Description=Anki (headless, for AnkiConnect)
After=network-online.target xvfb-anki.service
Requires=xvfb-anki.service
Wants=network-online.target

[Service]
User=anki
Group=anki
Environment=HOME=/var/lib/anki
Environment=DISPLAY=:99
ExecStart=/usr/local/bin/anki -b /var/lib/anki/.local/share/Anki2
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now xvfb-anki.service anki.service
```

Confirm AnkiConnect answers, from the Home Assistant host:

```bash
curl -s http://<anki-server-ip>:8765 -X POST -d '{"action": "version", "version": 6}'
# {"result": 6, "error": null}
```

If that hangs or refuses, check the firewall rule from step 3 and `sudo journalctl -u anki.service` for startup errors (a missing Qt xcb dependency shows up here as "could not
load the Qt platform plugin"). A lighter alternative to Xvfb is
`Environment=QT_QPA_PLATFORM=offscreen` on `anki.service`, dropping `xvfb-anki.service`
entirely, but it's less exercised for long-running Anki processes; fall back to Xvfb if
dialogs or first-run flows behave oddly.

### 6. Sync to AnkiWeb periodically in the background

Anki normally syncs on open/close, which never happens for a service that just keeps running.
Trigger it on a schedule instead by calling AnkiConnect's own `sync` action with a systemd
timer:

```ini
# /etc/systemd/system/anki-sync.service
[Unit]
Description=Trigger an AnkiConnect sync to AnkiWeb

[Service]
Type=oneshot
ExecStart=/usr/bin/curl -sf -X POST http://localhost:8765 \
  -d '{"action": "sync", "version": 6}'
```

```ini
# /etc/systemd/system/anki-sync.timer
[Unit]
Description=Periodically trigger an AnkiConnect sync

[Timer]
OnBootSec=5min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now anki-sync.timer
```

Adjust `OnUnitActiveSec` to taste: 30 minutes keeps due/new counts reasonably fresh without
syncing on every review. `sync` briefly blocks the collection while it runs, so don't set this
shorter than AnkiConnect's own polling in Home Assistant (5 minutes).

### Docker alternative

Community Docker images bundle Anki, a virtual display, and AnkiConnect together, trading
some control over the setup for a single `docker run`:

```bash
docker run -d \
  -p 8765:8765 \
  -v anki-data:/data \
  thisisnttheway/headless-anki:latest
```

This is [`thisisnttheway/headless-anki`](https://github.com/ThisIsntTheWay/headless-anki);
[`ankimcp/headless-anki`](https://github.com/ankimcp/headless-anki) is a similar alternative.
`-v anki-data:/data` persists the Anki profile, and once logged in, the AnkiWeb auth token,
across container restarts and recreations; without it, every recreation starts from the
image's barebones default profile again.

The step 3 firewalling advice above still applies to the container's published `8765`.

#### Authentication

This image has no environment variable for AnkiWeb credentials: logging in works exactly like
step 4 above, just over the image's own built-in VNC server instead of a throwaway one. By
default it runs Anki under `QT_QPA_PLATFORM=vnc`, listening on port `5900`.

1. Add `-p 5900:5900` to the `docker run` above (or bind it to `127.0.0.1` and SSH-tunnel in,
   same caveat as step 4).
1. Connect a VNC client to `<host>:5900`, log in from Anki's **Sync** menu, and let the
   initial sync finish.
1. The auth token is now cached in `/data`, kept by the `anki-data` volume. Stop publishing
   `5900` if you only opened it for this.

AnkiConnect on port `8765` and the `ha_anki.sync` service behave exactly as described
above from here, since it's the same Anki + AnkiConnect stack underneath.

If you bring your own existing profile instead (`-v ~/.local/share/Anki2:/data`), its
AnkiConnect config may still be bound to `localhost` or have a restrictive CORS list from
desktop use: add `-e ANKICONNECT_WILDCARD_ORIGIN=1` to reset `webCorsOriginList` to `["*"]`
(the image backs up your existing `config.json` first), and check `webBindAddress` per step 3.

## Testing

`uv run --dev pytest` runs the regular unit test suite, which mocks
AnkiConnect's HTTP responses. There's also an end-to-end suite that runs the
integration against a real, disposable Anki + AnkiConnect instance instead,
including how to run the `e2e` GitHub Actions workflow locally with
[`act`](https://github.com/nektos/act) before pushing. See
[CONTRIBUTING.md](CONTRIBUTING.md#testing) for both.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines, and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community expectations. Found a
security issue? See [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Versioning

Version numbers follow [ZeroVer](https://0ver.org/): the major version stays at 0
indefinitely, so a 0.y bump can carry breaking changes.
