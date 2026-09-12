import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from ws_manager import dispatch_manager
from sqlalchemy.future import select
from sqlalchemy import delete, func, or_, and_, case, nullslast, update, cast, Float, text
from database import get_db
from api.dependencies import get_current_admin, get_current_driver
from inventory_access import InventoryAccess, require_transfer
from dispatch_access import require_vehicle, require_route, route_filter, vehicle_filter
from datetime import timedelta, datetime, timezone
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
from decimal import Decimal
from typing import List 
from fastapi.responses import JSONResponse
import hashlib
import json
from collections import Counter
import logging
logger = logging.getLogger("wanasah_logger")

# +++ توحيد الزمن المعماري لنسف تعارض الـ Timezone في قاعدة البيانات +++
def get_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

from models import (
    Driver,
    WorkSession,
    SystemAuditLog,
    ProductVariant,
    DispatchRoute,
    RouteCommercialContext,
    Zone,
    Vehicle,
    Shop,
    Visit,
    ShortageRequest,
    Country,
    Governorate,
    ImportLog,
    VisitItem,
    InventoryLocation,
    InventoryBalance,
    InventoryTransferHeader,
    InventoryTransferLine,
    DispatchLoadPlanLine,
    ProductBatch,
    ProductLocation,
    InventoryMovement,
    SessionInventorySnapshot,
)
from services import (
    check_inventory_lock,
    InventoryMutationError,
    get_company_local_date,
    allocate_fefo_inventory_batch,
    apply_inventory_movements_batch,
    acquire_inventory_location_guards,
    inventory_business_error,
    warehouse_setup_required_detail,
    begin_idempotent_operation,
    complete_idempotent_operation,
)
from uuid import uuid4
from product_lifecycle import (
    REPLENISHMENT_NEW,
    ROUTE_LOAD_NEW,
    acquire_product_lifecycle_guards,
    evaluate_product_capability,
    product_capability_predicate,
    product_location_allows,
)
from domains.pricing.core import PricingError
from domains.pricing.context import (
    commercial_context_payload,
    lock_route_commercial_context,
    require_route_commercial_context,
)

from schemas import ( MessageResponse, AuthorizeSessionRequest, AdminDashboardDriverResponse,
SessionSettlementReportResponse, SettleSessionRequest, SettleSessionResponse, DispatchInitResponse,
DispatchRouteRequest, VehicleInventoryItemResponse, RouteLiveInventoryItemResponse, AdjustRouteInventoryRequest,
RouteTransferResponse, DispatchShopResponse, BulkUpdateShopItem, AdminAddShopRequest, ActiveRouteResponse,
UpdateRouteStatusRequest, AddZoneRequest, ArchivedZoneResponse, EditShopDetailsRequest, ShortageResponseItem,
CreateShortageItem, BulkImportRequest, UpdateZoneRequest, RestoreZoneRequest, ForceCancelHandshakeRequest)



# إنشاء روتر خاص بمسارات الإدارة (بتاج منفصل لتنظيم Swagger)
router = APIRouter(tags=["Admin & Dispatch Operations"])

# PATCH: DISPATCH_FINAL_INTEGRITY_GATE

# =========================================
# 1. إعطاء أو سحب "الضوء الأخضر" (تفعيل صلاحية البيع)
# =========================================
@router.put("/admin/sessions/{session_id}/authorize", response_model=MessageResponse, status_code=200)
async def authorize_session(
    session_id: int,
    # +++ الدرع الفولاذي: تهيئة كائن Pydantic كقيمة افتراضية صريحة للوفاء بعقود الـ React القديمة ومنع الـ 422 والـ 500 +++
    payload: AuthorizeSessionRequest = AuthorizeSessionRequest(),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):

    # 1. جلب الجلسة مع قفل التزامن (Row-Level Lock)
    stmt = select(WorkSession).filter_by(
    id=session_id,
    company_id=current_admin.company_id
).order_by(WorkSession.id.asc()).with_for_update()
    session = (await db.execute(stmt)).scalar_one_or_none()

    if not session:
        await db.rollback() # +++ سحق ثغرة تسريب الاتصالات (Connection Leak) +++
        raise HTTPException(status_code=404, detail="الجلسة المطلوبة غير موجودة.")

    # 2. درع الزومبي (حظر المساس بالجلسات الميتة أو المسواة)
    if session.end_time or session.is_settled:
        await db.rollback()
        raise HTTPException(status_code=400, detail="مرفوض: لا يمكن تعديل صلاحيات جلسة مغلقة أو تمت تسويتها ماليًا.")

    # 3. +++ الدرع الرقابي (Conflict of Interest): منع المشرف من إعطاء الصلاحية لنفسه +++
    if session.driver_id == current_admin.id:
        await db.rollback()
        raise HTTPException(status_code=403, detail="مرفوض رقابياً: لا يمكنك منح صلاحية البيع لجلسة تخصك (تضارب مصالح).")

    try:
        if session.is_authorized_to_sell != payload.is_authorized:
            old_val = session.is_authorized_to_sell
            session.is_authorized_to_sell = payload.is_authorized
            
            # 4. الدرع السيادي (Audit Trail): توثيق الحركة إجبارياً
            audit_log = SystemAuditLog(
                company_id=current_admin.company_id,
                admin_id=current_admin.id,
                target_id=f"Session_{session.id}_Driver_{session.driver_id}",
                action_type="AUTHORIZATION_TOGGLE",
                old_value=f"is_authorized: {old_val}",
                new_value=f"is_authorized: {payload.is_authorized}"
            )
            db.add(audit_log)
            
        await db.commit()
        return {"message": "تم تحديث صلاحية البيع وتوثيق العملية بنجاح."}
        
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء التحديث.")

# PATCH: DISPATCH_DASHBOARD_FINANCIAL_SETTLEMENT
# Dashboard/settlement are projections only. InventoryBalance remains live truth;
# SessionInventorySnapshot remains historical opening/ending truth.

async def _dispatch_session_inventory_projection(
    db: AsyncSession,
    *,
    company_id: int,
    sessions,
):
    session_ids = [int(session.id) for session in sessions]
    if not session_ids:
        return {}, {}

    routes = (
        await db.execute(
            select(DispatchRoute)
            .options(joinedload(DispatchRoute.vehicle))
            .filter(
                DispatchRoute.company_id == company_id,
                DispatchRoute.work_session_id.in_(session_ids),
            )
            .order_by(DispatchRoute.work_session_id.asc(), DispatchRoute.id.asc())
        )
    ).scalars().all()
    route_map = {}
    for route in routes:
        sid = int(route.work_session_id)
        if sid in route_map:
            raise HTTPException(
                status_code=409,
                detail="تم اكتشاف أكثر من خط سير مرتبط بنفس جلسة العمل.",
            )
        route_map[sid] = route

    snapshot_rows = (
        await db.execute(
            select(
                SessionInventorySnapshot.work_session_id,
                SessionInventorySnapshot.location_id,
                SessionInventorySnapshot.product_variant_id,
                SessionInventorySnapshot.stock_status,
                SessionInventorySnapshot.starting_quantity,
                SessionInventorySnapshot.ending_quantity,
            )
            .filter(
                SessionInventorySnapshot.company_id == company_id,
                SessionInventorySnapshot.work_session_id.in_(session_ids),
            )
            .order_by(
                SessionInventorySnapshot.work_session_id.asc(),
                SessionInventorySnapshot.product_variant_id.asc(),
                SessionInventorySnapshot.stock_status.asc(),
            )
        )
    ).all()

    opening_available = {}
    ending_available = {}
    location_by_session = {}
    product_ids = set()
    for sid, location_id, pid, stock_status, starting, ending in snapshot_rows:
        sid = int(sid)
        location_id = int(location_id)
        pid = int(pid)
        product_ids.add(pid)
        prior_location = location_by_session.get(sid)
        if prior_location is not None and prior_location != location_id:
            raise HTTPException(
                status_code=409,
                detail=f"لقطة الجلسة ({sid}) موزعة على أكثر من موقع مخزون.",
            )
        location_by_session[sid] = location_id
        if str(stock_status).upper() == "AVAILABLE":
            opening_available[(sid, pid)] = int(starting or 0)
            if ending is not None:
                ending_available[(sid, pid)] = int(ending)

    # الجلسة قد تبدأ بسيارة فارغة فلا يوجد Snapshot row؛ نحل موقع السيارة من Route.
    unresolved_vehicle_ids = sorted({
        int(route.vehicle_id)
        for sid, route in route_map.items()
        if sid not in location_by_session and route.vehicle_id is not None
    })
    if unresolved_vehicle_ids:
        location_rows = (
            await db.execute(
                select(InventoryLocation.vehicle_id, InventoryLocation.id)
                .filter(
                    InventoryLocation.company_id == company_id,
                    InventoryLocation.location_type == "VEHICLE",
                    InventoryLocation.vehicle_id.in_(unresolved_vehicle_ids),
                )
                .order_by(
                    InventoryLocation.vehicle_id.asc(),
                    InventoryLocation.is_active.desc(),
                    InventoryLocation.id.desc(),
                )
            )
        ).all()
        first_location_by_vehicle = {}
        for vehicle_id, location_id in location_rows:
            first_location_by_vehicle.setdefault(int(vehicle_id), int(location_id))
        for sid, route in route_map.items():
            if sid in location_by_session or route.vehicle_id is None:
                continue
            location_id = first_location_by_vehicle.get(int(route.vehicle_id))
            if location_id is not None:
                location_by_session[sid] = location_id

    location_ids = sorted(set(location_by_session.values()))
    current_by_location = {}
    if location_ids:
        current_rows = (
            await db.execute(
                select(
                    InventoryBalance.location_id,
                    InventoryBalance.product_variant_id,
                    func.sum(InventoryBalance.on_hand_quantity),
                )
                .filter(
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.location_id.in_(location_ids),
                    InventoryBalance.stock_status == "AVAILABLE",
                    InventoryBalance.on_hand_quantity > 0,
                )
                .group_by(
                    InventoryBalance.location_id,
                    InventoryBalance.product_variant_id,
                )
            )
        ).all()
        for location_id, pid, qty in current_rows:
            current_by_location[(int(location_id), int(pid))] = int(qty or 0)
            product_ids.add(int(pid))

    movement_rows = (
        await db.execute(
            select(
                InventoryMovement.work_session_id,
                InventoryMovement.product_variant_id,
                InventoryMovement.reference_type,
                InventoryMovement.source_location_id,
                InventoryMovement.destination_location_id,
                InventoryMovement.source_stock_status,
                InventoryMovement.destination_stock_status,
                InventoryMovement.quantity,
            )
            .filter(
                InventoryMovement.company_id == company_id,
                InventoryMovement.work_session_id.in_(session_ids),
                InventoryMovement.movement_kind == "PHYSICAL",
                InventoryMovement.reference_type.in_([
                    "VISIT_ITEM_OUT",
                    "VISIT_EXCHANGE_OUT",
                    "VISIT_REVERSAL",
                    "HANDSHAKE_POST",
                ]),
            )
            .order_by(InventoryMovement.id.asc())
        )
    ).all()

    issued_map = {}
    handshake_net_map = {}
    for (
        sid,
        pid,
        reference_type,
        source_location_id,
        destination_location_id,
        source_status,
        destination_status,
        quantity,
    ) in movement_rows:
        sid = int(sid)
        pid = int(pid)
        qty = int(quantity or 0)
        product_ids.add(pid)
        vehicle_location_id = location_by_session.get(sid)
        if vehicle_location_id is None:
            continue

        if reference_type in {"VISIT_ITEM_OUT", "VISIT_EXCHANGE_OUT"}:
            if (
                source_location_id == vehicle_location_id
                and source_status == "AVAILABLE"
            ):
                issued_map[(sid, pid)] = issued_map.get((sid, pid), 0) + qty
        elif reference_type == "VISIT_REVERSAL":
            # فقط عكس خروج AVAILABLE يقلل issued؛ عكس مرتجع DAMAGED لا يدخل هنا.
            if (
                destination_location_id == vehicle_location_id
                and destination_status == "AVAILABLE"
            ):
                issued_map[(sid, pid)] = issued_map.get((sid, pid), 0) - qty
        elif reference_type == "HANDSHAKE_POST":
            if destination_location_id == vehicle_location_id and destination_status == "AVAILABLE":
                handshake_net_map[(sid, pid)] = handshake_net_map.get((sid, pid), 0) + qty
            elif source_location_id == vehicle_location_id and source_status == "AVAILABLE":
                handshake_net_map[(sid, pid)] = handshake_net_map.get((sid, pid), 0) - qty

    if any(value < 0 for value in issued_map.values()):
        raise HTTPException(
            status_code=409,
            detail="سجل حركات الزيارات غير متسق: صافي VISIT_REVERSAL أكبر من الصرف الأصلي.",
        )

    variants = []
    if product_ids:
        variants = (
            await db.execute(
                select(ProductVariant)
                .filter(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id.in_(sorted(product_ids)),
                )
                .order_by(ProductVariant.id.asc())
            )
        ).scalars().all()
    variant_map = {int(variant.id): variant for variant in variants}
    if set(product_ids) - set(variant_map):
        raise HTTPException(status_code=409, detail="العهدة تشير إلى صنف مفقود داخل الشركة.")

    projection_by_session = {}
    for session in sessions:
        sid = int(session.id)
        vehicle_location_id = location_by_session.get(sid)
        session_products = sorted({
            pid for s, pid in set(opening_available) | set(ending_available) | set(issued_map) | set(handshake_net_map)
            if s == sid
        } | {
            pid for (loc, pid), qty in current_by_location.items()
            if vehicle_location_id is not None and loc == vehicle_location_id and qty > 0
        })

        rows = []
        for pid in session_products:
            variant = variant_map.get(pid)
            if variant is None:
                continue
            ppc = int(variant.packs_per_carton or 0)
            if ppc <= 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"إعداد التعبئة غير صالح للصنف ({variant.variant_name}).",
                )

            opening = opening_available.get((sid, pid), 0)
            received_basis = opening + handshake_net_map.get((sid, pid), 0)
            issued = issued_map.get((sid, pid), 0)

            if session.inventory_reconciled_at is not None:
                remaining = ending_available.get((sid, pid), 0)
            else:
                remaining = (
                    current_by_location.get((vehicle_location_id, pid), 0)
                    if vehicle_location_id is not None
                    else 0
                )

            if received_basis == 0 and issued == 0 and remaining == 0:
                continue
            if min(received_basis, issued, remaining) < 0:
                raise HTTPException(status_code=409, detail="تم اكتشاف كمية سالبة في إسقاط عهدة الجلسة.")

            rows.append({
                "product_id": pid,
                "product_name": variant.variant_name,
                "starting_quantity": received_basis,
                "sold_quantity": issued,
                "remaining_quantity": remaining,
                "packs_per_carton": ppc,
                "starting_cartons": received_basis // ppc,
                "starting_loose_packs": received_basis % ppc,
                "sold_cartons": issued // ppc,
                "sold_loose_packs": issued % ppc,
                "remaining_cartons": remaining // ppc,
                "remaining_loose_packs": remaining % ppc,
            })
        projection_by_session[sid] = rows

    return projection_by_session, route_map


async def _dispatch_driver_shortage_cash_map(
    db: AsyncSession,
    *,
    company_id: int,
    work_session_ids,
):
    session_ids = sorted({int(session_id) for session_id in work_session_ids})
    if not session_ids:
        return {}

    rows = (
        await db.execute(
            select(
                InventoryMovement.work_session_id,
                InventoryMovement.quantity,
                InventoryMovement.financial_unit_price_snapshot,
            )
            .filter(
                InventoryMovement.company_id == company_id,
                InventoryMovement.work_session_id.in_(session_ids),
                InventoryMovement.reference_type == "DRIVER_SHORTAGE",
                InventoryMovement.movement_kind == "PHYSICAL",
            )
            .order_by(
                InventoryMovement.work_session_id.asc(),
                InventoryMovement.id.asc(),
            )
        )
    ).all()

    money_limit = Decimal("999999999.999")
    totals = {session_id: Decimal("0.000") for session_id in session_ids}
    for work_session_id, quantity, unit_price_snapshot in rows:
        sid = int(work_session_id)
        qty = int(quantity or 0)
        if unit_price_snapshot is None:
            raise HTTPException(
                status_code=409,
                detail=f"قيد عجز المندوب للجلسة ({sid}) بلا سعر مالي مثبت.",
            )
        price = Decimal(str(unit_price_snapshot))
        line_total = Decimal(qty) * price
        if (
            qty < 0
            or not price.is_finite()
            or price < 0
            or not line_total.is_finite()
            or line_total < 0
            or line_total > money_limit
        ):
            raise HTTPException(
                status_code=409,
                detail=f"قيد عجز المندوب للجلسة ({sid}) يحمل قيمة مالية غير صالحة.",
            )
        totals[sid] = totals.get(sid, Decimal("0.000")) + line_total
        if totals[sid] > money_limit:
            raise HTTPException(
                status_code=409,
                detail=f"إجمالي عجز المندوب للجلسة ({sid}) يتجاوز السعة المالية.",
            )

    return totals



async def _dispatch_driver_shortage_cash(
    db: AsyncSession,
    *,
    company_id: int,
    work_session_id: int,
) -> Decimal:
    totals = await _dispatch_driver_shortage_cash_map(
        db,
        company_id=company_id,
        work_session_ids=[work_session_id],
    )
    return totals.get(int(work_session_id), Decimal("0.000"))


async def _dispatch_assert_vehicle_custody_reconciled(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
    allowed_work_session_id: int | None = None,
) -> None:
    stmt = (
        select(WorkSession.id, WorkSession.driver_id, WorkSession.end_time)
        .join(
            DispatchRoute,
            and_(
                DispatchRoute.company_id == WorkSession.company_id,
                DispatchRoute.work_session_id == WorkSession.id,
            ),
        )
        .filter(
            WorkSession.company_id == company_id,
            DispatchRoute.company_id == company_id,
            DispatchRoute.vehicle_id == vehicle_id,
            WorkSession.inventory_reconciled_at.is_(None),
        )
    )
    if allowed_work_session_id is not None:
        stmt = stmt.filter(WorkSession.id != int(allowed_work_session_id))

    unresolved = (
        await db.execute(
            stmt.order_by(WorkSession.id.asc()).limit(1)
        )
    ).first()
    if unresolved is not None:
        state = "نشطة" if unresolved.end_time is None else "بانتظار التسوية المخزنية"
        raise HTTPException(
            status_code=409,
            detail=(
                f"السيارة مرتبطة بجلسة عمل ({int(unresolved.id)}) {state}. "
                "لا يجوز إعادة إسناد عهدة السيارة أو تعديل حمولتها قبل ختم التسوية المخزنية."
            ),
        )


async def _dispatch_vehicle_location_ids(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
) -> list[int]:
    location_ids = list((
        await db.execute(
            select(InventoryLocation.id)
            .filter_by(
                company_id=company_id,
                vehicle_id=vehicle_id,
                location_type="VEHICLE",
            )
            .order_by(InventoryLocation.id.asc())
        )
    ).scalars().all())
    if not location_ids:
        raise HTTPException(
            status_code=409,
            detail="السيارة لا تملك أي موقع مخزون VEHICLE تاريخي داخل الشركة.",
        )
    return [int(location_id) for location_id in location_ids]


