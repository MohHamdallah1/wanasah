"""#1071 — bounded, read-only canonical selected-SKU vehicle custody evidence.

The normal FIELD/settlement snapshot and its whole-vehicle movement watermark
remain EXACTLY unchanged. This opt-in reader is for non-binding Dashboard
shortage quotes and, after a separate LEAD acceptance, a manager's promotion
recheck. It does NOT authorize fulfillment or reserve stock.

Lock order: resolve canonical active vehicle location -> acquire tenant-scoped
inventory location transaction guard (shared for quotes, EXCLUSIVE for an
approval/recheck) -> validate vehicle + accepted epoch -> read ONLY selected
balances/batches. Stock writers acquire that SAME location guard exclusively.
Never acquire selected balance row locks BEFORE this guard. The guard must be
held through the caller's transaction and response decision.

stock_snapshot is deliberately a SELECTED-QUOTE marker, not FIELD's existing
full-vehicle custody fingerprint and never an approval/idempotency authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import InventoryBalance, InventoryLocation, ProductBatch, ProductVariant, Vehicle
from product_lifecycle import ROUTE_SALE_OPEN, evaluate_product_capability
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from domains.dispatch.route_execution.custody.proofs import CustodyRejected, digest
from domains.vehicles.contracts import VehicleError
from domains.vehicles.eligibility import vehicle_is_operational
from domains.vehicles.repository import read_canonical_custody_location_id
from services import acquire_inventory_location_guard, get_company_local_date

MAX_SELECTED_PRODUCTS = 240
MAX_SELECTED_STOCK_LINES = 10000


@dataclass(frozen=True)
class SelectedVehicleStock:
    vehicle_id: int
    location_id: int
    epoch: VehicleCustodyEpoch
    # Selected rows ONLY; never claim to represent all stock in the vehicle.
    lines: list[dict]
    batches: dict[int, tuple[int, date | None, str]]
    company_day: date
    stock_snapshot: str

    @property
    def revision(self) -> int:
        return int(self.epoch.context_revision)


def _selected_scope(product_ids: set[int]) -> list[int]:
    if (
        not isinstance(product_ids, set)
        or not (1 <= len(product_ids) <= MAX_SELECTED_PRODUCTS)
        or any(type(value) is not int or value <= 0 for value in product_ids)
    ):
        raise CustodyRejected("CUSTODY_SELECTED_PRODUCTS_INVALID", 422)
    return sorted(product_ids)


async def read_selected_vehicle_stock(
    db: AsyncSession,
    company_id: int,
    vehicle_id: int,
    product_ids: set[int],
    *,
    expected_epoch_id: int | None = None,
    expected_representative_id: int | None = None,
    expected_principal_id: int | None = None,
    for_approval: bool = False,
) -> SelectedVehicleStock:
    """Return a transaction-guarded, tenant-bound SELECTED stock projection.

    The 10,001 limit is on matching SELECTED SKU rows, not unrelated vehicle
    inventory. A selected SKU with >10k status/lot rows fails UNKNOWN, never
    truncates. There is no query at all against inventory_movements.

    for_approval=True takes the EXCLUSIVE inventory guard and row locks. An
    approving caller must invoke this *before* taking any balance row locks;
    it must still independently verify its business authorization, matching
    route, visit, remaining-demand and command idempotency inside the SAME
    transaction. Neither this projection nor stock_snapshot grants delivery.
    """
    if type(company_id) is not int or company_id <= 0 or type(vehicle_id) is not int or vehicle_id <= 0:
        raise CustodyRejected("CUSTODY_SELECTED_SCOPE_INVALID", 422)
    wanted = _selected_scope(product_ids)
    # Never let a promotion/approval reader omit the signed assignment to
    # a specific epoch + FIELD representative + principal. Quote calls may
    # omit these when no manager mutation is being authorized.
    if for_approval and (
        expected_epoch_id is None or expected_representative_id is None
        or expected_principal_id is None
    ):
        raise CustodyRejected("CUSTODY_APPROVAL_SIGNED_SCOPE_REQUIRED", 422)
    if expected_epoch_id is not None and (type(expected_epoch_id) is not int or expected_epoch_id <= 0):
        raise CustodyRejected("CUSTODY_EPOCH_INVALID", 422)
    if expected_representative_id is not None and (
        type(expected_representative_id) is not int or expected_representative_id <= 0
    ):
        raise CustodyRejected("CUSTODY_REPRESENTATIVE_INVALID", 422)

    # Same canonical all-history location cardinality as global snapshot,
    # but NOT the lifetime inventory-movement scan.
    try:
        location_id = await read_canonical_custody_location_id(
            db, company_id=company_id, vehicle_id=vehicle_id, require_active=True,
        )
    except VehicleError as exc:
        raise CustodyRejected(exc.code, exc.status_code) from exc
    # This guard also fences the selected stock+lot reads against all normal
    # movement engine writers. Exclusive mode is reserved for manager approval.
    await acquire_inventory_location_guard(
        db, company_id, location_id, exclusive=for_approval,
    )
    try:
        confirmed_location = await read_canonical_custody_location_id(
            db, company_id=company_id, vehicle_id=vehicle_id, require_active=True,
        )
    except VehicleError as exc:
        raise CustodyRejected(exc.code, exc.status_code) from exc
    if confirmed_location != location_id:
        raise CustodyRejected("CUSTODY_LOCATION_CHANGED")

    vehicle = await db.scalar(select(Vehicle).where(
        Vehicle.company_id == company_id, Vehicle.id == vehicle_id,
    ).execution_options(populate_existing=True))
    if not vehicle_is_operational(vehicle):
        raise CustodyRejected("CUSTODY_VEHICLE_NOT_OPERATIONAL")
    location = await db.scalar(select(InventoryLocation).where(
        InventoryLocation.company_id == company_id,
        InventoryLocation.id == location_id,
        InventoryLocation.vehicle_id == vehicle_id,
        InventoryLocation.location_type == "VEHICLE",
        InventoryLocation.is_active.is_(True),
    ).execution_options(populate_existing=True))
    if location is None:
        raise CustodyRejected("CUSTODY_LOCATION_CHANGED")

    epoch_query = select(VehicleCustodyEpoch).where(
        VehicleCustodyEpoch.company_id == company_id,
        VehicleCustodyEpoch.vehicle_id == vehicle_id,
        VehicleCustodyEpoch.ended_at.is_(None),
    ).order_by(VehicleCustodyEpoch.id.asc()).limit(2).execution_options(
        populate_existing=True,
    )
    if for_approval:
        epoch_query = epoch_query.with_for_update()
    epochs = (await db.scalars(epoch_query)).all()
    if len(epochs) != 1:
        raise CustodyRejected("CUSTODY_EPOCH_AMBIGUOUS" if epochs else "CUSTODY_EPOCH_MISSING")
    epoch = epochs[0]
    if (
        int(epoch.vehicle_location_id) != location_id
        or epoch.state != "ACCEPTED"
        or epoch.custodian_kind != "FIELD_REPRESENTATIVE"
        or epoch.field_representative_id is None
        or epoch.custodian_principal_id is None
        or (expected_epoch_id is not None and int(epoch.id) != expected_epoch_id)
        or (expected_representative_id is not None and
            int(epoch.field_representative_id) != expected_representative_id)
        or (expected_principal_id is not None and
            int(epoch.custodian_principal_id) != expected_principal_id)
    ):
        raise CustodyRejected("CUSTODY_EPOCH_NOT_SIGNED_FIELD")

    # Do not report blocked/held/retiring products as vehicle availability.
    # This is a bounded query for at most 240 selected SKUs.
    variants = (await db.execute(
        select(ProductVariant.id, ProductVariant.lifecycle_status,
               ProductVariant.operational_hold)
        .where(ProductVariant.company_id == company_id,
               ProductVariant.id.in_(wanted))
    )).all()
    if len(variants) != len(wanted) or {int(v[0]) for v in variants} != product_ids:
        raise CustodyRejected("CUSTODY_SELECTED_PRODUCT_MISSING")
    for _, lifecycle, hold in variants:
        if not evaluate_product_capability(lifecycle, hold, ROUTE_SALE_OPEN).allowed:
            raise CustodyRejected("CUSTODY_SELECTED_PRODUCT_NOT_SELLABLE")

    query = select(
        InventoryBalance.product_variant_id, InventoryBalance.batch_id,
        InventoryBalance.stock_status, InventoryBalance.on_hand_quantity,
        InventoryBalance.reserved_quantity, InventoryBalance.last_updated,
    ).where(
        InventoryBalance.company_id == company_id,
        InventoryBalance.location_id == location_id,
        InventoryBalance.product_variant_id.in_(wanted),
    ).order_by(
        InventoryBalance.product_variant_id,
        InventoryBalance.batch_id,
        InventoryBalance.stock_status,
    ).limit(MAX_SELECTED_STOCK_LINES + 1)
    if for_approval:
        query = query.with_for_update()
    stock = (await db.execute(query)).all()
    if len(stock) > MAX_SELECTED_STOCK_LINES:
        raise CustodyRejected("CUSTODY_SELECTED_STOCK_WINDOW_EXCEEDED")
    lines = [
        dict(
            variant_id=int(row[0]), batch_id=int(row[1]), status=str(row[2]),
            on_hand=str(row[3]), reserved=str(row[4]),
            last_updated=str(row[5]),
        )
        for row in stock
    ]
    batch_ids = sorted({line["batch_id"] for line in lines})
    batches: dict[int, tuple[int, date | None, str]] = {}
    if batch_ids:
        rows = (await db.execute(
            select(ProductBatch.id, ProductBatch.product_variant_id,
                   ProductBatch.expiry_date, ProductBatch.disposition)
            .where(ProductBatch.company_id == company_id,
                   ProductBatch.id.in_(batch_ids))
        )).all()
        batches = {int(row[0]): (int(row[1]), row[2], str(row[3])) for row in rows}
        if len(batches) != len(batch_ids):
            raise CustodyRejected("CUSTODY_SELECTED_BATCH_UNVERIFIED")
    company_day = await get_company_local_date(db, company_id)
    # This is an O(selected balances + selected batches) fingerprint. It
    # deliberately excludes ALL past movements and all other vehicle SKUs.
    # No frontend or backend may interpret this as a full-vehicle authority.
    marker = digest({
        "purpose": "SHORTAGE_SELECTED_QUOTE_V1",
        "company_id": company_id, "vehicle_id": vehicle_id,
        "location_id": location_id,
        "location_version": int(location.version),
        "epoch_id": int(epoch.id),
        "epoch_revision": int(epoch.context_revision),
        "epoch_principal_id": int(epoch.custodian_principal_id),
        "field_representative_id": int(epoch.field_representative_id),
        "products": wanted,
        "lines": lines,
        "batches": [(batch_id, batches[batch_id]) for batch_id in batch_ids],
        "company_day": company_day.isoformat(),
        "lifecycle": sorted((int(row[0]), str(row[1]), str(row[2])) for row in variants),
    })
    return SelectedVehicleStock(
        vehicle_id=vehicle_id, location_id=location_id, epoch=epoch,
        lines=lines, batches=batches, company_day=company_day,
        stock_snapshot="selected-quote-v1:" + marker,
    )
