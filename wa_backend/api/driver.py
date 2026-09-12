from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, update, or_, and_, delete, case
from sqlalchemy.orm import joinedload, contains_eager, selectinload
from sqlalchemy.exc import IntegrityError
from database import get_db
from typing import List
from api.dependencies import get_current_driver
from datetime import datetime, timezone
from decimal import Decimal
from services import (
    reverse_previous_visit_state,
    InventoryReversalError,
    InventoryMutationError,
    get_setting,
    calculate_invoice,
    check_debt_limits,
    check_inventory_lock,
    acquire_inventory_location_guard,
    get_company_local_date,
    allocate_fefo_inventory_batch,
    apply_inventory_movements_batch,
    begin_idempotent_operation,
    complete_idempotent_operation,
)
import hashlib
import json
import logging

from models import (
    Driver, WorkSession, DispatchRoute, Visit,
    WorkBreakLog, VisitItem, Shop, ProductVariant, VisitReturn, OfferRule, Zone,
    ShortageRequest, SystemAuditLog,
    InventoryLocation, InventoryBalance, InventoryMovement, ProductBatch,
    InventoryTransferHeader, InventoryTransferLine,
    SessionInventorySnapshot,
)

from schemas import (SessionStartRequest, BreakToggleRequest, TransferResponseRequest,
BatchTransferResponseRequest, PendingBatchResponse, AddShopRequest, ProductVariantResponse,
GetVisitsContract, VisitDetailsResponse, ActiveSessionResponse, VisitUpdateRequest,)
from product_lifecycle import (
    INBOUND_COMPLETE,
    ROUTE_SALE_OPEN,
    acquire_product_lifecycle_guards,
    evaluate_product_capability,
    product_capability_predicate,
)

logger = logging.getLogger("wanasah_logger")

def get_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
    
router = APIRouter(tags=["Driver Operations"])
# =========================================
# 1. بدء جلسة العمل (مربوطة بالتوزيع والجرد)
# =========================================
@router.post("/driver/sessions/start", status_code=201)
async def start_work_session(
    payload: SessionStartRequest,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    driver_id = current_driver.id
    company_id = current_driver.company_id

    try:
        # Lock order يبدأ بالمندوب لمنع تشغيل جلستين متوازيتين لنفس الهوية.
        locked_driver = (
            await db.execute(
                select(Driver)
                .filter_by(
                    company_id=company_id,
                    id=driver_id,
                )
                .order_by(Driver.id.asc())
                .with_for_update()
            )
        ).scalar_one_or_none()

        if locked_driver is None:
            await db.rollback()
            raise HTTPException(
                status_code=403,
                detail="حساب المندوب غير موجود أو لا يتبع الشركة الحالية."
            )

        # تاريخ العمل يُحسم بتوقيت الشركة قبل اختيار Route؛ لا نقبل Route قديم بقي active بالخطأ.
        company_local_date = await get_company_local_date(db, company_id)

        # لا يوم جديد قبل تسوية العهدة السابقة.
        unsettled_session = (
            await db.execute(
                select(WorkSession)
                .filter(
                    WorkSession.company_id == company_id,
                    WorkSession.driver_id == driver_id,
                    WorkSession.is_settled.is_(False),
                    WorkSession.end_time.is_not(None),
                )
                .order_by(WorkSession.id.desc())
                .limit(1)
            )
        ).scalars().first()

        if unsettled_session:
            await db.rollback()
            raise HTTPException(
                status_code=400,
                detail="لا يمكنك بدء يوم عمل جديد. لديك عهدة سابقة معلقة لم يتم تسويتها من قبل الإدارة."
            )

        # خط السير الفعال يجب أن يكون من نفس الشركة ونفس المندوب.
        active_route = (
            await db.execute(
                select(DispatchRoute)
                .filter_by(
                    company_id=company_id,
                    driver_id=driver_id,
                    dispatch_date=company_local_date,
                    status="active",
                )
                .order_by(DispatchRoute.id.asc())
                .with_for_update()
            )
        ).scalars().first()

        if active_route is None:
            await db.rollback()
            raise HTTPException(
                status_code=400,
                detail="لا يوجد لديك خط سير مخصص اليوم. الرجاء مراجعة مدير التوزيع."
            )

        if active_route.vehicle_id is None:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail="خط السير الحالي غير مربوط بسيارة. لا يمكن بدء الجلسة قبل تصحيح التوزيع."
            )

        if active_route.work_session_id is not None:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail="خط السير الحالي مربوط مسبقاً بجلسة عمل أخرى."
            )

        existing_session = (
            await db.execute(
                select(WorkSession)
                .filter_by(
                    company_id=company_id,
                    driver_id=driver_id,
                    end_time=None,
                )
                .order_by(WorkSession.id.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalars().first()

        if existing_session:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail="لديك جلسة عمل نشطة بالفعل لم يتم إنهاؤها."
            )

        # حل موقع السيارة حصراً داخل Tenant الحالي.
        vehicle_location_id = (
            await db.execute(
                select(InventoryLocation.id)
                .filter_by(
                    company_id=company_id,
                    vehicle_id=active_route.vehicle_id,
                    location_type="VEHICLE",
                    is_active=True,
                )
            )
        ).scalar_one_or_none()

        if vehicle_location_id is None:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail="السيارة المخصصة لا تملك موقع مخزون VEHICLE فعالاً داخل الشركة."
            )

        # Snapshot حقيقي لنقطة زمنية واحدة:
        # نمنع أي حركة مخزون على السيارة حتى تثبيت اللقطة والجلسة في نفس Transaction.
        await acquire_inventory_location_guard(
            db,
            company_id,
            vehicle_location_id,
            exclusive=True,
        )

        # إعادة التحقق بعد امتلاك القفل.
        locked_vehicle_location_id = (
            await db.execute(
                select(InventoryLocation.id)
                .filter_by(
                    company_id=company_id,
                    id=vehicle_location_id,
                    vehicle_id=active_route.vehicle_id,
                    location_type="VEHICLE",
                    is_active=True,
                )
                .with_for_update(read=True)
            )
        ).scalar_one_or_none()

        if locked_vehicle_location_id is None:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail="موقع مخزون السيارة تغير أو أصبح غير فعال أثناء بدء الجلسة."
            )

        new_session = WorkSession(
            company_id=company_id,
            driver_id=driver_id,
            session_date=company_local_date,
            start_time=get_utc_now(),
            start_latitude=payload.latitude,
            start_longitude=payload.longitude,
            is_authorized_to_sell=False,
        )
        db.add(new_session)
        await db.flush()

        active_route.work_session_id = new_session.id

        # Opening custody snapshot.
        # InventoryBalance يبقى الرصيد الحي؛ هذه مجرد صورة تاريخية غير قابلة للتعديل أثناء اليوم.
        opening_rows = (
            await db.execute(
                select(
                    InventoryBalance.product_variant_id,
                    InventoryBalance.stock_status,
                    func.sum(InventoryBalance.on_hand_quantity),
                )
                .filter(
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.location_id == vehicle_location_id,
                    InventoryBalance.on_hand_quantity > 0,
                )
                .group_by(
                    InventoryBalance.product_variant_id,
                    InventoryBalance.stock_status,
                )
                .order_by(
                    InventoryBalance.product_variant_id.asc(),
                    InventoryBalance.stock_status.asc(),
                )
            )
        ).all()

        for product_variant_id, stock_status, starting_quantity in opening_rows:
            qty = int(starting_quantity or 0)
            normalized_status = str(stock_status or "").upper()

            if normalized_status not in {
                "AVAILABLE", "QUARANTINED", "BLOCKED", "RECALLED",
                "DAMAGED", "DISPOSAL_PENDING",
            }:
                raise RuntimeError("Vehicle opening inventory has unsupported stock_status.")
            if qty < 0 or qty > 2_147_483_647:
                raise RuntimeError(
                    "Vehicle opening inventory exceeds SessionInventorySnapshot INTEGER bounds."
                )

            db.add(
                SessionInventorySnapshot(
                    company_id=company_id,
                    work_session_id=new_session.id,
                    location_id=vehicle_location_id,
                    product_variant_id=product_variant_id,
                    stock_status=normalized_status,
                    starting_quantity=qty,
                )
            )

        # نفس Workflow القديم للزيارات، لكن Tenant-safe.
        subq_shops = (
            select(Shop.id)
            .where(
                Shop.company_id == company_id,
                Shop.zone_id == active_route.zone_id,
            )
            .scalar_subquery()
        )

        await db.execute(
            update(Visit)
            .where(
                Visit.company_id == company_id,
                Visit.driver_id == driver_id,
                Visit.status == "Pending",
                or_(
                    and_(
                        Visit.shop_id.in_(subq_shops),
                        Visit.operational_date == company_local_date,
                    ),
                    Visit.is_emergency.is_(True),
                ),
            )
            .values(
                work_session_id=new_session.id,
            )
        )

        await db.commit()

        return {
            "message": "تم بدء الجلسة بنجاح، وتم تثبيت رصيد السيارة الافتتاحي.",
            "session_id": new_session.id,
        }

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في بدء جلسة العمل: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="خطأ داخلي أثناء بدء الجلسة."
        )

