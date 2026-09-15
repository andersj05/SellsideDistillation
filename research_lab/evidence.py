"""Build a generator capability containing only allowlisted, timely evidence."""

from copy import deepcopy
from dataclasses import dataclass, field

from .corpus import Corpus, facts_from_spans
from .schemas import Document, EvidenceSpan, Fact, Issue, Task, timestamp


class AccessDenied(ValueError):
    pass


@dataclass(frozen=True)
class EvidencePacket:
    documents: list[Document] = field(default_factory=list)
    spans: list[EvidenceSpan] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


def build_packet(corpus: Corpus, task: Task) -> EvidencePacket:
    documents, spans, facts, issues = [], [], [], []
    cutoff = timestamp(task.as_of)
    for reference in task.allowed_sources:
        document = corpus.document(reference.document_id)
        # Check policy and dates BEFORE reading bytes or parsing content.
        if document.role != "development":
            raise AccessDenied("Generator sources must belong to the development evidence split")
        if reference.content_sha256 != document.content_sha256:
            raise AccessDenied("Allowed-source manifest hash mismatch")
        if document.available_at is None or timestamp(document.available_at) > cutoff:
            code = "unknown_availability" if document.available_at is None else "late_source"
            issues.append(
                Issue(
                    code=code,
                    message="A source was withheld by the information cutoff.",
                    stage="retrieval",
                    artifact_id=document.document_id,
                )
            )
            continue
        source_spans = corpus.spans(document.document_id)
        source_facts = facts_from_spans(source_spans)
        withheld_spans = set()
        kept_facts = []
        for fact in source_facts:
            if fact.available_at is None or timestamp(fact.available_at) > cutoff:
                withheld_spans.update(fact.source_span_ids)
                issues.append(
                    Issue(
                        code="fact_availability",
                        stage="retrieval",
                        artifact_id=fact.fact_id,
                        message="A financial row was withheld by the information cutoff.",
                    )
                )
            elif fact.entity_id != task.entity_id:
                withheld_spans.update(fact.source_span_ids)
                issues.append(
                    Issue(
                        code="entity_mismatch",
                        stage="normalization",
                        artifact_id=fact.fact_id,
                        message="A financial row belongs to a different entity.",
                    )
                )
            else:
                kept_facts.append(fact)
        spans.extend(s for s in source_spans if s.span_id not in withheld_spans)
        facts.extend(kept_facts)
        documents.append(document)
    return EvidencePacket(documents, spans, facts, issues)


class EvidenceView:
    """Tool boundary, not an OS sandbox. Never supply a host-filesystem tool to an adapter."""

    def __init__(self, packet: EvidencePacket, meter):
        self._facts = {f.fact_id: deepcopy(f) for f in packet.facts}
        self._spans = {s.span_id: deepcopy(s) for s in packet.spans}
        self._meter = meter

    def get_financial_facts(self, scenario: str) -> list[Fact]:
        self._meter.reserve(tool_calls=1)
        return deepcopy([f for f in self._facts.values() if f.scenario == scenario])

    def read_source_span(self, span_id: str) -> EvidenceSpan:
        self._meter.reserve(tool_calls=1)
        if span_id not in self._spans:
            raise AccessDenied("Source span is outside this task's allowed evidence")
        return deepcopy(self._spans[span_id])

    def search_evidence(self, query: str) -> list[EvidenceSpan]:
        self._meter.reserve(tool_calls=1)
        words = set(query.casefold().split())
        matches = [
            s for s in self._spans.values() if words and all(w in s.text.casefold() for w in words)
        ]
        return deepcopy(matches)
