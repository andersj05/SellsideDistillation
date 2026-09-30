"""Detailed local PDF capture, with unverified text/geometry and explicit review gaps."""

import importlib
import io
import math
import re
import statistics
import sys
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

from .corpus import Corpus, now
from .extraction_review import render_index, render_page
from .ocr import recognize, select_engine
from .schemas import Document, EvidenceSpan
from .serde import atomic_write, digest, object_hash, write_json, write_jsonl

MAX_PAGES = 500
MAX_WORDS_PER_PAGE = 50000


@dataclass(frozen=True)
class ExtractionOptions:
    ocr: str = "auto"
    dpi: int = 300
    image_ocr: bool = True

    def __post_init__(self) -> None:
        if self.ocr not in ("auto", "none", "windows", "tesseract"):
            raise ValueError("Unknown OCR mode")
        if type(self.dpi) is not int or not 96 <= self.dpi <= 300:
            raise ValueError("PDF rendering DPI must be an integer between 96 and 300")


def normalized_box(box: list | tuple, width: float, height: float) -> list[float]:
    if len(box) != 4 or width <= 0 or height <= 0 or not all(math.isfinite(x) for x in box):
        raise ValueError("Invalid source geometry")
    if box[0] > box[2] or box[1] > box[3]:
        raise ValueError("Inverted source geometry")
    return [
        round(max(0.0, min(1.0, float(value) / dimension)), 9)
        for value, dimension in zip(box, (width, height, width, height), strict=True)
    ]


def issue(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message, "status": "pending_review"}


def recipe(options: ExtractionOptions, engine: dict | None) -> dict:
    directory = Path(__file__).parent
    return {
        "schema_version": "1.0",
        "extractor": "pdf_capture_v1",
        "options": asdict(options),
        "parsers": {
            name: version(name) for name in ("pdfplumber", "pdfminer-six", "pypdfium2", "Pillow")
        },
        "ocr_engine": engine,
        "implementation_hash": digest(
            b"".join(
                (directory / name).read_bytes()
                for name in (
                    "pdf_extraction.py",
                    "ocr.py",
                    "extraction_review.py",
                    "schemas.py",
                    "serde.py",
                )
            )
        ),
        "verification": "Transcription only; no automatic fact or gold-label promotion.",
    }


def word_record(
    text: str, box: list[float], prefix: str, index: int, channel: str, **attributes: Any
) -> dict:
    return {
        "word_id": f"{prefix}:word:{index}",
        "text": text,
        "bbox": box,
        "channel": channel,
        "verification_status": "unverified",
        **attributes,
    }


def line_groups(words: list[dict], height: float) -> list[list[dict]]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for word in words:
        key = (word["source_region"], word.get("line", round(word["bbox"][1] * height / 3)))
        groups[key].append(word)
    return [sorted(group, key=lambda w: w["bbox"][0]) for group in groups.values()]


def make_spans(document: Document, record: dict, method: str) -> list[EvidenceSpan]:
    words = record["words"]
    spans = []

    def span(identifier: str, text: str, box: list[float], channel: str) -> EvidenceSpan:
        return EvidenceSpan(
            span_id=identifier,
            document_id=document.document_id,
            document_sha256=document.content_sha256,
            text=text,
            excerpt=text[:300],
            location_kind="pdf_page",
            locator=identifier.removeprefix(document.document_id + ":"),
            page_index=record["page_index"],
            printed_page_label=record["printed_page_label"],
            bbox=box,
            coordinate_system="normalized_top_left",
            extraction_method=method + ":" + channel,
        )

    for index, group in enumerate(line_groups(words, record["height_points"])):
        identifier = f"{document.document_id}:{method}:page:{record['page_index']}:line:{index}"
        box = [
            min(w["bbox"][0] for w in group),
            min(w["bbox"][1] for w in group),
            max(w["bbox"][2] for w in group),
            max(w["bbox"][3] for w in group),
        ]
        spans.append(span(identifier, " ".join(w["text"] for w in group), box, group[0]["channel"]))
        for word in group:
            word["line_span_id"] = identifier
            spans.append(span(word["word_id"], word["text"], word["bbox"], word["channel"]))
    return spans