# =========================================
# 2. إنهاء جلسة العمل
# =========================================
@router.put("/driver/sessions/end", status_code=200)
async def end_work_session(
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    company_id = current_driver.company_id
    driver_id = current_driver.id

    try:
        active_session = (
            await db.execute(
                select(WorkSession)
                .filter_by(
                    company_id=company_id,
                    driver_id=driver_id,
                    end_time=None,
                )
                .order_by(WorkSession.id.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalars().first()

        if active_session is None:
            raise HTTPException(status_code=404, detail="No active session")

        if active_session.break_start_time and not active_session.break_end_time:
            raise HTTPException(
                status_code=400,
                detail="مرفوض أمنياً: أنت الآن في وقت الاستراحة. يجب إنهاء الاستراحة أولاً قبل إنهاء يوم العمل.",
            )

        pending_handshake = (
            await db.execute(
                select(InventoryTransferHeader.id)
                .filter(
                    InventoryTransferHeader.company_id == company_id,
                    InventoryTransferHeader.work_session_id == active_session.id,
                    InventoryTransferHeader.workflow_type == "HANDSHAKE",
                    InventoryTransferHeader.status == "PENDING",
                    InventoryTransferHeader.expected_receiver_id == driver_id,
                )
                .order_by(InventoryTransferHeader.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if pending_handshake is not None:
            raise HTTPException(
                status_code=400,
                detail="لا يمكنك إنهاء العمل! لديك حوالات معلقة من الإدارة (مصافحة) يجب الموافقة عليها أو رفضها أولاً.",
            )

        # التسوية ليست مسؤولية هذا endpoint؛ هو يغلق يوم العمل فقط.
        active_session.end_time = get_utc_now()
        await db.commit()
        return {"message": "تم إنهاء الجلسة بنجاح."}

    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في إنهاء جلسة العمل: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء إنهاء الجلسة.") from exc

# =========================================
# 3. تسجيل وقت الاستراحة
# =========================================

@router.put("/driver/sessions/break", status_code=200)
async def toggle_break(
    payload: BreakToggleRequest,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    company_id = current_driver.company_id
    driver_id = current_driver.id

    try:
        active_session = (
            await db.execute(
                select(WorkSession)
                .filter_by(
                    company_id=company_id,
                    driver_id=driver_id,
                    end_time=None,
                )
                .order_by(WorkSession.id.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalars().first()

        if active_session is None:
            raise HTTPException(status_code=404, detail="لا توجد جلسة عمل نشطة حالياً.")

        action = payload.action

        if action == "start":
            if active_session.break_start_time and not active_session.break_end_time:
                raise HTTPException(status_code=400, detail="الاستراحة بدأت بالفعل.")

            active_session.break_start_time = get_utc_now()
            active_session.break_end_time = None
            msg = "تم بدء الاستراحة بنجاح."

        elif action == "end":
            if not active_session.break_start_time or active_session.break_end_time:
                raise HTTPException(status_code=400, detail="لا يوجد استراحة نشطة لإنهائها.")

            end_t = get_utc_now()
            break_start = active_session.break_start_time
            duration = int((end_t - break_start).total_seconds() / 60) if break_start else 0

            db.add(
                WorkBreakLog(
                    company_id=company_id,
                    work_session_id=active_session.id,
                    break_start=active_session.break_start_time,
                    break_end=end_t,
                    duration_minutes=duration,
                )
            )

            active_session.break_start_time = None
            active_session.break_end_time = None
            msg = "تم إنهاء الاستراحة وتوثيق مدتها بنجاح."
        else:
            raise HTTPException(status_code=400, detail="إجراء الاستراحة غير صالح.")

        await db.commit()
        return {"message": msg}

    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في تسجيل الاستراحة: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي أثناء تسجيل الاستراحة.") from exc

# =========================================
# 4. تحديث نتيجة الزيارة (Update Visit) - النسخة الفولاذية المعدلة
# =========================================
@router.put("/visits/{visit_id}", status_code=200)
async def update_visit(
    visit_id: int,
    payload: VisitUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    # PATCH: DRIVER_UNIFIED_VISIT_INVENTORY
    # Workflow الميدان محفوظ؛ التغيير هنا محصور في العزل ومحرك المخزون الموحد والـidempotency.
    company_id = current_driver.company_id
    driver_id = current_driver.id

    canonical_payload = payload.model_dump(mode="json", exclude={"request_id"})
    # ترتيب أسطر Flutter ليس جزءاً من المعنى التجاري؛ retry مطابق لا يفشل لمجرد إعادة ترتيب القوائم.
    canonical_payload["cart_items"] = sorted(
        canonical_payload.get("cart_items", []),
        key=lambda item: int(item["product_variant_id"]),
    )
    canonical_payload["returns"] = sorted(
        canonical_payload.get("returns", []),
        key=lambda item: (
            int(item["product_variant_id"]),
            int(item["batch_id"]),
            str(item["return_type"]),
        ),
    )
    request_hash = hashlib.sha256(
        json.dumps(
            {"visit_id": visit_id, "payload": canonical_payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    try:
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=driver_id,
            operation="DRIVER_UPDATE_VISIT",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )

        if replay_response is not None:
            await db.rollback()
            return replay_response

        # Lock order: idempotency -> session -> shop -> visit -> inventory.
        active_session = (
            await db.execute(
                select(WorkSession)
                .filter_by(
                    company_id=company_id,
                    driver_id=driver_id,
                    end_time=None,
                )
                .order_by(WorkSession.id.asc())
                .limit(1)
                .with_for_update()
            )
        ).scalars().first()

        if active_session is None:
            raise HTTPException(
                status_code=403,
                detail="لا يمكنك تنفيذ العملية. الرجاء بدء يوم العمل أولاً.",
            )
        if active_session.inventory_reconciled_at is not None:
            raise HTTPException(
                status_code=409,
                detail="مرفوض: عهدة مخزون هذه الجلسة تم ختمها ولا تقبل أي تعديل ميداني جديد.",
            )

        # Tenant-safe probe لمعرفة shop_id فقط؛ لا نكشف زيارة خارج الشركة/المندوب.
        visit_shop_id = (
            await db.execute(
                select(Visit.shop_id).filter_by(
                    company_id=company_id,
                    id=visit_id,
                    driver_id=driver_id,
                )
            )
        ).scalar_one_or_none()

        if visit_shop_id is None:
            raise HTTPException(status_code=404, detail="الزيارة غير موجودة")

        shop = (
            await db.execute(
                select(Shop)
                .filter_by(company_id=company_id, id=visit_shop_id)
                .order_by(Shop.id.asc())
                .with_for_update()
            )
        ).scalar_one_or_none()

        if shop is None:
            raise HTTPException(
                status_code=404,
                detail="المحل المربوط بالزيارة غير موجود في النظام.",
            )

        visit = (
            await db.execute(
                select(Visit)
                .options(
                    selectinload(Visit.work_session),
                    selectinload(Visit.items).selectinload(VisitItem.product_variant),
                    selectinload(Visit.returns),
                )
                .filter_by(
                    company_id=company_id,
                    id=visit_id,
                    driver_id=driver_id,
                )
                .order_by(Visit.id.asc())
                .with_for_update()
            )
        ).scalars().first()

        if visit is None or visit.shop_id != shop.id:
            raise HTTPException(status_code=404, detail="الزيارة غير موجودة")

        locked_original_status = visit.status

        if visit.status == "Cancelled":
            raise HTTPException(
                status_code=403,
                detail=(
                    "مرفوض أمنياً: هذه الزيارة تم إلغاؤها من قبل الإدارة "
                    "(أو المنطقة مؤرشفة). لا يمكنك التعديل عليها."
                ),
            )

        visit.shop = shop

        if visit.work_session and visit.work_session.inventory_reconciled_at is not None:
            raise HTTPException(
                status_code=409,
                detail="مرفوض: لا يمكن تعديل زيارة بعد ختم التسوية المخزنية لجلسة العمل.",
            )
        if visit.work_session and visit.work_session.is_settled:
            raise HTTPException(
                status_code=403,
                detail="مرفوض: لا يمكن تعديل زيارة تم تسويتها ماليًا واعتمادها من الإدارة.",
            )

        if visit.driver_id != driver_id:
            raise HTTPException(
                status_code=403,
                detail="مرفوض أمنياً: لا تملك صلاحية التعديل على هذه الزيارة.",
            )

        if visit.work_session_id is not None and visit.work_session_id != active_session.id:
            raise HTTPException(
                status_code=409,
                detail="الزيارة مرتبطة بجلسة عمل أخرى ولا يجوز نقلها بين الجلسات أثناء التحديث.",
            )

        current_route = (
            await db.execute(
                select(DispatchRoute)
                .filter_by(
                    company_id=company_id,
                    work_session_id=active_session.id,
                    driver_id=driver_id,
                    status="active",
                )
                .order_by(DispatchRoute.id.asc())
                .limit(1)
                .with_for_update(read=True)
            )
        ).scalars().first()

        if current_route is None:
            raise HTTPException(
                status_code=403,
                detail="تم سحب خط السير أو إيقافه من قبل الإدارة. لا يمكنك إتمام العملية.",
            )

        if current_route.vehicle_id is None:
            raise HTTPException(
                status_code=409,
                detail="خط السير الحالي غير مربوط بسيارة صالحة للمخزون.",
            )

        has_active_shortage = (
            await db.execute(
                select(ShortageRequest.id)
                .filter(
                    ShortageRequest.company_id == company_id,
                    ShortageRequest.shop_id == shop.id,
                    ShortageRequest.status == "pending",
                    or_(
                        ShortageRequest.driver_id.is_(None),
                        ShortageRequest.driver_id == driver_id,
                    ),
                )
                .limit(1)
            )
        ).scalar_one_or_none() is not None

        is_emergency_request = payload.is_emergency or visit.is_emergency
        if shop.zone_id != current_route.zone_id and not (
            is_emergency_request or has_active_shortage
        ):
            raise HTTPException(
                status_code=403,
                detail=(
                    "مرفوض أمنياً: لا يمكنك البيع لمحل خارج منطقة عملك المخصصة "
                    "إلا بتصريح طلب عاجل."
                ),
            )

        veh_loc_id = (
            await db.execute(
                select(InventoryLocation.id).filter_by(
                    company_id=company_id,
                    vehicle_id=current_route.vehicle_id,
                    location_type="VEHICLE",
                    is_active=True,
                )
            )
        ).scalar_one_or_none()

        if veh_loc_id is None:
            raise HTTPException(
                status_code=409,
                detail="السيارة الحالية لا تملك موقع مخزون VEHICLE فعالاً داخل الشركة.",
            )

        try:
            await check_inventory_lock(db, company_id, veh_loc_id)

            touched_variants = sorted(
                {item.product_variant_id for item in payload.cart_items}
                | {ret.product_variant_id for ret in payload.returns}
            )
            for variant_id in touched_variants:
                await check_inventory_lock(
                    db,
                    company_id,
                    veh_loc_id,
                    variant_id=variant_id,
                )

            # المرتجع يدخل Batch بعينه، لذلك لا يجوز تجاوز قفل Batch محدد.
            for ret in payload.returns:
                await check_inventory_lock(
                    db,
                    company_id,
                    veh_loc_id,
                    variant_id=ret.product_variant_id,
                    batch_id=ret.batch_id,
                )
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail=f"تم تجميد مبيعات سيارتك مؤقتاً لمراجعة العهدة: {str(exc)}",
            ) from exc

        if active_session.break_start_time and not active_session.break_end_time:
            raise HTTPException(
                status_code=403,
                detail="أنت الآن في وقت الاستراحة. قم بإنهاء الاستراحة لمتابعة العمل.",
            )

        if not active_session.is_authorized_to_sell:
            raise HTTPException(
                status_code=403,
                detail="غير مصرح لك بإجراء عمليات بيع حالياً. بانتظار تفعيل خط السير من الإدارة.",
            )

        pending_handshake = (
            await db.execute(
                select(InventoryTransferHeader.id)
                .filter(
                    InventoryTransferHeader.company_id == company_id,
                    InventoryTransferHeader.work_session_id == active_session.id,
                    InventoryTransferHeader.workflow_type == "HANDSHAKE",
                    InventoryTransferHeader.status == "PENDING",
                    InventoryTransferHeader.expected_receiver_id == driver_id,
                )
                .order_by(InventoryTransferHeader.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if pending_handshake is not None:
            raise HTTPException(
                status_code=403,
                detail=(
                    "مرفوض: لديك حوالة معلقة من الإدارة (مصافحة). "
                    "يرجى تأكيدها أو رفضها أولاً."
                ),
            )

        if visit.status == "Completed":
            await reverse_previous_visit_state(
                db,
                visit,
                active_session,
                shop,
                admin_id=driver_id,
            )

        debt_paid_input = Decimal(str(payload.debt_paid))
        original_shop_balance = Decimal(str(shop.current_balance or "0.000"))
        cash_collected = Decimal(str(payload.cash_collected))

        if debt_paid_input < Decimal("0") or cash_collected < Decimal("0"):
            raise HTTPException(
                status_code=400,
                detail="مرفوض أمنياً: لا يمكن إدخال قيم مالية سالبة في التحصيل أو النقد.",
            )

        if debt_paid_input > Decimal("0"):
            if original_shop_balance <= Decimal("0"):
                raise HTTPException(
                    status_code=400,
                    detail=f"مرفوض: المحل رصيده دائن أو مُصفر ({original_shop_balance}). لا توجد ذمم.",
                )
            if debt_paid_input > original_shop_balance:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"مرفوض: التحصيل ({debt_paid_input}) أكبر من ذمة المحل "
                        f"({original_shop_balance})."
                    ),
                )

        if visit.status == "Pending":
            visit.visit_timestamp = get_utc_now()

        visit.outcome = payload.outcome
        visit.status = "Completed" if payload.outcome in {"Sale", "NoSale"} else "Pending"
        visit.notes = payload.notes
        visit.latitude = payload.latitude if payload.latitude is not None else visit.latitude
        visit.longitude = payload.longitude if payload.longitude is not None else visit.longitude
        visit.shop_balance_before = original_shop_balance
        visit.is_emergency = payload.is_emergency or visit.is_emergency
        visit.work_session_id = active_session.id

        if payload.outcome == "Postponed" and (
            payload.cart_items
            or payload.returns
            or payload.debt_paid > Decimal("0")
            or payload.cash_collected > Decimal("0")
        ):
            raise HTTPException(
                status_code=400,
                detail="مرفوض أمنياً: لا يمكن تسجيل مبيعات أو مرتجعات أو تحصيل لزيارة حالتها (مؤجلة).",
            )

        has_real_sales = any(
            item.quantity > 0 or item.packs_quantity > 0
            for item in payload.cart_items
        )
        if payload.outcome == "NoSale" and (
            has_real_sales or cash_collected > Decimal("0")
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "مرفوض أمنياً: لا يمكن تسجيل مبيعات حقيقية أو كاش نقدي لحالة "
                    "(لا يوجد بيع). يسمح بالمرتجعات والعينات فقط، أو تحصيل ديون سابقة."
                ),
            )

        cart_pids = [item.product_variant_id for item in payload.cart_items]
        ret_keys = [
            (ret.product_variant_id, ret.batch_id, ret.return_type)
            for ret in payload.returns
        ]
        if len(cart_pids) != len(set(cart_pids)):
            raise HTTPException(
                status_code=400,
                detail="مرفوض أمنياً: سلة المبيعات تحتوي على أصناف مكررة.",
            )
        if len(ret_keys) != len(set(ret_keys)):
            raise HTTPException(
                status_code=400,
                detail="مرفوض أمنياً: المرتجعات تحتوي السطر نفسه (الصنف/الدفعة/النوع) أكثر من مرة.",
            )
        if payload.outcome == "Sale" and not payload.cart_items:
            raise HTTPException(
                status_code=400,
                detail="مرفوض أمنياً: لا يمكن تسجيل حالة (بيع) دون وجود منتجات فعلية في السلة.",
            )

        all_var_ids = sorted(
            set(cart_pids + [ret.product_variant_id for ret in payload.returns])
        )
        await acquire_product_lifecycle_guards(
            db, company_id, all_var_ids, exclusive=False,
        )
        variants_map = {}
        if all_var_ids:
            variant_rows = (
                await db.execute(
                    select(ProductVariant)
                    .filter(
                        ProductVariant.company_id == company_id,
                        ProductVariant.id.in_(all_var_ids),
                    )
                    .order_by(ProductVariant.id.asc())
                )
            ).scalars().all()
            variants_map = {variant.id: variant for variant in variant_rows}
            missing_variants = sorted(set(all_var_ids) - set(variants_map))
            if missing_variants:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "أحد المنتجات غير موجود أو لا يتبع الشركة الحالية: "
                        f"{missing_variants[:10]}"
                    ),
                )

        # Batch المرتجع قد يكون منتهياً/غير فعال، لكنه يجب أن يكون حقيقياً ومن نفس الصنف والشركة.
        return_batch_ids = sorted({ret.batch_id for ret in payload.returns})
        if return_batch_ids:
            batch_rows = (
                await db.execute(
                    select(ProductBatch.id, ProductBatch.product_variant_id)
                    .filter(
                        ProductBatch.company_id == company_id,
                        ProductBatch.id.in_(return_batch_ids),
                    )
                    .order_by(ProductBatch.id.asc())
                )
            ).all()
            return_batch_map = {
                int(batch_id): int(product_variant_id)
                for batch_id, product_variant_id in batch_rows
            }
            if set(return_batch_map) != set(return_batch_ids):
                raise HTTPException(
                    status_code=400,
                    detail="إحدى دفعات المرتجع غير موجودة أو لا تتبع الشركة الحالية.",
                )
            for ret in payload.returns:
                if return_batch_map.get(ret.batch_id) != ret.product_variant_id:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"الدفعة ({ret.batch_id}) لا تتبع الصنف "
                            f"({ret.product_variant_id}) المحدد في المرتجع."
                        ),
                    )

        for variant in variants_map.values():
            if variant.packs_per_carton is None or int(variant.packs_per_carton) <= 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"إعداد عدد الحبات في الكرتونة غير صالح للصنف ({variant.variant_name}).",
                )

        company_local_date = await get_company_local_date(db, company_id)

        sample_items = [
            item
            for item in payload.cart_items
            if item.sample_quantity > 0 or item.sample_packs_quantity > 0
        ]
        if sample_items:
            sample_pids = sorted({item.product_variant_id for item in sample_items})
            past_rows = (
                await db.execute(
                    select(
                        VisitItem.product_variant_id,
                        func.sum(
                            VisitItem.sample_quantity * ProductVariant.packs_per_carton
                            + VisitItem.sample_packs_quantity
                        ),
                    )
                    .join(
                        Visit,
                        and_(
                            Visit.company_id == VisitItem.company_id,
                            Visit.id == VisitItem.visit_id,
                        ),
                    )
                    .join(
                        ProductVariant,
                        and_(
                            ProductVariant.company_id == VisitItem.company_id,
                            ProductVariant.id == VisitItem.product_variant_id,
                        ),
                    )
                    .join(
                        WorkSession,
                        and_(
                            WorkSession.company_id == Visit.company_id,
                            WorkSession.id == Visit.work_session_id,
                        ),
                    )
                    .filter(
                        VisitItem.company_id == company_id,
                        Visit.company_id == company_id,
                        Visit.driver_id == driver_id,
                        WorkSession.company_id == company_id,
                        WorkSession.driver_id == driver_id,
                        WorkSession.session_date == company_local_date,
                        Visit.status == "Completed",
                        VisitItem.product_variant_id.in_(sample_pids),
                        VisitItem.is_cancelled.is_(False),
                    )
                    .group_by(VisitItem.product_variant_id)
                )
            ).all()
            past_samples_map = {
                int(product_variant_id): int(total or 0)
                for product_variant_id, total in past_rows
            }

            for item in sample_items:
                variant = variants_map[item.product_variant_id]
                ppc = int(variant.packs_per_carton)
                requested_packs = item.sample_quantity * ppc + item.sample_packs_quantity
                past_packs = past_samples_map.get(item.product_variant_id, 0)
                max_allowed_packs = (
                    int(getattr(variant, "default_max_samples_per_day", 0) or 0) * ppc
                )
                # نحافظ على Workflow الحالي: صفر = لا يوجد سقف مفعل حالياً.
                if max_allowed_packs > 0 and past_packs + requested_packs > max_allowed_packs:
                    max_cartons = max_allowed_packs // ppc
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "مرفوض أمنياً: تجاوزت الحد المسموح من العينات لمنتج "
                            f"({variant.variant_name}). المسموح لك باليوم: {max_cartons} كرتونة."
                        ),
                    )

        if locked_original_status == "Pending":
            for existing_item in list(visit.items):
                await db.delete(existing_item)
            for existing_return in list(visit.returns):
                await db.delete(existing_return)
            visit.items.clear()
            visit.returns.clear()
        else:
            for existing_item in visit.items:
                if not getattr(existing_item, "is_cancelled", False):
                    existing_item.is_cancelled = True
            for existing_return in visit.returns:
                if not getattr(existing_return, "is_cancelled", False):
                    existing_return.is_cancelled = True

        total_final_amount = Decimal("0.000")
        total_base_amount = Decimal("0.000")
        total_discount = Decimal("0.000")
        total_tax = Decimal("0.000")

        current_tax_pct = await get_setting(
            db,
            company_id,
            "tax_percentage",
            Decimal("0.000"),
            Decimal,
            strict_conversion=True,
        )
        active_offers = (
            await db.execute(
                select(OfferRule)
                .filter_by(company_id=company_id, is_active=True)
                .order_by(OfferRule.threshold_quantity.desc(), OfferRule.id.asc())
            )
        ).scalars().all()

        item_contexts = []
        return_contexts = []
        outgoing_requests = {}

        # Pass 1: نحسب الفاتورة والبونص أولاً ثم نجمع طلب FEFO لكل صنف.
        for line_index, item in enumerate(payload.cart_items):
            variant = variants_map[item.product_variant_id]
            sale_capability = evaluate_product_capability(
                variant.lifecycle_status,
                variant.operational_hold,
                ROUTE_SALE_OPEN,
            )
            if not sale_capability.allowed:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": sale_capability.code,
                        "message": f"مرفوض: لا يمكن بيع المنتج ({variant.variant_name}) في حالته الحالية.",
                    },
                )

            ppc = int(variant.packs_per_carton)
            invoice = calculate_invoice(
                item.quantity,
                item.packs_quantity,
                variant.price_per_carton,
                variant.price_per_pack,
                current_tax_pct,
                active_offers,
                company_id=company_id,
                packs_per_carton=ppc,
                variant_id=item.product_variant_id,
            )
            final_bonus_cartons = int(invoice["bonus_units"])
            total_issue_packs = (
                item.quantity * ppc
                + item.packs_quantity
                + final_bonus_cartons * ppc
                + item.sample_quantity * ppc
                + item.sample_packs_quantity
            )
            if total_issue_packs > 0:
                outgoing_requests[item.product_variant_id] = (
                    outgoing_requests.get(item.product_variant_id, 0) + total_issue_packs
                )

            item_contexts.append(
                {
                    "line_index": line_index,
                    "item": item,
                    "variant": variant,
                    "invoice": invoice,
                    "bonus_cartons": final_bonus_cartons,
                    "total_issue_packs": total_issue_packs,
                }
            )
            total_final_amount += Decimal(str(invoice["final_amount"]))
            total_base_amount += Decimal(str(invoice["base_amount"]))
            total_discount += Decimal(str(invoice["discount_applied"]))
            total_tax += Decimal(str(invoice["tax_amount"]))

        # Workflow المرتجع محفوظ: استبدال 1:1، لكن الوارد التالف يحمل Batch صريحاً.
        for return_index, ret in enumerate(payload.returns):
            variant = variants_map[ret.product_variant_id]
            ppc = int(variant.packs_per_carton)
            total_return_packs = ret.quantity * ppc + ret.packs_quantity
            outgoing_requests[ret.product_variant_id] = (
                outgoing_requests.get(ret.product_variant_id, 0) + total_return_packs
            )
            return_contexts.append(
                {
                    "return_index": return_index,
                    "ret": ret,
                    "variant": variant,
                    "total_return_packs": total_return_packs,
                }
            )

        # كل سطر مالي آمن منفرداً في calculate_invoice؛ هنا نحمي مجموع مئات الأسطر قبل PostgreSQL.
        money_limit = Decimal("999999999.999")
        for money_label, money_value in (
            ("amount_before_tax_and_discount", total_base_amount),
            ("discount_applied", total_discount),
            ("tax_amount", total_tax),
            ("final_amount_due", total_final_amount),
        ):
            if not money_value.is_finite() or money_value < 0 or money_value > money_limit:
                raise HTTPException(
                    status_code=400,
                    detail=f"القيمة المجمعة ({money_label}) تتجاوز السعة المالية المسموحة.",
                )

        fefo_allocations = {}
        if outgoing_requests:
            fefo_allocations = await allocate_fefo_inventory_batch(
                db,
                company_id=company_id,
                location_id=veh_loc_id,
                requests=outgoing_requests,
                as_of_date=company_local_date,
                require_full=True,
            )

        allocation_state = {
            variant_id: [[int(batch_id), int(quantity)] for batch_id, quantity in allocations]
            for variant_id, allocations in fefo_allocations.items()
        }

        def consume_fefo(variant_id: int, quantity: int):
            if quantity <= 0:
                return []
            buckets = allocation_state.get(variant_id, [])
            remaining = quantity
            consumed = []
            for bucket in buckets:
                if remaining <= 0:
                    break
                batch_id, available = bucket
                if available <= 0:
                    continue
                take = min(available, remaining)
                consumed.append((batch_id, take))
                bucket[1] -= take
                remaining -= take
            if remaining != 0:
                raise RuntimeError(
                    f"FEFO allocation invariant violated for variant {variant_id}."
                )
            return consumed

        movement_specs = []
        request_token = str(payload.request_id)

        # البيع/البونص/العينات: شاشة المندوب لا ترى Batch؛ الخادم يستهلك FEFO تلقائياً.
        for ctx in item_contexts:
            item = ctx["item"]
            variant = ctx["variant"]
            for segment_index, (batch_id, qty) in enumerate(
                consume_fefo(item.product_variant_id, ctx["total_issue_packs"])
            ):
                movement_specs.append(
                    {
                        "product_variant_id": item.product_variant_id,
                        "batch_id": batch_id,
                        "quantity": qty,
                        "movement_kind": "PHYSICAL",
                        "reference_type": "VISIT_ITEM_OUT",
                        "reference_id": str(visit.id),
                        "idempotency_key": (
                            f"VIS-{visit.id}-{request_token}-I{ctx['line_index']}-"
                            f"B{batch_id}-S{segment_index}"
                        ),
                        "source_location_id": veh_loc_id,
                        "destination_location_id": None,
                        "source_stock_status": "AVAILABLE",
                        "destination_stock_status": None,
                        "work_session_id": active_session.id,
                        "notes": (
                            f"صرف زيارة للمحل {shop.name}: "
                            f"بيع={item.quantity} كرتونة + {item.packs_quantity} حبة، "
                            f"بونص={ctx['bonus_cartons']} كرتونة، "
                            f"عينات={item.sample_quantity} كرتونة + {item.sample_packs_quantity} حبة."
                        ),
                    }
                )

            db.add(
                VisitItem(
                    company_id=company_id,
                    visit_id=visit.id,
                    product_variant_id=item.product_variant_id,
                    quantity=item.quantity,
                    packs_quantity=item.packs_quantity,
                    bonus_quantity=ctx["bonus_cartons"],
                    sample_quantity=item.sample_quantity,
                    sample_packs_quantity=item.sample_packs_quantity,
                    sample_reason=item.sample_reason,
                    price_per_unit_at_sale=variant.price_per_carton,
                    total_price=Decimal(str(ctx["invoice"]["final_amount"])),
                )
            )

        # المرتجع: البديل الصالح يخرج FEFO، والمرتجع نفسه يدخل DAMAGED على Batch الممسوح.
        for ctx in return_contexts:
            ret = ctx["ret"]
            total_return_packs = ctx["total_return_packs"]
            for segment_index, (batch_id, qty) in enumerate(
                consume_fefo(ret.product_variant_id, total_return_packs)
            ):
                movement_specs.append(
                    {
                        "product_variant_id": ret.product_variant_id,
                        "batch_id": batch_id,
                        "quantity": qty,
                        "movement_kind": "PHYSICAL",
                        "reference_type": "VISIT_EXCHANGE_OUT",
                        "reference_id": str(visit.id),
                        "idempotency_key": (
                            f"VIS-{visit.id}-{request_token}-X{ctx['return_index']}-"
                            f"B{batch_id}-S{segment_index}"
                        ),
                        "source_location_id": veh_loc_id,
                        "destination_location_id": None,
                        "source_stock_status": "AVAILABLE",
                        "destination_stock_status": None,
                        "work_session_id": active_session.id,
                        "notes": (
                            f"استبدال 1:1 للمحل {shop.name}; "
                            f"إخراج بضاعة صالحة مقابل مرتجع {ret.return_type}."
                        ),
                    }
                )

            movement_specs.append(
                {
                    "product_variant_id": ret.product_variant_id,
                    "batch_id": ret.batch_id,
                    "quantity": total_return_packs,
                    "movement_kind": "PHYSICAL",
                    "reference_type": "VISIT_RETURN_IN",
                    "reference_id": str(visit.id),
                    "idempotency_key": (
                        f"VIS-{visit.id}-{request_token}-R{ctx['return_index']}-B{ret.batch_id}"
                    ),
                    "source_location_id": None,
                    "destination_location_id": veh_loc_id,
                    "source_stock_status": None,
                    "destination_stock_status": "DAMAGED",
                    "work_session_id": active_session.id,
                    "notes": (
                        f"استلام مرتجع {ret.return_type} من المحل {shop.name}; "
                        f"Batch={ret.batch_id}. "
                        f"{('السبب: ' + ret.reason) if ret.reason else ''}"
                    ).strip(),
                }
            )

            db.add(
                VisitReturn(
                    company_id=company_id,
                    visit_id=visit.id,
                    product_variant_id=ret.product_variant_id,
                    batch_id=ret.batch_id,
                    quantity=ret.quantity,
                    packs_quantity=ret.packs_quantity,
                    return_type=ret.return_type,
                    reason=ret.reason,
                )
            )

        if any(
            remaining_qty != 0
            for buckets in allocation_state.values()
            for _, remaining_qty in buckets
        ):
            raise RuntimeError("Unconsumed FEFO allocation detected.")

        if movement_specs:
            applied_movements = await apply_inventory_movements_batch(
                db,
                company_id=company_id,
                performed_by=driver_id,
                movements=movement_specs,
            )
            if len(applied_movements) != len(movement_specs):
                raise RuntimeError("Inventory movement batch result size mismatch.")

        if payload.outcome == "Sale":
            if cash_collected > total_final_amount:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"مرفوض: النقد المحصل ({cash_collected}) لا يمكن أن يتجاوز "
                        f"قيمة الفاتورة ({total_final_amount}). لسداد الديون السابقة "
                        "استخدم حقل التحصيل المخصص."
                    ),
                )
            new_debt = total_final_amount - cash_collected
            if new_debt > Decimal("0"):
                is_allowed, msg = await check_debt_limits(
                    db,
                    company_id,
                    driver_id,
                    shop.id,
                    new_debt,
                    pre_fetched_driver=current_driver,
                )
                if not is_allowed:
                    raise HTTPException(status_code=403, detail=msg)
        else:
            new_debt = Decimal("0.000")
            total_final_amount = Decimal("0.000")
            total_base_amount = Decimal("0.000")
            total_discount = Decimal("0.000")
            total_tax = Decimal("0.000")

        visit.amount_before_tax_and_discount = total_base_amount
        visit.discount_applied = total_discount
        visit.tax_percentage_applied = (
            current_tax_pct if payload.outcome == "Sale" else Decimal("0.000")
        )
        visit.tax_amount = total_tax
        visit.final_amount_due = total_final_amount
        visit.cash_collected = (
            cash_collected if payload.outcome == "Sale" else Decimal("0.000")
        )
        visit.debt_paid = (
            debt_paid_input if payload.outcome != "Postponed" else Decimal("0.000")
        )

        if payload.outcome == "NoSale":
            visit.no_sale_reason = payload.notes
        elif payload.outcome == "Sale":
            visit.no_sale_reason = None
        else:
            visit.no_sale_reason = payload.notes

        # منطق الذمم الحالي محفوظ كما هو؛ Patch المخزون لا يعيد تصميمه.
        if payload.outcome != "Postponed":
            new_balance = original_shop_balance + new_debt - debt_paid_input
            if new_balance < Decimal("0"):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "مرفوض محاسبياً: التحصيل أكبر من إجمالي الدين. "
                        f"الرصيد سيصبح بالسالب ({new_balance})."
                    ),
                )
            if not new_balance.is_finite() or new_balance > money_limit:
                raise HTTPException(
                    status_code=400,
                    detail="الرصيد الناتج للمحل يتجاوز السعة المالية Numeric(12,3).",
                )
            shop.current_balance = new_balance
            visit.shop_balance_after = new_balance

            if debt_paid_input > Decimal("0"):
                db.add(
                    SystemAuditLog(
                        company_id=company_id,
                        admin_id=driver_id,
                        target_id=f"Shop_{shop.id}_Visit_{visit.id}",
                        action_type="DEBT_COLLECTION",
                        old_value=f"Balance: {original_shop_balance}",
                        new_value=(
                            f"Collected: {debt_paid_input} | New Balance: {new_balance}"
                        ),
                    )
                )
        else:
            visit.shop_balance_after = original_shop_balance

        sold_variant_ids = sorted({
            item.product_variant_id
            for item in payload.cart_items
            if item.quantity > 0 or item.packs_quantity > 0
        })
        if payload.outcome == "Sale" and sold_variant_ids:
            await db.execute(
                update(ShortageRequest)
                .where(
                    ShortageRequest.company_id == company_id,
                    ShortageRequest.shop_id == shop.id,
                    ShortageRequest.status == "pending",
                    ShortageRequest.product_variant_id.in_(sold_variant_ids),
                    or_(
                        ShortageRequest.driver_id.is_(None),
                        ShortageRequest.driver_id == driver_id,
                    ),
                )
                .values(
                    status="fulfilled",
                    fulfilled_by_visit_id=visit.id,
                    fulfilled_at=get_utc_now(),
                )
            )

        if payload.outcome in {"Sale", "NoSale"}:
            if shop.zone_id == current_route.zone_id:
                visit.is_emergency = False
                # نفس Workflow القديم لمنع ظهور المحل مرتين؛ أضفنا Tenant scope فقط.
                await db.execute(
                    delete(Visit).where(
                        Visit.company_id == company_id,
                        Visit.shop_id == shop.id,
                        Visit.driver_id == active_session.driver_id,
                        Visit.status == "Pending",
                        Visit.operational_date == visit.operational_date,
                        Visit.id != visit.id,
                    )
                )

        response_payload = {
            "message": "Visit updated successfully",
            "new_balance": str(shop.current_balance or "0.000"),
        }
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except InventoryReversalError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        await db.rollback()
        logger.error(
            f"إعداد أو قيمة غير صالحة أثناء تحديث الزيارة: {str(exc)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=409,
            detail=f"تعذر تنفيذ الزيارة بسبب إعداد غير صالح: {str(exc)}",
        ) from exc
    except Exception as exc:
        await db.rollback()
        logger.error(
            f"خطأ غير متوقع أثناء تحديث الزيارة: {str(exc)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="خطأ داخلي أثناء حفظ الزيارة.",
        ) from exc

