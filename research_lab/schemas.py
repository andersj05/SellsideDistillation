"""Core contracts for schema 1.0. Financial decimals are serialized as strings."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
import re

Origin = Literal["observed", "inferred", "proposed"]
Verification = Literal["verified", "partially_verified", "unverified", "contradicted", "not_applicable"]
Role = Literal["discovery", "development", "locked_evaluation", "archive"]


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timestamps require an explicit timezone")
    return parsed


def decimal(value: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("Financial values must be decimal strings")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal") from exc
    if not number.is_finite():
        raise ValueError("Financial values must be finite")
    return number


def sha256(value: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("Expected an actual lowercase SHA-256 digest")


@dataclass(frozen=True, kw_only=True)
class Record:
    schema_version: str = "1.0"

    def __post_init__(self):
        if self.schema_version != "1.0":
            raise ValueError(f"Unsupported schema version {self.schema_version}; migration required")


@dataclass(frozen=True, kw_only=True)
class Document(Record):
    document_id: str
    content_sha256: str
    original_filename: str
    role: Role
    report_family: str
    ingested_at: str
    published_at: str | None = None
    available_at: str | None = None
    publication_time_confidence: Literal["known", "unknown"] = "unknown"
    availability_evidence: str = "Unknown; do not use in cutoff-controlled generation"
    company_ids: list[str] = field(default_factory=list)
    publisher: str | None = None
    page_count: int | None = None
    source_policy_id: str = "local_private_v1"
    extraction_status: Literal["extracted", "pending_parser"] = "extracted"
    review_status: str = "pending"

    def __post_init__(self):
        super().__post_init__()
        sha256(self.content_sha256)
        if self.document_id != "doc_" + self.content_sha256:
            raise ValueError("Document identity must match its content hash")
        timestamp(self.ingested_at)
        for value in (self.published_at, self.available_at):
            if value is not None:
                timestamp(value)
        if self.published_at and self.available_at and timestamp(self.available_at) < timestamp(self.published_at):
            raise ValueError("Availability precedes publication")
        if self.page_count is not None and self.page_count < 1:
            raise ValueError("Page count must be positive or unknown")


@dataclass(frozen=True, kw_only=True)
class EvidenceSpan(Record):
    span_id: str
    document_id: str
    document_sha256: str
    text: str
    excerpt: str
    location_kind: Literal["text_lines", "csv_record", "pdf_page"]
    locator: str
    page_index: int | None = None
    printed_page_label: str | None = None
    bbox: list[float] | None = None
    coordinate_system: str | None = None
    extraction_method: str = "native_text_v1"
    verification_status: Verification = "unverified"

    def __post_init__(self):
        super().__post_init__()
        sha256(self.document_sha256)
        if self.document_id != "doc_" + self.document_sha256:
            raise ValueError("Evidence document/hash mismatch")
        if not self.locator or not self.text:
            raise ValueError("Evidence requires text and a stable location")
        if self.page_index is not None and self.page_index < 0:
            raise ValueError("PDF page indices are zero-based")
        if self.bbox is not None:
            if (len(self.bbox) != 4 or not all(0 <= x <= 1 for x in self.bbox)
                    or self.bbox[0] > self.bbox[2] or self.bbox[1] > self.bbox[3]
                    or self.coordinate_system != "normalized_top_left"):
                raise ValueError("Invalid normalized top-left bounding box")
        if self.location_kind == "pdf_page" and self.page_index is None:
            raise ValueError("PDF evidence needs a page index")


@dataclass(frozen=True, kw_only=True)
class Fact(Record):
    fact_id: str
    entity_id: str
    metric: str
    value: str
    displayed_value: str
    unit: Literal["USD", "shares", "ratio", "multiple"]
    scale: Literal["one", "million", "billion"]
    period_start: str
    period_end: str
    period_type: Literal["fiscal_year", "calendar_year", "quarter"]
    accounting_basis: str
    value_type: Literal["actual", "forecast", "guidance", "consensus", "assumption"]
    scenario: str
    source_span_ids: list[str]
    available_at: str | None
    definition_version: str = "synthetic_operating_model_v1"
    verification_status: Verification = "unverified"
    supersedes_fact_id: str | None = None
    transformation: str = "Curated decimal transcription; no implicit scale conversion"

    def __post_init__(self):
        super().__post_init__()
        decimal(self.value)
        if date.fromisoformat(self.period_end) < date.fromisoformat(self.period_start):
            raise ValueError("Financial period ends before it starts")
        if not self.source_span_ids:
            raise ValueError("Facts require evidence spans")
        if self.available_at is not None:
            timestamp(self.available_at)


@dataclass(frozen=True, kw_only=True)
class Claim(Record):
    claim_id: str
    text: str
    claim_type: Literal["fact", "forecast", "assumption", "judgment", "unknown"]
    origin: Origin
    verification_status: Verification
    entity_id: str
    horizon: str
    materiality: Literal["critical", "supporting"]
    supporting_span_ids: list[str]
    calculation_ids: list[str]
    fact_ids: list[str]
    contradicting_span_ids: list[str] = field(default_factory=list)
    qualifiers: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    report_section: str = ""


@dataclass(frozen=True, kw_only=True)
class Calculation(Record):
    calculation_id: str
    operation: str
    formula_version: str
    scenario: str
    input_fact_ids: dict[str, str]
    outputs: dict[str, str]
    output_units: dict[str, str]
    rounding_policy: str = "Full precision; Decimal ROUND_HALF_UP to 0.01 for display"
    reconciliation_tolerance: str = "0.00000001"
    status: str = "completed"
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self):
        super().__post_init__()
        for value in self.outputs.values():
            decimal(value)
        if decimal(self.reconciliation_tolerance) < 0:
            raise ValueError("Negative reconciliation tolerance")


@dataclass(frozen=True, kw_only=True)
class Rule(Record):
    rule_id: str
    version: int
    name: str
    purpose: str
    origin: Origin
    status: Literal["experimental", "reviewed", "rejected"]
    applies_when: str
    does_not_apply_when: str
    required_inputs: list[str]
    actions: list[str]
    outputs: list[str]
    checks: list[str]
    on_missing: str
    supporting_report_span_ids: list[str]
    confidence: str
    alternatives: list[str] = field(default_factory=list)
    expert_review_ids: list[str] = field(default_factory=list)
    counterexamples: list[str] = field(default_factory=list)
    experiment_history: list[str] = field(default_factory=list)

    def __post_init__(self):
        super().__post_init__()
        if self.version < 1 or not self.actions or not self.checks:
            raise ValueError("Rules require a version, executable actions, and observable checks")
        if self.origin == "inferred" and not self.supporting_report_span_ids:
            raise ValueError("Inferred rules require discovery evidence")


@dataclass(frozen=True, kw_only=True)
class SourceRef(Record):
    document_id: str
    content_sha256: str

    def __post_init__(self):
        super().__post_init__()
        sha256(self.content_sha256)
        if self.document_id != "doc_" + self.content_sha256:
            raise ValueError("Source manifest identity mismatch")


@dataclass(frozen=True, kw_only=True)
class Task(Record):
    task_id: str
    entity_id: str
    question: str
    as_of: str
    allowed_sources: list[SourceRef]
    report_family: str = "earnings_update"
    evaluation_track: Literal["development_supplied_evidence"] = "development_supplied_evidence"
    required_sections: list[str] = field(default_factory=lambda: ["Estimate bridge", "Margin sensitivity", "Assumptions and gaps"])
    output_word_budget: int = 1500

    def __post_init__(self):
        super().__post_init__()
        timestamp(self.as_of)
        if len({s.document_id for s in self.allowed_sources}) != len(self.allowed_sources):
            raise ValueError("Duplicate source references")
        if self.output_word_budget < 1:
            raise ValueError("Output word budget must be positive")


@dataclass(frozen=True, kw_only=True)
class BudgetLimits(Record):
    max_elapsed_seconds: int = 30
    max_model_calls: int = 0
    max_tool_calls: int = 40
    max_tokens: int = 0
    max_repair_rounds: int = 0
    max_cost_usd: str = "0"

    def __post_init__(self):
        super().__post_init__()
        for value in (self.max_elapsed_seconds, self.max_model_calls, self.max_tool_calls,
                      self.max_tokens, self.max_repair_rounds):
            if type(value) is not int or value < 0:
                raise ValueError("Budget caps must be nonnegative integers")
        if decimal(self.max_cost_usd) < 0:
            raise ValueError("Cost cap must be nonnegative")


@dataclass(frozen=True, kw_only=True)
class Issue(Record):
    code: str
    message: str
    stage: str
    severity: Literal["critical", "warning"] = "critical"
    artifact_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class RunRecord(Record):
    run_id: str
    task_id: str
    variant: str
    started_at: str
    ended_at: str
    status: Literal["completed", "incomplete", "failed", "budget_exhausted"]
    stopping_reason: str
    protocol_hash: str
    task_hash: str
    playbook_hash: str
    code_hash: str
    dependency_lock_hash: str
    provider: str
    model_id: str
    budget: BudgetLimits
    usage: dict[str, str]
    source_manifest_hash: str
    workflow_version: str = "fixture_v1"
    prompt_hash: str | None = None
    generation_parameters: dict[str, str] = field(default_factory=dict)
    permitted_tools: list[str] = field(default_factory=lambda: ["get_financial_facts", "read_source_span", "run_calculation"])
    parser_version: str = "native_text_csv_v1"
    replicate: int = 1
