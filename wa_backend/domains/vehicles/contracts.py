from __future__ import annotations

from dataclasses import dataclass
from datetime import date


VEHICLE_MAINTENANCE_STATUSES = frozenset({"Active", "In_Maintenance"})
CURRENT_ROUTE_STATUSES = ("active", "waiting", "postponed")


class VehicleError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        context: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.context = context or {}


@dataclass(frozen=True, slots=True)
class VehicleRecord:
    vehicle_id: int
    plate_number: str
    vehicle_type: str | None
    current_mileage: int
    next_oil_change: int | None
    license_expiry_date: date | None
    maintenance_status: str
    is_active: bool
    version: int
    custody_ready: bool


@dataclass(frozen=True, slots=True)
class VehiclePage:
    items: tuple[VehicleRecord, ...]
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class CreateVehicleCommand:
    request_id: str
    plate_number: str
    vehicle_type: str | None = None
    current_mileage: int = 0
    next_oil_change: int | None = None
    license_expiry_date: date | None = None
    maintenance_status: str = "Active"


@dataclass(frozen=True, slots=True)
class UpdateVehicleCommand:
    request_id: str
    expected_version: int
    fields: dict[str, object]


@dataclass(frozen=True, slots=True)
class VehicleLifecycleCommand:
    request_id: str
    expected_version: int


__all__ = [
    "CURRENT_ROUTE_STATUSES",
    "CreateVehicleCommand",
    "UpdateVehicleCommand",
    "VEHICLE_MAINTENANCE_STATUSES",
    "VehicleError",
    "VehicleLifecycleCommand",
    "VehiclePage",
    "VehicleRecord",
]
