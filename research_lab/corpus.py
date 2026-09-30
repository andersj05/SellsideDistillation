"""Immutable source bytes, SQLite inventory, and stable native-text locations."""

import csv
import io
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .schemas import Document, EvidenceSpan, Fact
from .serde import (
    atomic_write,
    digest,
    encode,
    from_dict,
    load_json,
    object_hash,
    write_json,
)

SUPPORTED_INPUTS = {".md", ".txt", ".csv", ".pdf"}
MAX_SOURCE_BYTES = 64 * 1024 * 1024
FACT_COLUMNS = (
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


def now() -> str:
    return datetime.now(UTC).isoformat()


def read_source(path: Path) -> bytes:
    with path.open("rb") as handle:
        payload = handle.read(MAX_SOURCE_BYTES + 1)
    if len(payload) > MAX_SOURCE_BYTES:
        raise ValueError("Source exceeds the 64 MiB intake limit")
    return payload


def extract(document: Document, payload: bytes) -> list[EvidenceSpan]:
    suffix = Path(document.original_filename).suffix.lower()
    if suffix == ".pdf":
        return []  # Retain the PDF; do not fabricate locations without a parser.
    text = payload.decode("utf-8-sig")
    if suffix == ".csv":
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("CSV requires unique column names")
        records: list[tuple[str, str, Literal["csv_record", "text_lines"]]] = []
        for number, row in enumerate(reader, start=1):
            if None in row or None in row.values():
                raise ValueError(f"Malformed CSV record {number}")
            records.append((f"record:{number}", json.dumps(row, sort_keys=True), "csv_record"))
    else:
        records = [
            (f"line:{n}", line, "text_lines")
            for n, line in enumerate(text.splitlines(), start=1)
            if line.strip()
        ]
    return [
        EvidenceSpan(
            span_id=f"{document.document_id}:{locator}",
            document_id=document.document_id,
            document_sha256=document.content_sha256,
            text=body,
            excerpt=body[:300],
            location_kind=kind,
            locator=locator,
            extraction_method="csv_dictreader_v1" if kind == "csv_record" else "utf8_lines_v1",
        )
        for locator, body, kind in records
    ]


def facts_from_spans(spans: list[EvidenceSpan]) -> list[Fact]:
    facts = []
    for span in spans:
        if span.location_kind != "csv_record":
            continue
        row = json.loads(span.text)
        if not set(FACT_COLUMNS).issubset(row):
            continue  # Ordinary CSV is still inspectable; only the documented schema becomes facts.
        values = {key: row[key] for key in FACT_COLUMNS}
        values["available_at"] = values["available_at"] or None
        facts.append(
            from_dict(
                Fact,
                {
                    **values,
                    "fact_id": "fact_" + digest(span.span_id.encode()),
                    "source_span_ids": [span.span_id],
                },
            )
        )
    return facts


class Corpus:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.data = self.root / "data"
        self.originals = self.data / "originals"
        self.derived = self.data / "derived"
        for directory in (self.originals, self.derived, self.data / "incoming"):
            directory.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data / "corpus.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR IGNORE INTO metadata VALUES ('schema_version', '1.0');
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL, manifest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS aliases (
                    document_id TEXT NOT NULL, filename TEXT NOT NULL,
                    PRIMARY KEY (document_id, filename));
                CREATE TABLE IF NOT EXISTS pdf_extractions (
                    extraction_id TEXT PRIMARY KEY, document_id TEXT NOT NULL,
                    manifest_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS active_pdf_extractions (
                    document_id TEXT PRIMARY KEY, extraction_id TEXT NOT NULL);
            """)
            if (
                db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
                != "1.0"
            ):
                raise ValueError("Unsupported corpus schema; explicit migration required")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        # sqlite3's context manager commits/rolls back but does not close the handle.
        # Explicit closure matters on Windows and for long-running intake sessions.
        connection = sqlite3.connect(self.db_path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def ingest(
        self,
        path: Path,
        *,
        role: str,
        available_at: str | None = None,
        published_at: str | None = None,
        availability_evidence: str = "Unknown",
        report_family: str = "unknown",
    ) -> Document:
        if path.suffix.lower() not in SUPPORTED_INPUTS:
            raise ValueError(f"Unsupported input format: {path.suffix}")
        payload = read_source(path)
        content_hash = digest(payload)
        identifier = "doc_" + content_hash
        with self.connect() as db:
            # Serialize inventory/object creation across cooperating importers.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT manifest FROM documents WHERE document_id=?", (identifier,)
            ).fetchone()
            if row:
                document = from_dict(Document, load_json(row[0]))
                if document.role != role:
                    raise ValueError("Duplicate source cannot cross corpus splits")
                if available_at is not None and available_at != document.available_at:
                    raise ValueError("Duplicate source has conflicting availability metadata")
                if published_at is not None and published_at != document.published_at:
                    raise ValueError("Duplicate source has conflicting publication metadata")
                self.read_bytes(document.document_id)
                db.execute("INSERT OR IGNORE INTO aliases VALUES (?, ?)", (identifier, path.name))
                return document
            document = from_dict(
                Document,
                dict(
                    document_id=identifier,
                    content_sha256=content_hash,
                    original_filename=path.name,
                    role=role,
                    report_family=report_family,
                    ingested_at=now(),
                    published_at=published_at,
                    available_at=available_at,
                    publication_time_confidence="known" if published_at else "unknown",
                    availability_evidence=availability_evidence,
                    extraction_status="pending_parser"
                    if path.suffix.lower() == ".pdf"
                    else "extracted",
                ),
            )
            spans = extract(document, payload)
            original = self.originals / content_hash
            # Publish complete bytes atomically while holding the inventory write lock.
            if original.exists():
                if digest(read_source(original)) != content_hash:
                    raise ValueError("Corrupt source object")
            else:
                atomic_write(original, payload)
            write_json(
                self.derived / f"{identifier}.json",
                {"document": asdict(document), "spans": [asdict(s) for s in spans]},
            )
            db.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?)",
                (identifier, content_hash, role, encode(document).decode()),
            )
            db.execute("INSERT INTO aliases VALUES (?, ?)", (identifier, path.name))
        return document

    def document(self, document_id: str) -> Document:
        with self.connect() as db:
            row = db.execute(
                "SELECT manifest FROM documents WHERE document_id=?", (document_id,)
            ).fetchone()
        if row is None:
            raise ValueError("Unknown document ID")
        return from_dict(Document, load_json(row[0]))

    def read_bytes(self, document_id: str) -> bytes:
        document = self.document(document_id)
        payload = read_source(self.originals / document.content_sha256)
        if digest(payload) != document.content_sha256:
            raise ValueError("Source content hash mismatch")
        return payload

    def spans(self, document_id: str) -> list[EvidenceSpan]:
        # Re-extraction from hashed originals makes derived-cache edits non-authoritative.
        document = self.document(document_id)
        if Path(document.original_filename).suffix.lower() == ".pdf":
            captured = self.pdf_extraction(document_id)
            if captured is None:
                return []
            directory, manifest = captured
            spans = [
                from_dict(EvidenceSpan, load_json(line))
                for line in (directory / "spans.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            if len({s.span_id for s in spans}) != len(spans) or any(
                s.document_id != document_id
                or s.document_sha256 != document.content_sha256
                or s.page_index is None
                or s.page_index >= manifest["counts"]["pages"]
                for s in spans
            ):
                raise ValueError("PDF evidence lineage or span inventory mismatch")
            return spans
        return extract(document, self.read_bytes(document_id))

    def verify_pdf_directory(
        self, document_id: str, directory: Path, expected_hash: str | None = None
    ) -> dict:
        document = self.document(document_id)
        self.read_bytes(document_id)  # Verify source bytes before admitting cached observations.
        if directory.resolve().parent != (self.derived / document_id).resolve() or not re.fullmatch(
            r"extract_[a-f0-9]{32}", directory.name
        ):
            raise ValueError("PDF extraction must use a managed document directory")
        payload = (directory / "manifest.json").read_bytes()
        if expected_hash is not None and digest(payload) != expected_hash:
            raise ValueError("PDF extraction manifest integrity check failed")
        manifest = load_json(payload.decode("utf-8"))
        if (
            manifest["schema_version"] != "1.0"
            or manifest["document_id"] != document_id
            or manifest["source_sha256"] != document.content_sha256
            or manifest["extraction_id"] != directory.name
            or object_hash(manifest["recipe"]) != manifest["recipe_hash"]
        ):
            raise ValueError("PDF extraction identity or recipe mismatch")
        files = manifest["files"]
        actual = {
            p.relative_to(directory).as_posix()
            for p in directory.rglob("*")
            if p.is_file() and p.name != "manifest.json"
        }
        if set(files) != actual or not {
            "spans.jsonl",
            "pages.jsonl",
            "tables.jsonl",
            "review.html",
        } <= set(files):
            raise ValueError("PDF extraction file inventory mismatch")
        for name, expected in files.items():
            candidate = directory / name
            path = candidate.resolve()
            if (
                not path.is_relative_to(directory.resolve())
                or candidate.is_symlink()
                or digest(path.read_bytes()) != expected
            ):
                raise ValueError("PDF extraction artifact integrity check failed")
        return manifest

    def pdf_extraction(self, document_id: str) -> tuple[Path, dict] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT e.extraction_id, e.manifest_hash FROM pdf_extractions e "
                "JOIN active_pdf_extractions a ON a.extraction_id=e.extraction_id "
                "WHERE a.document_id=? AND e.document_id=?",
                (document_id, document_id),
            ).fetchone()
        if row is None:
            return None
        directory = self.derived / document_id / row[0]
        return directory, self.verify_pdf_directory(document_id, directory, row[1])

    def register_pdf_extraction(self, document_id: str, directory: Path) -> None:
        manifest = self.verify_pdf_directory(document_id, directory)
        document = replace(
            self.document(document_id),
            page_count=manifest["counts"]["pages"],
            extraction_status="extracted",
            review_status="pending_semantic_review",
        )
        with self.connect() as db:
            db.execute(
                "INSERT INTO pdf_extractions VALUES (?, ?, ?)",
                (directory.name, document_id, digest((directory / "manifest.json").read_bytes())),
            )
            db.execute(
                "INSERT OR REPLACE INTO active_pdf_extractions VALUES (?, ?)",
                (document_id, directory.name),
            )
            db.execute(
                "UPDATE documents SET manifest=? WHERE document_id=?",
                (encode(document).decode(), document_id),
            )

    def inventory(self) -> list[Document]:
        with self.connect() as db:
            rows = db.execute("SELECT manifest FROM documents ORDER BY document_id").fetchall()
        return [from_dict(Document, load_json(row[0])) for row in rows]
