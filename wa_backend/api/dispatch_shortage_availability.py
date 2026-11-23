"""Backoffice read-only evidence from a selected FIELD representative's accepted vehicle custody.

A quote is not a stock reservation or delivery promise. Missing/ambiguous/stale
custody is UNKNOWN, never interpreted as zero physical stock.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from database import get_db
from dispatch_access import require_vehicle
from domains.authorization.backoffice_access import BackofficeCapabilityAccess, BackofficeCapabilityAccessRejected
from domains.dispatch_representatives import has_canonical_field_identity
from domains.dispatch.route_execution.custody.proofs import CustodyRejected
from domains.dispatch_shortage_selected_stock import read_selected_vehicle_stock
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from domains.identity.migration.models import IdentityLegacyDriverMap
from models import Driver, ProductVariant, UOM
from quantity import QUANTITY_MAX, canonical_quantity

router = APIRouter()
MAX_PRODUCTS = 240
_ALLOWED_VEHICLE_STATES = frozenset({
    "AVAILABLE", "QUARANTINED", "BLOCKED", "RECALLED", "DAMAGED", "DISPOSAL_PENDING",
})


def _unknown(reason: str) -> dict:
    return {"status": "UNKNOWN", "reason": reason, "items": []}


def _nonnegative(value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError("Invalid vehicle stock evidence") from exc
    if not amount.is_finite() or amount < 0 or amount > QUANTITY_MAX:
        raise ValueError("Invalid vehicle stock evidence")
    return amount


def _sellable_by_variant(
    *, lines: list[dict],
    batches: dict[int, tuple[int, object, str]],
    today, product_ids: set[int],
) -> dict[int, Decimal] | None:
    """AVAILABLE, unreserved, RELEASED, unexpired vehicle stock only."""
    totals = {product_id: Decimal(0) for product_id in product_ids}
    for line in lines:
        try:
            product_id = int(line["variant_id"])
            if product_id not in product_ids:
                continue
            batch = batches.get(int(line["batch_id"]))
            if batch is None or batch[0] != product_id:
                return None
            on_hand = _nonnegative(line["on_hand"])
            reserved = _nonnegative(line["reserved"])
            if reserved > on_hand or line["status"] not in _ALLOWED_VEHICLE_STATES:
                return None
            if (
                line["status"] == "AVAILABLE"
                and batch[2] == "RELEASED"
                and (batch[1] is None or batch[1] >= today)
            ):
                totals[product_id] += on_hand - reserved
                if totals[product_id] > QUANTITY_MAX:
                    return None
        except (ValueError, TypeError, KeyError, OverflowError):
            return None
    return totals


@router.get("/dispatch/shortages/vehicle-availability")
async def shortage_vehicle_availability(
    driver_id: int = Query(..., gt=0),
    product_ids: list[int] = Query(..., min_length=1, max_length=MAX_PRODUCTS),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    """Current signed vehicle snapshot for selected IDs, not permission to fulfill.

    shortage.create AND dispatch.read (on actual authorized vehicle location)
    are both mandatory; no client vehicle/location/batch selection is trusted.
    """
    if len(set(product_ids)) != len(product_ids) or any(type(x) is not int or x <= 0 for x in product_ids):
        raise HTTPException(422, detail={"code": "SHORTAGE_AVAILABILITY_PRODUCT_IDS_INVALID", "context": {}})
    try:
        # Without an accepted epoch the vehicle location is unknowable; still
        # require dispatch.read on at least one persisted authorized location
        # before exposing whether the representative/products/custody exist.
        # An actual accepted vehicle is additionally checked by require_vehicle.
        await access.require("shortage.create")
        await access.require("dispatch.read", any_location=True)
    except BackofficeCapabilityAccessRejected as exc:
        raise HTTPException(403, detail={"code": "SHORTAGE_AVAILABILITY_CAPABILITY_DENIED", "context": {}}) from exc
    company_id = access.company_id

    representative_id = await db.scalar(
        select(IdentityLegacyDriverMap.field_representative_id)
        .join(Driver, and_(
            Driver.company_id == IdentityLegacyDriverMap.company_id,
            Driver.id == IdentityLegacyDriverMap.legacy_driver_id,
        ))
        .where(
            IdentityLegacyDriverMap.company_id == company_id,
            IdentityLegacyDriverMap.legacy_driver_id == driver_id,
            Driver.is_active.is_(True),
            has_canonical_field_identity(company_id=company_id, legacy_driver_id=driver_id),
        )
    )
    if representative_id is None:
        raise HTTPException(404, detail={"code": "SHORTAGE_AVAILABILITY_REP_NOT_FOUND", "context": {}})

    variants = (await db.execute(
        select(ProductVariant.id, UOM.code).join(UOM, UOM.id == ProductVariant.base_uom_id)
        .where(ProductVariant.company_id == company_id, ProductVariant.id.in_(product_ids))
    )).all()
    base_units = {int(row[0]): str(row[1]) for row in variants}
    if len(base_units) != len(product_ids) or any(not unit for unit in base_units.values()):
        raise HTTPException(404, detail={"code": "SHORTAGE_AVAILABILITY_PRODUCT_NOT_FOUND", "context": {}})

    epochs = (await db.scalars(
        select(VehicleCustodyEpoch)
        .where(
            VehicleCustodyEpoch.company_id == company_id,
            VehicleCustodyEpoch.field_representative_id == representative_id,
            VehicleCustodyEpoch.custodian_kind == "FIELD_REPRESENTATIVE",
            VehicleCustodyEpoch.state == "ACCEPTED",
            VehicleCustodyEpoch.ended_at.is_(None),
        ).order_by(VehicleCustodyEpoch.id.desc()).limit(2)
    )).all()
    if not epochs:
        return _unknown("NO_ACCEPTED_VEHICLE_CUSTODY")
    if len(epochs) != 1:
        return _unknown("AMBIGUOUS_VEHICLE_CUSTODY")
    epoch = epochs[0]
    await require_vehicle(access, "dispatch.read", int(epoch.vehicle_id))
    try:
        state = await read_selected_vehicle_stock(
            db, company_id, int(epoch.vehicle_id), set(product_ids),
            expected_epoch_id=int(epoch.id),
            expected_representative_id=int(representative_id),
            expected_principal_id=int(epoch.custodian_principal_id or 0),
        )
    except CustodyRejected:
        return _unknown("VEHICLE_STOCK_UNVERIFIED")
    if (
        state.epoch is None or int(state.epoch.id) != int(epoch.id)
        or state.epoch.state != "ACCEPTED"
        or state.epoch.custodian_kind != "FIELD_REPRESENTATIVE"
        or int(state.epoch.field_representative_id or 0) != int(representative_id)
        or int(state.epoch.custodian_principal_id or 0) != int(epoch.custodian_principal_id or 0)
        or state.location_id != int(epoch.vehicle_location_id)
    ):
        return _unknown("VEHICLE_CUSTODY_CHANGED")

    # Only requested SKU rows/batches were read under the SAME transaction
    # guard as stock writers.  No whole-vehicle balance list and no lifetime
    # COUNT/MAX inventory_movements call. The marker is selected-quote scoped,
    # opaque, and NEVER an authorization, reservation or delivery proof.
    quantities = _sellable_by_variant(
        lines=state.lines, batches=state.batches,
        today=state.company_day, product_ids=set(product_ids),
    )
    if quantities is None:
        return _unknown("VEHICLE_STOCK_UNVERIFIED")
    # A role/location revocation after the initial access check must not admit
    # a quote using an earlier permission snapshot.
    await require_vehicle(access, "dispatch.read", int(epoch.vehicle_id))
    return {
        "status": "VERIFIED",
        "source": "CANONICAL_VEHICLE_CUSTODY",
        "vehicle_id": int(epoch.vehicle_id),
        "vehicle_location_id": int(state.location_id),
        "custody_epoch_id": int(epoch.id),
        "stock_snapshot": state.stock_snapshot,
        "items": [
            {"product_id": str(product_id),
             "available_base": canonical_quantity(quantities[product_id]),
             "base_uom": base_units[product_id]}
            for product_id in product_ids
        ],
    }