# =========================================
# Helpers: unified VEHICLE inventory + HANDSHAKE projection
# =========================================
async def _load_vehicle_inventory_projection(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
    work_session_id: int | None = None,
):
    """
    عرض Flutter التجميعي من المحرك الموحد فقط.

    - current_quantity: الرصيد الفيزيائي AVAILABLE الحي من InventoryBalance.
    - starting_quantity: لقطة بداية الجلسة الثابتة من SessionInventorySnapshot.
    - issued_quantity: صافي صرف الزيارات من AVAILABLE بعد طرح VISIT_REVERSAL الداخل للسيارة.

    لا يجوز اشتقاق رصيد البداية من current + issued لأن حوالات منتصف اليوم
    والتراجعات تغيّر current دون أن تكون جزءاً من عهدة بداية اليوم.
    """
    vehicle_location_id = (
        await db.execute(
            select(InventoryLocation.id).filter_by(
                company_id=company_id,
                vehicle_id=vehicle_id,
                location_type="VEHICLE",
                is_active=True,
            )
        )
    ).scalar_one_or_none()

    if vehicle_location_id is None:
        raise HTTPException(
            status_code=409,
            detail="السيارة الحالية لا تملك موقع مخزون VEHICLE فعالاً داخل الشركة.",
        )

    current_rows = (
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
    current_map = {
        int(product_variant_id): int(quantity or 0)
        for product_variant_id, quantity in current_rows
    }

    # قبل بدء الجلسة لا توجد Snapshot بعد؛ للعرض التمهيدي فقط تكون البداية هي الرصيد الحالي.
    # بعد بدء الجلسة تصبح SessionInventorySnapshot المصدر التاريخي الوحيد لبداية اليوم.
    starting_map = dict(current_map) if work_session_id is None else {}
    issued_map = {}
    if work_session_id is not None:
        snapshot_rows = (
            await db.execute(
                select(
                    SessionInventorySnapshot.product_variant_id,
                    SessionInventorySnapshot.starting_quantity,
                    SessionInventorySnapshot.location_id,
                )
                .filter(
                    SessionInventorySnapshot.company_id == company_id,
                    SessionInventorySnapshot.work_session_id == work_session_id,
                    SessionInventorySnapshot.stock_status == "AVAILABLE",
                )
                .order_by(SessionInventorySnapshot.product_variant_id.asc())
            )
        ).all()
        if snapshot_rows:
            snapshot_location_ids = {int(row.location_id) for row in snapshot_rows}
            if snapshot_location_ids != {int(vehicle_location_id)}:
                raise HTTPException(
                    status_code=409,
                    detail="لقطة بداية الجلسة لا تطابق موقع مخزون السيارة الحالية.",
                )
            starting_map = {
                int(row.product_variant_id): int(row.starting_quantity or 0)
                for row in snapshot_rows
            }

        # صافي الصرف: الخروج الأصلي من الزيارة موجب، وعكسه الداخل AVAILABLE سالب.
        net_issue_expr = case(
            (
                and_(
                    InventoryMovement.source_location_id == vehicle_location_id,
                    InventoryMovement.source_stock_status == "AVAILABLE",
                    InventoryMovement.reference_type.in_([
                        "VISIT_ITEM_OUT",
                        "VISIT_EXCHANGE_OUT",
                    ]),
                ),
                InventoryMovement.quantity,
            ),
            (
                and_(
                    InventoryMovement.destination_location_id == vehicle_location_id,
                    InventoryMovement.destination_stock_status == "AVAILABLE",
                    InventoryMovement.reference_type == "VISIT_REVERSAL",
                ),
                -InventoryMovement.quantity,
            ),
            else_=0,
        )
        issued_rows = (
            await db.execute(
                select(
                    InventoryMovement.product_variant_id,
                    func.sum(net_issue_expr),
                )
                .filter(
                    InventoryMovement.company_id == company_id,
                    InventoryMovement.work_session_id == work_session_id,
                    InventoryMovement.movement_kind == "PHYSICAL",
                    or_(
                        and_(
                            InventoryMovement.source_location_id == vehicle_location_id,
                            InventoryMovement.source_stock_status == "AVAILABLE",
                            InventoryMovement.reference_type.in_([
                                "VISIT_ITEM_OUT",
                                "VISIT_EXCHANGE_OUT",
                            ]),
                        ),
                        and_(
                            InventoryMovement.destination_location_id == vehicle_location_id,
                            InventoryMovement.destination_stock_status == "AVAILABLE",
                            InventoryMovement.reference_type == "VISIT_REVERSAL",
                        ),
                    ),
                )
                .group_by(InventoryMovement.product_variant_id)
                .order_by(InventoryMovement.product_variant_id.asc())
            )
        ).all()
        for product_variant_id, quantity in issued_rows:
            net_quantity = int(quantity or 0)
            if net_quantity < 0:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "تم اكتشاف صافي صرف زيارة سالب في سجل السيارة؛ "
                        "أوقف العرض وراجع سجل الحركات بدلاً من إخفاء التناقض."
                    ),
                )
            issued_map[int(product_variant_id)] = net_quantity

    variant_ids = sorted(set(current_map) | set(starting_map) | set(issued_map))
    if not variant_ids:
        return int(vehicle_location_id), []

    variants = (
        await db.execute(
            select(ProductVariant)
            .filter(
                ProductVariant.company_id == company_id,
                ProductVariant.id.in_(variant_ids),
            )
            .order_by(ProductVariant.id.asc())
        )
    ).scalars().all()
    variant_map = {int(variant.id): variant for variant in variants}

    if set(variant_map) != set(variant_ids):
        raise HTTPException(
            status_code=409,
            detail="تم اكتشاف رصيد سيارة مرتبط بصنف مفقود أو خارج الشركة.",
        )

    projection = []
    for product_variant_id in variant_ids:
        variant = variant_map[product_variant_id]
        packs_per_carton = int(variant.packs_per_carton or 0)
        if packs_per_carton <= 0:
            raise HTTPException(
                status_code=409,
                detail=f"إعداد عدد الحبات في الكرتونة غير صالح للصنف ({variant.variant_name}).",
            )

        projection.append({
            "variant": variant,
            "packs_per_carton": packs_per_carton,
            "starting_quantity": starting_map.get(product_variant_id, 0),
            "issued_quantity": issued_map.get(product_variant_id, 0),
            "current_quantity": current_map.get(product_variant_id, 0),
        })

    return int(vehicle_location_id), projection