# =========================================
# 2. جلب ملخص الجلسات التشغيلية حسب تاريخ الشركة
# =========================================
@router.get("/admin/sessions/today", response_model=List[AdminDashboardDriverResponse], status_code=200)
async def get_admin_dashboard_data(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id
    company_local_date = await get_company_local_date(db, company_id)

    # لا نخفي أي ذمة غير مسواة مهما كان عمرها أو حالة حساب المندوب.
    # الجلسات المسواة تظهر فقط إذا كانت من يوم الشركة الحالي.
    sessions = (
        await db.execute(
            select(WorkSession)
            .options(joinedload(WorkSession.driver))
            .filter(
                WorkSession.company_id == company_id,
                or_(
                    WorkSession.session_date == company_local_date,
                    WorkSession.is_settled.is_(False),
                ),
            )
            .order_by(WorkSession.id.desc())
        )
    ).scalars().all()
    if not sessions:
        return []

    session_ids = [int(session.id) for session in sessions]
    stats_rows = (
        await db.execute(
            select(
                Visit.work_session_id,
                func.count(Visit.id).label("total_visits"),
                func.sum(case((Visit.outcome == "Sale", 1), else_=0)).label("successful_sales"),
                func.sum(Visit.cash_collected).label("total_cash"),
                func.sum(Visit.debt_paid).label("total_debt"),
            )
            .filter(
                Visit.company_id == company_id,
                Visit.work_session_id.in_(session_ids),
                Visit.status == "Completed",
            )
            .group_by(Visit.work_session_id)
        )
    ).all()
    stats_map = {int(row.work_session_id): row for row in stats_rows}

    pending_rows = (
        await db.execute(
            select(Visit.work_session_id, func.count(Visit.id))
            .filter(
                Visit.company_id == company_id,
                Visit.work_session_id.in_(session_ids),
                Visit.status == "Pending",
            )
            .group_by(Visit.work_session_id)
        )
    ).all()
    pending_map = {int(session_id): int(count or 0) for session_id, count in pending_rows}

    shortage_cash_map = await _dispatch_driver_shortage_cash_map(
        db,
        company_id=company_id,
        work_session_ids=session_ids,
    )

    inventory_map, route_map = await _dispatch_session_inventory_projection(
        db,
        company_id=company_id,
        sessions=sessions,
    )

    result = []
    for session in sessions:
        driver = session.driver
        if driver is None:
            raise HTTPException(
                status_code=409,
                detail=f"جلسة العمل ({session.id}) لا تملك مندوباً صالحاً داخل الشركة.",
            )

        sid = int(session.id)
        stats = stats_map.get(sid)
        cash_from_sales = Decimal(str(stats.total_cash or "0.000")) if stats else Decimal("0.000")
        cash_from_debts = Decimal(str(stats.total_debt or "0.000")) if stats else Decimal("0.000")
        shortage_cash = shortage_cash_map.get(sid, Decimal("0.000"))
        expected_cash = cash_from_sales + cash_from_debts + shortage_cash
        is_on_break = bool(session.break_start_time and not session.break_end_time)

        if session.is_settled:
            status_str = "تمت التسوية"
        elif session.inventory_reconciled_at is not None:
            status_str = "تمت التسوية المخزنية بانتظار المالية"
        elif session.end_time is not None:
            status_str = "مغلقة بانتظار التسوية المخزنية"
        elif is_on_break:
            status_str = "استراحة"
        else:
            status_str = "في الطريق"

        route = route_map.get(sid)
        vehicle_label = (
            route.vehicle.plate_number
            if route is not None and route.vehicle is not None
            else "بدون سيارة"
        )

        result.append({
            "session": {
                "session_id": sid,
                "driver_name": driver.full_name,
                "start_time": (
                    session.start_time.replace(tzinfo=timezone.utc).isoformat()
                    if session.start_time else None
                ),
                "is_authorized_to_sell": session.is_authorized_to_sell,
                "is_on_break": is_on_break,
                "vehicle_label": vehicle_label,
            },
            "settlement": {
                "driver_name": driver.full_name,
                "status": status_str,
                "financials": {
                    "expected_cash_in_hand": str(expected_cash),
                    "cash_from_sales": str(cash_from_sales),
                    "cash_from_debts": str(cash_from_debts),
                    "inventory_shortage_cash": str(shortage_cash),
                },
                "visits": {
                    "completed_total": int(stats.total_visits or 0) if stats else 0,
                    "successful_sales": int(stats.successful_sales or 0) if stats else 0,
                    "pending_remaining": pending_map.get(sid, 0),
                },
                "inventory": inventory_map.get(sid, []),
            },
        })

    rank = {
        "في الطريق": 1,
        "استراحة": 2,
        "مغلقة بانتظار التسوية المخزنية": 3,
        "تمت التسوية المخزنية بانتظار المالية": 4,
        "تمت التسوية": 5,
    }
    result.sort(key=lambda row: rank.get(row["settlement"]["status"], 99))
    return result

# =========================================
# 3. تقرير التسوية اليومية - Snapshot/Movement projection فقط
# =========================================
@router.get("/admin/sessions/{session_id}/settlement_report", response_model=SessionSettlementReportResponse, status_code=200)
async def get_session_settlement_report(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id
    session = (
        await db.execute(
            select(WorkSession)
            .options(joinedload(WorkSession.driver))
            .filter_by(company_id=company_id, id=session_id)
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="الجلسة غير موجودة")

    stats = (
        await db.execute(
            select(
                func.count(Visit.id).label("total_visits"),
                func.sum(case((Visit.outcome == "Sale", 1), else_=0)).label("sales_count"),
                func.sum(Visit.cash_collected).label("total_cash"),
                func.sum(Visit.debt_paid).label("total_debt"),
            )
            .filter(
                Visit.company_id == company_id,
                Visit.work_session_id == session.id,
                Visit.status == "Completed",
            )
        )
    ).first()

    pending_count = int((
        await db.execute(
            select(func.count(Visit.id)).filter(
                Visit.company_id == company_id,
                Visit.work_session_id == session.id,
                Visit.status == "Pending",
            )
        )
    ).scalar() or 0)

    inventory_map, _ = await _dispatch_session_inventory_projection(
        db,
        company_id=company_id,
        sessions=[session],
    )

    sample_rows = (
        await db.execute(
            select(VisitItem, Shop.name, ProductVariant.name)
            .join(
                Visit,
                and_(
                    Visit.company_id == VisitItem.company_id,
                    Visit.id == VisitItem.visit_id,
                ),
            )
            .join(
                Shop,
                and_(
                    Shop.company_id == Visit.company_id,
                    Shop.id == Visit.shop_id,
                ),
            )
            .join(
                ProductVariant,
                and_(
                    ProductVariant.company_id == VisitItem.company_id,
                    ProductVariant.id == VisitItem.product_variant_id,
                ),
            )
            .filter(
                VisitItem.company_id == company_id,
                Visit.company_id == company_id,
                Visit.work_session_id == session.id,
                Visit.status == "Completed",
                VisitItem.is_cancelled.is_(False),
                or_(VisitItem.sample_quantity > 0, VisitItem.sample_packs_quantity > 0),
            )
            .order_by(Visit.id.asc(), VisitItem.id.asc())
        )
    ).all()
    samples_list = [{
        "shop_name": shop_name,
        "product_name": product_name,
        "sample_quantity_cartons": int(item.sample_quantity or 0),
        "sample_quantity_packs": int(item.sample_packs_quantity or 0),
        "reason": item.sample_reason or "بدون سبب",
    } for item, shop_name, product_name in sample_rows]

    cash_from_sales = Decimal(str(stats.total_cash or "0.000")) if stats else Decimal("0.000")
    cash_from_debts = Decimal(str(stats.total_debt or "0.000")) if stats else Decimal("0.000")
    shortage_cash = await _dispatch_driver_shortage_cash(
        db,
        company_id=company_id,
        work_session_id=session.id,
    )
    expected_cash = cash_from_sales + cash_from_debts + shortage_cash

    if session.is_settled:
        status_str = "تمت التسوية"
    elif session.inventory_reconciled_at is not None:
        status_str = "تمت التسوية المخزنية بانتظار المالية"
    elif session.end_time is not None:
        status_str = "مغلقة بانتظار التسوية المخزنية"
    else:
        status_str = "جلسة نشطة"

    return {
        "driver_name": session.driver.full_name if session.driver else "غير معروف",
        "session_date": session.session_date,
        "status": status_str,
        "financials": {
            "expected_cash_in_hand": str(expected_cash),
            "cash_from_sales": str(cash_from_sales),
            "cash_from_debts": str(cash_from_debts),
            "inventory_shortage_cash": str(shortage_cash),
        },
        "visits": {
            "completed_total": int(stats.total_visits or 0) if stats else 0,
            "successful_sales": int(stats.sales_count or 0) if stats else 0,
            "pending_remaining": pending_count,
        },
        "inventory": inventory_map.get(int(session.id), []),
        "samples_given": samples_list,
    }

# =========================================
# 4. اعتماد التسوية المالية فقط - المخزون مختوم مسبقاً في reconciliation.py
# =========================================
@router.put("/admin/sessions/{session_id}/settle", response_model=SettleSessionResponse, status_code=200)
async def settle_session(
    session_id: int,
    payload: SettleSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id

    try:
        session = (
            await db.execute(
                select(WorkSession)
                .filter_by(company_id=company_id, id=session_id)
                .order_by(WorkSession.id.asc())
                .with_for_update()
            )
        ).scalar_one_or_none()
        if session is None:
            raise HTTPException(status_code=404, detail="الجلسة غير موجودة")
        if session.is_settled:
            raise HTTPException(status_code=409, detail="الجلسة تمت تسويتها مالياً مسبقاً.")
        if session.end_time is None:
            raise HTTPException(status_code=400, detail="لا يمكن التسوية المالية قبل إنهاء يوم العمل.")
        if session.inventory_reconciled_at is None or session.inventory_reconciled_by is None:
            raise HTTPException(
                status_code=409,
                detail="لا يمكن التسوية المالية قبل اكتمال التسوية المخزنية وتثبيت Ending Snapshot.",
            )

        incomplete_snapshot_id = (
            await db.execute(
                select(SessionInventorySnapshot.id)
                .filter(
                    SessionInventorySnapshot.company_id == company_id,
                    SessionInventorySnapshot.work_session_id == session.id,
                    or_(
                        SessionInventorySnapshot.ending_quantity.is_(None),
                        SessionInventorySnapshot.settled_by.is_(None),
                        SessionInventorySnapshot.settled_at.is_(None),
                    ),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if incomplete_snapshot_id is not None:
            raise HTTPException(status_code=409, detail="Ending Snapshot للجلسة غير مكتمل.")

        # الحقل يبقى للتوافق مع React القديم فقط. إذا أرسله العميل نتحقق منه ولا نستخدمه لتعديل المخزون.
        if payload.inventory_jard:
            submitted_ids = sorted({int(item.product_id) for item in payload.inventory_jard})
            valid_ids = set((
                await db.execute(
                    select(ProductVariant.id).filter(
                        ProductVariant.company_id == company_id,
                        ProductVariant.id.in_(submitted_ids),
                    )
                )
            ).scalars().all())
            if valid_ids != set(submitted_ids):
                raise HTTPException(status_code=400, detail="أحد أصناف الجرد المرسل لا يتبع الشركة الحالية.")

            ending_rows = (
                await db.execute(
                    select(
                        SessionInventorySnapshot.product_variant_id,
                        func.sum(SessionInventorySnapshot.ending_quantity),
                    )
                    .filter(
                        SessionInventorySnapshot.company_id == company_id,
                        SessionInventorySnapshot.work_session_id == session.id,
                        SessionInventorySnapshot.product_variant_id.in_(submitted_ids),
                        SessionInventorySnapshot.stock_status == "AVAILABLE",
                    )
                    .group_by(SessionInventorySnapshot.product_variant_id)
                )
            ).all()
            ending_map = {int(pid): int(qty or 0) for pid, qty in ending_rows}
            for item in payload.inventory_jard:
                if int(item.actual) != ending_map.get(int(item.product_id), 0):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "الجرد المرسل من شاشة المحاسب لا يطابق Ending Snapshot المختوم. "
                            "حدّث الشاشة؛ تعديل المخزون يتم حصراً عبر reconciliation."
                        ),
                    )

        stats = (
            await db.execute(
                select(
                    func.sum(Visit.cash_collected).label("total_cash"),
                    func.sum(Visit.debt_paid).label("total_debt"),
                )
                .filter(
                    Visit.company_id == company_id,
                    Visit.work_session_id == session.id,
                    Visit.status == "Completed",
                )
            )
        ).first()
        cash_from_sales = Decimal(str(stats.total_cash or "0.000")) if stats else Decimal("0.000")
        cash_from_debts = Decimal(str(stats.total_debt or "0.000")) if stats else Decimal("0.000")
        shortage_cash = await _dispatch_driver_shortage_cash(
            db,
            company_id=company_id,
            work_session_id=session.id,
        )
        expected_cash = cash_from_sales + cash_from_debts + shortage_cash
        actual_cash = Decimal(str(payload.actual_cash))
        if not actual_cash.is_finite() or actual_cash < 0:
            raise HTTPException(status_code=400, detail="قيمة النقد الفعلية غير صالحة.")
        if not expected_cash.is_finite() or expected_cash < 0:
            raise HTTPException(status_code=409, detail="القيمة النقدية المتوقعة للجلسة غير صالحة.")

        cash_difference = actual_cash - expected_cash
        notes = (payload.notes or "").strip() or None
        if cash_difference != Decimal("0.000") and not notes:
            raise HTTPException(
                status_code=400,
                detail=f"يوجد فرق نقدي ({cash_difference}). يجب كتابة تبرير صريح لاعتماد التسوية.",
            )

        # لا نلمس InventoryBalance ولا Ending Snapshot ولا route.work_session_id هنا.
        session.is_settled = True
        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"Session_{session.id}_Driver_{session.driver_id}",
            action_type="FINANCIAL_SETTLEMENT",
            old_value="is_settled=False",
            new_value=(
                f"is_settled=True | expected_cash={expected_cash} | actual_cash={actual_cash} | "
                f"difference={cash_difference} | inventory_shortage_cash={shortage_cash} | "
                f"notes={notes or ''}"
            )[:4000],
        ))

        await db.commit()
        return {
            "message": "تم اعتماد التسوية المالية بنجاح",
            "cash_difference": str(cash_difference),
            "is_settled": True,
        }

    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        logger.error(f"Financial settlement integrity conflict: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=409, detail="تعارض متزامن أثناء اعتماد التسوية المالية.") from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في اعتماد التسوية المالية: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي أثناء اعتماد التسوية المالية.") from exc

# =========================================
# 5. تهيئة شاشة التوزيع (Dispatch Init)
# =========================================
@router.get("/dispatch/init", response_model=DispatchInitResponse, status_code=200)
async def dispatch_init(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver)
):
    access = InventoryAccess(db, current_admin)
    await access.require('dispatch.read', any_location=True)

    company_id = current_admin.company_id
    zones = (await db.execute(
        select(Zone).filter_by(company_id=company_id, is_active=True).order_by(Zone.id.asc())
    )).scalars().all()
    drivers = (await db.execute(
        select(Driver).filter_by(company_id=company_id, is_active=True, is_admin=False).order_by(Driver.id.asc())
    )).scalars().all()
    vehicles = (await db.execute(
        select(Vehicle).filter_by(company_id=company_id, is_active=True).filter(vehicle_filter(access, 'dispatch.read', Vehicle.id)).order_by(Vehicle.id.asc())
    )).scalars().all()
    executable_vehicles = set((await db.scalars(select(Vehicle.id).where(
        Vehicle.company_id == company_id, vehicle_filter(access, 'dispatch.execute', Vehicle.id)))).all())
    warehouses = (await db.execute(select(InventoryLocation).where(
        InventoryLocation.company_id == company_id,
        InventoryLocation.location_type == 'WAREHOUSE',
        InventoryLocation.is_active.is_(True),
        access.location_filter('dispatch.read'),
    ).order_by(InventoryLocation.name.asc(), InventoryLocation.id.asc()))).scalars().all()
    executable_warehouses = set((await db.scalars(select(InventoryLocation.id).where(
        InventoryLocation.company_id == company_id,
        InventoryLocation.location_type == 'WAREHOUSE',
        InventoryLocation.is_active.is_(True),
        access.location_filter('dispatch.execute'),
    ))).all())
    products = (await db.execute(
        select(ProductVariant).where(
            ProductVariant.company_id == company_id,
            product_capability_predicate(ProductVariant, ROUTE_LOAD_NEW),
        ).order_by(ProductVariant.id.asc())
    )).scalars().all()

    shop_counts = (await db.execute(
        select(Shop.zone_id, func.count(Shop.id)).filter(
            Shop.company_id == company_id,
            Shop.is_archived.is_(False),
            Shop.is_active.is_(True),
        ).group_by(Shop.zone_id)
    )).all()
    shop_count_map = {int(row.zone_id): int(row[1]) for row in shop_counts if row.zone_id is not None}

    today = await get_company_local_date(db, company_id)
    zones_data = []
    for zone in zones:
        schedule_status = "null"
        if zone.start_date is not None:
            if zone.start_date < today:
                schedule_status = "overdue"
            elif zone.start_date == today:
                schedule_status = "today"
            else:
                schedule_status = "upcoming"
        interval = int(zone.interval_days) if zone.interval_days is not None else None
        zones_data.append({
            "id": str(zone.id),
            "name": zone.name,
            # compatibility/display only; no backend decision parses these strings.
            "visitDay": "",
            "startDate": zone.start_date.isoformat() if zone.start_date else "",
            "frequency": (f"كل {interval} يوم" if interval else ""),
            "intervalDays": interval,
            "scheduleStatus": schedule_status,
            "shopsCount": shop_count_map.get(int(zone.id), 0),
        })

    return {
        "zones": zones_data,
        "drivers": [{"id": str(d.id), "name": d.full_name} for d in drivers],
        "vehicles": [{"id": str(v.id), "label": f"{v.vehicle_type} - {v.plate_number}",
                      "can_execute": v.id in executable_vehicles} for v in vehicles],
        "warehouses": [{"id": str(w.id), "label": f"{w.name} ({w.code})",
                        "can_execute": w.id in executable_warehouses} for w in warehouses],
        "products": [{"id": str(p.id), "name": p.variant_name} for p in products],
    }



# PATCH: DISPATCH_UNIFIED_INVENTORY_CORE
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
        )
    ).scalar_one_or_none()
    if location is None:
        has_active_warehouse = (
            await db.execute(
                select(InventoryLocation.id).filter(
                    InventoryLocation.company_id == company_id,
                    InventoryLocation.location_type == "WAREHOUSE",
                    InventoryLocation.is_active.is_(True),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if has_active_warehouse is None:
            raise HTTPException(status_code=409, detail=warehouse_setup_required_detail())
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "SOURCE_WAREHOUSE_INVALID",
                "مستودع المصدر غير موجود أو غير فعال أو لا يتبع شركتك.",
            ),
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
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('dispatch.execute', any_location=True)
    await require_vehicle(access, 'dispatch.execute', payload.vehicle_id)

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
        await acquire_inventory_location_guards(
            db,
            company_id,
            [int(source_location.id), vehicle_location_id],
        )
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
        await access.require('dispatch.execute', int(source_location.id))
        await _dispatch_assert_vehicle_custody_reconciled(
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
        await acquire_product_lifecycle_guards(
            db, company_id, all_product_ids, exclusive=False,
        )
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

        source_assignments = {
            int(item.product_variant_id): item
            for item in (await db.scalars(select(ProductLocation).where(
                ProductLocation.company_id == company_id,
                ProductLocation.location_id == int(source_location.id),
                ProductLocation.product_variant_id.in_(all_product_ids),
            ))).all()
        } if all_product_ids else {}

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

        # POST /dispatch/route is the current workflow's Launch point.
        # Pricing writes and this lock share the same Company-row mutex.
        commercial_context = await lock_route_commercial_context(
            db,
            company_id=company_id,
            dispatch_route_id=int(route.id),
        )

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
                load_capability = evaluate_product_capability(
                    variant.lifecycle_status,
                    variant.operational_hold,
                    ROUTE_LOAD_NEW,
                )
                if not load_capability.allowed:
                    raise HTTPException(
                        status_code=409,
                        detail={"code": load_capability.code, "message": f"لا يمكن تحميل المنتج ({variant.variant_name}) إلى السيارة في حالته الحالية."},
                    )
                assignment = source_assignments.get(product_variant_id)
                if assignment is None or not product_location_allows(assignment.operational_flags, ROUTE_LOAD_NEW):
                    raise HTTPException(
                        status_code=409,
                        detail={"code": "PRODUCT_LOCATION_REQUIRED", "message": f"الصنف ({variant.variant_name}) غير مهيأ للصرف من مستودع المصدر."},
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

        # زيارات Route مرتبطة صراحة بيوم الشركة؛ timestamps تبقى UTC للأثر الرقابي فقط.
        shops_in_zone = (
            await db.execute(
                select(Shop).filter_by(
                    company_id=company_id,
                    zone_id=payload.zone_id,
                    is_active=True,
                    is_archived=False,
                ).order_by(Shop.id.asc())
            )
        ).scalars().all()
        shop_ids = [int(shop.id) for shop in shops_in_zone]

        if shop_ids:
            await _dispatch_advisory_locks(
                db,
                company_id=company_id,
                keys=[
                    f"pending-visit:{payload.driver_id}:{shop_id}"
                    for shop_id in shop_ids
                ],
            )
            existing_visits = (
                await db.execute(
                    select(Visit).filter(
                        Visit.company_id == company_id,
                        Visit.driver_id == payload.driver_id,
                        Visit.shop_id.in_(shop_ids),
                        Visit.status == "Pending",
                    ).order_by(Visit.shop_id.asc(), Visit.id.asc())
                )
            ).scalars().all()
            existing_by_shop = {}
            seen_today = set()
            for visit in existing_visits:
                if visit.operational_date == company_local_date:
                    seen_today.add(int(visit.shop_id))
                if visit.status == "Pending":
                    shop_id = int(visit.shop_id)
                    if shop_id in existing_by_shop:
                        raise HTTPException(
                            status_code=409,
                            detail="تم اكتشاف أكثر من زيارة Pending لنفس المندوب والمحل؛ أصلح البيانات قبل إطلاق خط السير.",
                        )
                    visit.work_session_id = None
                    existing_by_shop[shop_id] = visit

            shortage_shop_ids = set((
                await db.execute(
                    select(ShortageRequest.shop_id).filter(
                        ShortageRequest.company_id == company_id,
                        ShortageRequest.shop_id.in_(shop_ids),
                        or_(
                            ShortageRequest.driver_id == payload.driver_id,
                            ShortageRequest.driver_id.is_(None),
                        ),
                        ShortageRequest.status == "pending",
                    )
                )
            ).scalars().all())

            for shop in shops_in_zone:
                shop_id = int(shop.id)
                is_emergency = shop_id in shortage_shop_ids
                existing = existing_by_shop.get(shop_id)
                if existing is None and shop_id not in seen_today:
                    db.add(Visit(
                        company_id=company_id,
                        driver_id=payload.driver_id,
                        shop_id=shop_id,
                        operational_date=company_local_date,
                        status="Pending",
                        sequence=shop.sequence,
                        is_emergency=is_emergency,
                    ))
                elif existing is not None and is_emergency:
                    existing.is_emergency = True

        await db.commit()
        asyncio.create_task(
            dispatch_manager.broadcast(
                {"event": "ROUTE_DISPATCHED", "message": "تم إطلاق خط سير جديد"},
                company_id=company_id,
            )
        )
        return {
            "message": "تم إطلاق خط السير بنجاح",
            "route_id": int(route.id),
            "commercial_context": commercial_context_payload(
                commercial_context
            ),
        }

    except HTTPException:
        await db.rollback()
        raise
    except PricingError as exc:
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
        logger.error(f"Dispatch route integrity conflict: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=409, detail="تعارض متزامن أثناء إطلاق خط السير.") from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في إطلاق خط السير: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي في الخادم أثناء إطلاق خط السير.") from exc

# =========================================
# 7. جلب الحمولة الفعلية للسيارة من InventoryBalance
# =========================================
@router.get("/dispatch/inventory/{vehicle_id}", response_model=List[VehicleInventoryItemResponse], status_code=200)
async def get_vehicle_inventory(
    vehicle_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await require_vehicle(access, 'dispatch.read', vehicle_id)

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
        or_(product_capability_predicate(ProductVariant, ROUTE_LOAD_NEW), ProductVariant.id.in_(loaded_ids))
        if loaded_ids
        else product_capability_predicate(ProductVariant, ROUTE_LOAD_NEW)
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

# =========================================
# 8. جلب الجرد اللحظي الحر لسيارة المسار
# =========================================
@router.get("/dispatch/route/{route_id}/live_inventory", response_model=List[RouteLiveInventoryItemResponse], status_code=200)
async def get_route_live_inventory(
    route_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await require_route(access, 'dispatch.read', route_id)

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
        or_(product_capability_predicate(ProductVariant, ROUTE_LOAD_NEW), ProductVariant.id.in_(loaded_ids))
        if loaded_ids
        else product_capability_predicate(ProductVariant, ROUTE_LOAD_NEW)
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

# +++ دالة مساعدة (مطابقة للفلاسك) لتحويل الحبات إلى نصوص بشرية في الليدجر +++
def format_qty_py(total_packs: int, packs_per_carton: int) -> str:
    if not packs_per_carton or packs_per_carton <= 1:
        return f"{total_packs} حبة"
    is_negative = int(total_packs) < 0
    abs_total = abs(int(total_packs))
    cartons, packs = divmod(abs_total, packs_per_carton)
    parts = []
    if cartons > 0: parts.append(f"{cartons} كرتونة")
    if packs > 0: parts.append(f"{packs} حبة")
    res = " و ".join(parts) if parts else "0 حبة"
    return f"-{res}" if is_negative and res != "0 حبة" else res


# =========================================
# 9. تعديل الحمولة اللحظي - DIRECT قبل الجلسة / HANDSHAKE أثناء الجلسة
# =========================================
# PATCH: DISPATCH_ROUTE_STATUS_UNIFIED
# Route identity is immutable once a WorkSession is bound; inventory uses the unified engine.
async def _dispatch_bound_session(
    db: AsyncSession, *, company_id: int, route: DispatchRoute
):
    if route.work_session_id is None:
        return None
    session = (
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
    if session is None:
        raise HTTPException(status_code=409, detail="خط السير مرتبط بجلسة عمل غير صالحة.")
    return session


async def _dispatch_variant_map(
    db: AsyncSession, *, company_id: int, product_ids
):
    ids = sorted({int(pid) for pid in product_ids})
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(ProductVariant)
            .filter(
                ProductVariant.company_id == company_id,
                ProductVariant.id.in_(ids),
            )
            .order_by(ProductVariant.id.asc())
        )
    ).scalars().all()
    result = {int(row.id): row for row in rows}
    if set(result) != set(ids):
        raise HTTPException(status_code=404, detail="أحد أصناف الحمولة لا يتبع الشركة.")
    return result


async def _dispatch_pending_handshake_net(
    db: AsyncSession,
    *,
    company_id: int,
    work_session_id: int,
    driver_id: int,
    vehicle_location_id: int,
):
    rows = (
        await db.execute(
            select(
                InventoryTransferHeader.source_location_id,
                InventoryTransferHeader.destination_location_id,
                InventoryTransferLine.product_variant_id,
                func.sum(InventoryTransferLine.quantity),
            )
            .join(
                InventoryTransferLine,
                and_(
                    InventoryTransferLine.company_id == InventoryTransferHeader.company_id,
                    InventoryTransferLine.transfer_header_id == InventoryTransferHeader.id,
                ),
            )
            .filter(
                InventoryTransferHeader.company_id == company_id,
                InventoryTransferHeader.work_session_id == work_session_id,
                InventoryTransferHeader.workflow_type == "HANDSHAKE",
                InventoryTransferHeader.status == "PENDING",
                InventoryTransferHeader.expected_receiver_id == driver_id,
                InventoryTransferLine.company_id == company_id,
                or_(
                    InventoryTransferHeader.source_location_id == vehicle_location_id,
                    InventoryTransferHeader.destination_location_id == vehicle_location_id,
                ),
            )
            .group_by(
                InventoryTransferHeader.source_location_id,
                InventoryTransferHeader.destination_location_id,
                InventoryTransferLine.product_variant_id,
            )
        )
    ).all()
    result = {}
    for src, dst, pid, qty in rows:
        signed = int(qty or 0) * (1 if int(dst) == vehicle_location_id else -1)
        result[int(pid)] = result.get(int(pid), 0) + signed
    return result


async def _dispatch_apply_pack_deltas(
    db: AsyncSession,
    *,
    company_id: int,
    route: DispatchRoute,
    admin: Driver,
    session,
    variants,
    pack_deltas,
    plan_targets,
    audit_action: str,
):
    deltas = {int(pid): int(qty) for pid, qty in pack_deltas.items() if int(qty)}
    if route.vehicle_id is None or route.source_location_id is None:
        raise HTTPException(status_code=409, detail="المسار لا يملك سيارة ومستودع مصدر صالحين.")

    await _dispatch_assert_vehicle_custody_reconciled(
        db,
        company_id=company_id,
        vehicle_id=int(route.vehicle_id),
        allowed_work_session_id=(int(session.id) if session is not None else None),
    )

    warehouse = await _dispatch_source_warehouse(
        db, company_id=company_id, location_id=int(route.source_location_id)
    )
    vehicle_location_id = await _dispatch_vehicle_location_id(
        db, company_id=company_id, vehicle_id=int(route.vehicle_id)
    )
    await acquire_inventory_location_guards(
        db,
        company_id,
        [int(warehouse.id), vehicle_location_id],
    )
    warehouse = await _dispatch_source_warehouse(
        db, company_id=company_id, location_id=int(route.source_location_id)
    )
    vehicle_location_id = await _dispatch_vehicle_location_id(
        db, company_id=company_id, vehicle_id=int(route.vehicle_id)
    )
    as_of_date = await get_company_local_date(db, company_id)
    mode = "NO_CHANGE"

    positive_variant_ids = sorted(pid for pid, delta in deltas.items() if delta > 0)
    await acquire_product_lifecycle_guards(
        db, company_id, positive_variant_ids, exclusive=False,
    )
    source_assignments = {
        int(item.product_variant_id): item
        for item in (await db.scalars(select(ProductLocation).where(
            ProductLocation.company_id == company_id,
            ProductLocation.location_id == int(warehouse.id),
            ProductLocation.product_variant_id.in_(positive_variant_ids),
        ))).all()
    } if positive_variant_ids else {}

    # قفل أرصدة المصدر/السيارة بترتيب عالمي ثابت قبل FEFO لمنع Deadlock عكسي
    # عندما يجري تحميل وسحب متزامنان لنفس الصنف بين نفس الموقعين.
    if deltas:
        await db.execute(
            select(InventoryBalance.id)
            .filter(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id.in_(
                    sorted({int(warehouse.id), vehicle_location_id})
                ),
                InventoryBalance.product_variant_id.in_(sorted(deltas)),
                InventoryBalance.stock_status == "AVAILABLE",
            )
            .order_by(
                InventoryBalance.location_id.asc(),
                InventoryBalance.product_variant_id.asc(),
                InventoryBalance.batch_id.asc(),
                InventoryBalance.id.asc(),
            )
            .with_for_update()
        )

    if session is not None and deltas:
        specs = []
        batch_token = f"BATCH_{uuid4().hex[:16].upper()}"
        for pid in sorted(deltas):
            delta = deltas[pid]
            variant = variants[pid]
            if delta > 0:
                load_capability = evaluate_product_capability(
                    variant.lifecycle_status, variant.operational_hold, ROUTE_LOAD_NEW,
                )
                if not load_capability.allowed:
                    raise HTTPException(status_code=409, detail={"code": load_capability.code, "message": f"لا يمكن تحميل المنتج ({variant.variant_name}) في حالته الحالية."})
                assignment = source_assignments.get(pid)
                if assignment is None or not product_location_allows(assignment.operational_flags, ROUTE_LOAD_NEW):
                    raise HTTPException(status_code=409, detail={"code": "PRODUCT_LOCATION_REQUIRED", "message": f"الصنف ({variant.variant_name}) غير مهيأ للصرف من مستودع المصدر."})
                src, dst, sellable = int(warehouse.id), vehicle_location_id, True
            else:
                src, dst, sellable = vehicle_location_id, int(warehouse.id), False

            await check_inventory_lock(db, company_id, src, variant_id=pid)
            await check_inventory_lock(db, company_id, dst, variant_id=pid)
            allocations = await _dispatch_allocate_available_batches(
                db,
                company_id=company_id,
                location_id=src,
                product_variant_id=pid,
                quantity=abs(delta),
                as_of_date=as_of_date,
                require_sellable=sellable,
            )
            transfer_purpose = "ROUTE_LOAD" if delta > 0 else "ROUTE_RETURN"
            source_location_type = "WAREHOUSE" if delta > 0 else "VEHICLE"
            destination_location_type = "VEHICLE" if delta > 0 else "WAREHOUSE"
            header = InventoryTransferHeader(
                company_id=company_id,
                reference_number=f"HS-{uuid4().hex.upper()}",
                source_location_id=src,
                destination_location_id=dst,
                workflow_type="HANDSHAKE",
                status="PENDING",
                transfer_purpose=transfer_purpose,
                commercial_context={
                    "schema_version": 1,
                    "commercial_context_id": None,
                    "tenant_policy_revision": None,
                    "route_id": int(route.id),
                    "work_session_id": int(session.id),
                    "source_location_type": source_location_type,
                    "destination_location_type": destination_location_type,
                    "transfer_purpose": transfer_purpose,
                },
                work_session_id=session.id,
                expected_receiver_id=route.driver_id,
                dispatched_by=admin.id,
                notes=batch_token,
            )
            db.add(header)
            await db.flush()
            for batch_id, quantity in allocations:
                line = InventoryTransferLine(
                    company_id=company_id,
                    transfer_header_id=header.id,
                    product_variant_id=pid,
                    batch_id=batch_id,
                    quantity=quantity,
                    source_stock_status="AVAILABLE",
                    lifecycle_revision_snapshot=int(variant.lifecycle_revision),
                    lifecycle_status_snapshot=str(variant.lifecycle_status),
                    operational_hold_snapshot=str(variant.operational_hold),
                )
                db.add(line)
                specs.append({
                    "product_variant_id": pid,
                    "batch_id": batch_id,
                    "quantity": quantity,
                    "movement_kind": "RESERVATION",
                    "reservation_action": "RESERVE",
                    "reference_type": "HANDSHAKE_RESERVE",
                    "reference_id": header.reference_number,
                    "idempotency_key": f"HS-RES-{header.id}-{batch_id}",
                    "source_location_id": src,
                    "destination_location_id": src,
                    "source_stock_status": "AVAILABLE",
                    "destination_stock_status": "AVAILABLE",
                    "work_session_id": session.id,
                    "transfer_header_id": header.id,
                    "notes": "حجز مصدر مصافحة Dispatch حتى قرار المندوب.",
                })
        if len(specs) > 10_000:
            raise HTTPException(status_code=400, detail="تعديل الحمولة يتجاوز الحد الآمن.")
        await apply_inventory_movements_batch(
            db, company_id=company_id, performed_by=admin.id, movements=specs
        )
        mode = "HANDSHAKE"

    elif session is None and deltas:
        current = await _dispatch_available_totals(
            db, company_id=company_id, location_id=vehicle_location_id
        )
        if any(reserved for _, reserved in current.values()):
            raise HTTPException(status_code=409, detail="السيارة تحمل حجوزات معلقة.")
        specs, token = [], uuid4().hex[:16].upper()
        for pid in sorted(deltas):
            delta, variant = deltas[pid], variants[pid]
            if current.get(pid, (0, 0))[0] + delta < 0:
                raise HTTPException(status_code=400, detail=f"رصيد السيارة من ({variant.variant_name}) لا يكفي.")
            if delta > 0:
                load_capability = evaluate_product_capability(
                    variant.lifecycle_status, variant.operational_hold, ROUTE_LOAD_NEW,
                )
                if not load_capability.allowed:
                    raise HTTPException(status_code=409, detail={"code": load_capability.code, "message": f"لا يمكن تحميل المنتج ({variant.variant_name}) في حالته الحالية."})
                assignment = source_assignments.get(pid)
                if assignment is None or not product_location_allows(assignment.operational_flags, ROUTE_LOAD_NEW):
                    raise HTTPException(status_code=409, detail={"code": "PRODUCT_LOCATION_REQUIRED", "message": f"الصنف ({variant.variant_name}) غير مهيأ للصرف من مستودع المصدر."})
                src, dst, sellable, ref = int(warehouse.id), vehicle_location_id, True, "DISPATCH_LOAD"
            else:
                src, dst, sellable, ref = vehicle_location_id, int(warehouse.id), False, "DISPATCH_UNLOAD"
            await check_inventory_lock(db, company_id, src, variant_id=pid)
            await check_inventory_lock(db, company_id, dst, variant_id=pid)
            allocations = await _dispatch_allocate_available_batches(
                db,
                company_id=company_id,
                location_id=src,
                product_variant_id=pid,
                quantity=abs(delta),
                as_of_date=as_of_date,
                require_sellable=sellable,
            )
            for idx, (batch_id, quantity) in enumerate(allocations):
                specs.append({
                    "product_variant_id": pid,
                    "batch_id": batch_id,
                    "quantity": quantity,
                    "movement_kind": "PHYSICAL",
                    "reference_type": ref,
                    "reference_id": str(route.id),
                    "idempotency_key": f"DSP-ADJ-{route.id}-{token}-{pid}-{batch_id}-{idx}",
                    "source_location_id": src,
                    "destination_location_id": dst,
                    "source_stock_status": "AVAILABLE",
                    "destination_stock_status": "AVAILABLE",
                    "work_session_id": None,
                    "transfer_header_id": None,
                    "notes": "تعديل حمولة Dispatch قبل بدء WorkSession.",
                })
        if len(specs) > 10_000:
            raise HTTPException(status_code=400, detail="تعديل الحمولة يتجاوز الحد الآمن.")
        await apply_inventory_movements_batch(
            db, company_id=company_id, performed_by=admin.id, movements=specs
        )
        mode = "DIRECT"

    for pid, target in sorted((plan_targets or {}).items()):
        await _dispatch_set_load_plan_target(
            db,
            company_id=company_id,
            route_id=route.id,
            product_variant_id=int(pid),
            target_quantity_packs=int(target),
            updated_by=admin.id,
        )

    if deltas:
        details = " | ".join(
            f"{variants[pid].variant_name}: {deltas[pid]:+d} حبة"
            for pid in sorted(deltas)
        )[:4000]
        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=admin.id,
            target_id=f"Route_{route.id}",
            action_type=audit_action,
            old_value="InventoryBalance لا يُعدّل مباشرة",
            new_value=details,
        ))
    return mode


async def _dispatch_absolute_targets(
    db: AsyncSession,
    *,
    company_id: int,
    route: DispatchRoute,
    admin: Driver,
    session,
    inventory,
):
    targets = {}
    for raw_pid, qty in inventory.items():
        try:
            pid = int(str(raw_pid).strip())
            cartons = int(qty)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="بيانات الحمولة غير صالحة.") from exc
        if pid <= 0 or cartons < 0:
            raise HTTPException(status_code=400, detail="بيانات الحمولة غير صالحة.")
        targets[pid] = cartons

    vehicle_location_id = await _dispatch_vehicle_location_id(
        db, company_id=company_id, vehicle_id=int(route.vehicle_id)
    )
    current = await _dispatch_available_totals(
        db, company_id=company_id, location_id=vehicle_location_id
    )
    pending = (
        await _dispatch_pending_handshake_net(
            db,
            company_id=company_id,
            work_session_id=session.id,
            driver_id=route.driver_id,
            vehicle_location_id=vehicle_location_id,
        )
        if session is not None
        else {}
    )
    product_ids = sorted(targets if session is not None else set(targets) | set(current))
    variants = await _dispatch_variant_map(db, company_id=company_id, product_ids=product_ids)

    deltas, plan_targets = {}, {}
    for pid in product_ids:
        ppc = int(variants[pid].packs_per_carton or 0)
        if ppc <= 0:
            raise HTTPException(status_code=409, detail=f"إعداد التعبئة غير صالح للصنف ({variants[pid].variant_name}).")
        target = targets.get(pid, 0) * ppc
        if target > _DB_INT_MAX_DISPATCH:
            raise HTTPException(status_code=400, detail="حمولة الصنف تتجاوز سعة INTEGER.")
        projected = current.get(pid, (0, 0))[0] + pending.get(pid, 0)
        if projected < 0:
            raise HTTPException(status_code=409, detail="المصافحات المعلقة تتجاوز الرصيد الفعلي.")
        plan_targets[pid] = target
        if target != projected:
            deltas[pid] = target - projected

    return await _dispatch_apply_pack_deltas(
        db,
        company_id=company_id,
        route=route,
        admin=admin,
        session=session,
        variants=variants,
        pack_deltas=deltas,
        plan_targets=plan_targets,
        audit_action="ROUTE_TARGET_INVENTORY_UPDATE",
    )

async def _dispatch_sync_route_plan_to_current_vehicle(
    db: AsyncSession,
    *,
    company_id: int,
    route: DispatchRoute,
    updated_by: int,
) -> None:
    if route.vehicle_id is None:
        raise HTTPException(status_code=409, detail="خط السير لا يملك سيارة لتهيئة خطة الحمولة.")

    vehicle_location_id = await _dispatch_vehicle_location_id(
        db,
        company_id=company_id,
        vehicle_id=int(route.vehicle_id),
    )
    current = await _dispatch_available_totals(
        db,
        company_id=company_id,
        location_id=vehicle_location_id,
    )
    if any(reserved > 0 for _, reserved in current.values()):
        raise HTTPException(
            status_code=409,
            detail="السيارة تحمل حجوزات معلقة؛ لا يمكن ربطها بخط السير قبل معالجة الحجوزات.",
        )

    await db.execute(
        delete(DispatchLoadPlanLine).where(
            DispatchLoadPlanLine.company_id == company_id,
            DispatchLoadPlanLine.dispatch_route_id == route.id,
        )
    )
    for product_variant_id, (on_hand, _) in sorted(current.items()):
        if on_hand <= 0:
            continue
        db.add(
            DispatchLoadPlanLine(
                company_id=company_id,
                dispatch_route_id=route.id,
                product_variant_id=product_variant_id,
                target_quantity_packs=on_hand,
                updated_by=updated_by,
            )
        )

@router.put("/dispatch/route/{route_id}/adjust_inventory", status_code=200)
async def adjust_route_inventory(
    route_id: int,
    payload: AdjustRouteInventoryRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await require_route(access, 'dispatch.execute', route_id)

    company_id = current_admin.company_id
    canonical_deltas = sorted(
        (
            {
                "product_id": int(item.product_id),
                "delta_cartons": int(item.delta_cartons),
            }
            for item in payload.deltas
        ),
        key=lambda item: item["product_id"],
    )
    request_hash = hashlib.sha256(
        json.dumps(
            {"route_id": int(route_id), "deltas": canonical_deltas},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    try:
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="DISPATCH_ADJUST_ROUTE_INVENTORY",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        route = (
            await db.execute(
                select(DispatchRoute)
                .filter_by(company_id=company_id, id=route_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if route is None or route.driver_id is None or route.vehicle_id is None:
            raise HTTPException(status_code=404, detail="خط السير غير موجود أو غير مكتمل.")

        session = await _dispatch_bound_session(db, company_id=company_id, route=route)
        if session is not None:
            if session.end_time is not None:
                raise HTTPException(status_code=403, detail="لا يمكن تعديل حمولة جلسة انتهى عملها.")
            if session.inventory_reconciled_at is not None:
                raise HTTPException(status_code=409, detail="عهدة الجلسة مختومة مخزنياً.")

        carton_deltas = {}
        for item in payload.deltas:
            pid = int(item.product_id)
            carton_deltas[pid] = carton_deltas.get(pid, 0) + int(item.delta_cartons)
        carton_deltas = {pid: qty for pid, qty in carton_deltas.items() if qty}
        if not carton_deltas:
            raise HTTPException(status_code=400, detail="لم يتم إرسال أي تعديل فعلي.")

        variants = await _dispatch_variant_map(
            db, company_id=company_id, product_ids=carton_deltas
        )
        vehicle_location_id = await _dispatch_vehicle_location_id(
            db, company_id=company_id, vehicle_id=route.vehicle_id
        )
        current = await _dispatch_available_totals(
            db, company_id=company_id, location_id=vehicle_location_id
        )
        pending = (
            await _dispatch_pending_handshake_net(
                db,
                company_id=company_id,
                work_session_id=session.id,
                driver_id=route.driver_id,
                vehicle_location_id=vehicle_location_id,
            )
            if session is not None
            else {}
        )

        deltas, plan_targets = {}, {}
        for pid, cartons in carton_deltas.items():
            ppc = int(variants[pid].packs_per_carton or 0)
            if ppc <= 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"إعداد التعبئة غير صالح للصنف ({variants[pid].variant_name}).",
                )
            delta = cartons * ppc
            projected = current.get(pid, (0, 0))[0] + pending.get(pid, 0)
            target = projected + delta
            if abs(delta) > _DB_INT_MAX_DISPATCH or not (0 <= target <= _DB_INT_MAX_DISPATCH):
                raise HTTPException(
                    status_code=400,
                    detail=f"الحمولة الناتجة للصنف ({variants[pid].variant_name}) خارج النطاق.",
                )
            deltas[pid], plan_targets[pid] = delta, target

        mode = await _dispatch_apply_pack_deltas(
            db,
            company_id=company_id,
            route=route,
            admin=current_admin,
            session=session,
            variants=variants,
            pack_deltas=deltas,
            plan_targets=plan_targets,
            audit_action=(
                "HANDSHAKE_INVENTORY_REQUEST"
                if session is not None
                else "DIRECT_INVENTORY_ADJUSTMENT"
            ),
        )

        response_payload = {
            "message": (
                "تم إرسال الحوالة للمندوب؛ الرصيد الفيزيائي لن يتغير قبل القبول."
                if mode == "HANDSHAKE"
                else "تم تحديث حمولة السيارة عبر محرك المخزون الموحد."
            )
        }
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()

        asyncio.create_task(
            dispatch_manager.broadcast(
                {"event": "INVENTORY_ADJUSTED", "message": "تم تعديل حمولة السيارة"},
                company_id=company_id,
            )
        )
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.error(f"Dispatch inventory conflict: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=409, detail="تعارض متزامن أثناء تعديل الحمولة.") from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في تعديل حمولة المسار: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء تعديل الحمولة.") from exc

# =========================================
# 10. مراقبة حوالات HANDSHAKE للمسؤول
# =========================================
@router.post("/dispatch/transfers/{transfer_id}/force_cancel", status_code=200)
async def force_cancel_handshake(
    transfer_id: int,
    payload: ForceCancelHandshakeRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await require_transfer(access, 'transfer.cancel', transfer_id, 'source')

    company_id = current_admin.company_id
    request_hash = hashlib.sha256(
        json.dumps(
            {"transfer_id": int(transfer_id), "reason": payload.reason.strip()},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="DISPATCH_FORCE_CANCEL_HANDSHAKE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay is not None:
            await db.rollback()
            return replay

        header = (await db.execute(
            select(InventoryTransferHeader).filter(
                InventoryTransferHeader.company_id == company_id,
                InventoryTransferHeader.id == transfer_id,
                InventoryTransferHeader.workflow_type == "HANDSHAKE",
            ).order_by(InventoryTransferHeader.id.asc()).with_for_update()
        )).scalar_one_or_none()
        if header is None:
            raise HTTPException(status_code=404, detail="المصافحة غير موجودة داخل الشركة.")
        if header.status != "PENDING":
            raise HTTPException(status_code=409, detail=f"لا يمكن إلغاء حوالة بحالة {header.status}.")

        lines = (await db.execute(
            select(InventoryTransferLine).filter(
                InventoryTransferLine.company_id == company_id,
                InventoryTransferLine.transfer_header_id == header.id,
            ).order_by(InventoryTransferLine.id.asc()).with_for_update()
        )).scalars().all()
        if not lines:
            raise HTTPException(status_code=409, detail="المصافحة لا تحتوي أسطر مخزون؛ البيانات غير متسقة.")

        specs = [{
            "product_variant_id": int(line.product_variant_id),
            "batch_id": int(line.batch_id),
            "quantity": line.quantity,
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
            "notes": "تحرير حجز المصافحة بعد Force Cancel من المشرف؛ لا توجد حركة PHYSICAL.",
        } for line in lines]
        await apply_inventory_movements_batch(
            db,
            company_id=company_id,
            performed_by=current_admin.id,
            movements=specs,
        )

        now = get_utc_now()
        header.status = "CANCELLED"
        header.cancelled_by = current_admin.id
        header.cancelled_at = now
        header.updated_at = now
        header.decision_reason = payload.reason.strip()
        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"Transfer_{header.id}",
            action_type="HANDSHAKE_FORCE_CANCELLED",
            old_value="PENDING",
            new_value=payload.reason.strip(),
        ))
        response = {
            "message": "تم إلغاء المصافحة وتحرير الحجز بدون أي حركة مخزون فيزيائية.",
            "transfer_id": int(header.id),
            "status": "CANCELLED",
        }
        complete_idempotent_operation(idem, response)
        await db.commit()
        asyncio.create_task(dispatch_manager.broadcast(
            {"event": "HANDSHAKE_CANCELLED", "message": "تم إلغاء حوالة معلقة من الإدارة"},
            company_id=company_id,
        ))
        return response
    except HTTPException:
        await db.rollback(); raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.error(f"Force cancel handshake conflict: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=409, detail="تعارض متزامن أثناء إلغاء المصافحة.") from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"Force cancel handshake failed: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي أثناء إلغاء المصافحة.") from exc


@router.get("/dispatch/route/{route_id}/transfers", response_model=List[RouteTransferResponse], status_code=200)
async def get_route_transfers(
    route_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await require_route(access, 'dispatch.read', route_id)

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

    vehicle_location_ids = set(
        await _dispatch_vehicle_location_ids(
            db,
            company_id=company_id,
            vehicle_id=route.vehicle_id,
        )
    )

    header_rows = (
        await db.execute(
            select(
                InventoryTransferHeader,
                access.allows(
                    'transfer.cancel',
                    InventoryTransferHeader.source_location_id,
                ).label("can_force_cancel"),
            )
            .filter(
                InventoryTransferHeader.company_id == company_id,
                InventoryTransferHeader.work_session_id == route.work_session_id,
                InventoryTransferHeader.workflow_type == "HANDSHAKE",
                InventoryTransferHeader.expected_receiver_id == route.driver_id,
            )
            .order_by(
                InventoryTransferHeader.created_at.desc(),
                InventoryTransferHeader.id.desc(),
            )
        )
    ).all()
    headers = [row[0] for row in header_rows]
    if not headers:
        return []

    can_force_cancel_by_header = {
        int(header.id): bool(can_force_cancel)
        for header, can_force_cancel in header_rows
    }

    header_ids = [int(header.id) for header in headers]
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
                ProductVariant.company_id == company_id,
            )
            .group_by(
                InventoryTransferLine.transfer_header_id,
                InventoryTransferLine.product_variant_id,
                ProductVariant.name,
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
            raise HTTPException(
                status_code=409,
                detail=f"الحوالة ({header.id}) تحمل بيانات كمية غير صالحة.",
            )

        source_is_vehicle = int(header.source_location_id) in vehicle_location_ids
        destination_is_vehicle = int(header.destination_location_id) in vehicle_location_ids
        if source_is_vehicle == destination_is_vehicle:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"الحوالة ({header.id}) لا ترتبط بطرف VEHICLE تاريخي واحد فقط "
                    "لهذه السيارة."
                ),
            )
        signed_quantity = quantity if destination_is_vehicle else -quantity

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
            "can_force_cancel": can_force_cancel_by_header.get(int(header.id), False),
        })

    return result

# =========================================
# 11. استرجاع المحلات (شاشة التوزيع - Pagination Limit)
# =========================================
@router.get("/dispatch/shops", response_model=List[DispatchShopResponse], status_code=200)
async def get_dispatch_shops(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver)
):
    
    # تحذير هندسي: تم إزالة  ـ limit(2000) الكارثي لأن يسبب اختلاف المحلات (Data Truncation)
    # ملاحظة: يجب تطبيق Pagination 진ية لاحقاً، ولكن حالياً نجلب المحلات النشطة لoids كوارث التوزيع
    access = InventoryAccess(db, current_admin)
    await access.require('dispatch.read', any_location=True)

    stmt = select(Shop).filter(
    Shop.company_id == current_admin.company_id,
    Shop.is_active == True,
).order_by(nullslast(Shop.sequence.asc()), Shop.id.asc())
    shops = (await db.execute(stmt)).scalars().all()
    
    result = []
    for s in shops:
        result.append({
            "id": str(s.id),
            "name": s.name,
            "owner": s.contact_person.strip() if s.contact_person else "", # +++ تنظيف المالك +++
            "phone": s.phone_number or "",
            "mapLink": s.location_link or "",
            "zoneId": str(s.zone_id) if s.zone_id else "",
            "initialDebt": float(s.current_balance or 0.0),
            "maxDebtLimit": float(s.max_debt_limit or 0.0),
            "sequence": s.sequence if s.sequence is not None else 999, # +++ حماية Pydantic من كراش الـ None +++
            "archived": getattr(s, 'is_archived', False)
        })

    return result


# PATCH: DISPATCH_CONCURRENCY_EMERGENCY_INTEGRITY
# ترتيب الأقفال في Dispatch mutations:
# driver(s) -> vehicle(s) -> zone(s) -> shop advisory -> shop/visit rows.
# Route مربوط بجلسة: WorkSession -> driver/vehicle -> zone -> DispatchRoute.
async def _dispatch_advisory_locks(
    db: AsyncSession,
    *,
    company_id: int,
    keys,
) -> None:
    normalized = sorted({str(key).strip() for key in keys if str(key).strip()})
    if not normalized:
        return
    await db.execute(
        text(
            """
            SELECT pg_advisory_xact_lock(
                CAST(:company_id AS integer),
                hashtext(lock_key)
            )
            FROM unnest(CAST(:keys AS text[])) AS t(lock_key)
            ORDER BY lock_key
            """
        ),
        {"company_id": int(company_id), "keys": normalized},
    )


async def _dispatch_lock_zone_rows(
    db: AsyncSession,
    *,
    company_id: int,
    zone_ids,
):
    ids = sorted({int(zone_id) for zone_id in zone_ids if zone_id is not None})
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Zone)
            .filter(
                Zone.company_id == company_id,
                Zone.id.in_(ids),
            )
            .order_by(Zone.id.asc())
            .with_for_update()
        )
    ).scalars().all()
    result = {int(zone.id): zone for zone in rows}
    if set(result) != set(ids):
        raise HTTPException(
            status_code=404,
            detail="إحدى المناطق غير موجودة أو لا تتبع شركتك.",
        )
    return result


async def _dispatch_lock_shop_rows(
    db: AsyncSession,
    *,
    company_id: int,
    shop_ids,
):
    ids = sorted({int(shop_id) for shop_id in shop_ids})
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Shop)
            .filter(
                Shop.company_id == company_id,
                Shop.id.in_(ids),
            )
            .order_by(Shop.id.asc())
            .with_for_update()
        )
    ).scalars().all()
    result = {int(shop.id): shop for shop in rows}
    if set(result) != set(ids):
        raise HTTPException(
            status_code=404,
            detail="أحد المحلات غير موجود أو لا يتبع شركتك.",
        )
    return result

