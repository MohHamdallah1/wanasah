from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from sqlalchemy import and_, func, or_, select
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


async def _read_terminal_origins_bounded(db, statement, *, max_rows: int, limit_message: str):
    # Enforce capacity in SQL before materializing history. The overflow-only
    # aggregate retains the existing exact error count without loading its rows.
    rows = (await db.execute(statement.limit(max_rows + 1))).all()
    if len(rows) > max_rows:
        total = await db.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )
        raise InventoryRuleError(
            "TERMINAL_ORIGIN_EVIDENCE_LIMIT",
            limit_message,
            context={"origin_document_count": int(total)},
        )
    return rows


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
        await _read_terminal_origins_bounded(
            db,
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
                InventoryTransferHeader.transfer_purpose == transfer_purpose,
                InventoryTransferHeader.status == "POSTED",
                or_(
                    and_(
                        InventoryTransferHeader.workflow_type == "TRANSIT",
                        InventoryTransferHeader.destination_location_id == destination_location_id,
                    ),
                    and_(
                        InventoryTransferHeader.workflow_type == "DIRECT",
                        InventoryTransferHeader.reference_number.like("QSTG-%"),
                        InventoryTransferHeader.source_location_id == destination_location_id,
                    ),
                ),
                InventoryTransferLine.product_variant_id == product_variant_id,
                InventoryTransferLine.batch_id == batch_id,
            )
            .order_by(InventoryTransferHeader.id.asc()),
            max_rows=500,
            limit_message="Too many staging documents exist for one product batch at this location.",
        )
    )
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


