from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


MONEY_QUANT = Decimal("0.000001")
MONEY_MAX = Decimal("99999999999999.999999")
_CURRENCY_RE = re.compile(r"^[A-Z][A-Z0-9]{2,9}$")


class CalculationError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        context: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.status_code = int(status_code)
        self.context = dict(context or {})

    def as_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "context": self.context,
        }


def require_aware_datetime(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CalculationError(
            "CALCULATION_DATETIME_OFFSET_REQUIRED",
            f"{field_name} must include a UTC offset.",
            status_code=422,
            context={"field": field_name},
        )
    return value.astimezone(timezone.utc)


def exact_money(value: Any, field_name: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise CalculationError(
            "CALCULATION_AMOUNT_INVALID",
            f"{field_name} must be an exact decimal value.",
            status_code=422,
            context={"field": field_name},
        )
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise CalculationError(
            "CALCULATION_AMOUNT_INVALID",
            f"{field_name} is not a valid decimal amount.",
            status_code=422,
            context={"field": field_name},
        ) from exc
    if not result.is_finite() or result < 0:
        raise CalculationError(
            "CALCULATION_AMOUNT_INVALID",
            f"{field_name} must be finite and non-negative.",
            status_code=422,
            context={"field": field_name},
        )
    try:
        quantized = result.quantize(MONEY_QUANT)
    except InvalidOperation as exc:
        raise CalculationError(
            "CALCULATION_AMOUNT_INVALID",
            f"{field_name} cannot be represented as NUMERIC(20,6).",
            status_code=422,
            context={"field": field_name},
        ) from exc
    if quantized != result or result > MONEY_MAX:
        raise CalculationError(
            "CALCULATION_AMOUNT_INVALID",
            f"{field_name} exceeds NUMERIC(20,6) precision/capacity.",
            status_code=422,
            context={"field": field_name},
        )
    return result


def normalize_currency_code(value: str) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise CalculationError(
            "CALCULATION_CURRENCY_INVALID",
            "Currency code is invalid.",
            status_code=422,
        )
    code = value.strip().upper()
    if not _CURRENCY_RE.fullmatch(code):
        raise CalculationError(
            "CALCULATION_CURRENCY_INVALID",
            "Currency code must be a stable 3-10 character code.",
            status_code=422,
        )
    return code
