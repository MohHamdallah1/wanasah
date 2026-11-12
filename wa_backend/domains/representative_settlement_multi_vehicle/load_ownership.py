"""Canonical custody ownership for the existing standalone Vehicle Load guard.

An ended, unclosed current responsibility cannot be loaded around a signed
count. A later accepted custodian is independent from an older session's cash
closure. This read is rechecked under Vehicle lock by the existing load owner.
"""
from sqlalchemy import and_, or_, select

from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod as Period
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch as Epoch
from models import WorkSession

from .contracts import CustodyRejected


async def canonical_load_context(db, *, company_id, vehicle_id):
    current = select(Epoch).where(
        Epoch.company_id == company_id, Epoch.vehicle_id == vehicle_id, Epoch.ended_at.is_(None),
    ).subquery()
    rows = (await db.execute(select(WorkSession.id, WorkSession.end_time).select_from(Period)
        .join(WorkSession, and_(WorkSession.company_id == Period.company_id,
                               WorkSession.id == Period.work_session_id))
        .outerjoin(current, current.c.vehicle_id == Period.vehicle_id)
        .where(Period.company_id == company_id, Period.vehicle_id == vehicle_id,
               Period.evidence_origin == "CANONICAL", WorkSession.is_settled.is_(False),
               or_(current.c.id.is_(None), current.c.state != "ACCEPTED",
                   current.c.related_session_id == WorkSession.id,
                   and_(current.c.related_session_id.is_(None),
                        current.c.field_representative_id == Period.field_representative_id,
                        current.c.started_at <= Period.started_at)))
        .distinct().order_by(WorkSession.id.desc()).limit(2))).all()
    if not rows:
        unsealed_prior = await db.scalar(select(WorkSession.id).join(Period, and_(
            Period.company_id == WorkSession.company_id, Period.work_session_id == WorkSession.id,
        )).where(Period.company_id == company_id, Period.vehicle_id == vehicle_id,
                 Period.evidence_origin == "CANONICAL", WorkSession.is_settled.is_(False),
                 WorkSession.inventory_reconciled_at.is_(None)).limit(1))
        if unsealed_prior is not None:
            raise CustodyRejected("VEHICLE_CUSTODY_REVIEW_REQUIRED")
        return None
    # Several route periods in ONE day are expected. Never choose the last
    # session when two unresolved current responsibilities remain ambiguous.
    sessions = {r.id for r in rows}
    if len(sessions) != 1:
        raise CustodyRejected("VEHICLE_CUSTODY_REVIEW_REQUIRED")
    ended = rows[0].end_time
    # For an open work day route identity belongs to its one ACTIVE period.
    if ended is None:
        active = (await db.execute(select(Period.route_id).where(
            Period.company_id == company_id, Period.vehicle_id == vehicle_id,
            Period.work_session_id == rows[0].id, Period.state == "ACTIVE", Period.ended_at.is_(None),
        ).limit(2))).scalars().all()
        if len(active) != 1:
            raise CustodyRejected("VEHICLE_CUSTODY_REVIEW_REQUIRED")
        return {"route_id": active[0], "session_id": rows[0].id, "ended": False}
    return {"route_id": None, "session_id": rows[0].id, "ended": True}
