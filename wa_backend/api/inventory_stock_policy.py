from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, func, select, text
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
    Product,
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



class BulkMinimumStockBase(BaseModel):
    """Bulk minimum-stock command scoped to one warehouse."""

    model_config = ConfigDict(extra="forbid")

    location_id: int = Field(gt=0)
    scope: Literal["ALL", "FAMILY", "PRODUCT"]
    family_id: int | None = Field(default=None, gt=0)
    product_variant_id: int | None = Field(default=None, gt=0)
    minimum_quantity: Decimal
    apply_mode: Literal["ONLY_UNSET", "OVERWRITE"] = "ONLY_UNSET"

    @field_validator("minimum_quantity", mode="before")
    @classmethod
    def exact_bulk_quantity_input(cls, value):
        if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
            raise ValueError("Quantity must be sent as an exact decimal value.")
        try:
            parsed = Decimal(str(value))
        except Exception as exc:
            raise ValueError("Quantity is invalid.") from exc
        if not parsed.is_finite() or parsed < 0:
            raise ValueError("Quantity must be finite and non-negative.")
        return parsed

    def validate_scope(self) -> None:
        if self.scope == "ALL":
            if self.family_id is not None or self.product_variant_id is not None:
                raise HTTPException(
                    status_code=422,
                    detail=_error(
                        "STOCK_MINIMUM_SCOPE_INVALID",
                        "نطاق كل المنتجات لا يقبل عائلة أو منتجاً محدداً.",
                    ),
                )
        elif self.scope == "FAMILY":
            if self.family_id is None or self.product_variant_id is not None:
                raise HTTPException(
                    status_code=422,
                    detail=_error(
                        "STOCK_MINIMUM_SCOPE_INVALID",
                        "اختر عائلة واحدة لتطبيق الحد الأدنى عليها.",
                    ),
                )
        elif self.scope == "PRODUCT":
            if self.product_variant_id is None or self.family_id is not None:
                raise HTTPException(
                    status_code=422,
                    detail=_error(
                        "STOCK_MINIMUM_SCOPE_INVALID",
                        "اختر منتجاً واحداً لتطبيق الحد الأدنى عليه.",
                    ),
                )


class BulkMinimumStockApplyRequest(BulkMinimumStockBase):
    request_id: UUID


