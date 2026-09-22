# Auto-merge and malice gate

Mechanical PRs can squash-merge themselves once CI and the malice gate are green.
This is intentionally narrow.

## Allowlist

Only these authors may enable auto-merge:

- `MrMooreUK`
- `dependabot[bot]`
- `github-actions[bot]`

To add another known bot, update:

1. `ALLOWLIST` in `scripts/automerge_eligibility.py`
2. The `ALLOW` regex in `.github/workflows/auto-merge.yml`

External contributors never auto-merge.

## Malice gate (fail closed)

Every PR runs:

- **Secret scan** (Gitleaks)
- **Bandit** on changed Python files
- **Semgrep** (`p/python` + `p/security-audit`) against the PR baseline
- **Automerge eligibility** — allowlist + diff scan for new egress / subprocess / `eval` / dynamic import, plus a BLE path gate

Any finding blocks a green malice gate.

## What forces manual Dev review

- Author not on the allowlist
- New lines matching dangerous patterns (network egress, subprocess/shell, `eval`/`exec`, dynamic import)
- Substantive changes under `custom_components/fluvalble/core/{discovery,protocol,client}.py` (packet / UUID / FACEBD routing) — still need **Dev + Bob**, not just CI green

Typing / null-safety-only edits that do not touch packet or UUID logic can still auto-merge when the author is allowlisted.

## Workflows

- `.github/workflows/malice-gate.yml` — scanners + eligibility
- `.github/workflows/auto-merge.yml` — enables `gh pr merge --auto --squash` when checks are green

## Install note (workflow scope)

GitHub refuses API writes under `.github/workflows/` without the `workflow` OAuth scope.
Until that scope is available on the automation token:

```bash
# one-time: re-auth gh with workflow scope
gh auth refresh -h github.com -s repo,workflow

# install the staged workflows onto this branch or main
cp docs/ci/proposed/malice-gate.yml .github/workflows/malice-gate.yml
cp docs/ci/proposed/auto-merge.yml .github/workflows/auto-merge.yml
git add .github/workflows/malice-gate.yml .github/workflows/auto-merge.yml
git commit -m "ci: install malice gate and allowlisted auto-merge"
```

Then mark the Malice gate checks as required on `main` / `dev` branch protection.
