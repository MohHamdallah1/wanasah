"""M02 sorted legacy row locks for the future M01 period/custody adapter.

Read-only locking seam: route.*, session.*, Driver and Vehicle here are only
existing physical/operational references. They do NOT authorize FIELD commands
or replace tenant-scoped M01 period/custodian checks. Only one transaction may
hold these objects while it validates and mutates an execution period.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import DispatchRoute, Driver, Vehicle, WorkSession, Zone
from domains.dispatch_representatives import has_canonical_field_identity

from .policy import LifecycleConflict


@dataclass(frozen=True, slots=True)
class LockedRouteResources:
    route: DispatchRoute
    zone: Zone
    session: WorkSession | None
    target_session: WorkSession | None
    sessions: Mapping[int, WorkSession]
    drivers: Mapping[int, Driver]
    vehicles: Mapping[int, Vehicle]
    canonical_field_driver_ids: frozenset[int]


def _snapshot_identity(route: DispatchRoute) -> tuple:
    """Pre-read drives lock order, NOT an authorization or business decision."""
    return (
        route.driver_id, route.vehicle_id, route.zone_id,
        route.work_session_id, route.status, route.assignment_context_revision,
    )


async def lock_route_resources(
    db: AsyncSession, *, company_id: int, route_id: int,
    target_driver_id: int | None, target_vehicle_id: int | None,
    additional_session_ids: tuple[int, ...] = (),
) -> LockedRouteResources:
    """Existing M00 lock order: session -> sorted drivers -> vehicles -> zone -> route.

    Every query is scoped to company, and a changing pre-read is 409 rather
    than guessing a new route/session/vehicle. The new M01 live-period/custody
    locks and context CAS remain mandatory in the composing store.
    """
    snapshot = await db.scalar(
        select(DispatchRoute).where(
            DispatchRoute.company_id == company_id,
            DispatchRoute.id == route_id,
        ).execution_options(populate_existing=True)
    )
    if snapshot is None:
        raise LifecycleConflict("ROUTE_NOT_FOUND")
    original = _snapshot_identity(snapshot)
    # Include the destination representative's *current* session in the
    # sorted pre-driver lock set. No session on the target is a valid planned
    # assignment, not an invented financial day for that representative.
    target_session_id = None
    if target_driver_id is not None:
        target_session_id = await db.scalar(
            select(WorkSession.id).where(
                WorkSession.company_id == company_id,
                WorkSession.driver_id == target_driver_id,
                WorkSession.end_time.is_(None),
            ).order_by(WorkSession.id.asc()).limit(1)
        )
    ids = sorted({
        int(session_id)
        for session_id in (snapshot.work_session_id, target_session_id, *additional_session_ids)
        if session_id is not None
    })
    session_rows = (
        (await db.execute(
            select(WorkSession).where(
                WorkSession.company_id == company_id,
                WorkSession.id.in_(ids),
            ).order_by(WorkSession.id.asc()).with_for_update()
        )).scalars().all()
        if ids else []
    )
    sessions = {int(session.id): session for session in session_rows}
    if len(sessions) != len(ids):
        raise LifecycleConflict("ROUTE_SESSION_CHANGED_CONCURRENTLY")
    session = sessions.get(int(snapshot.work_session_id)) if snapshot.work_session_id else None
    target_session = sessions.get(int(target_session_id)) if target_session_id else None
    if target_session is not None and (
        target_session.driver_id != target_driver_id
        or target_session.end_time is not None
    ):
        raise LifecycleConflict("TARGET_SESSION_CHANGED_CONCURRENTLY")

    driver_ids = sorted({
        int(driver_id)
        for driver_id in (snapshot.driver_id, target_driver_id)
        if driver_id is not None
    })
    drivers = {}
    field_ids: set[int] = set()
    if driver_ids:
        result = await db.execute(
            select(
                Driver,
                has_canonical_field_identity(
                    company_id=company_id, legacy_driver_id=Driver.id,
                ),
            ).where(
                Driver.company_id == company_id,
                Driver.id.in_(driver_ids),
            ).order_by(Driver.id.asc()).with_for_update()
        )
        for driver, has_field_identity in result.all():
            drivers[int(driver.id)] = driver
            if has_field_identity:
                field_ids.add(int(driver.id))

    vehicle_ids = sorted({
        int(vehicle_id)
        for vehicle_id in (snapshot.vehicle_id, target_vehicle_id)
        if vehicle_id is not None
    })
    vehicles: dict[int, Vehicle] = {}
    if vehicle_ids:
        rows = (
            await db.execute(
                select(Vehicle).where(
                    Vehicle.company_id == company_id,
                    Vehicle.id.in_(vehicle_ids),
                ).order_by(Vehicle.id.asc()).with_for_update()
            )
        ).scalars().all()
        vehicles = {int(vehicle.id): vehicle for vehicle in rows}

    zone = await db.scalar(
        select(Zone).where(
            Zone.company_id == company_id,
            Zone.id == int(snapshot.zone_id),
        ).order_by(Zone.id.asc()).with_for_update()
    )
    if zone is None:
        raise LifecycleConflict("ROUTE_ZONE_MISSING")

    route = await db.scalar(
        select(DispatchRoute).where(
            DispatchRoute.company_id == company_id,
            DispatchRoute.id == route_id,
        ).order_by(DispatchRoute.id.asc())
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if route is None:
        raise LifecycleConflict("ROUTE_NOT_FOUND")
    if _snapshot_identity(route) != original:
        raise LifecycleConflict("ROUTE_CHANGED_CONCURRENTLY")
    if target_driver_id is not None and target_driver_id not in drivers:
        raise LifecycleConflict("TARGET_DRIVER_NOT_IN_COMPANY")
    if target_vehicle_id is not None and target_vehicle_id not in vehicles:
        raise LifecycleConflict("TARGET_VEHICLE_NOT_IN_COMPANY")

    return LockedRouteResources(
        route=route, zone=zone, session=session, target_session=target_session,
        sessions=sessions, drivers=drivers, vehicles=vehicles,
        canonical_field_driver_ids=frozenset(field_ids),
    )
