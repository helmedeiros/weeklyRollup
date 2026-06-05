# Contributing

Small, focused commits. Every commit leaves `main` green: tests pass, configs validate, and the GitHub Actions workflow goes green for the same checks.

## Quality gates

Two layers, identical content:

1. **Local pre-push hook** at `scripts/hooks/pre-push`. Activate once per clone:
   ```
   git config core.hooksPath scripts/hooks
   ```
   The hook runs before any `git push`:
   - `python -m unittest discover -s tests`
   - `python scripts/validate_config.py config/example-team.yaml`
   - `cd jira-mcp && npm test -- --ci` (skipped if Node is missing)

2. **GitHub Actions** at `.github/workflows/ci.yml`. Runs on every push and pull request against `main` with the same commands. A red CI blocks the PR.

If you must bypass the hook (rare — e.g., a CI-only fix), `git push --no-verify`. CI will still gate the merge.

## Commit style

Conventional Commits: `type(scope): subject`. Common types here:

- `feat(skill|parser|jira-mcp|ci): …` — new capability
- `fix(parser|skill|jira-mcp): …` — bug fix
- `chore: …` — non-functional housekeeping (renames, scrubs, deps)
- `docs: …` — README/SKILL/docs/

One logical change per commit. Stage hunks individually with `git add -p` when needed.

## When CI goes red on `main`

Investigate the failing step, push a `fix:` commit that turns it green again, do not revert. Force-push to `main` is reserved for the very narrow case where the red commit must be amended (e.g., a leaked secret); never force-push to overwrite someone else's history.

## Test pyramid

- **Unit (most)**: `tests/*.py` (Python skill, ~104 tests) and `jira-mcp/tests/*.test.js` (Node MCP, ~207 tests). Add new tests here for every fix and feature.
- **Integration (some)**: the `--jira-source fixture` and `--sheet-source fixture` paths exercised by `tests/test_run_rollup.py`. Extend the fixtures under `tests/fixtures/` rather than hitting live Jira.
- **End-to-end (manual)**: real Jira / Sheets / email runs against a configured team. Credentials and tenant URLs do not belong in CI, so the live path is verified ad-hoc by the operator.
