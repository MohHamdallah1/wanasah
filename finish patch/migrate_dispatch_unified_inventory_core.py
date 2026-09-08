from __future__ import annotations

from pathlib import Path
import ast
import shutil
import sys

ROOT = Path.cwd()
TARGET = ROOT / "wa_backend" / "api" / "dispatch.py"
BACKUP_DIR = ROOT / ".patch_backups" / "DISPATCH_UNIFIED_INVENTORY_CORE"
MARKER = "# PATCH: DISPATCH_UNIFIED_INVENTORY_CORE"


def fail(msg: str) -> None:
    print(f"PATCH_ABORTED: {msg}")
    raise SystemExit(1)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected exactly 1 anchor, found {count}")
    return text.replace(old, new, 1)


def replace_section(text: str, start: str, end: str, new_block: str, label: str) -> str:
    s = text.find(start)
    if s < 0:
        fail(f"{label}: start marker not found")
    e = text.find(end, s + len(start))
    if e < 0:
        fail(f"{label}: end marker not found")
    if text.find(start, s + 1) >= 0:
        fail(f"{label}: start marker is not unique")
    return text[:s] + new_block.rstrip() + "\n\n" + text[e:]


if not TARGET.exists():
    fail(f"target not found: {TARGET}")

text = TARGET.read_text(encoding="utf-8")
if MARKER in text:
    print("DISPATCH_UNIFIED_INVENTORY_CORE_ALREADY_OK")
    raise SystemExit(0)

# Baseline guards: this patch is intentionally for the legacy dispatch implementation only.
required_legacy = [
    "MainWarehouse",
    "VehicleLoad",
    "SessionInventory",
    "InventoryTransfer",
    "WarehouseLedger",
    "InventoryLedger",
]
missing = [name for name in required_legacy if name not in text]
if missing:
    fail(f"baseline differs; missing legacy anchors: {missing}")

# Add only the new dependencies needed by sections 6-10. Legacy imports remain temporarily
# because later dispatch sections still use them and will be migrated in the next patches.
imports_anchor = "from services import check_inventory_lock # +++ الحارس الجراحي للـ SaaS +++\n"
imports_new = '''from services import check_inventory_lock # +++ الحارس الجراحي للـ SaaS +++
from services import (
    InventoryMutationError,
    get_company_local_date,
    allocate_fefo_inventory_batch,
    apply_inventory_movements_batch,
)
from models import (
    InventoryBalance,
    InventoryTransferHeader,
    InventoryTransferLine,
    DispatchLoadPlanLine,
    ProductBatch,
)
from uuid import uuid4
'''
text = replace_once(text, imports_anchor, imports_new, "imports")

section6_start = "# =========================================\n# 6. إطلاق خط سير جديد"
section7_start = "# =========================================\n# 7. جلب الحمولة الافتتاحية"
section8_start = "# =========================================\n# 8. جلب الجرد اللحظي"
section9_start = "# =========================================\n# 9. تعديل الحمولة اللحظي"
section10_start = "# =========================================\n# 10. مراقبة حالة الحوالات"
section11_start = "# =========================================\n# 11. استرجاع المحلات"

