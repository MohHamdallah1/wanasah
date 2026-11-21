from pydantic import BaseModel, Field, model_serializer
from schemas import RouteLiveInventoryItemResponse


class DispatchProductOptionResponse(BaseModel):
    id: str
    name: str
    load: RouteLiveInventoryItemResponse | None = None
    base_uom_code: str | None = Field(
        default=None,
        description="Canonical stock UOM code for SHORTAGE demand quantity; not the display/outer packaging UOM.",
    )

    @model_serializer(mode="wrap")
    def serialize_optional_base_uom(self, handler):
        # LOAD retains its pre-existing JSON shape; SHORTAGE adds only the
        # authoritative SKU base UOM, without changing its existing load=null.
        payload = handler(self)
        if self.base_uom_code is None:
            payload.pop("base_uom_code", None)
        return payload


class DispatchProductPageResponse(BaseModel):
    items: list[DispatchProductOptionResponse]
    next_cursor: str | None
    has_more: bool