async def _load_handshake_product_totals(
    db: AsyncSession,
    *,
    company_id: int,
    header_ids: list[int],
):
    if not header_ids:
        return {}

    rows = (
        await db.execute(
            select(
                InventoryTransferLine.transfer_header_id,
                InventoryTransferLine.product_variant_id,
                func.sum(InventoryTransferLine.quantity),
                ProductVariant.name,
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
            )
            .group_by(
                InventoryTransferLine.transfer_header_id,
                InventoryTransferLine.product_variant_id,
                ProductVariant.name,
                ProductVariant.packs_per_carton,
            )
            .order_by(
                InventoryTransferLine.transfer_header_id.asc(),
                InventoryTransferLine.product_variant_id.asc(),
            )
        )
    ).all()

    by_header = {}
    for header_id, product_variant_id, quantity, variant_name, packs_per_carton in rows:
        by_header.setdefault(int(header_id), []).append({
            "product_variant_id": int(product_variant_id),
            "quantity": int(quantity or 0),
            "variant_name": str(variant_name),
            "packs_per_carton": int(packs_per_carton or 0),
        })

    for header_id in header_ids:
        products = by_header.get(int(header_id), [])
        if len(products) != 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"الحوالة ({header_id}) لا تطابق عقد المصافحة الميداني: "
                    "يجب أن تمثل صنفاً واحداً ويمكن أن تتوزع داخلياً على عدة Batches."
                ),
            )
        if products[0]["quantity"] <= 0 or products[0]["packs_per_carton"] <= 0:
            raise HTTPException(
                status_code=409,
                detail=f"الحوالة ({header_id}) تحمل كمية أو إعداد تعبئة غير صالح.",
            )

    return by_header