helpers_and_section6 = r'''# PATCH: DISPATCH_UNIFIED_INVENTORY_CORE
# قلب Dispatch المخزني يعتمد InventoryBalance/InventoryMovement فقط.
# DispatchLoadPlanLine هدف تخطيطي وليس رصيداً حياً.

_DB_INT_MAX_DISPATCH = 2_147_483_647


async def _dispatch_vehicle_location_id(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
    require_active: bool = True,
) -> int:
    stmt = select(InventoryLocation.id).filter_by(
        company_id=company_id,
        vehicle_id=vehicle_id,
        location_type="VEHICLE",
    )
    if require_active:
        stmt = stmt.filter(InventoryLocation.is_active.is_(True))
    location_id = (
        await db.execute(stmt.order_by(InventoryLocation.id.asc()).limit(1))
    ).scalar_one_or_none()
    if location_id is None:
        raise HTTPException(
            status_code=409,
            detail="السيارة لا تملك موقع مخزون VEHICLE فعالاً داخل الشركة.",
        )
    return int(location_id)


async def _dispatch_source_warehouse(
    db: AsyncSession,
    *,
    company_id: int,
    location_id: int,
):
    location = (
        await db.execute(
            select(InventoryLocation)
            .filter_by(
                company_id=company_id,
                id=location_id,
                location_type="WAREHOUSE",
                is_active=True,
            )
            .with_for_update(read=True)
        )
    ).scalar_one_or_none()
    if location is None:
        raise HTTPException(
            status_code=400,
            detail="مستودع المصدر غير موجود أو غير فعال أو لا يتبع شركتك.",
        )
    return location


async def _dispatch_available_totals(
    db: AsyncSession,
    *,
    company_id: int,
    location_id: int,
):
    rows = (
        await db.execute(
            select(
                InventoryBalance.product_variant_id,
                func.sum(InventoryBalance.on_hand_quantity),
                func.sum(InventoryBalance.reserved_quantity),
            )
            .filter(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == location_id,
                InventoryBalance.stock_status == "AVAILABLE",
                or_(
                    InventoryBalance.on_hand_quantity > 0,
                    InventoryBalance.reserved_quantity > 0,
                ),
            )
            .group_by(InventoryBalance.product_variant_id)
            .order_by(InventoryBalance.product_variant_id.asc())
        )
    ).all()
    return {
        int(product_variant_id): (int(on_hand or 0), int(reserved or 0))
        for product_variant_id, on_hand, reserved in rows
    }


async def _dispatch_allocate_available_batches(
    db: AsyncSession,
    *,
    company_id: int,
    location_id: int,
    product_variant_id: int,
    quantity: int,
    as_of_date,
    require_sellable: bool,
):
    if quantity <= 0:
        return []

    if require_sellable:
        allocations = await allocate_fefo_inventory_batch(
            db,
            company_id=company_id,
            location_id=location_id,
            requests={product_variant_id: quantity},
            as_of_date=as_of_date,
            require_full=True,
        )
        return [
            (int(batch_id), int(qty))
            for batch_id, qty in allocations.get(product_variant_id, [])
        ]

    # إخراج عهدة من السيارة لا يجوز منعه لأن Batch أصبح منتهياً/موقوفاً.
    # نستخدم ترتيباً حتمياً (الأقرب انتهاءً أولاً) ونحجز Row Locks؛ لا نخترع Batch جديداً.
    rows = (
        await db.execute(
            select(
                InventoryBalance.batch_id,
                InventoryBalance.on_hand_quantity,
                InventoryBalance.reserved_quantity,
            )
            .join(
                ProductBatch,
                and_(
                    ProductBatch.company_id == InventoryBalance.company_id,
                    ProductBatch.product_variant_id == InventoryBalance.product_variant_id,
                    ProductBatch.id == InventoryBalance.batch_id,
                ),
            )
            .filter(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == location_id,
                InventoryBalance.product_variant_id == product_variant_id,
                InventoryBalance.stock_status == "AVAILABLE",
                InventoryBalance.on_hand_quantity > InventoryBalance.reserved_quantity,
            )
            .order_by(
                ProductBatch.expiry_date.asc(),
                ProductBatch.id.asc(),
                InventoryBalance.id.asc(),
            )
            .with_for_update()
        )
    ).all()

    remaining = int(quantity)
    allocations = []
    for batch_id, on_hand, reserved in rows:
        free_qty = int(on_hand or 0) - int(reserved or 0)
        if free_qty <= 0:
            continue
        take = min(free_qty, remaining)
        allocations.append((int(batch_id), int(take)))
        remaining -= take
        if remaining == 0:
            break

    if remaining:
        raise InventoryMutationError(
            f"الرصيد الحر في الموقع لا يغطي الصنف ({product_variant_id}). العجز: {remaining} حبة."
        )
    return allocations


async def _dispatch_set_load_plan_target(
    db: AsyncSession,
    *,
    company_id: int,
    route_id: int,
    product_variant_id: int,
    target_quantity_packs: int,
    updated_by: int,
) -> None:
    line = (
        await db.execute(
            select(DispatchLoadPlanLine)
            .filter_by(
                company_id=company_id,
                dispatch_route_id=route_id,
                product_variant_id=product_variant_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if target_quantity_packs <= 0:
        if line is not None:
            await db.delete(line)
        return

    if line is None:
        db.add(
            DispatchLoadPlanLine(
                company_id=company_id,
                dispatch_route_id=route_id,
                product_variant_id=product_variant_id,
                target_quantity_packs=target_quantity_packs,
                updated_by=updated_by,
            )
        )
    else:
        line.target_quantity_packs = target_quantity_packs
        line.updated_by = updated_by
        line.updated_at = get_utc_now()


# =========================================
# 6. إطلاق خط سير جديد وحفظ الحمولة - Unified Inventory Engine
# =========================================
@router.post("/dispatch/route", status_code=201)
async def dispatch_route(
    payload: DispatchRouteRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id

    try:
        company_local_date = await get_company_local_date(db, company_id)

        # ترتيب أقفال كيانات التوزيع ثابت: driver -> vehicle -> zone -> route/inventory.
        driver = (
            await db.execute(
                select(Driver)
                .filter_by(
                    company_id=company_id,
                    id=payload.driver_id,
                    is_active=True,
                    is_admin=False,
                )
                .order_by(Driver.id.asc())
                .with_for_update()
            )
        ).scalar_one_or_none()
        if driver is None:
            raise HTTPException(status_code=404, detail="المندوب غير موجود أو غير فعال.")

        vehicle = (
            await db.execute(
                select(Vehicle)
                .filter_by(
                    company_id=company_id,
                    id=payload.vehicle_id,
                    is_active=True,
                )
                .order_by(Vehicle.id.asc())
                .with_for_update()
            )
        ).scalar_one_or_none()
        if vehicle is None:
            raise HTTPException(status_code=404, detail="السيارة غير موجودة أو غير فعالة.")

        zone = (
            await db.execute(
                select(Zone)
                .filter_by(
                    company_id=company_id,
                    id=payload.zone_id,
                    is_active=True,
                )
                .order_by(Zone.id.asc())
                .with_for_update()
            )
        ).scalar_one_or_none()
        if zone is None:
            raise HTTPException(status_code=404, detail="المنطقة غير موجودة أو مؤرشفة.")

        source_location = await _dispatch_source_warehouse(
            db,
            company_id=company_id,
            location_id=payload.source_location_id,
        )
        vehicle_location_id = await _dispatch_vehicle_location_id(
            db,
            company_id=company_id,
            vehicle_id=payload.vehicle_id,
        )

        # إنشاء Route جديد أثناء WorkSession قائمة يفتح باب تبديل عهدة ضمني؛ ممنوع.
        active_session = (
            await db.execute(
                select(WorkSession.id)
                .filter_by(
                    company_id=company_id,
                    driver_id=payload.driver_id,
                    end_time=None,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if active_session is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "مرفوض: لا يمكن إطلاق خط سير جديد أو تبديل عهدة المندوب أثناء WorkSession نشطة. "
                    "استخدم تعديل حمولة المسار الحالي أو أنهِ الجلسة أولاً."
                ),
            )

        previous_unsettled = (
            await db.execute(
                select(WorkSession.id)
                .filter(
                    WorkSession.company_id == company_id,
                    WorkSession.driver_id == payload.driver_id,
                    WorkSession.end_time.is_not(None),
                    WorkSession.is_settled.is_(False),
                )
                .order_by(WorkSession.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if previous_unsettled is not None:
            raise HTTPException(
                status_code=409,
                detail="المندوب لديه جلسة سابقة بانتظار التسوية المالية ولا يمكن إطلاق يوم جديد له.",
            )

        # Fail-fast واضح؛ PostgreSQL partial unique indexes يبقون خط الدفاع النهائي ضد السباق.
        conflict = (
            await db.execute(
                select(DispatchRoute.id)
                .filter(
                    DispatchRoute.company_id == company_id,
                    DispatchRoute.status.in_(["active", "waiting", "postponed"]),
                    or_(
                        DispatchRoute.zone_id == payload.zone_id,
                        DispatchRoute.driver_id == payload.driver_id,
                        DispatchRoute.vehicle_id == payload.vehicle_id,
                    ),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if conflict is not None:
            raise HTTPException(
                status_code=409,
                detail="المنطقة أو المندوب أو السيارة مستخدمة حالياً في خط سير فعال/معلق.",
            )

        clean_inventory = {int(pid): int(qty) for pid, qty in payload.inventory.items()}
        target_product_ids = sorted(clean_inventory)

        current_vehicle = await _dispatch_available_totals(
            db,
            company_id=company_id,
            location_id=vehicle_location_id,
        )
        if any(reserved > 0 for _, reserved in current_vehicle.values()):
            raise HTTPException(
                status_code=409,
                detail="السيارة تحمل حجوزات مخزون معلقة؛ عالج المصافحات/الحجوزات قبل إطلاق خط سير جديد.",
            )

        all_product_ids = sorted(set(target_product_ids) | set(current_vehicle))
        variants_map = {}
        if all_product_ids:
            variants = (
                await db.execute(
                    select(ProductVariant)
                    .filter(
                        ProductVariant.company_id == company_id,
                        ProductVariant.id.in_(all_product_ids),
                    )
                    .order_by(ProductVariant.id.asc())
                )
            ).scalars().all()
            variants_map = {int(v.id): v for v in variants}
            if set(variants_map) != set(all_product_ids):
                raise HTTPException(status_code=404, detail="أحد أصناف خطة التحميل غير موجود داخل الشركة.")

        route = DispatchRoute(
            company_id=company_id,
            zone_id=payload.zone_id,
            driver_id=payload.driver_id,
            vehicle_id=payload.vehicle_id,
            source_location_id=int(source_location.id),
            dispatch_date=company_local_date,
            status="active",
        )
        db.add(route)
        await db.flush()

        movement_specs = []
        for product_variant_id in all_product_ids:
            variant = variants_map[product_variant_id]
            ppc = int(variant.packs_per_carton or 0)
            if ppc <= 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"إعداد عدد الحبات في الكرتونة غير صالح للصنف ({variant.variant_name}).",
                )

            target_cartons = clean_inventory.get(product_variant_id, 0)
            target_packs = target_cartons * ppc
            if target_packs > _DB_INT_MAX_DISPATCH:
                raise HTTPException(status_code=400, detail="حمولة صنف تتجاوز سعة INTEGER في قاعدة البيانات.")

            current_packs = current_vehicle.get(product_variant_id, (0, 0))[0]
            delta_packs = target_packs - current_packs

            await _dispatch_set_load_plan_target(
                db,
                company_id=company_id,
                route_id=route.id,
                product_variant_id=product_variant_id,
                target_quantity_packs=target_packs,
                updated_by=current_admin.id,
            )

            if delta_packs == 0:
                continue

            if delta_packs > 0:
                if not variant.is_active:
                    raise HTTPException(
                        status_code=400,
                        detail=f"لا يمكن تحميل المنتج الموقوف ({variant.variant_name}) إلى السيارة.",
                    )
                await check_inventory_lock(
                    db, company_id, int(source_location.id), variant_id=product_variant_id
                )
                await check_inventory_lock(
                    db, company_id, vehicle_location_id, variant_id=product_variant_id
                )
                allocations = await _dispatch_allocate_available_batches(
                    db,
                    company_id=company_id,
                    location_id=int(source_location.id),
                    product_variant_id=product_variant_id,
                    quantity=delta_packs,
                    as_of_date=company_local_date,
                    require_sellable=True,
                )
                src, dst = int(source_location.id), vehicle_location_id
                ref_type = "DISPATCH_LOAD"
            else:
                await check_inventory_lock(
                    db, company_id, vehicle_location_id, variant_id=product_variant_id
                )
                await check_inventory_lock(
                    db, company_id, int(source_location.id), variant_id=product_variant_id
                )
                allocations = await _dispatch_allocate_available_batches(
                    db,
                    company_id=company_id,
                    location_id=vehicle_location_id,
                    product_variant_id=product_variant_id,
                    quantity=abs(delta_packs),
                    as_of_date=company_local_date,
                    require_sellable=False,
                )
                src, dst = vehicle_location_id, int(source_location.id)
                ref_type = "DISPATCH_UNLOAD"

            for segment_index, (batch_id, quantity) in enumerate(allocations):
                movement_specs.append({
                    "product_variant_id": product_variant_id,
                    "batch_id": batch_id,
                    "quantity": quantity,
                    "movement_kind": "PHYSICAL",
                    "reference_type": ref_type,
                    "reference_id": str(route.id),
                    "idempotency_key": (
                        f"DSP-ROUTE-{route.id}-{product_variant_id}-{batch_id}-{segment_index}-{ref_type}"
                    ),
                    "source_location_id": src,
                    "destination_location_id": dst,
                    "source_stock_status": "AVAILABLE",
                    "destination_stock_status": "AVAILABLE",
                    "work_session_id": None,
                    "transfer_header_id": None,
                    "notes": f"تهيئة حمولة خط السير {route.id} قبل بدء WorkSession.",
                })

        if len(movement_specs) > 10_000:
            raise HTTPException(status_code=400, detail="خطة التحميل تتجاوز الحد الآمن لحركات المخزون.")
        if movement_specs:
            await apply_inventory_movements_batch(
                db,
                company_id=company_id,
                performed_by=current_admin.id,
                movements=movement_specs,
            )

        # منطق إنشاء الزيارات نفسه محفوظ.
        shops_in_zone = (
            await db.execute(
                select(Shop).filter_by(
                    company_id=company_id,
                    zone_id=payload.zone_id,
                    is_active=True,
                    is_archived=False,
                )
            )
        ).scalars().all()
        shop_ids = [shop.id for shop in shops_in_zone]

        if shop_ids:
            today_start = datetime.combine(company_local_date, datetime.min.time())
            today_end = today_start + timedelta(days=1)
            existing_visits = (
                await db.execute(
                    select(Visit).filter(
                        Visit.company_id == company_id,
                        Visit.driver_id == payload.driver_id,
                        Visit.shop_id.in_(shop_ids),
                        or_(
                            Visit.status == "Pending",
                            and_(
                                Visit.visit_timestamp >= today_start,
                                Visit.visit_timestamp < today_end,
                            ),
                        ),
                    )
                )
            ).scalars().all()
            existing_by_shop = {visit.shop_id: visit for visit in existing_visits}

            shortage_shop_ids = set((
                await db.execute(
                    select(ShortageRequest.shop_id).filter(
                        ShortageRequest.company_id == company_id,
                        ShortageRequest.shop_id.in_(shop_ids),
                        ShortageRequest.status == "pending",
                    )
                )
            ).scalars().all())

            for shop in shops_in_zone:
                is_emergency = shop.id in shortage_shop_ids
                existing = existing_by_shop.get(shop.id)
                if existing is None:
                    db.add(Visit(
                        company_id=company_id,
                        driver_id=payload.driver_id,
                        shop_id=shop.id,
                        status="Pending",
                        sequence=shop.sequence,
                        is_emergency=is_emergency,
                    ))
                elif is_emergency:
                    existing.is_emergency = True

        await db.commit()
        asyncio.create_task(
            dispatch_manager.broadcast(
                {"event": "ROUTE_DISPATCHED", "message": "تم إطلاق خط سير جديد"},
                company_id=company_id,
            )
        )
        return {"message": "تم إطلاق خط السير بنجاح"}

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.error(f"Dispatch route integrity conflict: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=409, detail="تعارض متزامن أثناء إطلاق خط السير.") from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في إطلاق خط السير: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي في الخادم أثناء إطلاق خط السير.") from exc
'''
text = replace_section(text, section6_start, section7_start, helpers_and_section6, "section 6")

