from __future__ import annotations

import base64
import hashlib
import json

from sqlalchemy import and_, case, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from models import InventoryLocation, Vehicle

from .contracts import (
    VEHICLE_MAINTENANCE_STATUSES,
    VehicleError,
    VehiclePage,
    VehicleRecord,
)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


def _sort_rank(is_active: bool, maintenance_status: str) -> int:
    if not is_active:
        return 2
    return 0 if maintenance_status == "Active" else 1


def _sort_rank_column():
    return case(
        (Vehicle.is_active.is_(False), 2),
        (Vehicle.maintenance_status == "Active", 0),
        else_=1,
    )


def _normalized_plate_column():
    return func.lower(func.trim(Vehicle.plate_number))


def _custody_readiness_column():
    total = (
        select(func.count(InventoryLocation.id))
        .where(
            InventoryLocation.company_id == Vehicle.company_id,
            InventoryLocation.vehicle_id == Vehicle.id,
            InventoryLocation.location_type == "VEHICLE",
        )
        .correlate(Vehicle)
        .scalar_subquery()
    )
    active = (
        select(func.count(InventoryLocation.id))
        .where(
            InventoryLocation.company_id == Vehicle.company_id,
            InventoryLocation.vehicle_id == Vehicle.id,
            InventoryLocation.location_type == "VEHICLE",
            InventoryLocation.is_active.is_(True),
        )
        .correlate(Vehicle)
        .scalar_subquery()
    )
    return case(
        (
            and_(
                total == 1,
                or_(
                    and_(Vehicle.is_active.is_(True), active == 1),
                    and_(Vehicle.is_active.is_(False), active == 0),
                ),
            ),
            True,
        ),
        else_=False,
    )


def _record(vehicle: Vehicle, custody_ready: bool) -> VehicleRecord:
    return VehicleRecord(
        vehicle_id=int(vehicle.id),
        plate_number=str(vehicle.plate_number),
        vehicle_type=(
            str(vehicle.vehicle_type)
            if vehicle.vehicle_type is not None
            else None
        ),
        current_mileage=int(vehicle.current_mileage),
        next_oil_change=(
            int(vehicle.next_oil_change)
            if vehicle.next_oil_change is not None
            else None
        ),
        license_expiry_date=vehicle.license_expiry_date,
        next_maintenance_date=vehicle.next_maintenance_date,
        maintenance_status=str(vehicle.maintenance_status),
        is_active=bool(vehicle.is_active),
        version=int(vehicle.version),
        custody_ready=bool(custody_ready),
    )


def vehicle_payload(record: VehicleRecord) -> dict:
    return {
        "id": record.vehicle_id,
        "plate_number": record.plate_number,
        "vehicle_type": record.vehicle_type,
        "current_mileage": record.current_mileage,
        "next_oil_change": record.next_oil_change,
        "license_expiry_date": (
            record.license_expiry_date.isoformat()
            if record.license_expiry_date
            else None
        ),
        "next_maintenance_date": (
            record.next_maintenance_date.isoformat()
            if record.next_maintenance_date
            else None
        ),
        "maintenance_status": record.maintenance_status,
        "is_active": record.is_active,
        "version": record.version,
        "custody_ready": record.custody_ready,
    }


def _encode_cursor(
    record: VehicleRecord,
    *,
    scope: str,
    normalized_plate: str,
) -> str:
    raw = json.dumps(
        {
            "v": 1,
            "kind": "vehicle",
            "scope": _scope_hash(scope),
            "rank": _sort_rank(record.is_active, record.maintenance_status),
            "plate": normalized_plate,
            "id": record.vehicle_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(
    cursor: str,
    *,
    expected_scope: str,
) -> tuple[int, str, int]:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode((cursor + padding).encode("ascii")).decode("utf-8")
        )
        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("kind") != "vehicle"
            or payload.get("scope") != _scope_hash(expected_scope)
        ):
            raise ValueError
        rank = payload.get("rank")
        plate = payload.get("plate")
        vehicle_id = payload.get("id")
        if (
            rank not in (0, 1, 2)
            or not isinstance(plate, str)
            or type(vehicle_id) is not int
            or vehicle_id <= 0
        ):
            raise ValueError
        return rank, plate, vehicle_id
    except Exception as exc:
        raise VehicleError(
            "VEHICLE_CURSOR_INVALID",
            "Vehicle cursor is invalid for the current query.",
            status_code=400,
        ) from exc


