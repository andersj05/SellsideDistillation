"""Deterministic fixture adapter. It receives capabilities, not a repository path."""

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from .budget import BudgetMeter
from .evidence import EvidenceView
from .finance import FinancialError, comparable, difference, display, margin_change, run_calculation
from .schemas import Calculation, Claim, Issue, Task


@dataclass
class Findings:
    claims: list[Claim] = field(default_factory=list)
    calculations: list[Calculation] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    answered_questions: list[str] = field(default_factory=list)


class ModelAdapter(Protocol):
    provider: str
    model_id: str

    def generate(
        self,
        task: Task,
        evidence: EvidenceView,
        actions: set[str],
        meter: BudgetMeter,
        findings: Findings,
        event: Callable,
    ) -> None: ...


class FixtureAdapter:
    provider = "offline"
    model_id = "deterministic-fixture-v1"

    def generate(self, task, evidence, actions, meter, findings, event):
        known_actions = {
            "calculate_forecasts",
            "explain_changes",
            "preserve_gaps",
            "validate_single_driver",
        }
        if actions - known_actions:
            raise ValueError("Playbook contains an unimplemented action")
        if not {"calculate_forecasts", "explain_changes", "preserve_gaps"}.issubset(actions):
            raise ValueError("The fixture adapter requires the generic workflow actions")
        scenario_facts, calculations = {}, {}

        def claim(
            identifier,
            text,
            section,
            *,
            facts=(),
            calcs=(),
            kind="forecast",
            verification="verified",
            gaps=(),
        ):
            findings.claims.append(
                Claim(
                    claim_id=identifier,
                    text=text,
                    claim_type=kind,
                    origin="proposed" if kind != "unknown" else "observed",
                    verification_status=verification,
                    entity_id=task.entity_id,
                    horizon="FY2026",
                    materiality="critical",
                    supporting_span_ids=sorted({s for f in facts for s in f.source_span_ids}),
                    fact_ids=[f.fact_id for f in facts],
                    calculation_ids=[c.calculation_id for c in calcs],
                    report_section=section,
                    unresolved_questions=list(gaps),
                    qualifiers=[
                        "Invented fixture inputs; arithmetic verification does not verify forecasts."
                    ],
                )
            )

        for scenario in ("prior", "base", "downside"):
            rows = evidence.get_financial_facts(scenario)
            scenario_facts[scenario] = rows
            event("evidence_read", {"scenario": scenario, "fact_ids": [f.fact_id for f in rows]})
            try:
                for fact in rows:
                    for span_id in fact.source_span_ids:
                        evidence.read_source_span(span_id)
                meter.reserve(tool_calls=1)
                calc = run_calculation("operating_model", rows, scenario)
            except FinancialError as exc:
                findings.issues.append(
                    Issue(code=exc.code, message=str(exc), stage="normalization")
                )
                claim(
                    "gap_" + scenario,
                    f"The {scenario} forecast cannot be calculated: {exc}",
                    "Assumptions and gaps",
                    kind="unknown",
                    verification="not_applicable",
                    gaps=[str(exc)],
                )
                event("calculation_rejected", {"scenario": scenario, "code": exc.code})
                continue
            calculations[scenario] = calc
            findings.calculations.append(calc)
            output = calc.outputs
            label = {
                "prior": "Prior forecast",
                "base": "Revised base case",
                "downside": "Margin-downside case",
            }[scenario]
            section = "Margin sensitivity" if scenario == "downside" else "Estimate bridge"
            claim(
                "forecast_" + scenario,
                f"{label}: operating profit is USD {output['operating_profit']} million, EPS is USD {output['eps']}, "
                f"and illustrative value is USD {display(output['value_per_share'])} per share.",
                section,
                facts=rows,
                calcs=[calc],
            )
            event(
                "calculation_completed",
                {"calculation_id": calc.calculation_id, "input_fact_ids": calc.input_fact_ids},
            )

        def pair(left, right, changed_metric):
            if left not in calculations or right not in calculations:
                return None
            comparable(scenario_facts[left] + scenario_facts[right])
            a = {f.metric: f for f in scenario_facts[left]}
            b = {f.metric: f for f in scenario_facts[right]}
            if any(
                Decimal(a[key].value) != Decimal(b[key].value) for key in a if key != changed_metric
            ):
                raise FinancialError(
                    "multiple_driver_change",
                    "The scenarios change more than the stated single driver.",
                )
            return a, b

        try:
            bridge = pair("prior", "base", "revenue")
            if bridge:
                delta = difference(
                    calculations["prior"].outputs["value_per_share"],
                    calculations["base"].outputs["value_per_share"],
                )
                claim(
                    "revision_bridge",
                    f"At fixed non-revenue assumptions, the revised base case changes illustrative value by USD {display(delta)} "
                    "per share versus the prior forecast.",
                    "Estimate bridge",
                    facts=scenario_facts["prior"] + scenario_facts["base"],
                    calcs=[calculations["prior"], calculations["base"]],
                )
                findings.answered_questions.append("revision")
            sensitivity = pair("base", "downside", "operating_margin")
            if sensitivity:
                a, b = sensitivity
                change = margin_change(a["operating_margin"].value, b["operating_margin"].value)
                delta = difference(
                    calculations["base"].outputs["value_per_share"],
                    calculations["downside"].outputs["value_per_share"],
                )
                claim(
                    "margin_sensitivity",
                    f"The margin scenario changes operating margin by {display(change['percentage_points'])} percentage points "
                    f"({Decimal(change['basis_points']):.0f} basis points) and illustrative value by USD {display(delta)} per share, "
                    "holding the other supplied inputs fixed.",
                    "Margin sensitivity",
                    facts=scenario_facts["base"] + scenario_facts["downside"],
                    calcs=[calculations["base"], calculations["downside"]],
                )
                findings.answered_questions.append("sensitivity")
                if "validate_single_driver" in actions:
                    meter.reserve(tool_calls=1)
                    event(
                        "rule_check",
                        {
                            "rule_id": "synthetic_single_driver_sensitivity",
                            "result": "passed",
                            "changed_metric": "operating_margin",
                        },
                    )
        except FinancialError as exc:
            findings.issues.append(Issue(code=exc.code, message=str(exc), stage="normalization"))
            claim(
                "gap_comparison",
                str(exc),
                "Assumptions and gaps",
                kind="unknown",
                verification="not_applicable",
                gaps=[str(exc)],
            )

        pe_facts = [
            f for rows in scenario_facts.values() for f in rows if f.metric == "assumed_forward_pe"
        ]
        if (
            pe_facts
            and len({Decimal(f.value) for f in pe_facts}) == 1
            and all(f.value_type == "assumption" for f in pe_facts)
        ):
            claim(
                "multiple_assumption",
                f"The forward P/E of {pe_facts[0].value}x is a supplied assumption. Its market justification is unassessed.",
                "Assumptions and gaps",
                facts=pe_facts,
                kind="assumption",
                verification="partially_verified",
            )
            findings.answered_questions.append("assumption")
        else:
            findings.issues.append(
                Issue(
                    code="unsupported_multiple",
                    message="The valuation multiple lacks an unambiguous assumption label.",
                    stage="inference",
                )
            )
        meter.reserve()
