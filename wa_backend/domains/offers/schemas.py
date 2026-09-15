from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from quantity import parse_quantity


OfferType = Literal[
    "PERCENTAGE_DISCOUNT",
    "FIXED_DISCOUNT",
    "BUY_X_GET_Y",
    "FREE_GOODS",
    "QUANTITY_TIERS",
    "BUNDLE",
]
StackingMode = Literal["EXCLUSIVE", "STACKABLE"]
ScopeType = Literal["PRODUCT_VARIANT", "CUSTOMER", "BRANCH", "CHANNEL"]
ProductRole = Literal["QUALIFYING", "REWARD", "BUNDLE_COMPONENT"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _quantity(value: Any, field_name: str) -> Decimal:
    return parse_quantity(value, field_name)


def _money(value: Any, field_name: str) -> Decimal:
    # Money and quantity share the exact NUMERIC(20,6) storage contract.
    return parse_quantity(value, field_name)


def _optional_text(value: Any, field_name: str) -> Any:
    if value is None:
        return None
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError(f"Invalid {field_name}.")
    return value


def _reason(value: Any) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError("Invalid reason.")
    clean = value.strip()
    if not 3 <= len(clean) <= 1000:
        raise ValueError(
            "reason must contain 3-1000 non-whitespace characters."
        )
    return clean


class OfferCaps(StrictModel):
    max_applications_per_document: Optional[int] = Field(None, gt=0)
    max_discount_amount: Optional[Decimal] = Field(None, gt=0)
    max_reward_quantity: Optional[Decimal] = Field(None, gt=0)

    @field_validator("max_discount_amount", mode="before")
    @classmethod
    def normalize_discount_cap(cls, value: Any) -> Optional[Decimal]:
        return None if value is None else _money(value, "max_discount_amount")

    @field_validator("max_reward_quantity", mode="before")
    @classmethod
    def normalize_reward_cap(cls, value: Any) -> Optional[Decimal]:
        return None if value is None else _quantity(value, "max_reward_quantity")


class PercentageDiscountPayload(StrictModel):
    percentage: Decimal = Field(gt=0, le=100)
    caps: Optional[OfferCaps] = None


class FixedDiscountPayload(StrictModel):
    amount: Decimal = Field(gt=0)
    caps: Optional[OfferCaps] = None

    @field_validator("amount", mode="before")
    @classmethod
    def normalize_amount(cls, value: Any) -> Decimal:
        return _money(value, "amount")


class BuyXGetYPayload(StrictModel):
    """Reward quantities live on typed REWARD product terms."""

    buy_quantity: Decimal
    caps: Optional[OfferCaps] = None

    @field_validator("buy_quantity", mode="before")
    @classmethod
    def normalize_quantity(cls, value: Any) -> Decimal:
        return _quantity(value, "buy_quantity")


class FreeGoodsPayload(StrictModel):
    """Every reward row owns its explicit UOM and quantity."""

    qualifying_quantity: Decimal
    caps: Optional[OfferCaps] = None

    @field_validator("qualifying_quantity", mode="before")
    @classmethod
    def normalize_quantity(cls, value: Any) -> Decimal:
        return _quantity(value, "qualifying_quantity")


class QuantityTier(StrictModel):
    minimum_quantity: Decimal
    reward_type: Literal["PERCENTAGE_DISCOUNT", "FIXED_DISCOUNT", "FREE_QUANTITY"]
    reward_value: Decimal

    @field_validator("minimum_quantity", "reward_value", mode="before")
    @classmethod
    def normalize_quantities(cls, value: Any, info) -> Decimal:
        return _quantity(value, info.field_name)

    @model_validator(mode="after")
    def validate_percentage(self):
        if self.reward_type == "PERCENTAGE_DISCOUNT" and self.reward_value > 100:
            raise ValueError("Percentage tier reward cannot exceed 100.")
        return self


class QuantityTiersPayload(StrictModel):
    tiers: list[QuantityTier] = Field(min_length=1, max_length=100)
    caps: Optional[OfferCaps] = None

    @model_validator(mode="after")
    def validate_tier_order(self):
        minimums = [tier.minimum_quantity for tier in self.tiers]
        if minimums != sorted(minimums) or len(set(minimums)) != len(minimums):
            raise ValueError(
                "Quantity tiers must have unique ascending minimum_quantity values."
            )
        return self


class BundlePayload(StrictModel):
    """Each BUNDLE_COMPONENT row owns its UOM and required quantity."""

    reward_type: Literal["PERCENTAGE_DISCOUNT", "FIXED_DISCOUNT", "FIXED_PRICE"]
    reward_value: Decimal = Field(gt=0)
    caps: Optional[OfferCaps] = None

    @model_validator(mode="after")
    def validate_percentage(self):
        if self.reward_type == "PERCENTAGE_DISCOUNT":
            if self.reward_value > 100:
                raise ValueError("Bundle percentage reward cannot exceed 100.")
        else:
            _money(self.reward_value, "reward_value")
        return self


class OfferScopeInput(StrictModel):
    scope_type: ScopeType
    product_variant_id: Optional[int] = Field(None, gt=0)
    uom_id: Optional[int] = Field(None, gt=0)
    customer_id: Optional[int] = Field(None, gt=0)
    branch_id: Optional[int] = Field(None, gt=0)
    channel_code: Optional[str] = Field(None, min_length=1, max_length=50)

    @field_validator("channel_code", mode="before")
    @classmethod
    def normalize_channel(cls, value: Any):
        if value is None:
            return None
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("Invalid channel_code.")
        clean = value.strip().upper()
        if not clean or not re.fullmatch(r"[A-Z0-9][A-Z0-9_.:-]{0,49}", clean):
            raise ValueError("channel_code must be a stable code.")
        return clean

    @model_validator(mode="after")
    def validate_target(self):
        values = {
            "PRODUCT_VARIANT": self.product_variant_id,
            "CUSTOMER": self.customer_id,
            "BRANCH": self.branch_id,
            "CHANNEL": self.channel_code,
        }
        if values[self.scope_type] is None:
            raise ValueError(f"{self.scope_type} requires its matching target.")
        if any(
            key != self.scope_type and value is not None
            for key, value in values.items()
        ):
            raise ValueError("Exactly one scope target may be supplied.")
        if self.scope_type != "PRODUCT_VARIANT" and self.uom_id is not None:
            raise ValueError("uom_id is allowed only for PRODUCT_VARIANT scope.")
        return self


class OfferProductInput(StrictModel):
    role: ProductRole
    product_variant_id: int = Field(gt=0)
    uom_id: int = Field(gt=0)
    quantity_per_application: Optional[Decimal] = None

    @field_validator("quantity_per_application", mode="before")
    @classmethod
    def normalize_quantity(cls, value: Any) -> Optional[Decimal]:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return _quantity(value, "quantity_per_application")


class DefinitionCreate(StrictModel):
    request_id: UUID
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=2000)

    @field_validator("description", mode="before")
    @classmethod
    def description_value(cls, value: Any):
        return _optional_text(value, "description")

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: Any):
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("Invalid offer code.")
        clean = value.strip().upper()
        if not clean:
            raise ValueError("Offer code is required.")
        return clean

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: Any):
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("Invalid offer name.")
        clean = value.strip()
        if not clean:
            raise ValueError("Offer name is required.")
        return clean


