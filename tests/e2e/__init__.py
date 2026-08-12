"""End-to-end tests against a real, running Anki + AnkiConnect instance.

Not part of the regular `pytest` run (see pyproject.toml's `testpaths`).
Set up the real instance first with tests/e2e/scripts/run_local.sh, then run:

    uv run --dev pytest tests_e2e -v

or let the `e2e` GitHub Actions workflow do both.
"""
