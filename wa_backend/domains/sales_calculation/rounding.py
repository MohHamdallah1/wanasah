from __future__ import annotations

from decimal import (
    Decimal,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
)

from domains.sales_calculation.contracts import RoundingPolicy
from domains.sales_calculation.core import (
    CalculationError,
    MONEY_MAX,
    normalize_currency_code,
)


_ROUNDING_MODES = {
    "HALF_UP": ROUND_HALF_UP,
    "HALF_EVEN": ROUND_HALF_EVEN,
}


def validate_rounding_policy(policy: RoundingPolicy) -> RoundingPolicy:
    if not isinstance(policy.version, int) or isinstance(policy.version, bool) or policy.version <= 0:
        raise CalculationError(
            "ROUNDING_POLICY_INVALID",
            "Rounding policy version must be a positive integer.",
            status_code=422,
        )
    currency = normalize_currency_code(policy.currency_code)
    if (
        not isinstance(policy.precision, int)
        or isinstance(policy.precision, bool)
        or policy.precision < 0
        or policy.precision > 6
    ):
        raise CalculationError(
            "ROUNDING_POLICY_INVALID",
            "Currency precision must be an integer between 0 and 6.",
            status_code=422,
        )
    mode = str(policy.mode).strip().upper()
    if mode not in _ROUNDING_MODES:
        raise CalculationError(
            "ROUNDING_POLICY_INVALID",
            "Unsupported rounding mode.",
            status_code=422,
            context={"mode": mode},
        )
    return RoundingPolicy(
        version=policy.version,
        currency_code=currency,
        precision=policy.precision,
        mode=mode,
    )


def quantum(policy: RoundingPolicy) -> Decimal:
    checked = validate_rounding_policy(policy)
    return Decimal("1").scaleb(-checked.precision)


def round_currency(value: Decimal, policy: RoundingPolicy) -> Decimal:
    checked = validate_rounding_policy(policy)
    if not isinstance(value, Decimal) or not value.is_finite():
        raise CalculationError(
            "ROUNDING_AMOUNT_INVALID",
            "Only finite Decimal values can be currency-rounded.",
        )
    rounded = value.quantize(
        Decimal("1").scaleb(-checked.precision),
        rounding=_ROUNDING_MODES[checked.mode],
    )
    if abs(rounded) > MONEY_MAX:
        raise CalculationError(
            "CALCULATION_AMOUNT_OVERFLOW",
            "Rounded amount exceeds NUMERIC(20,6) monetary capacity.",
        )
    return rounded


def reconcile_components(
    *,
    raw_amounts: tuple[Decimal, ...],
    target_total: Decimal,
    policy: RoundingPolicy,
) -> tuple[Decimal, ...]:
    if not raw_amounts:
        if target_total != Decimal("0"):
            raise CalculationError(
                "TAX_COMPONENT_RECONCILIATION_FAILED",
                "A non-zero tax total cannot be reconciled without tax components.",
            )
        return ()

    if any(not value.is_finite() or value < 0 for value in raw_amounts):
        raise CalculationError(
            "TAX_COMPONENT_RECONCILIATION_FAILED",
            "Tax component amounts must be finite and non-negative.",
        )

    unit = quantum(policy)
    rounded = [round_currency(value, policy) for value in raw_amounts]
    delta = target_total - sum(rounded, Decimal("0"))
    if delta == 0:
        return tuple(rounded)

    steps_decimal = delta / unit
    if steps_decimal != steps_decimal.to_integral_value():
        raise CalculationError(
            "TAX_COMPONENT_RECONCILIATION_FAILED",
            "Tax component reconciliation delta is not a whole currency unit.",
            context={"delta": str(delta), "unit": str(unit)},
        )
    steps = int(steps_decimal)

    if steps > 0:
        order = sorted(
            range(len(raw_amounts)),
            key=lambda index: (
                raw_amounts[index] - rounded[index],
                -index,
            ),
            reverse=True,
        )
        for offset in range(steps):
            index = order[offset % len(order)]
            rounded[index] += unit
    else:
        order = sorted(
            range(len(raw_amounts)),
            key=lambda index: (
                rounded[index] - raw_amounts[index],
                -index,
            ),
            reverse=True,
        )
        remaining = -steps
        cursor = 0
        max_iterations = max(1, remaining * len(order) * 2)
        iterations = 0
        while remaining:
            index = order[cursor % len(order)]
            if rounded[index] >= unit:
                rounded[index] -= unit
                remaining -= 1
            cursor += 1
            iterations += 1
            if iterations > max_iterations:
                raise CalculationError(
                    "TAX_COMPONENT_RECONCILIATION_FAILED",
                    "Unable to reconcile rounded tax components without a negative amount.",
                )

    if any(value < 0 for value in rounded):
        raise CalculationError(
            "TAX_COMPONENT_RECONCILIATION_FAILED",
            "Tax component reconciliation produced a negative amount.",
        )
    if sum(rounded, Decimal("0")) != target_total:
        raise CalculationError(
            "TAX_COMPONENT_RECONCILIATION_FAILED",
            "Rounded tax components do not reconcile to line tax.",
        )
    return tuple(rounded)