def _bulk_request_hash(payload: BulkMinimumStockApplyRequest) -> str:
    data = payload.model_dump(mode="json")
    data.pop("request_id", None)
    encoded = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _require_bulk_admin(
    db: AsyncSession,
    *,
    current_admin: Driver,
    location_id: int,
) -> int:
    if not bool(current_admin.is_admin):
        raise HTTPException(
            status_code=403,
            detail=_error(
                "STOCK_MINIMUM_ADMIN_REQUIRED",
                "إدارة الحد الأدنى للمخزون متاحة لمسؤول الشركة فقط.",
            ),
        )

    company_id = int(current_admin.company_id)
    access = InventoryAccess(db, current_admin)
    await access.require("inventory.read", int(location_id))

    location = (
        await db.execute(
            select(InventoryLocation.id).where(
                InventoryLocation.company_id == company_id,
                InventoryLocation.id == int(location_id),
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
    return company_id


async def _load_bulk_minimum_candidates(
    db: AsyncSession,
    *,
    company_id: int,
    payload: BulkMinimumStockBase,
):
    conversion = ProductUomConversion

    stmt = (
        select(
            ProductVariant.id.label("variant_id"),
            ProductVariant.base_uom_id.label("base_uom_id"),
            ProductVariant.quantity_scale.label("quantity_scale"),
            ProductVariant.quantity_step.label("quantity_step"),
            ProductVariant.product_id.label("family_id"),
            func.count(conversion.id).label("display_candidate_count"),
            func.min(conversion.from_uom_id).label("display_uom_id"),
            func.min(conversion.numerator / conversion.denominator).label(
                "display_factor_to_base"
            ),
        )
        .select_from(ProductLocation)
        .join(
            ProductVariant,
            and_(
                ProductVariant.company_id == ProductLocation.company_id,
                ProductVariant.id == ProductLocation.product_variant_id,
            ),
        )
        .join(
            Product,
            and_(
                Product.company_id == ProductVariant.company_id,
                Product.id == ProductVariant.product_id,
            ),
        )
        .outerjoin(
            conversion,
            and_(
                conversion.company_id == ProductVariant.company_id,
                conversion.product_variant_id == ProductVariant.id,
                conversion.to_uom_id == ProductVariant.base_uom_id,
                conversion.numerator > conversion.denominator,
            ),
        )
        .where(
            ProductLocation.company_id == company_id,
            ProductLocation.location_id == int(payload.location_id),
            ProductVariant.lifecycle_status == "ACTIVE",
        )
        .group_by(
            ProductVariant.id,
            ProductVariant.base_uom_id,
            ProductVariant.quantity_scale,
            ProductVariant.quantity_step,
            ProductVariant.product_id,
        )
        .order_by(ProductVariant.id.asc())
    )

    if payload.scope == "FAMILY":
        stmt = stmt.where(ProductVariant.product_id == int(payload.family_id))
    elif payload.scope == "PRODUCT":
        stmt = stmt.where(ProductVariant.id == int(payload.product_variant_id))

    return (await db.execute(stmt)).mappings().all()


async def _plan_bulk_minimum(
    db: AsyncSession,
    *,
    company_id: int,
    payload: BulkMinimumStockBase,
    lock_policies: bool,
) -> dict:
    payload.validate_scope()
    candidates = await _load_bulk_minimum_candidates(
        db,
        company_id=company_id,
        payload=payload,
    )

    variant_ids = [int(row["variant_id"]) for row in candidates]
    if lock_policies and variant_ids:
        lock_keys = [
            (
                f"live-stock-minimum:{company_id}:"
                f"{int(payload.location_id)}:{variant_id}"
            )
            for variant_id in variant_ids
        ]
        await db.execute(
            text(
                """
                SELECT pg_advisory_xact_lock(hashtextextended(lock_key, 0))
                FROM unnest(CAST(:lock_keys AS text[])) AS t(lock_key)
                ORDER BY lock_key
                """
            ),
            {"lock_keys": lock_keys},
        )

    policy_stmt = select(InventoryStockPolicy).where(
        InventoryStockPolicy.company_id == company_id,
        InventoryStockPolicy.location_id == int(payload.location_id),
        InventoryStockPolicy.product_variant_id.in_(variant_ids or [-1]),
    )
    if lock_policies:
        policy_stmt = policy_stmt.with_for_update()

    policies = {
        int(policy.product_variant_id): policy
        for policy in (await db.execute(policy_stmt)).scalars().all()
    }

    entered_quantity = parse_quantity(
        payload.minimum_quantity,
        "minimum_quantity",
        allow_zero=True,
    )

    updates: list[dict] = []
    skipped_existing = 0
    inactive_conflicts: list[int] = []
    target_conflicts: list[int] = []
    invalid_quantity: list[int] = []

    for row in candidates:
        variant_id = int(row["variant_id"])
        policy = policies.get(variant_id)
        current_minimum = (
            Decimal(policy.minimum_quantity) if policy is not None else Decimal("0")
        )

        if payload.apply_mode == "ONLY_UNSET" and current_minimum > 0:
            skipped_existing += 1
            continue

        if policy is not None and not bool(policy.is_active):
            inactive_conflicts.append(variant_id)
            continue

        factor = Decimal("1")
        display_uom_id = int(row["base_uom_id"])
        if int(row["display_candidate_count"] or 0) == 1:
            raw_factor = row["display_factor_to_base"]
            raw_uom_id = row["display_uom_id"]
            if raw_factor is not None and raw_uom_id is not None:
                factor = Decimal(raw_factor)
                display_uom_id = int(raw_uom_id)

        try:
            new_minimum = validate_variant_quantity(
                entered_quantity * factor,
                quantity_scale=int(row["quantity_scale"]),
                quantity_step=row["quantity_step"],
                field_name="minimum_quantity",
                allow_zero=True,
            )
        except QuantityError:
            invalid_quantity.append(variant_id)
            continue

        if (
            policy is not None
            and policy.target_quantity is not None
            and new_minimum > Decimal(policy.target_quantity)
        ):
            target_conflicts.append(variant_id)
            continue

        if current_minimum == new_minimum:
            continue

        updates.append(
            {
                "variant_id": variant_id,
                "policy": policy,
                "old_minimum": current_minimum,
                "new_minimum": new_minimum,
                "display_uom_id": display_uom_id,
            }
        )

    return {
        "candidates": candidates,
        "updates": updates,
        "entered_quantity": entered_quantity,
        "matched_count": len(candidates),
        "affected_count": len(updates),
        "skipped_existing_count": skipped_existing,
        "inactive_conflicts": inactive_conflicts,
        "target_conflicts": target_conflicts,
        "invalid_quantity": invalid_quantity,
    }


def _bulk_plan_response(payload: BulkMinimumStockBase, plan: dict) -> dict:
    return {
        "location_id": int(payload.location_id),
        "scope": payload.scope,
        "family_id": payload.family_id,
        "product_variant_id": payload.product_variant_id,
        "minimum_quantity": canonical_quantity(plan["entered_quantity"]),
        "unit_mode": "DISPLAY_UOM_PER_PRODUCT",
        "apply_mode": payload.apply_mode,
        "matched_count": int(plan["matched_count"]),
        "affected_count": int(plan["affected_count"]),
        "skipped_existing_count": int(plan["skipped_existing_count"]),
        "inactive_conflict_count": len(plan["inactive_conflicts"]),
        "target_conflict_count": len(plan["target_conflicts"]),
        "invalid_quantity_count": len(plan["invalid_quantity"]),
        "conflict_samples": {
            "inactive": plan["inactive_conflicts"][:10],
            "target": plan["target_conflicts"][:10],
            "invalid_quantity": plan["invalid_quantity"][:10],
        },
    }


@router.post(
    "/warehouse/inventory/minimum-stock/bulk/preview",
    status_code=200,
)
async def preview_bulk_minimum_stock(
    payload: BulkMinimumStockBase,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    company_id = await _require_bulk_admin(
        db,
        current_admin=current_admin,
        location_id=int(payload.location_id),
    )
    try:
        plan = await _plan_bulk_minimum(
            db,
            company_id=company_id,
            payload=payload,
            lock_policies=False,
        )
        return _bulk_plan_response(payload, plan)
    except HTTPException:
        raise
    except QuantityError as exc:
        raise HTTPException(
            status_code=422,
            detail=_error("STOCK_MINIMUM_QUANTITY_INVALID", str(exc)),
        ) from exc


@router.put(
    "/warehouse/inventory/minimum-stock/bulk",
    status_code=200,
)
async def apply_bulk_minimum_stock(
    payload: BulkMinimumStockApplyRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    company_id = await _require_bulk_admin(
        db,
        current_admin=current_admin,
        location_id=int(payload.location_id),
    )

    try:
        request_hash = _bulk_request_hash(payload)
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=int(current_admin.id),
            operation="LIVE_STOCK_MINIMUM_BULK_UPDATE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        plan = await _plan_bulk_minimum(
            db,
            company_id=company_id,
            payload=payload,
            lock_policies=True,
        )

        if (
            plan["inactive_conflicts"]
            or plan["target_conflicts"]
            or plan["invalid_quantity"]
        ):
            response = _bulk_plan_response(payload, plan)
            raise HTTPException(
                status_code=409,
                detail=_error(
                    "STOCK_MINIMUM_BULK_CONFLICT",
                    "تعذر تطبيق الحد الأدنى على كامل النطاق بأمان. راجع التعارضات أولاً.",
                    context=response,
                ),
            )

        keys: list[tuple[int, int]] = []
        for item in plan["updates"]:
            variant_id = int(item["variant_id"])
            policy = item["policy"]
            new_minimum = item["new_minimum"]
            old_minimum = item["old_minimum"]

            if policy is None:
                policy = InventoryStockPolicy(
                    company_id=company_id,
                    location_id=int(payload.location_id),
                    product_variant_id=variant_id,
                    minimum_quantity=new_minimum,
                    target_quantity=None,
                    minimum_remaining_shelf_life_days=0,
                    is_active=True,
                )
                db.add(policy)
            else:
                policy.minimum_quantity = new_minimum

            db.add(
                SystemAuditLog(
                    company_id=company_id,
                    admin_id=int(current_admin.id),
                    target_id=(
                        f"InventoryStockPolicy_{int(payload.location_id)}_{variant_id}"
                    ),
                    action_type="LIVE_STOCK_MINIMUM_BULK_UPDATED",
                    old_value=canonical_quantity(old_minimum),
                    new_value=canonical_quantity(new_minimum),
                )
            )
            keys.append((int(payload.location_id), variant_id))

        await db.flush()

        for offset in range(0, len(keys), 5000):
            await refresh_live_stock_keys(
                db,
                company_id=company_id,
                keys=keys[offset : offset + 5000],
            )

        response_payload = _bulk_plan_response(payload, plan)
        response_payload["changed"] = bool(keys)
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
            detail=_error("STOCK_MINIMUM_QUANTITY_INVALID", str(exc)),
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

        if policy is not None and not bool(policy.is_active):
            raise HTTPException(
                status_code=409,
                detail=_error(
                    "STOCK_MINIMUM_POLICY_INACTIVE",
                    "سياسة هذا المنتج غير فعالة حالياً وتحتاج إدارة السياسة قبل تعديل الحد الأدنى.",
                ),
            )

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