def native_capture(
    page: Any, document: Document, page_index: int, prefix: str
) -> tuple[dict, list[dict]]:
    width, height = float(page.width), float(page.height)
    source_words = page.extract_words(extra_attrs=["fontname", "size"])
    if len(source_words) > MAX_WORDS_PER_PAGE:
        raise ValueError("PDF page exceeds the native word limit")
    words = [
        word_record(
            w["text"],
            normalized_box([w["x0"], w["top"], w["x1"], w["bottom"]], width, height),
            prefix + ":native",
            i,
            "native",
            font=w["fontname"],
            font_size=float(w["size"]),
            upright=w["upright"],
            source_region="native_page",
        )
        for i, w in enumerate(source_words)
        if w["text"].strip()
    ]
    labels = [
        w
        for w in words
        if w["text"].isdigit()
        and len(w["text"]) <= 3
        and w["bbox"][1] > 0.8
        and (w["bbox"][0] < 0.1 or w["bbox"][0] > 0.85)
    ]
    images = [
        {
            "image_index": i,
            "bbox": normalized_box([im["x0"], im["top"], im["x1"], im["bottom"]], width, height),
            "source_pixel_size": list(im.get("srcsize", ())),
            "bits": im.get("bits"),
            "verification_status": "unverified",
        }
        for i, im in enumerate(page.images)
    ]
    issues = []
    if any(re.fullmatch(r"[0-9,.%]{18,}", w["text"]) for w in words):
        issues.append(
            issue(
                "native_numeric_run",
                "Long merged numeric tokens suggest a damaged or overlapping native text layer.",
            )
        )
    if len(words) < 20:
        issues.append(
            issue(
                "native_text_sparse",
                "Sparse native text: image content or section divider requires review.",
            )
        )
    if any(not w["upright"] for w in words):
        issues.append(issue("rotated_native_text", "Rotated text reading order requires review."))
    tables = []
    for index, table in enumerate(page.find_tables()):
        rows = table.extract()
        cells = []
        for row_index, row in enumerate(table.rows):
            for column_index, box in enumerate(row.cells):
                if box is None:
                    continue
                location = normalized_box(box, width, height)
                cell_words = [
                    w["word_id"]
                    for w in words
                    if location[0] <= (w["bbox"][0] + w["bbox"][2]) / 2 <= location[2]
                    and location[1] <= (w["bbox"][1] + w["bbox"][3]) / 2 <= location[3]
                ]
                cells.append(
                    {
                        "row": row_index,
                        "column": column_index,
                        "bbox": location,
                        "text": rows[row_index][column_index],
                        "word_ids": cell_words,
                    }
                )
        tables.append(
            {
                "document_id": document.document_id,
                "page_index": page_index,
                "table_index": index,
                "bbox": normalized_box(table.bbox, width, height),
                "rows": rows,
                "cells": cells,
                "method": "pdfplumber_default_lines",
                "status": "candidate_pending_review",
                "header_semantics": "Unassigned; preserve merged-header context from the page.",
            }
        )
    if tables and any(len(t["rows"]) <= 2 for t in tables):
        issues.append(
            issue(
                "table_fragment_candidates",
                "Short detected tables may be row fragments or non-table graphics.",
            )
        )
    # Drawing geometry supplements the retained page image; it is not inferred chart-series data.
    graphics = [
        {
            "kind": kind,
            "bbox": normalized_box([g["x0"], g["top"], g["x1"], g["bottom"]], width, height),
            "points": [list(point) for point in g.get("pts", [])],
            "linewidth": g.get("linewidth"),
        }
        for kind in ("lines", "rects", "curves")
        for g in getattr(page, kind)
    ]
    hyperlinks = [
        {
            "uri": str(link.get("uri", "")),
            "bbox": normalized_box(
                [link["x0"], link["top"], link["x1"], link["bottom"]], width, height
            ),
        }
        for link in page.hyperlinks
    ]
    sizes = [w["font_size"] for w in words]
    heading_words = [
        w["word_id"] for w in words if sizes and w["font_size"] >= statistics.median(sizes) + 2
    ]
    return {
        "page_index": page_index,
        "width_points": width,
        "height_points": height,
        "rotation": page.rotation,
        "native_text": page.extract_text() or "",
        "ocr_text": "",
        "words": words,
        "images": images,
        "image_count": len(images),
        "graphics": graphics,
        "hyperlinks": hyperlinks,
        "heading_word_candidates": heading_words,
        "printed_page_label_candidates": labels,
        "printed_page_label": labels[0]["text"] if len(labels) == 1 else None,
        "issues": issues,
        "native_word_count": len(words),
        "ocr_word_count": 0,
        "semantic_review": "unassessed",
    }, tables


def save_image(image: Any, path: Path) -> None:
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    atomic_write(path, stream.getvalue())


