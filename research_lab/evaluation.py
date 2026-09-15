"""Evaluator-only code. Independent rational arithmetic and a closed fixture prose audit.

This is deliberately not a general natural-language entailment grader.
"""

import json
import re
from collections import Counter
from fractions import Fraction
from pathlib import Path

from .fixtures import PROJECT
from .schemas import Calculation, Claim, Fact, Task, timestamp
from .serde import from_dict, read_json, write_json


def half_up(value: Fraction) -> str:
    # Independent of the generator's Decimal display implementation.
    scaled = abs(value) * 100
    whole, remainder = divmod(scaled.numerator, scaled.denominator)
    cents = whole + (2 * remainder >= scaled.denominator)
    sign = "-" if value < 0 else ""
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def oracle_for(root: Path, task_id: str) -> dict:
    if not re.fullmatch(r"synthetic_earnings_[a-z_]+", task_id):
        raise ValueError("No evaluator has been defined for this task")
    path = root / "private_eval" / f"{task_id}.json"
    fixture_oracle = read_json(PROJECT / "fixtures" / "evaluator" / "answers.json")
    if path.exists():
        if read_json(path) != fixture_oracle:
            raise ValueError("Evaluator reference changed; define a new protocol before using it")
    else:
        write_json(path, fixture_oracle)
    return fixture_oracle


