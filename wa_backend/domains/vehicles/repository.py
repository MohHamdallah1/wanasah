from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import InventoryLocation, OperationIdempotency, SystemAuditLog, Vehicle
from services import acquire_inventory_location_guard

from .contracts import VehicleError


_VEHICLE_IDEMPOTENT_OPERATIONS = frozenset(
    {
        "VEHICLE_CREATE",
        "VEHICLE_UPDATE",
        "VEHICLE_DEACTIVATE",
        "VEHICLE_REACTIVATE",
    }
)


async def guard_vehicle_request_identity(
    db: AsyncSession,
    *,
    company_id: int,
    request_id: str,
    operation: str,
) -> str:
    if operation not in _VEHICLE_IDEMPOTENT_OPERATIONS:
        raise ValueError("Unsupported Vehicle idempotency operation")
    try:
        canonical_request_id = str(UUID(str(request_id)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise VehicleError(
            "VEHICLE_REQUEST_ID_INVALID",
            "Vehicle request id is invalid.",
            status_code=422,
        ) from exc

    await db.execute(
        select(
            func.pg_advisory_xact_lock(
                int(company_id),
                func.hashtext(f"vehicle-request:{canonical_request_id}"),
            )
        )
    )
    existing = list(
        (
            await db.execute(
                select(OperationIdempotency.operation)
                .where(
                    OperationIdempotency.company_id == int(company_id),
                    OperationIdempotency.request_id == canonical_request_id,
                    OperationIdempotency.operation.in_(
                        tuple(sorted(_VEHICLE_IDEMPOTENT_OPERATIONS))
                    ),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if any(str(value) != operation for value in existing):
        raise VehicleError(
            "VEHICLE_IDEMPOTENCY_CONFLICT",
            "The request identity conflicts with a previous vehicle command.",
            status_code=409,
        )
    return canonical_request_id


async def load_vehicle(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
    for_update: bool = False,
) -> Vehicle:
    stmt = select(Vehicle).where(
        Vehicle.company_id == company_id,
        Vehicle.id == vehicle_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    vehicle = (await db.execute(stmt)).scalar_one_or_none()
    if vehicle is None:
        raise VehicleError(
            "VEHICLE_NOT_FOUND",
            "Vehicle was not found.",
            status_code=404,
        )
    return vehicle


async def plate_exists(
    db: AsyncSession,
    *,
    company_id: int,
    plate_number: str,
    exclude_vehicle_id: int | None = None,
) -> bool:
    stmt = select(Vehicle.id).where(
        Vehicle.company_id == company_id,
        Vehicle.plate_number == plate_number,
    )
    if exclude_vehicle_id is not None:
        stmt = stmt.where(Vehicle.id != exclude_vehicle_id)
    return await db.scalar(stmt.limit(1)) is not None


async def _custody_ids(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
) -> list[int]:
    rows = await db.execute(
        select(InventoryLocation.id)
        .where(
            InventoryLocation.company_id == company_id,
            InventoryLocation.vehicle_id == vehicle_id,
            InventoryLocation.location_type == "VEHICLE",
        )
        .order_by(InventoryLocation.id.asc())
    )
    return [int(value) for value in rows.scalars().all()]


def _custody_cardinality_error(count: int) -> VehicleError:
    if count == 0:
        return VehicleError(
            "VEHICLE_CUSTODY_LOCATION_MISSING",
            "Vehicle custody location is missing.",
            status_code=409,
        )
    return VehicleError(
        "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS",
        "Vehicle custody location is ambiguous.",
        status_code=409,
        context={"location_count": count},
    )


async def lock_canonical_custody(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
) -> InventoryLocation:
    ids = await _custody_ids(db, company_id=company_id, vehicle_id=vehicle_id)
    if len(ids) != 1:
        raise _custody_cardinality_error(len(ids))
    location_id = ids[0]
    await acquire_inventory_location_guard(
        db,
        company_id,
        location_id,
        exclusive=True,
    )
    location = (
        await db.execute(
            select(InventoryLocation)
            .where(
                InventoryLocation.company_id == company_id,
                InventoryLocation.id == location_id,
                InventoryLocation.vehicle_id == vehicle_id,
                InventoryLocation.location_type == "VEHICLE",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if location is None:
        raise VehicleError(
            "VEHICLE_CUSTODY_LOCATION_INCONSISTENT",
            "Vehicle custody location changed during the operation.",
            status_code=409,
        )
    return location


def create_vehicle_custody(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle: Vehicle,
) -> InventoryLocation:
    if vehicle.id is None:
        raise VehicleError(
            "VEHICLE_CUSTODY_CREATE_ORDER_INVALID",
            "Vehicle identity must exist before custody is created.",
            status_code=409,
        )
    location = InventoryLocation(
        company_id=company_id,
        branch_id=None,
        name=f"Vehicle {vehicle.plate_number}",
        code=f"VEH-{int(vehicle.id)}",
        location_type="VEHICLE",
        vehicle_id=int(vehicle.id),
        system_role=None,
        is_system_managed=False,
        is_active=True,
        version=1,
    )
    db.add(location)
    return location


def add_vehicle_audit(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    vehicle_id: int,
    action: str,
    before: dict | None,
    after: dict,
) -> None:
    db.add(
        SystemAuditLog(
            company_id=company_id,
            admin_id=actor_id,
            target_id=f"Vehicle_{vehicle_id}",
            action_type=action,
            old_value=(
                json.dumps(before, sort_keys=True, ensure_ascii=False, default=str)
                if before is not None
                else None
            ),
            new_value=json.dumps(
                after,
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            ),
        )
    )


__all__ = [
    "add_vehicle_audit",
    "create_vehicle_custody",
    "guard_vehicle_request_identity",
    "load_vehicle",
    "lock_canonical_custody",
    "plate_exists",
]
