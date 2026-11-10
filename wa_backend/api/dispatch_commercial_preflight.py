"""D11: read-only advisory of the ACTUAL published route-launch authorities.

Never creates a Route, locks/changes physical stock, or reserves a D07 UUID.
The POST /dispatch/route still rechecks everything under its canonical locks.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from api.warehouse._shared import _active_full_warehouse_audit_lock
from database import get_db
from dispatch_access import require_any_location, require_location, require_vehicle
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.dispatch_representatives import has_canonical_field_identity
from domains.offers.core import OfferError
from domains.offers.eligibility import current_offer_revision_ceiling
from domains.pricing.context import _read_lock_snapshot
from domains.pricing.core import PricingError
from domains.sales_calculation.policy import (
    CommercialPolicyError, resolve_commercial_rounding_policy,
)
from domains.taxation.core import TaxError, current_tax_revision_ceiling
from domains.vehicles import (
    VehicleError, resolve_vehicle_custody_location_id, vehicle_is_operational,
)
from models import (
    Company, DispatchRoute, Driver, InventoryBalance, InventoryLocation,
    Vehicle, WorkSession, Zone,
)

router = APIRouter()


async def _execute_access(
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
) -> BackofficeCapabilityAccess:
    await require_any_location(access, "dispatch.execute")
    return access


def _entry(ready: bool, code: str = "READY", **context) -> dict:
    return {"ready": ready, "code": code, "context": context}


@router.get("/dispatch/route/commercial-preflight", status_code=200)
async def route_commercial_preflight(
    zone_id: int = Query(gt=0),
    driver_id: int = Query(gt=0),
    vehicle_id: int = Query(gt=0),
    source_location_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_execute_access),
):
    """Bounded current-authority snapshot for the selected launch context.

    A 200 means this READ succeeded, not that a route may execute. The 'ready'
    field is false until every authority passes. 401/403 are returned by real
    Bearer/warehouse/vehicle capability checks, never converted to ready=false.
    """
    company_id = int(access.company_id)
    await require_location(access, "dispatch.execute", source_location_id)
    await require_vehicle(access, "dispatch.execute", vehicle_id)

    checks: dict[str, dict] = {}
    warehouse = await db.scalar(select(InventoryLocation).where(
        InventoryLocation.id == source_location_id,
        InventoryLocation.company_id == company_id,
        InventoryLocation.location_type == "WAREHOUSE",
        InventoryLocation.is_active.is_(True),
    ))
    if warehouse is None:
        checks["warehouse"] = _entry(False, "SOURCE_WAREHOUSE_INVALID")
    else:
        active_lock = await _active_full_warehouse_audit_lock(
            db, company_id=company_id, location_id=source_location_id,
        )
        checks["warehouse"] = (
            _entry(False, "SOURCE_WAREHOUSE_AUDIT_LOCK",
                   stocktake_reference=active_lock.stocktake_reference)
            if active_lock else _entry(True)
        )

    vehicle = await db.scalar(select(Vehicle).where(
        Vehicle.company_id == company_id, Vehicle.id == vehicle_id,
    ))
    if not vehicle_is_operational(vehicle):
        checks["vehicle"] = _entry(False, "VEHICLE_NOT_OPERATIONAL")
        custody_id = None
    else:
        try:
            custody_id = await resolve_vehicle_custody_location_id(
                db, company_id=company_id, vehicle_id=vehicle_id,
            )
            checks["vehicle"] = _entry(True)
        except VehicleError as exc:
            custody_id = None
            checks["vehicle"] = _entry(False, exc.code)

    driver = await db.scalar(select(Driver.id).where(
        Driver.company_id == company_id,
        Driver.id == driver_id, Driver.is_active.is_(True),
        has_canonical_field_identity(company_id=company_id, legacy_driver_id=Driver.id),
    ))
    checks["driver"] = _entry(driver is not None, "READY" if driver is not None else "DRIVER_UNAVAILABLE")
    zone = await db.scalar(select(Zone.id).where(
        Zone.company_id == company_id, Zone.id == zone_id, Zone.is_active.is_(True),
    ))
    checks["zone"] = _entry(zone is not None, "READY" if zone is not None else "ZONE_UNAVAILABLE")

    if driver is not None:
        active_session = await db.scalar(select(WorkSession.id).where(
            WorkSession.company_id == company_id,
            WorkSession.driver_id == driver_id, WorkSession.end_time.is_(None),
        ).limit(1))
        unsettled = await db.scalar(select(WorkSession.id).where(
            WorkSession.company_id == company_id, WorkSession.driver_id == driver_id,
            WorkSession.end_time.is_not(None), WorkSession.is_settled.is_(False),
        ).limit(1))
        if active_session is not None:
            checks["session"] = _entry(False, "DRIVER_SESSION_ACTIVE")
        elif unsettled is not None:
            checks["session"] = _entry(False, "DRIVER_SETTLEMENT_REQUIRED")
        else:
            checks["session"] = _entry(True)
    else:
        checks["session"] = _entry(False, "DRIVER_UNAVAILABLE")

    conflict = await db.scalar(select(DispatchRoute.id).where(
        DispatchRoute.company_id == company_id,
        DispatchRoute.status.in_(["active", "waiting", "postponed"]),
        or_(DispatchRoute.zone_id == zone_id, DispatchRoute.driver_id == driver_id,
            DispatchRoute.vehicle_id == vehicle_id),
    ).limit(1))
    checks["route"] = _entry(conflict is None, "READY" if conflict is None else "ROUTE_ALREADY_ASSIGNED")

    if custody_id is not None:
        reserved = await db.scalar(select(func.coalesce(func.sum(InventoryBalance.reserved_quantity), 0)).where(
            InventoryBalance.company_id == company_id,
            InventoryBalance.location_id == custody_id,
            InventoryBalance.stock_status == "AVAILABLE",
        ))
        checks["custody"] = _entry(not bool(reserved), "READY" if not reserved else "VEHICLE_RESERVATIONS_PENDING")
    else:
        checks["custody"] = _entry(False, "VEHICLE_CUSTODY_UNAVAILABLE")

    # Use the SAME Pricing selector used at POST launch, not a UI count or
    # homegrown PriceBook/Assignment resolution.
    when = datetime.now(timezone.utc)
    company_currency = (await db.scalar(select(Company.currency_code).where(
        Company.id == company_id,
    ))) or ""
    currency = str(company_currency).strip().upper()
    try:
        verified_currency, publication, assignment, _ = await _read_lock_snapshot(
            db, company_id=company_id, locked_at=when,
        )
        checks["pricing"] = _entry(True, publication_revision=publication,
                                   assignment_revision=assignment)
        currency = verified_currency
    except PricingError as exc:
        checks["pricing"] = _entry(False, exc.code, **(exc.context or {}))

    try:
        tax_revision = await current_tax_revision_ceiling(db, company_id, as_of=when)
        # Revision proves a published tax version. A legitimately published
        # zero-percent component is READY; no published version is BLOCKED.
        checks["tax"] = (_entry(True, revision=tax_revision) if tax_revision > 0
                         else _entry(False, "TAX_CONFIGURATION_REQUIRED"))
    except TaxError as exc:
        checks["tax"] = _entry(False, exc.code)

    try:
        rounding = await resolve_commercial_rounding_policy(
            db, company_id=company_id, as_of=when,
            expected_currency_code=currency or None,
        )
        checks["rounding"] = _entry(True, revision=int(rounding.policy_revision))
    except CommercialPolicyError as exc:
        checks["rounding"] = _entry(False, exc.code)

    try:
        offer_ceiling = await current_offer_revision_ceiling(
            db, company_id=company_id, as_of=when,
        )
        checks["offers"] = _entry(True, revision=int(offer_ceiling))
    except OfferError as exc:
        checks["offers"] = _entry(False, exc.code)

    return {
        "ready": all(check["ready"] for check in checks.values()),
        "currency_code": currency if currency else None,
        "checks": checks,
        # Advisory only. All authorities will be rechecked on the original POST.
        "advisory": True,
    }
