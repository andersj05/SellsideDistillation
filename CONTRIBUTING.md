# Contributing

## Setup and checks

Use Python 3.12–3.14 and uv 0.12.5 (the CI version). Install uv using its [official instructions](https://docs.astral.sh/uv/getting-started/installation/).

```powershell
uv sync --locked
git config --local core.hooksPath .githooks
uv run --frozen --offline python scripts/check.py
```

The initial development-tool installation needs package-index access. The fixture runtime has no external dependencies; use the README's `--no-dev` commands for a fresh offline runtime environment. Existing development environments can run local checks offline.

The pre-commit hook checks staged repository contents, lint, formatting, and types. The pre-push hook runs the full local suite and coverage check. CI enforces these checks independently, including on clones without hooks. Never bypass a failing check to promote a change.

Format changes with `uv run --frozen --offline ruff format .`. Application and script functions require annotations. Keep flexible JSON typing at serialization and artifact boundaries. Add regression tests for material behavior, financial identities, source eligibility, and recovery; avoid tests that only repeat implementation details.

## Branches and commits

| Branch | Purpose | Accepts changes from |
| --- | --- | --- |
| `main` | Validated release baseline | `dev` pull requests |
| `dev` | Integration and upcoming work | `feat/*` pull requests; Dependabot updates |
| `feat/<feature-name>` | A bounded change | Small local commits |

Start from current `dev`:

```powershell
git fetch origin
git switch dev
git pull --ff-only
git switch -c feat/your-feature
```

Commit whenever a coherent change is tested and reviewable. Use descriptive prefixes such as `feat:`, `fix:`, `test:`, `docs:`, `ci:`, or `chore:`. Stage intended paths, inspect the diff, and push regularly with `git push -u origin feat/your-feature`.

Open a PR targeting `dev`. Describe the problem, final behavior, checks, and material limitations. Merge only after `CI required` succeeds against the current base and conversations are resolved. Use merge commits to preserve the frequent development commits.

Promote a validated batch using a PR from `dev` to `main`. Both branches require PRs and current successful CI, including for administrators. Force pushes and deletion are blocked. The solo-maintainer setup requires zero external approvals; code ownership identifies the reviewer. Increase required approvals when another maintainer can review independently.

After a release, merge `origin/main` into a new `feat/sync-main` branch created from current `dev`, then merge its PR into `dev` before the next release. This carries release merge ancestry forward while preserving the same PR checks. Fixes to released code also follow `feat/*` → `dev` → `main`.

## Dependencies and automation

Keep runtime dependencies separate from development tools. Pin new development tools exactly and commit `pyproject.toml` with `uv.lock`:

```powershell
uv add --dev --bounds exact PACKAGE
uv run --frozen --offline python scripts/check.py
```

Dependabot proposes weekly uv and GitHub Actions updates to `dev`. Review release notes, the lock diff, and CI before merging. Vulnerability alerts require attention even when an automatic update PR is unavailable. Fix security alerts through the same feature/development/release path.

Actions use full commit hashes, read-only workflow tokens, and no persisted checkout credentials. The required aggregate check fails when any dependency job fails, is cancelled, or is skipped. Repository settings are recorded in `configs/github/` and can be reapplied by an administrator using the GitHub API.

## Research data and artifacts

Keep supplied reports, workpapers, run bundles, evaluator copies, exports, databases, and credentials outside Git. Only explicitly invented fixtures belong in source control. The repository guard checks tracked paths and common credential signatures; GitHub secret scanning and push protection provide another check. Ignore rules and scanners do not replace inspecting a public diff.

Financial/provenance changes must preserve units, periods, classifications, cutoff checks, full matching lineage, and independent recomputation. Change fixture protocols explicitly when assumptions or oracle expectations change. Preserve earlier runs and regrades for comparison.

The [handoff](equity-research-agent-lab-handoff.md) describes the larger research project. Current capability and remaining work are tracked in [milestone status](docs/implementation_status.md).
