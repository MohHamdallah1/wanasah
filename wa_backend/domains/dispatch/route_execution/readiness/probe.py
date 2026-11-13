"""M05 read-only eligibility probe; M02 writer revalidates under DB locks.

Only returns a positive, current FIELD-custodian proof for a fully authorized
target pair. All unavailable identities, invalid scope, stale revision, ambiguous
epoch/field bridge and inactive resources fail closed with a constant-size code.
No balances, stock, finance or other candidate identities are returned.
"""
from __future__ import annotations

from sqlalchemy import func, or_, select

from models import DispatchRoute, Driver, InventoryLocation, Vehicle, WorkSession, Zone
from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from domains.dispatch_representatives import has_canonical_field_identity
from domains.identity.migration.models import IdentityLegacyDriverMap
from domains.identity.models import CompanyPrincipal
from domains.auth_sessions.context import FieldRequestContext
from domains.authorization.field_access import FieldCapabilityAccess, FieldCapabilityAccessRejected
from domains.vehicles.eligibility import vehicle_is_operational


class LifecycleReadinessRejected(Exception):
    def __init__(self, code: str, *, status: int = 409):
        self.code = code
        self.status = status
        super().__init__(code)


async def read_lifecycle_readiness(
    db, *, access, route_id: int, driver_id: int, vehicle_id: int,
) -> dict:
    cid = access.company_id
    route = (await db.execute(select(DispatchRoute).where(
        DispatchRoute.company_id == cid, DispatchRoute.id == route_id,
    ))).scalar_one_or_none()
    if route is None:
        raise LifecycleReadinessRejected("M05_ROUTE_UNAVAILABLE", status=404)
    continuing_pause = route.status == "waiting" and route.assignment_context_revision > 1
    if route.status != "postponed" and not continuing_pause:
        raise LifecycleReadinessRejected("M05_ROUTE_NOT_POSTPONED")
    zone = await db.scalar(select(Zone.id).where(
        Zone.company_id == cid, Zone.id == route.zone_id, Zone.is_active.is_(True),
    ))
    if zone is None:
        raise LifecycleReadinessRejected("M05_ROUTE_NOT_AVAILABLE")
    # POSTPONED has no live period. WAITING continuation MUST have exactly
    # one signed current period and the identical representative/vehicle;
    # it cannot use this read as an implicit reassignment permission.
    period = DispatchRouteExecutionPeriod
    open_periods = (await db.execute(select(period).where(
        period.company_id == cid, period.route_id == route_id,
        period.ended_at.is_(None), period.state.in_(("ACTIVE", "PLANNED")),
    ).order_by(period.id.asc()).limit(2))).scalars().all()
    paused_period = None
    if continuing_pause:
        if len(open_periods) != 1:
            raise LifecycleReadinessRejected("M05_PAUSE_PERIOD_UNVERIFIED")
        paused_period = open_periods[0]
        if (paused_period.context_revision != route.assignment_context_revision or
            paused_period.driver_id != driver_id or paused_period.vehicle_id != vehicle_id or
            paused_period.field_representative_id is None or
            paused_period.vehicle_location_id is None or
            paused_period.request_id is None or paused_period.payload_hash is None):
            raise LifecycleReadinessRejected("M05_PAUSE_CONTEXT_STALE")
    elif open_periods:
        raise LifecycleReadinessRejected("M05_ROUTE_ALREADY_ASSIGNED")
    driver = await db.scalar(select(Driver).where(
        Driver.company_id == cid, Driver.id == driver_id, Driver.is_active.is_(True),
    ))
    vehicle = await db.scalar(select(Vehicle).where(
        Vehicle.company_id == cid, Vehicle.id == vehicle_id,
    ))
    if driver is None or not vehicle_is_operational(vehicle):
        raise LifecycleReadinessRejected("M05_TARGET_UNAVAILABLE")
    if not await db.scalar(select(1).where(
        has_canonical_field_identity(company_id=cid, legacy_driver_id=driver_id),
    )):
        raise LifecycleReadinessRejected("M05_TARGET_FIELD_UNVERIFIED")
    bridge = IdentityLegacyDriverMap
    identities = (await db.execute(select(
        bridge.field_representative_id, bridge.field_principal_id,
    ).where(
        bridge.company_id == cid,
        bridge.legacy_driver_id == driver_id,
        has_canonical_field_identity(company_id=cid, legacy_driver_id=driver_id),
    ).limit(2))).all()
    if len(identities) != 1 or identities[0][0] is None or identities[0][1] is None:
        raise LifecycleReadinessRejected("M05_TARGET_FIELD_UNVERIFIED")
    representative_id, principal_id = map(int, identities[0])
    principal = await db.scalar(select(CompanyPrincipal).where(
        CompanyPrincipal.company_id == cid,
        CompanyPrincipal.id == principal_id,
        CompanyPrincipal.is_active.is_(True),
    ))
    if principal is None:
        raise LifecycleReadinessRejected("M05_TARGET_FIELD_UNVERIFIED")
    try:
        await FieldCapabilityAccess(
            db,
            FieldRequestContext(
                principal_id=principal_id, company_id=cid,
                representative_id=representative_id,
                auth_revision=int(principal.auth_revision),
            ),
        ).require_all(("work_session.execute", "visit.execute"))
    except FieldCapabilityAccessRejected:
        raise LifecycleReadinessRejected("M05_TARGET_FIELD_UNAVAILABLE")
    # Enforce current M01 driver/vehicle partial-unique guards before the user
    # sees "ready"; acceptance remains subject to M02 transactional checks.
    if await db.scalar(select(period.id).where(
        period.company_id == cid, period.ended_at.is_(None),
        period.state.in_(("ACTIVE", "PLANNED")),
        or_(period.driver_id == driver_id, period.vehicle_id == vehicle_id),
        *([period.id != paused_period.id] if paused_period is not None else []),
    ).limit(1)) is not None:
        raise LifecycleReadinessRejected("M05_TARGET_IN_USE")

    locations = (await db.execute(select(InventoryLocation.id).where(
        InventoryLocation.company_id == cid,
        InventoryLocation.vehicle_id == vehicle_id,
        InventoryLocation.location_type == "VEHICLE",
        InventoryLocation.is_active.is_(True),
    ).limit(2))).scalars().all()
    if len(locations) != 1:
        raise LifecycleReadinessRejected("M05_VEHICLE_LOCATION_UNAVAILABLE")
    location_id = int(locations[0])
    if paused_period is not None and (
        paused_period.vehicle_location_id != location_id or
        paused_period.field_representative_id != representative_id
    ):
        raise LifecycleReadinessRejected("M05_PAUSE_CONTEXT_STALE")
    # Historical/retired duplicates can still make M02 reject even if the
    # sole *active* location looks fine; count all locations for this vehicle.
    location_count = await db.scalar(select(func.count(InventoryLocation.id)).where(
        InventoryLocation.company_id == cid,
        InventoryLocation.vehicle_id == vehicle_id,
        InventoryLocation.location_type == "VEHICLE",
    ))
    if location_count != 1:
        raise LifecycleReadinessRejected("M05_VEHICLE_LOCATION_UNAVAILABLE")
    epochs = (await db.execute(select(VehicleCustodyEpoch).where(
        VehicleCustodyEpoch.company_id == cid,
        VehicleCustodyEpoch.vehicle_id == vehicle_id,
        VehicleCustodyEpoch.ended_at.is_(None),
    ).limit(2))).scalars().all()
    if len(epochs) != 1:
        raise LifecycleReadinessRejected("M05_CUSTODY_REQUIRED")
    epoch = epochs[0]
    if paused_period is not None and (
        paused_period.field_representative_id != epoch.field_representative_id or
        paused_period.vehicle_location_id != epoch.vehicle_location_id
    ):
        raise LifecycleReadinessRejected("M05_PAUSED_CUSTODY_CHANGED")
    if (
        epoch.state != "ACCEPTED"
        or epoch.vehicle_location_id != location_id
        or epoch.custodian_kind != "FIELD_REPRESENTATIVE"
        or epoch.custodian_principal_id != principal_id
        or epoch.field_representative_id != representative_id
        or epoch.accepted_by_principal_id is None
        or epoch.request_id is None or epoch.payload_hash is None
    ):
        raise LifecycleReadinessRejected("M05_CUSTODY_REQUIRED")
    latest_revision = await db.scalar(select(func.max(VehicleCustodyEpoch.context_revision)).where(
        VehicleCustodyEpoch.company_id == cid,
        VehicleCustodyEpoch.vehicle_id == vehicle_id,
    ))
    if latest_revision != epoch.context_revision:
        raise LifecycleReadinessRejected("M05_CUSTODY_STALE")
    sessions = (await db.execute(select(WorkSession).where(
        WorkSession.company_id == cid, WorkSession.driver_id == driver_id,
        WorkSession.end_time.is_(None),
    ).limit(2))).scalars().all()
    if len(sessions) > 1 or any(s.is_settled for s in sessions):
        raise LifecycleReadinessRejected("M05_TARGET_SESSION_UNAVAILABLE")
    if paused_period is not None and paused_period.work_session_id is not None and (
        len(sessions) != 1 or sessions[0].id != paused_period.work_session_id
    ):
        raise LifecycleReadinessRejected("M05_PAUSED_SESSION_CHANGED")
    return {
        "driverId": driver_id,
        "vehicleId": vehicle_id,
        "custodyRevision": int(epoch.context_revision),
        "accepted": True,
        "authorized": True,
        "assignmentContextRevision": int(route.assignment_context_revision),
    }
