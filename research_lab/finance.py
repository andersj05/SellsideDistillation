"""Registered financial operations. No arbitrary expressions or generated code."""

from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Context, Decimal, localcontext

from .schemas import Calculation, Fact, decimal

FINANCIAL_CONTEXT = Context(prec=64, rounding=ROUND_HALF_EVEN)

INPUTS = {
    "revenue": ("USD", "million"),
    "operating_margin": ("ratio", "one"),
    "net_interest_expense": ("USD", "million"),
    "tax_rate": ("ratio", "one"),
    "diluted_shares": ("shares", "million"),
    "assumed_forward_pe": ("multiple", "one"),
}
OUTPUT_UNITS = {
    "operating_profit": "USD million",
    "pretax_income": "USD million",
    "net_income": "USD million",
    "eps": "USD/share",
    "value_per_share": "USD/share",
}


class FinancialError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def display(value: str | Decimal) -> str:
    with localcontext(FINANCIAL_CONTEXT):
        return str(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def difference(old: str, new: str) -> Decimal:
    with localcontext(FINANCIAL_CONTEXT):
        return decimal(new) - decimal(old)


def comparable(facts: list[Fact]) -> None:
    contexts = {
        (
            f.entity_id,
            f.period_start,
            f.period_end,
            f.period_type,
            f.accounting_basis,
            f.definition_version,
        )
        for f in facts
    }
    if len(contexts) != 1:
        raise FinancialError(
            "definition_mismatch",
            "Inputs must share entity, fiscal period, accounting basis, and definition version.",
        )


def operating_model(facts: list[Fact], scenario: str) -> Calculation:
    if not facts:
        raise FinancialError(
            "missing_prior" if scenario == "prior" else "missing_input",
            f"No usable {scenario} forecast is available.",
        )
    comparable(facts)
    selected = {}
    for metric, (unit, scale) in INPUTS.items():
        candidates = [f for f in facts if f.metric == metric and f.scenario == scenario]
        if not candidates:
            raise FinancialError("missing_input", f"Missing {scenario} {metric}.")
        if len(candidates) != 1:
            raise FinancialError(
                "conflicting_source",
                f"Multiple {scenario} {metric} records require explicit reconciliation.",
            )
        fact = candidates[0]
        if fact.unit != unit or fact.scale != scale:
            raise FinancialError(
                "unit_scale_mismatch",
                f"{metric} requires {unit} in {scale} units; source says {fact.unit} in {fact.scale}.",
            )
        if fact.value_type not in ("forecast", "assumption"):
            raise FinancialError(
                "value_type_mismatch",
                "This forecast model cannot silently substitute actuals, guidance, or consensus.",
            )
        selected[metric] = fact
    values = {metric: decimal(f.value) for metric, f in selected.items()}
    if values["diluted_shares"] <= 0 or values["revenue"] < 0 or values["assumed_forward_pe"] < 0:
        raise FinancialError(
            "invalid_domain",
            "Revenue and P/E must be nonnegative and diluted shares must be positive.",
        )
    if not 0 <= values["tax_rate"] <= 1 or not 0 <= values["operating_margin"] <= 1:
        raise FinancialError(
            "invalid_domain",
            "Fixture tax and margin assumptions must be ratios between zero and one.",
        )
    with localcontext(FINANCIAL_CONTEXT):
        operating_profit = values["revenue"] * values["operating_margin"]
        pretax = operating_profit - values["net_interest_expense"]
        if pretax < 0:
            raise FinancialError(
                "unsupported_tax_case",
                "The fixture tax model is defined only for nonnegative pretax income.",
            )
        net_income = pretax * (1 - values["tax_rate"])
        eps = net_income / values["diluted_shares"]
        outputs = dict(
            operating_profit=operating_profit,
            pretax_income=pretax,
            net_income=net_income,
            eps=eps,
            value_per_share=eps * values["assumed_forward_pe"],
        )
    return Calculation(
        calculation_id=f"calc_{scenario}",
        operation="operating_model",
        formula_version="1",
        scenario=scenario,
        input_fact_ids={k: v.fact_id for k, v in selected.items()},
        outputs={k: str(v) for k, v in outputs.items()},
        output_units=OUTPUT_UNITS.copy(),
    )


def margin_change(old: str, new: str) -> dict[str, str]:
    with localcontext(FINANCIAL_CONTEXT):
        change = decimal(new) - decimal(old)
        return {"percentage_points": str(change * 100), "basis_points": str(change * 10000)}


OPERATIONS = {"operating_model": operating_model}


def run_calculation(operation: str, facts: list[Fact], scenario: str) -> Calculation:
    if operation not in OPERATIONS:
        raise FinancialError("unknown_operation", "Calculation is not in the operation registry")
    return OPERATIONS[operation](facts, scenario)
