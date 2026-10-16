from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
)
from database import get_db
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from domains.inventory_stock_policy import (
    InventoryStockPolicyReadNotFound,
    read_effective_shelf_life_policy,
)


router = APIRouter()


class EffectiveShelfLifePolicyResponse(BaseModel):
    location_id: int = Field(..., gt=0)
    product_variant_id: int = Field(..., gt=0)
    minimum_remaining_shelf_life_days: int = Field(..., ge=0)
    requirement_applies: bool
    source: Literal["EXACT_ACTIVE_POLICY", "NO_ACTIVE_POLICY"]
    management_mode: Literal["READ_ONLY_V1"] = "READ_ONLY_V1"


@router.get(
    "/warehouse/inventory/stock-policy/effective",
    response_model=EffectiveShelfLifePolicyResponse,
    status_code=200,
)
async def get_effective_shelf_life_policy(
    location_id: int = Query(..., gt=0),
    product_variant_id: int = Query(..., gt=0),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(
        get_current_backoffice_capability_access
    ),
):
    """Explain the effective shelf-life cutoff; never mutate or re-evaluate sellability."""

    try:
        await access.require("inventory.read", location_id=int(location_id))
    except BackofficeCapabilityAccessRejected:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "STOCK_POLICY_READ_FORBIDDEN",
                "message": "Inventory policy read is not allowed at the selected warehouse.",
                "context": {},
            },
        ) from None

    try:
        effective = await read_effective_shelf_life_policy(
            db,
            company_id=int(access.company_id),
            location_id=int(location_id),
            product_variant_id=int(product_variant_id),
        )
    except InventoryStockPolicyReadNotFound:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "STOCK_POLICY_SCOPE_NOT_FOUND",
                "message": "The selected warehouse/product assignment is unavailable.",
                "context": {},
            },
        ) from None

    return EffectiveShelfLifePolicyResponse(
        location_id=effective.location_id,
        product_variant_id=effective.product_variant_id,
        minimum_remaining_shelf_life_days=(
            effective.minimum_remaining_shelf_life_days
        ),
        requirement_applies=effective.requirement_applies,
        source=effective.source,
    )
