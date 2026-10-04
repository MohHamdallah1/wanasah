"""Bounded inventory reads consumed through the public catalog warning contract."""
from collections.abc import Sequence
from typing import get_args

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from inventory_access import InventoryAccess
from models import Driver, InventoryBalance, ProductBatch
from .contracts import BatchRestrictionSummary, CurrentDispositionReason, DispositionCounts, RestrictedDisposition


def _summary_statement(company_id: int, variant_ids: Sequence[int]):
    restricted = select(
        ProductBatch.company_id, ProductBatch.product_variant_id,
        ProductBatch.id.label("batch_id"), ProductBatch.disposition,
        ProductBatch.disposition_reason, ProductBatch.disposition_revision,
    ).where(
        ProductBatch.company_id == company_id,
        ProductBatch.product_variant_id.in_(variant_ids),
        ProductBatch.disposition.in_(get_args(RestrictedDisposition)),
    ).cte("restricted_batches")

    # Aggregate locations/status buckets BEFORE joining: one row per batch,
    # so a batch in several balances never multiplies counts or its reason.
    quantities = select(
        InventoryBalance.company_id, InventoryBalance.product_variant_id,
        InventoryBalance.batch_id,
        func.sum(InventoryBalance.on_hand_quantity).label("on_hand"),
    ).join(restricted, and_(
        InventoryBalance.company_id == restricted.c.company_id,
        InventoryBalance.product_variant_id == restricted.c.product_variant_id,
        InventoryBalance.batch_id == restricted.c.batch_id,
    )).where(
        InventoryBalance.company_id == company_id,
        InventoryBalance.product_variant_id.in_(variant_ids),
    ).group_by(
        InventoryBalance.company_id, InventoryBalance.product_variant_id,
        InventoryBalance.batch_id,
    ).cte("restricted_quantities")

    totals = select(
        restricted.c.company_id,
        restricted.c.product_variant_id,
        func.count().label("affected_batch_count"),
        func.coalesce(func.sum(quantities.c.on_hand), 0).label("on_hand"),
        *(func.count().filter(restricted.c.disposition == code).label(code)
          for code in get_args(RestrictedDisposition)),
    ).select_from(restricted).outerjoin(quantities, and_(
        quantities.c.company_id == restricted.c.company_id,
        quantities.c.product_variant_id == restricted.c.product_variant_id,
        quantities.c.batch_id == restricted.c.batch_id,
    )).group_by(restricted.c.company_id, restricted.c.product_variant_id).cte("restriction_totals")

    reasons = select(
        restricted.c.company_id,
        restricted.c.product_variant_id, restricted.c.batch_id,
        restricted.c.disposition, restricted.c.disposition_reason,
        restricted.c.disposition_revision,
        func.row_number().over(
            partition_by=restricted.c.product_variant_id,
            order_by=restricted.c.batch_id.asc(),
        ).label("reason_rank"),
    ).where(restricted.c.disposition_reason.is_not(None)).cte("current_reasons")

    return select(
        totals, reasons.c.batch_id, reasons.c.disposition,
        reasons.c.disposition_reason, reasons.c.disposition_revision,
    ).outerjoin(reasons, and_(
        reasons.c.company_id == totals.c.company_id,
        reasons.c.product_variant_id == totals.c.product_variant_id,
        reasons.c.reason_rank == 1,
    )).execution_options(autoflush=False)


async def load_batch_restrictions(
    db: AsyncSession, *, actor: Driver, variant_ids: Sequence[int],
) -> dict[int, BatchRestrictionSummary | None]:
    """Read the already-authorized catalog page, never derive Product state.

    Company-wide inventory.read is mandatory for ANY company-wide batch evidence.
    Location-only grants must not reveal counts, quantities or reasons elsewhere.
    None means unavailable by permission; a zero DTO means a visible clear result.
    Caller retains catalog.read, the tenant/RLS session and page identity authority.
    """
    if type(actor.company_id) is not int or actor.company_id <= 0:
        raise ValueError("A positive authenticated company identity is required.")
    if len(variant_ids) > 200 or any(type(value) is not int or value <= 0 for value in variant_ids):
        raise ValueError("Expected at most 200 positive variant IDs.")
    ids = sorted(set(variant_ids))
    if not ids:
        return {}
    access = InventoryAccess(db, actor)
    if not bool(await db.scalar(select(access.allows("inventory.read")).execution_options(autoflush=False))):
        return dict.fromkeys(ids)

    rows = (await db.execute(_summary_statement(actor.company_id, ids))).mappings().all()
    summaries = {variant_id: BatchRestrictionSummary(
        affected_batch_count=0, affected_on_hand_quantity="0.000000",
        counts_by_disposition=DispositionCounts(),
    ) for variant_id in ids}
    for row in rows:
        reason = None if row["batch_id"] is None else CurrentDispositionReason(
            batch_id=int(row["batch_id"]), disposition=row["disposition"],
            disposition_revision=int(row["disposition_revision"]),
            disposition_reason=row["disposition_reason"],
        )
        summaries[int(row["product_variant_id"])] = BatchRestrictionSummary(
            affected_batch_count=int(row["affected_batch_count"]),
            affected_on_hand_quantity=format(row["on_hand"], ".6f"),
            counts_by_disposition=DispositionCounts(**{
                code: int(row[code]) for code in get_args(RestrictedDisposition)
            }),
            representative_reason=reason,
        )
    return summaries
