"""Exact quantity primitives shared by API contracts and inventory services."""

from decimal import Decimal, InvalidOperation
from typing import Any


QUANTITY_SCALE = 6
QUANTITY_QUANT = Decimal("0.000001")
QUANTITY_MAX = Decimal("99999999999999.999999")


class QuantityError(ValueError):
    pass


def parse_quantity(
    value: Any,
    field_name: str = "quantity",
    *,
    allow_zero: bool = False,
    allow_negative: bool = False,
) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float) or value is None:
        raise QuantityError(f"{field_name} يجب أن يكون كمية Decimal صالحة.")
    try:
        quantity = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError) as exc:
        raise QuantityError(f"{field_name} يجب أن يكون كمية Decimal صالحة.") from exc
    if not quantity.is_finite():
        raise QuantityError(f"{field_name} لا يقبل NaN أو Infinity.")
    if abs(quantity) > QUANTITY_MAX:
        raise QuantityError(f"{field_name} يتجاوز سعة NUMERIC(20,6).")
    if quantity != quantity.quantize(QUANTITY_QUANT):
        raise QuantityError(f"{field_name} لا يقبل أكثر من 6 منازل عشرية.")
    if not allow_negative and quantity < 0:
        raise QuantityError(f"{field_name} لا يمكن أن يكون سالباً.")
    if not allow_zero and quantity == 0:
        raise QuantityError(f"{field_name} يجب أن يكون أكبر من صفر.")
    return quantity


def validate_variant_quantity(
    value: Any,
    *,
    quantity_scale: int,
    quantity_step: Any,
    field_name: str = "quantity",
    allow_zero: bool = False,
    allow_negative: bool = False,
) -> Decimal:
    quantity = parse_quantity(
        value,
        field_name,
        allow_zero=allow_zero,
        allow_negative=allow_negative,
    )
    if type(quantity_scale) is not int or not 0 <= quantity_scale <= QUANTITY_SCALE:
        raise QuantityError("دقة كمية الصنف غير صالحة.")
    step = parse_quantity(quantity_step, "quantity_step")
    scale_quant = Decimal(1).scaleb(-quantity_scale)
    if quantity != quantity.quantize(scale_quant):
        raise QuantityError(
            f"{field_name} يتجاوز دقة الصنف البالغة {quantity_scale} منازل عشرية."
        )
    if quantity % step != 0:
        raise QuantityError(f"{field_name} لا يطابق خطوة الصنف {canonical_quantity(step)}.")
    return quantity


def canonical_quantity(value: Any) -> str:
    quantity = parse_quantity(
        value,
        allow_zero=True,
        allow_negative=True,
    )
    rendered = format(quantity, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"-0", ""} else rendered