def read_records(path: Path, cls):
    return [
        from_dict(cls, json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def evaluate_bundle(run_dir: Path, oracle: dict) -> dict:
    task = from_dict(Task, read_json(run_dir / "task.json"))
    packet = read_json(run_dir / "evidence.json")
    facts = {f.fact_id: f for f in (from_dict(Fact, x) for x in packet["facts"])}
    spans = {s["span_id"]: s for s in packet["spans"]}
    claims = read_records(run_dir / "claims.jsonl", Claim)
    calculations = read_records(run_dir / "calculations.jsonl", Calculation)
    findings = read_json(run_dir / "findings.json")
    issues = list(findings["issues"]) + list(packet["issues"])

    def issue(code, message, artifact=None, severity="critical"):
        issues.append(
            {
                "code": code,
                "message": message,
                "artifact_id": artifact,
                "stage": "evaluation",
                "severity": severity,
            }
        )

    if len({c.claim_id for c in claims}) != len(claims):
        issue("claim_inventory_mismatch", "Claim IDs must be unique.")
    if len({c.calculation_id for c in calculations}) != len(calculations) or len(
        {c.scenario for c in calculations}
    ) != len(calculations):
        issue("invalid_calculation", "Calculation IDs and scenario outputs must be unique.")

    allowed_documents = {s.document_id for s in task.allowed_sources}
    cutoff = timestamp(task.as_of)
    for document in packet["documents"]:
        if (
            document["document_id"] not in allowed_documents
            or document["role"] != "development"
            or document["available_at"] is None
            or timestamp(document["available_at"]) > cutoff
        ):
            issue("source_boundary", "Saved evidence violates the task source boundary.")
    for fact in facts.values():
        if (
            fact.available_at is None
            or timestamp(fact.available_at) > cutoff
            or fact.entity_id != task.entity_id
        ):
            issue(
                "fact_boundary", "A fact is outside the task's entity/time boundary.", fact.fact_id
            )
        for identifier in fact.source_span_ids:
            span = spans.get(identifier)
            if span is None or span["document_id"] not in allowed_documents:
                issue(
                    "source_link_missing",
                    "Financial input has no allowed source span.",
                    fact.fact_id,
                )
                continue
            row = json.loads(span["text"])
            fields = (
                "entity_id",
                "metric",
                "value",
                "displayed_value",
                "unit",
                "scale",
                "period_start",
                "period_end",
                "period_type",
                "accounting_basis",
                "value_type",
                "scenario",
                "available_at",
            )
            if any(getattr(fact, key) != (row.get(key) or None) for key in fields):
                issue(
                    "source_transcription_mismatch",
                    "Financial fact differs from its saved source row.",
                    fact.fact_id,
                )

    numeric_checks = []
    rational_outputs = {}
    required_metrics = {
        "revenue",
        "operating_margin",
        "net_interest_expense",
        "tax_rate",
        "diluted_shares",
        "assumed_forward_pe",
    }
    expected_units = {
        "revenue": ("USD", "million"),
        "net_interest_expense": ("USD", "million"),
        "operating_margin": ("ratio", "one"),
        "tax_rate": ("ratio", "one"),
        "diluted_shares": ("shares", "million"),
        "assumed_forward_pe": ("multiple", "one"),
    }
    for calc in calculations:
        try:
            if (
                calc.operation != "operating_model"
                or calc.formula_version != "1"
                or set(calc.input_fact_ids) != required_metrics
            ):
                raise ValueError("Unknown calculation contract")
            inputs = {k: facts[v] for k, v in calc.input_fact_ids.items()}
            contexts = {
                (
                    f.entity_id,
                    f.period_start,
                    f.period_end,
                    f.period_type,
                    f.accounting_basis,
                    f.definition_version,
                )
                for f in inputs.values()
            }
            if len(contexts) != 1:
                raise ValueError("Incompatible financial definitions")
            for metric, fact in inputs.items():
                if (
                    fact.metric != metric
                    or fact.scenario != calc.scenario
                    or (fact.unit, fact.scale) != expected_units[metric]
                    or fact.value_type not in ("forecast", "assumption")
                ):
                    raise ValueError("Incompatible input unit, metric, vintage, or classification")
            x = {k: Fraction(f.value) for k, f in inputs.items()}
            if (
                x["diluted_shares"] <= 0
                or not 0 <= x["tax_rate"] <= 1
                or not 0 <= x["operating_margin"] <= 1
            ):
                raise ValueError("Invalid financial domain")
            profit = x["revenue"] * x["operating_margin"]
            pretax = profit - x["net_interest_expense"]
            if pretax < 0:
                raise ValueError("Unsupported negative-tax case")
            income = pretax * (1 - x["tax_rate"])
            eps = income / x["diluted_shares"]
            expected = dict(
                operating_profit=profit,
                pretax_income=pretax,
                net_income=income,
                eps=eps,
                value_per_share=eps * x["assumed_forward_pe"],
            )
            if set(calc.outputs) != set(expected):
                raise ValueError("Unexpected output inventory")
            expected_output_units = {
                "operating_profit": "USD million",
                "pretax_income": "USD million",
                "net_income": "USD million",
                "eps": "USD/share",
                "value_per_share": "USD/share",
            }
            if calc.output_units != expected_output_units:
                raise ValueError("Unexpected output units")
            rational_outputs[calc.scenario] = expected
            for metric, reference in expected.items():
                actual = Fraction(calc.outputs[metric])
                golden = Fraction(oracle["expected"][calc.scenario][metric])
                passed = abs(actual - reference) <= Fraction(1, 100000000) and actual == golden
                numeric_checks.append(
                    {"calculation_id": calc.calculation_id, "metric": metric, "passed": passed}
                )
                if not passed:
                    issue(
                        "wrong_number",
                        f"{calc.scenario} {metric} fails independent recomputation/reference check.",
                        calc.calculation_id,
                    )
            if (
                half_up(expected["value_per_share"])
                != oracle["expected"][calc.scenario]["display_value"]
            ):
                issue(
                    "rounding_error",
                    "Half-up display disagrees with the hidden fixture reference.",
                    calc.calculation_id,
                )
        except (KeyError, ValueError, ZeroDivisionError) as exc:
            issue("invalid_calculation", str(exc), calc.calculation_id)

    calculation_ids = {c.calculation_id for c in calculations}
    resolved_links = 0
    labels = {
        "prior": "Prior forecast",
        "base": "Revised base case",
        "downside": "Margin-downside case",
    }
    grammar = re.compile(
        r"(Prior forecast|Revised base case|Margin-downside case): operating profit is USD ([-\d.]+) million, EPS is USD ([-\d.]+), and illustrative value is USD ([-\d.]+) per share\."
    )
    for claim in claims:
        linked = (
            all(s in spans for s in claim.supporting_span_ids)
            and all(c in calculation_ids for c in claim.calculation_ids)
            and all(f in facts for f in claim.fact_ids)
        )
        if not linked:
            issue(
                "claim_lineage_missing",
                "Claim has a missing evidence or calculation link.",
                claim.claim_id,
            )
        if linked and (claim.supporting_span_ids or claim.calculation_ids):
            resolved_links += 1
        if claim.claim_type == "unknown":
            continue
        supported = False
        match = grammar.fullmatch(claim.text)
        if match:
            scenario = next(k for k, v in labels.items() if v == match[1])
            if scenario in rational_outputs:
                expected = rational_outputs[scenario]
                supported = (
                    Fraction(match[2]) == expected["operating_profit"]
                    and Fraction(match[3]) == expected["eps"]
                    and match[4] == half_up(expected["value_per_share"])
                )
        elif claim.claim_id == "revision_bridge" and {"prior", "base"} <= rational_outputs.keys():
            delta = (
                rational_outputs["base"]["value_per_share"]
                - rational_outputs["prior"]["value_per_share"]
            )
            supported = claim.text == (
                "At fixed non-revenue assumptions, the revised base case changes illustrative value by USD "
                f"{half_up(delta)} per share versus the prior forecast."
            )
            prior = {f.metric: f.value for f in facts.values() if f.scenario == "prior"}
            base = {f.metric: f.value for f in facts.values() if f.scenario == "base"}
            supported = supported and all(
                prior[k] == base[k] for k in required_metrics - {"revenue"}
            )
        elif (
            claim.claim_id == "margin_sensitivity"
            and {"base", "downside"} <= rational_outputs.keys()
        ):
            base = {f.metric: f.value for f in facts.values() if f.scenario == "base"}
            down = {f.metric: f.value for f in facts.values() if f.scenario == "downside"}
            margin_delta = Fraction(down["operating_margin"]) - Fraction(base["operating_margin"])
            price_delta = (
                rational_outputs["downside"]["value_per_share"]
                - rational_outputs["base"]["value_per_share"]
            )
            bp = margin_delta * 10000
            supported = claim.text == (
                f"The margin scenario changes operating margin by {half_up(margin_delta * 100)} percentage points "
                f"({int(bp)} basis points) and illustrative value by USD {half_up(price_delta)} per share, "
                "holding the other supplied inputs fixed."
            )
            supported = supported and all(
                base[k] == down[k] for k in required_metrics - {"operating_margin"}
            )
        elif claim.claim_id == "multiple_assumption":
            multiples = [f for f in facts.values() if f.metric == "assumed_forward_pe"]
            supported = bool(multiples) and all(
                f.value_type == "assumption" and f.value == multiples[0].value for f in multiples
            )
            supported = (
                supported
                and claim.text
                == f"The forward P/E of {multiples[0].value}x is a supplied assumption. Its market justification is unassessed."
            )
        if not supported:
            issue(
                "claim_semantics_unassessed",
                "This claim is outside the checked synthetic prose contract or disagrees with the evidence.",
                claim.claim_id,
            )

    # Scan the final artifact independently of the generator's registered claim inventory.
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    headings = {
        "# Synthetic earnings update",
        "## Source and calculation notes",
        *("## " + s for s in task.required_sections),
    }
    fixed_text = {
        "All inputs are invented. This is a test of research plumbing, not a company forecast.",
        "No supported findings are available for this section.",
    }
    seen = Counter()
    for block in report.strip().split("\n\n"):
        if block in headings or block in fixed_text:
            continue
        body = re.fullmatch(r"(.+) \[\^(\d+)\]", block, re.DOTALL)
        note = re.fullmatch(r"\[\^(\d+)\]: Sources: (.*)\. Calculations: (.*)\.", block)
        if body and 1 <= int(body[2]) <= len(claims) and body[1] == claims[int(body[2]) - 1].text:
            seen[int(body[2])] += 1
            continue
        if note and 1 <= int(note[1]) <= len(claims):
            claim = claims[int(note[1]) - 1]
            if note[2] == (", ".join(claim.supporting_span_ids) or "none") and note[3] == (
                ", ".join(claim.calculation_ids) or "none"
            ):
                continue
        issue(
            "unregistered_prose",
            "Final report contains unregistered, altered, or unsupported content.",
        )
    if any(seen[i] != 1 for i in range(1, len(claims) + 1)):
        issue(
            "claim_inventory_mismatch",
            "Registered claims must appear exactly once in the final report.",
        )
    if len(report.split()) > task.output_word_budget:
        issue("output_budget", "Final report exceeds its declared word budget.")
    answered = []
    for identifier, question in (
        ("revision_bridge", "revision"),
        ("margin_sensitivity", "sensitivity"),
        ("multiple_assumption", "assumption"),
    ):
        if any(c.claim_id == identifier for c in claims) and not any(
            i.get("artifact_id") == identifier for i in issues
        ):
            answered.append(question)
    if len(answered) < 3:
        issue(
            "missing_required_question",
            "One or more required analytical questions cannot be answered with usable evidence.",
        )
    critical = [i for i in issues if i["severity"] == "critical"]
    failures = {
        "wrong_number",
        "source_boundary",
        "fact_boundary",
        "unregistered_prose",
        "claim_inventory_mismatch",
        "source_transcription_mismatch",
        "claim_semantics_unassessed",
        "invalid_calculation",
        "rounding_error",
        "claim_lineage_missing",
    }
    status = (
        "failed"
        if any(i["code"] in failures for i in critical)
        else "incomplete"
        if critical
        else "passed_automated_checks"
    )
    return {
        "schema_version": "1.0",
        "grader": "fixture_fraction_and_prose_v1",
        "status": status,
        "issues": issues,
        "checks": numeric_checks,
        "scorecards": {
            "extraction": {"status": "transcription_links_checked", "human_review": "pending"},
            "method_reconstruction": {
                "status": "unassessed",
                "reason": "Only an invented discovery note has been used.",
            },
            "research": {
                "correct_numeric_outputs": sum(c["passed"] for c in numeric_checks),
                "assessed_numeric_outputs": len(numeric_checks),
                "required_numeric_outputs": 15,
                "answered_questions": answered,
                "required_questions": 3,
                "claims_with_resolved_lineage": resolved_links,
                "total_registered_claims": len(claims),
                "citation_entailment": "General entailment unassessed; only the closed fixture prose contract is checked.",
                "analytical_usefulness": "unassessed",
                "correction_effort": "unassessed",
            },
            "document": {"status": "final_prose_inventory_checked", "visual_review": "pending"},
        },
        "limitations": [
            "Public synthetic oracle; not an untouched research evaluation.",
            "No live model, real-report extraction study, or human analyst review.",
            "No general natural-language claim extraction or entailment grading.",
        ],
    }
