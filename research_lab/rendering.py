"""Self-contained Markdown/HTML review artifacts; no remote assets or services."""

import re
from html import escape
from pathlib import Path

from .schemas import Claim, Task
from .serde import atomic_write

STYLE = """
:root{--paper:#f5f3ed;--ink:#202d31;--muted:#58676a;--line:#d8dfdb;--accent:#0a6959;--red:#973c35;--gold:#805518}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 system-ui,-apple-system,Segoe UI,sans-serif}
a{color:var(--accent);text-underline-offset:3px}header{border-bottom:1px solid var(--line);background:#fffdf8;padding:18px 5vw;display:flex;justify-content:space-between;gap:20px;align-items:center}
.brand{font-weight:750;letter-spacing:.04em}.eyebrow{text-transform:uppercase;letter-spacing:.14em;font-size:11px;font-weight:750;color:var(--accent)}
main{max-width:1320px;margin:auto;padding:42px 5vw 70px}h1{font-size:clamp(30px,4vw,48px);font-weight:550;line-height:1.15;letter-spacing:-.035em;margin:12px 0 18px}
h2{font-size:23px;font-weight:620;line-height:1.3;margin:32px 0 16px}h3{font-size:17px;margin:12px 0}.lede{color:var(--muted);max-width:830px;font-size:17px}.small,small{font-size:12px;color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:28px 0}.card,.panel{background:#fffdf8;border:1px solid var(--line);border-radius:8px;padding:22px}.metric{font-size:32px;font-weight:650;letter-spacing:-.025em}
.tag{display:inline-block;font-size:11px;line-height:1.4;padding:5px 9px;border-radius:5px;background:#e2eee8;color:var(--accent);font-weight:700}.tag.failed,.tag.critical{color:var(--red);background:#f8e6e1}.tag.incomplete,.tag.budget_exhausted{color:var(--gold);background:#f5ead5}
.notice{padding:16px 20px;border-left:3px solid var(--accent);background:#e9efe8;margin:24px 0}.grid{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(260px,1fr);gap:24px;align-items:start}.report{font:17px/1.8 Georgia,serif}.report h1{font:600 27px/1.25 system-ui}.report h2{font:600 20px/1.3 system-ui;margin-top:28px}
.report p{overflow-wrap:anywhere}.report .footnote{font:11px/1.6 system-ui;color:var(--muted)}.report a{font:12px system-ui;vertical-align:super}
table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);background:#edf0e9}td,th{padding:13px 12px;border-bottom:1px solid var(--line);vertical-align:top}.scroll{overflow-x:auto}td.number{font-variant-numeric:tabular-nums;text-align:right}
details{background:#fffdf8;border:1px solid var(--line);border-radius:6px;margin:12px 0;padding:14px 18px}summary{cursor:pointer;font-weight:620}pre,code{font:12px/1.6 ui-monospace,Consolas,monospace}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f3ee;padding:14px;border-radius:5px}.issue{border-bottom:1px solid var(--line);padding:12px 0}.issue:last-child{border:0}.claim{margin:18px 0;padding-bottom:18px;border-bottom:1px solid var(--line)}.claim a{overflow-wrap:anywhere}
nav{display:flex;gap:18px;flex-wrap:wrap;margin:22px 0}footer{font-size:12px;color:var(--muted);margin-top:40px;border-top:1px solid var(--line);padding-top:20px}select{padding:9px 14px;border:1px solid var(--line);border-radius:5px;background:white;color:var(--ink)}
@media(max-width:820px){.grid{grid-template-columns:1fr}.cards{grid-template-columns:1fr}main{padding:25px 5vw}header{align-items:flex-start;flex-direction:column}table{min-width:620px}}
@media print{body{background:white}main{max-width:none;padding:15px}.grid{display:block}.panel,.card{break-inside:avoid}nav,select{display:none}details{break-inside:avoid}}
"""


def page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)} · Research Lab</title><style>{STYLE}</style></head><body>"
        "<header><span class='brand'>SELLSIDE DISTILLATION</span><span class='eyebrow'>Local research lab · Fixture mode</span></header>"
        f"<main>{body}<footer>Local synthetic experiment · No hosted model calls · Human review pending</footer></main></body></html>"
    )


