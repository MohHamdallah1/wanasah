from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_MAX_DEBT_LIMIT = Decimal("999999999.999")
_DEBT_QUANT = Decimal("0.001")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _validate_debt_limit(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if not value.is_finite() or value < 0 or value > _MAX_DEBT_LIMIT:
        raise ValueError("max_debt_limit is outside the supported range")
    if value.quantize(_DEBT_QUANT) != value:
        raise ValueError("max_debt_limit supports at most 3 decimal places")
    return value


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

    @field_validator("max_debt_limit")
    @classmethod
    def validate_debt_limit(cls, value: Decimal) -> Decimal:
        result = _validate_debt_limit(value)
        assert result is not None
        return result


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

    @field_validator("max_debt_limit")
    @classmethod
    def validate_optional_debt_limit(cls, value: Decimal | None) -> Decimal | None:
        return _validate_debt_limit(value)

    @model_validator(mode="after")
    def validate_patch_shape(self):
        mutable_fields = self.model_fields_set - {"request_id"}
        if not mutable_fields:
            raise ValueError("at least one mutable representative field is required")
        for field in ("full_name", "username", "can_allow_debt", "max_debt_limit"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null")
        return self


class RepresentativeLifecycleRequest(StrictModel):
    request_id: UUID


class RepresentativeCredentialResetRequest(StrictModel):
    request_id: UUID
    new_password: str = Field(min_length=8, max_length=72)


__all__ = [
    "RepresentativeCreateRequest",
    "RepresentativeCredentialResetRequest",
    "RepresentativeCursorPage",
    "RepresentativeLifecycleRequest",
    "RepresentativeResponse",
    "RepresentativeUpdateRequest",
]
