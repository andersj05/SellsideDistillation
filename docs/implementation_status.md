# Milestone status

## Milestone 0: offline foundation

Implemented:

- Python CLI, strictly validated offline configuration, no runtime dependencies, locked development tools, and local setup instructions.
- Validated document, evidence, fact, claim, calculation, rule, task, budget, issue, and run contracts.
- Content-hashed source copies, duplicate/split checks, SQLite inventory, native text/CSV locations, and PDF intake with pending parser status.
- Development evidence allowlists, source/fact availability cutoffs, hidden-reference denial, and derived-cache bypass prevention.
- A source-linked synthetic dissection with separate observations, inferred candidate rule, alternative explanation, and review gaps.
- Exact financial arithmetic, half-up display rounding, independent rational recomputation, and a closed synthetic prose audit.
- Generic and synthetic candidate workflow selection, a predeclared paired comparison, and deliberate degraded cases.
- Atomic artifacts, append-preserving trace snapshots, resource reservations, partial checkpoints, integrity-checked offline replay, and separate regrading exports.
- Self-contained report and comparison HTML with evidence/claim/calculation inspection.

The foundation is not the handoff's completed empirical research lab. It demonstrates mechanics using public invented data and a deterministic adapter.

## Validation record

The full fixture demonstration produced twelve expected outcomes: two clean runs passed all fifteen financial-output checks and all three question checks; ten deliberately degraded runs retained their expected issues. Both clean reports were identical across the generic and synthetic candidate variants. No hosted model calls or paid tools were used.

The expanded 44-test suite passes in GitHub CI on Windows and Linux with Python 3.12, 3.13, and 3.14. Ruff lint/format, mypy, coverage, repository content checks, and the locked dependency audit also pass. The initial foundation's static artifact inspection verified thirteen HTML pages, 512 local links/anchors, and all twelve run manifests. See [the audit record](audit-2026-09-15.md) for regression details and current checks.

The initial Windows test pass exposed SQLite handles remaining open after transactions; explicit connection closure fixed that cleanup failure. The workspace demo exposed transient Windows file locks during atomic replacement; bounded retries now cover that condition and have a regression test.

Browser visual QA remains pending: the browser tool rejected the local-file URL under its URL security policy. HTML structure and local links can be checked without opening a browser. Do not interpret generated `review.html` files as visually approved reports.

## Detailed PDF capture

Implemented optional local PDF capture with pinned pdfplumber/PDFium dependencies, full-page and substantial-image OCR, page visuals, native/OCR word geometry, table/cell candidates, drawing geometry, and inspectable evidence spans. Hashes in the trusted corpus registration bind the derived manifest and files. Forced and changed-recipe captures preserve previous bundles. Separate extraction-reference checks retain draft versus reviewed status and do not grade research quality.

Real-PDF dissection exposes observations and structural candidates without creating analytical rules. The owner prioritized source detail first and task/company-dependent analytical methods. See [the extraction guide](pdf_extraction.md) for routes and limitations.

The extraction route has local invented-PDF regression checks covering native and OCR provenance, page/cell geometry, malformed input, cutoff enforcement, cache tampering, preserved prior captures, safe HTML rendering, and separate reference grading. This does not establish human-reviewed OCR accuracy or semantic completeness.

The required offline check passes locally with 58 tests and 90% coverage, plus Ruff, mypy, and repository content checks. The updated locked development/PDF dependency set passes the separate dependency audit. Cross-platform validation remains subject to the feature's CI run.

## Next milestone: extraction review and task-specific evaluation

1. Inventory supplied PDFs and workpapers from `data/incoming/`; determine report family, publication/availability evidence, and related-report groups.
2. Assign discovery/development/evaluation roles before detailed methodology extraction.
3. Compare the implemented capture with a structured parser on a cover page, dense financial table, chart/footnote page, and valuation page when reviewed errors justify the added route.
4. Retain page renderings and build a small human-verified sample of critical values, units, merged headers, footnotes, and locations. Measure correction effort.
5. Define evaluation criteria and analytical choices for a bounded real assignment. Keep any proposed reusable rules optional, scoped, and reviewable; do not replace a task-adaptive method with a mandatory report-derived pattern.
6. Configure a hosted model/data route and paid caps when authorized; add a live smoke suite and an isolated evaluator boundary before any real baseline/transfer claim.

## Deliberately pending

- Human-reviewed OCR/table accuracy, verified header/period/unit relationships, chart-series reconstruction, and structured-parser comparison.
- Automatic real-report methodology inference and expert-corrected rules.
- Hosted model/API integrations, licensed data, external research tools, and live baselines.
- Arbitrary user-defined financial models, automatic scale normalization, and DCF.
- General final-claim extraction/entailment assessment, analyst usefulness scores, and persistent reviewer annotations.
- Crash resumption, dependency-aware refresh, locked evaluation process isolation, and cryptographically signed immutable records.

Setup, adapter, grading, and rendering failures preserve attempt records and available outputs. Comparisons predeclare all attempts, retain failures, and continue later attempts. Abrupt termination or persistent filesystem failure may leave a partial, unsealed directory; recovery records require writable storage and `replay` will not certify an unsealed run.
