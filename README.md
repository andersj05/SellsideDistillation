# SellsideDistillation

[![CI](https://github.com/andersj05/SellsideDistillation/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/andersj05/SellsideDistillation/actions/workflows/ci.yml)

A local lab for investigating whether research reports can yield useful, reusable research methods.

**Implemented: the handoff's offline foundation milestone.** It ingests synthetic source packets, calculates a forecast and valuation bridge, produces evidence-linked reports, independently evaluates them, and saves a local review bundle. There are no runtime dependencies, model credentials, or hosted calls.

Real-report extraction, analyst review, live agent baselines, and claims of methodology transfer remain pending. The candidate playbook is inferred from an explicitly invented discovery note.

## Run it

From this repository, with Python 3.12–3.14:

```powershell
py -3.12 -m research_lab doctor
py -3.12 -m research_lab demo
```

`demo` creates twelve runs: six cases × two fixture workflows. It prints the absolute path to the HTML comparison. Open that file in your browser; each row links to the report, evidence, calculations, errors, playbook, and execution trace. Every file stays local.

On macOS/Linux, replace `py -3.12` with `python3`. With `uv` and a supported Python already installed:

```powershell
uv sync --frozen --offline --no-dev
uv run --frozen --offline --no-dev python -m research_lab demo
```

The project is a source checkout, not an installed `lab` executable. The runtime dependency graph is empty; `uv.lock` also pins development tools. The Python version is recorded in every run.

## Development

Use `feat/<feature-name>` branches from `dev`. Merge pull requests into `dev`, then promote `dev` into `main`. Commit small, tested changes frequently and push the feature branch regularly.

```powershell
uv sync --locked
git config --local core.hooksPath .githooks
uv run --frozen --offline python scripts/check.py
```

CI requires Ruff formatting/lint, fully annotated application functions checked by mypy, repository content checks, a dependency audit, and tests with at least 85% combined statement/branch coverage. Tests run on Windows and Linux with Python 3.12, 3.13, and 3.14.

See [CONTRIBUTING](CONTRIBUTING.md) for the full workflow and [the audit record](docs/audit-2026-09-15.md) for findings, fixes, and limitations.

## What the demonstration checks

| Case | Expected outcome |
| --- | --- |
| Clean forecast | 15 financial outputs recompute; all three analytical questions are answered |
| Missing prior forecast | Incomplete; no unsupported revision comparison |
| Individual shares mixed with USD millions | Incomplete; explicit unit/scale mismatch |
| Contradictory margin source | Incomplete; conflicting values require reconciliation |
| Revised forecast available after the cutoff | Source content withheld; incomplete comparison |
| Unsupported sentence added to the final report | Failed final-prose audit |

The clean case reproduces the handoff's illustrative values of **41.63, 50.63, and 45.23 USD per share**, using decimal half-up display rounding. The evaluator uses separate rational arithmetic and an evaluator-only reference file.

Both variants receive the same evidence and caps. The synthetic candidate adds an explicit scenario check already implied by the generic workflow. Identical supported reports are an expected plumbing result, not evidence that a learned method improves research.

## Commands

```powershell
# A single clean run or a focused comparison
py -3.12 -m research_lab run --case clean --variant candidate
py -3.12 -m research_lab compare --cases clean missing_prior

# Verify and inspect saved artifacts without generation or external calls
py -3.12 -m research_lab replay --run RUN_ID

# Regrade a frozen run into a separate exports/ artifact
py -3.12 -m research_lab evaluate --run RUN_ID

# Preserve reports and extract supported native text
py -3.12 -m research_lab ingest --input data/incoming --role discovery
py -3.12 -m research_lab inspect --document DOCUMENT_ID
py -3.12 -m research_lab dissect --document DOCUMENT_ID

# Run the deterministic suite
py -3.12 -m unittest discover -s tests -v
```

Use `--root PATH` **before** the command to store data and runs elsewhere. Use `--config PATH` for a fixture TOML configuration. Run IDs and document IDs are printed by the commands.

A single incomplete/failed run exits with code 1; configuration or input errors use code 2. `demo` and `compare` return 0 when every declared case has its expected outcome, including intentionally degraded cases.

## Bring in actual reports

Place files in **`data/incoming/`**. Intake accepts:

- `.md` and `.txt`: UTF-8 text with original line locations.
- `.csv`: native records with column names retained. Financial normalization requires the explicit schema in [the data dictionary](docs/data_dictionary.md).
- `.pdf`: originals are hashed, copied, and inventoried with `pending_parser` status. PDF text, tables, OCR, images, and page geometry are not yet extracted.

Incoming originals remain unchanged. Managed copies are content-addressed by SHA-256 in `data/originals/`; aliases share the same document identity. Imports publish complete source objects atomically and serialize inventory writes. Intake is capped at 64 MiB per source. Exact duplicates cannot cross corpus roles. Near-duplicate/report-series grouping is still manual.

Publication and availability times stay unknown unless explicitly supplied. For dated sources, pass `--published-at`, `--available-at`, and `--availability-evidence`. Timestamps require a timezone. Unknown or late availability is rejected from task evidence before source content is read.

`dissect` gives an inspectable transcription and section map for native-text discovery inputs. Automatic inferred-rule generation is intentionally limited to the bundled synthetic note. A real PDF parser comparison and human-verified extraction sample are the next milestone.

## Storage and scope

```text
research_lab/       Contracts, intake, evidence tools, finance, runner, evaluator, rendering, CLI
configs/           Offline route, budgets, and predeclared fixture protocol
fixtures/          Public invented inputs, discovery note, and evaluator test oracle
playbooks/generic/ Versioned proposed finance rules
docs/              Decisions, data contracts, research register, and next milestone
tests/             Financial, access-boundary, artifact, and pipeline checks
data/              Private originals, SQLite inventory, extraction artifacts (ignored)
private_eval/      Evaluator reference copies (ignored)
runs/              Separate run bundles and comparisons (ignored)
exports/           Derived evaluations (ignored)
```

The adapter gets an evidence capability containing only allowed facts/spans. It gets no corpus object, evaluator path, network tool, or host-filesystem tool. This is a tested application/tool boundary for the bundled deterministic adapter, **not an OS sandbox for arbitrary Python or a locked live evaluation**. The public synthetic answers are known test fixtures.

Runs capture task/source/protocol/playbook/code/lock hashes, resource counts, issues, checkpoints, exact outputs, and an artifact-integrity manifest. Replay verifies those saved bytes. It never resumes a model or fetches data. Comparisons journal every planned attempt, retain setup/grading/rendering failures, and continue subsequent attempts. Regrades create distinct exports with grader and oracle hashes. Recovery writes depend on writable storage; automatic crash resumption, signed immutability, and live refresh are not implemented.

Financial output checks and the closed synthetic prose audit do not establish general citation entailment, forecast validity, analytical usefulness, or expert approval. Those measures are shown as unassessed.

## Project notes

- [Implementation decisions](docs/decision_log.md)
- [Data dictionary](docs/data_dictionary.md)
- [Research register and comparison protocol](docs/research_register.md)
- [Milestone status and next work](docs/implementation_status.md)
- [Original research and implementation handoff](equity-research-agent-lab-handoff.md)