async def read_terminal_origin_availability_for_batches(
    db: AsyncSession,
    *,
    company_id: int,
    destination_location_ids: Iterable[int],
    product_variant_id: int,
    batch_ids: Iterable[int],
) -> dict[tuple[str, int, int], Decimal]:
    """Read terminal staging evidence for one bounded batch page in two queries.

    Keys are ``(purpose, batch_id, destination_location_id)``. This is advisory
    read evidence only; terminal mutations re-run exact provenance allocation
    under an advisory transaction guard and the unified movement engine owns the
    authoritative stock locks.
    """
    location_ids = sorted({int(value) for value in destination_location_ids})
    normalized_batch_ids = sorted({int(value) for value in batch_ids})
    if not location_ids or not normalized_batch_ids:
        return {}
    if len(location_ids) > 500:
        raise InventoryRuleError(
            "TERMINAL_SOURCE_LIMIT_EXCEEDED",
            "Too many readable stock sources for terminal-action discovery.",
        )
    if len(normalized_batch_ids) > 50:
        raise InventoryRuleError(
            "TERMINAL_BATCH_PAGE_LIMIT_EXCEEDED",
            "Too many batches were requested for terminal-action discovery.",
        )

    purposes = tuple(TERMINAL_REFERENCE_TYPE_BY_PURPOSE)
    origin_rows = (
        await _read_terminal_origins_bounded(
            db,
            select(
                InventoryTransferHeader.id.label("header_id"),
                InventoryTransferHeader.workflow_type,
                InventoryTransferHeader.source_location_id,
                InventoryTransferHeader.destination_location_id,
                InventoryTransferHeader.transfer_purpose,
                InventoryTransferLine.batch_id,
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
                InventoryTransferHeader.transfer_purpose.in_(purposes),
                InventoryTransferHeader.status == "POSTED",
                or_(
                    and_(
                        InventoryTransferHeader.workflow_type == "TRANSIT",
                        InventoryTransferHeader.destination_location_id.in_(location_ids),
                    ),
                    and_(
                        InventoryTransferHeader.workflow_type == "DIRECT",
                        InventoryTransferHeader.reference_number.like("QSTG-%"),
                        InventoryTransferHeader.source_location_id.in_(location_ids),
                    ),
                ),
                InventoryTransferLine.product_variant_id == product_variant_id,
                InventoryTransferLine.batch_id.in_(normalized_batch_ids),
            )
            .order_by(
                InventoryTransferHeader.id.asc(),
                InventoryTransferLine.batch_id.asc(),
            ),
            max_rows=10_000,
            limit_message="Too many terminal staging documents exist for this batch page.",
        )
    )
    if not origin_rows:
        return {}
    origin_meta: dict[tuple[int, int], tuple[str, int, Decimal]] = {}
    for row in origin_rows:
        header_id = int(row.header_id)
        batch_id = int(row.batch_id)
        key = (header_id, batch_id)
        if key in origin_meta:
            # DB uniqueness should prevent this for one product+batch per transfer.
            raise InventoryRuleError(
                "TERMINAL_ORIGIN_EVIDENCE_INCONSISTENT",
                "Duplicate terminal staging evidence exists for one transfer batch.",
                context={"transfer_header_id": header_id, "batch_id": batch_id},
            )
        workflow_type = str(row.workflow_type).upper()
        staged_location_id = (
            int(row.source_location_id)
            if workflow_type == "DIRECT"
            else int(row.destination_location_id)
        )
        origin_meta[key] = (
            str(row.transfer_purpose).upper(),
            staged_location_id,
            Decimal(row.quantity or 0),
        )

    header_ids = sorted({header_id for header_id, _batch_id in origin_meta})
    consumed_rows = (
        await db.execute(
            select(
                InventoryMovement.transfer_header_id,
                InventoryMovement.batch_id,
                InventoryMovement.source_location_id,
                InventoryMovement.reference_type,
                func.coalesce(func.sum(InventoryMovement.quantity), 0).label("quantity"),
            )
            .where(
                InventoryMovement.company_id == company_id,
                InventoryMovement.transfer_header_id.in_(header_ids),
                InventoryMovement.product_variant_id == product_variant_id,
                InventoryMovement.batch_id.in_(normalized_batch_ids),
                InventoryMovement.source_location_id.in_(location_ids),
                InventoryMovement.destination_location_id.is_(None),
                InventoryMovement.reference_type.in_(
                    tuple(TERMINAL_REFERENCE_TYPE_BY_PURPOSE.values())
                ),
            )
            .group_by(
                InventoryMovement.transfer_header_id,
                InventoryMovement.batch_id,
                InventoryMovement.source_location_id,
                InventoryMovement.reference_type,
            )
        )
    ).all()

    consumed_by_origin: dict[tuple[int, int], Decimal] = {}
    for row in consumed_rows:
        key = (int(row.transfer_header_id), int(row.batch_id))
        meta = origin_meta.get(key)
        if meta is None:
            continue
        purpose, expected_location_id, _staged = meta
        expected_reference = TERMINAL_REFERENCE_TYPE_BY_PURPOSE[purpose]
        if (
            int(row.source_location_id) != expected_location_id
            or str(row.reference_type) != expected_reference
        ):
            raise InventoryRuleError(
                "TERMINAL_ORIGIN_EVIDENCE_INCONSISTENT",
                "Terminal movement evidence does not match its staging origin.",
                context={
                    "transfer_header_id": key[0],
                    "batch_id": key[1],
                },
            )
        consumed_by_origin[key] = consumed_by_origin.get(key, Decimal("0")) + Decimal(
            row.quantity or 0
        )

    available: dict[tuple[str, int, int], Decimal] = {}
    for (header_id, batch_id), (purpose, location_id, staged) in origin_meta.items():
        consumed = consumed_by_origin.get((header_id, batch_id), Decimal("0"))
        if consumed < 0 or consumed > staged:
            raise InventoryRuleError(
                "TERMINAL_ORIGIN_EVIDENCE_INCONSISTENT",
                "Terminal consumption exceeds immutable staging evidence.",
                context={
                    "transfer_header_id": header_id,
                    "batch_id": batch_id,
                    "staged_quantity": canonical_quantity(staged),
                    "consumed_quantity": canonical_quantity(consumed),
                },
            )
        key = (purpose, batch_id, location_id)
        available[key] = available.get(key, Decimal("0")) + (staged - consumed)
    return available


async def read_terminal_origin_availability(
    db: AsyncSession,
    *,
    company_id: int,
    destination_location_ids: Iterable[int],
    product_variant_id: int,
    batch_id: int,
) -> dict[tuple[str, int], Decimal]:
    """Compatibility wrapper for the single-batch stock-source read."""
    page = await read_terminal_origin_availability_for_batches(
        db,
        company_id=company_id,
        destination_location_ids=destination_location_ids,
        product_variant_id=product_variant_id,
        batch_ids=[batch_id],
    )
    return {
        (purpose, location_id): quantity
        for (purpose, _batch_id, location_id), quantity in page.items()
    }
