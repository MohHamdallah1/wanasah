from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from domains.live_stock_projection.service import (
    LiveStockProjectionError,
    refresh_live_stock_keys,
)
from inventory_access import InventoryAccess
from models import (
    Driver,
    InventoryLocation,
    InventoryStockPolicy,
    ProductLocation,
    ProductUomConversion,
    ProductVariant,
    SystemAuditLog,
)
from quantity import (
    QuantityError,
    canonical_quantity,
    parse_quantity,
    validate_variant_quantity,
)
from services import (
    InventoryMutationError,
    begin_idempotent_operation,
    complete_idempotent_operation,
)


router = APIRouter()


def _error(code: str, message: str, *, context: dict | None = None) -> dict:
    return {
        "code": code,
        "message": message,
        "context": dict(context or {}),
    }


class MinimumStockUpdateRequest(BaseModel):
    """Company-admin command for one warehouse/product minimum-stock threshold."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    location_id: int = Field(gt=0)
    uom_id: int = Field(gt=0)
    minimum_quantity: Decimal
    expected_minimum_quantity: Decimal

    @field_validator("minimum_quantity", "expected_minimum_quantity", mode="before")
    @classmethod
    def exact_quantity_input(cls, value):
        if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
            raise ValueError("Quantity must be sent as an exact decimal value.")
        try:
            parsed = Decimal(str(value))
        except Exception as exc:
            raise ValueError("Quantity is invalid.") from exc
        if not parsed.is_finite() or parsed < 0:
            raise ValueError("Quantity must be finite and non-negative.")
        return parsed


def _request_hash(
    payload: MinimumStockUpdateRequest,
    *,
    product_variant_id: int,
) -> str:
    data = payload.model_dump(mode="json")
    data.pop("request_id", None)
    data["product_variant_id"] = int(product_variant_id)
    encoded = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _display_factor_to_base(
    db: AsyncSession,
    *,
    company_id: int,
    product_variant_id: int,
    base_uom_id: int,
    uom_id: int,
) -> Decimal:
    if int(uom_id) == int(base_uom_id):
        return Decimal("1")

    rows = (
        await db.execute(
            select(ProductUomConversion).where(
                ProductUomConversion.company_id == int(company_id),
                ProductUomConversion.product_variant_id == int(product_variant_id),
                ProductUomConversion.from_uom_id == int(uom_id),
                ProductUomConversion.to_uom_id == int(base_uom_id),
            ).limit(2)
        )
    ).scalars().all()

    if len(rows) != 1:
        raise HTTPException(
            status_code=422,
            detail=_error(
                "STOCK_MINIMUM_UOM_UNSUPPORTED",
                "وحدة الحد الأدنى لا تملك تحويلاً وحيداً ودقيقاً إلى وحدة أساس المنتج.",
                context={
                    "product_variant_id": int(product_variant_id),
                    "uom_id": int(uom_id),
                },
            ),
        )

    numerator = Decimal(rows[0].numerator)
    denominator = Decimal(rows[0].denominator)
    if numerator <= 0 or denominator <= 0:
        raise HTTPException(
            status_code=409,
            detail=_error(
                "STOCK_MINIMUM_UOM_INVALID",
                "تحويل وحدة الحد الأدنى غير صالح.",
                context={
                    "product_variant_id": int(product_variant_id),
                    "uom_id": int(uom_id),
                },
            ),
        )
    return numerator / denominator


@router.put(
    "/warehouse/inventory/{product_variant_id}/minimum-stock",
    status_code=200,
)
async def update_minimum_stock(
    product_variant_id: int,
    payload: MinimumStockUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    """Set the company-owned minimum stock threshold for one product/warehouse.

    InventoryStockPolicy stores the authoritative threshold in base quantity.
    The caller may enter the value in the Live Stock display UOM; the server
    resolves and validates the exact conversion before changing the policy.
    """

    if product_variant_id <= 0:
        raise HTTPException(
            status_code=422,
            detail=_error("STOCK_MINIMUM_PRODUCT_INVALID", "معرّف المنتج غير صالح."),
        )

    if not bool(current_admin.is_admin):
        raise HTTPException(
            status_code=403,
            detail=_error(
                "STOCK_MINIMUM_ADMIN_REQUIRED",
                "تعديل الحد الأدنى للمخزون متاح لمسؤول الشركة فقط.",
            ),
        )

    company_id = int(current_admin.company_id)
    access = InventoryAccess(db, current_admin)
    await access.require("inventory.read", int(payload.location_id))

    try:
        request_hash = _request_hash(
            payload,
            product_variant_id=int(product_variant_id),
        )
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=int(current_admin.id),
            operation="LIVE_STOCK_MINIMUM_UPDATE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        location = (
            await db.execute(
                select(InventoryLocation).where(
                    InventoryLocation.company_id == company_id,
                    InventoryLocation.id == int(payload.location_id),
                    InventoryLocation.location_type == "WAREHOUSE",
                    InventoryLocation.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if location is None:
            raise HTTPException(
                status_code=404,
                detail=_error(
                    "STOCK_MINIMUM_LOCATION_NOT_FOUND",
                    "المستودع المحدد غير موجود أو غير فعال.",
                ),
            )

        variant = (
            await db.execute(
                select(ProductVariant).where(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id == int(product_variant_id),
                )
            )
        ).scalar_one_or_none()
        if variant is None:
            raise HTTPException(
                status_code=404,
                detail=_error(
                    "STOCK_MINIMUM_PRODUCT_NOT_FOUND",
                    "المنتج المحدد غير موجود ضمن هذه الشركة.",
                ),
            )

        product_location_exists = await db.scalar(
            select(ProductLocation.id).where(
                ProductLocation.company_id == company_id,
                ProductLocation.location_id == int(payload.location_id),
                ProductLocation.product_variant_id == int(product_variant_id),
            ).limit(1)
        )
        if product_location_exists is None:
            raise HTTPException(
                status_code=409,
                detail=_error(
                    "STOCK_MINIMUM_PRODUCT_LOCATION_REQUIRED",
                    "اربط المنتج بالمستودع قبل تحديد الحد الأدنى له.",
                ),
            )

        factor = await _display_factor_to_base(
            db,
            company_id=company_id,
            product_variant_id=int(product_variant_id),
            base_uom_id=int(variant.base_uom_id),
            uom_id=int(payload.uom_id),
        )

        entered_quantity = parse_quantity(
            payload.minimum_quantity,
            "minimum_quantity",
            allow_zero=True,
        )
        new_minimum = validate_variant_quantity(
            entered_quantity * factor,
            quantity_scale=int(variant.quantity_scale),
            quantity_step=variant.quantity_step,
            field_name="minimum_quantity",
            allow_zero=True,
        )
        expected_minimum = validate_variant_quantity(
            payload.expected_minimum_quantity,
            quantity_scale=int(variant.quantity_scale),
            quantity_step=variant.quantity_step,
            field_name="expected_minimum_quantity",
            allow_zero=True,
        )

        # Serialize the create/update path as the policy row may not exist yet.
        await db.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended(:lock_key, 0)"
                ")"
            ),
            {
                "lock_key": (
                    f"live-stock-minimum:{company_id}:"
                    f"{int(payload.location_id)}:{int(product_variant_id)}"
                )
            },
        )

        policy = (
            await db.execute(
                select(InventoryStockPolicy)
                .where(
                    InventoryStockPolicy.company_id == company_id,
                    InventoryStockPolicy.location_id == int(payload.location_id),
                    InventoryStockPolicy.product_variant_id == int(product_variant_id),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

        current_minimum = (
            Decimal(policy.minimum_quantity)
            if policy is not None
            else Decimal("0")
        )
        if current_minimum != expected_minimum:
            raise HTTPException(
                status_code=409,
                detail=_error(
                    "STOCK_MINIMUM_VERSION_CONFLICT",
                    "تغير الحد الأدنى منذ فتح الصفحة. حدّث الرصيد ثم أعد المحاولة.",
                    context={
                        "current_minimum_quantity": canonical_quantity(current_minimum),
                    },
                ),
            )

        if policy is not None and not bool(policy.is_active):
            raise HTTPException(
                status_code=409,
                detail=_error(
                    "STOCK_MINIMUM_POLICY_INACTIVE",
                    "سياسة هذا المنتج غير فعالة حالياً وتحتاج إدارة السياسة قبل تعديل الحد الأدنى.",
                ),
            )

        if (
            policy is not None
            and policy.target_quantity is not None
            and new_minimum > Decimal(policy.target_quantity)
        ):
            raise HTTPException(
                status_code=409,
                detail=_error(
                    "STOCK_MINIMUM_EXCEEDS_TARGET",
                    "الحد الأدنى لا يجوز أن يتجاوز الكمية المستهدفة الحالية.",
                    context={
                        "target_quantity": canonical_quantity(policy.target_quantity),
                    },
                ),
            )

        changed = current_minimum != new_minimum
        if policy is None and new_minimum > 0:
            policy = InventoryStockPolicy(
                company_id=company_id,
                location_id=int(payload.location_id),
                product_variant_id=int(product_variant_id),
                minimum_quantity=new_minimum,
                target_quantity=None,
                minimum_remaining_shelf_life_days=0,
                is_active=True,
            )
            db.add(policy)
        elif policy is not None and changed:
            policy.minimum_quantity = new_minimum

        if changed:
            db.add(
                SystemAuditLog(
                    company_id=company_id,
                    admin_id=int(current_admin.id),
                    target_id=(
                        f"InventoryStockPolicy_{int(payload.location_id)}_"
                        f"{int(product_variant_id)}"
                    ),
                    action_type="LIVE_STOCK_MINIMUM_UPDATED",
                    old_value=canonical_quantity(current_minimum),
                    new_value=canonical_quantity(new_minimum),
                )
            )
            await db.flush()
            await refresh_live_stock_keys(
                db,
                company_id=company_id,
                keys=[
                    (
                        int(payload.location_id),
                        int(product_variant_id),
                    )
                ],
            )

        response_payload = {
            "location_id": int(payload.location_id),
            "product_variant_id": int(product_variant_id),
            "minimum_quantity": canonical_quantity(new_minimum),
            "entered_quantity": canonical_quantity(entered_quantity),
            "uom_id": int(payload.uom_id),
            "changed": bool(changed),
        }
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except QuantityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=422,
            detail=_error(
                "STOCK_MINIMUM_QUANTITY_INVALID",
                str(exc),
            ),
        ) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=_error(
                "STOCK_MINIMUM_IDEMPOTENCY_CONFLICT",
                str(exc),
            ),
        ) from exc
    except LiveStockProjectionError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=503,
            detail=_error(
                "LIVE_STOCK_PROJECTION_UNAVAILABLE",
                "تعذر تحديث حالة الرصيد الحي بأمان.",
            ),
        ) from exc