section7_new = r'''# =========================================
# 7. جلب الحمولة الفعلية للسيارة من InventoryBalance
# =========================================
@router.get("/dispatch/inventory/{vehicle_id}", response_model=List[VehicleInventoryItemResponse], status_code=200)
async def get_vehicle_inventory(
    vehicle_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id
    vehicle_exists = (
        await db.execute(
            select(Vehicle.id).filter_by(
                company_id=company_id,
                id=vehicle_id,
            )
        )
    ).scalar_one_or_none()
    if vehicle_exists is None:
        raise HTTPException(status_code=404, detail="السيارة غير موجودة.")

    vehicle_location_id = await _dispatch_vehicle_location_id(
        db,
        company_id=company_id,
        vehicle_id=vehicle_id,
    )

    rows = (
        await db.execute(
            select(
                InventoryBalance.product_variant_id,
                func.sum(InventoryBalance.on_hand_quantity),
            )
            .filter(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == vehicle_location_id,
                InventoryBalance.stock_status == "AVAILABLE",
                InventoryBalance.on_hand_quantity > 0,
            )
            .group_by(InventoryBalance.product_variant_id)
            .order_by(InventoryBalance.product_variant_id.asc())
        )
    ).all()
    inventory_map = {int(pid): int(qty or 0) for pid, qty in rows}

    loaded_ids = sorted(inventory_map)
    variant_filter = (
        or_(ProductVariant.is_active.is_(True), ProductVariant.id.in_(loaded_ids))
        if loaded_ids
        else ProductVariant.is_active.is_(True)
    )
    variants = (
        await db.execute(
            select(ProductVariant)
            .filter(ProductVariant.company_id == company_id, variant_filter)
            .order_by(ProductVariant.id.asc())
        )
    ).scalars().all()

    result = []
    for variant in variants:
        ppc = int(variant.packs_per_carton or 0)
        if ppc <= 0:
            raise HTTPException(
                status_code=409,
                detail=f"إعداد التعبئة غير صالح للصنف ({variant.variant_name}).",
            )
        total_packs = inventory_map.get(int(variant.id), 0)
        cartons, loose = divmod(total_packs, ppc)
        result.append({
            "product_id": str(variant.id),
            "product_name": variant.variant_name,
            "current_quantity": cartons,
            "current_loose_packs": loose,
        })
    return result
'''
text = replace_section(text, section7_start, section8_start, section7_new, "section 7")

