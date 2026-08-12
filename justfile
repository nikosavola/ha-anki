# Justfile for ha-anki (https://github.com/casey/just)

set shell := ["bash", "-uc"]

# Show available recipes (default target)
default:
    @just --list

alias help := default

## Setup

# Sync the dev environment and install the prek git hook (see CONTRIBUTING.md#setup)
[group('setup')]
install:
    uv sync --dev
    uvx prek install

## Test

# Run the unit test suite, which mocks every AnkiConnect HTTP response
[group('test')]
test:
    uv run --dev pytest

# Run the unit test suite the same way CI does, with coverage and JUnit output
[group('test')]
test-cov:
    uv run --dev --group github pytest --cov --cov-branch --cov-report=xml --junitxml=junit.xml -o junit_family=legacy

# Ruff, pyrefly and the rest aren't project dependencies on purpose (see
# CONTRIBUTING.md#linting-formatting-and-type-checking): they run through prek so the
# same pinned versions are used locally and in CI, rather than whatever `ruff`/`pyrefly`
# happens to resolve to on a given machine.
[doc('Run every pre-commit hook (ruff, pyrefly, actionlint, zizmor, ...) over all files')]
[group('test')]
pre-commit:
    uvx prek run --all-files

## End-to-end

# Install Anki + AnkiConnect, bootstrap a profile, and seed and start a collection
[group('e2e')]
e2e-start:
    tests/e2e/scripts/run_local.sh

# Repeatable: start once with `e2e-start`, then run this as many times as needed
# against the same instance.
[doc('Run the end-to-end suite against the instance `e2e-start` started')]
[group('e2e')]
e2e-test:
    uv run --dev pytest tests/e2e --run-e2e -v

# Stop the Anki instance `e2e-start` started
[group('e2e')]
e2e-stop:
    tests/e2e/scripts/stop_anki.sh

# Needs the `catthehacker/ubuntu:act-latest` image: the default act image has no
# apt-get package lists or sudo, which install_anki.sh needs (see
# CONTRIBUTING.md#validating-the-e2e-workflow-with-act).
[doc('Validate .github/workflows/e2e.yml locally with act, before pushing')]
[group('e2e')]
act-e2e:
    act -j e2e -P ubuntu-latest=catthehacker/ubuntu:act-latest --container-architecture linux/amd64
