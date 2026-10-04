from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    InventoryBalance,
    InventoryLocation,
    InventoryTransferHeader,
    InventoryTransferLine,
    ProductBatch,
)
from product_lifecycle import record_domain_event
from quantity import QuantityError, canonical_quantity, parse_quantity
from services import (
    InventoryMutationError,
    InventoryRuleError,
    apply_inventory_movement,
)

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
    location = (
        await db.execute(
            select(InventoryLocation)
            .where(
                InventoryLocation.company_id == company_id,
                InventoryLocation.id == source_location_id,
                InventoryLocation.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if location is None:
        raise InventoryRuleError(
            "DISPOSAL_LOCATION_UNAVAILABLE",
            "The disposal source location is missing or inactive.",
            context={"source_location_id": source_location_id},
        )

    batch = (
        await db.execute(
            select(ProductBatch)
            .where(
                ProductBatch.company_id == company_id,
                ProductBatch.product_variant_id == product_variant_id,
                ProductBatch.id == batch_id,
            )
        )
    ).scalar_one_or_none()
    if batch is None:
        raise InventoryRuleError(
            "DISPOSAL_BATCH_NOT_FOUND",
            "The disposal batch does not belong to this product/company.",
            context={"product_variant_id": product_variant_id, "batch_id": batch_id},
        )

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
    if before_reserved > 0:
        raise InventoryRuleError(
            "DISPOSAL_PENDING_STOCK_RESERVED",
            "Reserved disposal-pending stock must be released by its owner first.",
            context={
                "source_location_id": source_location_id,
                "product_variant_id": product_variant_id,
                "batch_id": batch_id,
                "reserved_quantity": canonical_quantity(before_reserved),
            },
        )
    if before_on_hand < qty:
        raise InventoryRuleError(
            "DISPOSAL_QUANTITY_EXCEEDS_PENDING",
            "The requested disposal quantity exceeds the pending quantity.",
            context={
                "available_quantity": canonical_quantity(before_on_hand),
                "requested_quantity": canonical_quantity(qty),
            },
        )

    origin_rows = (
        await db.execute(
            select(
                InventoryTransferHeader.id.label("header_id"),
                InventoryTransferHeader.reference_number,
                InventoryTransferLine.quantity,
            )
            .join(
                InventoryTransferLine,
                and_(
                    InventoryTransferLine.company_id == InventoryTransferHeader.company_id,
                    InventoryTransferLine.transfer_header_id == InventoryTransferHeader.id,
                ),
            )
            .where(
                InventoryTransferHeader.company_id == company_id,
                InventoryTransferHeader.workflow_type == "TRANSIT",
                InventoryTransferHeader.transfer_purpose == "DISPOSAL",
                InventoryTransferHeader.status == "POSTED",
                InventoryTransferHeader.destination_location_id == source_location_id,
                InventoryTransferLine.product_variant_id == product_variant_id,
                InventoryTransferLine.batch_id == batch_id,
            )
            .order_by(InventoryTransferHeader.id.asc())
        )
    ).all()
    if not origin_rows:
        raise InventoryRuleError(
            "DISPOSAL_ORIGIN_EVIDENCE_MISSING",
            "Final disposal requires evidence that the batch reached this location through an approved disposal transfer.",
            context={
                "source_location_id": source_location_id,
                "product_variant_id": product_variant_id,
                "batch_id": batch_id,
            },
        )

    origin_total = sum((Decimal(row.quantity or 0) for row in origin_rows), Decimal("0"))
    if origin_total < before_on_hand:
        raise InventoryRuleError(
            "DISPOSAL_ORIGIN_EVIDENCE_INCONSISTENT",
            "Disposal-pending stock exceeds its immutable disposal-transfer evidence.",
            context={
                "pending_quantity": canonical_quantity(before_on_hand),
                "origin_quantity": canonical_quantity(origin_total),
            },
        )

    origin_ids = sorted({int(row.header_id) for row in origin_rows})
    if len(origin_ids) > 100:
        raise InventoryRuleError(
            "DISPOSAL_ORIGIN_EVIDENCE_LIMIT",
            "Too many disposal origin documents are attached to this batch/location; narrow the operational history before confirming disposal.",
            context={"origin_document_count": len(origin_ids)},
        )

    movement = await apply_inventory_movement(
        db,
        company_id=company_id,
        performed_by=actor_id,
        product_variant_id=product_variant_id,
        batch_id=batch_id,
        quantity=qty,
        movement_kind="PHYSICAL",
        reference_type=FINAL_DISPOSAL_REFERENCE_TYPE,
        reference_id=str(request_id),
        idempotency_key=f"FINAL-DISPOSAL-{request_id}",
        source_location_id=source_location_id,
        destination_location_id=None,
        source_stock_status="DISPOSAL_PENDING",
        destination_stock_status=None,
        transfer_header_id=(origin_ids[0] if len(origin_ids) == 1 else None),
        notes=str(reason).strip(),
    )

    # apply_inventory_movement refreshes/locks the same identity-mapped balance.
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
        entity_id=int(movement.id),
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
            "movement_id": int(movement.id),
            "disposed_quantity": canonical_quantity(qty),
            "remaining_quantity": canonical_quantity(remaining),
            "method": method,
            "evidence_reference": evidence_reference,
            "origin_transfer_header_ids": origin_ids,
        },
        emit_outbox=True,
    )

    return {
        "movement_id": int(movement.id),
        "product_variant_id": product_variant_id,
        "batch_id": batch_id,
        "source_location_id": source_location_id,
        "disposed_quantity": canonical_quantity(qty),
        "remaining_quantity": canonical_quantity(remaining),
        "origin_transfer_header_ids": origin_ids,
        "event_type": FINAL_DISPOSAL_EVENT,
    }
