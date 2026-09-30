"""Invented PDFs exercise capture, OCR lineage, cache integrity, and separate grading."""

import io
import json
import subprocess
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image, ImageDraw

from research_lab.cli import main, output
from research_lab.corpus import Corpus
from research_lab.evidence import build_packet
from research_lab.extraction_evaluation import evaluate_extraction
from research_lab.ocr import invoke, recognize, select_engine, tesseract_words, windows_command
from research_lab.pdf_extraction import ExtractionOptions, add_ocr, extract_pdf, normalized_box
from research_lab.playbooks import dissect
from research_lab.schemas import SourceRef, Task
from research_lab.serde import digest, read_json, write_json


def invented_pdf(path):
    image = Image.new("RGB", (480, 120), "white")
    ImageDraw.Draw(image).text((20, 30), "617 chips x USD 11 = USD 6787", fill="black")
    pixels = zlib.compress(image.tobytes())
    text = (
        b"BT /F1 16 Tf 50 380 Td (Invented <script>alert\\(1\\)</script>) Tj ET\n"
        b"50 300 m 350 300 l 350 360 l 50 360 l h S\n"
        b"180 300 m 180 360 l S 50 330 m 350 330 l S\n"
        b"BT /F1 12 Tf 60 345 Td (Metric) Tj 140 0 Td (2027e) Tj ET\n"
        b"BT /F1 12 Tf 60 315 Td (Sales) Tj 140 0 Td (123,456) Tj ET"
    )
    raster = b"q 480 0 0 120 60 100 cm /Im1 Do Q\nBT /F1 14 Tf 50 340 Td (Image-only table) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 7 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 400] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(text)).encode() + b" >>\nstream\n" + text + b"\nendstream",
        b"<< /Type /XObject /Subtype /Image /Width 480 /Height 120 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length "
        + str(len(pixels)).encode()
        + b" >>\nstream\n"
        + pixels
        + b"\nendstream",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 400] /Resources << /Font << /F1 4 0 R >> /XObject << /Im1 6 0 R >> >> /Contents 8 0 R >>",
        b"<< /Length " + str(len(raster)).encode() + b" >>\nstream\n" + raster + b"\nendstream",
    ]
    payload = b"%PDF-1.4\n"
    offsets = [0]
    for n, obj in enumerate(objects, 1):
        offsets.append(len(payload))
        payload += f"{n} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(payload)
    payload += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    payload += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    payload += (
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(payload)


def fake_ocr(jobs, engine, directory):
    return [
        {
            "id": job["id"],
            "error": None,
            "words": [
                {"text": "617", "line": "1", "bbox": [20, 20, 90, 50], "confidence": None},
                {"text": "chips", "line": "1", "bbox": [95, 20, 180, 50], "confidence": None},
            ],
        }
        for job in jobs
    ]


class PdfExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.corpus = Corpus(self.root)
        self.source = self.root / "invented.pdf"
        invented_pdf(self.source)
        self.document = self.corpus.ingest(self.source, role="discovery")

    def capture(self, ocr="none", **kwargs):
        return extract_pdf(
            self.corpus,
            self.document.document_id,
            options=ExtractionOptions(ocr=ocr, dpi=96),
            **kwargs,
        )

    def reference(self, checks, review="draft"):
        path = self.root / "private_reference.json"
        write_json(
            path,
            {
                "schema_version": "1.0",
                "document_sha256": self.document.content_sha256,
                "review_status": review,
                "checks": checks,
            },
        )
        return path

    def test_native_capture_retains_geometry_tables_visuals_and_unverified_lineage(self):
        before = self.source.read_bytes()
        result = self.capture()
        self.assertEqual(result["pages"], 2)
        self.assertGreater(result["table_candidates"], 0)
        self.assertEqual(result["images"], 1)
        spans = self.corpus.spans(self.document.document_id)
        value = next(s for s in spans if s.text == "123,456")
        self.assertEqual(value.page_index, 0)
        self.assertEqual(value.coordinate_system, "normalized_top_left")
        self.assertEqual(value.verification_status, "unverified")
        self.assertTrue(value.bbox[0] < value.bbox[2])
        directory = Path(result["directory"])
        self.assertTrue((directory / "pages/page_002.png").is_file())
        page = read_json(directory / "pages/page_001.json")
        self.assertTrue(page["graphics"])
        self.assertEqual(self.corpus.document(self.document.document_id).page_count, 2)
        self.assertEqual(self.source.read_bytes(), before)
        html = (directory / "pages/page_001.html").read_text(encoding="utf-8")
        self.assertNotIn("<script>alert", html)
        self.assertIn("\\u003cscript", html)
        self.assertIn("&lt;script&gt;", html)
        with patch(
            "research_lab.pdf_extraction.native_capture",
            side_effect=AssertionError("Reparsed cache"),
        ):
            cached = self.capture()
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["directory"], result["directory"])
        dissection = dissect(self.corpus, self.document.document_id)
        self.assertEqual(dissection["candidate_rules"], [])
        self.assertEqual(len(dissection["observations"]), 2)
        self.assertTrue(dissection["sections"][0]["heading_word_candidates"])

    def test_ocr_full_page_and_crop_observations_are_separate_and_unverified(self):
        engine = {"name": "windows", "max_dimension": 5000, "version": "invented"}
        with (
            patch("research_lab.pdf_extraction.select_engine", return_value=engine),
            patch("research_lab.pdf_extraction.recognize", side_effect=fake_ocr),
        ):
            result = self.capture("auto")
        self.assertEqual(result["ocr_words"], 6)
        page = read_json(Path(result["directory"]) / "pages/page_002.json")
        self.assertEqual(
            {w["source_region"] for w in page["words"] if w["channel"] == "ocr"},
            {"full_page", "image_0"},
        )
        for word in page["words"]:
            self.assertTrue(all(0 <= v <= 1 for v in word["bbox"]))
        self.assertTrue(page["images"][0]["rendered_crop"])
        self.assertTrue(
            any(s.text == "617 chips" for s in self.corpus.spans(self.document.document_id))
        )
        evaluation = evaluate_extraction(self.corpus, self.document.document_id)
        self.assertEqual(evaluation["status"], "unassessed")

    def test_artifact_and_manifest_tampering_fail_against_corpus_anchor(self):
        directory = Path(self.capture()["directory"])
        spans = directory / "spans.jsonl"
        spans.write_text(spans.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "artifact integrity"):
            self.corpus.spans(self.document.document_id)
        manifest = read_json(directory / "manifest.json")
        manifest["files"]["spans.jsonl"] = digest(spans.read_bytes())
        write_json(directory / "manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "manifest integrity"):
            self.corpus.spans(self.document.document_id)

    def test_new_recipe_and_forced_capture_preserve_prior_bundle(self):
        first = Path(self.capture()["directory"])
        prior_manifest = (first / "manifest.json").read_bytes()
        second = self.capture(force=True)
        self.assertNotEqual(str(first), second["directory"])
        self.assertEqual((first / "manifest.json").read_bytes(), prior_manifest)
        with self.corpus.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM pdf_extractions").fetchone()[0], 2)

    def test_unknown_or_late_pdf_is_withheld_before_cached_evidence_read(self):
        document = Corpus(self.root / "development").ingest(self.source, role="development")
        task = Task(
            task_id="pdf_cutoff",
            entity_id="invented",
            question="Inspect evidence",
            as_of="2026-01-01T00:00:00Z",
            allowed_sources=[
                SourceRef(document_id=document.document_id, content_sha256=document.content_sha256)
            ],
        )
        corpus = Corpus(self.root / "development")
        with patch.object(corpus, "read_bytes", side_effect=AssertionError("Unavailable PDF read")):
            self.assertFalse(build_packet(corpus, task).spans)

    def test_independent_anchor_grade_separates_missing_and_draft_references(self):
        self.capture()
        check = {
            "check_id": "sales",
            "page_index": 0,
            "expected_text": "123,456",
            "bbox": [0.3, 0.1, 0.6, 0.3],
        }
        evaluation = evaluate_extraction(
            self.corpus, self.document.document_id, self.reference([check])
        )
        self.assertEqual(evaluation["status"], "draft_reference_checks_passed")
        self.assertTrue(evaluation["checks"][0]["matching_span_ids"])
        reviewed = evaluate_extraction(
            self.corpus, self.document.document_id, self.reference([check], "reviewed")
        )
        self.assertEqual(reviewed["status"], "reference_checks_passed")
        check["bbox"] = [0.0, 0.8, 1.0, 1.0]
        missing = evaluate_extraction(
            self.corpus, self.document.document_id, self.reference([check])
        )
        self.assertEqual(missing["status"], "needs_review")

    def test_invalid_reference_rejected(self):
        self.capture()
        base = {"check_id": "sales", "page_index": 0, "expected_text": "123,456"}
        for checks in (
            [base, base],
            [{**base, "page_index": 10}],
            [{**base, "expected_text": ""}],
            [{**base, "expected_text": 123}],
            [{**base, "check_id": []}],
            [{"check_id": "missing_fields"}],
            ["malformed_check"],
            [{**base, "bbox": [0, 0, 2, 1]}],
            [{**base, "bbox": None}],
            [{**base, "bbox": [False, 0, 1, 1]}],
        ):
            with self.subTest(checks=checks), self.assertRaises(ValueError):
                evaluate_extraction(self.corpus, self.document.document_id, self.reference(checks))
        path = self.reference([base])
        reference = read_json(path)
        reference["document_sha256"] = "0" * 64
        write_json(path, reference)
        with self.assertRaisesRegex(ValueError, "different source"):
            evaluate_extraction(self.corpus, self.document.document_id, path)
        write_json(path, [])
        with self.assertRaisesRegex(ValueError, "different source"):
            evaluate_extraction(self.corpus, self.document.document_id, path)
        self.reference("malformed_checks")
        with self.assertRaisesRegex(ValueError, "must be a list"):
            evaluate_extraction(self.corpus, self.document.document_id, path)

    def test_pdf_cli_capture_and_separate_audit(self):
        args = ["--root", str(self.root)]
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(
                main(
                    [
                        *args,
                        "extract-pdf",
                        "--document",
                        self.document.document_id,
                        "--ocr",
                        "none",
                        "--dpi",
                        "96",
                    ]
                ),
                0,
            )
        self.assertEqual(json.loads(output.getvalue())["pages"], 2)
        reference = self.reference(
            [{"check_id": "missing", "page_index": 0, "expected_text": "999"}]
        )
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(
                main(
                    [
                        *args,
                        "audit-extraction",
                        "--document",
                        self.document.document_id,
                        "--reference",
                        str(reference),
                    ]
                ),
                1,
            )
        self.assertTrue(Path(json.loads(output.getvalue())["evaluation"]).is_file())

    def test_ocr_errors_are_retained_and_bad_geometry_fails_closed(self):
        engine = {"name": "windows", "max_dimension": 5000}

        def errors(jobs, engine, directory):
            return [{"id": job["id"], "words": [], "error": "Invented OCR error"} for job in jobs]

        with (
            patch("research_lab.pdf_extraction.select_engine", return_value=engine),
            patch("research_lab.pdf_extraction.recognize", side_effect=errors),
        ):
            result = self.capture()
        self.assertEqual(result["ocr_errors"], 3)
        record = {"words": [], "issues": [], "height_points": 100}
        jobs = [{"id": "page", "pixel_size": [100, 100], "page_bbox": [0.0, 0.0, 1.0, 1.0]}]
        with self.assertRaisesRegex(ValueError, "inventory mismatch"):
            add_ocr(record, jobs, [], "invented")
        with self.assertRaises(ValueError):
            normalized_box([0, 0, float("nan"), 1], 1, 1)
        with self.assertRaises(ValueError):
            ExtractionOptions(dpi=500)

    def test_invalid_pdf_failure_retains_original_and_attempt(self):
        path = self.root / "broken.pdf"
        path.write_bytes(b"%PDF-broken")
        doc = self.corpus.ingest(path, role="discovery")
        with self.assertRaisesRegex(ValueError, "PDF capture failed"):
            extract_pdf(self.corpus, doc.document_id, options=ExtractionOptions(ocr="none"))
        self.assertEqual(self.corpus.read_bytes(doc.document_id), b"%PDF-broken")
        self.assertEqual(
            len(list((self.corpus.derived / doc.document_id).glob("*/failure.json"))), 1
        )
        self.assertIsNone(self.corpus.pdf_extraction(doc.document_id))


class CliUnicodeTests(unittest.TestCase):
    def test_source_unicode_round_trips_through_legacy_windows_stdout(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252")
        value = {"source_heading": "Invented \u25cf \u7814\u7a76"}
        with redirect_stdout(stream):
            output(value)
        stream.flush()
        self.assertEqual(json.loads(raw.getvalue().decode("ascii")), value)
        stream.detach()


class OcrTests(unittest.TestCase):
    def test_tesseract_words_keep_confidence_and_location(self):
        text = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        text += "5\t1\t1\t1\t1\t1\t10\t20\t30\t10\t95.5\t617\n"
        word = tesseract_words(text)[0]
        self.assertEqual(word["bbox"], [10, 20, 40, 30])
        self.assertEqual(word["confidence"], 95.5)
        self.assertIsNone(select_engine("none"))
        with self.assertRaises(ValueError):
            select_engine("hosted")

    def test_engine_detection_and_windows_results_cleanup(self):
        details = {"os_version": "invented", "language": "en-US", "max_dimension": 5000}
        with (
            patch("research_lab.ocr.platform.system", return_value="Windows"),
            patch("research_lab.ocr.invoke", return_value=json.dumps(details)),
        ):
            self.assertEqual(select_engine("windows")["name"], "windows")
        with (
            patch("research_lab.ocr.platform.system", return_value="Linux"),
            patch("research_lab.ocr.shutil.which", return_value=None),
        ):
            self.assertIsNone(select_engine("auto"))
        with (
            patch("research_lab.ocr.shutil.which", return_value="tesseract"),
            patch(
                "research_lab.ocr.invoke",
                side_effect=["List of available languages: eng", "tesseract invented\n"],
            ),
        ):
            self.assertEqual(select_engine("tesseract")["language"], "eng")
        with (
            TemporaryDirectory() as folder,
            patch("research_lab.ocr.invoke", return_value='[{"id":"x","words":[]}]'),
        ):
            path = Path(folder)
            self.assertEqual(
                recognize([{"id": "x", "path": "invented.png"}], {"name": "windows"}, path)[0][
                    "id"
                ],
                "x",
            )
            self.assertFalse((path / "ocr_jobs.json").exists())
        self.assertIn("-NoProfile", windows_command())

    def test_subprocess_errors_are_recorded_for_tesseract(self):
        with (
            TemporaryDirectory() as folder,
            patch("research_lab.ocr.invoke", side_effect=OSError("No OCR")),
        ):
            result = recognize(
                [{"id": "x", "path": "invented.png"}], {"name": "tesseract"}, Path(folder)
            )
            self.assertEqual(result[0]["error"], "No OCR")
        with patch(
            "research_lab.ocr.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, b"ok", b""),
        ):
            self.assertEqual(invoke(["invented"]), "ok")


if __name__ == "__main__":
    unittest.main()
