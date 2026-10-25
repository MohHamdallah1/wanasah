from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas import PositiveQuantity


class VehicleLoadStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VehicleLoadItemResponse(VehicleLoadStrictModel):
    product_variant_id: int = Field(gt=0)
    product_name: str
    sku: str | None = None
    base_uom_id: int = Field(gt=0)
    base_uom_code: str
    base_uom_name: str
    quantity_scale: int = Field(ge=0, le=6)
    quantity_step: PositiveQuantity
    stock_status: Literal[
        "AVAILABLE",
        "QUARANTINED",
        "BLOCKED",
        "RECALLED",
        "DAMAGED",
        "DISPOSAL_PENDING",
    ]
    on_hand_quantity: str
    reserved_quantity: str
    available_quantity: str


class VehicleLoadSnapshotResponse(VehicleLoadStrictModel):
    vehicle_id: int = Field(gt=0)
    mode: Literal["DIRECT", "ROUTE", "SETTLEMENT_REQUIRED"]
    route_id: int | None = Field(default=None, gt=0)
    work_session_id: int | None = Field(default=None, gt=0)
    vehicle_operational: bool
    can_add: bool
    can_unload: bool
    items: list[VehicleLoadItemResponse]


class VehicleLoadWarehouseItem(VehicleLoadStrictModel):
    id: int = Field(gt=0)
    name: str
    code: str


class VehicleLoadWarehousePage(VehicleLoadStrictModel):
    items: list[VehicleLoadWarehouseItem]
    next_cursor: str | None = None
    has_more: bool


class VehicleLoadSourceItem(VehicleLoadStrictModel):
    product_variant_id: int = Field(gt=0)
    product_name: str
    sku: str | None = None
    base_uom_id: int = Field(gt=0)
    base_uom_code: str
    base_uom_name: str
    quantity_scale: int = Field(ge=0, le=6)
    quantity_step: PositiveQuantity
    available_quantity: str


class VehicleLoadSourcePage(VehicleLoadStrictModel):
    items: list[VehicleLoadSourceItem]
    next_cursor: str | None = None
    has_more: bool


class VehicleLoadMutationItem(VehicleLoadStrictModel):
    product_variant_id: int = Field(gt=0)
    quantity: PositiveQuantity
    stock_status: Literal[
        "AVAILABLE",
        "QUARANTINED",
        "BLOCKED",
        "RECALLED",
        "DAMAGED",
        "DISPOSAL_PENDING",
    ] | None = None


class VehicleLoadMutationRequest(VehicleLoadStrictModel):
    request_id: UUID
    warehouse_id: int = Field(gt=0)
    items: list[VehicleLoadMutationItem] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def reject_duplicates(self):
        keys = [
            (item.product_variant_id, item.stock_status or "AVAILABLE")
            for item in self.items
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("لا يجوز تكرار نفس الصنف وحالة المخزون.")
        return self


class VehicleLoadMutationResponse(VehicleLoadStrictModel):
    vehicle_id: int = Field(gt=0)
    warehouse_id: int = Field(gt=0)
    direction: Literal["ADD", "UNLOAD"]
    movement_count: int = Field(gt=0)
    message: str


__all__ = [
    "VehicleLoadItemResponse",
    "VehicleLoadMutationRequest",
    "VehicleLoadMutationResponse",
    "VehicleLoadSnapshotResponse",
    "VehicleLoadSourcePage",
    "VehicleLoadWarehousePage",
]