async def _dispatch_blocking_shop_zone_move_ids(
    db: AsyncSession,
    *,
    company_id: int,
    shop_ids,
):
    ids = sorted({int(shop_id) for shop_id in shop_ids})
    if not ids:
        return set()
    rows = (
        await db.execute(
            select(Visit.shop_id)
            .join(
                Shop,
                and_(Shop.company_id == Visit.company_id, Shop.id == Visit.shop_id),
            )
            .join(
                DispatchRoute,
                and_(
                    DispatchRoute.company_id == Visit.company_id,
                    DispatchRoute.driver_id == Visit.driver_id,
                    DispatchRoute.zone_id == Shop.zone_id,
                    DispatchRoute.status == "active",
                    or_(
                        Visit.work_session_id.is_(None),
                        DispatchRoute.work_session_id == Visit.work_session_id,
                    ),
                ),
            )
            .filter(
                Visit.company_id == company_id,
                Visit.shop_id.in_(ids),
                Visit.status == "Pending",
            )
            .distinct()
        )
    ).scalars().all()
    return {int(shop_id) for shop_id in rows}


# =========================================
# 12. التحديث الجماعي للمحلات (نقل، ترتيب، أرشفة، استعادة)
# =========================================
@router.put("/dispatch/shops/bulk_update", status_code=200)
async def bulk_update_shops(
    payload: List[BulkUpdateShopItem],
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    company_id = current_admin.company_id
    shop_ids = [int(item.id) for item in payload if item.id]
    if not shop_ids:
        return {"message": "لا توجد بيانات للتحديث"}
    if len(shop_ids) != len(set(shop_ids)):
        raise HTTPException(status_code=400, detail="لا يجوز تكرار نفس المحل في طلب التحديث الجماعي.")

    try:
        # Pre-read فقط لاكتشاف ترتيب أقفال المناطق؛ بعد الأقفال نعيد جلب المحلات FOR UPDATE.
        pre_rows = (
            await db.execute(
                select(Shop.id, Shop.zone_id)
                .filter(
                    Shop.company_id == company_id,
                    Shop.id.in_(sorted(shop_ids)),
                )
                .order_by(Shop.id.asc())
            )
        ).all()
        pre_zone_by_shop = {int(shop_id): zone_id for shop_id, zone_id in pre_rows}
        if set(pre_zone_by_shop) != set(shop_ids):
            raise HTTPException(
                status_code=404,
                detail="أحد المحلات غير موجود أو لا يتبع شركتك.",
            )

        zone_ids_to_lock = {
            int(zone_id)
            for zone_id in pre_zone_by_shop.values()
            if zone_id is not None
        }
        for item in payload:
            if item.zoneId is not None:
                zone_ids_to_lock.add(int(item.zoneId))

        locked_zones = await _dispatch_lock_zone_rows(
            db,
            company_id=company_id,
            zone_ids=zone_ids_to_lock,
        )

        # كل عمليات Mutation لنفس المحل تتسلسل على نفس Advisory key.
        await _dispatch_advisory_locks(
            db,
            company_id=company_id,
            keys=[f"dispatch-shop:{shop_id}" for shop_id in sorted(shop_ids)],
        )
        bulk_shops = await _dispatch_lock_shop_rows(
            db,
            company_id=company_id,
            shop_ids=shop_ids,
        )

        # لو تغيرت منطقة محل بين الـpre-read وامتلاك الأقفال نرفض بدلاً من قفل منطقة جديدة بترتيب عكسي.
        for shop_id, shop in bulk_shops.items():
            if shop.zone_id != pre_zone_by_shop[shop_id]:
                raise HTTPException(
                    status_code=409,
                    detail="تغيرت منطقة أحد المحلات بالتزامن. حدّث الشاشة وأعد المحاولة.",
                )

        moving_shop_ids = [
            int(item.id)
            for item in payload
            if item.zoneId is not None
            and int(item.zoneId) != int(bulk_shops[int(item.id)].zone_id or 0)
        ]
        blocked_moves = await _dispatch_blocking_shop_zone_move_ids(
            db, company_id=company_id, shop_ids=moving_shop_ids
        )
        if blocked_moves:
            raise HTTPException(
                status_code=409,
                detail=(
                    "مرفوض: لا يمكن نقل محل إلى منطقة أخرى بينما لديه زيارة Pending "
                    "ضمن خط سير Active. أغلق/أنهِ الزيارة أولاً."
                ),
            )

        archived_shop_ids = []
        for item in payload:
            shop = bulk_shops[int(item.id)]

            target_zone_id = int(item.zoneId) if item.zoneId is not None else shop.zone_id
            if item.zoneId is not None:
                target_zone = locked_zones.get(target_zone_id)
                if target_zone is None or not target_zone.is_active:
                    raise HTTPException(
                        status_code=400,
                        detail="لا يمكن نقل المحل إلى منطقة غير موجودة أو مؤرشفة.",
                    )

            if item.archived is False:
                if target_zone_id is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"لا يمكن استعادة المحل '{shop.name}' بدون منطقة نشطة.",
                    )
                target_zone = locked_zones.get(int(target_zone_id))
                if target_zone is None or not target_zone.is_active:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"لا يمكن استعادة المحل '{shop.name}' لأن منطقته مؤرشفة. "
                            "يرجى نقله لمنطقة نشطة أولاً."
                        ),
                    )

            if item.sequence is not None:
                shop.sequence = int(item.sequence)

            if item.zoneId is not None:
                shop.zone_id = int(item.zoneId)
                # النقل اليدوي يقطع provenance الأرشفة التلقائية القديمة.
                shop.archived_due_to_zone_id = None

            if item.archived is not None:
                shop.is_archived = bool(item.archived)
                shop.archived_due_to_zone_id = None
                if item.archived:
                    archived_shop_ids.append(int(shop.id))

        if archived_shop_ids:
            await db.execute(
                update(Visit)
                .where(
                    Visit.company_id == company_id,
                    Visit.shop_id.in_(sorted(archived_shop_ids)),
                    Visit.status == "Pending",
                )
                .values(status="Cancelled")
            )

        await db.commit()
        return {"message": "تم تحديث المحلات بنجاح"}

    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        logger.error(f"Bulk shop update integrity conflict: {str(exc)}", exc_info=True)
        raise HTTPException(
            status_code=409,
            detail="تعارض متزامن أثناء تحديث المحلات. حدّث الشاشة وأعد المحاولة.",
        ) from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء التحديث الجماعي.") from exc