def ocr_jobs(
    image: Any, record: dict, directory: Path, engine: dict, image_ocr: bool
) -> list[dict]:
    number = record["page_index"] + 1
    jobs = [
        {
            "id": "full_page",
            "path": str((directory / f"page_{number:03d}.png").resolve()),
            "pixel_size": list(image.size),
            "page_bbox": [0.0, 0.0, 1.0, 1.0],
        }
    ]
    for region in record["images"]:
        box = region["bbox"]
        if (box[2] - box[0]) * (box[3] - box[1]) < 0.015:
            continue  # Tiny logos are still retained in the page image and geometry.
        crop = image.crop(
            tuple(round(v * d) for v, d in zip(box, (*image.size, *image.size), strict=True))
        )
        path = directory / f"page_{number:03d}_image_{region['image_index']:03d}.png"
        region["rendered_crop"] = path.name
        # Upscaling a small embedded exhibit helps OCR without adding source detail.
        factor = min(2.0, engine["max_dimension"] / max(crop.size))
        crop = crop.resize(
            (max(1, round(crop.width * factor)), max(1, round(crop.height * factor)))
        )
        save_image(crop, path)
        if image_ocr:
            jobs.append(
                {
                    "id": f"image_{region['image_index']}",
                    "path": str(path.resolve()),
                    "pixel_size": list(crop.size),
                    "page_bbox": box,
                }
            )
        crop.close()
    return jobs


def add_ocr(record: dict, jobs: list[dict], results: list[dict], prefix: str) -> None:
    by_id = {result["id"]: result for result in results}
    if len(by_id) != len(results) or set(by_id) != {job["id"] for job in jobs}:
        raise ValueError("OCR job/result inventory mismatch")
    for job in jobs:
        result = by_id[job["id"]]
        if result.get("error"):
            record["issues"].append(issue("ocr_error", f"{job['id']}: {result['error']}"))
            continue
        if len(result["words"]) > MAX_WORDS_PER_PAGE:
            raise ValueError("OCR result exceeds the word limit")
        page_box = job["page_bbox"]
        for index, word in enumerate(result["words"]):
            if not isinstance(word["text"], str) or not word["text"].strip():
                continue
            box = normalized_box(word["bbox"], *job["pixel_size"])
            box = [
                round(page_box[axis % 2] + value * (page_box[axis % 2 + 2] - page_box[axis % 2]), 9)
                for axis, value in enumerate(box)
            ]
            record["words"].append(
                word_record(
                    word["text"],
                    box,
                    prefix + ":ocr:" + job["id"],
                    index,
                    "ocr",
                    source_region=job["id"],
                    line=str(word["line"]),
                    confidence=word.get("confidence"),
                )
            )
        if abs(result.get("text_angle") or 0) > 0.2:
            record["issues"].append(
                issue("ocr_rotation", "OCR reports rotated text; coordinates require review.")
            )
    record["ocr_word_count"] = sum(w["channel"] == "ocr" for w in record["words"])
    record["ocr_text"] = "\n".join(
        " ".join(w["text"] for w in group)
        for group in line_groups(record["words"], record["height_points"])
        if group[0]["channel"] == "ocr"
    )


