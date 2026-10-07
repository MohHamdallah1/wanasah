from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from domains.inventory_costing.service import get_cost_policy, money6
from inventory_access import InventoryAccess
from models import (
    Company,
    Driver,
    InventoryBalance,
    InventoryCostLayer,
    InventoryCostState,
    InventoryLocation,
    ProductBatch,
    ProductVariant,
)
from quantity import canonical_quantity
from services import inventory_business_error


router = APIRouter()
_MAX_PREVIEW_LINES = 5000
_MAX_PREVIEW_LOCATIONS = 100


class WholeProductQualityPreviewLocation(BaseModel):
    location_id: int
    location_name: str
    location_type: Literal["WAREHOUSE", "VEHICLE", "IN_TRANSIT", "SCRAP"]
    quantity: str


class WholeProductQualityPreviewBatch(BaseModel):
    batch_id: int
    batch_number: str
    quantity: str


class WholeProductQualityValuationLine(BaseModel):
    batch_id: int
    batch_number: str
    quantity: str
    unit_cost: str
    book_value: str


class WholeProductQualityPreviewResponse(BaseModel):
    product_variant_id: int
    currency_code: str
    costing_method: Literal["MOVING_AVERAGE", "FIFO"] | None
    valuation_available: bool
    valuation_reason: str | None
    total_quantity: str
    total_book_value: str | None
    locations: list[WholeProductQualityPreviewLocation]
    batches: list[WholeProductQualityPreviewBatch]
    valuation_lines: list[WholeProductQualityValuationLine]
    blocker_codes: list[str]


def _business_detail(code: str, message: str, *, context: dict | None = None):
    return inventory_business_error(code, message, context=context or {})


def _money_text(value: Decimal) -> str:
    return format(money6(value, "preview_value"), "f")


