from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RepresentativeResponse(StrictModel):
    id: int = Field(gt=0)
    full_name: str
    username: str
    phone_number: str | None
    is_active: bool
    can_allow_debt: bool
    max_debt_limit: Decimal
    created_at: datetime
    updated_at: datetime


class RepresentativeCursorPage(StrictModel):
    items: list[RepresentativeResponse]
    next_cursor: str | None = None
    has_more: bool


class RepresentativeMutationResponse(StrictModel):
    message: str
    representative: RepresentativeResponse


class RepresentativeCreateRequest(StrictModel):
    request_id: UUID
    full_name: str = Field(min_length=1, max_length=120)
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=72)
    phone_number: str | None = Field(default=None, max_length=20)
    can_allow_debt: bool = False
    max_debt_limit: Decimal = Decimal("0.000")

    @field_validator("full_name", "username")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be blank")
        return value

    @field_validator("phone_number")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("password exceeds bcrypt byte limit")
        return value


class RepresentativeUpdateRequest(StrictModel):
    request_id: UUID
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    username: str | None = Field(default=None, min_length=1, max_length=80)
    phone_number: str | None = Field(default=None, max_length=20)
    can_allow_debt: bool | None = None
    max_debt_limit: Decimal | None = None

    @field_validator("full_name", "username")
    @classmethod
    def normalize_optional_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("field must not be blank")
        return value

    @field_validator("phone_number")
    @classmethod
    def normalize_optional_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def reject_null_required_identity_fields(self):
        for field in ("full_name", "username", "can_allow_debt", "max_debt_limit"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null")
        return self


RepresentativeStatus = Literal["active", "inactive", "all"]


__all__ = [
    "RepresentativeCreateRequest",
    "RepresentativeCursorPage",
    "RepresentativeMutationResponse",
    "RepresentativeResponse",
    "RepresentativeStatus",
    "RepresentativeUpdateRequest",
]
