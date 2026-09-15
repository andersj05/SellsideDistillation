from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import io
import socket
import unittest

from research_lab.cli import main
from research_lab.evaluation import evaluate_bundle, oracle_for
from research_lab.fixtures import CASES
from research_lab.runtime import compare, configuration, run_fixture, verify_run
from research_lab.serde import read_json


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_end_to_end_case_matrix_and_comparison_parity(self):
        with patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden")):
            result = compare(self.root, cases=CASES)
        self.assertEqual(len(result["results"]), 12)
        self.assertTrue(all(row["expected_behavior_observed"] for row in result["results"]))
        for case in CASES:
            rows = [r for r in result["results"] if r["case"] == case]
            self.assertEqual(len({r["source_manifest_hash"] for r in rows}), 1)
        clean = [r for r in result["results"] if r["case"] == "clean"]
        self.assertTrue(all(r["numeric_correct"] == 15 and r["questions_answered"] == 3 for r in clean))
        report_paths = [self.root / "runs" / row["run_id"] / "report.md" for row in clean]
        self.assertEqual(report_paths[0].read_bytes(), report_paths[1].read_bytes())
        for row in result["results"]:
            run_dir = self.root / "runs" / row["run_id"]
            manifest = verify_run(run_dir)
            self.assertEqual(manifest["usage"]["model_calls"], "0")
            task_json = (run_dir / "task.json").read_text()
            self.assertNotIn("private_eval", task_json)
            self.assertNotIn("expected", task_json)
        self.assertTrue(Path(result["review"]).is_file())

    def test_replay_no_adapter_or_network_and_integrity_detection(self):
        result = run_fixture(self.root)
        with patch("research_lab.runtime.FixtureAdapter.generate", side_effect=AssertionError("Replay generated new work")), \
             patch.object(socket, "create_connection", side_effect=AssertionError("Replay made network request")):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(self.root), "replay", "--run", result["run_id"]]), 0)
        path = Path(result["run_dir"]) / "report.md"
        path.write_text(path.read_text() + "\nChanged", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "integrity"):
            verify_run(Path(result["run_dir"]))

    def test_budget_failure_preserves_partial_work(self):
        config = configuration()
        config["budget"]["max_tool_calls"] = 9
        result = run_fixture(self.root, config=config)
        self.assertEqual(result["status"], "budget_exhausted")
        run_dir = Path(result["run_dir"])
        self.assertTrue(read_json(run_dir / "findings.json")["calculations"])
        verify_run(run_dir)
        self.assertIn("budget_exhausted", {i["code"] for i in result["evaluation"]["issues"]})

    def test_independent_evaluator_rejects_changed_number_and_registered_fabrication(self):
        result = run_fixture(self.root)
        run_dir = Path(result["run_dir"])
        oracle = oracle_for(self.root, result["manifest"]["task_id"])
        path = run_dir / "calculations.jsonl"
        rows = [json.loads(s) for s in path.read_text().splitlines()]
        rows[0]["outputs"]["eps"] = "999"
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        evaluation = evaluate_bundle(run_dir, oracle)
        self.assertIn("wrong_number", {i["code"] for i in evaluation["issues"]})
        claims_path = run_dir / "claims.jsonl"
        claims = [json.loads(s) for s in claims_path.read_text().splitlines()]
        claims[0]["text"] = "Management guaranteed that demand will double."
        claims_path.write_text("\n".join(json.dumps(c) for c in claims) + "\n", encoding="utf-8")
        evaluation = evaluate_bundle(run_dir, oracle)
        self.assertIn("claim_semantics_unassessed", {i["code"] for i in evaluation["issues"]})


if __name__ == "__main__":
    unittest.main()
