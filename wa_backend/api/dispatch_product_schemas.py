from pydantic import BaseModel
from schemas import RouteLiveInventoryItemResponse


class DispatchProductOptionResponse(BaseModel):
    id: str
    name: str
    load: RouteLiveInventoryItemResponse | None = None


class DispatchProductPageResponse(BaseModel):
    items: list[DispatchProductOptionResponse]
    next_cursor: str | None
    has_more: bool
