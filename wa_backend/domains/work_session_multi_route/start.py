"""M03 canonical first-period session activation.

Only this boundary creates the daily WorkSession for a M02 PLANNED period.
M02 handles subsequent RESUME periods, and never creates another session.
Physical stock, financial settlement and prior Visit identities are untouched.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    InventoryBalance, InventoryLocation, RouteCommercialContext,
    SessionInventorySnapshot, WorkSession, utc_now,
)
from domains.auth_sessions.context import FieldRequestContext
from domains.work_session_multi_route.context import (
    ResolvedExecution, SessionPeriodRejected, find_planned_period,
)
from quantity import QUANTITY_MAX
from domains.pricing.context import commercial_context_payload
from services import acquire_inventory_location_guard

_STOCK_STATUSES = frozenset((
    "AVAILABLE", "QUARANTINED", "BLOCKED", "RECALLED",
    "DAMAGED", "DISPOSAL_PENDING",
))


async def establish_session_vehicle_opening(
    db: AsyncSession,
    *,
    company_id: int,
    session_id: int,
    vehicle_location_id: int,
) -> None:
    """Record one independent opening per physical location, without stock writes.

    A and B may carry the same variant/status: the canonical unique key now
    includes location_id. Existing historical S1 snapshots remain unchanged.
    """
    existing_locations = (
        await db.execute(
            select(SessionInventorySnapshot.location_id)
            .where(
                SessionInventorySnapshot.company_id == company_id,
                SessionInventorySnapshot.work_session_id == session_id,
                SessionInventorySnapshot.location_id == vehicle_location_id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing_locations is not None:
        return

    balance_rows = (
        await db.execute(
            select(
                InventoryBalance.product_variant_id,
                InventoryBalance.stock_status,
                func.sum(InventoryBalance.on_hand_quantity),
            )
            .where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == vehicle_location_id,
                InventoryBalance.on_hand_quantity > 0,
            )
            .group_by(
                InventoryBalance.product_variant_id,
                InventoryBalance.stock_status,
            )
            .order_by(
                InventoryBalance.product_variant_id.asc(),
                InventoryBalance.stock_status.asc(),
            )
        )
    ).all()
    if not balance_rows:
        return

    for variant_id, stock_status, value in balance_rows:
        qty = Decimal(value or 0)
        if (
            str(stock_status) not in _STOCK_STATUSES
            or qty < 0 or qty > QUANTITY_MAX
            or (stock_status == "AVAILABLE" and qty != qty.to_integral_value())
        ):
            raise SessionPeriodRejected("M03_INVALID_VEHICLE_OPENING")
        db.add(SessionInventorySnapshot(
            company_id=company_id,
            work_session_id=session_id,
            location_id=vehicle_location_id,
            product_variant_id=int(variant_id),
            stock_status=str(stock_status),
            starting_quantity=qty,
        ))
    await db.flush()


async def start_session_from_planned_period(
    db: AsyncSession,
    *,
    field_context: FieldRequestContext,
    driver_id: int,
    company_local_date,
    latitude,
    longitude,
) -> Optional[dict]:
    """Return None only if there is no canonical PLANNED period to activate.

    Caller has already locked its legacy Driver, checked historical
    unsettled session prohibition, and opened optional request-idempotency
    record. This method never commits its transaction.
    """
    authority = await find_planned_period(
        db,
        company_id=field_context.company_id,
        driver_id=driver_id,
        field_representative_id=field_context.representative_id,
        principal_id=field_context.principal_id,
        for_update=True,
    )
    if authority is None:
        return None
    if authority.route.status != "active":
        raise SessionPeriodRejected("M03_ROUTE_NOT_ACTIVE")
    # Concurrent first starts serialize on the Driver lock in the caller and
    # this check; the DB still enforces unique open session per driver.
    existing = (
        await db.execute(
            select(WorkSession.id)
            .where(
                WorkSession.company_id == field_context.company_id,
                WorkSession.driver_id == driver_id,
                WorkSession.session_date == company_local_date,
            ).limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise SessionPeriodRejected("M03_DAILY_WORK_SESSION_EXISTS")
    context_row = (
        await db.execute(
            select(RouteCommercialContext)
            .where(
                RouteCommercialContext.company_id == field_context.company_id,
                RouteCommercialContext.id == authority.commercial_context_id,
                RouteCommercialContext.dispatch_route_id == authority.route.id,
            )
        )
    ).scalar_one_or_none()
    if context_row is None:
        raise SessionPeriodRejected("M03_ROUTE_COMMERCIAL_CONTEXT_INVALID")

    # The opening snapshot and first period binding share one transaction.
    # Fence concurrent physical stock movements before reading either car.
    await acquire_inventory_location_guard(
        db, field_context.company_id, int(authority.vehicle_location_id),
        exclusive=True,
    )
    valid_location = await db.scalar(
        select(InventoryLocation.id).where(
            InventoryLocation.company_id == field_context.company_id,
            InventoryLocation.id == authority.vehicle_location_id,
            InventoryLocation.vehicle_id == authority.period.vehicle_id,
            InventoryLocation.location_type == 'VEHICLE',
            InventoryLocation.is_active.is_(True),
        ).with_for_update(read=True)
    )
    if valid_location is None:
        raise SessionPeriodRejected('M03_VEHICLE_LOCATION_STALE')

    session = WorkSession(
        company_id=field_context.company_id,
        driver_id=driver_id,
        session_date=company_local_date,
        commercial_context_id=context_row.id,  # frozen initial ref, NOT active pricing authority after a switch
        start_time=utc_now(),
        start_latitude=latitude,
        start_longitude=longitude,
        is_authorized_to_sell=False,
    )
    db.add(session)
    await db.flush()

    assert authority.period is not None
    authority.period.work_session_id = session.id
    authority.period.state = "ACTIVE"
    # Never overwrite historical route.work_session_id or driver_id: M02
    # current-period assignment is the source of truth.
    await establish_session_vehicle_opening(
        db,
        company_id=field_context.company_id,
        session_id=session.id,
        vehicle_location_id=int(authority.vehicle_location_id),
    )
    return {
        "message": "Work session started.",
        "session_id": int(session.id),
        "commercial_context": commercial_context_payload(context_row),
        "execution_context": {
            "period_id": int(authority.period.id),
            "assignment_context_revision": int(authority.period.context_revision),
            "vehicle_location_id": int(authority.vehicle_location_id),
            "custody_epoch_id": int(authority.custody_epoch.id),
        },
    }