class DefinitionUpdate(StrictModel):
    request_id: UUID
    expected_version: int = Field(gt=0)
    code: Optional[str] = Field(None, min_length=1, max_length=100)
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=2000)

    @field_validator("description", mode="before")
    @classmethod
    def description_value(cls, value: Any):
        return _optional_text(value, "description")

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: Any):
        if value is None:
            return None
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("Invalid offer code.")
        clean = value.strip().upper()
        if not clean:
            raise ValueError("Offer code cannot be blank.")
        return clean

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: Any):
        if value is None:
            return None
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("Invalid offer name.")
        clean = value.strip()
        if not clean:
            raise ValueError("Offer name cannot be blank.")
        return clean

    @model_validator(mode="after")
    def require_change(self):
        if not ({"code", "name", "description"} & self.model_fields_set):
            raise ValueError("At least one definition field must be supplied.")
        return self


class DefinitionDelete(StrictModel):
    request_id: UUID
    expected_version: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def reason_value(cls, value: Any) -> str:
        return _reason(value)


class VersionConfigMixin(StrictModel):
    offer_type: OfferType
    payload: dict[str, Any]
    currency_code: Optional[str] = Field(None, min_length=3, max_length=10)
    priority: int = Field(default=0, ge=0)
    stacking_mode: StackingMode = "EXCLUSIVE"
    effective_from: datetime
    effective_to: Optional[datetime] = None
    scopes: list[OfferScopeInput] = Field(default_factory=list, max_length=500)
    products: list[OfferProductInput] = Field(default_factory=list, max_length=500)

    @field_validator("currency_code", mode="before")
    @classmethod
    def normalize_currency(cls, value: Any):
        if value is None:
            return None
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("Invalid currency code.")
        clean = value.strip().upper()
        if not clean:
            return None
        if not re.fullmatch(r"[A-Z][A-Z0-9]{2,9}", clean):
            raise ValueError("Invalid currency code.")
        return clean

    @model_validator(mode="after")
    def validate_dates(self):
        if self.effective_from.tzinfo is None:
            raise ValueError("effective_from must include a timezone.")
        if self.effective_to is not None:
            if self.effective_to.tzinfo is None:
                raise ValueError("effective_to must include a timezone.")
            if self.effective_to <= self.effective_from:
                raise ValueError("effective_to must be later than effective_from.")
        return self