def report_markdown(task: Task, claims: list[Claim]) -> str:
    blocks = [
        "# Synthetic earnings update",
        "All inputs are invented. This is a test of research plumbing, not a company forecast.",
    ]
    for section in task.required_sections:
        blocks.append("## " + section)
        paragraphs = [
            f"{claim.text} [^{i}]"
            for i, claim in enumerate(claims, 1)
            if claim.report_section == section
        ]
        blocks.extend(paragraphs or ["No supported findings are available for this section."])
    blocks.append("## Source and calculation notes")
    blocks.extend(
        f"[^{i}]: Sources: {', '.join(claim.supporting_span_ids) or 'none'}. "
        f"Calculations: {', '.join(claim.calculation_ids) or 'none'}."
        for i, claim in enumerate(claims, 1)
    )
    return "\n\n".join(blocks) + "\n"


def markdown_html(text: str) -> str:
    parts = []
    source_notes_open = False
    for block in text.strip().split("\n\n"):
        if block == "## Source and calculation notes":
            parts.append("<details><summary>Source and calculation notes</summary>")
            source_notes_open = True
        elif block.startswith("## "):
            parts.append(f"<h2>{escape(block[3:])}</h2>")
        elif block.startswith("# "):
            parts.append(f"<h1>{escape(block[2:])}</h1>")
        elif block.startswith("[^") and "]: " in block:
            parts.append(f"<p class='footnote'>{escape(block)}</p>")
        else:
            safe = re.sub(
                r"\[\^(\d+)\]",
                lambda m: f"<a href='#claim-{m[1]}' aria-label='Inspect claim {m[1]}'>[{m[1]}]</a>",
                escape(block),
            )
            if source_notes_open:
                # Novel final prose must stay visible, including the deliberately injected failure.
                parts.append("</details>")
                source_notes_open = False
            parts.append(f"<p>{safe}</p>")
    if source_notes_open:
        parts.append("</details>")
    return "".join(parts)


def status_tag(status: str) -> str:
    label = {"passed_automated_checks": "Automated checks passed", "completed": "Completed"}.get(
        status, status.replace("_", " ").capitalize()
    )
    return f"<span class='tag {escape(status, quote=True)}'>{escape(label)}</span>"


