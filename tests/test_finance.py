import unittest
from dataclasses import replace
from decimal import ROUND_DOWN, Decimal, localcontext
from pathlib import Path
from tempfile import TemporaryDirectory

from research_lab.adapter import Findings, FixtureAdapter
from research_lab.budget import BudgetMeter
from research_lab.corpus import Corpus
from research_lab.evidence import EvidencePacket, EvidenceView, build_packet
from research_lab.finance import (
    FinancialError,
    display,
    margin_change,
    operating_model,
    run_calculation,
)
from research_lab.fixtures import prepare_case
from research_lab.schemas import BudgetLimits, Task


class FinanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        corpus = Corpus(Path(self.temp.name))
        self.packet = build_packet(corpus, prepare_case(corpus, "clean"))

    def scenario(self, scenario="base"):
        return [f for f in self.packet.facts if f.scenario == scenario]

    def test_handoff_arithmetic_and_rounding(self):
        expectations = {
            "prior": ("1.3875", "41.625", "41.63"),
            "base": ("1.6875", "50.625", "50.63"),
            "downside": ("1.5075", "45.225", "45.23"),
        }
        for scenario, expected in expectations.items():
            calc = operating_model(self.scenario(scenario), scenario)
            self.assertEqual(Decimal(calc.outputs["eps"]), Decimal(expected[0]))
            self.assertEqual(Decimal(calc.outputs["value_per_share"]), Decimal(expected[1]))
            self.assertEqual(display(calc.outputs["value_per_share"]), expected[2])
            self.assertEqual(
                set(calc.input_fact_ids.values()), {f.fact_id for f in self.scenario(scenario)}
            )
        self.assertEqual(display("-41.625"), "-41.63")

    def test_percentage_points_are_not_relative_percent(self):
        result = margin_change(".20", ".18")
        self.assertEqual(Decimal(result["percentage_points"]), -2)
        self.assertEqual(Decimal(result["basis_points"]), -200)

    def test_arithmetic_is_independent_of_ambient_decimal_context(self):
        with localcontext() as context:
            context.prec = 2
            context.rounding = ROUND_DOWN
            self.assertEqual(display("50.625"), "50.63")
            result = operating_model(self.scenario(), "base")
            self.assertEqual(Decimal(result.outputs["value_per_share"]), Decimal("50.625"))
            self.assertEqual(
                Decimal(margin_change(".2001", ".18")["basis_points"]), Decimal("-201")
            )

    def test_equivalent_decimal_strings_do_not_create_spurious_driver_changes(self):
        facts = [
            replace(f, value=f.value + "0" if "." in f.value else f.value + ".0")
            if f.scenario == "base"
            else f
            for f in self.packet.facts
        ]
        packet = EvidencePacket(self.packet.documents, self.packet.spans, facts)
        meter = BudgetMeter(BudgetLimits())
        findings = Findings()
        task = Task(
            task_id="test",
            entity_id=facts[0].entity_id,
            question="Test",
            as_of="2026-09-01T00:00:00Z",
            allowed_sources=[],
        )
        with localcontext() as context:
            context.prec = 2
            FixtureAdapter().generate(
                task,
                EvidenceView(packet, meter),
                {"calculate_forecasts", "explain_changes", "preserve_gaps"},
                meter,
                findings,
                lambda *_: None,
            )
        self.assertFalse(findings.issues)
        self.assertEqual(
            set(findings.answered_questions), {"revision", "sensitivity", "assumption"}
        )

    def test_more_revenue_increases_profit_with_other_inputs_fixed(self):
        original = self.scenario()
        changed = [replace(f, value="1300") if f.metric == "revenue" else f for f in original]
        a, b = operating_model(original, "base"), operating_model(changed, "base")
        self.assertGreater(
            Decimal(b.outputs["operating_profit"]), Decimal(a.outputs["operating_profit"])
        )

    def test_rejects_scale_period_entity_basis_and_classification_mismatches(self):
        for change in (
            {"scale": "billion"},
            {"period_end": "2025-12-31", "period_start": "2025-01-01"},
            {"entity_id": "other"},
            {"accounting_basis": "GAAP"},
            {"value_type": "guidance"},
        ):
            with self.subTest(change=change), self.assertRaises(FinancialError):
                rows = self.scenario()
                rows[0] = replace(rows[0], **change)
                operating_model(rows, "base")

    def test_zero_shares_negative_tax_domain_and_unknown_operation(self):
        for metric, value in (("diluted_shares", "0"), ("net_interest_expense", "1000")):
            with self.subTest(metric=metric), self.assertRaises(FinancialError):
                operating_model(
                    [replace(f, value=value) if f.metric == metric else f for f in self.scenario()],
                    "base",
                )
        with self.assertRaises(FinancialError):
            run_calculation("__import__('os')", [], "base")


if __name__ == "__main__":
    unittest.main()