# Section 8 ends at the legacy format helper comment.
format_helper_marker = "# +++ دالة مساعدة (مطابقة للفلاسك) لتحويل الحبات إلى نصوص بشرية في الليدجر +++"
section8_new = r'''# =========================================
# 8. جلب الجرد اللحظي الحر لسيارة المسار
# =========================================
@router.get("/dispatch/route/{route_id}/live_inventory", response_model=List[RouteLiveInventoryItemResponse], status_code=200)
async def get_route_live_inventory(
    route_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id
    route = (
        await db.execute(
            select(DispatchRoute).filter_by(
                company_id=company_id,
                id=route_id,
            )
        )
    ).scalar_one_or_none()
    if route is None or route.vehicle_id is None:
        raise HTTPException(status_code=404, detail="خط السير غير موجود أو غير مرتبط بسيارة.")

    vehicle_location_id = await _dispatch_vehicle_location_id(
        db,
        company_id=company_id,
        vehicle_id=route.vehicle_id,
    )

    rows = (
        await db.execute(
            select(
                InventoryBalance.product_variant_id,
                func.sum(
                    InventoryBalance.on_hand_quantity - InventoryBalance.reserved_quantity
                ),
            )
            .filter(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == vehicle_location_id,
                InventoryBalance.stock_status == "AVAILABLE",
                InventoryBalance.on_hand_quantity > 0,
            )
            .group_by(InventoryBalance.product_variant_id)
            .order_by(InventoryBalance.product_variant_id.asc())
        )
    ).all()
    free_map = {int(pid): max(0, int(qty or 0)) for pid, qty in rows}

    loaded_ids = sorted(free_map)
    variant_filter = (
        or_(ProductVariant.is_active.is_(True), ProductVariant.id.in_(loaded_ids))
        if loaded_ids
        else ProductVariant.is_active.is_(True)
    )
    variants = (
        await db.execute(
            select(ProductVariant)
            .filter(ProductVariant.company_id == company_id, variant_filter)
            .order_by(ProductVariant.id.asc())
        )
    ).scalars().all()

    result = []
    for variant in variants:
        ppc = int(variant.packs_per_carton or 0)
        if ppc <= 0:
            raise HTTPException(
                status_code=409,
                detail=f"إعداد التعبئة غير صالح للصنف ({variant.variant_name}).",
            )
        total_packs = free_map.get(int(variant.id), 0)
        cartons, loose = divmod(total_packs, ppc)
        result.append({
            "product_id": str(variant.id),
            "product_name": variant.variant_name,
            "current_cartons": cartons,
            "current_packs": loose,
        })
    return result
'''
text = replace_section(text, section8_start, format_helper_marker, section8_new, "section 8")

