"""M03 FIELD end-of-day freeze: close only signed *daily* periods.

The caller holds the exact live WorkSession FOR UPDATE after the existing
break/handshake guards. M02 acquires session -> route -> period -> custody:
the same route/period/epoch order is respected by resolve_active_execution.
No route status, zone scheduling, assignment, stock or money writes here.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
from domains.work_session_multi_route.context import (
    SessionPeriodRejected, resolve_active_execution,
)


async def freeze_end_of_day_execution(
    db: AsyncSession, *, company_id: int, session_id: int, driver_id: int,
    field_representative_id: int, principal_id: int, ended_at: datetime,
) -> None:
    """Freeze the last ACTIVE signed S1 period or preserve historical V1.

    Never close/reassign the DispatchRoute. A canonical session with no live
    period is valid only when ALL its periods were already legitimately
    closed by an explicit M02 lifecycle transition.
    """
    prior = await db.scalar(
        select(DispatchRouteExecutionPeriod.id).where(
            DispatchRouteExecutionPeriod.company_id == company_id,
            DispatchRouteExecutionPeriod.work_session_id == session_id,
            DispatchRouteExecutionPeriod.evidence_origin == "CANONICAL",
        ).order_by(DispatchRouteExecutionPeriod.id.asc()).limit(1)
    )
    if prior is None:
        return  # Historical single-route V1; preserve previous End Work.

    current = await resolve_active_execution(
        db, company_id=company_id, driver_id=driver_id,
        session_id=session_id, field_representative_id=field_representative_id,
        principal_id=principal_id, require_active=False, for_update=True,
    )
    if current is not None:
        if not current.canonical or current.period is None:
            raise SessionPeriodRejected("M03_DAY_END_PERIOD_IDENTITY_INVALID")
        # An ACTIVE period is independently revalidated under the locked
        # route / period / accepted epoch before it can be signed closed.
        period = current.period
        if (
            period.started_at is None or period.ended_at is not None
            or ended_at < period.started_at
            or period.started_by_principal_id is None
            or not period.request_id or not period.payload_hash
        ):
            raise SessionPeriodRejected("M03_DAY_END_PERIOD_EVIDENCE_INVALID")
        period.state = "CLOSED"
        period.ended_at = ended_at
        period.ended_by_principal_id = principal_id
        period.reason = "WORK_SESSION_ENDED"

    # No incomplete canonical period may outlive a closed WorkSession.
    # The transaction auto-flushes the freshly closed period for this
    # DB-scoped guard, and rolls back BOTH states on any conflict.
    incomplete = await db.scalar(
        select(DispatchRouteExecutionPeriod.id).where(
            DispatchRouteExecutionPeriod.company_id == company_id,
            DispatchRouteExecutionPeriod.work_session_id == session_id,
            DispatchRouteExecutionPeriod.evidence_origin == "CANONICAL",
            or_(
                DispatchRouteExecutionPeriod.state != "CLOSED",
                DispatchRouteExecutionPeriod.ended_at.is_(None),
            ),
        ).order_by(DispatchRouteExecutionPeriod.id.asc()).limit(1)
    )
    if incomplete is not None:
        raise SessionPeriodRejected("M03_DAY_END_INCOMPLETE_PERIODS")
