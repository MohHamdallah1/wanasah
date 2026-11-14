"""Owner-approved #773: untouched, single-supplier-receipt current Lot metadata.

No new purchase, stock move, valuation or historic invoice mutation. The
caller must hold the canonical warehouse exclusive guard before any write.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.inventory_supplier_evidence import InventorySupplierEvidence
from domains.product_tracking import is_reserved_internal_batch_number
from domains.live_stock_projection.service import refresh_live_stock_keys
from models import (
    InventoryBalance, InventoryCostEvent, InventoryLocation, InventoryLock,
    InventoryMovement, ProductBatch, ProductVariant, StocktakeSession, utc_now,
)
from .models import BatchMetadataCorrectionEvent


class BatchCorrectionRejected(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status
        super().__init__(code)


def _values(batch: ProductBatch) -> dict:
    return {
        "batch_number": str(batch.batch_number),
        "production_date": batch.production_date.isoformat() if batch.production_date else None,
        "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
    }


async def inspect_batch(
    db: AsyncSession, *, company_id: int, batch_id: int, location_id: int,
    locked: bool = False,
) -> dict:
    """Fail closed on all ambiguous source/quantity/stocktake states."""
    query = select(ProductBatch).where(
        ProductBatch.company_id == company_id, ProductBatch.id == batch_id,
    )
    if locked:
        query = query.with_for_update()
    batch = await db.scalar(query)
    if batch is None:
        raise BatchCorrectionRejected("BATCH_NOT_FOUND", 404)
    state = {
        "batch_id": batch_id, "product_variant_id": int(batch.product_variant_id),
        "location_id": location_id, "metadata_revision": int(batch.metadata_revision),
        "current": _values(batch), "disposition": batch.disposition,
        "eligible": False, "block_code": None, "source_invoice": None,
        "source_movement_id": None, "source_cost_event_id": None,
    }
    def blocked(code: str) -> dict:
        state["block_code"] = code
        return state

    loc = await db.scalar(select(InventoryLocation).where(
        InventoryLocation.company_id == company_id,
        InventoryLocation.id == location_id,
        InventoryLocation.is_active.is_(True),
        InventoryLocation.location_type == "WAREHOUSE",
        InventoryLocation.is_system_managed.is_(False),
    ))
    if loc is None:
        return blocked("BATCH_LOCATION_UNAVAILABLE")
    variant = await db.scalar(select(ProductVariant).where(
        ProductVariant.company_id == company_id,
        ProductVariant.id == batch.product_variant_id,
    ))
    if variant is None or not batch.is_active:
        return blocked("BATCH_PRODUCT_UNAVAILABLE")
    if (str(variant.lot_control_mode) == "NONE"
            or is_reserved_internal_batch_number(str(batch.batch_number))):
        return blocked("BATCH_INTERNAL_LOT_NOT_EDITABLE")
    if str(batch.disposition) not in {"RELEASED", "QUARANTINED"}:
        return blocked("BATCH_UNDER_RECALL_OR_BLOCK")
    # Exactly one POSTED supplier physical inbound movement for this batch.
    # Even a reverted transfer, released reservation, sale or stocktake
    # adjustment makes exact printed carton identity unprovable.
    movements = (await db.scalars(select(InventoryMovement).where(
        InventoryMovement.company_id == company_id,
        InventoryMovement.batch_id == batch_id,
    ).order_by(InventoryMovement.id).limit(2))).all()
    if len(movements) != 1:
        return blocked("BATCH_USED_OR_SHARED_RECEIPT")
    movement = movements[0]
    if not (
        movement.reference_type == "INBOUND_SUPPLIER"
        and movement.movement_kind == "PHYSICAL"
        and movement.source_location_id is None
        and movement.destination_location_id == location_id
        and movement.destination_stock_status == "AVAILABLE"
        and str(movement.reference_id).strip()
    ):
        return blocked("BATCH_NOT_SINGLE_SUPPLIER_RECEIPT")
    supplier = await db.scalar(select(InventorySupplierEvidence).where(
        InventorySupplierEvidence.company_id == company_id,
        InventorySupplierEvidence.movement_id == movement.id,
    ))
    if supplier is None:
        return blocked("BATCH_SUPPLIER_EVIDENCE_MISSING")
    costs = (await db.scalars(select(InventoryCostEvent).where(
        InventoryCostEvent.company_id == company_id,
        InventoryCostEvent.batch_id == batch_id,
    ).limit(2))).all()
    if len(costs) != 1:
        return blocked("BATCH_COST_PROVENANCE_AMBIGUOUS")
    cost = costs[0]
    if not (
        cost.inventory_movement_id == movement.id
        and cost.event_type == "PURCHASE_IN"
        and cost.cost_basis == "PURCHASE_ACTUAL"
        and cost.method in ("FIFO", "MOVING_AVERAGE")
        and Decimal(cost.quantity) == Decimal(movement.quantity)
    ):
        return blocked("BATCH_ORIGINAL_COST_MISSING")
    balances_query = select(InventoryBalance).where(
        InventoryBalance.company_id == company_id,
        InventoryBalance.batch_id == batch_id,
    )
    if locked:
        balances_query = balances_query.with_for_update()
    balances = (await db.scalars(balances_query)).all()
    if (len(balances) != 1 or balances[0].location_id != location_id
            or balances[0].stock_status != "AVAILABLE"
            or Decimal(balances[0].reserved_quantity) != 0
            or Decimal(balances[0].on_hand_quantity) <= 0
            or Decimal(balances[0].on_hand_quantity) != Decimal(movement.quantity)):
        return blocked("BATCH_STOCK_MOVED_RESERVED_OR_CHANGED")
    inventory_lock = await db.scalar(select(InventoryLock.id).where(
        InventoryLock.company_id == company_id,
        InventoryLock.location_id == location_id,
        InventoryLock.released_at.is_(None),
        or_(InventoryLock.product_variant_id.is_(None),
            InventoryLock.product_variant_id == batch.product_variant_id),
        or_(InventoryLock.batch_id.is_(None), InventoryLock.batch_id == batch_id),
    ).limit(1))
    if inventory_lock is not None:
        return blocked("BATCH_ACTIVE_STOCKTAKE_LOCK")
    active_count = await db.scalar(select(StocktakeSession.id).where(
        StocktakeSession.company_id == company_id,
        StocktakeSession.location_id == location_id,
        StocktakeSession.status.in_(
            ("DRAFT", "COUNTING", "PENDING_REVIEW", "RECOUNT_REQUIRED", "APPROVED")
        ),
        or_(StocktakeSession.stocktake_type != "CYCLE_COUNT",
            and_(StocktakeSession.scope_product_variant_id == batch.product_variant_id,
                 or_(StocktakeSession.scope_batch_id.is_(None),
                     StocktakeSession.scope_batch_id == batch_id))),
    ).limit(1))
    if active_count is not None:
        return blocked("BATCH_ACTIVE_STOCKTAKE")
    state.update({
        "eligible": True, "source_invoice": str(movement.reference_id),
        "source_movement_id": int(movement.id),
        "source_cost_event_id": int(cost.id),
    })
    return state


async def correct_current_metadata(
    db: AsyncSession, *, company_id: int, batch_id: int, location_id: int,
    expected_revision: int, request_id: str, actor_principal_id: int,
    actor_username: str, actor_auth_revision: int, reason: str,
    new_batch_number: str, new_production_date: date | None,
    new_expiry_date: date | None, local_today: date,
) -> dict:
    state = await inspect_batch(
        db, company_id=company_id, batch_id=batch_id,
        location_id=location_id, locked=True,
    )
    if not state["eligible"]:
        raise BatchCorrectionRejected(state["block_code"])
    if state["metadata_revision"] != expected_revision:
        raise BatchCorrectionRejected("BATCH_METADATA_STALE_RELOAD")
    batch = await db.scalar(select(ProductBatch).where(
        ProductBatch.company_id == company_id, ProductBatch.id == batch_id,
    ))
    variant = await db.scalar(select(ProductVariant).where(
        ProductVariant.company_id == company_id,
        ProductVariant.id == batch.product_variant_id,
    ))
    lot = new_batch_number.strip()
    if not lot or len(lot) > 100 or is_reserved_internal_batch_number(lot):
        raise BatchCorrectionRejected("BATCH_INVALID_PRINTED_LOT", 422)
    if new_production_date is not None and new_production_date > local_today:
        raise BatchCorrectionRejected("BATCH_PRODUCTION_IN_FUTURE", 422)
    if new_production_date and new_expiry_date and new_production_date > new_expiry_date:
        raise BatchCorrectionRejected("BATCH_DATES_INCONSISTENT", 422)
    if str(variant.expiry_control_mode) == "REQUIRED" and new_expiry_date is None:
        raise BatchCorrectionRejected("BATCH_EXPIRY_REQUIRED", 422)
    if str(variant.expiry_control_mode) == "NONE" and new_expiry_date is not None:
        raise BatchCorrectionRejected("BATCH_EXPIRY_NOT_ALLOWED", 422)
    collision = await db.scalar(select(ProductBatch.id).where(
        ProductBatch.company_id == company_id,
        ProductBatch.product_variant_id == batch.product_variant_id,
        ProductBatch.id != batch_id,
        func.lower(ProductBatch.batch_number) == lot.lower(),
    ).limit(1))
    if collision is not None:
        raise BatchCorrectionRejected("BATCH_LOT_COLLIDES")
    before = state["current"]
    after = {
        "batch_number": lot,
        "production_date": new_production_date.isoformat() if new_production_date else None,
        "expiry_date": new_expiry_date.isoformat() if new_expiry_date else None,
    }
    if before == after:
        raise BatchCorrectionRejected("BATCH_METADATA_UNCHANGED", 422)
    batch.batch_number = lot
    batch.production_date = new_production_date
    batch.expiry_date = new_expiry_date
    batch.metadata_revision = expected_revision + 1
    batch.updated_at = utc_now()
    db.add(BatchMetadataCorrectionEvent(
        company_id=company_id, batch_id=batch_id, location_id=location_id,
        source_movement_id=state["source_movement_id"],
        source_cost_event_id=state["source_cost_event_id"],
        source_invoice=state["source_invoice"], revision=int(batch.metadata_revision),
        request_id=request_id, actor_principal_id=actor_principal_id,
        actor_username=actor_username, actor_auth_revision=actor_auth_revision,
        verified_at=utc_now(), reason=reason.strip(), before_values=before,
        after_values=after,
    ))
    await db.flush()
    # Re-evaluate cached expiry/risk/FEFO view on the same transaction.
    await refresh_live_stock_keys(
        db, company_id=company_id,
        keys=[(location_id, int(batch.product_variant_id))],
    )
    return {
        "batch_id": batch_id, "metadata_revision": int(batch.metadata_revision),
        "before": before, "current": after, "disposition": batch.disposition,
        "source_invoice": state["source_invoice"],
        "actor_username": actor_username, "reason": reason.strip(),
    }


async def correction_history(
    db: AsyncSession, *, company_id: int, batch_id: int, limit: int = 50,
) -> list[dict]:
    rows = (await db.scalars(select(BatchMetadataCorrectionEvent).where(
        BatchMetadataCorrectionEvent.company_id == company_id,
        BatchMetadataCorrectionEvent.batch_id == batch_id,
    ).order_by(BatchMetadataCorrectionEvent.id.desc()).limit(limit))).all()
    return [{
        "revision": int(row.revision), "verified_at": row.verified_at.isoformat() + "Z",
        "actor_username": row.actor_username, "source_invoice": row.source_invoice,
        "reason": row.reason, "before": row.before_values, "after": row.after_values,
    } for row in rows]
