"""Inventory-owned live evidence read under the canonical location guard."""
from decimal import Decimal

from sqlalchemy import and_, func, or_, select

from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from domains.product_tracking import public_batch_number
from models import InventoryBalance, InventoryMovement, ProductBatch, ProductVariant, UOM

from .contracts import MAX_LINES, BalanceEvidence, CustodyRejected, VehicleSnapshot
from .policy import line_key, snapshot_token


async def movement_watermark(db, *, company_id: int, location_id: int) -> int:
    return int((await db.scalar(select(func.max(InventoryMovement.id)).where(
        InventoryMovement.company_id == company_id,
        or_(InventoryMovement.source_location_id == location_id,
            InventoryMovement.destination_location_id == location_id),
    ))) or 0)


async def load_vehicle_snapshot(db, *, company_id: int, session_id: int, responsibility):
    latest = (await db.scalars(select(VehicleCustodyEpoch).where(
        VehicleCustodyEpoch.company_id == company_id,
        VehicleCustodyEpoch.vehicle_id == responsibility.vehicle_id,
    ).order_by(VehicleCustodyEpoch.context_revision.desc()).limit(1))).one_or_none()
    if (latest is None or latest.state != "ACCEPTED"
            or latest.id not in responsibility.epoch_ids
            or latest.vehicle_location_id != responsibility.location_id):
        # A historical sealed receipt may still close finance after a legitimate
        # later takeover; a NEW physical count cannot count the later custodian's stock.
        raise CustodyRejected("VEHICLE_CUSTODY_ASSIGNED_TO_LATER_SESSION")
    first_epoch = min(responsibility.epoch_ids)
    foreign = await db.scalar(select(VehicleCustodyEpoch.id).where(
        VehicleCustodyEpoch.company_id == company_id,
        VehicleCustodyEpoch.vehicle_id == responsibility.vehicle_id,
        VehicleCustodyEpoch.id >= first_epoch,
        VehicleCustodyEpoch.id.not_in(responsibility.epoch_ids),
    ).limit(1))
    if foreign is not None:
        raise CustodyRejected("INTERVENING_VEHICLE_CUSTODY_REQUIRES_REVIEW")
    found = (await db.execute(select(
        InventoryBalance, ProductVariant, ProductBatch, UOM.code,
    ).join(ProductVariant, and_(
        ProductVariant.company_id == InventoryBalance.company_id,
        ProductVariant.id == InventoryBalance.product_variant_id,
    )).join(ProductBatch, and_(
        ProductBatch.company_id == InventoryBalance.company_id,
        ProductBatch.id == InventoryBalance.batch_id,
        ProductBatch.product_variant_id == InventoryBalance.product_variant_id,
    )).join(UOM, UOM.id == ProductVariant.base_uom_id).where(
        InventoryBalance.company_id == company_id,
        InventoryBalance.location_id == responsibility.location_id,
        or_(InventoryBalance.on_hand_quantity > 0, InventoryBalance.reserved_quantity > 0),
    ).order_by(InventoryBalance.product_variant_id, InventoryBalance.batch_id,
               InventoryBalance.stock_status).limit(MAX_LINES + 1))).all()
    rows = tuple(BalanceEvidence(
        b.product_variant_id, b.batch_id, b.stock_status,
        Decimal(b.on_hand_quantity), Decimal(b.reserved_quantity),
        int(v.quantity_scale), Decimal(v.quantity_step), v.name, v.sku,
        public_batch_number(batch.batch_number),
        batch.expiry_date.isoformat() if batch.expiry_date else None, uom,
    ) for b, v, batch, uom in found)
    snapshot = VehicleSnapshot(
        company_id, session_id, responsibility, latest.id, latest.context_revision,
        await movement_watermark(db, company_id=company_id, location_id=responsibility.location_id), rows,
    )
    snapshot_token(snapshot)  # Validate all rows, including reserved/non-AVAILABLE.
    return snapshot


def present_snapshot(snapshot):
    from quantity import canonical_quantity
    return {
        "vehicle_id": snapshot.responsibility.vehicle_id,
        "snapshot_token": snapshot_token(snapshot),
        "epoch_count": len(snapshot.responsibility.epoch_ids),
        "lines": [{
            "line_key": line_key(snapshot, row), "product_name": row.product_name,
            "sku": row.sku, "batch_number": row.lot, "expiry_date": row.expiry,
            "stock_status": row.stock_status, "uom": row.uom,
            "expected_quantity": canonical_quantity(row.quantity),
        } for row in snapshot.rows],
    }
