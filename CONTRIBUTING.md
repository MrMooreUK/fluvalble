# Contributing

Thanks for your interest in the Fluval BLE Home Assistant integration.
This project is small and friendly — please open an issue or discussion
before sending a large change so we can agree on direction first.

## Branch workflow

This repository uses a `dev` → `main` promotion model:

- `main` is the released code. Direct pushes and direct PRs are blocked
  by CI (the `branch-guard` job).
- `dev` is the integration branch. Open your PR against `dev`.
- Feature/fix branches follow the `feature/<slug>` or `fix/<slug>`
  convention; AI-driven branches follow `claude/<slug>`.

## Local development

```bash
# 1. Install dev tooling
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pre-commit
pre-commit install

# 2. Run the test suite
pytest tests/ -v

# 3. Lint + format
ruff check custom_components/ tests/
ruff format --check custom_components/ tests/
```

## Tests

- New behaviour **must** come with a unit test. We use `pytest` and
  `pytest-asyncio`.
- Keep the suite green. The CI lint and test jobs must pass before a
  PR can be merged.
- Coverage must remain at or above the floor in `pyproject.toml`
  (currently 33%, with a target of ~70% as entity-platform tests land).

## Code style

- Ruff enforces the style — there is no separate style guide. Run
  `ruff format` before committing.
- Type hints are encouraged but not yet enforced. Mypy runs in CI as a
  soft check.

## Reporting bugs

Before opening a new issue, please check the open issues and the
`docs/bug-triage.md` document. When you do open an issue, include:

1. Integration version (Settings → Devices & services → ⓘ)
2. Lamp model (Plant 3.0, Aquasky 2.0, etc.)
3. Bluetooth adapter (built-in, ESP32 proxy, etc.)
4. A debug log snippet with `custom_components.fluvalble: debug` enabled
5. The exact steps to reproduce

## Release process

Releases are tag-driven. The maintainer:

1. Adds an `[Unreleased]` entry to `CHANGELOG.md` covering the work
   landing in the next release.
2. Bumps `version` in `custom_components/fluvalble/manifest.json`.
3. Merges `dev` → `main` via PR.
4. Tags the merge commit: `git tag v0.0.X && git push --tags`.
5. The `release.yml` workflow builds the release assets and publishes
   a GitHub release.

## License

By contributing, you agree that your contributions will be licensed
under the Apache License 2.0 (see `LICENSE`).
