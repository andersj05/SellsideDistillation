"""A reviewable synthetic dissection and versioned rule selection."""

from dataclasses import asdict
from typing import Any

from .corpus import Corpus
from .fixtures import PROJECT
from .schemas import Rule
from .serde import digest, from_dict, read_json, write_json


def dissect(corpus: Corpus, document_id: str) -> dict:
    document = corpus.document(document_id)
    if document.role != "discovery":
        raise ValueError("Dissection requires a discovery document")
    if document.original_filename.lower().endswith(".pdf"):
        return dissect_pdf(corpus, document_id)
    spans = corpus.spans(document_id)
    fixture_hash = digest((PROJECT / "fixtures" / "discovery" / "report.md").read_bytes())
    synthetic = document.content_sha256 == fixture_hash
    bundle: dict[str, Any] = {
        "schema_version": "1.0",
        "document_id": document_id,
        "synthetic": synthetic,
        "review_status": "pending_human_review",
        "sections": [
            {"title": s.text.lstrip("# "), "span_id": s.span_id}
            for s in spans
            if s.text.startswith("#")
        ],
        "observations": [
            {
                "text": s.text,
                "span_id": s.span_id,
                "origin": "observed",
                "verification_status": "unverified",
                "meaning": "Transcription only",
            }
            for s in spans
            if not s.text.startswith("#")
        ],
        "candidate_rules": [],
        "unknowns": [
            "The author's actual research process is unknown.",
        ],
        "expert_questions": [
            "Which source relationships and definitions matter for the intended research task?",
            "Which transcriptions and assumptions need independent review?",
        ],
    }
    if synthetic:
        bundle["unknowns"].append(
            "Scenario selection and market support for the multiple are unestablished."
        )
        source = next(s for s in spans if s.text.startswith("Revenue, interest"))
        rule = Rule(
            rule_id="synthetic_single_driver_sensitivity",
            version=1,
            name="Check that a margin sensitivity holds other inputs fixed",
            purpose="Distinguish margin sensitivity from simultaneous changes in several assumptions.",
            origin="inferred",
            status="experimental",
            applies_when="The synthetic note's base and downside scenarios are being compared.",
            does_not_apply_when="The scenarios intentionally change several drivers together.",
            required_inputs=["base_forecast", "downside_forecast"],
            actions=["validate_single_driver"],
            outputs=["scenario_comparability_check"],
            checks=["only_operating_margin_changes"],
            on_missing="Preserve the comparison gap and mark the run incomplete.",
            supporting_report_span_ids=[source.span_id],
            confidence="Low: plausible inference from an invented note; no empirical transfer evidence.",
            alternatives=[
                "The scenario may have been supplied externally rather than selected by the author."
            ],
        )
        bundle["candidate_rules"] = [asdict(rule)]
    else:
        bundle["unknowns"].append(
            "Automatic methodology inference is not implemented for real reports."
        )
    write_json(corpus.derived / f"{document_id}.dissection.json", bundle)
    return bundle


def dissect_pdf(corpus: Corpus, document_id: str) -> dict:
    captured = corpus.pdf_extraction(document_id)
    if captured is None:
        raise ValueError("PDF dissection requires a registered extract-pdf capture")
    directory, manifest = captured
    pages = [read_json(path) for path in sorted((directory / "pages").glob("page_*.json"))]
    bundle = {
        "schema_version": "1.0",
        "document_id": document_id,
        "synthetic": False,
        "extraction_id": manifest["extraction_id"],
        "review_status": "pending_human_review",
        "sections": [
            {
                "page_index": p["page_index"],
                "heading_word_candidates": [
                    {"text": w["text"], "span_id": w["word_id"], "bbox": w["bbox"]}
                    for w in p["words"]
                    if w["word_id"] in set(p["heading_word_candidates"])
                ],
                "status": "font_size_candidates_not_verified_headings",
            }
            for p in pages
        ],
        "observations": [
            {
                "page_index": p["page_index"],
                "native_word_count": p["native_word_count"],
                "ocr_word_count": p["ocr_word_count"],
                "image_count": p["image_count"],
                "issues": p["issues"],
                "origin": "observed",
                "verification_status": "unverified",
            }
            for p in pages
        ],
        "candidate_rules": [],
        "evidence_file": str(directory / "spans.jsonl"),
        "review": str(directory / "review.html"),
        "unknowns": [
            "OCR, headers, periods, units, chart values, and source relationships need review.",
            "The author's actual production process is unknown.",
        ],
        "scope": "Detailed source capture. Analytical methods remain dependent on each task/company; no reusable workflow is inferred.",
    }
    write_json(corpus.derived / f"{document_id}.dissection.json", bundle)
    return bundle


def load_playbook(corpus: Corpus, variant: str) -> dict:
    if variant not in ("generic", "candidate"):
        raise ValueError("Only generic and synthetic candidate fixture variants are implemented")
    generic = read_json(PROJECT / "playbooks" / "generic" / "v1.json")
    rules = [from_dict(Rule, rule) for rule in generic["rules"]]
    dissection = None
    if variant == "candidate":
        source = corpus.ingest(
            PROJECT / "fixtures" / "discovery" / "report.md",
            role="discovery",
            report_family="earnings_update",
        )
        dissection = dissect(corpus, source.document_id)
        rules.extend(from_dict(Rule, rule) for rule in dissection["candidate_rules"])
    return {
        "schema_version": "1.0",
        "playbook_id": variant + "_v1",
        "synthetic": True,
        "rules": [asdict(rule) for rule in rules],
        "dissection": dissection,
        "scope": "Mechanics demonstration; report-derived methodology and expert review pending.",
    }
