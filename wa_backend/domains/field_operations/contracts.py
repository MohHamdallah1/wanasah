"""FIELD read contracts and safe business errors; no inventory/pricing authority."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, field_validator, model_validator

from schemas import RequestModel, PositiveDbInt, NonNegativeDbInt, VisitItemInput


class FieldContractError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 409, context=None):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code
        self.context = context or {}

    def as_detail(self):
        return {"code": self.code, "message": self.message, "context": self.context}


class ReturnResolutionRequest(RequestModel):
    product_variant_id: PositiveDbInt
    quantity: NonNegativeDbInt = 0
    packs_quantity: NonNegativeDbInt = 0
    return_type: Literal["Damaged", "Expired", "Factory_Defect"] = "Damaged"
    lot_number: str | None = Field(default=None, min_length=1, max_length=100)
    production_date: date | None = None
    expiry_date: date | None = None
    delivery_date: date | None = None

    @field_validator("lot_number", mode="before")
    @classmethod
    def normalize_lot(cls, value):
        if value is None:
            return None
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("Invalid printed lot evidence.")
        return value.strip() or None

    @model_validator(mode="after")
    def nonzero(self):
        if self.quantity + self.packs_quantity == 0:
            raise ValueError("A positive returned quantity is required.")
        return self


class InvoicePreviewRequest(RequestModel):
    cart_items: list[VisitItemInput] = Field(min_length=1, max_length=500)
