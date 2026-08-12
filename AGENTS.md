# AGENTS.md

ha-anki is a Home Assistant custom integration (`custom_components/ha_anki`, domain `ha_anki`)
that polls a local Anki desktop's AnkiConnect add-on over HTTP. There is no other component or
service in this repo.

## Commands

Python and dependencies are managed by [uv](https://docs.astral.sh/uv/); there is no manual
virtualenv step, `uv run` creates and syncs one from `pyproject.toml` on demand.

- Unit tests: `uv run --dev pytest`
- Lint, format, and type-check (ruff, pyrefly, codespell, yamllint, markdownlint, and more, all
  pinned in `.pre-commit-config.yaml`): `uvx prek run --all-files`

Both must pass before a change is done. Real-Anki end-to-end tests live in `tests/e2e/` and are
skipped by default; they need `--run-e2e` plus a real running Anki + AnkiConnect instance, so
don't try to run them as part of a normal edit-test loop, and don't treat their absence from a
`pytest` run as a gap in coverage.

## Code layout

- `custom_components/ha_anki/api.py`: `AnkiConnectClient`, the only place that speaks HTTP to
  AnkiConnect. Every failure surfaces as an `AnkiConnectError` subclass; catch those, not raw
  `aiohttp` exceptions.
- `coordinator.py`: the `DataUpdateCoordinator` that polls once per interval, batched into a
  single `multi` request.
- `config_flow.py`: the initial setup flow, plus `AnkiConnectOptionsFlow` for user-defined query
  sensors.
- `sensor.py`: entity definitions and entity-scoped services.
- `__init__.py`: config entry setup/teardown, plus any domain-wide (non-entity) services.
- `const.py`: every constant key and service/attribute name. Add new ones here instead of
  inlining string literals that duplicate them.
- `strings.json` and `translations/en.json` must stay identical whenever either changes; other
  locale files don't need to track every change immediately.

## Entity services vs. domain services

A Home Assistant entity service (registered via `platform.async_register_entity_service`) runs
once per targeted entity, concurrently, when a user targets a device or several entities at once.
That's acceptable for a read-only or idempotent action, but not for one that mutates external
state and must run exactly once per call: those must be a domain service instead (registered with
`hass.services.async_register` from `async_setup`), taking an explicit `config_entry_id` field to
pick which AnkiConnect instance to act on rather than an entity target. Don't register a new
mutating action as an entity service.

## Conventions enforced here

- No em dashes, arrows, or stacked parenthetical asides in code, comments, docstrings, or docs;
  write plain sentences instead.
- Docstrings are Google-style; where both appear, `Returns:` comes before `Raises:` (pydoclint
  enforces this order).
- Comments explain non-obvious *why* (a constraint, a workaround, a gotcha), never *what* the code
  already states.
- New behavior needs a test; a bug fix needs a regression test.
- Commits are atomic (one logical change each) with imperative-mood subjects: "Add x", not "Added
  x" or "Adds x".
- AI-generated contributions must be reviewed, tested, and verified to actually work, not just
  plausible-looking; see `CONTRIBUTING.md`'s AI usage policy for the full expectations.