# =========================================
# 13. إضافة محل جديد من لوحة التحكم (مع كاشف التكرار الذكي)
# =========================================
@router.post("/dispatch/shops", status_code=201)
async def admin_add_shop(
    payload: AdminAddShopRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    company_id = current_admin.company_id
    name = payload.name.strip()
    phone = payload.phone.strip() if payload.phone and payload.phone.strip() else None
    map_link = payload.mapLink.strip() if payload.mapLink else ""
    zone_id = int(payload.zoneId)

    # Pydantic أنهى التحقق من الإحداثيات/الأموال؛ نحافظ على القيم كما وصلت بلا تصحيح صامت.
    lat = float(payload.latitude) if payload.latitude is not None else None
    lng = float(payload.longitude) if payload.longitude is not None else None

    try:
        zones = await _dispatch_lock_zone_rows(
            db,
            company_id=company_id,
            zone_ids=[zone_id],
        )
        if not zones[zone_id].is_active:
            raise HTTPException(
                status_code=400,
                detail="المنطقة المحددة مؤرشفة ولا يمكن إضافة محل جديد إليها.",
            )

        if phone:
            await _dispatch_advisory_locks(
                db,
                company_id=company_id,
                keys=[f"shop-phone:{phone}"],
            )

        duplicate_shop = None

        if phone:
            duplicate_shop = (
                await db.execute(
                    select(Shop)
                    .options(joinedload(Shop.zone))
                    .filter(
                        Shop.company_id == company_id,
                        Shop.phone_number == phone,
                    )
                    .order_by(Shop.id.asc())
                )
            ).scalars().first()

        if duplicate_shop is None and name and map_link:
            duplicate_shop = (
                await db.execute(
                    select(Shop)
                    .options(joinedload(Shop.zone))
                    .filter(
                        Shop.company_id == company_id,
                        Shop.name == name,
                        Shop.location_link == map_link,
                    )
                    .order_by(Shop.id.asc())
                )
            ).scalars().first()

        if duplicate_shop is None and lat is not None and lng is not None:
            duplicate_shop = (
                await db.execute(
                    select(Shop)
                    .options(joinedload(Shop.zone))
                    .filter(
                        Shop.company_id == company_id,
                        Shop.name == name,
                        Shop.latitude.isnot(None),
                        Shop.longitude.isnot(None),
                        func.abs(cast(Shop.latitude, Float) - lat) < 0.0001,
                        func.abs(cast(Shop.longitude, Float) - lng) < 0.0001,
                    )
                    .order_by(Shop.id.asc())
                )
            ).scalars().first()

        if duplicate_shop and not payload.force_save:
            zone_name = duplicate_shop.zone.name if duplicate_shop.zone else "بدون منطقة"
            is_arch_msg = " (مؤرشف)" if duplicate_shop.is_archived else ""
            duplicate_payload = {
                "message": "تنبيه: يوجد محل مسجل مسبقاً بمعلومات مطابقة.",
                "is_duplicate": True,
                "existing_shop": {
                    "id": str(duplicate_shop.id),
                    "name": duplicate_shop.name,
                    "owner": duplicate_shop.contact_person or "غير مسجل",
                    "phone": duplicate_shop.phone_number,
                    "mapLink": duplicate_shop.location_link,
                    "zone_name": zone_name + is_arch_msg,
                },
            }
            await db.rollback()
            return JSONResponse(status_code=409, content=duplicate_payload)

        # force_save لا يستطيع تجاوز قيد الهاتف الصلب داخل Tenant.
        if duplicate_shop and phone and duplicate_shop.phone_number == phone:
            raise HTTPException(
                status_code=409,
                detail="رقم الهاتف مستخدم لمحل آخر داخل الشركة ولا يمكن تجاوزه بالحفظ الإجباري.",
            )

        new_shop = Shop(
            company_id=company_id,
            name=name,
            contact_person=payload.owner.strip() if payload.owner else "",
            phone_number=phone,
            location_link=map_link,
            latitude=payload.latitude,
            longitude=payload.longitude,
            zone_id=zone_id,
            is_active=True,
            is_archived=False,
            current_balance=payload.initialDebt,
            max_debt_limit=payload.maxDebtLimit,
            added_by_driver_id=current_admin.id,
            sequence=int(payload.sequence),
        )
        db.add(new_shop)
        await db.flush()
        shop_id = int(new_shop.id)

        await db.commit()
        return {"message": "تم إضافة المحل بنجاح", "shop_id": str(shop_id)}

    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        logger.error(f"Admin add shop integrity conflict: {str(exc)}", exc_info=True)
        raise HTTPException(
            status_code=409,
            detail="تعذر إضافة المحل بسبب تعارض بيانات فريدة داخل الشركة.",
        ) from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء إضافة المحل.") from exc


# =========================================
# 14. استرجاع خطوط السير النشطة والمؤجلة (غرفة مراقبة المدير)
# =========================================
@router.get("/dispatch/active_routes", response_model=List[ActiveRouteResponse], status_code=200)
async def get_active_routes(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver)
):
    
        
    access = InventoryAccess(db, current_admin)
    await access.require('dispatch.read', any_location=True)

    stmt_routes = (
        select(
            DispatchRoute,
            route_filter(access, 'dispatch.execute').label('can_execute'),
            RouteCommercialContext,
        )
        .outerjoin(
            RouteCommercialContext,
            and_(
                RouteCommercialContext.company_id == DispatchRoute.company_id,
                RouteCommercialContext.dispatch_route_id == DispatchRoute.id,
            ),
        )
        .filter(
            DispatchRoute.company_id == current_admin.company_id,
            route_filter(access, 'dispatch.read'),
            DispatchRoute.status.in_(['active', 'waiting', 'postponed']),
        )
    )
    route_rows = (await db.execute(stmt_routes)).all()
    routes = [row[0] for row in route_rows]
    executable_routes = {row[0].id: bool(row[1]) for row in route_rows}
    commercial_context_by_route = {
        row[0].id: (
            commercial_context_payload(row[2]) if row[2] is not None else None
        )
        for row in route_rows
    }
    
    # +++ تدمير N+1 باستخدام القواميس (Dictionaries) مع تنظيف التكرار عبر Set لحماية السيرفر +++
    zone_ids = list({r.zone_id for r in routes if r.zone_id})
    driver_ids = list({r.driver_id for r in routes if r.driver_id})
    session_ids = list({r.work_session_id for r in routes if r.work_session_id})
    
    zones_map = {}
    if zone_ids:
        stmt_zones = select(Zone.id, Zone.name).filter(
            Zone.company_id == current_admin.company_id,
            Zone.id.in_(zone_ids)
        )
        zones_map = {z_id: z_name for z_id, z_name in (await db.execute(stmt_zones)).all()}

    drivers_map = {}
    if driver_ids:
        stmt_drivers = select(Driver.id, Driver.full_name).filter(
            Driver.company_id == current_admin.company_id,
            Driver.id.in_(driver_ids)
        )
        drivers_map = {d_id: d_name for d_id, d_name in (await db.execute(stmt_drivers)).all()}

    pending_visits_map = {}
    session_ended_map = {} 
    
    if driver_ids:
        # +++  لـ "كمين الصفر": نعد المحلات المعلقة بضربة واحدة للداتابيز (O(1)) +++
        active_zone_ids = list({r.zone_id for r in routes if r.status == 'active' and r.zone_id})
        
        if active_zone_ids:
            # +++ Clean Code (Labeling) لتأمين البيانات وحماية الـ Indexing +++
            stmt_pending = select(Visit.driver_id, func.count(Visit.id).label('pending_count')).join(
                Shop, Visit.shop_id == Shop.id
            ).filter(
                Visit.company_id == current_admin.company_id,
                Shop.company_id == current_admin.company_id,
                Visit.driver_id.in_(driver_ids),
                Visit.status == 'Pending',
                or_(Shop.zone_id.in_(active_zone_ids), Visit.is_emergency == True)
            ).group_by(Visit.driver_id)
            
            pending_counts = (await db.execute(stmt_pending)).all()
            # +++ استخدام الأسماء الصريحة بناءً على اقتراح البوت +++
            pending_visits_map = {row.driver_id: row.pending_count for row in pending_counts}
        
        # +++ جلب حالات نهاية الجلسة O(1) +++
        if session_ids:
            stmt_sessions = select(WorkSession.id, WorkSession.end_time).filter(
                WorkSession.company_id == current_admin.company_id,
                WorkSession.id.in_(session_ids)
            )
            sessions_info = (await db.execute(stmt_sessions)).all()
            session_ended_map = {s_id: (end_t is not None) for s_id, end_t in sessions_info}
    
    # +++ حساب المحلات (المتبقية فقط) في المنطقة التي ليس لها مندوب +++
    # نعد فقط الزيارات المحررة (الأيتام) التي لم تنجز بعد
    stmt_shop_counts = select(Shop.zone_id, func.count(Visit.id)).join(
        Visit, Shop.id == Visit.shop_id
    ).filter(
        Shop.company_id == current_admin.company_id,
        Visit.company_id == current_admin.company_id,
        Shop.is_active == True,
        Shop.is_archived == False,
        Visit.status == 'Pending',
        Visit.driver_id.is_(None) # استخدام is_(None) للآمان في SQLAlchemy
    ).group_by(Shop.zone_id)
    
    shop_counts = (await db.execute(stmt_shop_counts)).all()
    zone_shops_map = {z_id: count for z_id, count in shop_counts}

    res = []
    for r in routes:
        # اللوجيك الأصلي: إذا كان الخط نشطاً والمندوب موجوداً، احسب الزيارات المعلقة للمندوب.
        # أما إذا كان موقوفاً أو بدون مندوب، فالمحلات المتبقية هي كل محلات المنطقة.
        if r.status == 'active' and r.driver_id:
            shops_remaining = pending_visits_map.get(r.driver_id, 0)
        else:
            shops_remaining = zone_shops_map.get(r.zone_id, 0)
            
        session_ended = session_ended_map.get(r.work_session_id, False) if r.work_session_id else False
            
        res.append({
            "id": str(r.id),
            "zoneId": str(r.zone_id) if r.zone_id else "",
            "zoneName": zones_map.get(r.zone_id, "منطقة محذوفة"),
            "driverId": str(r.driver_id) if r.driver_id else "",
            "driverName": drivers_map.get(r.driver_id, "بدون مندوب") if r.driver_id else "بدون مندوب",
            "vehicleId": str(r.vehicle_id) if r.vehicle_id else "",
            "shopsRemaining": shops_remaining,
            "status": r.status,
            "sessionEnded": session_ended,
            "sessionBound": r.work_session_id is not None,
            "can_execute": executable_routes[r.id],
            "commercial_context": commercial_context_by_route.get(r.id),
        })
        
    return res


