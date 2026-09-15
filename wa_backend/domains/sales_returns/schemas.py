from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from quantity import parse_quantity


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SalesReturnComponentInput(StrictModel):
    original_price_component_id: int = Field(gt=0)
    quantity: Decimal

    @field_validator("quantity", mode="before")
    @classmethod
    def quantity_value(cls, value: Any) -> Decimal:
        return parse_quantity(value, "quantity")


class SalesReturnCreate(StrictModel):
    request_id: UUID
    original_sales_revision_id: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=1000)
    components: list[SalesReturnComponentInput] = Field(min_length=1, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def reason_value(cls, value: Any) -> str:
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("Invalid reason.")
        clean = value.strip()
        if not 3 <= len(clean) <= 1000:
            raise ValueError("reason must contain 3-1000 non-whitespace characters.")
        return clean

    @model_validator(mode="after")
    def unique_components(self):
        ids = [row.original_price_component_id for row in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate original price component.")
        return self
