"""Bounded session-period/epoch reads over M01 canonical persistence.

There is deliberately no DispatchRoute.work_session_id fallback here. Unknown
historical links require review instead of guessing the last vehicle.
"""
from sqlalchemy import select

from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from models import InventoryLocation, WorkSession

from .contracts import (
    MAX_EPOCHS, MAX_PERIODS, CustodyRejected, EpochEvidence, PeriodEvidence,
)
from .policy import resolve_responsibilities


async def session_responsibilities(db, *, company_id: int, session_id: int,
                                   lock: bool = False, lock_session: bool = False):
    work_query = select(WorkSession).where(
        WorkSession.company_id == company_id, WorkSession.id == session_id,
    ).execution_options(populate_existing=True)
    if lock or lock_session:
        work_query = work_query.with_for_update()
    work = (await db.execute(work_query)).scalar_one_or_none()
    if work is None:
        raise CustodyRejected("SETTLEMENT_SESSION_NOT_FOUND", status=404)
    if work.end_time is None:
        raise CustodyRejected("WORK_SESSION_NOT_ENDED")
    periods = (await db.scalars(select(DispatchRouteExecutionPeriod).where(
        DispatchRouteExecutionPeriod.company_id == company_id,
        DispatchRouteExecutionPeriod.work_session_id == session_id,
    ).order_by(DispatchRouteExecutionPeriod.id).limit(MAX_PERIODS + 1))).all()
    epoch_query = select(VehicleCustodyEpoch).where(
        VehicleCustodyEpoch.company_id == company_id,
        VehicleCustodyEpoch.related_session_id == session_id,
    ).order_by(VehicleCustodyEpoch.vehicle_id, VehicleCustodyEpoch.id).limit(MAX_EPOCHS + 1)
    if lock:
        epoch_query = epoch_query.with_for_update()
    epochs = (await db.scalars(epoch_query)).all()
    period_evidence = tuple(PeriodEvidence(
        p.id, p.company_id, p.work_session_id, p.driver_id, p.field_representative_id,
        p.vehicle_id, p.vehicle_location_id, p.context_revision, p.state,
        p.started_at, p.ended_at,
        p.evidence_origin == "CANONICAL" and bool(p.request_id and p.payload_hash
                                                  and p.started_by_principal_id),
    ) for p in periods)
    epoch_evidence = tuple(EpochEvidence(
        e.id, e.company_id, e.related_session_id, e.field_representative_id,
        e.vehicle_id, e.vehicle_location_id, e.context_revision, e.state,
        e.started_at, e.ended_at, e.accepted_by_principal_id,
        e.evidence_origin == "CANONICAL" and bool(e.request_id and e.payload_hash),
    ) for e in epochs)
    vehicles = resolve_responsibilities(
        company_id=company_id, session_id=session_id, driver_id=work.driver_id,
        periods=period_evidence, epochs=epoch_evidence,
    )
    locations = (await db.execute(select(
        InventoryLocation.id, InventoryLocation.vehicle_id,
    ).where(
        InventoryLocation.company_id == company_id,
        InventoryLocation.id.in_([v.location_id for v in vehicles]),
        InventoryLocation.location_type == "VEHICLE",
        InventoryLocation.is_active.is_(True),
    ))).all()
    if set(locations) != {(v.location_id, v.vehicle_id) for v in vehicles}:
        raise CustodyRejected("VEHICLE_LOCATION_EVIDENCE_AMBIGUOUS")
    return work, vehicles
