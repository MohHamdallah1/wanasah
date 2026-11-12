"""M05 bounded scoped current route-period projection (read-only).

Historic DispatchRoute.driver_id/vehicle_id/work_session_id are never current
execution authority. The M01 unique live-route index remains the primary guard;
a corrupt duplicate must not be arbitrarily chosen by the UI.
"""
from __future__ import annotations

from sqlalchemy import and_, select
from dispatch_access import vehicle_filter

from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod

MAX_M05_ROUTE_READ = 1024


class RoutePeriodReadConflict(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


async def read_current_route_periods(db, *, access, route_ids: list[int]) -> dict[int, dict]:
    if not route_ids:
        return {}
    if len(route_ids) > MAX_M05_ROUTE_READ or len(set(route_ids)) != len(route_ids):
        raise RoutePeriodReadConflict("M05_ROUTE_READ_WINDOW_INVALID")
    period = DispatchRouteExecutionPeriod
    # One tenant/route-bounded query, no route-by-route SQL and no N+1;
    # dynamic read/execute permissions are evaluated by PostgreSQL itself.
    rows = (await db.execute(
        select(
            period,
            and_(
                access.allows("dispatch.read", period.vehicle_location_id),
                vehicle_filter(access, "dispatch.read", period.vehicle_id),
            ).label("may_read"),
            and_(
                access.allows("dispatch.execute", period.vehicle_location_id),
                vehicle_filter(access, "dispatch.execute", period.vehicle_id),
            ).label("may_execute"),
        ).where(
            period.company_id == access.company_id,
            period.route_id.in_(route_ids),
            period.ended_at.is_(None),
            period.state.in_(("PLANNED", "ACTIVE")),
            period.evidence_origin == "CANONICAL",
        ).order_by(period.route_id, period.id).limit(MAX_M05_ROUTE_READ + 1)
    )).all()
    if len(rows) > MAX_M05_ROUTE_READ:
        raise RoutePeriodReadConflict("M05_ROUTE_PERIOD_AMBIGUOUS")
    projected: dict[int, dict] = {}
    for record, may_read, may_execute in rows:
        if record.route_id in projected:
            raise RoutePeriodReadConflict("M05_ROUTE_PERIOD_AMBIGUOUS")
        if record.vehicle_location_id is None or record.context_revision is None:
            raise RoutePeriodReadConflict("M05_ROUTE_PERIOD_INCOMPLETE")
        # Never return IDs for a vehicle location outside current access; the
        # legacy route's visible source/previous car cannot grant new access.
        projected[int(record.route_id)] = {
            "id": int(record.id) if may_read else None,
            "driver_id": int(record.driver_id) if may_read else None,
            "vehicle_id": int(record.vehicle_id) if may_read else None,
            "location_id": int(record.vehicle_location_id) if may_read else None,
            "revision": int(record.context_revision),
            "state": str(record.state) if may_read else None,
            "session_id": int(record.work_session_id) if may_read and record.work_session_id else None,
            "may_read": bool(may_read),
            "may_execute": bool(may_execute and may_read),
        }
    return projected
