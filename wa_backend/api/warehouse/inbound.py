from decimal import Decimal
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from inventory_access import InventoryAccess
from models import Company, Driver, ProductLocation, ProductUomConversion, ProductVariant, UOM
from quantity import canonical_quantity
from schemas import InboundOptionsRequest, InventoryCostPolicyUpdateRequest
from services import (
    InventoryMutationError,
    begin_idempotent_operation,
    complete_idempotent_operation,
    inventory_business_error,
    warehouse_setup_required_detail,
)
from domains.inventory_costing.service import (
    CostingError,
    cost_policy_payload,
    set_cost_policy,
)
from product_lifecycle import (
    DEFAULT_PRODUCT_LOCATION_FLAGS,
    record_domain_event,
)

# Staging-only dependency: remains sourced from the untouched monolith until
# _stable_request_hash is moved once to _shared.py in its dedicated stage.
from api.warehouse import _stable_request_hash


router = APIRouter()


# ====================================================
# 1. استلام بضاعة من المورد (Inbound) - المحرك الموحد
# ====================================================
# ====================================================
# 1.1 التحقق من وجود مستودع فعال قبل تنفيذ التوريد
# ====================================================
async def _require_active_warehouse_setup(
    db: AsyncSession,
    company_id: int,
) -> None:
    active_id = (
        await db.execute(
            select(InventoryLocation.id).filter(
                InventoryLocation.company_id == company_id,
                InventoryLocation.location_type == 'WAREHOUSE',
                InventoryLocation.is_active.is_(True),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if active_id is None:
        raise HTTPException(status_code=409, detail=warehouse_setup_required_detail())


# ====================================================
# 1.2 تحميل وحدات القياس والتحويلات المسموحة للتوريد
# ====================================================
async def _resolve_inbound_uom_options(
    db: AsyncSession,
    *,
    company_id: int,
    variant_ids: list[int],
) -> tuple[dict[int, int], dict[tuple[int, int], Decimal], dict[int, UOM]]:
    ids = sorted({int(value) for value in variant_ids})
    if not ids:
        return {}, {}, {}

    variant_rows = (
        await db.execute(
            select(ProductVariant.id, ProductVariant.base_uom_id).filter(
                ProductVariant.company_id == company_id,
                ProductVariant.id.in_(ids),
                ProductVariant.lifecycle_status == "ACTIVE",
            )
        )
    ).all()
    base_by_variant = {
        int(row.id): int(row.base_uom_id)
        for row in variant_rows
    }
    if set(base_by_variant) != set(ids):
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "INBOUND_VARIANT_UNAVAILABLE",
                "One or more products are not active or do not belong to the company.",
            ),
        )

    conversion_rows = (
        await db.execute(
            select(ProductUomConversion).filter(
                ProductUomConversion.company_id == company_id,
                ProductUomConversion.product_variant_id.in_(ids),
            )
        )
    ).scalars().all()

    factors: dict[tuple[int, int], Decimal] = {
        (variant_id, base_uom_id): Decimal("1")
        for variant_id, base_uom_id in base_by_variant.items()
    }
    uom_ids = set(base_by_variant.values())
    for conversion in conversion_rows:
        variant_id = int(conversion.product_variant_id)
        base_uom_id = base_by_variant[variant_id]
        numerator = Decimal(conversion.numerator)
        denominator = Decimal(conversion.denominator)
        if numerator <= 0 or denominator <= 0:
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "INBOUND_UOM_CONVERSION_INVALID",
                    "A product unit conversion is invalid.",
                    context={"product_variant_id": variant_id},
                ),
            )

        candidate_uom_id = None
        factor = None
        if int(conversion.to_uom_id) == base_uom_id:
            candidate_uom_id = int(conversion.from_uom_id)
            factor = numerator / denominator
        elif int(conversion.from_uom_id) == base_uom_id:
            candidate_uom_id = int(conversion.to_uom_id)
            factor = denominator / numerator
        if candidate_uom_id is None or factor is None:
            continue

        key = (variant_id, candidate_uom_id)
        existing = factors.get(key)
        if existing is not None and existing != factor:
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "INBOUND_UOM_CONVERSION_CONFLICT",
                    "Conflicting direct unit conversions were found for a product.",
                    context={
                        "product_variant_id": variant_id,
                        "uom_id": candidate_uom_id,
                    },
                ),
            )
        factors[key] = factor
        uom_ids.add(candidate_uom_id)

    uoms = list(
        (
            await db.scalars(
                select(UOM).where(UOM.id.in_(sorted(uom_ids))).order_by(UOM.id.asc())
            )
        ).all()
    )
    uom_map = {int(row.id): row for row in uoms}
    if set(uom_map) != uom_ids:
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "INBOUND_UOM_REFERENCE_MISSING",
                "A unit reference required by the product is missing.",
            ),
        )
    return base_by_variant, factors, uom_map


