from __future__ import annotations

from datetime import date

from .contracts import (
    VEHICLE_MAINTENANCE_STATUSES,
    UpdateVehicleCommand,
    VehicleError,
)


_DB_INT_MAX = 2_147_483_647
_MUTABLE_FIELDS = frozenset({
    "plate_number",
    "vehicle_type",
    "current_mileage",
    "next_oil_change",
    "license_expiry_date",
    "next_maintenance_date",
    "maintenance_status",
})


def normalize_plate(value: object) -> str:
    if not isinstance(value, str):
        raise VehicleError("VEHICLE_PLATE_INVALID", "Vehicle plate number is invalid.", status_code=422)
    value = value.strip()
    if not value or len(value) > 20 or "\x00" in value:
        raise VehicleError("VEHICLE_PLATE_INVALID", "Vehicle plate number is invalid.", status_code=422)
    return value


def normalize_vehicle_type(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or "\x00" in value:
        raise VehicleError("VEHICLE_TYPE_INVALID", "Vehicle type is invalid.", status_code=422)
    value = value.strip()
    if not value:
        return None
    if len(value) > 50:
        raise VehicleError("VEHICLE_TYPE_INVALID", "Vehicle type is invalid.", status_code=422)
    return value


def nonnegative_int(value: object, field: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or type(value) is not int or value < 0 or value > _DB_INT_MAX:
        raise VehicleError(
            "VEHICLE_FIELD_INVALID",
            f"{field} is invalid.",
            status_code=422,
            context={"field": field},
        )
    return int(value)


def normalize_maintenance_status(value: object) -> str:
    if not isinstance(value, str) or value not in VEHICLE_MAINTENANCE_STATUSES:
        raise VehicleError(
            "VEHICLE_MAINTENANCE_STATUS_INVALID",
            "Vehicle maintenance status is invalid.",
            status_code=422,
        )
    return value


def validated_update_fields(command: UpdateVehicleCommand) -> dict[str, object]:
    if command.expected_version <= 0:
        raise VehicleError("VEHICLE_VERSION_INVALID", "Vehicle expected version is invalid.", status_code=422)
    fields = dict(command.fields)
    if not fields:
        raise VehicleError("VEHICLE_UPDATE_EMPTY", "At least one mutable vehicle field is required.", status_code=422)
    unknown = set(fields) - _MUTABLE_FIELDS
    if unknown:
        raise VehicleError("VEHICLE_UPDATE_FIELD_INVALID", "Vehicle update contains an unsupported field.", status_code=422)
    if "plate_number" in fields:
        fields["plate_number"] = normalize_plate(fields["plate_number"])
    if "vehicle_type" in fields:
        fields["vehicle_type"] = normalize_vehicle_type(fields["vehicle_type"])
    if "current_mileage" in fields:
        fields["current_mileage"] = nonnegative_int(fields["current_mileage"], "current_mileage")
    if "next_oil_change" in fields:
        fields["next_oil_change"] = nonnegative_int(fields["next_oil_change"], "next_oil_change", optional=True)
    for date_field in ("license_expiry_date", "next_maintenance_date"):
        if (
            date_field in fields
            and fields[date_field] is not None
            and not isinstance(fields[date_field], date)
        ):
            raise VehicleError(
                "VEHICLE_FIELD_INVALID",
                f"{date_field} is invalid.",
                status_code=422,
                context={"field": date_field},
            )
    if "maintenance_status" in fields:
        fields["maintenance_status"] = normalize_maintenance_status(fields["maintenance_status"])
    return fields


__all__ = [
    "nonnegative_int",
    "normalize_maintenance_status",
    "normalize_plate",
    "normalize_vehicle_type",
    "validated_update_fields",
]
