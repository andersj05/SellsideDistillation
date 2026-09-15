from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research_lab.corpus import Corpus
from research_lab.evidence import build_packet
from research_lab.finance import FinancialError, display, margin_change, operating_model, run_calculation
from research_lab.fixtures import prepare_case


class FinanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        corpus = Corpus(Path(self.temp.name))
        self.packet = build_packet(corpus, prepare_case(corpus, "clean"))

    def scenario(self, scenario="base"):
        return [f for f in self.packet.facts if f.scenario == scenario]

    def test_handoff_arithmetic_and_rounding(self):
        expectations = {"prior": ("1.3875", "41.625", "41.63"), "base": ("1.6875", "50.625", "50.63"),
                        "downside": ("1.5075", "45.225", "45.23")}
        for scenario, expected in expectations.items():
            calc = operating_model(self.scenario(scenario), scenario)
            self.assertEqual(Decimal(calc.outputs["eps"]), Decimal(expected[0]))
            self.assertEqual(Decimal(calc.outputs["value_per_share"]), Decimal(expected[1]))
            self.assertEqual(display(calc.outputs["value_per_share"]), expected[2])
            self.assertEqual(set(calc.input_fact_ids.values()), {f.fact_id for f in self.scenario(scenario)})
        self.assertEqual(display("-41.625"), "-41.63")

    def test_percentage_points_are_not_relative_percent(self):
        result = margin_change(".20", ".18")
        self.assertEqual(Decimal(result["percentage_points"]), -2)
        self.assertEqual(Decimal(result["basis_points"]), -200)

    def test_more_revenue_increases_profit_with_other_inputs_fixed(self):
        original = self.scenario()
        changed = [replace(f, value="1300") if f.metric == "revenue" else f for f in original]
        a, b = operating_model(original, "base"), operating_model(changed, "base")
        self.assertGreater(Decimal(b.outputs["operating_profit"]), Decimal(a.outputs["operating_profit"]))

    def test_rejects_scale_period_entity_basis_and_classification_mismatches(self):
        for change in ({"scale": "billion"}, {"period_end": "2025-12-31", "period_start": "2025-01-01"},
                       {"entity_id": "other"}, {"accounting_basis": "GAAP"}, {"value_type": "guidance"}):
            with self.subTest(change=change), self.assertRaises(FinancialError):
                rows = self.scenario()
                rows[0] = replace(rows[0], **change)
                operating_model(rows, "base")

    def test_zero_shares_negative_tax_domain_and_unknown_operation(self):
        for metric, value in (("diluted_shares", "0"), ("net_interest_expense", "1000")):
            with self.subTest(metric=metric), self.assertRaises(FinancialError):
                operating_model([replace(f, value=value) if f.metric == metric else f for f in self.scenario()], "base")
        with self.assertRaises(FinancialError):
            run_calculation("__import__('os')", [], "base")


if __name__ == "__main__":
    unittest.main()
