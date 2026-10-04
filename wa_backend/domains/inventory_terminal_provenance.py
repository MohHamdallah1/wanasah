from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import InventoryMovement, InventoryTransferHeader, InventoryTransferLine
from quantity import canonical_quantity
from services import InventoryRuleError


TERMINAL_REFERENCE_TYPE_BY_PURPOSE = {
    "DISPOSAL": "FINAL_DISPOSAL",
    "RETURN_TO_VENDOR": "FINAL_VENDOR_HANDOVER",
}


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


async def read_terminal_origin_availability(
    db: AsyncSession,
    *,
    company_id: int,
    destination_location_ids: Iterable[int],
    product_variant_id: int,
    batch_id: int,
) -> dict[tuple[str, int], Decimal]:
    """Read unconsumed terminal staging evidence with constant query count.

    This is advisory read evidence only. Terminal mutations re-run the
    provenance allocator under its transaction advisory guard and the unified
    movement engine revalidates current stock under row locks.
    """
    location_ids = sorted({int(value) for value in destination_location_ids})
    if not location_ids:
        return {}
    if len(location_ids) > 500:
        raise InventoryRuleError(
            "TERMINAL_SOURCE_LIMIT_EXCEEDED",
            "Too many readable stock sources for terminal-action discovery.",
        )

    purposes = tuple(TERMINAL_REFERENCE_TYPE_BY_PURPOSE)
    origin_rows = (
        await db.execute(
            select(
                InventoryTransferHeader.id.label("header_id"),
                InventoryTransferHeader.destination_location_id,
                InventoryTransferHeader.transfer_purpose,
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
                InventoryTransferHeader.transfer_purpose.in_(purposes),
                InventoryTransferHeader.status == "POSTED",
                InventoryTransferHeader.destination_location_id.in_(location_ids),
                InventoryTransferLine.product_variant_id == product_variant_id,
                InventoryTransferLine.batch_id == batch_id,
            )
            .order_by(InventoryTransferHeader.id.asc())
        )
    ).all()
    if not origin_rows:
        return {}
    if len(origin_rows) > 1000:
        raise InventoryRuleError(
            "TERMINAL_ORIGIN_EVIDENCE_LIMIT",
            "Too many terminal staging documents exist for this batch.",
            context={"origin_document_count": len(origin_rows)},
        )

    header_meta: dict[int, tuple[str, int, Decimal]] = {}
    for row in origin_rows:
        header_id = int(row.header_id)
        purpose = str(row.transfer_purpose).upper()
        location_id = int(row.destination_location_id)
        quantity = Decimal(row.quantity or 0)
        previous = header_meta.get(header_id)
        if previous is not None:
            # Transfer-line identity guarantees one line for product+batch.
            raise InventoryRuleError(
                "TERMINAL_ORIGIN_EVIDENCE_INCONSISTENT",
                "Duplicate terminal staging evidence exists for one transfer.",
                context={"transfer_header_id": header_id},
            )
        header_meta[header_id] = (purpose, location_id, quantity)

    consumed_rows = (
        await db.execute(
            select(
                InventoryMovement.transfer_header_id,
                InventoryMovement.reference_type,
                func.coalesce(func.sum(InventoryMovement.quantity), 0).label("quantity"),
            )
            .where(
                InventoryMovement.company_id == company_id,
                InventoryMovement.transfer_header_id.in_(list(header_meta)),
                InventoryMovement.product_variant_id == product_variant_id,
                InventoryMovement.batch_id == batch_id,
                InventoryMovement.destination_location_id.is_(None),
                InventoryMovement.reference_type.in_(
                    tuple(TERMINAL_REFERENCE_TYPE_BY_PURPOSE.values())
                ),
            )
            .group_by(
                InventoryMovement.transfer_header_id,
                InventoryMovement.reference_type,
            )
        )
    ).all()
    consumed_by_header: dict[int, Decimal] = {}
    for row in consumed_rows:
        header_id = int(row.transfer_header_id)
        meta = header_meta.get(header_id)
        if meta is None:
            continue
        expected_reference = TERMINAL_REFERENCE_TYPE_BY_PURPOSE[meta[0]]
        if str(row.reference_type) != expected_reference:
            continue
        consumed_by_header[header_id] = Decimal(row.quantity or 0)

    available: dict[tuple[str, int], Decimal] = {}
    for header_id, (purpose, location_id, staged) in header_meta.items():
        consumed = consumed_by_header.get(header_id, Decimal("0"))
        if consumed < 0 or consumed > staged:
            raise InventoryRuleError(
                "TERMINAL_ORIGIN_EVIDENCE_INCONSISTENT",
                "Terminal consumption exceeds immutable staging evidence.",
                context={
                    "transfer_header_id": header_id,
                    "staged_quantity": canonical_quantity(staged),
                    "consumed_quantity": canonical_quantity(consumed),
                },
            )
        key = (purpose, location_id)
        available[key] = available.get(key, Decimal("0")) + (staged - consumed)
    return available