class VersionCreate(VersionConfigMixin):
    request_id: UUID
    expected_definition_version: int = Field(gt=0)


class VersionUpdate(VersionConfigMixin):
    request_id: UUID
    expected_version: int = Field(gt=0)


class VersionDelete(StrictModel):
    request_id: UUID
    expected_version: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def reason_value(cls, value: Any) -> str:
        return _reason(value)


class VersionCommand(StrictModel):
    request_id: UUID
    expected_version: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def reason_value(cls, value: Any) -> str:
        return _reason(value)


class PreviewComponent(StrictModel):
    uom_id: int = Field(gt=0)
    quantity: Decimal

    @field_validator("quantity", mode="before")
    @classmethod
    def normalize_quantity(cls, value: Any) -> Decimal:
        return _quantity(value, "quantity")


class PreviewLine(StrictModel):
    product_variant_id: int = Field(gt=0)
    components: list[PreviewComponent] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_components(self):
        uoms = [component.uom_id for component in self.components]
        if len(uoms) != len(set(uoms)):
            raise ValueError("A preview line cannot repeat the same UOM.")
        return self


class PreviewRequest(StrictModel):
    customer_id: Optional[int] = Field(None, gt=0)
    branch_id: Optional[int] = Field(None, gt=0)
    channel_code: Optional[str] = Field(None, min_length=1, max_length=50)
    as_of: Optional[datetime] = None
    offer_revision_ceiling: Optional[int] = Field(None, gt=0)
    lines: list[PreviewLine] = Field(min_length=1, max_length=500)

    @field_validator("channel_code", mode="before")
    @classmethod
    def normalize_preview_channel(cls, value: Any):
        if value is None:
            return None
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("Invalid channel_code.")
        clean = value.strip().upper()
        if not clean or not re.fullmatch(r"[A-Z0-9][A-Z0-9_.:-]{0,49}", clean):
            raise ValueError("channel_code must be a stable code.")
        return clean

    @model_validator(mode="after")
    def validate_preview(self):
        if self.as_of is not None and (
            self.as_of.tzinfo is None or self.as_of.utcoffset() is None
        ):
            raise ValueError("as_of must include a timezone.")
        ids = [line.product_variant_id for line in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Preview basket cannot repeat a product variant.")
        return self