section9_new = r'''# =========================================
# 9. تعديل الحمولة اللحظي - DIRECT قبل الجلسة / HANDSHAKE أثناء الجلسة
# =========================================
@router.put("/dispatch/route/{route_id}/adjust_inventory", status_code=200)
async def adjust_route_inventory(
    route_id: int,
    payload: AdjustRouteInventoryRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id

    try:
        route = (
            await db.execute(
                select(DispatchRoute)
                .filter_by(company_id=company_id, id=route_id)
                .order_by(DispatchRoute.id.asc())
                .with_for_update()
            )
        ).scalar_one_or_none()
        if route is None or route.driver_id is None or route.vehicle_id is None:
            raise HTTPException(status_code=404, detail="خط السير غير موجود أو غير مكتمل.")

        source_location = await _dispatch_source_warehouse(
            db,
            company_id=company_id,
            location_id=route.source_location_id,
        )
        vehicle_location_id = await _dispatch_vehicle_location_id(
            db,
            company_id=company_id,
            vehicle_id=route.vehicle_id,
        )

        active_session = None
        if route.work_session_id is not None:
            active_session = (
                await db.execute(
                    select(WorkSession)
                    .filter_by(
                        company_id=company_id,
                        id=route.work_session_id,
                        driver_id=route.driver_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if active_session is None:
                raise HTTPException(status_code=409, detail="المسار مرتبط بجلسة غير صالحة داخل الشركة.")
            if active_session.end_time is not None:
                raise HTTPException(
                    status_code=403,
                    detail="لا يمكن تعديل حمولة جلسة انتهى عملها؛ أكمل التسوية المخزنية أولاً.",
                )
            if active_session.inventory_reconciled_at is not None:
                raise HTTPException(status_code=409, detail="عهدة الجلسة مختومة مخزنياً ولا تقبل تعديلات.")

        aggregated_deltas = {
            int(item.product_id): int(item.delta_cartons)
            for item in payload.deltas
            if int(item.delta_cartons) != 0
        }
        if not aggregated_deltas:
            raise HTTPException(status_code=400, detail="لم يتم إرسال أي تعديل فعلي.")

        product_ids = sorted(aggregated_deltas)
        variants = (
            await db.execute(
                select(ProductVariant)
                .filter(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id.in_(product_ids),
                )
                .order_by(ProductVariant.id.asc())
            )
        ).scalars().all()
        variants_map = {int(v.id): v for v in variants}
        if set(variants_map) != set(product_ids):
            raise HTTPException(status_code=404, detail="أحد المنتجات غير موجود أو لا يتبع الشركة.")

        company_local_date = await get_company_local_date(db, company_id)
        batch_token = f"BATCH_{uuid4().hex[:16].upper()}"

        # أثناء الجلسة: لا نحرك الرصيد فيزيائياً؛ نحجز المصدر ونصدر HANDSHAKE.
        if active_session is not None:
            reserve_specs = []
            created_headers = []

            for product_variant_id in product_ids:
                variant = variants_map[product_variant_id]
                ppc = int(variant.packs_per_carton or 0)
                if ppc <= 0:
                    raise HTTPException(
                        status_code=409,
                        detail=f"إعداد التعبئة غير صالح للصنف ({variant.variant_name}).",
                    )
                delta_packs = aggregated_deltas[product_variant_id] * ppc
                if abs(delta_packs) > _DB_INT_MAX_DISPATCH:
                    raise HTTPException(status_code=400, detail="كمية التعديل تتجاوز سعة INTEGER.")

                if delta_packs > 0:
                    if not variant.is_active:
                        raise HTTPException(
                            status_code=400,
                            detail=f"لا يمكن إرسال المنتج الموقوف ({variant.variant_name}) إلى السيارة.",
                        )
                    source_id = int(source_location.id)
                    destination_id = vehicle_location_id
                    require_sellable = True
                else:
                    source_id = vehicle_location_id
                    destination_id = int(source_location.id)
                    require_sellable = False

                await check_inventory_lock(
                    db, company_id, source_id, variant_id=product_variant_id
                )
                await check_inventory_lock(
                    db, company_id, destination_id, variant_id=product_variant_id
                )

                allocations = await _dispatch_allocate_available_batches(
                    db,
                    company_id=company_id,
                    location_id=source_id,
                    product_variant_id=product_variant_id,
                    quantity=abs(delta_packs),
                    as_of_date=company_local_date,
                    require_sellable=require_sellable,
                )

                header = InventoryTransferHeader(
                    company_id=company_id,
                    reference_number=f"HS-{uuid4().hex.upper()}",
                    source_location_id=source_id,
                    destination_location_id=destination_id,
                    workflow_type="HANDSHAKE",
                    status="PENDING",
                    work_session_id=active_session.id,
                    expected_receiver_id=route.driver_id,
                    dispatched_by=current_admin.id,
                    notes=batch_token,
                )
                db.add(header)
                await db.flush()

                for batch_id, quantity in allocations:
                    db.add(InventoryTransferLine(
                        company_id=company_id,
                        transfer_header_id=header.id,
                        product_variant_id=product_variant_id,
                        batch_id=batch_id,
                        quantity=quantity,
                    ))
                    reserve_specs.append({
                        "product_variant_id": product_variant_id,
                        "batch_id": batch_id,
                        "quantity": quantity,
                        "movement_kind": "RESERVATION",
                        "reservation_action": "RESERVE",
                        "reference_type": "HANDSHAKE_RESERVE",
                        "reference_id": header.reference_number,
                        "idempotency_key": f"HS-RES-{header.id}-{batch_id}",
                        "source_location_id": source_id,
                        "destination_location_id": source_id,
                        "source_stock_status": "AVAILABLE",
                        "destination_stock_status": "AVAILABLE",
                        "work_session_id": active_session.id,
                        "transfer_header_id": header.id,
                        "notes": "حجز مصدر مصافحة منتصف اليوم حتى قرار المندوب.",
                    })
                created_headers.append(header)

            if len(reserve_specs) > 10_000:
                raise HTTPException(status_code=400, detail="تعديلات المصافحة تتجاوز الحد الآمن.")
            if reserve_specs:
                await apply_inventory_movements_batch(
                    db,
                    company_id=company_id,
                    performed_by=current_admin.id,
                    movements=reserve_specs,
                )

            audit_details = " | ".join(
                f"صنف {pid}: {aggregated_deltas[pid]:+d} كرتونة"
                for pid in product_ids
            )[:1000]
            db.add(SystemAuditLog(
                company_id=company_id,
                admin_id=current_admin.id,
                target_id=f"Route_{route.id}_Session_{active_session.id}",
                action_type="HANDSHAKE_INVENTORY_REQUEST",
                old_value="لا تغيير في الرصيد الفيزيائي قبل قرار المندوب",
                new_value=audit_details,
            ))

            await db.commit()
            asyncio.create_task(
                dispatch_manager.broadcast(
                    {"event": "INVENTORY_ADJUSTED", "message": "تم إرسال تعديل حمولة للمندوب"},
                    company_id=company_id,
                )
            )
            return {
                "message": "تم إرسال الحوالة للمندوب. الرصيد الفيزيائي لن يتغير قبل القبول؛ الكمية محجوزة فقط.",
            }

        # قبل الجلسة: DIRECT فوري بين مستودع المصدر والسيارة.
        current_vehicle = await _dispatch_available_totals(
            db,
            company_id=company_id,
            location_id=vehicle_location_id,
        )
        if any(reserved > 0 for _, reserved in current_vehicle.values()):
            raise HTTPException(
                status_code=409,
                detail="السيارة تحمل حجوزات معلقة؛ لا يجوز تعديل الحمولة مباشرة قبل تنظيفها.",
            )

        movement_specs = []
        op_token = uuid4().hex[:16].upper()
        for product_variant_id in product_ids:
            variant = variants_map[product_variant_id]
            ppc = int(variant.packs_per_carton or 0)
            if ppc <= 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"إعداد التعبئة غير صالح للصنف ({variant.variant_name}).",
                )
            delta_packs = aggregated_deltas[product_variant_id] * ppc
            if abs(delta_packs) > _DB_INT_MAX_DISPATCH:
                raise HTTPException(status_code=400, detail="كمية التعديل تتجاوز سعة INTEGER.")

            current_packs = current_vehicle.get(product_variant_id, (0, 0))[0]
            target_after = current_packs + delta_packs
            if target_after < 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"حمولة السيارة من ({variant.variant_name}) لا تكفي لهذا السحب.",
                )

            if delta_packs > 0:
                if not variant.is_active:
                    raise HTTPException(
                        status_code=400,
                        detail=f"لا يمكن تحميل المنتج الموقوف ({variant.variant_name}).",
                    )
                source_id = int(source_location.id)
                destination_id = vehicle_location_id
                allocations = await _dispatch_allocate_available_batches(
                    db,
                    company_id=company_id,
                    location_id=source_id,
                    product_variant_id=product_variant_id,
                    quantity=delta_packs,
                    as_of_date=company_local_date,
                    require_sellable=True,
                )
                reference_type = "DISPATCH_LOAD"
            else:
                source_id = vehicle_location_id
                destination_id = int(source_location.id)
                allocations = await _dispatch_allocate_available_batches(
                    db,
                    company_id=company_id,
                    location_id=source_id,
                    product_variant_id=product_variant_id,
                    quantity=abs(delta_packs),
                    as_of_date=company_local_date,
                    require_sellable=False,
                )
                reference_type = "DISPATCH_UNLOAD"

            await check_inventory_lock(db, company_id, source_id, variant_id=product_variant_id)
            await check_inventory_lock(db, company_id, destination_id, variant_id=product_variant_id)

            for segment_index, (batch_id, quantity) in enumerate(allocations):
                movement_specs.append({
                    "product_variant_id": product_variant_id,
                    "batch_id": batch_id,
                    "quantity": quantity,
                    "movement_kind": "PHYSICAL",
                    "reference_type": reference_type,
                    "reference_id": str(route.id),
                    "idempotency_key": (
                        f"DSP-ADJ-{route.id}-{op_token}-{product_variant_id}-{batch_id}-{segment_index}"
                    ),
                    "source_location_id": source_id,
                    "destination_location_id": destination_id,
                    "source_stock_status": "AVAILABLE",
                    "destination_stock_status": "AVAILABLE",
                    "work_session_id": None,
                    "transfer_header_id": None,
                    "notes": "تعديل مباشر لحمولة السيارة قبل بدء WorkSession.",
                })

            await _dispatch_set_load_plan_target(
                db,
                company_id=company_id,
                route_id=route.id,
                product_variant_id=product_variant_id,
                target_quantity_packs=target_after,
                updated_by=current_admin.id,
            )

        if len(movement_specs) > 10_000:
            raise HTTPException(status_code=400, detail="تعديل الحمولة يتجاوز الحد الآمن للحركات.")
        if movement_specs:
            await apply_inventory_movements_batch(
                db,
                company_id=company_id,
                performed_by=current_admin.id,
                movements=movement_specs,
            )

        audit_details = " | ".join(
            f"صنف {pid}: {aggregated_deltas[pid]:+d} كرتونة"
            for pid in product_ids
        )[:1000]
        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"Route_{route.id}",
            action_type="DIRECT_INVENTORY_ADJUSTMENT",
            old_value="InventoryBalance قبل التعديل",
            new_value=audit_details,
        ))

        await db.commit()
        asyncio.create_task(
            dispatch_manager.broadcast(
                {"event": "INVENTORY_ADJUSTED", "message": "تم تعديل حمولة السيارة"},
                company_id=company_id,
            )
        )
        return {"message": "تم تحديث حمولة السيارة مباشرة عبر محرك المخزون الموحد."}

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.error(f"Dispatch inventory integrity conflict: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=409, detail="تعارض متزامن أثناء تعديل الحمولة.") from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في تعديل حمولة المسار: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي في الخادم أثناء تعديل الحمولة.") from exc
'''
text = replace_section(text, section9_start, section10_start, section9_new, "section 9")

