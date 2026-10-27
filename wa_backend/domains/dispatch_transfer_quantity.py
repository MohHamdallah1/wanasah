"""Creation-time quantity contract for Dispatch handshakes and FIELD projection."""
from domains.uom_authority import UomAuthorityError
from quantity import QuantityError, parse_quantity


CANONICAL_BASE_V1 = "CANONICAL_BASE_V1"


def is_canonical_base_handshake(header) -> bool:
    context = getattr(header, "commercial_context", None)
    return isinstance(context, dict) and context.get("quantity_contract") == CANONICAL_BASE_V1


def canonical_field_base_quantity(signed_base_quantity) -> int:
    """Lossless integer adapter only; never infer a carton from base quantities."""
    try:
        quantity = parse_quantity(signed_base_quantity, allow_negative=True)
    except QuantityError as exc:
        raise UomAuthorityError("DRIVER_MOBILE_QUANTITY_PRECISION_UNSUPPORTED",
            "The FIELD transfer contract requires an exact integral base quantity.") from exc
    if quantity != quantity.to_integral_value():
        raise UomAuthorityError("DRIVER_MOBILE_QUANTITY_PRECISION_UNSUPPORTED",
            "The FIELD transfer contract requires an exact integral base quantity.")
    return int(quantity)
