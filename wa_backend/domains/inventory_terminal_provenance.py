from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import InventoryMovement, InventoryTransferHeader, InventoryTransferLine
from quantity import canonical_quantity
from services import InventoryRuleError


@dataclass(frozen=True)
class TerminalOriginAllocation:
    transfer_header_id: int
    transfer_reference: str
    quantity: Decimal


async def allocate_terminal_origin_quantity(
    db: AsyncSession,
    *,
    company_id: int,
    transfer_purpose: str,
    destination_location_id: int,
    product_variant_id: int,
    batch_id: int,
    terminal_reference_type: str,
    requested_quantity: Decimal,
) -> list[TerminalOriginAllocation]:
    """Allocate terminal quantity against immutable posted staging evidence.

    A transaction advisory guard serializes terminal consumption for the same
    purpose/location/product/batch without changing the unified movement engine's
    canonical lifecycle/location/balance lock order.
    """
    guard_key = (
        f"terminal:{transfer_purpose}:{destination_location_id}:"
        f"{product_variant_id}:{batch_id}"
    )
    await db.execute(
        select(
            func.pg_advisory_xact_lock(
                int(company_id),
                func.hashtext(guard_key),
            )
        )
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
                InventoryTransferHeader.transfer_purpose == transfer_purpose,
                InventoryTransferHeader.status == "POSTED",
                InventoryTransferHeader.destination_location_id == destination_location_id,
                InventoryTransferLine.product_variant_id == product_variant_id,
                InventoryTransferLine.batch_id == batch_id,
            )
            .order_by(InventoryTransferHeader.id.asc())
        )
    ).all()
    if not origin_rows:
        raise InventoryRuleError(
            "TERMINAL_ORIGIN_EVIDENCE_MISSING",
            "Terminal stock action requires a posted staging-transfer origin.",
            context={
                "transfer_purpose": transfer_purpose,
                "destination_location_id": destination_location_id,
                "product_variant_id": product_variant_id,
                "batch_id": batch_id,
            },
        )
    if len(origin_rows) > 500:
        raise InventoryRuleError(
            "TERMINAL_ORIGIN_EVIDENCE_LIMIT",
            "Too many staging documents exist for one product batch at this location.",
            context={"origin_document_count": len(origin_rows)},
        )

    header_ids = [int(row.header_id) for row in origin_rows]
    consumed_rows = (
        await db.execute(
            select(
                InventoryMovement.transfer_header_id,
                func.coalesce(func.sum(InventoryMovement.quantity), 0).label("quantity"),
            )
            .where(
                InventoryMovement.company_id == company_id,
                InventoryMovement.transfer_header_id.in_(header_ids),
                InventoryMovement.product_variant_id == product_variant_id,
                InventoryMovement.batch_id == batch_id,
                InventoryMovement.source_location_id == destination_location_id,
                InventoryMovement.destination_location_id.is_(None),
                InventoryMovement.reference_type == terminal_reference_type,
            )
            .group_by(InventoryMovement.transfer_header_id)
        )
    ).all()
    consumed = {
        int(row.transfer_header_id): Decimal(row.quantity or 0)
        for row in consumed_rows
    }

    requested_remaining = Decimal(requested_quantity)
    allocations: list[TerminalOriginAllocation] = []
    for row in origin_rows:
        header_id = int(row.header_id)
        staged = Decimal(row.quantity or 0)
        already_consumed = consumed.get(header_id, Decimal("0"))
        if already_consumed < 0 or already_consumed > staged:
            raise InventoryRuleError(
                "TERMINAL_ORIGIN_EVIDENCE_INCONSISTENT",
                "Terminal consumption exceeds immutable staging evidence.",
                context={
                    "transfer_header_id": header_id,
                    "staged_quantity": canonical_quantity(staged),
                    "consumed_quantity": canonical_quantity(already_consumed),
                },
            )
        available = staged - already_consumed
        if available <= 0:
            continue
        take = min(available, requested_remaining)
        allocations.append(TerminalOriginAllocation(
            transfer_header_id=header_id,
            transfer_reference=str(row.reference_number),
            quantity=take,
        ))
        requested_remaining -= take
        if requested_remaining == 0:
            break

    if requested_remaining != 0:
        raise InventoryRuleError(
            "TERMINAL_STAGING_EVIDENCE_SHORTAGE",
            "The requested terminal quantity exceeds unconsumed staging evidence.",
            context={
                "requested_quantity": canonical_quantity(requested_quantity),
                "missing_quantity": canonical_quantity(requested_remaining),
            },
        )
    return allocations
