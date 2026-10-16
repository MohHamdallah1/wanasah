from __future__ import annotations

from decimal import Decimal
from typing import Final


STATUS_CHANGE_DESTINATIONS: Final[dict[str, tuple[str, ...]]] = {
    "AVAILABLE": ("QUARANTINED", "BLOCKED", "RECALLED"),
    "QUARANTINED": ("AVAILABLE", "BLOCKED", "RECALLED"),
    "BLOCKED": ("RECALLED",),
    "RECALLED": (),
    "DAMAGED": (),
    "DISPOSAL_PENDING": (),
}


def status_change_availability(
    source_status: str,
    *,
    eligible_quantity: Decimal,
    can_change: bool,
    batch_sellable: bool,
) -> list[dict[str, object]]:
    """Server-derived advisory actions for one exact inventory source bucket.

    The POST mutation remains final authority. This read helper only exposes the
    frozen operational destinations plus current permission/free-quantity and
    the sellability re-check required before QUARANTINED -> AVAILABLE.
    """
    source = str(source_status or "").upper()
    if source not in STATUS_CHANGE_DESTINATIONS:
        raise ValueError("Unsupported inventory stock status")
    free_quantity = Decimal(eligible_quantity)
    if not free_quantity.is_finite() or free_quantity < 0:
        raise ValueError("eligible_quantity must be finite and non-negative")

    actions: list[dict[str, object]] = []
    for destination in STATUS_CHANGE_DESTINATIONS[source]:
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
