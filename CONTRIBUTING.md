# Contributing

## Setup

This project uses [uv](https://docs.astral.sh/uv/). There is no manual virtualenv
step: `uv run` creates and syncs `.venv` from `pyproject.toml` on demand.

```bash
uv run --dev pytest
```

The commands below are also available as [`just`](https://github.com/casey/just)
recipes; run `just --list` to see them all.

## Linting, formatting and type checking

Ruff and pyrefly aren't project dependencies; they run through
[pre-commit](https://pre-commit.com) hooks via
[`prek`](https://github.com/j178/prek), a drop-in pre-commit replacement, so the
same versions are used locally and in CI:

```bash
uvx prek run --all-files
```

Install it as a git hook so it runs automatically on every commit:

```bash
uvx prek install
```

## Testing

### Unit tests

`uv run --dev pytest` runs the suite in `tests/`, which mocks every AnkiConnect
HTTP response by hand. That only proves the integration behaves correctly against
our own assumptions about AnkiConnect's wire format, which is what the end-to-end
suite below is for.

### End-to-end tests

`tests/e2e/` runs the real `AnkiConnectClient` (and a full Home Assistant config
entry setup) against a real, disposable Anki instance with a real AnkiConnect
add-on, seeded with cards in known states. Tests there are marked `e2e` and
skipped by default (see `tests/conftest.py`), since they're slower and depend
on external downloads: pass `--run-e2e` to actually run them. There's a
separate `e2e` GitHub Actions workflow that does exactly that, rather than the
regular unit test workflow.

[`tests/e2e/scripts/seed_collection.py`](tests/e2e/scripts/seed_collection.py) creates a
"ha-anki-e2e" deck with:

- 3 brand-new cards (`is:new`)
- 2 cards forced into the review queue, due today or earlier (`is:due` and `is:review`)
- 1 card forced into the review queue, due 30 days out (`is:review` only, not due)

giving exact, non-overlapping expected counts for the cards_due/new_cards/review_cards
sensors: 2 due, 3 new, 3 review. reviewed_today is asserted as 0 too, since seeding
writes card rows directly rather than going through answerCard, so it never adds a
review log entry. The seeding script re-opens the collection and asserts these counts
itself before exiting, so a scheduler-semantics surprise fails loudly there instead of
showing up as a confusing mismatch in the pytest suite. `tests/e2e/conftest.py`'s
`EXPECTED_COUNTS` must be kept in sync with it.

The `ha_anki.sync` service isn't covered by the E2E suite: the seeded profile is
never logged in to AnkiWeb, and Anki's own sync flow can pop an interactive "please log
in" dialog in that case, which would hang the job rather than fail it cleanly.
`tests/test_sensor.py`'s mocked tests cover the service's success and error paths
instead.

The `ha_anki.add_note` service isn't covered either, for a different reason: it
mutates the collection, which would invalidate the deterministic counts
`EXPECTED_COUNTS` asserts on. It's covered by mocked tests in `tests/test_api.py` and
`tests/test_sensor.py` instead.

Run it locally:

```bash
tests/e2e/scripts/run_local.sh
uv run --dev pytest tests/e2e --run-e2e -v
tests/e2e/scripts/stop_anki.sh
```

`run_local.sh` installs Anki and AnkiConnect, bootstraps a profile, seeds the
collection, and starts Anki with AnkiConnect listening on `127.0.0.1:8765`. That's
the same steps `.github/workflows/e2e.yml` runs, in the same order, so a local
pass is a reasonable predictor of a CI pass.

Everything is installed under `${RUNNER_TEMP:-/tmp}/ha-anki-e2e`, isolated from
any real Anki installation on the machine. `install_anki.sh` runs `apt-get install` (via `sudo` if not already root) for Xvfb, Qt6's runtime libraries, and
`mpv`; it downloads the pinned Anki release and clones the pinned AnkiConnect tag
into that same temp directory, and nothing is written outside
`$RUNNER_TEMP`/`/tmp` except those system packages. Anki runs under Xvfb, so it
doesn't open a visible window.

`tests/e2e/scripts/env.sh` pins three things, all overridable via environment
variables of the same name:

- `ANKI_VERSION`: the desktop Anki release
- `ANKI_PYLIB_VERSION`: the `anki` PyPI package used only for seeding
- `ANKICONNECT_REF`: a git tag of the AnkiConnect source

`ANKI_VERSION` and `ANKI_PYLIB_VERSION` must refer to the same release, since the
pylib and the desktop app share one collection file format, and a pylib newer
than the installed desktop app can upgrade the seeded collection to a schema the
desktop app then refuses to open. Bump them together. AnkiConnect has no
PyPI-style releases, so its ref is a plain git tag from its
[sourcehut repository](https://git.sr.ht/~foosoft/anki-connect) instead of a
tracked branch, for reproducibility.

### Validating the E2E workflow with `act`

[`nektos/act`](https://github.com/nektos/act) runs GitHub Actions workflows
locally in Docker, which is a good way to validate `.github/workflows/e2e.yml`
end to end, including a fresh apt/Anki/AnkiConnect install, before pushing:

```bash
act -j e2e -P ubuntu-latest=catthehacker/ubuntu:act-latest --container-architecture linux/amd64
```

Notes specific to this workflow:

- The default (small) `act` runner image lacks `apt-get`'s package lists and
  `sudo`; use the `catthehacker/ubuntu:act-latest` image as above, which has
  both.
- `act`'s job containers run as root by default, unlike a real GitHub-hosted
  runner (which runs as an unprivileged `runner` user with passwordless
  `sudo`). Anki's Qt WebEngine review view refuses to start as root without
  `--no-sandbox`; `tests/e2e/scripts/env.sh` always sets
  `QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox`, which is a harmless no-op when
  already unprivileged, so the same scripts work in both.
- `act` won't reproduce a real runner's preinstalled state, so `apt-get` steps
  that would be fast no-ops on GitHub's own runners actually install packages
  here. That's expected, not a bug in the workflow.
- On Apple Silicon or other non-x86_64 hosts, `--container-architecture linux/amd64` is required, since the Anki release is only published for
  `x86_64`/`aarch64`, and act's images are amd64.

## Before opening a pull request

- `uv run --dev pytest` and `uvx prek run --all-files` both pass.
- Keep commits atomic: one logical change per commit, with an imperative-mood
  message ("Add x", not "Added x" or "Adds x").
- New behavior gets a test; a bug fix gets a regression test.
- If you change `strings.json`, update `translations/en.json` to match, so the two
  don't drift apart. Other locales don't need to track every change immediately.

## Adding a translation

Copy `custom_components/ha_anki/translations/en.json` to
`<language-code>.json` in the same directory and translate the values, keeping the
keys identical. [Supported language codes are listed in Home Assistant's developer
docs](https://developers.home-assistant.io/docs/internationalization/translation/#getting-started).

## AI usage policy

Using AI tools to accelerate your workflow, whether for prototyping, writing tests, or
improving documentation, is **encouraged**.

However, as a contributor, you remain **fully responsible** for the code and content
you submit. Please ensure the following:

1. **No "AI slop"**: don't submit unreviewed, low-quality, or redundant AI-generated
   content.
1. **Verify and test**: all AI-generated code must be reviewed, tested, and verified
   to work as intended.
1. **Maintainability**: the content must be clear, idiomatic, and maintainable by a
   human.
