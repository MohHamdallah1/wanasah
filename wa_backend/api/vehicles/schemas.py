from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_DB_INT_MAX = 2_147_483_647


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _plate(value: str) -> str:
    value = value.strip()
    if not value or "\x00" in value:
        raise ValueError("plate_number is invalid")
    return value


def _vehicle_type(value: str | None) -> str | None:
    if value is None:
        return None
    if "\x00" in value:
        raise ValueError("vehicle_type is invalid")
    value = value.strip()
    return value or None


class VehicleResponse(StrictModel):
    id: int = Field(gt=0)
    plate_number: str
    vehicle_type: str | None
    current_mileage: int
    next_oil_change: int | None
    license_expiry_date: date | None
    maintenance_status: Literal["Active", "In_Maintenance"]
    is_active: bool
    version: int = Field(gt=0)
    custody_ready: bool


class VehicleCursorPage(StrictModel):
    items: list[VehicleResponse]
    next_cursor: str | None = None
    has_more: bool


class VehicleCreateRequest(StrictModel):
    request_id: UUID
    plate_number: str = Field(min_length=1, max_length=20)
    vehicle_type: str | None = Field(default=None, max_length=50)
    current_mileage: int = Field(default=0, ge=0, le=_DB_INT_MAX)
    next_oil_change: int | None = Field(default=None, ge=0, le=_DB_INT_MAX)
    license_expiry_date: date | None = None
    maintenance_status: Literal["Active", "In_Maintenance"] = "Active"

    @field_validator("plate_number")
    @classmethod
    def normalize_plate(cls, value: str) -> str:
        return _plate(value)

    @field_validator("vehicle_type")
    @classmethod
    def normalize_type(cls, value: str | None) -> str | None:
        return _vehicle_type(value)


class VehicleUpdateRequest(StrictModel):
    request_id: UUID
    expected_version: int = Field(gt=0)
    plate_number: str | None = Field(default=None, min_length=1, max_length=20)
    vehicle_type: str | None = Field(default=None, max_length=50)
    current_mileage: int | None = Field(default=None, ge=0, le=_DB_INT_MAX)
    next_oil_change: int | None = Field(default=None, ge=0, le=_DB_INT_MAX)
    license_expiry_date: date | None = None
    maintenance_status: Literal["Active", "In_Maintenance"] | None = None

    @field_validator("plate_number")
    @classmethod
    def normalize_optional_plate(cls, value: str | None) -> str | None:
        return None if value is None else _plate(value)

    @field_validator("vehicle_type")
    @classmethod
    def normalize_optional_type(cls, value: str | None) -> str | None:
        return _vehicle_type(value)

    @model_validator(mode="after")
    def validate_patch(self):
        mutable = self.model_fields_set - {"request_id", "expected_version"}
        if not mutable:
            raise ValueError("at least one mutable vehicle field is required")
        for name in ("plate_number", "current_mileage", "maintenance_status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} may not be null")
        return self


class VehicleLifecycleRequest(StrictModel):
    request_id: UUID
    expected_version: int = Field(gt=0)


__all__ = [
    "VehicleCreateRequest",
    "VehicleCursorPage",
    "VehicleLifecycleRequest",
    "VehicleResponse",
    "VehicleUpdateRequest",
]
