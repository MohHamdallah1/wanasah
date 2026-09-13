from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class OfferCaps(StrictModel):
    max_applications_per_document: Optional[int] = Field(None, gt=0)
    max_discount_amount: Optional[Decimal] = Field(None, gt=0)
    max_reward_quantity: Optional[Decimal] = Field(None, gt=0)


class PercentageDiscountPayload(StrictModel):
    percentage: Decimal = Field(gt=0, le=100)
    caps: Optional[OfferCaps] = None


class FixedDiscountPayload(StrictModel):
    amount: Decimal = Field(gt=0)
    caps: Optional[OfferCaps] = None


class BuyXGetYPayload(StrictModel):
    buy_quantity: Decimal = Field(gt=0)
    get_quantity: Decimal = Field(gt=0)
    caps: Optional[OfferCaps] = None


class FreeGoodsPayload(StrictModel):
    qualifying_quantity: Decimal = Field(gt=0)
    free_quantity: Decimal = Field(gt=0)
    caps: Optional[OfferCaps] = None


class QuantityTier(StrictModel):
    minimum_quantity: Decimal = Field(gt=0)
    reward_type: Literal["PERCENTAGE_DISCOUNT", "FIXED_DISCOUNT", "FREE_QUANTITY"]
    reward_value: Decimal = Field(gt=0)

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
    bundle_quantity: Decimal = Field(default=Decimal("1"), gt=0)
    reward_type: Literal["PERCENTAGE_DISCOUNT", "FIXED_DISCOUNT", "FIXED_PRICE"]
    reward_value: Decimal = Field(gt=0)
    caps: Optional[OfferCaps] = None

    @model_validator(mode="after")
    def validate_percentage(self):
        if self.reward_type == "PERCENTAGE_DISCOUNT" and self.reward_value > 100:
            raise ValueError("Bundle percentage reward cannot exceed 100.")
        return self


class OfferScopeInput(StrictModel):
    scope_type: ScopeType
    product_variant_id: Optional[int] = Field(None, gt=0)
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
        if any(key != self.scope_type and value is not None for key, value in values.items()):
            raise ValueError("Exactly one scope target may be supplied.")
        return self


class OfferProductInput(StrictModel):
    role: ProductRole
    product_variant_id: int = Field(gt=0)


class DefinitionCreate(StrictModel):
    request_id: UUID
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=2000)

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


class VersionCommand(StrictModel):
    request_id: UUID
    expected_version: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=1000)