def render_run(
    run_dir: Path,
    manifest: dict,
    task: Task,
    packet: dict,
    findings: dict,
    evaluation: dict,
    playbook: dict,
) -> Path:
    research = evaluation["scorecards"]["research"]
    issues = "".join(
        f"<div class='issue'>{status_tag(i['severity'])}<h3>{escape(i['code'].replace('_', ' '))}</h3><p>{escape(i['message'])}</p></div>"
        for i in evaluation["issues"]
    )
    if not issues:
        issues = "<p>All declared mechanical checks passed. Forecast quality and analyst usefulness remain unassessed.</p>"
    documents = {d["document_id"]: d for d in packet["documents"]}
    spans = {s["span_id"]: s for s in packet["spans"]}
    anchors = {identifier: f"source-{n}" for n, identifier in enumerate(spans, 1)}
    claims_html = []
    for number, claim in enumerate(findings["claims"], 1):
        links = " · ".join(
            f"<a href='#{anchors[s]}'>{escape(documents[spans[s]['document_id']]['original_filename'])} / {escape(spans[s]['locator'])}</a>"
            for s in claim["supporting_span_ids"]
            if s in spans
        )
        claims_html.append(
            f"<article class='claim' id='claim-{number}'><span class='eyebrow'>Claim {number} · {escape(claim['claim_type'])} · {escape(claim['origin'])}</span>"
            f"<p>{escape(claim['text'])}</p><p class='small'>{links or 'No supporting source; explicit gap.'}</p>"
            f"<p class='small'>Calculations: {escape(', '.join(claim['calculation_ids']) or 'none')}</p></article>"
        )
    rows = []
    for calc in findings["calculations"]:
        for metric, value in calc["outputs"].items():
            rows.append(
                f"<tr><td>{escape(calc['scenario'])}</td><td>{escape(metric.replace('_', ' '))}</td>"
                f"<td class='number'>{escape(value)}</td><td>{escape(calc['output_units'][metric])}</td></tr>"
            )
    source_html = "".join(
        f"<details id='{anchors[s['span_id']]}'><summary>{escape(documents[s['document_id']]['original_filename'])} · {escape(s['locator'])}</summary>"
        f"<p class='small'>Available: {escape(documents[s['document_id']]['available_at'])} · Native CSV record; human review pending</p>"
        f"<pre>{escape(s['text'])}</pre><p class='small'>Source hash: {escape(s['document_sha256'])}</p></details>"
        for s in packet["spans"]
    )
    rule_html = "".join(
        f"<details><summary>{escape(r['name'])} · {escape(r['origin'])}</summary><p>{escape(r['confidence'])}</p>"
        f"<p><b>Applies:</b> {escape(r['applies_when'])}</p><p><b>Exception:</b> {escape(r['does_not_apply_when'])}</p>"
        f"<p><b>Checks:</b> {escape(', '.join(r['checks']))}</p><p><b>Source spans:</b> {escape(', '.join(r['supporting_report_span_ids']) or 'None; proposed generic rule')}</p></details>"
        for r in playbook["rules"]
    )
    body = (
        f"<div class='eyebrow'>Run review · {escape(manifest['variant'])}</div><h1>A forecast, with its evidence.</h1>"
        f"<p class='lede'>{escape(task.question)}</p>{status_tag(evaluation['status'])}"
        f"<nav><a href='#report'>Report</a><a href='#claims'>Claims</a><a href='#ledger'>Calculations</a><a href='#sources'>Sources</a><a href='#playbook'>Playbook</a></nav>"
        f"<div class='cards'><div class='card'><div class='eyebrow'>Numeric outputs checked</div><div class='metric'>{research['correct_numeric_outputs']} / {research['required_numeric_outputs']}</div><small>{research['assessed_numeric_outputs']} outputs were available to assess</small></div>"
        f"<div class='card'><div class='eyebrow'>Questions answered</div><div class='metric'>{len(research['answered_questions'])} / 3</div><small>Revision · sensitivity · assumption</small></div>"
        f"<div class='card'><div class='eyebrow'>Model / tool charges</div><div class='metric'>$0.00</div><small>{manifest['usage']['tool_calls']} tool calls · local compute unpriced</small></div></div>"
        "<div class='notice'>Synthetic inputs and scripted generation. Passing these checks validates the lab machinery; research quality and transfer remain untested.</div>"
        f"<div class='grid'><section id='report' class='panel report'>{markdown_html((run_dir / 'report.md').read_text(encoding='utf-8'))}</section>"
        f"<aside class='panel'><div class='eyebrow'>Independent evaluation</div><h2>Findings & gaps</h2>{issues}</aside></div>"
        f"<h2 id='claims'>Claim provenance</h2><div class='panel'>{''.join(claims_html)}</div>"
        f"<h2 id='ledger'>Calculation ledger</h2><div class='panel scroll'><table><thead><tr><th>Scenario</th><th>Output</th><th>Value</th><th>Unit</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        f"<h2 id='sources'>Source inspection</h2><p>Stable row locations in immutable source snapshots. No PDF page coordinates are inferred.</p>{source_html}"
        f"<h2 id='playbook'>Playbook & uncertainty</h2>{rule_html}"
        "<details><summary>Run artifacts and execution details</summary><p><a href='report.md'>Markdown</a> · <a href='manifest.json'>Run manifest</a> · <a href='evaluation.json'>Evaluation</a> · <a href='trace.jsonl'>Trace</a> · <a href='playbook.json'>Playbook and dissection</a></p>"
        f"<p>Model route: {escape(manifest['provider'])} / {escape(manifest['model_id'])}. No prompt or model tokens were used.</p>"
        f"<p>Stopped: {escape(manifest['stopping_reason'])}</p><p>Code hash: <code>{escape(manifest['code_hash'])}</code></p></details>"
    )
    path = run_dir / "review.html"
    atomic_write(path, page("Run review", body).encode("utf-8"))
    return path


