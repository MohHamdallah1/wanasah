"""M03: new daily period from unchanged, settled, signed FIELD assignment.

This bounded FIELD-only continuation is NOT an M02 POSTPONE/RESUME/CLOSE, and
never changes a route/zone schedule, physical stock, custody or historical Visit.
It only signs a new PLANNED period with monotonic assignment revision. The
existing M03 PLANNED->ACTIVE/start owns creating exactly one new WorkSession.
"""
from __future__ import annotations

import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    DispatchRoute, InventoryLocation, RouteCommercialContext, Vehicle,
    WorkSession, Zone, utc_now,
)
from domains.auth_sessions.context import FieldRequestContext
from domains.authorization.field_access import (
    FieldCapabilityAccess, FieldCapabilityAccessRejected,
)
from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
from domains.vehicles.eligibility import vehicle_is_operational
from domains.work_session_multi_route.context import (
    SessionPeriodRejected, _current_custody,
)


async def require_previous_day_closed(
    db: AsyncSession, *, company_id: int, driver_id: int,
) -> None:
    """No concurrent open S1 (also when its session date was yesterday)."""
    open_session = await db.scalar(
        select(WorkSession.id).where(
            WorkSession.company_id == company_id,
            WorkSession.driver_id == driver_id,
            WorkSession.end_time.is_(None),
        ).order_by(WorkSession.id.asc()).limit(1)
    )
    if open_session is not None:
        raise SessionPeriodRejected("M03_PREVIOUS_SESSION_NOT_ENDED")