# =========================================
# 15. تغيير حالة خط السير (تبديل مندوب، تغيير حالة، تعديل حمولة) - (Zero Trust & No Phantoms)
# =========================================
@router.put("/dispatch/route/{route_id}/status", status_code=200)
async def update_route_status(
    route_id: int,
    payload: UpdateRouteStatusRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await require_route(access, 'dispatch.execute', route_id)

    company_id = current_admin.company_id
    operational_statuses = {"active", "waiting", "postponed"}

    try:
        # Pre-read فقط لاكتشاف ترتيب الأقفال. لا نبني أي قرار نهائي قبل امتلاك الأقفال.
        snapshot = (
            await db.execute(
                select(
                    DispatchRoute.driver_id,
                    DispatchRoute.vehicle_id,
                    DispatchRoute.zone_id,
                    DispatchRoute.work_session_id,
                    DispatchRoute.status,
                ).filter(
                    DispatchRoute.company_id == company_id,
                    DispatchRoute.id == route_id,
                )
            )
        ).first()
        if snapshot is None:
            raise HTTPException(status_code=404, detail="خط السير غير موجود.")

        snap_driver_id = int(snapshot.driver_id) if snapshot.driver_id is not None else None
        snap_vehicle_id = int(snapshot.vehicle_id) if snapshot.vehicle_id is not None else None
        snap_zone_id = int(snapshot.zone_id)
        snap_session_id = (
            int(snapshot.work_session_id)
            if snapshot.work_session_id is not None
            else None
        )
        snap_status = str(snapshot.status)

        requested_driver_id = (
            int(payload.driverId) if payload.driverId is not None else snap_driver_id
        )
        requested_vehicle_id = (
            int(payload.vehicleId) if payload.vehicleId is not None else snap_vehicle_id
        )
        # Switching a pre-session vehicle also requires authority on the new car.
        await require_vehicle(access, 'dispatch.execute', requested_vehicle_id)

        bound_session = None
        active_session = None

        if snap_session_id is not None:
            # Route تاريخي/مربوط: نفس ترتيب undo/reconciliation يبدأ بـWorkSession.
            bound_session = (
                await db.execute(
                    select(WorkSession)
                    .filter_by(
                        company_id=company_id,
                        id=snap_session_id,
                        driver_id=snap_driver_id,
                    )
                    .order_by(WorkSession.id.asc())
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if bound_session is None:
                raise HTTPException(
                    status_code=409,
                    detail="خط السير مرتبط بجلسة عمل غير صالحة.",
                )

            driver = None
            if snap_driver_id is not None:
                driver = (
                    await db.execute(
                        select(Driver)
                        .filter_by(
                            company_id=company_id,
                            id=snap_driver_id,
                        )
                        .order_by(Driver.id.asc())
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if driver is None:
                    raise HTTPException(
                        status_code=404,
                        detail="المندوب المرتبط بالمسار غير موجود داخل الشركة.",
                    )

            vehicle = None
            if snap_vehicle_id is not None:
                vehicle = (
                    await db.execute(
                        select(Vehicle)
                        .filter_by(
                            company_id=company_id,
                            id=snap_vehicle_id,
                        )
                        .order_by(Vehicle.id.asc())
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if vehicle is None:
                    raise HTTPException(
                        status_code=404,
                        detail="السيارة المرتبطة بالمسار غير موجودة داخل الشركة.",
                    )

            locked_zones = await _dispatch_lock_zone_rows(
                db,
                company_id=company_id,
                zone_ids=[snap_zone_id],
            )
            zone = locked_zones[snap_zone_id]

            route = (
                await db.execute(
                    select(DispatchRoute)
                    .filter_by(company_id=company_id, id=route_id)
                    .order_by(DispatchRoute.id.asc())
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if route is None:
                raise HTTPException(status_code=404, detail="خط السير غير موجود.")

            locked_state = (
                route.driver_id,
                route.vehicle_id,
                route.zone_id,
                route.work_session_id,
                route.status,
            )
            snapshot_state = (
                snap_driver_id,
                snap_vehicle_id,
                snap_zone_id,
                snap_session_id,
                snap_status,
            )
            if locked_state != snapshot_state:
                raise HTTPException(
                    status_code=409,
                    detail="تغير خط السير بالتزامن. حدّث الشاشة وأعد المحاولة.",
                )

            target_status = payload.status if payload.status is not None else route.status
            target_driver_id = (
                int(payload.driverId) if payload.driverId is not None else route.driver_id
            )
            target_vehicle_id = (
                int(payload.vehicleId) if payload.vehicleId is not None else route.vehicle_id
            )
            driver_changed = target_driver_id != route.driver_id
            vehicle_changed = target_vehicle_id != route.vehicle_id

            # بعد ربط WorkSession تصبح هوية العهدة تاريخية وغير قابلة لإعادة الكتابة.
            if driver_changed or vehicle_changed:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "مرفوض: لا يمكن تبديل المندوب أو السيارة بعد بدء WorkSession. "
                        "أنه الجلسة والتسوية المخزنية ثم أنشئ خط سير جديد للحالة البديلة."
                    ),
                )

            requires_live_assets = (
                target_status == "active"
                or payload.inventory is not None
            )
            if requires_live_assets:
                if driver is None or not driver.is_active or driver.is_admin:
                    raise HTTPException(
                        status_code=409,
                        detail="لا يمكن تشغيل/تعديل حمولة المسار لأن المندوب غير فعال حالياً.",
                    )
                if vehicle is None or not vehicle.is_active:
                    raise HTTPException(
                        status_code=409,
                        detail="لا يمكن تشغيل/تعديل حمولة المسار لأن السيارة غير فعالة حالياً.",
                    )
                await _dispatch_vehicle_location_id(
                    db,
                    company_id=company_id,
                    vehicle_id=int(vehicle.id),
                    require_active=True,
                )

            active_session = (
                bound_session if bound_session.end_time is None else None
            )

        else:
            # Route غير مربوط: نفس ترتيب create/start session
            # driver(s) -> vehicle(s) -> zone -> route.
            driver_ids_to_lock = sorted({
                int(driver_id)
                for driver_id in (snap_driver_id, requested_driver_id)
                if driver_id is not None
            })
            driver_map = {}
            if driver_ids_to_lock:
                driver_rows = (
                    await db.execute(
                        select(Driver)
                        .filter(
                            Driver.company_id == company_id,
                            Driver.id.in_(driver_ids_to_lock),
                        )
                        .order_by(Driver.id.asc())
                        .with_for_update()
                    )
                ).scalars().all()
                driver_map = {int(driver.id): driver for driver in driver_rows}

            if requested_driver_id is not None:
                target_driver = driver_map.get(requested_driver_id)
                if (
                    target_driver is None
                    or not target_driver.is_active
                    or target_driver.is_admin
                ):
                    raise HTTPException(
                        status_code=404,
                        detail="المندوب المحدد غير موجود أو غير فعال أو لا يتبع الشركة.",
                    )

            vehicle_ids_to_lock = sorted({
                int(vehicle_id)
                for vehicle_id in (snap_vehicle_id, requested_vehicle_id)
                if vehicle_id is not None
            })
            vehicle_map = {}
            if vehicle_ids_to_lock:
                vehicle_rows = (
                    await db.execute(
                        select(Vehicle)
                        .filter(
                            Vehicle.company_id == company_id,
                            Vehicle.id.in_(vehicle_ids_to_lock),
                        )
                        .order_by(Vehicle.id.asc())
                        .with_for_update()
                    )
                ).scalars().all()
                vehicle_map = {int(vehicle.id): vehicle for vehicle in vehicle_rows}

            if requested_vehicle_id is not None:
                target_vehicle = vehicle_map.get(requested_vehicle_id)
                if target_vehicle is None or not target_vehicle.is_active:
                    raise HTTPException(
                        status_code=404,
                        detail="السيارة المحددة غير موجودة أو غير فعالة أو لا تتبع الشركة.",
                    )

            locked_zones = await _dispatch_lock_zone_rows(
                db,
                company_id=company_id,
                zone_ids=[snap_zone_id],
            )
            zone = locked_zones[snap_zone_id]

            route = (
                await db.execute(
                    select(DispatchRoute)
                    .filter_by(company_id=company_id, id=route_id)
                    .order_by(DispatchRoute.id.asc())
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if route is None:
                raise HTTPException(status_code=404, detail="خط السير غير موجود.")

            locked_state = (
                route.driver_id,
                route.vehicle_id,
                route.zone_id,
                route.work_session_id,
                route.status,
            )
            snapshot_state = (
                snap_driver_id,
                snap_vehicle_id,
                snap_zone_id,
                snap_session_id,
                snap_status,
            )
            if locked_state != snapshot_state:
                raise HTTPException(
                    status_code=409,
                    detail="تغير خط السير بالتزامن. حدّث الشاشة وأعد المحاولة.",
                )

            target_status = payload.status if payload.status is not None else route.status
            target_driver_id = (
                int(payload.driverId) if payload.driverId is not None else route.driver_id
            )
            target_vehicle_id = (
                int(payload.vehicleId) if payload.vehicleId is not None else route.vehicle_id
            )
            driver_changed = target_driver_id != route.driver_id
            vehicle_changed = target_vehicle_id != route.vehicle_id

        old_status = route.status
        old_driver_id = route.driver_id
        old_vehicle_id = route.vehicle_id

        if (
            bound_session is not None
            and bound_session.end_time is not None
            and target_status == "active"
            and old_status != "active"
            and bound_session.inventory_reconciled_at is not None
        ):
            raise HTTPException(
                status_code=409,
                detail="لا يمكن إعادة تفعيل خط السير بعد ختم التسوية المخزنية للجلسة.",
            )

        if (
            payload.inventory is not None
            and active_session is not None
            and target_status != "active"
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "لا يمكن إنشاء مصافحة حمولة في نفس الطلب الذي يوقف/يؤجل/يغلق المسار. "
                    "عدّل الحمولة أثناء الحالة active أو غيّر الحالة بدون حمولة."
                ),
            )

        if target_status in operational_statuses:
            if target_driver_id is None or target_vehicle_id is None:
                raise HTTPException(
                    status_code=409,
                    detail="خط السير التشغيلي يجب أن يكون مرتبطاً بمندوب وسيارة.",
                )
            if not zone.is_active:
                raise HTTPException(
                    status_code=409,
                    detail="لا يمكن تشغيل خط سير على منطقة مؤرشفة.",
                )

            conflict = (
                await db.execute(
                    select(DispatchRoute.id)
                    .filter(
                        DispatchRoute.company_id == company_id,
                        DispatchRoute.id != route.id,
                        DispatchRoute.status.in_(sorted(operational_statuses)),
                        or_(
                            DispatchRoute.driver_id == target_driver_id,
                            DispatchRoute.vehicle_id == target_vehicle_id,
                            DispatchRoute.zone_id == route.zone_id,
                        ),
                    )
                    .order_by(DispatchRoute.id.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if conflict is not None:
                raise HTTPException(
                    status_code=409,
                    detail="المنطقة أو المندوب أو السيارة مستخدمة حالياً في خط سير تشغيلي آخر.",
                )

        if bound_session is None and target_driver_id is not None and driver_changed:
            unsettled = (
                await db.execute(
                    select(WorkSession.id)
                    .filter(
                        WorkSession.company_id == company_id,
                        WorkSession.driver_id == target_driver_id,
                        WorkSession.is_settled.is_(False),
                    )
                    .order_by(WorkSession.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if unsettled is not None:
                raise HTTPException(
                    status_code=409,
                    detail="المندوب الجديد لديه جلسة غير مسواة ولا يمكن إسناد خط سير جديد له.",
                )

        if (
            bound_session is None
            and target_vehicle_id is not None
            and (
                vehicle_changed
                or target_status == "active"
                or payload.inventory is not None
            )
        ):
            await _dispatch_assert_vehicle_custody_reconciled(
                db,
                company_id=company_id,
                vehicle_id=int(target_vehicle_id),
            )

        # قبل WorkSession فقط يسمح بتغيير التعيين.
        if driver_changed:
            route.driver_id = target_driver_id

        if vehicle_changed:
            route.vehicle_id = target_vehicle_id
            if payload.inventory is None:
                # خطة الحمولة القديمة تخص السيارة السابقة؛ نعيدها إلى الرصيد الحقيقي للسيارة الجديدة.
                await _dispatch_sync_route_plan_to_current_vehicle(
                    db,
                    company_id=company_id,
                    route=route,
                    updated_by=current_admin.id,
                )

        inventory_mode = "NO_CHANGE"
        if payload.inventory is not None:
            if bound_session is not None and bound_session.end_time is not None:
                raise HTTPException(
                    status_code=409,
                    detail="لا يمكن تعديل حمولة خط سير بعد انتهاء WorkSession.",
                )
            inventory_mode = await _dispatch_absolute_targets(
                db,
                company_id=company_id,
                route=route,
                admin=current_admin,
                session=active_session,
                inventory=payload.inventory,
            )

        company_local_date = await get_company_local_date(db, company_id)

        # الجدولة رقمية فقط: الموعد التالي يحسب من يوم الإغلاق المحلي الفعلي.
        if target_status == "closed" and old_status != "closed":
            if zone.start_date is not None and zone.interval_days is not None:
                zone.start_date = company_local_date + timedelta(days=int(zone.interval_days))

        route.status = target_status

        if (
            bound_session is None
            and target_status == "active"
            and old_status != "active"
        ):
            # Route مؤجل من يوم سابق يجب أن يصبح قابلاً لبدء جلسة اليوم.
            route.dispatch_date = company_local_date

        commercial_context = None
        if target_status == "active":
            if bound_session is None:
                commercial_context = await lock_route_commercial_context(
                    db,
                    company_id=company_id,
                    dispatch_route_id=int(route.id),
                )
            else:
                commercial_context = await require_route_commercial_context(
                    db,
                    company_id=company_id,
                    dispatch_route_id=int(route.id),
                )
                if (
                    bound_session.commercial_context_id is None
                    or int(bound_session.commercial_context_id)
                    != int(commercial_context.id)
                ):
                    raise PricingError(
                        "COMMERCIAL_CONTEXT_LOCKED",
                        "الجلسة المربوطة لا تحمل نفس السياق التجاري المقفل للمسار؛ لا يجوز إنشاء سياق رجعي أو إعادة تسعيرها.",
                        context={
                            "dispatch_route_id": int(route.id),
                            "work_session_id": int(bound_session.id),
                        },
                    )

        zone_shop_ids = select(Shop.id).filter(
            Shop.company_id == company_id,
            Shop.zone_id == route.zone_id,
        ).scalar_subquery()

        # تغيير المندوب قبل بدء الجلسة ينقل كل Pending لنفس المنطقة، بما فيها الطوارئ.
        if driver_changed and old_driver_id is not None:
            await db.execute(
                update(Visit)
                .where(
                    Visit.company_id == company_id,
                    Visit.driver_id == old_driver_id,
                    Visit.status == "Pending",
                    Visit.shop_id.in_(zone_shop_ids),
                    Visit.work_session_id.is_(None),
                )
                .values(driver_id=route.driver_id)
            )
            await db.execute(
                update(ShortageRequest)
                .where(
                    ShortageRequest.company_id == company_id,
                    ShortageRequest.shop_id.in_(zone_shop_ids),
                    ShortageRequest.status == "pending",
                    or_(
                        ShortageRequest.driver_id == old_driver_id,
                        ShortageRequest.driver_id.is_(None),
                    ),
                )
                .values(driver_id=route.driver_id)
            )

        if target_status in {"closed", "waiting", "postponed"} and route.driver_id is not None:
            await db.execute(
                update(Visit)
                .where(
                    Visit.company_id == company_id,
                    Visit.driver_id == route.driver_id,
                    Visit.status == "Pending",
                    Visit.shop_id.in_(zone_shop_ids),
                )
                .values(
                    driver_id=None,
                    work_session_id=None,
                )
            )
            await db.execute(
                update(ShortageRequest)
                .where(
                    ShortageRequest.company_id == company_id,
                    ShortageRequest.shop_id.in_(zone_shop_ids),
                    ShortageRequest.status == "pending",
                    ShortageRequest.driver_id == route.driver_id,
                )
                .values(driver_id=None)
            )

        if target_status == "active" and route.driver_id is not None:
            shops_in_zone = (
                await db.execute(
                    select(Shop)
                    .filter_by(
                        company_id=company_id,
                        zone_id=route.zone_id,
                        is_active=True,
                        is_archived=False,
                    )
                    .order_by(Shop.id.asc())
                )
            ).scalars().all()
            shop_ids = [int(shop.id) for shop in shops_in_zone]

            if shop_ids:
                work_session_id = int(bound_session.id) if bound_session is not None else None
                await _dispatch_advisory_locks(
                    db,
                    company_id=company_id,
                    keys=[
                        f"pending-visit:{route.driver_id}:{shop_id}"
                        for shop_id in shop_ids
                    ],
                )

                # عند التفعيل يتبنى Route كل Pending غير المعيّن في منطقته، بما فيه الطوارئ.
                await db.execute(
                    update(Visit)
                    .where(
                        Visit.company_id == company_id,
                        Visit.shop_id.in_(shop_ids),
                        Visit.status == "Pending",
                        Visit.driver_id.is_(None),
                    )
                    .values(
                        driver_id=route.driver_id,
                        work_session_id=work_session_id,
                    )
                )
                await db.execute(
                    update(ShortageRequest)
                    .where(
                        ShortageRequest.company_id == company_id,
                        ShortageRequest.shop_id.in_(shop_ids),
                        ShortageRequest.status == "pending",
                        ShortageRequest.driver_id.is_(None),
                    )
                    .values(driver_id=route.driver_id)
                )

                existing_visits = (
                    await db.execute(
                        select(Visit).filter(
                            Visit.company_id == company_id,
                            Visit.driver_id == route.driver_id,
                            Visit.shop_id.in_(shop_ids),
                            Visit.status == "Pending",
                        ).order_by(Visit.shop_id.asc(), Visit.id.asc())
                    )
                ).scalars().all()
                existing_pending = {}
                seen_today = set()
                for visit in existing_visits:
                    if visit.operational_date == company_local_date:
                        seen_today.add(int(visit.shop_id))
                    if visit.status == "Pending":
                        shop_id = int(visit.shop_id)
                        if shop_id in existing_pending:
                            raise HTTPException(
                                status_code=409,
                                detail="تم اكتشاف أكثر من زيارة Pending لنفس المندوب والمحل؛ أصلح البيانات قبل تفعيل المسار.",
                            )
                        visit.work_session_id = work_session_id
                        existing_pending[shop_id] = visit

                shortage_shop_ids = set((
                    await db.execute(
                        select(ShortageRequest.shop_id).filter(
                            ShortageRequest.company_id == company_id,
                            ShortageRequest.shop_id.in_(shop_ids),
                            or_(
                                ShortageRequest.driver_id == route.driver_id,
                                ShortageRequest.driver_id.is_(None),
                            ),
                            ShortageRequest.status == "pending",
                        )
                    )
                ).scalars().all())

                for shop in shops_in_zone:
                    shop_id = int(shop.id)
                    existing = existing_pending.get(shop_id)
                    is_emergency = shop_id in shortage_shop_ids
                    if existing is None and shop_id not in seen_today:
                        db.add(Visit(
                            company_id=company_id,
                            driver_id=route.driver_id,
                            shop_id=shop_id,
                            operational_date=company_local_date,
                            status="Pending",
                            sequence=shop.sequence,
                            is_emergency=is_emergency,
                            work_session_id=work_session_id,
                        ))
                    elif existing is not None and is_emergency:
                        existing.is_emergency = True

        changed = (
            old_status != route.status
            or old_driver_id != route.driver_id
            or old_vehicle_id != route.vehicle_id
            or inventory_mode != "NO_CHANGE"
        )
        if changed:
            db.add(
                SystemAuditLog(
                    company_id=company_id,
                    admin_id=current_admin.id,
                    target_id=f"Route_{route.id}",
                    action_type="DISPATCH_ROUTE_UPDATE",
                    old_value=(
                        f"status={old_status}|driver={old_driver_id}|vehicle={old_vehicle_id}"
                    ),
                    new_value=(
                        f"status={route.status}|driver={route.driver_id}|vehicle={route.vehicle_id}|"
                        f"inventory={inventory_mode}"
                    ),
                )
            )

        await db.commit()
        asyncio.create_task(
            dispatch_manager.broadcast(
                {"event": "ROUTE_STATUS_UPDATED", "message": "تم تحديث حالة خط السير"},
                company_id=company_id,
            )
        )
        response = {"message": "تم تحديث خط السير بنجاح"}
        if commercial_context is not None:
            response["commercial_context"] = commercial_context_payload(
                commercial_context
            )
        return response

    except HTTPException:
        await db.rollback()
        raise
    except PricingError as exc:
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
        logger.error(f"Dispatch route status integrity conflict: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=409, detail="تعارض متزامن أثناء تحديث خط السير.") from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في تحديث خط السير: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي أثناء تحديث خط السير.") from exc


# =========================================
# 16. تراجع عن إنهاء العمل - مسموح فقط قبل ختم العهدة المخزنية
# =========================================
@router.put("/dispatch/session/{session_id}/undo_end_work", status_code=200)
async def undo_end_work(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id

    try:
        session = (
            await db.execute(
                select(WorkSession)
                .filter_by(company_id=company_id, id=session_id)
                .order_by(WorkSession.id.asc())
                .with_for_update()
            )
        ).scalar_one_or_none()
        if session is None:
            raise HTTPException(status_code=404, detail="الجلسة غير موجودة.")
        if session.is_settled:
            raise HTTPException(status_code=409, detail="لا يمكن إعادة فتح جلسة تمت تسويتها مالياً.")
        if session.inventory_reconciled_at is not None:
            raise HTTPException(
                status_code=409,
                detail="لا يمكن إعادة فتح يوم العمل بعد ختم التسوية المخزنية وEnding Snapshot.",
            )
        if session.end_time is None:
            return {"message": "الجلسة مفتوحة أصلاً ولا تحتاج إلى تراجع."}

        driver = (
            await db.execute(
                select(Driver)
                .filter_by(
                    company_id=company_id,
                    id=session.driver_id,
                    is_active=True,
                    is_admin=False,
                )
                .order_by(Driver.id.asc())
                .with_for_update()
            )
        ).scalar_one_or_none()
        if driver is None:
            raise HTTPException(
                status_code=409,
                detail="لا يمكن إعادة فتح الجلسة لأن حساب المندوب غير فعال حالياً.",
            )

        route = (
            await db.execute(
                select(DispatchRoute)
                .filter_by(
                    company_id=company_id,
                    work_session_id=session.id,
                    driver_id=session.driver_id,
                )
                .order_by(DispatchRoute.id.asc())
                .with_for_update()
            )
        ).scalar_one_or_none()
        if route is None or route.vehicle_id is None:
            raise HTTPException(
                status_code=409,
                detail="لا يمكن إعادة فتح الجلسة لأن خط السير التاريخي/السيارة غير موجودين.",
            )
        if route.status != "active":
            raise HTTPException(
                status_code=409,
                detail="لا يمكن إعادة فتح الجلسة إلا إذا كان خط السير نفسه ما زال active.",
            )

        vehicle = (
            await db.execute(
                select(Vehicle)
                .filter_by(
                    company_id=company_id,
                    id=route.vehicle_id,
                    is_active=True,
                )
                .order_by(Vehicle.id.asc())
                .with_for_update()
            )
        ).scalar_one_or_none()
        if vehicle is None:
            raise HTTPException(
                status_code=409,
                detail="لا يمكن إعادة فتح الجلسة لأن السيارة غير فعالة حالياً.",
            )
        await _dispatch_vehicle_location_id(
            db,
            company_id=company_id,
            vehicle_id=int(vehicle.id),
            require_active=True,
        )

        other_active = (
            await db.execute(
                select(WorkSession.id)
                .filter(
                    WorkSession.company_id == company_id,
                    WorkSession.driver_id == session.driver_id,
                    WorkSession.end_time.is_(None),
                    WorkSession.id != session.id,
                )
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if other_active is not None:
            raise HTTPException(
                status_code=409,
                detail="المندوب لديه جلسة عمل أخرى نشطة؛ لا يمكن إعادة فتح الجلسة القديمة.",
            )

        old_end_time = session.end_time
        session.end_time = None
        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"Session_{session.id}_Driver_{session.driver_id}",
            action_type="UNDO_END_WORK",
            old_value=f"end_time={old_end_time}",
            new_value="end_time=None",
        ))

        await db.commit()
        return {"message": "تم التراجع عن إنهاء العمل وإعادة فتح الجلسة بنجاح."}

    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في التراجع عن إنهاء العمل: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي أثناء التراجع عن إنهاء العمل.") from exc

# =========================================
# 17. إدارة المناطق (إضافة منطقة جديدة)
# =========================================
@router.post("/dispatch/zones", status_code=201)
async def add_zone(
    payload: AddZoneRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    company_id = current_admin.company_id
    name = payload.name.strip()
    try:
        await _dispatch_advisory_locks(db, company_id=company_id, keys=[f"zone-name:{name}"])
        existing_zone = (
            await db.execute(
                select(Zone).filter_by(name=name, company_id=company_id).order_by(Zone.id.asc())
            )
        ).scalars().first()
        if existing_zone is not None:
            if not existing_zone.is_active:
                raise HTTPException(status_code=409, detail="هذه المنطقة موجودة في الأرشيف؛ استعدها بدلاً من إنشائها.")
            raise HTTPException(status_code=409, detail="المنطقة موجودة ونشطة مسبقاً")

        await db.execute(select(func.pg_advisory_xact_lock(func.hashtext("dispatch-geo-bootstrap"))))
        gov = (await db.execute(select(Governorate).order_by(Governorate.id.asc()).limit(1))).scalars().first()
        if gov is None:
            country = (await db.execute(select(Country).order_by(Country.id.asc()).limit(1))).scalars().first()
            if country is None:
                country = Country(name="الأردن")
                db.add(country)
                await db.flush()
            gov = Governorate(name="العاصمة", country_id=country.id)
            db.add(gov)
            await db.flush()

        new_zone = Zone(
            company_id=company_id,
            name=name,
            governorate_id=gov.id,
            interval_days=(int(payload.intervalDays) if payload.intervalDays is not None else None),
            start_date=payload.startDate,
        )
        db.add(new_zone)
        await db.flush()
        zone_id = int(new_zone.id)
        await db.commit()
        return {"message": "تم إضافة المنطقة بنجاح", "zone_id": str(zone_id)}
    except HTTPException:
        await db.rollback(); raise
    except IntegrityError as exc:
        await db.rollback()
        logger.error(f"Zone create integrity conflict: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=409, detail="تعارض متزامن أثناء إنشاء المنطقة؛ يوجد سجل مطابق بالفعل.") from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء إضافة المنطقة.") from exc



# =========================================
# 18. أرشفة المنطقة (مع حماية  ـ Rug-Pull ونسف الـ N+1)
# =========================================
@router.delete("/dispatch/zones/{zone_id}", status_code=200)
async def archive_zone(
    zone_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    company_id = current_admin.company_id
    try:
        zone = (await db.execute(
            select(Zone).filter_by(id=zone_id, company_id=company_id).order_by(Zone.id.asc()).with_for_update()
        )).scalar_one_or_none()
        if zone is None:
            raise HTTPException(status_code=404, detail="المنطقة غير موجودة")
        if not zone.is_active:
            return {"message": "المنطقة مؤرشفة بالفعل"}

        active_route = (await db.execute(
            select(DispatchRoute.id).filter(
                DispatchRoute.company_id == company_id,
                DispatchRoute.zone_id == zone_id,
                DispatchRoute.status.in_(["active", "waiting", "postponed"]),
            ).order_by(DispatchRoute.id.asc()).limit(1)
        )).scalar_one_or_none()
        if active_route is not None:
            raise HTTPException(status_code=409, detail=f"مرفوض: يوجد خط سير تشغيلي في منطقة ({zone.name}). أغلقه أولاً.")

        # لا نضع provenance فوق محل أرشفه المسؤول يدوياً سابقاً.
        await db.execute(
            update(Shop).where(
                Shop.company_id == company_id,
                Shop.zone_id == zone_id,
                Shop.is_archived.is_(False),
            ).values(
                is_archived=True,
                archived_due_to_zone_id=zone_id,
            )
        )
        shop_ids = select(Shop.id).filter(
            Shop.company_id == company_id,
            Shop.zone_id == zone_id,
        ).scalar_subquery()
        await db.execute(
            update(Visit).where(
                Visit.company_id == company_id,
                Visit.shop_id.in_(shop_ids),
                Visit.status == "Pending",
            ).values(status="Cancelled")
        )
        zone.is_active = False
        zone_name = zone.name
        await db.commit()
        return {"message": f"تم أرشفة المنطقة ({zone_name}) ومحلاتها النشطة بنجاح"}
    except HTTPException:
        await db.rollback(); raise
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء أرشفة المنطقة.") from exc



# =========================================
# 19. تعديل بيانات المنطقة (جدولة، اسم، أيام)
# =========================================
@router.put("/dispatch/zones/{zone_id}", status_code=200)
async def update_zone(
    zone_id: int,
    payload: UpdateZoneRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    company_id = current_admin.company_id
    new_name = payload.name.strip() if payload.name else None
    try:
        if new_name:
            await _dispatch_advisory_locks(db, company_id=company_id, keys=[f"zone-name:{new_name}"])
        zone = (await db.execute(
            select(Zone).filter_by(id=zone_id, company_id=company_id).order_by(Zone.id.asc()).with_for_update()
        )).scalar_one_or_none()
        if zone is None:
            raise HTTPException(status_code=404, detail="المنطقة غير موجودة")

        if new_name and new_name != zone.name:
            duplicate = (await db.execute(
                select(Zone.id).filter(
                    Zone.company_id == company_id,
                    Zone.name == new_name,
                    Zone.id != zone_id,
                ).order_by(Zone.id.asc()).limit(1)
            )).scalar_one_or_none()
            if duplicate is not None:
                raise HTTPException(status_code=409, detail="يوجد منطقة أخرى بنفس الاسم")
            zone.name = new_name

        if payload.clearSchedule:
            zone.interval_days = None
            zone.start_date = None
        elif payload.intervalDays is not None or payload.startDate is not None:
            interval = int(payload.intervalDays) if payload.intervalDays is not None else zone.interval_days
            next_date = payload.startDate if payload.startDate is not None else zone.start_date
            if interval is None or next_date is None:
                raise HTTPException(
                    status_code=400,
                    detail="لتفعيل الجدولة يجب تحديد intervalDays و startDate معاً.",
                )
            zone.interval_days = int(interval)
            zone.start_date = next_date

        await db.commit()
        return {"message": "تم التعديل بنجاح"}
    except HTTPException:
        await db.rollback(); raise
    except IntegrityError as exc:
        await db.rollback()
        logger.error(f"Zone update integrity conflict: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=409, detail="تعارض متزامن أثناء تعديل المنطقة.") from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي أثناء تعديل المنطقة.") from exc



# =========================================
# 20. جلب المناطق المؤرشفة
# =========================================
@router.get("/dispatch/zones/archived", response_model=List[ArchivedZoneResponse], status_code=200)
async def get_archived_zones(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    # جلب المناطق الميتة فقط بـ O(1)
    stmt = select(Zone).filter_by(
        company_id=current_admin.company_id,
        is_active=False
    )
    zones = (await db.execute(stmt)).scalars().all()
    
    return [{"id": str(z.id), "name": z.name} for z in zones]


# =========================================
# 21. استعادة المنطقة المؤرشفة
# =========================================
@router.put("/dispatch/zones/{zone_id}/restore", status_code=200)
async def restore_zone(
    zone_id: int,
    payload: RestoreZoneRequest = RestoreZoneRequest(),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    company_id = current_admin.company_id
    try:
        zone = (await db.execute(
            select(Zone).filter_by(id=zone_id, company_id=company_id).order_by(Zone.id.asc()).with_for_update()
        )).scalar_one_or_none()
        if zone is None:
            raise HTTPException(status_code=404, detail="المنطقة غير موجودة")
        zone.is_active = True

        restored_count = 0
        if payload.mode != "zone_only":
            stmt = select(Shop).filter(
                Shop.company_id == company_id,
                Shop.zone_id == zone_id,
                Shop.is_archived.is_(True),
                Shop.archived_due_to_zone_id == zone_id,
            )
            if payload.mode == "selected_shops":
                selected_ids = sorted({int(shop_id) for shop_id in payload.shop_ids})
                stmt = stmt.filter(Shop.id.in_(selected_ids))
            shops = (await db.execute(
                stmt.order_by(Shop.id.asc()).with_for_update()
            )).scalars().all()
            if payload.mode == "selected_shops" and {int(shop.id) for shop in shops} != set(selected_ids):
                raise HTTPException(
                    status_code=409,
                    detail="أحد المحلات المحددة لم يُؤرشف تلقائياً بسبب هذه المنطقة؛ استعده من شاشة المحل.",
                )
            for shop in shops:
                shop.is_archived = False
                shop.archived_due_to_zone_id = None
            restored_count = len(shops)

        await db.commit()
        return {
            "message": "تم استعادة المنطقة بنجاح",
            "restored_shops": restored_count,
            "mode": payload.mode,
        }
    except HTTPException:
        await db.rollback(); raise
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء استعادة المنطقة.") from exc



# =========================================
# 22. تعديل بيانات محل موجود (الرصيد الحي، السقف، المنطقة)
# =========================================
@router.put("/dispatch/shops/{shop_id}", status_code=200)
async def edit_shop_details(
    shop_id: str,
    payload: EditShopDetailsRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    company_id = current_admin.company_id
    clean_id_str = str(shop_id).replace("s", "")
    if not clean_id_str.isdigit():
        raise HTTPException(status_code=400, detail="معرف المحل غير صالح.")
    clean_id = int(clean_id_str)

    try:
        # Pre-read لاكتشاف ترتيب أقفال المناطق/الهاتف؛ بعد الأقفال نعيد جلب المحل FOR UPDATE.
        pre = (
            await db.execute(
                select(
                    Shop.id,
                    Shop.zone_id,
                    Shop.phone_number,
                ).filter(
                    Shop.company_id == company_id,
                    Shop.id == clean_id,
                )
            )
        ).first()
        if pre is None:
            raise HTTPException(status_code=404, detail="المحل غير موجود")

        pre_zone_id = int(pre.zone_id) if pre.zone_id is not None else None
        pre_phone = (pre.phone_number or "").strip() or None
        target_zone_id = int(payload.zoneId) if payload.zoneId is not None else pre_zone_id
        new_phone = payload.phone.strip() if payload.phone else None

        zone_ids_to_lock = {
            zone_id for zone_id in (pre_zone_id, target_zone_id) if zone_id is not None
        }
        zones = await _dispatch_lock_zone_rows(
            db,
            company_id=company_id,
            zone_ids=zone_ids_to_lock,
        )
        if payload.zoneId is not None:
            target_zone = zones.get(target_zone_id)
            if target_zone is None or not target_zone.is_active:
                raise HTTPException(
                    status_code=400,
                    detail="المنطقة المحددة غير موجودة أو مؤرشفة أو لا تتبع شركتك.",
                )

        phone_keys = [
            f"shop-phone:{phone}"
            for phone in sorted({p for p in (pre_phone, new_phone) if p})
        ]
        await _dispatch_advisory_locks(
            db,
            company_id=company_id,
            keys=phone_keys,
        )
        await _dispatch_advisory_locks(
            db,
            company_id=company_id,
            keys=[f"dispatch-shop:{clean_id}"],
        )

        shop = (
            await db.execute(
                select(Shop)
                .filter_by(id=clean_id, company_id=company_id)
                .order_by(Shop.id.asc())
                .with_for_update()
            )
        ).scalar_one_or_none()
        if shop is None:
            raise HTTPException(status_code=404, detail="المحل غير موجود")

        locked_phone = (shop.phone_number or "").strip() or None
        if shop.zone_id != pre_zone_id or locked_phone != pre_phone:
            raise HTTPException(
                status_code=409,
                detail="تغيرت بيانات المحل بالتزامن. حدّث الشاشة وأعد المحاولة.",
            )

        if new_phone and new_phone != pre_phone:
            duplicate_phone = (
                await db.execute(
                    select(Shop.id)
                    .filter(
                        Shop.company_id == company_id,
                        Shop.phone_number == new_phone,
                        Shop.id != clean_id,
                    )
                    .order_by(Shop.id.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if duplicate_phone is not None:
                raise HTTPException(status_code=409, detail="رقم الهاتف مستخدم لمحل آخر")

        if payload.zoneId is not None and target_zone_id != pre_zone_id:
            blocked = await _dispatch_blocking_shop_zone_move_ids(
                db, company_id=company_id, shop_ids=[clean_id]
            )
            if clean_id in blocked:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "مرفوض: لا يمكن نقل المحل إلى منطقة أخرى بينما لديه زيارة Pending "
                        "ضمن خط سير Active."
                    ),
                )

        if payload.name is not None:
            shop.name = payload.name
        if payload.owner is not None:
            shop.contact_person = payload.owner

        # نحافظ على العقد الحالي: إرسال هاتف فارغ لا يمسح الرقم.
        if new_phone:
            shop.phone_number = new_phone

        if payload.mapLink is not None:
            shop.location_link = payload.mapLink

        if payload.zoneId is not None:
            shop.zone_id = target_zone_id
            shop.archived_due_to_zone_id = None

        if payload.max_debt_limit is not None:
            shop.max_debt_limit = payload.max_debt_limit

        if payload.initial_debt is not None:
            new_balance = payload.initial_debt
            old_balance = shop.current_balance or Decimal("0.000")
            if new_balance != old_balance:
                shop.current_balance = new_balance
                db.add(SystemAuditLog(
                    company_id=company_id,
                    admin_id=current_admin.id,
                    target_id=f"Shop_{shop.id}",
                    action_type="SHOP_BALANCE_MANUAL_EDIT",
                    old_value=str(old_balance),
                    new_value=f"الرصيد الجديد: {new_balance} (تعديل يدوي من لوحة التحكم)",
                ))

        await db.commit()
        return {"message": "تم التعديل بنجاح"}

    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        logger.error(f"Shop edit integrity conflict: {str(exc)}", exc_info=True)
        raise HTTPException(
            status_code=409,
            detail="تعارض متزامن أو بيانات فريدة مستخدمة أثناء تعديل المحل.",
        ) from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء تعديل المحل.") from exc


# =========================================
# 23. جلب الطلبات العاجلة (شاشة النواقص) - GET
# =========================================
@router.get("/dispatch/shortages", response_model=List[ShortageResponseItem], status_code=200)
async def get_shortages(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    # +++ التدمير الحقيقي لـ N+1 (O(1) Fetch) مع الدرع المفقود +++
    stmt = select(ShortageRequest).options(
        joinedload(ShortageRequest.zone),
        joinedload(ShortageRequest.shop),
        joinedload(ShortageRequest.driver),
        joinedload(ShortageRequest.product_variant)
    ).filter_by(
        company_id=current_admin.company_id,
        status='pending'
    ).order_by(ShortageRequest.created_at.asc())
    
    shortages = (await db.execute(stmt)).scalars().all()
    
    result = [{
        "id": str(s.id),
        "productId": str(s.product_variant_id),
        "zoneId": str(s.zone_id) if s.zone_id else "",
        "zoneName": s.zone.name if s.zone else "",
        "shopId": str(s.shop_id) if s.shop_id else "",
        "shopName": s.shop.name if s.shop else "",
        "driverId": str(s.driver_id) if s.driver_id else "",
        "driverName": s.driver.full_name if s.driver else "",
        "productName": s.product_variant.variant_name if s.product_variant else "غير معروف",
        "quantity": s.quantity,
        "status": s.status,
        "waitTime": s.wait_time,
        # +++ نسف لغم الـ Timezone الأخير في السيستم: توحيد توقيت الطوارئ مع جرينتش لمنع كراش الموبايل +++
        "createdAt": s.created_at.replace(tzinfo=timezone.utc).isoformat() if s.created_at else None
    } for s in shortages]
    
    return result


# =========================================
# 24. إضافة طلبات عاجلة (تبني ودمج الزيارات) - POST
# =========================================
@router.post("/dispatch/shortages", status_code=201)
async def add_shortages(
    payload: List[CreateShortageItem],
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    if not payload:
        raise HTTPException(status_code=400, detail="لا توجد بيانات لإضافتها.")
    company_id = current_admin.company_id
    try:
        shop_ids = sorted({int(item.shopId) for item in payload})
        product_ids = sorted({int(item.product_variant_id) for item in payload})
        await acquire_product_lifecycle_guards(
            db, company_id, product_ids, exclusive=False,
        )
        zone_ids = sorted({int(item.zoneId) for item in payload})
        driver_ids = sorted({int(item.driverId) for item in payload if item.driverId is not None})

        if driver_ids:
            drivers = (await db.execute(
                select(Driver).filter(
                    Driver.company_id == company_id,
                    Driver.id.in_(driver_ids),
                ).order_by(Driver.id.asc()).with_for_update()
            )).scalars().all()
            valid = {int(d.id) for d in drivers if d.is_active and not d.is_admin}
            if valid != set(driver_ids):
                raise HTTPException(status_code=400, detail="أحد المندوبين غير موجود/غير فعال أو لا يتبع شركتك.")

        locked_zones = await _dispatch_lock_zone_rows(db, company_id=company_id, zone_ids=zone_ids)
        if any(not zone.is_active for zone in locked_zones.values()):
            raise HTTPException(status_code=400, detail="إحدى المناطق مؤرشفة ولا يمكن إنشاء طلب عاجل فيها.")
        await _dispatch_advisory_locks(
            db, company_id=company_id, keys=[f"dispatch-shop:{shop_id}" for shop_id in shop_ids]
        )
        bulk_shops = await _dispatch_lock_shop_rows(db, company_id=company_id, shop_ids=shop_ids)
        if any(shop.is_archived or not shop.is_active for shop in bulk_shops.values()):
            raise HTTPException(status_code=404, detail="أحد المحلات غير فعال/مؤرشف أو لا يتبع شركتك.")

        variants = (await db.execute(
            select(ProductVariant).filter(
                ProductVariant.company_id == company_id,
                ProductVariant.id.in_(product_ids),
            ).order_by(ProductVariant.id.asc())
        )).scalars().all()
        variant_map = {int(v.id): v for v in variants}
        if set(product_ids) != set(variant_map):
            raise HTTPException(status_code=404, detail="أحد المنتجات غير موجود أو لا يتبع شركتك.")
        for variant in variant_map.values():
            replenishment_capability = evaluate_product_capability(
                variant.lifecycle_status,
                variant.operational_hold,
                REPLENISHMENT_NEW,
            )
            if not replenishment_capability.allowed:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": replenishment_capability.code,
                        "message": f"لا يمكن إنشاء طلب نقص جديد للصنف ({variant.variant_name}) في حالته الحالية.",
                    },
                )

        for item in payload:
            shop = bulk_shops[int(item.shopId)]
            if shop.zone_id is None or int(shop.zone_id) != int(item.zoneId):
                raise HTTPException(status_code=409, detail=f"منطقة الطلب العاجل لا تطابق منطقة المحل ({shop.name}).")

        existing_rows = (await db.execute(
            select(ShortageRequest).filter(
                ShortageRequest.company_id == company_id,
                ShortageRequest.shop_id.in_(shop_ids),
                ShortageRequest.product_variant_id.in_(product_ids),
                ShortageRequest.status == "pending",
            ).order_by(ShortageRequest.id.asc()).with_for_update()
        )).scalars().all()
        existing_pairs = {(int(r.shop_id), int(r.product_variant_id)) for r in existing_rows}

        company_local_date = await get_company_local_date(db, company_id)

        unassigned_zone_ids = sorted({
            int(item.zoneId)
            for item in payload
            if item.driverId is None
        })
        active_route_driver_by_zone = {}
        if unassigned_zone_ids:
            active_routes = (
                await db.execute(
                    select(DispatchRoute)
                    .filter(
                        DispatchRoute.company_id == company_id,
                        DispatchRoute.zone_id.in_(unassigned_zone_ids),
                        DispatchRoute.status == "active",
                        DispatchRoute.driver_id.is_not(None),
                    )
                    .order_by(DispatchRoute.zone_id.asc(), DispatchRoute.id.asc())
                    .with_for_update()
                )
            ).scalars().all()
            for active_route in active_routes:
                zone_id = int(active_route.zone_id)
                route_driver_id = int(active_route.driver_id)
                prior = active_route_driver_by_zone.get(zone_id)
                if prior is not None and prior != route_driver_id:
                    raise HTTPException(
                        status_code=409,
                        detail="تم اكتشاف أكثر من Route نشط لنفس المنطقة؛ أصلح التوزيع قبل إضافة النقص.",
                    )
                active_route_driver_by_zone[zone_id] = route_driver_id

            auto_driver_ids = sorted(set(active_route_driver_by_zone.values()))
            if auto_driver_ids:
                auto_drivers = (
                    await db.execute(
                        select(Driver)
                        .filter(
                            Driver.company_id == company_id,
                            Driver.id.in_(auto_driver_ids),
                            Driver.is_active.is_(True),
                            Driver.is_admin.is_(False),
                        )
                        .order_by(Driver.id.asc())
                        .with_for_update(read=True)
                    )
                ).scalars().all()
                valid_auto_ids = {int(driver.id) for driver in auto_drivers}
                active_route_driver_by_zone = {
                    zone_id: driver_id
                    for zone_id, driver_id in active_route_driver_by_zone.items()
                    if driver_id in valid_auto_ids
                }

        def resolve_shortage_driver_id(item: CreateShortageItem):
            if item.driverId is not None:
                return int(item.driverId)
            return active_route_driver_by_zone.get(int(item.zoneId))

        owner_pairs = sorted({
            (driver_id, int(item.shopId))
            for item in payload
            for driver_id in [resolve_shortage_driver_id(item)]
            if driver_id is not None
        })
        if owner_pairs:
            await _dispatch_advisory_locks(
                db,
                company_id=company_id,
                keys=[
                    f"pending-visit:{driver_id}:{shop_id}"
                    for driver_id, shop_id in owner_pairs
                ],
            )

        existing_owner_visits = {}
        if owner_pairs:
            owner_driver_ids = sorted({driver_id for driver_id, _ in owner_pairs})
            owner_shop_ids = sorted({shop_id for _, shop_id in owner_pairs})
            rows = (await db.execute(
                select(Visit).filter(
                    Visit.company_id == company_id,
                    Visit.driver_id.in_(owner_driver_ids),
                    Visit.shop_id.in_(owner_shop_ids),
                    Visit.status == "Pending",
                ).order_by(Visit.driver_id.asc(), Visit.shop_id.asc(), Visit.id.asc()).with_for_update()
            )).scalars().all()
            for visit in rows:
                key = (int(visit.driver_id), int(visit.shop_id))
                if key in existing_owner_visits:
                    raise HTTPException(
                        status_code=409,
                        detail="تم اكتشاف أكثر من زيارة Pending لنفس المندوب والمحل؛ أصلح البيانات قبل إضافة طوارئ جديدة.",
                    )
                existing_owner_visits[key] = visit

        payload_tracker = set()
        for item in payload:
            shop_id = int(item.shopId)
            product_id = int(item.product_variant_id)
            pair = (shop_id, product_id)
            if pair in payload_tracker:
                continue
            payload_tracker.add(pair)
            shop = bulk_shops[shop_id]
            if pair in existing_pairs:
                raise HTTPException(
                    status_code=409,
                    detail=f"يوجد طلب عاجل معلق مسبقاً للمحل ({shop.name}) وللصنف ({variant_map[product_id].variant_name}).",
                )

            driver_id = resolve_shortage_driver_id(item)
            db.add(ShortageRequest(
                company_id=company_id,
                zone_id=int(item.zoneId),
                shop_id=shop_id,
                driver_id=driver_id,
                product_variant_id=product_id,
                quantity=int(item.quantity),
            ))
            existing_pairs.add(pair)
            if driver_id is None:
                continue

            owner_key = (driver_id, shop_id)
            visit = existing_owner_visits.get(owner_key)
            if visit is None:
                visit = Visit(
                    company_id=company_id,
                    driver_id=driver_id,
                    shop_id=shop_id,
                    operational_date=company_local_date,
                    status="Pending",
                    sequence=shop.sequence if shop.sequence is not None else 999,
                    is_emergency=True,
                )
                db.add(visit)
                existing_owner_visits[owner_key] = visit
            else:
                visit.is_emergency = True

        await db.commit()
        asyncio.create_task(dispatch_manager.broadcast(
            {"event": "SHORTAGE_ADDED", "message": "تم إضافة نواقص جديدة"}, company_id=company_id
        ))
        return {"message": "تم تسجيل الطلبات بنجاح"}
    except HTTPException:
        await db.rollback(); raise
    except IntegrityError as exc:
        await db.rollback()
        logger.error(f"Shortage integrity conflict: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=409, detail="تعارض متزامن أثناء تسجيل الطلبات العاجلة.") from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء حفظ الطلبات.") from exc



# =========================================
# 25. حذف الطلب العاجل (وعملية تنظيف الأشباح) - DELETE
# =========================================
@router.delete("/dispatch/shortages/{shortage_id}", status_code=200)
async def delete_shortage(
    shortage_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    company_id = current_admin.company_id
    try:
        pre = (await db.execute(
            select(ShortageRequest.shop_id, ShortageRequest.zone_id, ShortageRequest.driver_id).filter(
                ShortageRequest.id == shortage_id,
                ShortageRequest.company_id == company_id,
            )
        )).first()
        if pre is None:
            return {"message": "الطلب غير موجود أصلاً."}
        shop_id, zone_id = int(pre.shop_id), int(pre.zone_id)
        driver_id = int(pre.driver_id) if pre.driver_id is not None else None

        await _dispatch_lock_zone_rows(db, company_id=company_id, zone_ids=[zone_id])
        await _dispatch_advisory_locks(db, company_id=company_id, keys=[f"dispatch-shop:{shop_id}"])
        shortage = (await db.execute(
            select(ShortageRequest).filter(
                ShortageRequest.id == shortage_id,
                ShortageRequest.company_id == company_id,
                ShortageRequest.shop_id == shop_id,
            ).order_by(ShortageRequest.id.asc()).with_for_update()
        )).scalar_one_or_none()
        if shortage is None:
            return {"message": "الطلب غير موجود أصلاً."}
        shop = (await db.execute(
            select(Shop).filter_by(id=shop_id, company_id=company_id).order_by(Shop.id.asc()).with_for_update()
        )).scalar_one_or_none()
        if shop is None:
            raise HTTPException(status_code=409, detail="الطلب العاجل يشير إلى محل مفقود داخل الشركة.")

        await db.delete(shortage)
        await db.flush()

        if driver_id is not None:
            remaining_for_owner = int((await db.execute(
                select(func.count(ShortageRequest.id)).filter(
                    ShortageRequest.company_id == company_id,
                    ShortageRequest.shop_id == shop_id,
                    ShortageRequest.driver_id == driver_id,
                    ShortageRequest.status == "pending",
                )
            )).scalar() or 0)
            if remaining_for_owner == 0:
                pending_emergency = (await db.execute(
                    select(Visit).filter(
                        Visit.company_id == company_id,
                        Visit.shop_id == shop_id,
                        Visit.driver_id == driver_id,
                        Visit.status == "Pending",
                        Visit.is_emergency.is_(True),
                    ).order_by(Visit.id.asc()).with_for_update()
                )).scalars().all()
                active_route = (await db.execute(
                    select(DispatchRoute).filter(
                        DispatchRoute.company_id == company_id,
                        DispatchRoute.driver_id == driver_id,
                        DispatchRoute.status == "active",
                    ).order_by(DispatchRoute.id.asc()).limit(1)
                )).scalars().first()
                for visit in pending_emergency:
                    if active_route is not None and int(active_route.zone_id) == int(shop.zone_id or 0):
                        visit.is_emergency = False
                    else:
                        # لا نخلق Visit يتيمة ولا ننقلها لمندوب آخر بصمت؛ إلغاء الطلب يلغي مهمته فقط.
                        visit.status = "Cancelled"
                        visit.is_emergency = False
                        visit.work_session_id = None

        await db.commit()
        asyncio.create_task(dispatch_manager.broadcast(
            {"event": "SHORTAGE_DELETED", "message": "تم معالجة نواقص"}, company_id=company_id
        ))
        return {"message": "تم حذف الطلب وتنظيف الميدان بنجاح"}
    except HTTPException:
        await db.rollback(); raise
    except IntegrityError as exc:
        await db.rollback()
        logger.error(f"Shortage delete integrity conflict: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=409, detail="تعارض متزامن أثناء حذف الطلب العاجل.") from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي أثناء حذف الطلب.") from exc



# =========================================
# 26. الاستيراد الآمن للمحلات بالجملة (Bulk Import O(1) & Memory Safe)
# =========================================
@router.post("/dispatch/shops/bulk_import", status_code=201)
async def bulk_import_shops(
    payload: BulkImportRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    company_id = current_admin.company_id
    zone_id = int(payload.zoneId)
    shops_list = payload.shops
    file_name = payload.fileName

    log_id = None
    try:
        # Log له معاملة مستقلة حتى يبقى أثر الفشل حتى لو rollback للاستيراد نفسه.
        zone_exists = (
            await db.execute(
                select(Zone.id).filter(
                    Zone.id == zone_id,
                    Zone.company_id == company_id,
                    Zone.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if zone_exists is None:
            raise HTTPException(
                status_code=400,
                detail="المنطقة المحددة غير موجودة أو لا تتبع شركتك.",
            )

        import_log = ImportLog(
            company_id=company_id,
            admin_id=current_admin.id,
            zone_id=zone_id,
            file_name=file_name,
            total_records=len(shops_list),
            status="Processing",
        )
        db.add(import_log)
        await db.flush()
        log_id = int(import_log.id)
        await db.commit()

        # نعيد قفل المنطقة بعد Commit الخاص بالـLog؛ هكذا لا يمكن أرشفتها أثناء الاستيراد.
        locked_zones = await _dispatch_lock_zone_rows(
            db,
            company_id=company_id,
            zone_ids=[zone_id],
        )
        if not locked_zones[zone_id].is_active:
            raise HTTPException(
                status_code=409,
                detail="تمت أرشفة المنطقة قبل بدء الاستيراد. أعد المحاولة بعد استعادتها.",
            )

        incoming_names = list({
            s.name.strip().lower()
            for s in shops_list
            if s.name and s.name.strip()
        })
        incoming_phones = list({
            (
                str(s.phone).strip()[:-2]
                if str(s.phone).strip().endswith(".0")
                else str(s.phone).strip()
            )
            for s in shops_list
            if s.phone and str(s.phone).strip()
        })
        incoming_links = list({
            s.mapLink.strip().lower()
            for s in shops_list
            if s.mapLink and s.mapLink.strip()
        })

        # نفس مفتاح phone المستخدم في إضافة المحل؛ استيرادان/إضافة يمران تسلسلياً دون إسقاط الملف كله.
        await _dispatch_advisory_locks(
            db,
            company_id=company_id,
            keys=[f"shop-phone:{phone}" for phone in incoming_phones],
        )

        all_existing_shops_raw = []
        chunk_size = 500
        max_len = max(len(incoming_names), len(incoming_phones), len(incoming_links))

        for i in range(0, max_len, chunk_size):
            name_chunk = incoming_names[i:i + chunk_size]
            phone_chunk = incoming_phones[i:i + chunk_size]
            link_chunk = incoming_links[i:i + chunk_size]

            filters = []
            if name_chunk:
                filters.append(func.lower(Shop.name).in_(name_chunk))
            if phone_chunk:
                filters.append(Shop.phone_number.in_(phone_chunk))
            if link_chunk:
                filters.append(func.lower(Shop.location_link).in_(link_chunk))

            if filters:
                results = (
                    await db.execute(
                        select(
                            Shop.id,
                            Shop.name,
                            Shop.phone_number,
                            Shop.location_link,
                        ).filter(
                            Shop.company_id == company_id,
                            or_(*filters),
                        )
                    )
                ).all()
                all_existing_shops_raw.extend(results)

        all_existing_shops = list({
            row[0]: row for row in all_existing_shops_raw
        }.values())

        name_idx, phone_idx, link_idx = {}, {}, {}
        for ext_id, ext_name, ext_phone, ext_link in all_existing_shops:
            n = (ext_name or "").strip().lower()
            p = str(ext_phone or "").strip()
            l = (ext_link or "").strip().lower()
            if n:
                name_idx.setdefault(n, []).append(ext_id)
            if p:
                phone_idx.setdefault(p, []).append(ext_id)
            if l:
                link_idx.setdefault(l, []).append(ext_id)

        new_shops = []
        ignored_count = 0

        for s in shops_list:
            s_name = (s.name or "").strip().lower()
            s_phone = str(s.phone or "").strip()
            if s_phone.endswith(".0"):
                s_phone = s_phone[:-2]
            s_link = (s.mapLink or "").strip().lower()

            candidate_ids = []
            if s_name in name_idx:
                candidate_ids.extend(name_idx[s_name])
            if s_phone in phone_idx:
                candidate_ids.extend(phone_idx[s_phone])
            if s_link in link_idx:
                candidate_ids.extend(link_idx[s_link])

            is_phone_duplicate = bool(s_phone and s_phone in phone_idx)
            is_duplicate = (
                is_phone_duplicate
                or any(count >= 2 for count in Counter(candidate_ids).values())
            )
            if is_duplicate:
                ignored_count += 1
                continue

            new_shop = Shop(
                company_id=company_id,
                name=s.name.strip(),
                contact_person=(s.owner or "").strip(),
                phone_number=s_phone or None,
                location_link=(s.mapLink or "").strip(),
                zone_id=zone_id,
                is_active=True,
                is_archived=False,
                current_balance=s.initialDebt,
                added_by_driver_id=current_admin.id,
                sequence=int(s.sequence),
            )
            new_shops.append(new_shop)

            temp_id = f"temp_{len(new_shops)}"
            if s_name:
                name_idx.setdefault(s_name, []).append(temp_id)
            if s_phone:
                phone_idx.setdefault(s_phone, []).append(temp_id)
            if s_link:
                link_idx.setdefault(s_link, []).append(temp_id)

        db.add_all(new_shops)

        current_log = (
            await db.execute(
                select(ImportLog)
                .filter_by(id=log_id, company_id=company_id)
                .order_by(ImportLog.id.asc())
                .with_for_update()
            )
        ).scalar_one_or_none()
        if current_log is None:
            raise HTTPException(
                status_code=409,
                detail="سجل الاستيراد اختفى أثناء التنفيذ.",
            )
        current_log.success_count = len(new_shops)
        current_log.status = "Success"

        await db.commit()
        return {
            "message": f"تم رفع {len(new_shops)} محل بنجاح، وتجاهل {ignored_count} مكرر."
        }

    except HTTPException:
        await db.rollback()
        if log_id:
            try:
                await db.execute(
                    update(ImportLog)
                    .where(
                        ImportLog.id == log_id,
                        ImportLog.company_id == company_id,
                    )
                    .values(status="Failed")
                )
                await db.commit()
            except Exception:
                await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        logger.error(f"Bulk import integrity conflict: {str(exc)}", exc_info=True)
        if log_id:
            try:
                await db.execute(
                    update(ImportLog)
                    .where(
                        ImportLog.id == log_id,
                        ImportLog.company_id == company_id,
                    )
                    .values(status="Failed")
                )
                await db.commit()
            except Exception:
                await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="تعارض متزامن أثناء استيراد المحلات؛ لم يتم حفظ دفعة جزئية.",
        ) from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(exc)}", exc_info=True)

        if log_id:
            try:
                await db.execute(
                    update(ImportLog)
                    .where(
                        ImportLog.id == log_id,
                        ImportLog.company_id == company_id,
                    )
                    .values(status="Failed")
                )
                await db.commit()
            except Exception:
                await db.rollback()

        raise HTTPException(
            status_code=500,
            detail="فشل في رفع البيانات، تم إلغاء العملية بالكامل لحماية قاعدة البيانات.",
        ) from exc
