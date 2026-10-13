from __future__ import annotations

from decimal import Decimal
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


class RepresentativeCursorPage(StrictModel):
    items: list[RepresentativeResponse]
    next_cursor: str | None = None
    has_more: bool


class RepresentativeCreateRequest(StrictModel):
    request_id: UUID
    full_name: str = Field(min_length=1, max_length=120)
    username: str = Field(min_length=1, max_length=80)
    phone_number: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=8, max_length=72)
    can_allow_debt: bool = False
    max_debt_limit: Decimal = Field(
        default=Decimal("0.000"),
        ge=0,
        max_digits=12,
        decimal_places=3,
    )

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


class RepresentativeUpdateRequest(StrictModel):
    request_id: UUID
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    username: str | None = Field(default=None, min_length=1, max_length=80)
    phone_number: str | None = Field(default=None, max_length=20)
    can_allow_debt: bool | None = None
    max_debt_limit: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=3,
    )

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
    def validate_patch_shape(self):
        mutable_fields = self.model_fields_set - {"request_id"}
        if not mutable_fields:
            raise ValueError("at least one mutable representative field is required")
        for field in ("full_name", "username", "can_allow_debt", "max_debt_limit"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null")
        return self


__all__ = [
    "RepresentativeCreateRequest",
    "RepresentativeCursorPage",
    "RepresentativeResponse",
    "RepresentativeUpdateRequest",
]
