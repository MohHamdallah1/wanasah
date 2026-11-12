"""Company-scoped zone vs live-resource admission across legacy and M01 writers.

Call only AFTER locking the same destination Driver+Vehicle+Zone rows as route
launch/M02 lifecycle. PostgreSQL enforces uniqueness *inside each* live
representation; these cross-table checks close the interop gap atomically.
"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import DispatchRoute
from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod

from .policy import LifecycleConflict


async def assert_route_resources_available(
    db: AsyncSession, *, company_id: int, zone_id: int,
    driver_id: int, vehicle_id: int, exclude_route_id: int | None = None,
) -> None:
    """Zone is reserved by postponed; driver and vehicle are never reserved by it."""
    route_clauses = [
        DispatchRoute.company_id == company_id,
        DispatchRoute.status.in_(("active", "waiting", "postponed")),
    ]
    if exclude_route_id is not None:
        route_clauses.append(DispatchRoute.id != exclude_route_id)
    zone = await db.scalar(
        select(DispatchRoute.id).where(
            *route_clauses,
            DispatchRoute.zone_id == zone_id,
        ).limit(1)
    )
    if zone is not None:
        raise LifecycleConflict("ZONE_RESERVED_BY_OTHER_ROUTE")

    # Only unconverted live route rows derive operational resources from the
    # old mutable route columns. Canonical periods are separate authority.
    legacy_clauses = [
        DispatchRoute.company_id == company_id,
        DispatchRoute.status.in_(("active", "waiting")),
        DispatchRoute.assignment_context_revision == 1,
        or_(DispatchRoute.driver_id == driver_id,
            DispatchRoute.vehicle_id == vehicle_id),
    ]
    if exclude_route_id is not None:
        legacy_clauses.append(DispatchRoute.id != exclude_route_id)
    legacy = await db.scalar(
        select(DispatchRoute.id).where(*legacy_clauses).limit(1)
    )
    if legacy is not None:
        raise LifecycleConflict("LIVE_LEGACY_RESOURCE_CONFLICT")

    canonical_clauses = [
        DispatchRouteExecutionPeriod.company_id == company_id,
        DispatchRouteExecutionPeriod.ended_at.is_(None),
        DispatchRouteExecutionPeriod.state.in_(("PLANNED", "ACTIVE")),
        or_(DispatchRouteExecutionPeriod.driver_id == driver_id,
            DispatchRouteExecutionPeriod.vehicle_id == vehicle_id),
    ]
    if exclude_route_id is not None:
        canonical_clauses.append(
            DispatchRouteExecutionPeriod.route_id != exclude_route_id
        )
    canonical = await db.scalar(
        select(DispatchRouteExecutionPeriod.id).where(
            *canonical_clauses
        ).limit(1)
    )
    if canonical is not None:
        raise LifecycleConflict("LIVE_PERIOD_RESOURCE_CONFLICT")


async def assert_current_signed_vehicle_responsibility(
    db: AsyncSession, *, company_id: int, driver_id: int,
    vehicle_id: int, vehicle_location_id: int,
) -> bool:
    """True iff M01 current accepted FIELD custodian exactly matches driver.

    Return False (safe legacy fallback) for unassigned vehicles. A mismatching
    current ACCEPTED epoch is a 409; NEEDS_REVIEW is never implicit acceptance.
    """
    from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
    from domains.identity.migration.models import IdentityLegacyDriverMap
    row = await db.scalar(select(IdentityLegacyDriverMap).where(
        IdentityLegacyDriverMap.company_id == company_id,
        IdentityLegacyDriverMap.legacy_driver_id == driver_id,
    ))
    if row is None or row.field_representative_id is None or row.field_principal_id is None:
        raise LifecycleConflict("TARGET_FIELD_IDENTITY_UNVERIFIED")

    current = await db.scalar(select(VehicleCustodyEpoch).where(
        VehicleCustodyEpoch.company_id == company_id,
        VehicleCustodyEpoch.vehicle_id == vehicle_id,
        VehicleCustodyEpoch.ended_at.is_(None),
    ).with_for_update())
    if current is None:
        return False
    if (
        current.state != "ACCEPTED"
        or current.custodian_kind != "FIELD_REPRESENTATIVE"
        or current.vehicle_location_id != vehicle_location_id
        or current.field_representative_id != row.field_representative_id
        or current.custodian_principal_id != row.field_principal_id
        or current.accepted_by_principal_id is None
        or not current.request_id
        or not current.payload_hash
    ):
        raise LifecycleConflict("VEHICLE_CURRENT_CUSTODIAN_NOT_ACCEPTED")
    return True
