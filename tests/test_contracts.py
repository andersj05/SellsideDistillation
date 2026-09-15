import unittest
from dataclasses import replace

from research_lab.schemas import BudgetLimits, Claim, decimal
from research_lab.serde import encode, from_dict, load_json


class ContractTests(unittest.TestCase):
    def test_direct_construction_checks_types_and_enum_values(self):
        with self.assertRaises(ValueError):
            BudgetLimits(max_cost_usd=0)
        claim = Claim(
            claim_id="gap",
            text="Unknown",
            claim_type="unknown",
            origin="observed",
            verification_status="not_applicable",
            entity_id="fixture",
            horizon="FY2026",
            materiality="critical",
            supporting_span_ids=[],
            calculation_ids=[],
            fact_ids=[],
        )
        for changes in (
            {"claim_type": "invented"},
            {"supporting_span_ids": "not-a-list"},
            {"fact_ids": [123]},
            {"schema_version": 1},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(claim, **changes)

    def test_invalid_json_is_rejected_without_coercion(self):
        for text in ('{"value": 1, "value": 2}', '{"value": NaN}', '{"value": Infinity}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                load_json(text)
        for value in (object(), {1, 2}, BudgetLimits):
            with self.subTest(value=value), self.assertRaises(TypeError):
                encode(value)

    def test_bounded_decimal_grammar(self):
        for value in ("1e99999999", "1e-999", "1_000", " 30 ", "9" * 100, "1e49"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                decimal(value)
        self.assertEqual(decimal(".20"), decimal("2e-1"))

    def test_strict_decoding_rejects_missing_and_wrong_fields(self):
        for value in ([], {"max_tool_calls": True}, {"max_tokens": "10"}, {"typo": 1}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                from_dict(BudgetLimits, value)
