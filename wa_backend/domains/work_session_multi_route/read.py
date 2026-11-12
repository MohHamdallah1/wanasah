"""Read-side active route projection for session and pre-start FIELD views."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import DispatchRoute, WorkSession
from domains.auth_sessions.context import FieldRequestContext
from domains.work_session_multi_route.context import (
    ResolvedExecution, find_planned_period, resolve_active_execution,
)
from services import get_company_local_date


async def read_current_execution(
    db: AsyncSession,
    *,
    field_context: FieldRequestContext,
    driver_id: int,
    active_session: Optional[WorkSession],
) -> Optional[ResolvedExecution]:
    company_id = int(field_context.company_id)
    if active_session is not None:
        return await resolve_active_execution(
            db,
            company_id=company_id,
            driver_id=driver_id,
            session_id=int(active_session.id),
            field_representative_id=int(field_context.representative_id),
            principal_id=int(field_context.principal_id),
            require_active=False,
        )

    planned = await find_planned_period(
        db,
        company_id=company_id,
        driver_id=driver_id,
        field_representative_id=int(field_context.representative_id),
        principal_id=int(field_context.principal_id),
    )
    if planned is not None:
        return planned

    # Legacy V1 compatibility before an M02 canonical period has been written.
    today = await get_company_local_date(db, company_id)
    query = (
        select(DispatchRoute)
        .where(
            DispatchRoute.company_id == company_id,
            DispatchRoute.driver_id == driver_id,
            DispatchRoute.dispatch_date == today,
            DispatchRoute.assignment_context_revision == 1,
            DispatchRoute.status.in_(("active", "waiting", "postponed")),
        )
        .order_by(DispatchRoute.id.asc()).limit(2)
    )
    rows = (await db.execute(query)).scalars().all()
    if len(rows) != 1:
        return None
    return ResolvedExecution(
        route=rows[0],
        period=None,
        custody_epoch=None,
        commercial_context_id=None,
        vehicle_location_id=None,
    )
