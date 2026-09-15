import io
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from research_lab.cli import main
from research_lab.corpus import Corpus
from research_lab.fixtures import prepare_case
from research_lab.runtime import compare, run_fixture, verify_run
from research_lab.serde import read_json


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_interrupted_import_can_be_retried_without_a_partial_source_object(self):
        corpus = Corpus(self.root)
        source = self.root / "source.txt"
        source.write_text("Complete source bytes", encoding="utf-8")
        with patch.object(Path, "replace", side_effect=OSError("Disk interrupted")):
            with self.assertRaises(OSError):
                corpus.ingest(source, role="discovery")
        self.assertEqual(corpus.inventory(), [])
        self.assertEqual(list(corpus.originals.iterdir()), [])
        document = corpus.ingest(source, role="discovery")
        self.assertEqual(corpus.read_bytes(document.document_id), source.read_bytes())

    def test_concurrent_imports_preserve_one_document(self):
        corpus = Corpus(self.root)
        source = self.root / "source.txt"
        source.write_text("Concurrent identical source", encoding="utf-8")
        with ThreadPoolExecutor(max_workers=2) as pool:
            documents = list(pool.map(lambda _: corpus.ingest(source, role="discovery"), range(2)))
        self.assertEqual(documents[0].document_id, documents[1].document_id)
        self.assertEqual(len(corpus.inventory()), 1)

    def test_source_size_limit_precedes_inventory_commit(self):
        corpus = Corpus(self.root)
        source = self.root / "source.txt"
        source.write_bytes(b"0123456789")
        with (
            patch("research_lab.corpus.MAX_SOURCE_BYTES", 5),
            self.assertRaisesRegex(ValueError, "limit"),
        ):
            corpus.ingest(source, role="discovery")
        self.assertEqual(corpus.inventory(), [])

    def test_cli_reports_malformed_csv_and_configuration(self):
        csv = self.root / "broken.csv"
        csv.write_text('key,value\nx,"unterminated', encoding="utf-8")
        config = self.root / "broken.toml"
        config.write_text('schema_version = "1.0"\n', encoding="utf-8")
        for args in (
            ["ingest", "--input", str(csv), "--role", "discovery"],
            ["--config", str(config), "doctor"],
        ):
            with self.subTest(args=args), redirect_stderr(io.StringIO()) as error:
                self.assertEqual(main(["--root", str(self.root), *args]), 2)
                self.assertIn("lab:", error.getvalue())

    def test_empty_comparison_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "nonempty"):
            compare(self.root, cases=[])
        self.assertFalse((self.root / "runs").exists())

    def test_replay_detects_a_nested_unlisted_freeze_manifest(self):
        result = run_fixture(self.root)
        run_dir = Path(result["run_dir"])
        extra = run_dir / "nested"
        extra.mkdir()
        (extra / "freeze.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inventory"):
            verify_run(run_dir)

    def test_prepare_failure_stays_in_comparison_and_later_attempts_run(self):
        calls = 0

        def prepare(corpus, case):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("Fixture setup failed")
            return prepare_case(corpus, case)

        with patch("research_lab.runtime.prepare_case", side_effect=prepare):
            comparison = compare(self.root, cases=["clean", "missing_prior"])
        self.assertEqual(calls, 4)
        self.assertEqual(len(comparison["results"]), 4)
        self.assertFalse(comparison["results"][0]["expected_behavior_observed"])
        self.assertTrue(all(row["expected_behavior_observed"] for row in comparison["results"][1:]))
        experiment = Path(comparison["review"]).parent
        self.assertEqual(len(read_json(experiment / "attempts.json")), 4)
        first_run = self.root / "runs" / comparison["results"][0]["run_id"]
        self.assertEqual(read_json(first_run / "failure.json")["error_type"], "OSError")
        self.assertFalse((first_run / "freeze.json").exists())

    def test_grader_and_renderer_failures_preserve_outputs_without_sealing(self):
        for function in ("evaluate_bundle", "render_run"):
            with self.subTest(function=function):
                with patch(
                    "research_lab.runtime." + function, side_effect=RuntimeError("Interrupted")
                ):
                    result = run_fixture(self.root)
                run_dir = Path(result["run_dir"])
                self.assertEqual(result["status"], "failed")
                self.assertFalse(result["review_available"])
                self.assertTrue((run_dir / "report.md").is_file())
                self.assertEqual(read_json(run_dir / "attempt.json")["status"], "failed")
                self.assertFalse((run_dir / "freeze.json").exists())

    def test_regrades_are_distinct_derivatives_and_leave_original_unchanged(self):
        result = run_fixture(self.root)
        run_dir = Path(result["run_dir"])
        original = (run_dir / "freeze.json").read_bytes()
        for _ in range(2):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(["--root", str(self.root), "evaluate", "--run", result["run_id"]]), 0
                )
        self.assertEqual(len(list((self.root / "exports").glob("*.evaluation.json"))), 2)
        self.assertEqual(original, (run_dir / "freeze.json").read_bytes())
        verify_run(run_dir)