async def _load_active_driver_route_and_vehicle_location(
    db: AsyncSession,
    *,
    company_id: int,
    driver_id: int,
    work_session_id: int,
    require_active_route: bool = True,
    require_active_vehicle_location: bool = True,
):
    stmt_route = select(DispatchRoute).filter_by(
        company_id=company_id,
        work_session_id=work_session_id,
        driver_id=driver_id,
    )
    if require_active_route:
        stmt_route = stmt_route.filter(DispatchRoute.status == "active")

    route = (
        await db.execute(
            stmt_route.order_by(DispatchRoute.id.asc()).limit(1)
        )
    ).scalars().first()

    if route is None or route.vehicle_id is None:
        detail = (
            "جلسة العمل الحالية لا تملك خط سير فعالاً مربوطاً بسيارة."
            if require_active_route
            else "جلسة العمل الحالية لا تملك خط سير مربوطاً بسيارة."
        )
        raise HTTPException(status_code=409, detail=detail)

    stmt_location = select(InventoryLocation.id).filter_by(
        company_id=company_id,
        vehicle_id=route.vehicle_id,
        location_type="VEHICLE",
    )
    if require_active_vehicle_location:
        stmt_location = stmt_location.filter(InventoryLocation.is_active.is_(True))

    vehicle_location_id = (
        await db.execute(
            stmt_location.order_by(
                InventoryLocation.is_active.desc(),
                InventoryLocation.id.desc(),
            ).limit(1)
        )
    ).scalar_one_or_none()

    if vehicle_location_id is None:
        detail = (
            "السيارة الحالية لا تملك موقع مخزون VEHICLE فعالاً."
            if require_active_vehicle_location
            else "السيارة الحالية لا تملك موقع مخزون VEHICLE مرتبطاً بها."
        )
        raise HTTPException(status_code=409, detail=detail)

    return route, int(vehicle_location_id)


async def _validate_handshake_locations(
    db: AsyncSession,
    *,
    company_id: int,
    header: InventoryTransferHeader,
    vehicle_location_id: int,
    require_active_warehouse: bool = True,
):
    if vehicle_location_id not in {
        int(header.source_location_id),
        int(header.destination_location_id),
    }:
        raise HTTPException(
            status_code=403,
            detail="مرفوض أمنياً: الحوالة لا تخص سيارة جلسة المندوب الحالية.",
        )

    other_location_id = (
        int(header.destination_location_id)
        if int(header.source_location_id) == vehicle_location_id
        else int(header.source_location_id)
    )
    stmt_other = select(InventoryLocation).filter_by(
        company_id=company_id,
        id=other_location_id,
        location_type="WAREHOUSE",
    )
    if require_active_warehouse:
        stmt_other = stmt_other.filter(InventoryLocation.is_active.is_(True))

    other_location = (await db.execute(stmt_other)).scalar_one_or_none()
    if other_location is None:
        detail = (
            "المصافحة الميدانية يجب أن تكون بين مستودع فعال وسيارة الجلسة الحالية."
            if require_active_warehouse
            else "المصافحة الميدانية لا ترتبط بمستودع صحيح داخل الشركة."
        )
        raise HTTPException(status_code=409, detail=detail)



async def _validate_incoming_handshake_batches(
    db: AsyncSession,
    *,
    company_id: int,
    header: InventoryTransferHeader,
    lines,
    vehicle_location_id: int,
    as_of_date,
):
    """نمنع فقط إدخال AVAILABLE غير صالح إلى السيارة؛ لا علاقة لهذا بمسار المرتجعات DAMAGED."""
    if int(header.destination_location_id) != int(vehicle_location_id):
        return

    batch_ids = sorted({int(line.batch_id) for line in lines})
    rows = (
        await db.execute(
            select(ProductBatch).filter(
                ProductBatch.company_id == company_id,
                ProductBatch.id.in_(batch_ids),
            ).order_by(ProductBatch.id.asc())
        )
    ).scalars().all()
    batch_map = {int(row.id): row for row in rows}
    if set(batch_map) != set(batch_ids):
        raise HTTPException(
            status_code=409,
            detail="إحدى دفعات المصافحة غير موجودة أو لا تتبع الشركة.",
        )

    for line in lines:
        batch = batch_map[int(line.batch_id)]
        if int(batch.product_variant_id) != int(line.product_variant_id):
            raise HTTPException(
                status_code=409,
                detail="إحدى دفعات المصافحة لا تتبع الصنف المسجل في سطر الحوالة.",
            )
        if not batch.is_active:
            raise HTTPException(
                status_code=409,
                detail=f"الدفعة ({batch.batch_number}) موقوفة ولا يجوز إدخالها AVAILABLE إلى السيارة.",
            )
        if batch.production_date is not None and batch.production_date > as_of_date:
            raise HTTPException(
                status_code=409,
                detail=f"الدفعة ({batch.batch_number}) تاريخ إنتاجها في المستقبل.",
            )
        if batch.expiry_date < as_of_date:
            raise HTTPException(
                status_code=409,
                detail=f"الدفعة ({batch.batch_number}) منتهية الصلاحية ولا يجوز إدخالها AVAILABLE إلى السيارة.",
            )


def _handshake_signed_quantity(
    header: InventoryTransferHeader,
    *,
    vehicle_location_id: int,
    quantity: int,
) -> int:
    if int(header.destination_location_id) == vehicle_location_id:
        return int(quantity)
    if int(header.source_location_id) == vehicle_location_id:
        return -int(quantity)
    raise RuntimeError("Handshake header is not connected to the driver vehicle location.")


async def _load_handshake_lines_for_update(
    db: AsyncSession,
    *,
    company_id: int,
    header_ids: list[int],
):
    if not header_ids:
        return {}

    rows = (
        await db.execute(
            select(InventoryTransferLine)
            .filter(
                InventoryTransferLine.company_id == company_id,
                InventoryTransferLine.transfer_header_id.in_(header_ids),
            )
            .order_by(
                InventoryTransferLine.transfer_header_id.asc(),
                InventoryTransferLine.product_variant_id.asc(),
                InventoryTransferLine.batch_id.asc(),
                InventoryTransferLine.id.asc(),
            )
            .with_for_update()
        )
    ).scalars().all()

    by_header = {}
    for line in rows:
        by_header.setdefault(int(line.transfer_header_id), []).append(line)

    for header_id in header_ids:
        lines = by_header.get(int(header_id), [])
        if not lines:
            raise HTTPException(
                status_code=409,
                detail=f"الحوالة ({header_id}) لا تحتوي أي سطر مخزني.",
            )
        variant_ids = {int(line.product_variant_id) for line in lines}
        if len(variant_ids) != 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"الحوالة ({header_id}) تحتوي أكثر من صنف داخل Header واحد؛ "
                    "هذا غير متوافق مع عقد تطبيق المندوب الحالي."
                ),
            )

    return by_header


def _build_handshake_movement_specs(
    *,
    header: InventoryTransferHeader,
    lines,
    accepted: bool,
):
    movement_specs = []
    for line in lines:
        movement_specs.append({
            "product_variant_id": int(line.product_variant_id),
            "batch_id": int(line.batch_id),
            "quantity": int(line.quantity),
            "movement_kind": "RESERVATION",
            "reservation_action": "RELEASE",
            "reference_type": "HANDSHAKE_RELEASE",
            "reference_id": str(header.reference_number),
            "idempotency_key": f"HS-REL-{header.id}-{line.id}",
            "source_location_id": int(header.source_location_id),
            "destination_location_id": int(header.source_location_id),
            "source_stock_status": "AVAILABLE",
            "destination_stock_status": "AVAILABLE",
            "work_session_id": int(header.work_session_id),
            "transfer_header_id": int(header.id),
            "notes": "تحرير حجز المصافحة بعد قرار المندوب.",
        })
        if accepted:
            movement_specs.append({
                "product_variant_id": int(line.product_variant_id),
                "batch_id": int(line.batch_id),
                "quantity": int(line.quantity),
                "movement_kind": "PHYSICAL",
                "reference_type": "HANDSHAKE_POST",
                "reference_id": str(header.reference_number),
                "idempotency_key": f"HS-POST-{header.id}-{line.id}",
                "source_location_id": int(header.source_location_id),
                "destination_location_id": int(header.destination_location_id),
                "source_stock_status": "AVAILABLE",
                "destination_stock_status": "AVAILABLE",
                "work_session_id": int(header.work_session_id),
                "transfer_header_id": int(header.id),
                "notes": "ترحيل مصافحة منتصف اليوم بعد موافقة المندوب.",
            })
    return movement_specs


