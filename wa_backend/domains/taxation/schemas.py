from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


JurisdictionType = Literal["COUNTRY", "SUBDIVISION", "LOCALITY", "CUSTOM"]
PriceMode = Literal["EXCLUSIVE", "INCLUSIVE"]
BasisMode = Literal["TAXABLE_BASE", "TAXABLE_BASE_PLUS_PRIOR_TAX"]
ScopeType = Literal["JURISDICTION", "PRODUCT_VARIANT", "CUSTOMER", "DOCUMENT_TYPE"]

_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]*$")
_MONEY_QUANT = Decimal("0.000001")
_MONEY_MAX = Decimal("99999999999999.999999")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _stable_code(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError(f"Invalid {field}.")
    clean = value.strip().upper()
    if not clean or len(clean) > maximum or not _CODE_RE.fullmatch(clean):
        raise ValueError(f"{field} must be a stable uppercase code.")
    return clean


def _name(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError(f"Invalid {field}.")
    clean = value.strip()
    if not clean or len(clean) > maximum:
        raise ValueError(f"{field} is required.")
    return clean


def validate_jurisdiction_shape(
    jurisdiction_type: str,
    parent_jurisdiction_id: int | None,
    subdivision_code: str | None,
    locality_code: str | None,
) -> None:
    if jurisdiction_type == "COUNTRY":
        if parent_jurisdiction_id is not None or subdivision_code or locality_code:
            raise ValueError("COUNTRY jurisdiction cannot have parent/subdivision/locality codes.")
    elif jurisdiction_type == "SUBDIVISION":
        if parent_jurisdiction_id is None or not subdivision_code or locality_code:
            raise ValueError("SUBDIVISION requires parent and subdivision_code only.")
    elif jurisdiction_type == "LOCALITY":
        if parent_jurisdiction_id is None or not locality_code:
            raise ValueError("LOCALITY requires parent and locality_code.")


class JurisdictionCreate(StrictModel):
    request_id: UUID
    code: str = Field(max_length=100)
    name: str = Field(max_length=150)
    jurisdiction_type: JurisdictionType
    country_code: str = Field(min_length=2, max_length=3)
    subdivision_code: Optional[str] = Field(None, max_length=50)
    locality_code: Optional[str] = Field(None, max_length=100)
    parent_jurisdiction_id: Optional[int] = Field(None, gt=0)

    @field_validator("code", mode="before")
    @classmethod
    def code_value(cls, value: Any) -> str:
        return _stable_code(value, "code", 100)

    @field_validator("name", mode="before")
    @classmethod
    def name_value(cls, value: Any) -> str:
        return _name(value, "name", 150)

    @field_validator("country_code", mode="before")
    @classmethod
    def country_value(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("country_code must be text.")
        clean = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{2,3}", clean):
            raise ValueError("country_code must be a 2-3 letter country code.")
        return clean

    @field_validator("subdivision_code", "locality_code", mode="before")
    @classmethod
    def optional_code(cls, value: Any, info):
        if value is None:
            return None
        return _stable_code(
            value,
            info.field_name,
            50 if info.field_name == "subdivision_code" else 100,
        )

    @model_validator(mode="after")
    def hierarchy_shape(self):
        validate_jurisdiction_shape(
            self.jurisdiction_type,
            self.parent_jurisdiction_id,
            self.subdivision_code,
            self.locality_code,
        )
        return self


class JurisdictionUpdate(StrictModel):
    request_id: UUID
    expected_version: int = Field(gt=0)
    code: Optional[str] = Field(None, max_length=100)
    name: Optional[str] = Field(None, max_length=150)
    jurisdiction_type: Optional[JurisdictionType] = None
    country_code: Optional[str] = Field(None, min_length=2, max_length=3)
    subdivision_code: Optional[str] = Field(None, max_length=50)
    locality_code: Optional[str] = Field(None, max_length=100)
    parent_jurisdiction_id: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None

    @field_validator("code", mode="before")
    @classmethod
    def code_value(cls, value: Any):
        return None if value is None else _stable_code(value, "code", 100)

    @field_validator("name", mode="before")
    @classmethod
    def name_value(cls, value: Any):
        return None if value is None else _name(value, "name", 150)

    @field_validator("country_code", mode="before")
    @classmethod
    def country_value(cls, value: Any):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("country_code must be text.")
        clean = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{2,3}", clean):
            raise ValueError("country_code must be a 2-3 letter country code.")
        return clean

    @field_validator("subdivision_code", "locality_code", mode="before")
    @classmethod
    def optional_code(cls, value: Any, info):
        if value is None:
            return None
        return _stable_code(
            value,
            info.field_name,
            50 if info.field_name == "subdivision_code" else 100,
        )

    @model_validator(mode="after")
    def require_change(self):
        if not (
            {
                "code", "name", "jurisdiction_type", "country_code",
                "subdivision_code", "locality_code", "parent_jurisdiction_id",
                "is_active",
            }
            & self.model_fields_set
        ):
            raise ValueError("At least one jurisdiction field must be supplied.")
        return self


class DeleteCommand(StrictModel):
    request_id: UUID
    expected_version: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=1000)


class RuleSetCreate(StrictModel):
    request_id: UUID
    code: str = Field(max_length=100)
    name: str = Field(max_length=150)
    description: Optional[str] = Field(None, max_length=2000)

    @field_validator("code", mode="before")
    @classmethod
    def code_value(cls, value: Any) -> str:
        return _stable_code(value, "code", 100)

    @field_validator("name", mode="before")
    @classmethod
    def name_value(cls, value: Any) -> str:
        return _name(value, "name", 150)


class RuleSetUpdate(StrictModel):
    request_id: UUID
    expected_version: int = Field(gt=0)
    code: Optional[str] = Field(None, max_length=100)
    name: Optional[str] = Field(None, max_length=150)
    description: Optional[str] = Field(None, max_length=2000)

    @field_validator("code", mode="before")
    @classmethod
    def code_value(cls, value: Any):
        return None if value is None else _stable_code(value, "code", 100)

    @field_validator("name", mode="before")
    @classmethod
    def name_value(cls, value: Any):
        return None if value is None else _name(value, "name", 150)

    @model_validator(mode="after")
    def require_change(self):
        if not ({"code", "name", "description"} & self.model_fields_set):
            raise ValueError("At least one rule-set field must be supplied.")
        return self


class TaxComponentInput(StrictModel):
    component_code: str = Field(max_length=100)
    name: str = Field(max_length=150)
    sequence: int = Field(gt=0, le=100)
    rate: Decimal = Field(
        ge=0,
        description="Percentage points; 5.00000000 means 5 percent.",
    )
    basis_mode: BasisMode = "TAXABLE_BASE"
    reporting_code: Optional[str] = Field(None, max_length=100)

    @field_validator("component_code", mode="before")
    @classmethod
    def component_code_value(cls, value: Any) -> str:
        return _stable_code(value, "component_code", 100)

    @field_validator("name", mode="before")
    @classmethod
    def name_value(cls, value: Any) -> str:
        return _name(value, "name", 150)

    @field_validator("rate", mode="before")
    @classmethod
    def rate_value(cls, value: Any) -> Decimal:
        if isinstance(value, bool) or isinstance(value, float):
            raise ValueError("rate must be an exact decimal value.")
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("rate must be an exact decimal value.") from exc
        if not result.is_finite() or result < 0:
            raise ValueError("rate must be finite and non-negative.")
        if result > Decimal("999999999999.99999999"):
            raise ValueError("rate exceeds NUMERIC(20,8) capacity.")
        try:
            quantized = result.quantize(Decimal("0.00000001"))
        except InvalidOperation as exc:
            raise ValueError("rate cannot be represented with 8 decimal places.") from exc
        if result != quantized:
            raise ValueError("rate accepts at most 8 decimal places.")
        return result

    @field_validator("reporting_code", mode="before")
    @classmethod
    def reporting_value(cls, value: Any):
        return None if value is None else _stable_code(value, "reporting_code", 100)


class TaxScopeInput(StrictModel):
    scope_type: ScopeType
    jurisdiction_id: Optional[int] = Field(None, gt=0)
    product_variant_id: Optional[int] = Field(None, gt=0)
    customer_id: Optional[int] = Field(None, gt=0)
    document_type_code: Optional[str] = Field(None, max_length=80)

    @field_validator("document_type_code", mode="before")
    @classmethod
    def document_type_value(cls, value: Any):
        return None if value is None else _stable_code(value, "document_type_code", 80)

    @model_validator(mode="after")
    def validate_target(self):
        values = {
            "JURISDICTION": self.jurisdiction_id,
            "PRODUCT_VARIANT": self.product_variant_id,
            "CUSTOMER": self.customer_id,
            "DOCUMENT_TYPE": self.document_type_code,
        }
        if values[self.scope_type] is None:
            raise ValueError(f"{self.scope_type} requires its matching target.")
        if any(key != self.scope_type and value is not None for key, value in values.items()):
            raise ValueError("Exactly one tax scope target may be supplied.")
        return self


class VersionConfigMixin(StrictModel):
    priority: int = Field(default=0, ge=0)
    price_mode: PriceMode = "EXCLUSIVE"
    effective_from: datetime
    effective_to: Optional[datetime] = None
    components: list[TaxComponentInput] = Field(min_length=1, max_length=100)
    scopes: list[TaxScopeInput] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.effective_from.tzinfo is None or self.effective_from.utcoffset() is None:
            raise ValueError("effective_from must include a timezone.")
        if self.effective_to is not None:
            if self.effective_to.tzinfo is None or self.effective_to.utcoffset() is None:
                raise ValueError("effective_to must include a timezone.")
            if self.effective_to <= self.effective_from:
                raise ValueError("effective_to must be later than effective_from.")
        return self


class VersionCreate(VersionConfigMixin):
    request_id: UUID
    expected_rule_set_version: int = Field(gt=0)


class VersionUpdate(VersionConfigMixin):
    request_id: UUID
    expected_version: int = Field(gt=0)


class VersionDelete(DeleteCommand):
    pass


class VersionCommand(StrictModel):
    request_id: UUID
    expected_version: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=1000)


class TaxPreviewLine(StrictModel):
    line_id: int = Field(gt=0)
    product_variant_id: int = Field(gt=0)
    amount: Decimal

    @field_validator("amount", mode="before")
    @classmethod
    def exact_money(cls, value: Any) -> Decimal:
        if isinstance(value, bool) or isinstance(value, float):
            raise ValueError("amount must be an exact decimal value.")
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("amount must be an exact decimal value.") from exc
        if not result.is_finite() or result < 0:
            raise ValueError("amount must be finite and non-negative.")
        try:
            quantized = result.quantize(_MONEY_QUANT)
        except InvalidOperation as exc:
            raise ValueError("amount cannot be represented with 6 decimal places.") from exc
        if result != quantized:
            raise ValueError("amount accepts at most 6 decimal places.")
        if result > _MONEY_MAX:
            raise ValueError("amount exceeds NUMERIC(20,6) capacity.")
        return result


class TaxPreviewRequest(StrictModel):
    jurisdiction_id: int = Field(gt=0)
    customer_id: Optional[int] = Field(None, gt=0)
    document_type_code: str = Field(min_length=1, max_length=80)
    as_of: Optional[datetime] = None
    tax_revision_ceiling: Optional[int] = Field(None, gt=0)
    lines: list[TaxPreviewLine] = Field(min_length=1, max_length=500)

    @field_validator("document_type_code", mode="before")
    @classmethod
    def document_code(cls, value: Any) -> str:
        return _stable_code(value, "document_type_code", 80)

    @model_validator(mode="after")
    def validate_preview(self):
        if self.as_of is not None and (
            self.as_of.tzinfo is None or self.as_of.utcoffset() is None
        ):
            raise ValueError("as_of must include a timezone.")
        line_ids = [line.line_id for line in self.lines]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("Tax preview line_id values must be unique.")
        return self