@router.get(
    "/warehouse/quality/products/{product_variant_id}/resolve-preview",
    response_model=WholeProductQualityPreviewResponse,
    status_code=200,
)
async def get_whole_product_quality_preview(
    product_variant_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    company_id = int(current_admin.company_id)
    access = InventoryAccess(db, current_admin)

    variant = (
        await db.execute(
            select(ProductVariant.id, ProductVariant.operational_hold).where(
                ProductVariant.company_id == company_id,
                ProductVariant.id == int(product_variant_id),
            )
        )
    ).one_or_none()
    if variant is None:
        raise HTTPException(status_code=404, detail="المنتج غير موجود أو لا يتبع شركتك.")
    if str(variant.operational_hold or "").upper() != "RECALL":
        raise HTTPException(
            status_code=409,
            detail=_business_detail(
                "PRODUCT_QUALITY_ISSUE_NOT_ACTIVE",
                "لا توجد مشكلة جودة مفتوحة على المنتج بالكامل.",
            ),
        )

    rows = (
        await db.execute(
            select(
                InventoryBalance.location_id,
                InventoryBalance.batch_id,
                InventoryBalance.on_hand_quantity,
                InventoryBalance.reserved_quantity,
                InventoryLocation.name.label("location_name"),
                InventoryLocation.location_type.label("location_type"),
                InventoryLocation.is_active.label("location_active"),
                ProductBatch.batch_number.label("batch_number"),
            )
            .join(
                InventoryLocation,
                and_(
                    InventoryLocation.company_id == InventoryBalance.company_id,
                    InventoryLocation.id == InventoryBalance.location_id,
                ),
            )
            .join(
                ProductBatch,
                and_(
                    ProductBatch.company_id == InventoryBalance.company_id,
                    ProductBatch.product_variant_id == InventoryBalance.product_variant_id,
                    ProductBatch.id == InventoryBalance.batch_id,
                ),
            )
            .where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.product_variant_id == int(product_variant_id),
                InventoryBalance.on_hand_quantity > 0,
            )
            .order_by(
                InventoryBalance.location_id.asc(),
                InventoryBalance.batch_id.asc(),
                InventoryBalance.stock_status.asc(),
            )
            .limit(_MAX_PREVIEW_LINES + 1)
        )
    ).all()
    if len(rows) > _MAX_PREVIEW_LINES:
        raise HTTPException(
            status_code=409,
            detail=_business_detail(
                "WHOLE_PRODUCT_QUALITY_CAPACITY_EXCEEDED",
                "عدد سجلات المخزون المتأثرة أكبر من حد المعالجة الآمنة في عملية واحدة.",
            ),
        )
    if not rows:
        raise HTTPException(
            status_code=409,
            detail=_business_detail(
                "WHOLE_PRODUCT_QUALITY_NO_STOCK",
                "لا توجد كمية حالية لهذا المنتج لمعالجتها.",
            ),
        )

    location_quantities: dict[int, Decimal] = defaultdict(Decimal)
    location_meta: dict[int, tuple[str, str, bool]] = {}
    batch_quantities: dict[int, Decimal] = defaultdict(Decimal)
    batch_numbers: dict[int, str] = {}
    total_quantity = Decimal("0")
    blocker_codes: set[str] = set()

    for row in rows:
        location_id = int(row.location_id)
        batch_id = int(row.batch_id)
        quantity = Decimal(row.on_hand_quantity or 0)
        location_type = str(row.location_type).upper()
        location_meta[location_id] = (
            str(row.location_name),
            location_type,
            bool(row.location_active),
        )
        location_quantities[location_id] += quantity
        batch_quantities[batch_id] += quantity
        batch_numbers[batch_id] = str(row.batch_number)
        total_quantity += quantity
        if location_type != "WAREHOUSE" or not bool(row.location_active):
            blocker_codes.add("WHOLE_PRODUCT_QUALITY_CUSTODY_BLOCKER")
        if Decimal(row.reserved_quantity or 0) > 0:
            blocker_codes.add("WHOLE_PRODUCT_QUALITY_RESERVED_STOCK")

    location_ids = sorted(location_quantities)
    if len(location_ids) > _MAX_PREVIEW_LOCATIONS:
        raise HTTPException(
            status_code=409,
            detail=_business_detail(
                "WHOLE_PRODUCT_QUALITY_LOCATION_CAPACITY_EXCEEDED",
                "عدد المواقع المتأثرة أكبر من حد العملية الواحدة.",
            ),
        )

    codes_by_location = await access.codes_by_location(location_ids)
    unreadable = [
        location_id
        for location_id in location_ids
        if "inventory.read" not in set(codes_by_location.get(location_id, ()))
    ]
    if unreadable:
        raise HTTPException(
            status_code=403,
            detail=_business_detail(
                "WHOLE_PRODUCT_QUALITY_LOCATION_PERMISSION_DENIED",
                "لا تملك صلاحية عرض كل مواقع المنتج المتأثرة.",
            ),
        )

    locations = [
        {
            "location_id": location_id,
            "location_name": location_meta[location_id][0],
            "location_type": location_meta[location_id][1],
            "quantity": canonical_quantity(location_quantities[location_id]),
        }
        for location_id in location_ids
    ]
    batches = [
        {
            "batch_id": batch_id,
            "batch_number": batch_numbers[batch_id],
            "quantity": canonical_quantity(batch_quantities[batch_id]),
        }
        for batch_id in sorted(batch_quantities)
    ]

    company = await db.scalar(select(Company).where(Company.id == company_id))
    currency_code = str(company.currency_code if company is not None else "JOD").upper()
    policy = await get_cost_policy(db, company_id=company_id)
    valuation_available = False
    valuation_reason: str | None = None
    total_book_value: str | None = None
    valuation_lines: list[dict] = []
    costing_method: str | None = None

    if policy is None or not bool(policy.is_active):
        valuation_reason = "COSTING_NOT_ACTIVE"
    else:
        costing_method = str(policy.method).upper()
        state = await db.scalar(
            select(InventoryCostState).where(
                InventoryCostState.company_id == company_id,
                InventoryCostState.product_variant_id == int(product_variant_id),
            )
        )
        if state is None:
            valuation_reason = "COST_STATE_MISSING"
        elif Decimal(state.quantity or 0) != total_quantity:
            valuation_reason = "COST_STATE_QUANTITY_MISMATCH"
        elif costing_method == "MOVING_AVERAGE":
            average_unit_cost = money6(Decimal(state.average_unit_cost or 0), "average_unit_cost")
            for batch_id in sorted(batch_quantities):
                quantity = batch_quantities[batch_id]
                valuation_lines.append({
                    "batch_id": batch_id,
                    "batch_number": batch_numbers[batch_id],
                    "quantity": canonical_quantity(quantity),
                    "unit_cost": _money_text(average_unit_cost),
                    "book_value": _money_text(average_unit_cost * quantity),
                })
            total_book_value = _money_text(Decimal(state.inventory_value or 0))
            valuation_available = True
        elif costing_method == "FIFO":
            layer_rows = (
                await db.execute(
                    select(
                        InventoryCostLayer.batch_id,
                        InventoryCostLayer.remaining_quantity,
                        InventoryCostLayer.remaining_value,
                        ProductBatch.batch_number,
                    )
                    .join(
                        ProductBatch,
                        and_(
                            ProductBatch.company_id == InventoryCostLayer.company_id,
                            ProductBatch.product_variant_id == InventoryCostLayer.product_variant_id,
                            ProductBatch.id == InventoryCostLayer.batch_id,
                        ),
                    )
                    .where(
                        InventoryCostLayer.company_id == company_id,
                        InventoryCostLayer.product_variant_id == int(product_variant_id),
                        InventoryCostLayer.remaining_quantity > 0,
                    )
                    .order_by(InventoryCostLayer.created_at.asc(), InventoryCostLayer.id.asc())
                )
            ).all()
            fifo_quantity = Decimal("0")
            fifo_value = Decimal("0")
            fifo_by_batch: dict[int, tuple[str, Decimal, Decimal]] = {}
            for layer in layer_rows:
                batch_id = int(layer.batch_id)
                quantity = Decimal(layer.remaining_quantity or 0)
                value = Decimal(layer.remaining_value or 0)
                fifo_quantity += quantity
                fifo_value += value
                current = fifo_by_batch.get(batch_id)
                if current is None:
                    fifo_by_batch[batch_id] = (str(layer.batch_number), quantity, value)
                else:
                    fifo_by_batch[batch_id] = (
                        current[0],
                        current[1] + quantity,
                        current[2] + value,
                    )
            if fifo_quantity != total_quantity:
                valuation_reason = "FIFO_LAYER_QUANTITY_MISMATCH"
            elif money6(fifo_value, "fifo_value") != money6(Decimal(state.inventory_value or 0), "state_value"):
                valuation_reason = "FIFO_LAYER_VALUE_MISMATCH"
            else:
                for batch_id, (batch_number, quantity, value) in fifo_by_batch.items():
                    unit_cost = money6(value / quantity, "fifo_weighted_unit_cost")
                    valuation_lines.append({
                        "batch_id": batch_id,
                        "batch_number": batch_number,
                        "quantity": canonical_quantity(quantity),
                        "unit_cost": _money_text(unit_cost),
                        "book_value": _money_text(value),
                    })
                total_book_value = _money_text(Decimal(state.inventory_value or 0))
                valuation_available = True
        else:
            valuation_reason = "COSTING_METHOD_UNSUPPORTED"

    return {
        "product_variant_id": int(product_variant_id),
        "currency_code": currency_code,
        "costing_method": costing_method if costing_method in {"MOVING_AVERAGE", "FIFO"} else None,
        "valuation_available": valuation_available,
        "valuation_reason": valuation_reason,
        "total_quantity": canonical_quantity(total_quantity),
        "total_book_value": total_book_value,
        "locations": locations,
        "batches": batches,
        "valuation_lines": valuation_lines,
        "blocker_codes": sorted(blocker_codes),
    }
