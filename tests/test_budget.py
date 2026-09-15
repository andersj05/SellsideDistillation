import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import localcontext

from research_lab.budget import BudgetExceeded, BudgetMeter
from research_lab.schemas import BudgetLimits


class BudgetConcurrencyTests(unittest.TestCase):
    def test_competing_reservations_never_exceed_limit(self):
        meter = BudgetMeter(BudgetLimits(max_tool_calls=7))

        def reserve(_):
            try:
                meter.reserve(tool_calls=1)
                return True
            except BudgetExceeded:
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            successful = list(pool.map(reserve, range(40)))
        self.assertEqual(sum(successful), 7)
        self.assertEqual(meter.usage()["tool_calls"], "7")

    def test_cost_addition_is_precise_and_failed_reservations_are_atomic(self):
        meter = BudgetMeter(BudgetLimits(max_tool_calls=2, max_cost_usd="0.333333"))
        with localcontext() as context:
            context.prec = 2
            meter.reserve(tool_calls=1, cost_usd="0.222222")
            meter.reserve(cost_usd="0.111111")
            with self.assertRaises(BudgetExceeded):
                meter.reserve(tool_calls=1, cost_usd="0.000001")
        self.assertEqual(meter.usage()["cost_usd"], "0.333333")
        self.assertEqual(meter.usage()["tool_calls"], "1")
