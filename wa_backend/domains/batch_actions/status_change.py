from __future__ import annotations

from decimal import Decimal


_STATUS_PRESENTATION_ORDER = (
    "AVAILABLE",
    "QUARANTINED",
    "BLOCKED",
    "RECALLED",
    "DAMAGED",
    "DISPOSAL_PENDING",
)


def status_change_destinations(source_status: str) -> tuple[str, ...]:
    """Read the movement engine's existing transition authority deterministically."""
    # Lazy import avoids making a low-level movement service import this read helper.
    # CP3 must not create a second authoritative matrix.
    from services import _PORTION_STATUS_TRANSITIONS

    source = str(source_status or "").upper()
    if source not in _PORTION_STATUS_TRANSITIONS:
        raise ValueError("Unsupported inventory stock status")
    allowed = _PORTION_STATUS_TRANSITIONS[source]
    return tuple(status for status in _STATUS_PRESENTATION_ORDER if status in allowed)


def status_change_availability(
    source_status: str,
    *,
    eligible_quantity: Decimal,
    can_change: bool,
    batch_sellable: bool,
) -> list[dict[str, object]]:
    """Server-derived advisory actions for one exact inventory source bucket.

    The existing POST mutation remains final authority. Destinations come from
    that same movement-engine transition table; this helper adds only current
    permission, free-quantity and quarantine-release sellability eligibility.
    """
    source = str(source_status or "").upper()
    destinations = status_change_destinations(source)
    free_quantity = Decimal(eligible_quantity)
    if not free_quantity.is_finite() or free_quantity < 0:
        raise ValueError("eligible_quantity must be finite and non-negative")

    actions: list[dict[str, object]] = []
    for destination in destinations:
        if not can_change:
            reason = "PERMISSION_REQUIRED"
        elif free_quantity <= 0:
            reason = "NO_ELIGIBLE_QUANTITY"
        elif (
            source == "QUARANTINED"
            and destination == "AVAILABLE"
            and not batch_sellable
        ):
            reason = "BATCH_NOT_SELLABLE"
        else:
            reason = "ALLOWED"
        actions.append(
            {
                "destination_status": destination,
                "allowed": reason == "ALLOWED",
                "eligible_quantity": free_quantity,
                "reason_code": reason,
            }
        )
    return actions
