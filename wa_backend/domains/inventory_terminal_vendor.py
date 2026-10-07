from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.inventory_terminal_provenance import allocate_terminal_origin_quantity
from models import InventoryBalance
from product_lifecycle import record_domain_event
from quantity import QuantityError, canonical_quantity, parse_quantity
from services import (
    InventoryMutationError,
    InventoryRuleError,
    apply_inventory_movements_batch,
)

FINAL_VENDOR_HANDOVER_EVENT = "INVENTORY_VENDOR_HANDOVER_CONFIRMED"
FINAL_VENDOR_HANDOVER_REFERENCE_TYPE = "FINAL_VENDOR_HANDOVER"
_VENDOR_HANDOVER_STATUSES = frozenset({"QUARANTINED", "BLOCKED", "RECALLED", "DAMAGED"})


async def confirm_vendor_handover(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    request_id: UUID,
    source_location_id: int,
    product_variant_id: int,
    batch_id: int,
    source_status: str,
    quantity: Decimal,
    vendor_name: str,
    vendor_reference: str,
    handover_reference: str,
    allow_legacy_fifo_state_bridge: bool = False,
    supplier_id: int | None = None,
    supplier_code: str | None = None,
) -> dict[str, Any]:
    try:
        qty = parse_quantity(quantity, "quantity", allow_zero=False)
    except QuantityError as exc:
        raise InventoryMutationError(str(exc)) from exc
    normalized_status = str(source_status or "").strip().upper()
    if normalized_status not in _VENDOR_HANDOVER_STATUSES:
        raise InventoryRuleError(
            "VENDOR_HANDOVER_STATUS_INVALID",
            "This stock status is not eligible for vendor handover.",
            context={"source_status": normalized_status},
        )

    balance = (
        await db.execute(
            select(InventoryBalance).where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == source_location_id,
                InventoryBalance.product_variant_id == product_variant_id,
                InventoryBalance.batch_id == batch_id,
                InventoryBalance.stock_status == normalized_status,
            )
        )
    ).scalar_one_or_none()
    if balance is None:
        raise InventoryRuleError(
            "VENDOR_HANDOVER_STOCK_NOT_FOUND",
            "No staged vendor-return quantity exists in this stock status.",
            context={
                "source_location_id": source_location_id,
                "product_variant_id": product_variant_id,
                "batch_id": batch_id,
                "source_status": normalized_status,
            },
        )
    before_on_hand = Decimal(balance.on_hand_quantity or 0)
    before_reserved = Decimal(balance.reserved_quantity or 0)
    movable_quantity = before_on_hand - before_reserved
    if movable_quantity < qty:
        raise InventoryRuleError(
            "VENDOR_HANDOVER_QUANTITY_EXCEEDS_MOVABLE",
            "The requested handover quantity exceeds unreserved staged stock.",
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
        transfer_purpose="RETURN_TO_VENDOR",
        destination_location_id=source_location_id,
        product_variant_id=product_variant_id,
        batch_id=batch_id,
        terminal_reference_type=FINAL_VENDOR_HANDOVER_REFERENCE_TYPE,
        requested_quantity=qty,
    )
    specs = [
        {
            "product_variant_id": product_variant_id,
            "batch_id": batch_id,
            "quantity": allocation.quantity,
            "movement_kind": "PHYSICAL",
            "reference_type": FINAL_VENDOR_HANDOVER_REFERENCE_TYPE,
            "reference_id": str(request_id),
            "idempotency_key": (
                f"FINAL-VENDOR-{request_id}-{allocation.transfer_header_id}"
            ),
            "source_location_id": source_location_id,
            "destination_location_id": None,
            "source_stock_status": normalized_status,
            "destination_stock_status": None,
            "transfer_header_id": allocation.transfer_header_id,
            "allow_legacy_fifo_state_bridge": allow_legacy_fifo_state_bridge,
            "notes": f"Vendor handover evidence: {vendor_reference}",
        }
        for allocation in allocations
    ]
    movements = await apply_inventory_movements_batch(
        db, company_id=company_id, performed_by=actor_id, movements=specs
    )
    if len(movements) != len(specs):
        raise RuntimeError("Unified movement engine returned an incomplete vendor-handover result.")
    movement_ids = [int(movement.id) for movement in movements]
    origin_ids = [allocation.transfer_header_id for allocation in allocations]

    refreshed = (
        await db.execute(
            select(InventoryBalance).where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == source_location_id,
                InventoryBalance.product_variant_id == product_variant_id,
                InventoryBalance.batch_id == batch_id,
                InventoryBalance.stock_status == normalized_status,
            )
        )
    ).scalar_one_or_none()
    if refreshed is None:
        raise RuntimeError("Unified movement removed the authoritative balance row unexpectedly.")
    remaining = Decimal(refreshed.on_hand_quantity or 0)
    exact_before = remaining + qty
    exact_reserved = Decimal(refreshed.reserved_quantity or 0)

    record_domain_event(
        db,
        company_id=company_id,
        actor_id=actor_id,
        request_id=request_id,
        event_type=FINAL_VENDOR_HANDOVER_EVENT,
        entity_type="InventoryMovement",
        entity_id=movement_ids[0],
        reason=f"Vendor handover: {vendor_reference}",
        before={
            "source_location_id": source_location_id,
            "product_variant_id": product_variant_id,
            "batch_id": batch_id,
            "stock_status": normalized_status,
            "on_hand_quantity": canonical_quantity(exact_before),
            "reserved_quantity": canonical_quantity(exact_reserved),
            "origin_transfer_header_ids": origin_ids,
        },
        after={
            "movement_ids": movement_ids,
            "handed_over_quantity": canonical_quantity(qty),
            "remaining_quantity": canonical_quantity(remaining),
            "vendor_name": vendor_name,
            "supplier_id": supplier_id,
            "supplier_code": supplier_code,
            "vendor_reference": vendor_reference,
            "handover_reference": handover_reference,
            "origin_transfer_header_ids": origin_ids,
        },
        emit_outbox=True,
    )
    return {
        "movement_ids": movement_ids,
        "product_variant_id": product_variant_id,
        "batch_id": batch_id,
        "source_location_id": source_location_id,
        "source_status": normalized_status,
        "handed_over_quantity": canonical_quantity(qty),
        "remaining_quantity": canonical_quantity(remaining),
        "origin_transfer_header_ids": origin_ids,
        "vendor_name": vendor_name,
        "supplier_id": supplier_id,
        "supplier_code": supplier_code,
        "vendor_reference": vendor_reference,
        "handover_reference": handover_reference,
        "event_type": FINAL_VENDOR_HANDOVER_EVENT,
    }
