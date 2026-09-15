import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from research_lab.evaluation import evaluate_bundle, oracle_for, read_records
from research_lab.rendering import report_markdown
from research_lab.runtime import run_fixture
from research_lab.schemas import Claim, Task
from research_lab.serde import from_dict, read_json, write_json, write_jsonl


class EvaluationRegressionTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        result = run_fixture(self.root)
        self.run_dir = Path(result["run_dir"])
        self.oracle = oracle_for(self.root, result["manifest"]["task_id"])
        self.claims = [
            json.loads(line) for line in (self.run_dir / "claims.jsonl").read_text().splitlines()
        ]

    def save_claims(self):
        write_jsonl(self.run_dir / "claims.jsonl", self.claims)
        findings = read_json(self.run_dir / "findings.json")
        findings["claims"] = self.claims
        write_json(self.run_dir / "findings.json", findings)
        task = from_dict(Task, read_json(self.run_dir / "task.json"))
        (self.run_dir / "report.md").write_text(
            report_markdown(task, read_records(self.run_dir / "claims.jsonl", Claim)),
            encoding="utf-8",
        )

    def evaluate(self):
        return evaluate_bundle(self.run_dir, self.oracle)

    def test_empty_lineage_cannot_support_correct_numbers(self):
        for claim in self.claims:
            claim.update(supporting_span_ids=[], fact_ids=[], calculation_ids=[])
        self.save_claims()
        result = self.evaluate()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["scorecards"]["research"]["answered_questions"], [])

    def test_existing_but_wrong_scenario_links_are_rejected(self):
        for key in ("supporting_span_ids", "fact_ids", "calculation_ids"):
            self.claims[0][key] = self.claims[1][key]
        self.save_claims()
        result = self.evaluate()
        self.assertIn("claim_lineage_missing", {i["code"] for i in result["issues"]})

    def test_unknown_question_ids_without_calculations_never_pass(self):
        self.claims = [
            c
            for c in self.claims
            if c["claim_id"] in {"revision_bridge", "margin_sensitivity", "multiple_assumption"}
        ]
        for claim in self.claims:
            claim.update(
                claim_type="unknown",
                text="Unresolved.",
                supporting_span_ids=[],
                fact_ids=[],
                calculation_ids=[],
                verification_status="not_applicable",
            )
        write_jsonl(self.run_dir / "calculations.jsonl", [])
        findings = read_json(self.run_dir / "findings.json")
        findings["calculations"] = []
        write_json(self.run_dir / "findings.json", findings)
        self.save_claims()
        result = self.evaluate()
        self.assertNotEqual(result["status"], "passed_automated_checks")
        self.assertEqual(result["scorecards"]["research"]["answered_questions"], [])
        self.assertIn("missing_required_calculation", {i["code"] for i in result["issues"]})

    def test_claim_classification_and_context_are_checked(self):
        original = dict(self.claims[0])
        for field, value in (
            ("claim_type", "fact"),
            ("entity_id", "other"),
            ("horizon", "FY2025"),
            ("claim_id", "revision_bridge"),
        ):
            with self.subTest(field=field):
                self.claims[0] = {**original, field: value}
                self.save_claims()
                self.assertEqual(self.evaluate()["status"], "failed")

    def test_malformed_number_is_reported_without_crashing(self):
        self.claims[0]["text"] = self.claims[0]["text"].replace(
            "USD 200.00 million", "USD . million"
        )
        self.assertIn("USD . million", self.claims[0]["text"])
        self.save_claims()
        self.assertEqual(self.evaluate()["status"], "failed")

    def test_duplicate_evidence_ids_are_rejected(self):
        original = read_json(self.run_dir / "evidence.json")
        for key in ("documents", "spans", "facts"):
            with self.subTest(key=key):
                packet = {**original, key: [*original[key], original[key][0]]}
                write_json(self.run_dir / "evidence.json", packet)
                self.assertEqual(self.evaluate()["status"], "failed")

    def test_span_parent_must_be_in_saved_document_inventory(self):
        packet = read_json(self.run_dir / "evidence.json")
        packet["documents"] = []
        write_json(self.run_dir / "evidence.json", packet)
        self.assertEqual(self.evaluate()["status"], "failed")
