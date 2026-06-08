# AGENTS.md

Guidance for AI coding agents (Hermes, Claude Code, Codex, Cursor, etc.)
working in this repository. Read this before you start changing code.

## Project at a glance

- **What:** Home Assistant custom integration for Fluval aquarium LED
  lights over BLE.
- **Language:** Python 3.11 / 3.12.
- **Framework:** Home Assistant core APIs (`homeassistant.components.bluetooth`,
  `ConfigEntry`, `Platform`).
- **Test framework:** `pytest` + `pytest-asyncio`.
- **Lint/format:** `ruff` (lint + format). Mypy runs in CI as a soft
  check (not yet gating).
- **Coverage floor:** 33% (configured in `pyproject.toml`). The floor
  is intentionally low to start — most of the platform/entity code is
  exercised via HA's own test harness rather than unit tests. A follow-up
  PR should add entity-platform tests and raise the floor to ~70%.
- **Branch model:** `dev` → `main`. PRs target `dev`. Direct PRs to
  `main` are blocked by CI's `branch-guard` job.

## Where to look

| Concern | Path |
|---|---|
| Integration entry point, platforms, lifecycle | `custom_components/fluvalble/__init__.py` |
| BLE client (connection, read/write) | `custom_components/fluvalble/core/client.py` |
| Device state machine | `custom_components/fluvalble/core/device.py` |
| Fluval packet encryption | `custom_components/fluvalble/core/encryption.py` |
| HA config flow | `custom_components/fluvalble/config_flow.py` |
| Entities (switch, number, select, binary_sensor) | `custom_components/fluvalble/{switch,number,select,binary_sensor}.py` |
| Tests | `tests/` |
| CI | `.github/workflows/ci.yml`, `dev-to-master.yml`, `release.yml` |

## Commands an agent will need

```bash
# Run the test suite (must pass)
pytest tests/ -v

# Lint + format check
ruff check custom_components/ tests/
ruff format --check custom_components/ tests/

# Auto-format the codebase
ruff format custom_components/ tests/

# Type-check (soft, not gating)
mypy custom_components/fluvalble/

# Coverage report
pytest tests/ --cov=custom_components/fluvalble --cov-report=term-missing
```

## What agents must NOT do

- **Do not** push directly to `main`. All changes go through `dev` and
  a PR. The CI branch-guard will reject direct PRs to `main`.
- **Do not** change the BLE protocol implementation
  (`core/encryption.py`, command bytes in `core/client.py`) without a
  protocol capture or hardware verification. Issue #6 (Aquasky 2.0) and
  issue #8 (RTC drift) are protocol-level problems that need evidence.
- **Do not** bump the `version` in `manifest.json` without also
  updating `CHANGELOG.md`.
- **Do not** edit the existing `dev-to-master.yml` or `release.yml`
  workflows without a maintainer review — they own the release train.
- **Do not** add new top-level dependencies to `manifest.json` without
  considering whether they should be `requirements` (run-time) or
  dev-only (kept in `requirements.txt`).
- **Do not** rename the integration domain (`fluvalble`). It is the
  config-flow key and HACS identifier.

## What agents SHOULD do

- Read `docs/bug-triage.md` before assuming an open issue is unfixed.
- Add a unit test for any new behaviour in `core/`, `__init__.py`, or
  any of the entity platforms.
- Keep the public BLE interface (anything in `core/`) backward
  compatible — the config flow and platforms depend on it.
- Prefer editing an existing file to creating a new one unless the new
  file has a clear single concern.

## Verifying a change

Before handing a change back to the maintainer, run:

```bash
pytest tests/ -v
ruff check custom_components/ tests/
ruff format --check custom_components/ tests/
```

All three must pass. If the change touched a platform file
(`switch.py`, `number.py`, etc.) or the config flow, also re-read the
relevant section of `README.md` and update it if the user-visible
behaviour changed.

## Background

- Reverse-engineering credits and protocol sources are in
  `README.md` → "How it works".
- Two real user bugs are tracked in `docs/bug-triage.md`. The
  maintainer is the only one with hardware to validate fixes for
  them; AI fixes for those issues should be marked "experimental" in
  the PR description and held for maintainer review.