async def list_vehicles(
    db: AsyncSession,
    *,
    company_id: int,
    search: str | None,
    active: bool | None,
    maintenance_status: str | None,
    cursor: str | None,
    limit: int,
    visibility_filter=None,
    scope_tag: str = "company",
) -> VehiclePage:
    clean_search = (search or "").strip().lower()
    if search is not None and not 2 <= len(clean_search) <= 100:
        raise VehicleError(
            "VEHICLE_SEARCH_INVALID",
            "Vehicle search must contain between 2 and 100 characters.",
            status_code=422,
        )
    if (
        maintenance_status is not None
        and maintenance_status not in VEHICLE_MAINTENANCE_STATUSES
    ):
        raise VehicleError(
            "VEHICLE_MAINTENANCE_STATUS_INVALID",
            "Vehicle maintenance status is invalid.",
            status_code=422,
        )

    visibility_filter = true() if visibility_filter is None else visibility_filter
    scope = (
        f"vehicles|{company_id}|{scope_tag}|{active!r}|"
        f"{maintenance_status!r}|{clean_search}"
    )
    rank = _sort_rank_column()
    plate = _normalized_plate_column()
    custody_ready = _custody_readiness_column()
    stmt = select(
        Vehicle,
        plate.label("cursor_plate"),
        custody_ready.label("custody_ready"),
    ).where(
        Vehicle.company_id == company_id,
        visibility_filter,
    )

    if active is True:
        stmt = stmt.where(Vehicle.is_active.is_(True))
    elif active is False:
        stmt = stmt.where(Vehicle.is_active.is_(False))
    if maintenance_status is not None:
        stmt = stmt.where(Vehicle.maintenance_status == maintenance_status)
    if clean_search:
        pattern = f"%{_escape_like(clean_search)}%"
        stmt = stmt.where(
            or_(
                plate.like(pattern, escape="\\"),
                func.lower(func.trim(func.coalesce(Vehicle.vehicle_type, ""))).like(
                    pattern,
                    escape="\\",
                ),
            )
        )
    if cursor:
        cursor_rank, cursor_plate, cursor_id = _decode_cursor(
            cursor,
            expected_scope=scope,
        )
        stmt = stmt.where(
            or_(
                rank > cursor_rank,
                and_(rank == cursor_rank, plate > cursor_plate),
                and_(
                    rank == cursor_rank,
                    plate == cursor_plate,
                    Vehicle.id > cursor_id,
                ),
            )
        )

    rows = (
        await db.execute(
            stmt.order_by(rank.asc(), plate.asc(), Vehicle.id.asc()).limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    records = tuple(
        _record(vehicle, ready)
        for vehicle, _plate, ready in page_rows
    )
    next_cursor = (
        _encode_cursor(
            records[-1],
            scope=scope,
            normalized_plate=str(page_rows[-1][1]),
        )
        if has_more and records
        else None
    )
    return VehiclePage(records, next_cursor, has_more)


async def get_vehicle(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
    visibility_filter=None,
) -> VehicleRecord:
    visibility_filter = true() if visibility_filter is None else visibility_filter
    custody_ready = _custody_readiness_column()
    row = (
        await db.execute(
            select(Vehicle, custody_ready.label("custody_ready")).where(
                Vehicle.company_id == company_id,
                Vehicle.id == vehicle_id,
                visibility_filter,
            )
        )
    ).one_or_none()
    if row is None:
        raise VehicleError(
            "VEHICLE_NOT_FOUND",
            "Vehicle was not found.",
            status_code=404,
        )
    return _record(row[0], row[1])


__all__ = ["get_vehicle", "list_vehicles", "vehicle_payload"]
