"""Field session -> execution-period authority (M03).

Read/validate M02's canonical period; never infer assignment from a prior
DispatchRoute.work_session_id or reuse an accepted Vehicle custody epoch
after an A -> B -> A switch. M01 historical records grant no live authority.

No InventoryBalance, stock, finance or historical visit is ever mutated here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import DispatchRoute
from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch


class SessionPeriodRejected(Exception):
    def __init__(self, code: str, *, status_code: int = 409):
        self.code = code
        self.status_code = status_code
        super().__init__(code)

    def as_detail(self) -> dict:
        return {"code": self.code, "message": self.code, "context": {}}


@dataclass(frozen=True)
class PeriodProof:
    """Header-carried offline envelope; never treat a client proof as authority."""
    period_id: Optional[int] = None
    assignment_revision: Optional[int] = None
    custody_epoch_id: Optional[int] = None

    @property
    def complete(self) -> bool:
        return all(
            isinstance(value, int) and not isinstance(value, bool) and value > 0
            for value in (self.period_id, self.assignment_revision, self.custody_epoch_id)
        )

    def matches(self, authority: "ResolvedExecution") -> bool:
        return (
            authority.period is not None
            and authority.custody_epoch is not None
            and self.period_id == authority.period.id
            and self.assignment_revision == authority.route.assignment_context_revision
            and self.assignment_revision == authority.period.context_revision
            and self.custody_epoch_id == authority.custody_epoch.id
        )


@dataclass(frozen=True)
class ResolvedExecution:
    route: DispatchRoute
    period: Optional[DispatchRouteExecutionPeriod]
    custody_epoch: Optional[VehicleCustodyEpoch]
    commercial_context_id: Optional[int]
    vehicle_location_id: Optional[int]

    @property
    def canonical(self) -> bool:
        return self.period is not None


async def _current_custody(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
    vehicle_location_id: int,
    field_representative_id: int,
    principal_id: int,
    for_update: bool,
) -> VehicleCustodyEpoch:
    query = (
        select(VehicleCustodyEpoch)
        .where(
            VehicleCustodyEpoch.company_id == company_id,
            VehicleCustodyEpoch.vehicle_id == vehicle_id,
            VehicleCustodyEpoch.vehicle_location_id == vehicle_location_id,
            VehicleCustodyEpoch.custodian_kind == "FIELD_REPRESENTATIVE",
            VehicleCustodyEpoch.custodian_principal_id == principal_id,
            VehicleCustodyEpoch.field_representative_id == field_representative_id,
            VehicleCustodyEpoch.state == "ACCEPTED",
            VehicleCustodyEpoch.ended_at.is_(None),
        )
        .order_by(VehicleCustodyEpoch.id.asc()).limit(2)
    )
    if for_update:
        query = query.with_for_update()
    epochs = (await db.execute(query)).scalars().all()
    if len(epochs) != 1:
        raise SessionPeriodRejected("M03_VEHICLE_CUSTODY_REQUIRED")
    return epochs[0]


async def resolve_active_execution(
    db: AsyncSession,
    *,
    company_id: int,
    driver_id: int,
    session_id: int,
    field_representative_id: int,
    principal_id: int,
    proof: Optional[PeriodProof] = None,
    for_update: bool = False,
    require_active: bool = True,
) -> Optional[ResolvedExecution]:
    """Resolve period and exact custody; optional read returns None on no work.

    When ANY canonical periods exist for this session, a legacy route cannot
    accidentally regain authority, including during postponed/no-active gaps.
    """
    if min(company_id, driver_id, session_id, field_representative_id, principal_id) <= 0:
        raise SessionPeriodRejected("M03_INVALID_CONTEXT", status_code=403)

    query = (
        select(DispatchRouteExecutionPeriod)
        .where(
            DispatchRouteExecutionPeriod.company_id == company_id,
            DispatchRouteExecutionPeriod.driver_id == driver_id,
            DispatchRouteExecutionPeriod.work_session_id == session_id,
            DispatchRouteExecutionPeriod.state == "ACTIVE",
            DispatchRouteExecutionPeriod.ended_at.is_(None),
            DispatchRouteExecutionPeriod.evidence_origin == "CANONICAL",
        )
        .order_by(DispatchRouteExecutionPeriod.id.asc()).limit(2)
    )
    # Read the candidate without a row lock, then acquire the Route lock
    # BEFORE the period lock: M02 locks Route -> period on transition.
    # The WorkSession is already FOR UPDATE in the mutation caller.
    active_periods = (await db.execute(query)).scalars().all()
    if len(active_periods) > 1:
        raise SessionPeriodRejected("M03_MULTIPLE_ACTIVE_PERIODS")

    if active_periods:
        period = active_periods[0]
        if (
            period.field_representative_id != field_representative_id
            or period.vehicle_location_id is None
            or period.commercial_context_id is None
            or period.context_revision is None
        ):
            raise SessionPeriodRejected("M03_PERIOD_EVIDENCE_INVALID")
        route_query = (
            select(DispatchRoute)
            .where(
                DispatchRoute.company_id == company_id,
                DispatchRoute.id == period.route_id,
            )
        )
        if for_update:
            route_query = route_query.with_for_update()
        route = (await db.execute(route_query)).scalar_one_or_none()
        if for_update:
            # Exact identity must still be ACTIVE after the route lock.
            locked_period = (
                await db.execute(
                    select(DispatchRouteExecutionPeriod).where(
                        DispatchRouteExecutionPeriod.company_id == company_id,
                        DispatchRouteExecutionPeriod.id == period.id,
                    ).with_for_update()
                )
            ).scalar_one_or_none()
            if (
                locked_period is None
                or locked_period.state != "ACTIVE"
                or locked_period.ended_at is not None
                or locked_period.driver_id != driver_id
                or locked_period.work_session_id != session_id
            ):
                raise SessionPeriodRejected("M03_STALE_EXECUTION_CONTEXT")
            period = locked_period
        if (
            route is None or route.status != "active"
            or int(route.assignment_context_revision) != int(period.context_revision)
        ):
            raise SessionPeriodRejected("M03_STALE_ROUTE_ASSIGNMENT")
        epoch = await _current_custody(
            db, company_id=company_id,
            vehicle_id=int(period.vehicle_id),
            vehicle_location_id=int(period.vehicle_location_id),
            field_representative_id=field_representative_id,
            principal_id=principal_id,
            for_update=for_update,
        )
        authority = ResolvedExecution(
            route=route,
            period=period,
            custody_epoch=epoch,
            commercial_context_id=int(period.commercial_context_id),
            vehicle_location_id=int(period.vehicle_location_id),
        )
        if proof is not None and (not proof.complete or not proof.matches(authority)):
            raise SessionPeriodRejected("M03_STALE_EXECUTION_CONTEXT")
        return authority

    # For any canonical history of this session, never fall back to old
    # DispatchRoute.work_session_id when a period was postponed or closed.
    has_canonical_history = (
        await db.execute(
            select(DispatchRouteExecutionPeriod.id)
            .where(
                DispatchRouteExecutionPeriod.company_id == company_id,
                DispatchRouteExecutionPeriod.driver_id == driver_id,
                DispatchRouteExecutionPeriod.work_session_id == session_id,
                DispatchRouteExecutionPeriod.evidence_origin == "CANONICAL",
            ).limit(1)
        )
    ).scalar_one_or_none() is not None
    if has_canonical_history or proof is not None:
        if require_active:
            raise SessionPeriodRejected("M03_NO_ACTIVE_EXECUTION_PERIOD")
        return None

    # Frozen single-route V1 compatibility only: revision 1, same bound
    # session+driver, and ACTIVE. No assertion from historical M01 rows.
    legacy_query = (
        select(DispatchRoute)
        .where(
            DispatchRoute.company_id == company_id,
            DispatchRoute.driver_id == driver_id,
            DispatchRoute.work_session_id == session_id,
            DispatchRoute.status == "active",
            DispatchRoute.assignment_context_revision == 1,
        ).order_by(DispatchRoute.id.asc()).limit(2)
    )
    if for_update:
        legacy_query = legacy_query.with_for_update()
    routes = (await db.execute(legacy_query)).scalars().all()
    if len(routes) > 1:
        raise SessionPeriodRejected("M03_LEGACY_ROUTE_AMBIGUOUS")
    if routes and routes[0].vehicle_id is not None:
        return ResolvedExecution(
            route=routes[0],
            period=None,
            custody_epoch=None,
            commercial_context_id=None,
            vehicle_location_id=None,
        )
    if require_active:
        raise SessionPeriodRejected("M03_NO_ACTIVE_EXECUTION_PERIOD")
    return None


async def find_planned_period(
    db: AsyncSession,
    *,
    company_id: int,
    driver_id: int,
    field_representative_id: int,
    principal_id: int,
    for_update: bool = False,
) -> Optional[ResolvedExecution]:
    """M02-planned, unbound work may be attached to today's ONE session.

    No old-session reassignment and no extra stock movement. Returned authority
    is never active until the caller binds WorkSession and updates period state
    in the same transaction.
    """
    stmt = (
        select(DispatchRouteExecutionPeriod)
        .where(
            DispatchRouteExecutionPeriod.company_id == company_id,
            DispatchRouteExecutionPeriod.driver_id == driver_id,
            DispatchRouteExecutionPeriod.field_representative_id == field_representative_id,
            DispatchRouteExecutionPeriod.work_session_id.is_(None),
            DispatchRouteExecutionPeriod.state == "PLANNED",
            DispatchRouteExecutionPeriod.ended_at.is_(None),
            DispatchRouteExecutionPeriod.evidence_origin == "CANONICAL",
        ).order_by(DispatchRouteExecutionPeriod.id.asc()).limit(2)
    )
    # M02 lifecycle lock ordering is Route -> Period. Do not invert it.
    periods = (await db.execute(stmt)).scalars().all()
    if not periods:
        return None
    if len(periods) != 1:
        raise SessionPeriodRejected("M03_AMBIGUOUS_PLANNED_PERIOD")
    period = periods[0]
    route_stmt = select(DispatchRoute).where(
        DispatchRoute.company_id == company_id,
        DispatchRoute.id == period.route_id,
    )
    if for_update:
        route_stmt = route_stmt.with_for_update()
    route = (await db.execute(route_stmt)).scalar_one_or_none()
    if for_update:
        locked_period = (
            await db.execute(
                select(DispatchRouteExecutionPeriod).where(
                    DispatchRouteExecutionPeriod.company_id == company_id,
                    DispatchRouteExecutionPeriod.id == period.id,
                ).with_for_update()
            )
        ).scalar_one_or_none()
        if (
            locked_period is None or locked_period.state != "PLANNED"
            or locked_period.ended_at is not None
            or locked_period.work_session_id is not None
            or locked_period.driver_id != driver_id
            or locked_period.field_representative_id != field_representative_id
        ):
            raise SessionPeriodRejected("M03_PLANNED_PERIOD_STALE")
        period = locked_period
    if (
        route is None or route.status not in ("waiting", "active")
        or int(route.assignment_context_revision) != int(period.context_revision)
        or period.vehicle_location_id is None
        or period.commercial_context_id is None
    ):
        raise SessionPeriodRejected("M03_PLANNED_PERIOD_STALE")
    epoch = await _current_custody(
        db, company_id=company_id,
        vehicle_id=int(period.vehicle_id),
        vehicle_location_id=int(period.vehicle_location_id),
        field_representative_id=field_representative_id,
        principal_id=principal_id,
        for_update=for_update,
    )
    return ResolvedExecution(
        route=route,
        period=period,
        custody_epoch=epoch,
        commercial_context_id=int(period.commercial_context_id),
        vehicle_location_id=int(period.vehicle_location_id),
    )


def execution_envelope(execution: Optional[ResolvedExecution]) -> Optional[dict]:
    """Public FIELD-context proof to persist with an offline command draft."""
    if execution is None or not execution.canonical:
        return None
    return {
        "session_id": int(execution.period.work_session_id) if execution.period.work_session_id else None,
        "period_id": int(execution.period.id),
        "route_id": int(execution.period.route_id),
        "vehicle_id": int(execution.period.vehicle_id),
        "vehicle_location_id": int(execution.vehicle_location_id),
        "commercial_context_id": int(execution.commercial_context_id),
        "assignment_context_revision": int(execution.period.context_revision),
        "custody_epoch_id": int(execution.custody_epoch.id),
    }
