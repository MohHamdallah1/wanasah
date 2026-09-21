from datetime import date
from decimal import Decimal
import hashlib
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from api.dependencies import get_current_driver
from database import get_db
from inventory_access import InventoryAccess
from models import (
    Company,
    Driver,
    InventoryLocation,
    InventoryMovement,
    ProductBatch,
    ProductLocation,
    ProductUomConversion,
    ProductVariant,
    UOM,
)
from quantity import QuantityError, canonical_quantity, validate_variant_quantity
from schemas import (
    InboundOptionsRequest,
    InventoryCostPolicyUpdateRequest,
    MessageResponse,
    UpgradedInboundRequest,
)
from services import (
    InventoryMutationError,
    begin_idempotent_operation,
    complete_idempotent_operation,
    apply_inventory_movements_batch,
    get_company_local_date,
    inventory_business_error,
    warehouse_setup_required_detail,
)
from domains.inventory_costing.service import (
    CostingError,
    activate_costing_for_first_receipt,
    build_purchase_cost_input,
    cost_policy_payload,
    set_cost_policy,
)
from product_lifecycle import (
    DEFAULT_PRODUCT_LOCATION_FLAGS,
    INBOUND_NEW,
    acquire_product_lifecycle_guards,
    evaluate_product_capability,
    product_location_allows,
    record_domain_event,
)

# Staging-only dependency: remains sourced from the untouched monolith until
# _stable_request_hash is moved once to _shared.py in its dedicated stage.
from api.warehouse import _stable_request_hash


logger = logging.getLogger("wanasah_logger")
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


