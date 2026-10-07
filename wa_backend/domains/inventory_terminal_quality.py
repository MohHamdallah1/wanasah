from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import InventoryBalance
from product_lifecycle import record_domain_event
from quantity import QuantityError, canonical_quantity, parse_quantity
from services import (
    InventoryMutationError,
    InventoryRuleError,
    apply_inventory_movements_batch,
)
from domains.inventory_terminal_provenance import allocate_terminal_origin_quantity

FINAL_DISPOSAL_EVENT = "INVENTORY_FINAL_DISPOSAL_CONFIRMED"
FINAL_DISPOSAL_REFERENCE_TYPE = "FINAL_DISPOSAL"


async def confirm_final_disposal(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    request_id: UUID,
    source_location_id: int,
    product_variant_id: int,
    batch_id: int,
    quantity: Decimal,
    reason: str,
    method: str | None = None,
    evidence_reference: str | None = None,
    allow_legacy_fifo_state_bridge: bool = False,
) -> dict[str, Any]:
    """Destroy company-owned stock only after it reached DISPOSAL_PENDING.

    The command intentionally reuses the unified movement engine as a source-only
    PHYSICAL movement. It never edits InventoryBalance directly. Historical
    POSTED DISPOSAL transfers prove that this batch legitimately reached the
    disposal location even if the company's current destination policy changed.
    """
    try:
        qty = parse_quantity(quantity, "quantity", allow_zero=False)
    except QuantityError as exc:
        raise InventoryMutationError(str(exc)) from exc
    if not str(reason or "").strip():
        raise InventoryMutationError("A disposal reason is required.")

    # Preflight reads intentionally do not acquire lifecycle/location/balance
    # locks. The unified movement engine owns the canonical lock order
    # (idempotency -> lifecycle -> locations -> batch/balances) and revalidates
    # all mutable inventory authority before writing. Posted disposal-transfer
    # evidence is immutable business history.
    balance = (
        await db.execute(
            select(InventoryBalance)
            .where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == source_location_id,
                InventoryBalance.product_variant_id == product_variant_id,
                InventoryBalance.batch_id == batch_id,
                InventoryBalance.stock_status == "DISPOSAL_PENDING",
            )
        )
    ).scalar_one_or_none()
    if balance is None:
        raise InventoryRuleError(
            "DISPOSAL_PENDING_STOCK_NOT_FOUND",
            "No quantity is waiting for final disposal at this location.",
            context={
                "source_location_id": source_location_id,
                "product_variant_id": product_variant_id,
                "batch_id": batch_id,
            },
        )

    before_on_hand = Decimal(balance.on_hand_quantity or 0)
    before_reserved = Decimal(balance.reserved_quantity or 0)
    movable_quantity = before_on_hand - before_reserved
    if movable_quantity < qty:
        raise InventoryRuleError(
            "DISPOSAL_QUANTITY_EXCEEDS_MOVABLE",
            "The requested disposal quantity exceeds the unreserved pending quantity.",
            context={
                "on_hand_quantity": canonical_quantity(before_on_hand),
                "reserved_quantity": canonical_quantity(before_reserved),
                "movable_quantity": canonical_quantity(movable_quantity),
                "requested_quantity": canonical_quantity(qty),
            },
        )

    allocations = await allocate_terminal_origin_quantity(
        db,
        company_id=company_id,
        transfer_purpose="DISPOSAL",
        destination_location_id=source_location_id,
        product_variant_id=product_variant_id,
        batch_id=batch_id,
        terminal_reference_type=FINAL_DISPOSAL_REFERENCE_TYPE,
        requested_quantity=qty,
    )

    movement_specs = [
        {
            "product_variant_id": product_variant_id,
            "batch_id": batch_id,
            "quantity": allocation.quantity,
            "movement_kind": "PHYSICAL",
            "reference_type": FINAL_DISPOSAL_REFERENCE_TYPE,
            "reference_id": str(request_id),
            "idempotency_key": (
                f"FINAL-DISPOSAL-{request_id}-{allocation.transfer_header_id}"
            ),
            "source_location_id": source_location_id,
            "destination_location_id": None,
            "source_stock_status": "DISPOSAL_PENDING",
            "destination_stock_status": None,
            "transfer_header_id": allocation.transfer_header_id,
            "allow_legacy_fifo_state_bridge": allow_legacy_fifo_state_bridge,
            "notes": str(reason).strip(),
        }
        for allocation in allocations
    ]
    movements = await apply_inventory_movements_batch(
        db,
        company_id=company_id,
        performed_by=actor_id,
        movements=movement_specs,
    )
    if len(movements) != len(movement_specs):
        raise RuntimeError("Unified movement engine returned an incomplete disposal result.")
    movement_ids = [int(movement.id) for movement in movements]
    origin_ids = [allocation.transfer_header_id for allocation in allocations]

    # The unified movement engine refreshes/locks the same identity-mapped balance.
    # Read the authoritative post-movement value rather than deriving remaining
    # from a preflight snapshot that could have become stale under concurrency.
    refreshed_balance = (
        await db.execute(
            select(InventoryBalance).where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == source_location_id,
                InventoryBalance.product_variant_id == product_variant_id,
                InventoryBalance.batch_id == batch_id,
                InventoryBalance.stock_status == "DISPOSAL_PENDING",
            )
        )
    ).scalar_one_or_none()
    if refreshed_balance is None:
        raise RuntimeError("Unified movement removed the authoritative balance row unexpectedly.")
    remaining = Decimal(refreshed_balance.on_hand_quantity or 0)
    exact_before_on_hand = remaining + qty
    exact_reserved = Decimal(refreshed_balance.reserved_quantity or 0)

    record_domain_event(
        db,
        company_id=company_id,
        actor_id=actor_id,
        request_id=request_id,
        event_type=FINAL_DISPOSAL_EVENT,
        entity_type="InventoryMovement",
        entity_id=movement_ids[0],
        reason=str(reason).strip(),
        before={
            "source_location_id": source_location_id,
            "product_variant_id": product_variant_id,
            "batch_id": batch_id,
            "stock_status": "DISPOSAL_PENDING",
            "on_hand_quantity": canonical_quantity(exact_before_on_hand),
            "reserved_quantity": canonical_quantity(exact_reserved),
            "origin_transfer_header_ids": origin_ids,
        },
        after={
            "movement_ids": movement_ids,
            "disposed_quantity": canonical_quantity(qty),
            "remaining_quantity": canonical_quantity(remaining),
            "method": method,
            "evidence_reference": evidence_reference,
            "origin_transfer_header_ids": origin_ids,
        },
        emit_outbox=True,
    )

    return {
        "movement_ids": movement_ids,
        "product_variant_id": product_variant_id,
        "batch_id": batch_id,
        "source_location_id": source_location_id,
        "disposed_quantity": canonical_quantity(qty),
        "remaining_quantity": canonical_quantity(remaining),
        "origin_transfer_header_ids": origin_ids,
        "event_type": FINAL_DISPOSAL_EVENT,
    }
