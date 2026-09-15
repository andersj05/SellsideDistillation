"""Reserve resource usage before dispatch, including calls that later fail."""

from decimal import Decimal
from threading import Lock
from time import monotonic

from .schemas import BudgetLimits, decimal


class BudgetExceeded(RuntimeError):
    pass


class BudgetMeter:
    def __init__(self, limits: BudgetLimits, clock=monotonic):
        self.limits = limits
        self.clock = clock
        self.start = clock()
        self.lock = Lock()
        self.counts = dict(model_calls=0, tool_calls=0, tokens=0, repair_rounds=0)
        self.cost = Decimal("0")

    def reserve(self, *, model_calls=0, tool_calls=0, tokens=0, repair_rounds=0, cost_usd="0"):
        increments = dict(
            model_calls=model_calls,
            tool_calls=tool_calls,
            tokens=tokens,
            repair_rounds=repair_rounds,
        )
        cost = decimal(cost_usd)
        if any(type(v) is not int or v < 0 for v in increments.values()) or cost < 0:
            raise ValueError("Resource reservations cannot be negative")
        with self.lock:
            if self.clock() - self.start >= self.limits.max_elapsed_seconds:
                raise BudgetExceeded("Elapsed-time budget reached")
            for name, value in increments.items():
                if self.counts[name] + value > getattr(self.limits, "max_" + name):
                    raise BudgetExceeded(f"{name} budget reached")
            if self.cost + cost > decimal(self.limits.max_cost_usd):
                raise BudgetExceeded("Monetary budget reached")
            for name, value in increments.items():
                self.counts[name] += value
            self.cost += cost

    def usage(self) -> dict[str, str]:
        return {
            **{k: str(v) for k, v in self.counts.items()},
            "cost_usd": str(self.cost),
            "elapsed_seconds": f"{self.clock() - self.start:.6f}",
            "cost_scope": "Model/tool charges only; local compute and human review unpriced",
        }
