"""Manual Product reference command; receipt selection is deliberately absent."""
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from .values import amount_value, currency_value

READ = "inventory.purchase_cost_reference.read"
MANAGE = "inventory.purchase_cost_reference.manage"
OPERATION = "MANUAL_PRODUCT_SET"
ExactAmount = Annotated[Decimal, BeforeValidator(amount_value)]


class ManualReferenceWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_revision: int = Field(ge=0, strict=True)
    amount: ExactAmount
    purchase_uom_id: int = Field(gt=0, strict=True)
    currency_code: str = Field(min_length=3, max_length=10)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("currency_code", mode="before")
    @classmethod
    def currency(cls, value):
        return currency_value(value)

    @field_validator("reason")
    @classmethod
    def reason_text(cls, value):
        if value is not None and "\x00" in value:
            raise ValueError("Reason contains an invalid character.")
        return value.strip() or None if value is not None else None