# ====================================================
# 1.7 تسجيل توريد المورد فعلياً وتطبيق حركات المخزون والتكلفة
# ====================================================
@router.post("/warehouse/inbound", response_model=MessageResponse, status_code=201)
async def warehouse_inbound(
    payload: UpgradedInboundRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver)
):
    access = InventoryAccess(db, current_admin)
    await access.require('inbound.create', any_location=True)

    company_id = current_admin.company_id
    await _require_active_warehouse_setup(db, company_id)
    await access.require('inbound.create', payload.location_id)

    try:
        request_hash = _stable_request_hash(payload)
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="WAREHOUSE_INBOUND",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        if not payload.items:
            raise HTTPException(status_code=400, detail="No inbound items were supplied.")

        reference_id = payload.reference_id
        if not reference_id or not reference_id.strip() or reference_id == "بدون فاتورة":
            reference_id = f"AUTO-INB-{payload.request_id.hex.upper()}"
        else:
            reference_id = reference_id.strip()
        normalized_ref = reference_id.strip().lower()

        if not reference_id.startswith("AUTO-INB-"):
            await db.execute(
                select(func.pg_advisory_xact_lock(
                    company_id,
                    func.hashtext(f"inbound-ref:{normalized_ref}")
                ))
            )
            duplicate_ref = (
                await db.execute(
                    select(InventoryMovement.id).filter(
                        InventoryMovement.company_id == company_id,
                        InventoryMovement.reference_type == 'INBOUND_SUPPLIER',
                        func.lower(func.trim(InventoryMovement.reference_id)) == normalized_ref
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if duplicate_ref is not None:
                raise HTTPException(
                    status_code=409,
                    detail=inventory_business_error(
                        "INBOUND_REFERENCE_DUPLICATE",
                        "The supplier reference was already posted.",
                        context={"reference_id": reference_id},
                    ),
                )

        main_loc = (
            await db.execute(
                select(InventoryLocation).filter_by(
                    id=payload.location_id,
                    company_id=company_id,
                    location_type='WAREHOUSE',
                    is_system_managed=False,
                    is_active=True
                )
            )
        ).scalar_one_or_none()
        if main_loc is None:
            raise HTTPException(
                status_code=404,
                detail=inventory_business_error(
                    "INBOUND_WAREHOUSE_UNAVAILABLE",
                    "The selected warehouse is unavailable.",
                ),
            )

        requested_var_ids = {item.product_variant_id for item in payload.items}
        await acquire_product_lifecycle_guards(
            db, company_id, requested_var_ids, exclusive=False,
        )
        variant_rows = (
            await db.execute(
                select(
                    ProductVariant.id,
                    ProductVariant.base_uom_id,
                    ProductVariant.quantity_scale,
                    ProductVariant.quantity_step,
                    ProductVariant.expiry_control_mode,
                    ProductVariant.lifecycle_status,
                    ProductVariant.operational_hold,
                    ProductLocation.operational_flags,
                ).outerjoin(
                    ProductLocation,
                    and_(
                        ProductLocation.company_id == ProductVariant.company_id,
                        ProductLocation.product_variant_id == ProductVariant.id,
                        ProductLocation.location_id == payload.location_id,
                    ),
                ).filter(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id.in_(requested_var_ids),
                )
            )
        ).all()
        found_variant_ids = {int(row.id) for row in variant_rows}
        if found_variant_ids != requested_var_ids:
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "INBOUND_VARIANT_UNAVAILABLE",
                    "One or more products are unavailable for inbound.",
                    context={
                        "missing_product_variant_ids": sorted(
                            requested_var_ids - found_variant_ids
                        ),
                    },
                ),
            )

        missing_location_variant_ids = sorted(
            int(row.id)
            for row in variant_rows
            if row.operational_flags is None
        )
        if missing_location_variant_ids:
            await _ensure_first_inbound_product_locations(
                db,
                company_id=company_id,
                location_id=payload.location_id,
                variant_ids=missing_location_variant_ids,
                actor_id=current_admin.id,
                request_id=payload.request_id,
            )

        variant_rules = {}
        for row in variant_rows:
            decision = evaluate_product_capability(
                row.lifecycle_status,
                row.operational_hold,
                INBOUND_NEW,
            )
            if not decision.allowed:
                raise HTTPException(
                    status_code=409,
                    detail=inventory_business_error(
                        decision.code,
                        "The product state does not allow inbound stock.",
                        context={"product_variant_id": int(row.id)},
                    ),
                )
            if (
                row.operational_flags is not None
                and not product_location_allows(
                    row.operational_flags,
                    INBOUND_NEW,
                )
            ):
                raise HTTPException(
                    status_code=409,
                    detail=inventory_business_error(
                        "PRODUCT_LOCATION_INBOUND_DISABLED",
                        "Inbound is disabled for this product at the selected warehouse.",
                        context={
                            "product_variant_id": int(row.id),
                            "location_id": payload.location_id,
                        },
                    ),
                )
            variant_rules[int(row.id)] = {
                "base_uom_id": int(row.base_uom_id),
                "quantity_scale": int(row.quantity_scale),
                "quantity_step": row.quantity_step,
                "expiry_control_mode": str(row.expiry_control_mode),
            }

        _, uom_factors, _ = await _resolve_inbound_uom_options(
            db,
            company_id=company_id,
            variant_ids=sorted(requested_var_ids),
        )
        as_of_date = await get_company_local_date(db, company_id)
        requested_batches: dict[
            tuple[int, str],
            tuple[Optional[date], Optional[date]],
        ] = {}
        inbound_lines: list[dict] = []
        seen_batch_uoms: set[tuple[int, str, int]] = set()

        for item in payload.items:
            batch_key = (int(item.product_variant_id), str(item.batch_number))
            metadata = (item.production_date, item.expiry_date)
            if batch_key in requested_batches and requested_batches[batch_key] != metadata:
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_BATCH_METADATA_CONFLICT",
                        "The same product batch cannot carry conflicting dates in one receipt.",
                        context={
                            "product_variant_id": int(item.product_variant_id),
                            "batch_number": str(item.batch_number),
                        },
                    ),
                )

            line_key = (
                int(item.product_variant_id),
                str(item.batch_number),
                int(item.uom_id),
            )
            if line_key in seen_batch_uoms:
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_DUPLICATE_BATCH_UOM_LINE",
                        "The same product, batch and purchasing unit may appear only once per receipt.",
                        context={
                            "product_variant_id": int(item.product_variant_id),
                            "batch_number": str(item.batch_number),
                            "uom_id": int(item.uom_id),
                        },
                    ),
                )
            seen_batch_uoms.add(line_key)

            factor = uom_factors.get(
                (int(item.product_variant_id), int(item.uom_id))
            )
            if factor is None:
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_UOM_UNSUPPORTED",
                        "The selected purchasing unit has no direct exact conversion to the base unit.",
                        context={
                            "product_variant_id": int(item.product_variant_id),
                            "uom_id": int(item.uom_id),
                        },
                    ),
                )
            raw_base_quantity = Decimal(item.quantity) * Decimal(factor)
            try:
                base_quantity = validate_variant_quantity(
                    raw_base_quantity,
                    quantity_scale=variant_rules[item.product_variant_id]["quantity_scale"],
                    quantity_step=variant_rules[item.product_variant_id]["quantity_step"],
                    field_name="quantity",
                )
            except QuantityError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_QUANTITY_CONVERSION_INVALID",
                        "The purchased quantity cannot be represented exactly in the product base unit.",
                        context={"product_variant_id": int(item.product_variant_id)},
                    ),
                ) from exc

            expiry_mode = variant_rules[item.product_variant_id]["expiry_control_mode"]
            if expiry_mode == 'REQUIRED' and item.expiry_date is None:
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_EXPIRY_REQUIRED",
                        "Expiry date is required for this product.",
                        context={"product_variant_id": int(item.product_variant_id)},
                    ),
                )
            if expiry_mode == 'NONE' and item.expiry_date is not None:
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_EXPIRY_NOT_ALLOWED",
                        "This product does not use expiry tracking.",
                        context={"product_variant_id": int(item.product_variant_id)},
                    ),
                )
            if item.expiry_date is not None and item.expiry_date < as_of_date:
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_BATCH_EXPIRED",
                        "Expired stock cannot be received as available inventory.",
                        context={"batch_number": str(item.batch_number)},
                    ),
                )
            if item.production_date is not None and item.production_date > as_of_date:
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_PRODUCTION_DATE_FUTURE",
                        "Production date cannot be in the future.",
                        context={"batch_number": str(item.batch_number)},
                    ),
                )
            if (
                item.production_date is not None
                and item.expiry_date is not None
                and item.production_date > item.expiry_date
            ):
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_BATCH_DATES_INVALID",
                        "Production date cannot be after expiry date.",
                        context={"batch_number": str(item.batch_number)},
                    ),
                )

            if batch_key not in requested_batches:
                requested_batches[batch_key] = metadata
            inbound_lines.append({
                "batch_key": batch_key,
                "uom_id": int(item.uom_id),
                "base_quantity": base_quantity,
                "cost_input": build_purchase_cost_input(
                    input_uom_id=int(item.uom_id),
                    input_quantity=Decimal(item.quantity),
                    input_unit_cost=Decimal(item.unit_cost),
                    base_quantity=base_quantity,
                ),
            })

        await db.execute(
            pg_insert(ProductBatch).values([
                {
                    "company_id": company_id,
                    "product_variant_id": product_variant_id,
                    "batch_number": batch_number,
                    "production_date": requested_batches[(product_variant_id, batch_number)][0],
                    "expiry_date": requested_batches[(product_variant_id, batch_number)][1],
                    "is_active": True,
                }
                for product_variant_id, batch_number in sorted(requested_batches)
            ]).on_conflict_do_nothing(
                index_elements=['company_id', 'product_variant_id', 'batch_number']
            )
        )

        batch_rows = (
            await db.execute(
                select(ProductBatch).filter(
                    ProductBatch.company_id == company_id,
                    tuple_(ProductBatch.product_variant_id, ProductBatch.batch_number).in_(
                        sorted(requested_batches)
                    )
                )
            )
        ).scalars().all()
        batch_map = {
            (int(row.product_variant_id), str(row.batch_number)): row
            for row in batch_rows
        }
        if set(batch_map) != set(requested_batches):
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "INBOUND_BATCH_PERSISTENCE_CONFLICT",
                    "Not all inbound batches could be established.",
                ),
            )

        for key, (production_date, expiry_date) in requested_batches.items():
            batch = batch_map[key]
            if not batch.is_active or batch.disposition != 'RELEASED':
                raise HTTPException(
                    status_code=409,
                    detail=inventory_business_error(
                        "INBOUND_BATCH_UNAVAILABLE",
                        "The batch is not released for available inventory.",
                        context={"batch_number": str(batch.batch_number)},
                    ),
                )
            expiry_mode = variant_rules[int(batch.product_variant_id)]["expiry_control_mode"]
            if expiry_mode == 'REQUIRED' and batch.expiry_date is None:
                raise HTTPException(status_code=409, detail=inventory_business_error(
                    "INBOUND_EXPIRY_REQUIRED", "The existing batch is missing its required expiry date.",
                    context={"batch_number": str(batch.batch_number)},
                ))
            if expiry_mode == 'NONE' and batch.expiry_date is not None:
                raise HTTPException(status_code=409, detail=inventory_business_error(
                    "INBOUND_EXPIRY_NOT_ALLOWED", "The existing batch has expiry data for a non-expiry product.",
                    context={"batch_number": str(batch.batch_number)},
                ))
            if batch.expiry_date is not None and batch.expiry_date < as_of_date:
                raise HTTPException(status_code=409, detail=inventory_business_error(
                    "INBOUND_BATCH_EXPIRED", "The existing batch is expired.",
                    context={"batch_number": str(batch.batch_number)},
                ))
            if batch.production_date is not None and batch.production_date > as_of_date:
                raise HTTPException(status_code=409, detail=inventory_business_error(
                    "INBOUND_PRODUCTION_DATE_FUTURE", "The existing batch has a future production date.",
                    context={"batch_number": str(batch.batch_number)},
                ))
            if batch.expiry_date != expiry_date:
                raise HTTPException(status_code=409, detail=inventory_business_error(
                    "INBOUND_BATCH_METADATA_CONFLICT", "The batch already exists with a different expiry date.",
                    context={"batch_number": str(batch.batch_number)},
                ))
            if batch.production_date is not None and production_date is not None and batch.production_date != production_date:
                raise HTTPException(status_code=409, detail=inventory_business_error(
                    "INBOUND_BATCH_METADATA_CONFLICT", "The batch already exists with a different production date.",
                    context={"batch_number": str(batch.batch_number)},
                ))

        # Policy activation is serialized and happens before the first physical receipt.
        await activate_costing_for_first_receipt(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
        )

        movement_specs = []
        for line in sorted(
            inbound_lines,
            key=lambda value: (
                value["batch_key"][0],
                value["batch_key"][1],
                value["uom_id"],
            ),
        ):
            batch_key = line["batch_key"]
            product_variant_id, batch_number = batch_key
            batch = batch_map[batch_key]
            movement_raw_key = (
                f"{company_id}|{normalized_ref}|{main_loc.id}|"
                f"{product_variant_id}|{batch.id}|{line['uom_id']}"
            )
            movement_specs.append({
                "product_variant_id": product_variant_id,
                "batch_id": int(batch.id),
                "quantity": line["base_quantity"],
                "movement_kind": 'PHYSICAL',
                "reference_type": 'INBOUND_SUPPLIER',
                "reference_id": reference_id,
                "idempotency_key": (
                    "INB-"
                    + hashlib.sha256(movement_raw_key.encode("utf-8")).hexdigest()
                ),
                "source_location_id": None,
                "destination_location_id": main_loc.id,
                "source_stock_status": None,
                "destination_stock_status": 'AVAILABLE',
                "inventory_cost_input": line["cost_input"],
                "notes": payload.notes,
            })

        await apply_inventory_movements_batch(
            db,
            company_id=company_id,
            performed_by=current_admin.id,
            movements=movement_specs,
        )

        response_payload = {"message": "INBOUND_POSTED"}
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except CostingError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.as_detail(),
        ) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.warning(
            f"Concurrent conflict during supplier inbound: {str(exc)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "INBOUND_CONCURRENT_CONFLICT",
                "A concurrent inbound conflict occurred. Nothing was committed.",
            ),
        ) from exc
    except Exception as exc:
        await db.rollback()
        logger.error(
            f"Unexpected supplier inbound failure: {str(exc)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=inventory_business_error(
                "INBOUND_INTERNAL_ERROR",
                "Supplier inbound could not be completed.",
            ),
        ) from exc