# ====================================================
# 1.3 إنشاء ربط المنتج بالمستودع عند أول توريد فقط عند الحاجة
# ====================================================
async def _ensure_first_inbound_product_locations(
    db: AsyncSession,
    *,
    company_id: int,
    location_id: int,
    variant_ids,
    actor_id: int,
    request_id: uuid.UUID,
) -> set[int]:
    """Create only missing product/location assignments for the selected inbound warehouse.

    The caller must already have validated exact-warehouse inbound permission and
    company-scoped product lifecycle eligibility. Existing assignments are never
    overwritten, so explicit inbound/outbound flags remain authoritative.
    """
    normalized_ids = sorted({int(value) for value in variant_ids})
    if not normalized_ids:
        return set()

    rows = [
        {
            "company_id": int(company_id),
            "location_id": int(location_id),
            "product_variant_id": int(variant_id),
            "operational_flags": dict(DEFAULT_PRODUCT_LOCATION_FLAGS),
            "created_by": int(actor_id),
        }
        for variant_id in normalized_ids
    ]
    created_rows = list(
        (
            await db.execute(
                pg_insert(ProductLocation)
                .values(rows)
                .on_conflict_do_nothing(
                    constraint="uq_product_location_assignment"
                )
                .returning(
                    ProductLocation.id,
                    ProductLocation.product_variant_id,
                )
            )
        ).all()
    )

    for product_location_id, product_variant_id in created_rows:
        snapshot = {
            "id": int(product_location_id),
            "company_id": int(company_id),
            "location_id": int(location_id),
            "product_variant_id": int(product_variant_id),
            "operational_flags": dict(DEFAULT_PRODUCT_LOCATION_FLAGS),
            "version": 1,
            "created_by": int(actor_id),
        }
        record_domain_event(
            db,
            company_id=int(company_id),
            actor_id=int(actor_id),
            request_id=request_id,
            event_type="ProductLocationAssigned",
            entity_type="ProductLocation",
            entity_id=int(product_location_id),
            reason="AUTO_FIRST_INBOUND",
            before=None,
            after=snapshot,
        )

    return {
        int(product_variant_id)
        for _, product_variant_id in created_rows
    }



# ====================================================
# 1.4 جلب خيارات وحدات القياس والعملات اللازمة لنموذج التوريد
# ====================================================
@router.post("/warehouse/inbound/options", status_code=200)
async def warehouse_inbound_options(
    payload: InboundOptionsRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('inbound.create', any_location=True)
    company_id = current_admin.company_id

    base_by_variant, factors, uom_map = await _resolve_inbound_uom_options(
        db,
        company_id=company_id,
        variant_ids=payload.ids,
    )
    company = await db.scalar(
        select(Company).where(Company.id == company_id)
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Company was not found.")

    items = []
    for variant_id in sorted(base_by_variant):
        base_uom_id = base_by_variant[variant_id]
        option_rows = []
        for (candidate_variant_id, uom_id), factor in sorted(factors.items()):
            if candidate_variant_id != variant_id:
                continue
            uom = uom_map[uom_id]
            option_rows.append({
                "id": int(uom.id),
                "code": str(uom.code),
                "name": str(uom.name),
                "factor_to_base": canonical_quantity(factor),
            })
        option_rows.sort(
            key=lambda row: (
                0 if int(row["id"]) == base_uom_id else 1,
                str(row["code"]),
                int(row["id"]),
            )
        )
        items.append({
            "product_variant_id": variant_id,
            "base_uom_id": base_uom_id,
            "uoms": option_rows,
        })

    return {
        "currency_code": str(company.currency_code).upper(),
        "items": items,
    }


# ====================================================
# 1.5 جلب سياسة تكلفة المخزون الحالية
# ====================================================
@router.get("/warehouse/costing-policy", status_code=200)
async def warehouse_costing_policy(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('inbound.create', any_location=True)
    can_change = bool(
        await db.scalar(select(access.allows('inventory.costing.manage')))
    )
    try:
        return await cost_policy_payload(
            db,
            company_id=current_admin.company_id,
            can_change=can_change,
        )
    except CostingError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.as_detail(),
        ) from exc


# ====================================================
# 1.6 تحديث سياسة تكلفة المخزون مع idempotency
# ====================================================
@router.put("/warehouse/costing-policy", status_code=200)
async def update_warehouse_costing_policy(
    payload: InventoryCostPolicyUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('inventory.costing.manage')
    company_id = current_admin.company_id
    try:
        request_hash = _stable_request_hash(payload)
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="INVENTORY_COST_POLICY_UPDATE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        await set_cost_policy(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            method=payload.method,
            expected_version=payload.expected_version,
        )
        response_payload = await cost_policy_payload(
            db,
            company_id=company_id,
            can_change=True,
        )
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload
    except CostingError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.as_detail(),
        ) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