# =========================================
# 5. جلب بيانات الداشبورد للمندوب
# =========================================
@router.get("/driver/dashboard", status_code=200)
async def get_driver_dashboard(
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    company_id = current_driver.company_id
    driver_id = current_driver.id

    active_session = (
        await db.execute(
            select(WorkSession)
            .filter_by(
                company_id=company_id,
                driver_id=driver_id,
                end_time=None,
            )
            .order_by(WorkSession.id.desc())
            .limit(1)
        )
    ).scalars().first()

    if active_session is not None:
        # أثناء جلسة قائمة نعرض Route المرتبط بها حتى لو أوقفته الإدارة؛ البيع نفسه يبقى محظوراً إلا على active.
        active_route = (
            await db.execute(
                select(DispatchRoute)
                .filter_by(
                    company_id=company_id,
                    work_session_id=active_session.id,
                    driver_id=driver_id,
                )
                .order_by(DispatchRoute.id.asc())
                .limit(1)
            )
        ).scalars().first()
    else:
        company_local_date = await get_company_local_date(db, company_id)
        active_route = (
            await db.execute(
                select(DispatchRoute)
                .filter(
                    DispatchRoute.company_id == company_id,
                    DispatchRoute.driver_id == driver_id,
                    DispatchRoute.dispatch_date == company_local_date,
                    DispatchRoute.status.in_(["active", "waiting", "postponed"]),
                )
                .order_by(DispatchRoute.id.asc())
                .limit(1)
            )
        ).scalars().first()

    assigned_region = "غير محددة"
    inventory_list = []

    if active_route:
        zone = (
            await db.execute(
                select(Zone).filter_by(
                    company_id=company_id,
                    id=active_route.zone_id,
                )
            )
        ).scalar_one_or_none()
        if zone:
            assigned_region = zone.name

        if active_route.vehicle_id is not None:
            _, inventory_projection = await _load_vehicle_inventory_projection(
                db,
                company_id=company_id,
                vehicle_id=active_route.vehicle_id,
                work_session_id=(active_session.id if active_session else None),
            )

            for row in inventory_projection:
                variant = row["variant"]
                packs = row["packs_per_carton"]
                starting = row["starting_quantity"]
                issued = row["issued_quantity"]
                current = row["current_quantity"]
                inventory_list.append({
                    "product_id": variant.id,
                    "product_name": variant.variant_name,
                    "starting_cartons": starting // packs,
                    "starting_packs": starting % packs,
                    "sold_cartons": issued // packs,
                    "sold_packs": issued % packs,
                    "remaining_cartons": current // packs,
                    "remaining_packs": current % packs,
                })

    total_sales_cash = Decimal("0.000")
    total_debt_paid = Decimal("0.000")
    debt_payments_count = 0
    total_completed = 0
    sales_in_completed = 0
    total_pending = 0

    if active_session:
        stats = (
            await db.execute(
                select(
                    func.count(Visit.id).label("total_visits"),
                    func.sum(Visit.cash_collected).label("total_cash"),
                    func.sum(Visit.debt_paid).label("total_debt"),
                ).filter(
                    Visit.company_id == company_id,
                    Visit.work_session_id == active_session.id,
                    Visit.driver_id == driver_id,
                    Visit.status == "Completed",
                )
            )
        ).first()
        if stats:
            total_completed = int(stats.total_visits or 0)
            total_sales_cash = Decimal(str(stats.total_cash or "0.000"))
            total_debt_paid = Decimal(str(stats.total_debt or "0.000"))

        debt_payments_count = int((
            await db.execute(
                select(func.count(Visit.id)).filter(
                    Visit.company_id == company_id,
                    Visit.work_session_id == active_session.id,
                    Visit.driver_id == driver_id,
                    Visit.status == "Completed",
                    Visit.debt_paid > 0,
                )
            )
        ).scalar() or 0)

        sales_in_completed = int((
            await db.execute(
                select(func.count(Visit.id)).filter(
                    Visit.company_id == company_id,
                    Visit.work_session_id == active_session.id,
                    Visit.driver_id == driver_id,
                    Visit.outcome == "Sale",
                    Visit.status == "Completed",
                )
            )
        ).scalar() or 0)

    if active_route:
        total_pending = int((
            await db.execute(
                select(func.count(Visit.id))
                .join(
                    Shop,
                    and_(
                        Shop.company_id == Visit.company_id,
                        Shop.id == Visit.shop_id,
                    ),
                )
                .filter(
                    Visit.company_id == company_id,
                    Visit.driver_id == driver_id,
                    Visit.status == "Pending",
                    Shop.company_id == company_id,
                    Shop.is_archived.is_(False),
                    or_(
                        Shop.zone_id == active_route.zone_id,
                        Visit.is_emergency.is_(True),
                    ),
                )
            )
        ).scalar() or 0)

    response_data = {
        "driver_name": current_driver.full_name,
        "assigned_region": assigned_region,
        "active_session": {
            "session_id": active_session.id,
            "start_time": active_session.start_time.replace(tzinfo=timezone.utc).isoformat()
            if active_session.start_time else None,
            "is_authorized_to_sell": active_session.is_authorized_to_sell,
            "break_start_time": active_session.break_start_time.replace(tzinfo=timezone.utc).isoformat()
            if active_session.break_start_time else None,
            "break_end_time": active_session.break_end_time.replace(tzinfo=timezone.utc).isoformat()
            if active_session.break_end_time else None,
            "inventory": inventory_list,
        } if active_session else None,
        "financials": {
            "total_sales_cash": str(total_sales_cash),
            "total_debt_paid": str(total_debt_paid),
            "debt_payments_count": debt_payments_count,
            "total_cash_overall": str(total_sales_cash + total_debt_paid),
        },
        "counts": {
            "total_pending": total_pending,
            "total_completed": total_completed,
            "sales_in_completed": sales_in_completed,
        },
    }

    if not active_session and active_route:
        response_data["active_session"] = {
            "session_id": None,
            "start_time": None,
            "is_authorized_to_sell": False,
            "inventory": inventory_list,
        }

    return response_data


# =========================================
# 6. تأكيد استلام/رفض حوالة منتصف اليوم (HANDSHAKE)
# =========================================
@router.put("/driver/transfers/{transfer_id}/respond", status_code=200)
async def respond_to_transfer(
    transfer_id: int,
    payload: TransferResponseRequest,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    company_id = current_driver.company_id
    driver_id = current_driver.id
    response = payload.response
    reason = (payload.reason or "").strip() or None

    try:
        header = (
            await db.execute(
                select(InventoryTransferHeader)
                .filter_by(
                    company_id=company_id,
                    id=transfer_id,
                    workflow_type="HANDSHAKE",
                    expected_receiver_id=driver_id,
                )
                .order_by(InventoryTransferHeader.id.asc())
                .with_for_update()
            )
        ).scalar_one_or_none()

        if header is None:
            raise HTTPException(status_code=404, detail="الحوالة المطلوبة غير موجودة أو لا تخصك.")

        # State-idempotency للـretry الشبكي بدون تغيير عقد Flutter الحالي.
        if response == "accepted" and header.status == "POSTED" and header.received_by == driver_id:
            await db.rollback()
            return {"message": "تم تسجيل الرد (accepted) بنجاح."}
        if response == "rejected" and header.status == "REJECTED" and header.received_by == driver_id:
            if reason == (header.decision_reason or "").strip():
                await db.rollback()
                return {"message": "تم تسجيل الرد (rejected) بنجاح."}
            raise HTTPException(
                status_code=409,
                detail="الحوالة رُفضت مسبقاً بسبب مختلف؛ لا يجوز تغيير القرار بعد اعتماده.",
            )

        if header.status != "PENDING":
            raise HTTPException(
                status_code=409,
                detail=f"هذه الحوالة تمت معالجتها مسبقاً بحالة: {header.status}",
            )

        if response == "rejected" and not reason:
            raise HTTPException(status_code=400, detail="رفض الحوالة يتطلب سبباً واضحاً.")

        work_session = (
            await db.execute(
                select(WorkSession)
                .filter_by(
                    company_id=company_id,
                    id=header.work_session_id,
                    driver_id=driver_id,
                )
                .with_for_update(read=True)
            )
        ).scalar_one_or_none()
        if work_session is None:
            raise HTTPException(status_code=403, detail="الحوالة لا ترتبط بجلسة عمل صالحة لهذا المندوب.")
        if work_session.end_time is not None or work_session.is_settled:
            raise HTTPException(status_code=400, detail="لا يمكن معالجة حوالة لجلسة عمل تم إنهاؤها أو تسويتها.")

        vehicle_location_id = None
        if response == "accepted":
            _, vehicle_location_id = await _load_active_driver_route_and_vehicle_location(
                db,
                company_id=company_id,
                driver_id=driver_id,
                work_session_id=work_session.id,
            )
            await _validate_handshake_locations(
                db,
                company_id=company_id,
                header=header,
                vehicle_location_id=vehicle_location_id,
            )
        # الرفض لا يحتاج Route/وجهة فعالة؛ يجب أن يبقى ممكناً لتحرير الحجز وعدم تعليق المندوب.

        lines_by_header = await _load_handshake_lines_for_update(
            db,
            company_id=company_id,
            header_ids=[header.id],
        )
        lines = lines_by_header[header.id]

        product_variant_id = int(lines[0].product_variant_id)
        await acquire_product_lifecycle_guards(
            db, company_id, [product_variant_id], exclusive=False,
        )
        variant = (
            await db.execute(
                select(ProductVariant).filter_by(
                    company_id=company_id,
                    id=product_variant_id,
                )
            )
        ).scalar_one_or_none()
        if variant is None:
            raise HTTPException(status_code=409, detail="صنف الحوالة غير موجود داخل الشركة.")

        # الاستلام AVAILABLE إلى السيارة يحتاج صنفاً وBatch صالحين لحظة القبول.
        # هذا لا يغيّر مسار المرتجعات: VisitReturn يدخل DAMAGED فوراً حتى لو منتهي/موقوف.
        if response == "accepted" and int(header.destination_location_id) == vehicle_location_id:
            receipt_capability = evaluate_product_capability(
                variant.lifecycle_status,
                variant.operational_hold,
                INBOUND_COMPLETE,
                document_started=True,
            )
            if not receipt_capability.allowed:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": receipt_capability.code,
                        "message": f"لا يمكن إنهاء استلام المنتج ({variant.variant_name}) في حالته الحالية.",
                    },
                )
            as_of_date = await get_company_local_date(db, company_id)
            await _validate_incoming_handshake_batches(
                db,
                company_id=company_id,
                header=header,
                lines=lines,
                vehicle_location_id=vehicle_location_id,
                as_of_date=as_of_date,
            )

        movement_specs = _build_handshake_movement_specs(
            header=header,
            lines=lines,
            accepted=(response == "accepted"),
        )
        await apply_inventory_movements_batch(
            db,
            company_id=company_id,
            performed_by=driver_id,
            movements=movement_specs,
        )

        now_utc = get_utc_now()
        header.received_by = driver_id
        header.updated_at = now_utc

        if response == "accepted":
            header.status = "POSTED"
            header.accepted_at = now_utc
            header.posted_at = now_utc
            header.decision_reason = None
            action_type = "HANDSHAKE_ACCEPTED"
            audit_value = "POSTED"
        else:
            header.status = "REJECTED"
            header.rejected_at = now_utc
            header.decision_reason = reason
            action_type = "HANDSHAKE_REJECTED"
            audit_value = reason

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=driver_id,
            target_id=f"Transfer_{header.id}",
            action_type=action_type,
            old_value="PENDING",
            new_value=audit_value,
        ))

        await db.commit()
        return {"message": f"تم تسجيل الرد ({response}) بنجاح."}

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.error(f"تعارض أثناء معالجة المصافحة: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=409, detail="حدث تعارض متزامن أثناء معالجة الحوالة.") from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في معالجة المصافحة: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي أثناء معالجة الحوالة.") from exc


