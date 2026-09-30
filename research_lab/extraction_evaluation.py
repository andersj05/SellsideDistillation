"""Separate extraction coverage grading against optional reviewer-supplied anchors.

The extractor never receives this reference file. Presence checks do not grade
financial correctness, table semantics, citation entailment, or research usefulness.
"""

from pathlib import Path

from .corpus import Corpus
from .serde import digest, object_hash, read_json


def evaluate_extraction(
    corpus: Corpus, document_id: str, reference_path: Path | None = None
) -> dict:
    captured = corpus.pdf_extraction(document_id)
    if captured is None:
        raise ValueError("No registered PDF extraction is available")
    directory, manifest = captured
    spans = corpus.spans(document_id)
    checks = []
    reference_hash = None
    reference_review = "not_supplied"
    if reference_path is not None:
        reference = read_json(reference_path)
        reference_hash = object_hash(reference)
        if (
            not isinstance(reference, dict)
            or reference.get("schema_version") != "1.0"
            or reference.get("document_sha256") != manifest["source_sha256"]
        ):
            raise ValueError("Extraction reference belongs to a different source or schema")
        review_status = reference.get("review_status")
        if review_status not in ("draft", "reviewed"):
            raise ValueError("Reference review status must be draft or reviewed")
        reference_review = str(review_status)
        items = reference.get("checks")
        if not isinstance(items, list):
            raise ValueError("Reference checks must be a list")
        identifiers = set()
        for check in items:
            if (
                not isinstance(check, dict)
                or not isinstance(check.get("check_id"), str)
                or not check["check_id"].strip()
                or check["check_id"] in identifiers
                or not isinstance(check.get("expected_text"), str)
                or not check["expected_text"].strip()
            ):
                raise ValueError("Reference checks require unique IDs and nonempty text")
            identifiers.add(check["check_id"])
            page = check.get("page_index")
            if type(page) is not int or not 0 <= page < manifest["counts"]["pages"]:
                raise ValueError("Reference page is outside the PDF")
            box = check.get("bbox", [0.0, 0.0, 1.0, 1.0])
            if (
                not isinstance(box, list)
                or len(box) != 4
                or not all(type(v) in (int, float) and 0 <= v <= 1 for v in box)
                or box[0] > box[2]
                or box[1] > box[3]
            ):
                raise ValueError("Invalid reference bounding box")
            hits = [
                s.span_id
                for s in spans
                if s.page_index == page
                and s.text == check["expected_text"]
                and s.bbox is not None
                and box[0] <= (s.bbox[0] + s.bbox[2]) / 2 <= box[2]
                and box[1] <= (s.bbox[1] + s.bbox[3]) / 2 <= box[3]
            ]
            checks.append(
                {
                    "check_id": check["check_id"],
                    "page_index": page,
                    "expected_text": check["expected_text"],
                    "passed": bool(hits),
                    "matching_span_ids": hits,
                }
            )
    return {
        "schema_version": "1.0",
        "grader": "located_exact_text_presence_v1",
        "grader_code_hash": digest(Path(__file__).read_bytes()),
        "document_id": document_id,
        "extraction_id": manifest["extraction_id"],
        "manifest_hash": digest((directory / "manifest.json").read_bytes()),
        "integrity": "verified_against_corpus_registration",
        "counts": manifest["counts"],
        "reference_hash": reference_hash,
        "reference_review": reference_review,
        "checks": checks,
        "status": "unassessed"
        if not checks
        else "needs_review"
        if not all(c["passed"] for c in checks)
        else "reference_checks_passed"
        if reference_review == "reviewed"
        else "draft_reference_checks_passed",
        "limitations": [
            "Exact located text presence only; no claim entailment or numerical correctness grade.",
            "The optional reference is separately supplied; draft anchors are not approved gold.",
            "Full table structure, chart data, analytical usefulness, and expert review are unassessed.",
        ],
    }