async def prepare_next_day_period(
    db: AsyncSession, *, field_context: FieldRequestContext, driver_id: int,
    company_local_date, request_id: str | None,
) -> bool:
    """Create a PLANNED period only from a fully settled previous FIELD day.

    Called under the caller's Driver FOR UPDATE and idempotency advisory lock.
    Locks follow M02 relative order: Vehicle -> Zone -> Route -> Period -> Epoch.
    A newer M02 manager transition or custody reassignment fails closed.
    """
    company_id = int(field_context.company_id)
    if not (driver_id > 0 and company_id > 0):
        raise SessionPeriodRejected("M03_CONTINUATION_IDENTITY_INVALID", status_code=403)

    previous = await db.scalar(
        select(WorkSession).where(
            WorkSession.company_id == company_id,
            WorkSession.driver_id == driver_id,
            WorkSession.end_time.is_not(None),
        ).order_by(WorkSession.session_date.desc(), WorkSession.id.desc()).limit(1)
    )
    if previous is None or previous.session_date >= company_local_date:
        return False
    if not previous.is_settled or previous.end_time is None:
        raise SessionPeriodRejected("M03_PREVIOUS_DAY_NOT_FULLY_SETTLED")

    # The ONLY possible automatic continuation is the precise period signed
    # closed by FIELD End Work, not a random old M02 POSTPONE/CLOSE period.
    periods = (await db.scalars(
        select(DispatchRouteExecutionPeriod).where(
            DispatchRouteExecutionPeriod.company_id == company_id,
            DispatchRouteExecutionPeriod.work_session_id == previous.id,
            DispatchRouteExecutionPeriod.driver_id == driver_id,
            DispatchRouteExecutionPeriod.field_representative_id == field_context.representative_id,
            DispatchRouteExecutionPeriod.evidence_origin == "CANONICAL",
            DispatchRouteExecutionPeriod.state == "CLOSED",
            DispatchRouteExecutionPeriod.reason == "WORK_SESSION_ENDED",
            DispatchRouteExecutionPeriod.ended_at == previous.end_time,
        ).order_by(DispatchRouteExecutionPeriod.id.desc()).limit(2)
    )).all()
    if not periods:
        return False  # old single-route V1 behaviour remains unchanged
    if len(periods) != 1:
        raise SessionPeriodRejected("M03_DAY2_AMBIGUOUS_PREVIOUS_PERIOD")
    last = periods[0]
    if previous.inventory_reconciled_at is None:
        raise SessionPeriodRejected("M03_PREVIOUS_DAY_INVENTORY_NOT_RECONCILED")
    if (
        last.started_by_principal_id is None or last.ended_by_principal_id is None
        or not last.request_id or not last.payload_hash
        or last.vehicle_location_id is None or last.commercial_context_id is None
        or last.context_revision is None
    ):
        raise SessionPeriodRejected("M03_DAY2_PREVIOUS_EVIDENCE_INVALID")

    if not request_id or not request_id.strip():
        raise SessionPeriodRejected("M03_START_REQUEST_ID_REQUIRED")
    if last.context_revision >= 2**63 - 1:
        raise SessionPeriodRejected("M03_DAY2_CONTEXT_REVISION_EXHAUSTED")

    try:
        await FieldCapabilityAccess(db, field_context).require_all(
            ("work_session.execute", "visit.execute")
        )
    except FieldCapabilityAccessRejected as exc:
        raise SessionPeriodRejected("M03_DAY2_FIELD_CAPABILITY_REVOKED", status_code=403) from exc

    # M02 takes Vehicle then Zone then Route locks for this authorized actor.
    vehicle = await db.scalar(select(Vehicle).where(
        Vehicle.company_id == company_id, Vehicle.id == last.vehicle_id,
    ).with_for_update())
    if not vehicle_is_operational(vehicle):
        raise SessionPeriodRejected("M03_DAY2_VEHICLE_INACTIVE")

    # Pre-read zone solely to establish the M02-consistent lock order; the
    # route/zone relationship is verified AGAIN while the route is locked.
    snapshot = await db.scalar(select(DispatchRoute).where(
        DispatchRoute.company_id == company_id,
        DispatchRoute.id == last.route_id,
    ))
    if snapshot is None:
        raise SessionPeriodRejected("M03_DAY2_ROUTE_MISSING")
    zone = await db.scalar(select(Zone).where(
        Zone.company_id == company_id, Zone.id == snapshot.zone_id,
    ).with_for_update())
    route = await db.scalar(
        select(DispatchRoute).where(
            DispatchRoute.company_id == company_id,
            DispatchRoute.id == last.route_id,
        ).execution_options(populate_existing=True).with_for_update()
    )
    if (
        zone is None or not zone.is_active or route is None
        or route.zone_id != zone.id
        or route.status != "active"
        or int(route.assignment_context_revision) != int(last.context_revision)
        or route.dispatch_date > previous.session_date
        or route.dispatch_date > company_local_date
    ):
        raise SessionPeriodRejected("M03_DAY2_ROUTE_CHANGED_OR_NOT_ACTIVE")

    # Read under Route lock: manager changes are serialized, not inferred.
    locked_last = await db.scalar(
        select(DispatchRouteExecutionPeriod).where(
            DispatchRouteExecutionPeriod.company_id == company_id,
            DispatchRouteExecutionPeriod.id == last.id,
        ).execution_options(populate_existing=True).with_for_update()
    )
    if (
        locked_last is None or locked_last.state != "CLOSED"
        or locked_last.reason != "WORK_SESSION_ENDED"
        or locked_last.ended_at != previous.end_time
        or locked_last.work_session_id != previous.id
        or locked_last.context_revision != route.assignment_context_revision
    ):
        raise SessionPeriodRejected("M03_DAY2_PERIOD_CHANGED")

    # Never borrow an M02 period/vehicle with another active assignment.
    live = await db.scalar(select(DispatchRouteExecutionPeriod.id).where(
        DispatchRouteExecutionPeriod.company_id == company_id,
        DispatchRouteExecutionPeriod.ended_at.is_(None),
        DispatchRouteExecutionPeriod.state.in_(("PLANNED", "ACTIVE")),
        or_(
            DispatchRouteExecutionPeriod.route_id == route.id,
            DispatchRouteExecutionPeriod.driver_id == driver_id,
            DispatchRouteExecutionPeriod.vehicle_id == last.vehicle_id,
        ),
    ).order_by(DispatchRouteExecutionPeriod.id.asc()).limit(1))
    if live is not None:
        raise SessionPeriodRejected("M03_DAY2_LIVE_ASSIGNMENT_CONFLICT")

    location = await db.scalar(select(InventoryLocation.id).where(
        InventoryLocation.company_id == company_id,
        InventoryLocation.id == last.vehicle_location_id,
        InventoryLocation.vehicle_id == last.vehicle_id,
        InventoryLocation.location_type == "VEHICLE",
        InventoryLocation.is_active.is_(True),
    ))
    if location is None:
        raise SessionPeriodRejected("M03_DAY2_VEHICLE_LOCATION_INVALID")

    commercial = await db.scalar(select(RouteCommercialContext.id).where(
        RouteCommercialContext.company_id == company_id,
        RouteCommercialContext.id == last.commercial_context_id,
        RouteCommercialContext.dispatch_route_id == route.id,
    ))
    if commercial is None:
        raise SessionPeriodRejected("M03_DAY2_COMMERCIAL_CONTEXT_STALE")
    custody = await _current_custody(
        db, company_id=company_id, vehicle_id=last.vehicle_id,
        vehicle_location_id=last.vehicle_location_id,
        field_representative_id=int(field_context.representative_id),
        principal_id=int(field_context.principal_id), for_update=True,
    )
    if custody.id <= 0:
        raise SessionPeriodRejected("M03_DAY2_CUSTODY_INVALID")

    next_revision = int(route.assignment_context_revision) + 1
    signed_request = str(uuid5(
        NAMESPACE_URL, f"M03_DAY2:{company_id}:{driver_id}:{request_id.strip()}"
    ))
    immutable = {
        "company_id": company_id, "driver_id": driver_id,
        "previous_session_id": previous.id,
        "previous_period_id": last.id,
        "route_id": route.id, "context_revision": next_revision,
        "vehicle_id": last.vehicle_id,
        "vehicle_location_id": last.vehicle_location_id,
        "commercial_context_id": last.commercial_context_id,
        "custody_epoch_id": custody.id,
        "field_representative_id": field_context.representative_id,
        "principal_id": field_context.principal_id,
        "company_local_date": company_local_date.isoformat(),
    }
    payload_hash = hashlib.sha256(json.dumps(
        immutable, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()

    period = DispatchRouteExecutionPeriod(
        company_id=company_id, route_id=route.id, work_session_id=None,
        driver_id=driver_id,
        field_representative_id=int(field_context.representative_id),
        vehicle_id=int(last.vehicle_id),
        vehicle_location_id=int(last.vehicle_location_id),
        commercial_context_id=int(last.commercial_context_id),
        state="PLANNED", context_revision=next_revision,
        started_at=utc_now(),
        started_by_principal_id=int(field_context.principal_id),
        reason="FIELD_NEXT_DAY_CONTINUATION",
        request_id=signed_request, payload_hash=payload_hash,
    )
    db.add(period)
    route.assignment_context_revision = next_revision
    await db.flush()  # DB partial unique indexes + tenant FKs + rev CAS.
    return True