section10_new = r'''# =========================================
# 10. مراقبة حوالات HANDSHAKE للمسؤول
# =========================================
@router.get("/dispatch/route/{route_id}/transfers", response_model=List[RouteTransferResponse], status_code=200)
async def get_route_transfers(
    route_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id
    route = (
        await db.execute(
            select(DispatchRoute).filter_by(
                company_id=company_id,
                id=route_id,
            )
        )
    ).scalar_one_or_none()
    if route is None or route.driver_id is None or route.vehicle_id is None:
        return []
    if route.work_session_id is None:
        return []

    vehicle_location_id = await _dispatch_vehicle_location_id(
        db,
        company_id=company_id,
        vehicle_id=route.vehicle_id,
        require_active=False,
    )

    headers = (
        await db.execute(
            select(InventoryTransferHeader)
            .filter_by(
                company_id=company_id,
                work_session_id=route.work_session_id,
                workflow_type="HANDSHAKE",
                expected_receiver_id=route.driver_id,
            )
            .order_by(
                InventoryTransferHeader.created_at.desc(),
                InventoryTransferHeader.id.desc(),
            )
        )
    ).scalars().all()
    if not headers:
        return []

    header_ids = [int(header.id) for header in headers]
    rows = (
        await db.execute(
            select(
                InventoryTransferLine.transfer_header_id,
                InventoryTransferLine.product_variant_id,
                func.sum(InventoryTransferLine.quantity),
                ProductVariant.variant_name,
                ProductVariant.packs_per_carton,
            )
            .join(
                ProductVariant,
                and_(
                    ProductVariant.company_id == InventoryTransferLine.company_id,
                    ProductVariant.id == InventoryTransferLine.product_variant_id,
                ),
            )
            .filter(
                InventoryTransferLine.company_id == company_id,
                InventoryTransferLine.transfer_header_id.in_(header_ids),
                ProductVariant.company_id == company_id,
            )
            .group_by(
                InventoryTransferLine.transfer_header_id,
                InventoryTransferLine.product_variant_id,
                ProductVariant.variant_name,
                ProductVariant.packs_per_carton,
            )
            .order_by(InventoryTransferLine.transfer_header_id.asc())
        )
    ).all()

    by_header = {}
    for header_id, product_variant_id, quantity, variant_name, ppc in rows:
        by_header.setdefault(int(header_id), []).append(
            (int(product_variant_id), int(quantity or 0), str(variant_name), int(ppc or 0))
        )

    status_map = {
        "PENDING": "pending",
        "POSTED": "accepted",
        "REJECTED": "rejected",
        "CANCELLED": "cancelled",
    }
    result = []
    for header in headers:
        products = by_header.get(int(header.id), [])
        if len(products) != 1:
            raise HTTPException(
                status_code=409,
                detail=f"الحوالة ({header.id}) لا تطابق عقد المصافحة: Header واحد يجب أن يحمل صنفاً واحداً.",
            )
        _, quantity, variant_name, ppc = products[0]
        if quantity <= 0 or ppc <= 0:
            raise HTTPException(status_code=409, detail=f"الحوالة ({header.id}) تحمل بيانات كمية غير صالحة.")

        if int(header.destination_location_id) == vehicle_location_id:
            signed_quantity = quantity
        elif int(header.source_location_id) == vehicle_location_id:
            signed_quantity = -quantity
        else:
            raise HTTPException(
                status_code=409,
                detail=f"الحوالة ({header.id}) لا ترتبط بسيارة هذا المسار.",
            )

        sign = -1 if signed_quantity < 0 else 1
        absolute = abs(signed_quantity)
        result.append({
            "transfer_id": int(header.id),
            "product_name": variant_name,
            "delta_cartons": (absolute // ppc) * sign,
            "delta_packs": (absolute % ppc) * sign,
            "status": status_map.get(str(header.status), str(header.status).lower()),
            "created_at": (
                header.created_at.replace(tzinfo=timezone.utc).isoformat()
                if header.created_at else None
            ),
            "batch_id": (
                header.notes
                if header.notes and "BATCH_" in header.notes
                else str(header.reference_number)
            ),
        })

    return result
'''
text = replace_section(text, section10_start, section11_start, section10_new, "section 10")

