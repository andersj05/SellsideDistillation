# Implementation decisions

These are local design choices for Milestone 0, not research findings.

| Decision | Evidence and alternatives | Choice / condition for revision |
| --- | --- | --- |
| Start with an offline earnings fixture | The repository contained only the handoff and README; no supplied reports or model key. The handoff explicitly permits fixture-only progress. | Implement section 18.5 and its failure cases. Choose the actual report family after intake. |
| Python standard library | Python 3.12 and 3.14 are installed; the first calculation and text/CSV pipeline requires no external parser or model client. | Use dataclasses, Decimal, SQLite, argparse, and unittest. Add a pinned parser dependency only after a real extraction comparison. |
| Source checkout and uv virtual project | A wheel or installed CLI adds packaging dependencies without helping the first local review. | Run `python -m research_lab`. Package it when distribution beyond this checkout is needed. |
| Own the experiment contracts | Evidence lineage, fiscal definitions, source cutoffs, and evaluation boundaries are project-specific. | Implement these locally. Defer importing FinSight/FinRobot/FinRpt and orchestration frameworks; no reuse performance claim has been made. Revisit with a bounded real task and inspect exact dependency/API versions then. |
| Avoid invented PDF extraction | No PDFs exist to select or compare parsers, and a table transcription is not page geometry. | Preserve PDF originals with pending status. Support exact native text lines and logical CSV records now. |
| Capability-limited adapter | A prompt alone cannot prevent reference leakage; directory names are not access enforcement. | Supply only a prefiltered evidence view. Explicitly exclude arbitrary code and filesystem tools. An actual locked/live evaluator needs process isolation and a fresh model context. |
| Independent arithmetic | Reusing the generator's calculation function inside its grader would miss shared bugs. | Generator uses Decimal; evaluator uses Fraction plus a separate public fixture oracle copied to private storage. |
| Closed prose audit | There is no live model or general entailment grader in fixture mode. | Scan all final prose, check registered text and known fixture semantics, flag novel/altered prose. Label broader citation and research judgments unassessed. |
| Static review bundle | The handoff accepts HTML as the first interface, and persistent annotations are not yet needed. | Self-contained HTML/CSS/JS with sources, claims, errors, and neutral comparison labels. No frontend runtime or remote assets. |
| Do not manufacture candidate benefit | The proposed generic finance workflow already includes sensitivity checks. | Keep the synthetic candidate's extra check redundant and report identical clean content. A fair comparator must not be weakened to make a candidate win. |
| Reserve resources before dispatch | Budget overflow and failures can otherwise be omitted from telemetry. | Synchronized counters reserve tool/model/token/repair/cost usage first. Cooperative elapsed checks stop bounded generation. Failed dispatched calls remain counted. No paid route is implemented. |
| Windows file behavior | Tests exposed unclosed SQLite handles; the workspace demo also encountered a transient atomic-replace lock. | Close connections explicitly. Bound retries to recognized Windows sharing/access errors; preserve the prior artifact if replacement fails. |

No third-party API, benchmark release, or repository implementation was adopted in this milestone. External API/version research is deferred to the first parser/model integration decision.

## Detailed PDF capture milestone

The owner prioritized comprehensive source extraction before generation and evaluation, and explicitly rejected locking real research into an exact reusable analytical pattern. The analytical method must adapt to the company and research task. Real-report dissection therefore exposes observations and structural candidates without compiling rules.

Use a pinned optional pdfplumber/PDFium route for native geometry and local rendering, plus native Windows OCR or an installed Tesseract for full pages and substantial image crops. Keep both transcriptions, source visuals, cell candidates, review gaps, and provenance. Adopt a more structured parser only if reviewed evidence shows an improvement worth its dependencies and correction effort.

Bind extraction manifests to corpus registrations so an editable derived cache cannot bypass evidence provenance. Keep references separate from capture, preserve draft versus reviewed status, and label exact text-presence checks as component diagnostics. Do not interpret captured coverage as financial, semantic, or research-quality validation. Optional reusable rules remain future, scoped research hypotheses rather than mandatory planning steps.
