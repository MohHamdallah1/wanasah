from __future__ import annotations

from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    DispatchRoute,
    InventoryBalance,
    InventoryLock,
    InventoryTransferHeader,
    StocktakeSession,
    WorkSession,
)

from .contracts import CURRENT_ROUTE_STATUSES, VehicleError


_FINAL_TRANSFER_STATUSES = ("POSTED", "REJECTED", "CANCELLED")
_OPEN_STOCKTAKE_STATUSES = (
    "DRAFT",
    "COUNTING",
    "PENDING_REVIEW",
    "RECOUNT_REQUIRED",
    "APPROVED",
)


def _blocked(code: str, message: str, blocker: str) -> VehicleError:
    return VehicleError(
        code,
        message,
        status_code=409,
        context={"blocker": blocker},
    )


async def _current_route_exists(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
) -> bool:
    value = await db.scalar(
        select(DispatchRoute.id)
        .where(
            DispatchRoute.company_id == company_id,
            DispatchRoute.vehicle_id == vehicle_id,
            DispatchRoute.status.in_(CURRENT_ROUTE_STATUSES),
        )
        .order_by(DispatchRoute.id.asc())
        .limit(1)
    )
    return value is not None


async def _unreconciled_session_exists(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
) -> bool:
    value = await db.scalar(
        select(WorkSession.id)
        .join(
            DispatchRoute,
            and_(
                DispatchRoute.company_id == WorkSession.company_id,
                DispatchRoute.work_session_id == WorkSession.id,
            ),
        )
        .where(
            WorkSession.company_id == company_id,
            DispatchRoute.company_id == company_id,
            DispatchRoute.vehicle_id == vehicle_id,
            WorkSession.inventory_reconciled_at.is_(None),
        )
        .order_by(WorkSession.id.asc())
        .limit(1)
    )
    return value is not None


async def assert_vehicle_maintenance_transition_safe(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
) -> None:
    if await _current_route_exists(
        db,
        company_id=company_id,
        vehicle_id=vehicle_id,
    ):
        raise _blocked(
            "VEHICLE_MAINTENANCE_BLOCKED",
            "Vehicle cannot enter maintenance while a current route remains open.",
            "CURRENT_DISPATCH_ROUTE",
        )
    if await _unreconciled_session_exists(
        db,
        company_id=company_id,
        vehicle_id=vehicle_id,
    ):
        raise _blocked(
            "VEHICLE_MAINTENANCE_BLOCKED",
            "Vehicle cannot enter maintenance before inventory reconciliation is complete.",
            "UNRECONCILED_WORK_SESSION",
        )


async def assert_vehicle_deactivation_safe(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
    location_id: int,
) -> None:
    if await _current_route_exists(
        db,
        company_id=company_id,
        vehicle_id=vehicle_id,
    ):
        raise _blocked(
            "VEHICLE_DEACTIVATION_BLOCKED",
            "Vehicle cannot be deactivated while a current route remains open.",
            "CURRENT_DISPATCH_ROUTE",
        )
    if await _unreconciled_session_exists(
        db,
        company_id=company_id,
        vehicle_id=vehicle_id,
    ):
        raise _blocked(
            "VEHICLE_DEACTIVATION_BLOCKED",
            "Vehicle cannot be deactivated before inventory reconciliation is complete.",
            "UNRECONCILED_WORK_SESSION",
        )

    totals = (
        await db.execute(
            select(
                func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0),
                func.coalesce(func.sum(InventoryBalance.reserved_quantity), 0),
            ).where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == location_id,
            )
        )
    ).one()
    if Decimal(totals[0] or 0) != 0 or Decimal(totals[1] or 0) != 0:
        raise _blocked(
            "VEHICLE_DEACTIVATION_BLOCKED",
            "Vehicle cannot be deactivated while inventory custody remains.",
            "NONZERO_OR_RESERVED_INVENTORY",
        )

    unfinished_transfer = await db.scalar(
        select(InventoryTransferHeader.id)
        .where(
            InventoryTransferHeader.company_id == company_id,
            or_(
                InventoryTransferHeader.source_location_id == location_id,
                InventoryTransferHeader.destination_location_id == location_id,
            ),
            InventoryTransferHeader.status.not_in(_FINAL_TRANSFER_STATUSES),
        )
        .order_by(InventoryTransferHeader.id.asc())
        .limit(1)
    )
    if unfinished_transfer is not None:
        raise _blocked(
            "VEHICLE_DEACTIVATION_BLOCKED",
            "Vehicle cannot be deactivated while an inventory transfer remains unfinished.",
            "UNFINISHED_TRANSFER",
        )

    active_lock = await db.scalar(
        select(InventoryLock.id)
        .where(
            InventoryLock.company_id == company_id,
            InventoryLock.location_id == location_id,
            InventoryLock.released_at.is_(None),
        )
        .order_by(InventoryLock.id.asc())
        .limit(1)
    )
    if active_lock is not None:
        raise _blocked(
            "VEHICLE_DEACTIVATION_BLOCKED",
            "Vehicle cannot be deactivated while inventory is locked.",
            "INVENTORY_LOCK",
        )

    open_stocktake = await db.scalar(
        select(StocktakeSession.id)
        .where(
            StocktakeSession.company_id == company_id,
            StocktakeSession.location_id == location_id,
            StocktakeSession.status.in_(_OPEN_STOCKTAKE_STATUSES),
        )
        .order_by(StocktakeSession.id.asc())
        .limit(1)
    )
    if open_stocktake is not None:
        raise _blocked(
            "VEHICLE_DEACTIVATION_BLOCKED",
            "Vehicle cannot be deactivated while stocktake or reconciliation remains open.",
            "OPEN_STOCKTAKE",
        )


__all__ = [
    "assert_vehicle_deactivation_safe",
    "assert_vehicle_maintenance_transition_safe",
]
