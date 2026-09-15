"""Immutable source bytes, SQLite inventory, and stable native-text locations."""

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import io
import json
import sqlite3

from .schemas import Document, EvidenceSpan, Fact
from .serde import digest, encode, from_dict, write_json

SUPPORTED_INPUTS = {".md", ".txt", ".csv", ".pdf"}
FACT_COLUMNS = ("entity_id", "metric", "value", "displayed_value", "unit", "scale",
                "period_start", "period_end", "period_type", "accounting_basis",
                "value_type", "scenario", "available_at")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract(document: Document, payload: bytes) -> list[EvidenceSpan]:
    suffix = Path(document.original_filename).suffix.lower()
    if suffix == ".pdf":
        return []  # Retain the PDF; do not fabricate locations without a parser.
    text = payload.decode("utf-8-sig")
    if suffix == ".csv":
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("CSV requires unique column names")
        records = []
        for number, row in enumerate(reader, start=1):
            if None in row or None in row.values():
                raise ValueError(f"Malformed CSV record {number}")
            records.append((f"record:{number}", json.dumps(row, sort_keys=True), "csv_record"))
    else:
        records = [(f"line:{n}", line, "text_lines")
                   for n, line in enumerate(text.splitlines(), start=1) if line.strip()]
    return [EvidenceSpan(span_id=f"{document.document_id}:{locator}",
                         document_id=document.document_id, document_sha256=document.content_sha256,
                         text=body, excerpt=body[:300], location_kind=kind, locator=locator,
                         extraction_method="csv_dictreader_v1" if kind == "csv_record" else "utf8_lines_v1")
            for locator, body, kind in records]


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
        facts.append(from_dict(Fact, {**values, "fact_id": "fact_" + digest(span.span_id.encode()),
                                     "source_span_ids": [span.span_id]}))
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
            """)
            if db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0] != "1.0":
                raise ValueError("Unsupported corpus schema; explicit migration required")

    @contextmanager
    def connect(self):
        # sqlite3's context manager commits/rolls back but does not close the handle.
        # Explicit closure matters on Windows and for long-running intake sessions.
        connection = sqlite3.connect(self.db_path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def ingest(self, path: Path, *, role: str, available_at: str | None = None,
               published_at: str | None = None, availability_evidence: str = "Unknown",
               report_family: str = "unknown") -> Document:
        if path.suffix.lower() not in SUPPORTED_INPUTS:
            raise ValueError(f"Unsupported input format: {path.suffix}")
        payload = path.read_bytes()
        content_hash = digest(payload)
        identifier = "doc_" + content_hash
        with self.connect() as db:
            row = db.execute("SELECT manifest FROM documents WHERE document_id=?", (identifier,)).fetchone()
            if row:
                document = from_dict(Document, json.loads(row[0]))
                if document.role != role:
                    raise ValueError("Duplicate source cannot cross corpus splits")
                if available_at is not None and available_at != document.available_at:
                    raise ValueError("Duplicate source has conflicting availability metadata")
                if published_at is not None and published_at != document.published_at:
                    raise ValueError("Duplicate source has conflicting publication metadata")
                self.read_bytes(document.document_id)
                db.execute("INSERT OR IGNORE INTO aliases VALUES (?, ?)", (identifier, path.name))
                return document
            document = from_dict(Document, dict(document_id=identifier, content_sha256=content_hash,
                original_filename=path.name, role=role, report_family=report_family,
                ingested_at=now(), published_at=published_at, available_at=available_at,
                publication_time_confidence="known" if published_at else "unknown",
                availability_evidence=availability_evidence,
                extraction_status="pending_parser" if path.suffix.lower() == ".pdf" else "extracted"))
            spans = extract(document, payload)
            original = self.originals / content_hash
            # Exclusive create prevents source replacement. An existing object must be identical.
            try:
                with original.open("xb") as handle:
                    handle.write(payload)
            except FileExistsError:
                if digest(original.read_bytes()) != content_hash:
                    raise ValueError("Corrupt source object")
            write_json(self.derived / f"{identifier}.json", {"document": asdict(document),
                                                          "spans": [asdict(s) for s in spans]})
            db.execute("INSERT INTO documents VALUES (?, ?, ?, ?)",
                       (identifier, content_hash, role, encode(document).decode()))
            db.execute("INSERT INTO aliases VALUES (?, ?)", (identifier, path.name))
        return document

    def document(self, document_id: str) -> Document:
        with self.connect() as db:
            row = db.execute("SELECT manifest FROM documents WHERE document_id=?", (document_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown document ID")
        return from_dict(Document, json.loads(row[0]))

    def read_bytes(self, document_id: str) -> bytes:
        document = self.document(document_id)
        payload = (self.originals / document.content_sha256).read_bytes()
        if digest(payload) != document.content_sha256:
            raise ValueError("Source content hash mismatch")
        return payload

    def spans(self, document_id: str) -> list[EvidenceSpan]:
        # Re-extraction from hashed originals makes derived-cache edits non-authoritative.
        document = self.document(document_id)
        return extract(document, self.read_bytes(document_id))

    def inventory(self) -> list[Document]:
        with self.connect() as db:
            rows = db.execute("SELECT manifest FROM documents ORDER BY document_id").fetchall()
        return [from_dict(Document, json.loads(row[0])) for row in rows]
