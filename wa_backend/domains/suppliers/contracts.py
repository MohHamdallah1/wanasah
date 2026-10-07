"""Language-neutral V1 HTTP and immutable cross-domain contracts."""
from dataclasses import dataclass
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SupplierDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=300)
    code: str | None = Field(default=None, max_length=50)
    contact_person: str | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=254)
    address: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("code", "contact_person", "phone", "email", "address", "notes", mode="before")
    @classmethod
    def optional_text(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value

    @field_validator("code")
    @classmethod
    def canonical_code(cls, value):
        return value.upper() if value else None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        if value and (value.count("@") != 1 or any(c.isspace() for c in value)
                      or not all(value.split("@"))):
            raise ValueError("email must have a local part and domain")
        return value


class SupplierCreate(SupplierDetails):
    request_id: UUID


class SupplierUpdate(SupplierDetails):
    request_id: UUID
    expected_version: int = Field(ge=1)


class SupplierState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_version: int = Field(ge=1)
    is_active: bool


class SupplierView(SupplierDetails):
    id: int
    is_active: bool
    version: int
    created_at: str
    updated_at: str


class SupplierPage(BaseModel):
    items: list[SupplierView]
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True)
class SupplierSnapshot:
    id: int
    name: str
    code: str | None