# =========================================
# 7. معالجة الحوالات بالجملة (Batch Response)
# =========================================
@router.put("/driver/transfers/batch_respond", status_code=200)
async def batch_respond_to_transfers(
    payload: BatchTransferResponseRequest,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    company_id = current_driver.company_id
    driver_id = current_driver.id

    if not payload.transfers:
        raise HTTPException(status_code=400, detail="بيانات الطلب غير مكتملة.")
    if len(payload.transfers) > 100:
        raise HTTPException(status_code=413, detail="الدفعة كبيرة جداً. الحد الأقصى 100 حوالة في الطلب الواحد.")

    request_map = {int(item.transfer_id): item for item in payload.transfers}
    transfer_ids = sorted(request_map)

    try:
        headers = (
            await db.execute(
                select(InventoryTransferHeader)
                .filter(
                    InventoryTransferHeader.company_id == company_id,
                    InventoryTransferHeader.id.in_(transfer_ids),
                    InventoryTransferHeader.workflow_type == "HANDSHAKE",
                    InventoryTransferHeader.expected_receiver_id == driver_id,
                )
                .order_by(InventoryTransferHeader.id.asc())
                .with_for_update()
            )
        ).scalars().all()
        header_map = {int(header.id): header for header in headers}

        if set(header_map) != set(transfer_ids):
            raise HTTPException(status_code=404, detail="إحدى الحوالات غير موجودة أو لا تخصك.")

        pending_headers = []
        for transfer_id in transfer_ids:
            header = header_map[transfer_id]
            request_item = request_map[transfer_id]
            reason = (request_item.reason or "").strip() or None

            if request_item.status == "accepted" and header.status == "POSTED" and header.received_by == driver_id:
                continue
            if request_item.status == "rejected" and header.status == "REJECTED" and header.received_by == driver_id:
                if reason == (header.decision_reason or "").strip():
                    continue
                raise HTTPException(
                    status_code=409,
                    detail=f"الحوالة ({transfer_id}) رُفضت مسبقاً بسبب مختلف.",
                )
            if header.status != "PENDING":
                raise HTTPException(
                    status_code=409,
                    detail=f"الحوالة ({transfer_id}) تمت معالجتها مسبقاً بحالة {header.status}.",
                )
            if request_item.status == "rejected" and not reason:
                raise HTTPException(status_code=400, detail=f"رفض الحوالة ({transfer_id}) يتطلب سبباً واضحاً.")
            pending_headers.append(header)

        if pending_headers:
            session_ids = {int(header.work_session_id) for header in pending_headers}
            if len(session_ids) != 1:
                raise HTTPException(
                    status_code=409,
                    detail="لا يجوز معالجة مصافحات من أكثر من جلسة عمل في دفعة واحدة.",
                )
            work_session_id = next(iter(session_ids))

            work_session = (
                await db.execute(
                    select(WorkSession)
                    .filter_by(
                        company_id=company_id,
                        id=work_session_id,
                        driver_id=driver_id,
                    )
                    .with_for_update(read=True)
                )
            ).scalar_one_or_none()
            if work_session is None or work_session.end_time is not None or work_session.is_settled:
                raise HTTPException(status_code=400, detail="جلسة العمل المرتبطة بالمصافحات مغلقة أو غير صالحة.")

            accepted_headers = [
                header
                for header in pending_headers
                if request_map[int(header.id)].status == "accepted"
            ]
            vehicle_location_id = None
            if accepted_headers:
                _, vehicle_location_id = await _load_active_driver_route_and_vehicle_location(
                    db,
                    company_id=company_id,
                    driver_id=driver_id,
                    work_session_id=work_session_id,
                )
                for header in accepted_headers:
                    await _validate_handshake_locations(
                        db,
                        company_id=company_id,
                        header=header,
                        vehicle_location_id=vehicle_location_id,
                    )
            # المصافحات المرفوضة لا تعتمد على استمرار Route/الوجهة؛ الرفض يحرر الحجز فقط.

            pending_ids = [int(header.id) for header in pending_headers]
            lines_by_header = await _load_handshake_lines_for_update(
                db,
                company_id=company_id,
                header_ids=pending_ids,
            )

            variant_ids = sorted({
                int(lines[0].product_variant_id)
                for lines in lines_by_header.values()
            })
            await acquire_product_lifecycle_guards(
                db, company_id, variant_ids, exclusive=False,
            )
            variants = (
                await db.execute(
                    select(ProductVariant).filter(
                        ProductVariant.company_id == company_id,
                        ProductVariant.id.in_(variant_ids),
                    )
                )
            ).scalars().all()
            variant_map = {int(variant.id): variant for variant in variants}
            if set(variant_map) != set(variant_ids):
                raise HTTPException(status_code=409, detail="إحدى المصافحات مرتبطة بصنف مفقود داخل الشركة.")

            movement_specs = []
            now_utc = get_utc_now()
            as_of_date = (
                await get_company_local_date(db, company_id)
                if accepted_headers
                else None
            )
            for header in pending_headers:
                request_item = request_map[int(header.id)]
                accepted = request_item.status == "accepted"
                lines = lines_by_header[int(header.id)]
                variant = variant_map[int(lines[0].product_variant_id)]

                if accepted and int(header.destination_location_id) == vehicle_location_id:
                    receipt_capability = evaluate_product_capability(
                        variant.lifecycle_status,
                        variant.operational_hold,
                        INBOUND_COMPLETE,
                        document_started=True,
                    )
                    if not receipt_capability.allowed:
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "code": receipt_capability.code,
                                "message": f"لا يمكن إنهاء استلام المنتج ({variant.variant_name}) في الحوالة ({header.id}).",
                            },
                        )
                    await _validate_incoming_handshake_batches(
                        db,
                        company_id=company_id,
                        header=header,
                        lines=lines,
                        vehicle_location_id=vehicle_location_id,
                        as_of_date=as_of_date,
                    )

                movement_specs.extend(
                    _build_handshake_movement_specs(
                        header=header,
                        lines=lines,
                        accepted=accepted,
                    )
                )

            if movement_specs:
                await apply_inventory_movements_batch(
                    db,
                    company_id=company_id,
                    performed_by=driver_id,
                    movements=movement_specs,
                )

            for header in pending_headers:
                request_item = request_map[int(header.id)]
                reason = (request_item.reason or "").strip() or None
                header.received_by = driver_id
                header.updated_at = now_utc

                if request_item.status == "accepted":
                    header.status = "POSTED"
                    header.accepted_at = now_utc
                    header.posted_at = now_utc
                    header.decision_reason = None
                    action_type = "HANDSHAKE_ACCEPTED"
                    new_value = "POSTED"
                else:
                    header.status = "REJECTED"
                    header.rejected_at = now_utc
                    header.decision_reason = reason
                    action_type = "HANDSHAKE_REJECTED"
                    new_value = reason

                db.add(SystemAuditLog(
                    company_id=company_id,
                    admin_id=driver_id,
                    target_id=f"Transfer_{header.id}",
                    action_type=action_type,
                    old_value="PENDING",
                    new_value=new_value,
                ))

        await db.commit()
        return {"message": f"تمت معالجة {len(transfer_ids)} حوالة بنجاح."}

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.error(f"تعارض أثناء معالجة المصافحات الجماعية: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=409, detail="فشل العملية بسبب تعارض متزامن في قاعدة البيانات.") from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في المعالجة الجماعية للمصافحات: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي في المعالجة الجماعية.") from exc


