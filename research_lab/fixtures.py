"""Prepare public synthetic source packets. No evaluator imports or answer values."""

from pathlib import Path
import csv
import io

from .corpus import Corpus, FACT_COLUMNS
from .schemas import SourceRef, Task
from .serde import atomic_write, read_json

PROJECT = Path(__file__).resolve().parents[1]
CASES = ("clean", "missing_prior", "share_scale", "conflicting_margin", "late_source", "unsupported_sentence")
METADATA = {
    "revenue": ("USD", "million", "forecast"),
    "operating_margin": ("ratio", "one", "assumption"),
    "net_interest_expense": ("USD", "million", "assumption"),
    "tax_rate": ("ratio", "one", "assumption"),
    "diluted_shares": ("shares", "million", "assumption"),
    "assumed_forward_pe": ("multiple", "one", "assumption"),
}


def prepare_case(corpus: Corpus, case: str) -> Task:
    if case not in CASES:
        raise ValueError("Unknown fixture case")
    fixture = read_json(PROJECT / "fixtures" / "earnings.json")
    references = []
    for scenario, inputs in fixture["scenarios"].items():
        if case == "missing_prior" and scenario == "prior":
            continue
        available = fixture["scenario_available_at"][scenario]
        if case == "late_source" and scenario == "base":
            available = "2026-03-02T07:00:00-05:00"
        rows = []
        for metric, value in inputs.items():
            unit, scale, value_type = METADATA[metric]
            if case == "share_scale" and scenario == "base" and metric == "diluted_shares":
                value, scale = "100000000", "one"
            row = dict(entity_id=fixture["entity_id"], metric=metric, value=value,
                       displayed_value=value, unit=unit, scale=scale,
                       period_start=fixture["period_start"], period_end=fixture["period_end"],
                       period_type="fiscal_year", accounting_basis="synthetic_adjusted_diluted_v1",
                       value_type=value_type, scenario=scenario, available_at=available)
            rows.append(row)
            if case == "conflicting_margin" and scenario == "base" and metric == "operating_margin":
                rows.append({**row, "value": "0.19", "displayed_value": "0.19"})
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=FACT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        path = corpus.data / "fixture_inputs" / case / f"{scenario}.csv"
        atomic_write(path, stream.getvalue().encode("utf-8"))
        document = corpus.ingest(path, role="development", published_at=available, available_at=available,
                                 availability_evidence="Invented, explicitly dated synthetic fixture",
                                 report_family="earnings_update")
        references.append(SourceRef(document_id=document.document_id, content_sha256=document.content_sha256))
    return Task(task_id="synthetic_earnings_" + case, entity_id=fixture["entity_id"],
                question="Explain the change in earnings expectations and valuation sensitivity, including unresolved inputs.",
                as_of=fixture["as_of"], allowed_sources=references)

