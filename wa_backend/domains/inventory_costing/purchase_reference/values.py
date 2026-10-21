"""Exact monetary/UOM arithmetic. No valuation, rounding or float fallback."""
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
import re

from .errors import PurchaseReferenceError

MONEY_MAX = Decimal("99999999999999.999999")
QUANTUM = Decimal("0.000001")
_RATIO_MAX = 10 ** 78 - 1


def amount_value(value):
    if isinstance(value, (float, bool)) or value is None:
        raise ValueError("Use an exact decimal string for purchase cost.")
    try:
        value = Decimal(value)
        with localcontext() as ctx:
            ctx.prec = 90
            normalized = value.quantize(QUANTUM)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Purchase cost is invalid.") from exc
    if not value.is_finite() or value < 0 or value > MONEY_MAX or value != normalized:
        raise ValueError("Purchase cost must be nonnegative with at most six decimals.")
    return normalized


def currency_value(value):
    if not isinstance(value, str):
        raise ValueError("Currency is required.")
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]{2,9}", value):
        raise ValueError("Currency code is invalid.")
    return value


def ratio_parts(factor):
    numerator, denominator = factor.numerator, factor.denominator
    if min(numerator, denominator) <= 0 or max(numerator, denominator) > _RATIO_MAX:
        raise PurchaseReferenceError(
            "PURCHASE_REFERENCE_UOM_RATIO_INVALID", "UOM ratio cannot be represented."
        )
    return Decimal(numerator), Decimal(denominator)


def convert_exact(amount, *, source_factor, target_factor):
    """Factors express base quantity per UOM. Reject monetary precision loss."""
    result = Fraction(amount) * target_factor / source_factor
    scaled = result * 1_000_000
    if scaled.denominator != 1:
        raise PurchaseReferenceError(
            "PURCHASE_REFERENCE_PRECISION_LOSS",
            "This UOM quote cannot be represented exactly at six decimal places.",
        )
    with localcontext() as ctx:
        ctx.prec = 90
        converted = Decimal(scaled.numerator).scaleb(-6)
    if converted > MONEY_MAX:
        raise PurchaseReferenceError(
            "PURCHASE_REFERENCE_AMOUNT_OVERFLOW", "The converted cost is too large."
        )
    return converted