# =========================================
# 8. التحقق من وجود حوالات معلقة (Polling)
# =========================================
@router.get("/driver/transfers/pending", response_model=List[PendingBatchResponse], status_code=200)
async def get_pending_transfers(
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    company_id = current_driver.company_id
    driver_id = current_driver.id

    active_session = (
        await db.execute(
            select(WorkSession)
            .filter_by(
                company_id=company_id,
                driver_id=driver_id,
                end_time=None,
            )
            .order_by(WorkSession.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if active_session is None:
        return []

    _, vehicle_location_id = await _load_active_driver_route_and_vehicle_location(
        db,
        company_id=company_id,
        driver_id=driver_id,
        work_session_id=active_session.id,
        require_active_route=False,
        require_active_vehicle_location=False,
    )

    headers = (
        await db.execute(
            select(InventoryTransferHeader)
            .filter_by(
                company_id=company_id,
                work_session_id=active_session.id,
                workflow_type="HANDSHAKE",
                status="PENDING",
                expected_receiver_id=driver_id,
            )
            .order_by(InventoryTransferHeader.created_at.asc(), InventoryTransferHeader.id.asc())
        )
    ).scalars().all()
    if not headers:
        return []

    for header in headers:
        await _validate_handshake_locations(
            db,
            company_id=company_id,
            header=header,
            vehicle_location_id=vehicle_location_id,
            require_active_warehouse=False,
        )

    header_ids = [int(header.id) for header in headers]
    totals = await _load_handshake_product_totals(
        db,
        company_id=company_id,
        header_ids=header_ids,
    )

    batches = {}
    for header in headers:
        product = totals[int(header.id)][0]
        signed_quantity = _handshake_signed_quantity(
            header,
            vehicle_location_id=vehicle_location_id,
            quantity=product["quantity"],
        )
        packs = product["packs_per_carton"]
        sign = -1 if signed_quantity < 0 else 1
        abs_packs = abs(signed_quantity)

        batch_key = (
            header.notes
            if header.notes and "BATCH_" in header.notes
            else str(header.reference_number)
        )
        if batch_key not in batches:
            batches[batch_key] = {
                "transfer_id": batch_key,
                "created_at": header.created_at.replace(tzinfo=timezone.utc).isoformat()
                if header.created_at else None,
                "items": [],
            }

        batches[batch_key]["items"].append({
            "real_transfer_id": int(header.id),
            "product_name": product["variant_name"],
            "delta_cartons": (abs_packs // packs) * sign,
            "delta_packs": (abs_packs % packs) * sign,
        })

    return list(batches.values())

# =========================================
# 9. إضافة محل جديد (من الميدان)
# =========================================
@router.post("/shops", status_code=201)
async def add_new_shop(
    payload: AddShopRequest,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    # 1. الدرع الأمني (IDOR) - سحب الـ ID مباشرة من التوكن
    driver_id = current_driver.id

    # 2. جلب الجلسة النشطة (مع درع الـ Limit لتسريع الداتابيز)
    stmt_session = (
        select(WorkSession)
        .filter_by(company_id=current_driver.company_id, driver_id=driver_id, end_time=None)
        .order_by(WorkSession.id.desc())
        .limit(1)
        .with_for_update()
    )
    active_session = (await db.execute(stmt_session)).scalars().first()
    
    if not active_session:
        raise HTTPException(status_code=403, detail="مرفوض: الرجاء بدء يوم العمل أولاً.")
    if active_session.inventory_reconciled_at is not None:
        raise HTTPException(status_code=409, detail="مرفوض: عهدة مخزون هذه الجلسة مختومة ولا تقبل إضافة محلات.")

    # 3. جلب خط السير النشط لمنع كارثة "المحل الشبح"
    stmt_route = (
        select(DispatchRoute)
        .filter_by(
            company_id=current_driver.company_id,
            work_session_id=active_session.id,
            driver_id=driver_id,
            status='active',
        )
        .order_by(DispatchRoute.id.asc())
        .limit(1)
        .with_for_update(read=True)
    )
    active_route = (await db.execute(stmt_route)).scalars().first()
    
    if not active_route:
        raise HTTPException(status_code=403, detail="مرفوض: لا يوجد لديك خط سير نشط لربط المحل الجديد به.")
        
    # 4. حماية الاستراحة والصلاحية
    if active_session.break_start_time and not active_session.break_end_time:
        raise HTTPException(status_code=403, detail="أنت الآن في وقت الاستراحة. قم بإنهاء الاستراحة لمتابعة العمل.")
        
    if not active_session.is_authorized_to_sell:
        raise HTTPException(status_code=403, detail="مرفوض: غير مصرح لك بإضافة محلات حالياً. بانتظار تفعيل خط السير من الإدارة.")

    # 5. +++ الدرع الجغرافي: سحق ثغرة نصف الإحداثي وعنصرية خط الاستواء +++
    has_coords = payload.latitude is not None and payload.longitude is not None
    # +++ سحق ثغرة المسافات الفارغة (Whitespace Bypass) التي تخدع دالة bool() وتصنع محلات بلا خرائط +++
    has_link = bool(str(payload.location_link or "").strip())

    if not (has_coords or has_link):
        raise HTTPException(status_code=400, detail="فشل الحفظ: يجب توفير الموقع الجغرافي كاملاً (خط الطول والعرض معاً) أو رابط الخريطة.")

    # 6. درع التكرار وإجبارية الهاتف (حسب قرار الإدارة لضبط الذمم)
    clean_phone = str(payload.phone_number or "").strip()
    if not clean_phone:
        raise HTTPException(status_code=400, detail="مرفوض: رقم الهاتف إجباري لضمان التواصل مع المحل وتوثيق الذمم.")
        
    # نفس الهاتف قرار uniqueness داخل الشركة؛ Advisory Lock يمنع سباق SELECT ثم INSERT.
    await db.execute(
        select(
            func.pg_advisory_xact_lock(
                current_driver.company_id,
                func.hashtext(f"shop-phone:{clean_phone}")
            )
        )
    )
    stmt_dup = select(Shop).filter_by(
        company_id=current_driver.company_id,
        phone_number=clean_phone,
    )
    existing_shop = (await db.execute(stmt_dup)).scalars().first()
    if existing_shop:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"فشل الحفظ: رقم الهاتف مسجل مسبقاً للمحل ({existing_shop.name}).")

    try:
        # Pydantic قام بالتنظيف المسبق للـ Whitespaces، نعين القيم مباشرة
        new_shop = Shop(
            company_id=current_driver.company_id,
            name=payload.name,
            address=payload.address,
            phone_number=payload.phone_number,
            contact_person=payload.contact_person,
            notes=payload.notes,
            location_link=payload.location_link,
            latitude=payload.latitude,
            longitude=payload.longitude,
            zone_id=active_route.zone_id, 
            added_by_driver_id=driver_id,
            sequence=999,
            current_balance=Decimal('0.0'),
            max_debt_limit=Decimal('0.0') 
        )
        db.add(new_shop)
        await db.flush()

        new_visit = Visit(
            company_id=current_driver.company_id,
            driver_id=driver_id,
            shop_id=new_shop.id,
            work_session_id=active_session.id,
            operational_date=active_session.session_date,
            status='Pending',
            sequence=new_shop.sequence,
            visit_timestamp=get_utc_now()
        )
        db.add(new_visit)
        
        await db.commit()
        return {"message": "Shop added successfully", "shop": {"id": new_shop.id, "name": new_shop.name}}
        
    except IntegrityError as e:
        # +++ الدرع الفولاذي: التقاط الـ IntegrityError ورمي 409 Conflict محترم للمندوب +++
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=409, detail="فشل الحفظ: تعارض في البيانات. قد يكون رقم الهاتف مسجلاً مسبقاً.")
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء إضافة المحل.")


# =========================================
# 10. قائمة المنتجات والأسعار (Product Catalog - Legacy URL Match)
# =========================================
@router.get("/product_variants", response_model=List[ProductVariantResponse], status_code=200)
async def get_products(
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver) # حماية الرابط بالتوكن الأصلي دون المساس بالـ URLContract
    ):
        # +++  النخبة لـ N+1 ومحرقة الـ CPU: استعلام مباشر وإرجاع الكائنات فوراً +++
        # لا توجد حلقات تكرارية (No Python Loops)، الداتا تُسلم مباشرة لمحرك Pydantic ليقوم بالـ Serialization بسرعة الصاروخ
        stmt = select(ProductVariant).where(
            ProductVariant.company_id == current_driver.company_id,
            product_capability_predicate(ProductVariant, ROUTE_SALE_OPEN),
        ).order_by(ProductVariant.id.asc())
        result = await db.execute(stmt)
        return result.scalars().all()


# =========================================
# 11. استعراض زيارات اليوم والجرد
# =========================================
@router.get("/driver/visits", response_model=GetVisitsContract, status_code=200)
async def get_driver_visits(
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    company_id = current_driver.company_id
    driver_id = current_driver.id

    active_session = (
        await db.execute(
            select(WorkSession)
            .filter_by(
                company_id=company_id,
                driver_id=driver_id,
                end_time=None,
            )
            .order_by(WorkSession.id.desc())
            .limit(1)
        )
    ).scalars().first()

    if active_session is not None:
        active_route = (
            await db.execute(
                select(DispatchRoute)
                .filter_by(
                    company_id=company_id,
                    work_session_id=active_session.id,
                    driver_id=driver_id,
                )
                .order_by(DispatchRoute.id.asc())
                .limit(1)
            )
        ).scalars().first()
    else:
        company_local_date = await get_company_local_date(db, company_id)
        active_route = (
            await db.execute(
                select(DispatchRoute)
                .filter(
                    DispatchRoute.company_id == company_id,
                    DispatchRoute.driver_id == driver_id,
                    DispatchRoute.dispatch_date == company_local_date,
                    DispatchRoute.status.in_(["active", "waiting", "postponed"]),
                )
                .order_by(DispatchRoute.id.asc())
                .limit(1)
            )
        ).scalars().first()

    if active_route is None:
        return {"visits": [], "inventory": [], "pending_transfers": []}

    session_id_val = active_session.id if active_session else -1
    operational_date = (
        active_session.session_date
        if active_session is not None
        else active_route.dispatch_date
    )
    condition = or_(
        and_(
            Visit.status == "Pending",
            Visit.operational_date == operational_date,
            Shop.zone_id == active_route.zone_id,
        ),
        Visit.work_session_id == session_id_val,
        # الطوارئ المعلقة تبقى ظاهرة حتى تُنجز/تلغى؛ operational_date يحفظ يوم إنشائها ولا يحولها لزيارة يتيمة.
        and_(Visit.is_emergency.is_(True), Visit.status == "Pending"),
    )

    stmt_visits = (
        select(Visit)
        .join(
            Shop,
            and_(
                Shop.company_id == Visit.company_id,
                Shop.id == Visit.shop_id,
            ),
        )
        .options(
            contains_eager(Visit.shop),
            selectinload(Visit.items.and_(VisitItem.is_cancelled.is_(False)))
            .joinedload(VisitItem.product_variant),
            selectinload(Visit.returns.and_(VisitReturn.is_cancelled.is_(False)))
            .joinedload(VisitReturn.product_variant),
        )
        .filter(
            Visit.company_id == company_id,
            Visit.driver_id == driver_id,
            Shop.company_id == company_id,
            Shop.is_archived.is_(False),
            condition,
        )
        .order_by(Shop.sequence.asc().nulls_last(), Visit.id.asc())
    )
    visits = (await db.execute(stmt_visits)).scalars().all()

    route_zone_id = active_route.zone_id
    for visit in visits:
        visit.allowed_zone_id = route_zone_id

    inventory_data = []
    vehicle_location_id = None
    if active_route.vehicle_id is not None:
        vehicle_location_id, inventory_projection = await _load_vehicle_inventory_projection(
            db,
            company_id=company_id,
            vehicle_id=active_route.vehicle_id,
            work_session_id=(active_session.id if active_session else None),
        )

        for row in inventory_projection:
            variant = row["variant"]
            packs = row["packs_per_carton"]
            starting = row["starting_quantity"]
            current = row["current_quantity"]
            inventory_data.append({
                "id": variant.id,
                "name": variant.variant_name,
                "price_per_carton": str(variant.price_per_carton or "0.000"),
                "price_per_pack": str(variant.price_per_pack or "0.000"),
                "packs_per_carton": packs,
                "starting_cartons": starting // packs,
                "starting_packs": starting % packs,
                "sold_cartons": row["issued_quantity"] // packs,
                "sold_packs": row["issued_quantity"] % packs,
                "current_cartons": current // packs,
                "current_packs": current % packs,
            })

    pending_transfers_data = []
    if active_session:
        if vehicle_location_id is None:
            _, vehicle_location_id = await _load_active_driver_route_and_vehicle_location(
                db,
                company_id=company_id,
                driver_id=driver_id,
                work_session_id=active_session.id,
                require_active_route=False,
                require_active_vehicle_location=False,
            )

        pending_headers = (
            await db.execute(
                select(InventoryTransferHeader)
                .filter_by(
                    company_id=company_id,
                    work_session_id=active_session.id,
                    workflow_type="HANDSHAKE",
                    status="PENDING",
                    expected_receiver_id=driver_id,
                )
                .order_by(InventoryTransferHeader.created_at.asc(), InventoryTransferHeader.id.asc())
            )
        ).scalars().all()

        if pending_headers:
            for header in pending_headers:
                await _validate_handshake_locations(
                    db,
                    company_id=company_id,
                    header=header,
                    vehicle_location_id=vehicle_location_id,
                    require_active_warehouse=False,
                )

            totals = await _load_handshake_product_totals(
                db,
                company_id=company_id,
                header_ids=[int(header.id) for header in pending_headers],
            )
            for header in pending_headers:
                product = totals[int(header.id)][0]
                pending_transfers_data.append({
                    "transfer_id": int(header.id),
                    "product_variant_id": product["product_variant_id"],
                    "quantity_packs": _handshake_signed_quantity(
                        header,
                        vehicle_location_id=vehicle_location_id,
                        quantity=product["quantity"],
                    ),
                    "status": "pending",
                    "created_at": header.created_at.replace(tzinfo=timezone.utc).isoformat()
                    if header.created_at else None,
                })

    return {
        "visits": visits,
        "inventory": inventory_data,
        "pending_transfers": pending_transfers_data,
    }


# =========================================
# 12. جلب تفاصيل الزيارة المكتملة (مطابقة العقد الأصيل)
# =========================================
@router.get("/visits/{visit_id}", response_model=VisitDetailsResponse, status_code=200)
async def get_visit_details(
    visit_id: int,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    # +++ التطهير الأدائي المطلق: سحق الأصناف الملغاة داخل الـ SQL +++
    stmt = select(Visit).options(
        joinedload(Visit.shop),
        selectinload(Visit.items.and_(VisitItem.is_cancelled == False)).joinedload(VisitItem.product_variant),
        selectinload(Visit.returns.and_(VisitReturn.is_cancelled == False)) # شحن المرتجعات السليمة فقط
    ).filter_by(company_id=current_driver.company_id, id=visit_id)
    
    visit = (await db.execute(stmt)).scalar_one_or_none()
    
    if not visit:
        raise HTTPException(status_code=404, detail="عذراً، الزيارة المطلوبة غير موجودة.")
    
    # +++ الدرع الأمني المصفح: المندوب يرى فواتيره فقط، والأدمن يرى كل شيء للرقابة المحاسبية والجرد +++
    if not current_driver.is_admin and visit.driver_id != current_driver.id:
        raise HTTPException(status_code=403, detail="مرفوض أمنياً: غير مصرح لك بالاطلاع على فواتير المناديب الآخرين.")
        
    return visit


# =========================================
# 13. التحقق من وجود جلسة نشطة للمندوب (عند فتح التطبيق)
# =========================================
@router.get("/driver/sessions/active", response_model=ActiveSessionResponse, status_code=200)
async def get_active_session(
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    driver_id = current_driver.id
        
    # 2. البحث عن الجلسة النشطة (مع حماية הـ limit)
    # +++ الدرع الفولاذي ضد كراش الـ MultipleResultsFound (بدون أقفال لأنه GET Request للقراءة فقط) +++
    stmt_session = select(WorkSession).filter_by(company_id=current_driver.company_id, driver_id=driver_id, end_time=None).order_by(WorkSession.id.desc()).limit(1)
    active_session = (await db.execute(stmt_session)).scalars().first()
    
    if active_session:
        return {
            "active_session_found": True, 
            "session_id": active_session.id, 
            # تحويل الوقت لـ ISO مع تأمين المنطقة الزمنية
            "start_time": active_session.start_time.replace(tzinfo=timezone.utc).isoformat() if active_session.start_time else None
        }
        
    return {"active_session_found": False}