def extract_pdf(
    corpus: Corpus,
    document_id: str,
    *,
    options: ExtractionOptions | None = None,
    force: bool = False,
) -> dict:
    options = options or ExtractionOptions()
    document = corpus.document(document_id)
    if Path(document.original_filename).suffix.lower() != ".pdf":
        raise ValueError("PDF extraction requires a PDF source")
    payload = corpus.read_bytes(document_id)
    try:
        plumber = importlib.import_module("pdfplumber")
        pdfium = importlib.import_module("pypdfium2")
    except ImportError as exc:
        raise ValueError("Install the optional PDF dependencies: uv sync --extra pdf") from exc
    engine = select_engine(options.ocr)
    selected_recipe = recipe(options, engine)
    recipe_hash = object_hash(selected_recipe)
    existing = None if force else corpus.pdf_extraction(document_id)
    if existing and existing[1]["recipe_hash"] == recipe_hash:
        return {
            "document_id": document_id,
            "directory": str(existing[0]),
            "cached": True,
            **existing[1]["counts"],
        }
    extraction_id = "extract_" + uuid.uuid4().hex
    directory = corpus.derived / document_id / extraction_id
    pages_dir = directory / "pages"
    pages_dir.mkdir(parents=True, exist_ok=False)
    pages, all_tables, all_spans = [], [], []
    started = now()
    metadata = {}
    try:
        with plumber.open(io.BytesIO(payload)) as pdf, pdfium.PdfDocument(payload) as renderer:
            metadata = {str(key): str(value) for key, value in pdf.metadata.items()}
            if not 1 <= len(pdf.pages) <= MAX_PAGES or len(pdf.pages) != len(renderer):
                raise ValueError("Invalid PDF page count or parser disagreement")
            for index, page in enumerate(pdf.pages):
                prefix = f"{document_id}:pdf:{recipe_hash[:16]}:page:{index}"
                record, tables = native_capture(page, document, index, prefix)
                rendered_page = renderer[index]
                try:
                    size = rendered_page.get_size()
                    if any(
                        abs(a - b) > 1 for a, b in zip(size, (page.width, page.height), strict=True)
                    ):
                        raise ValueError(
                            "PDF parser/render page geometry mismatch; explicit crop mapping required"
                        )
                    scale = options.dpi / 72
                    if engine:
                        scale = min(scale, (engine["max_dimension"] - 1) / max(size))
                    bitmap = rendered_page.render(scale=scale)
                    try:
                        image = bitmap.to_pil().copy()
                    finally:
                        bitmap.close()
                finally:
                    rendered_page.close()
                try:
                    save_image(image, pages_dir / f"page_{index + 1:03d}.png")
                    if engine:
                        jobs = ocr_jobs(image, record, pages_dir, engine, options.image_ocr)
                        add_ocr(record, jobs, recognize(jobs, engine, directory), prefix)
                    else:
                        record["issues"].append(
                            issue(
                                "ocr_not_run",
                                "OCR was disabled or unavailable; image-only text may be missing.",
                            )
                        )
                finally:
                    image.close()
                method = "pdf_capture_v1@" + recipe_hash[:16]
                all_spans.extend(make_spans(document, record, method))
                write_json(pages_dir / f"page_{index + 1:03d}.json", record)
                render_page(pages_dir / f"page_{index + 1:03d}.html", record, tables)
                pages.append(record)
                all_tables.extend(tables)
                page.close()
                print(
                    f"Captured {document.original_filename}: page {index + 1}/{len(pdf.pages)}",
                    file=sys.stderr,
                    flush=True,
                )
        write_jsonl(directory / "pages.jsonl", pages)
        write_jsonl(directory / "tables.jsonl", all_tables)
        write_jsonl(directory / "spans.jsonl", all_spans)
        write_json(directory / "source.json", asdict(document))
        atomic_write(
            directory / "extraction.txt",
            "\n\n".join(
                f"PDF PAGE {p['page_index'] + 1}\nNATIVE TEXT\n{p['native_text']}\nOCR TEXT (UNVERIFIED)\n{p['ocr_text']}"
                for p in pages
            ).encode("utf-8"),
        )
        render_index(directory / "review.html", asdict(document), pages, selected_recipe)
        counts = {
            "pages": len(pages),
            "native_words": sum(p["native_word_count"] for p in pages),
            "ocr_words": sum(p["ocr_word_count"] for p in pages),
            "evidence_spans": len(all_spans),
            "table_candidates": len(all_tables),
            "images": sum(p["image_count"] for p in pages),
            "ocr_errors": sum(i["code"] == "ocr_error" for p in pages for i in p["issues"]),
        }
        manifest = {
            "schema_version": "1.0",
            "extraction_id": extraction_id,
            "document_id": document_id,
            "source_sha256": document.content_sha256,
            "pdf_metadata": metadata,
            "started_at": started,
            "ended_at": now(),
            "recipe": selected_recipe,
            "recipe_hash": recipe_hash,
            "counts": counts,
            "status": "captured_pending_review",
            "semantic_evaluation": "unassessed",
            "limitations": [
                "OCR and table semantics require independent review.",
                "Chart images and labels are retained; unlabeled series values are not reconstructed.",
                "Repeated native/OCR observations are preserved; confidence is not verification.",
                "No report-derived analytical rules or evaluator gold answers were inferred.",
            ],
            "files": {
                p.relative_to(directory).as_posix(): digest(p.read_bytes())
                for p in sorted(directory.rglob("*"))
                if p.is_file()
            },
        }
        write_json(directory / "manifest.json", manifest)
        corpus.register_pdf_extraction(document_id, directory)
        return {"document_id": document_id, "directory": str(directory), "cached": False, **counts}
    except Exception as exc:
        write_json(
            directory / "failure.json",
            {
                "error_type": type(exc).__name__,
                "message": str(exc),
                "completed_pages": len(pages),
                "started_at": started,
            },
        )
        raise ValueError(f"PDF capture failed: {type(exc).__name__}: {exc}") from exc