def render_comparison(
    experiment_dir: Path, results: list[dict], assignments: dict, protocol: dict
) -> Path:
    clean = [r for r in results if r["case"] == "clean"]
    passed = sum(r["evaluation_status"] == "passed_automated_checks" for r in clean)
    detected = sum(r["expected_behavior_observed"] for r in results if r["case"] != "clean")
    degraded = sum(r["case"] != "clean" for r in results)
    rows = []
    for r in results:
        href = f"../../{r['run_id']}/review.html"
        if not r.get("review_available", True):
            href = "attempts.json"
        rows.append(
            f"<tr data-case='{escape(r['case'], quote=True)}'><td><a href='{escape(href, quote=True)}'>{escape(r['case'].replace('_', ' '))}</a></td>"
            f"<td>{escape(r['label'])}</td><td>{status_tag(r['evaluation_status'])}</td><td class='number'>{r['numeric_correct']}/15</td>"
            f"<td class='number'>{r['questions_answered']}/3</td><td>{escape(', '.join(r['issue_codes']) or 'None')}</td>"
            f"<td class='number'>{r['tool_calls']}</td></tr>"
        )
    options = "".join(
        f"<option value='{escape(c, quote=True)}'>{escape(c.replace('_', ' '))}</option>"
        for c in protocol["cases"]
    )
    mapping = " · ".join(
        f"{escape(label)} = {escape(variant)}" for variant, label in assignments.items()
    )
    body = (
        "<div class='eyebrow'>Development comparison · Foundation milestone</div><h1>Make the research inspectable.</h1>"
        "<p class='lede'>The first experiment follows a synthetic earnings forecast from dated source rows through valuation, claim checking, and deliberate failures.</p>"
        f"<div class='cards'><div class='card'><div class='eyebrow'>Clean runs passed</div><div class='metric'>{passed} / {len(clean)}</div><small>Independent arithmetic and final-prose checks</small></div>"
        f"<div class='card'><div class='eyebrow'>Expected failures detected</div><div class='metric'>{detected} / {degraded}</div><small>All degraded attempts remain in the comparison</small></div>"
        f"<div class='card'><div class='eyebrow'>Hosted model calls</div><div class='metric'>0</div><small>Fixture mode · $0 model/tool charges</small></div></div>"
        "<div class='notice'><b>What this establishes:</b> source boundaries, financial identities, trace capture, and error reporting work on the declared fixtures. Real-report extraction, inferred-method benefit, and analyst usefulness remain untested.</div>"
        f"<h2>Paired results</h2><p class='small'>Each pair uses the same source packet, cutoff, adapter, and budget. Labels reveal no automatic research-quality ranking.</p>"
        f"<label for='case-filter' class='small'>Show case </label><select id='case-filter'><option value='all'>All cases</option>{options}</select>"
        f"<div class='panel scroll' style='margin-top:16px'><table><thead><tr><th>Case / open review</th><th>Variant</th><th>Outcome</th><th>Numbers</th><th>Questions</th><th>Issues</th><th>Calls</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        "<h2>What to learn next</h2><div class='grid'><div class='panel'><h3>Bring one report family into the lab</h3><p>Place reports in <code>data/incoming/</code>. Inventory them before assigning discovery and holdout roles. PDFs are preserved for a parser comparison; native text and curated CSV are inspectable now.</p></div>"
        "<div class='panel'><h3>Test whether a learned rule adds value</h3><p>The synthetic candidate adds an explicit check already implied by the generic workflow. A real comparison needs report-derived rules, a strong general-agent baseline, and a fresh assignment.</p></div></div>"
        f"<details><summary>Show workflow assignments and protocol</summary><p>{mapping}</p><p><a href='protocol.json'>Frozen protocol</a> · <a href='comparison.json'>All results</a></p>"
        "<p>Neutral labels support inspection, but these run pages disclose workflow details. A genuinely blinded human study remains pending.</p></details>"
        "<script>document.getElementById('case-filter').addEventListener('change',function(){for(const row of document.querySelectorAll('tr[data-case]'))row.hidden=this.value!=='all'&&row.dataset.case!==this.value;});</script>"
    )
    path = experiment_dir / "index.html"
    atomic_write(path, page("Fixture comparison", body).encode("utf-8"))
    return path