# Parse the complete result before writing anything.
try:
    ast.parse(text)
except SyntaxError as exc:
    fail(f"patched dispatch.py does not parse: {exc}")

# Core postconditions. Legacy symbols are intentionally still present elsewhere in dispatch.py;
# these sections must no longer contain their old implementations.
core_start = text.index(MARKER)
core_end = text.index(section11_start, core_start)
core = text[core_start:core_end]
for legacy_symbol in (
    "MainWarehouse",
    "VehicleLoad",
    "SessionInventory",
    "InventoryTransfer(",
    "WarehouseLedger",
    "InventoryLedger",
):
    if legacy_symbol in core:
        fail(f"legacy symbol still present in migrated sections 6-10: {legacy_symbol}")

required_new = [
    "InventoryBalance",
    "InventoryTransferHeader",
    "InventoryTransferLine",
    "DispatchLoadPlanLine",
    "apply_inventory_movements_batch",
    "allocate_fefo_inventory_batch",
    "source_location_id=int(source_location.id)",
]
for needle in required_new:
    if needle not in core:
        fail(f"required unified inventory marker missing: {needle}")

BACKUP_DIR.mkdir(parents=True, exist_ok=True)
backup = BACKUP_DIR / "dispatch.py.before_unified_inventory_core"
if not backup.exists():
    shutil.copy2(TARGET, backup)

TARGET.write_text(text, encoding="utf-8", newline="\n")

print("DISPATCH_UNIFIED_INVENTORY_CORE_OK")
print("MORNING_LOAD_OK: explicit source_location_id + FEFO + InventoryMovement only")
print("MIDDAY_OK: HANDSHAKE Header/Lines + source reservation; no physical move before driver decision")
print("VEHICLE_READ_OK: InventoryBalance is the only live vehicle stock source in sections 7-8")
print("TRANSFER_VIEW_OK: admin transfer monitor reads InventoryTransferHeader/Line")
print("PLAN_OK: DispatchLoadPlanLine stores target plan only; never used as live stock")
print("MULTI_WAREHOUSE_OK: no first-active-warehouse inference in migrated core")
print("WORKFLOW_OK: active WorkSession cannot receive a new route; use current-route HANDSHAKE adjustments")
print("FILE_CHANGED: wa_backend/api/dispatch.py only")
print("NEXT: py_compile + git diff --check, then PostgreSQL core-dispatch E2E")
