import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from ws_manager import dispatch_manager
from sqlalchemy.future import select
from sqlalchemy import delete, func, or_, and_, case, nullslast, update, cast, Float
from database import get_db
from api.dependencies import get_current_driver, get_current_admin
from datetime import timedelta, datetime, timezone
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
from decimal import Decimal
from typing import List 
from fastapi.responses import JSONResponse
import re
from collections import Counter
import logging
logger = logging.getLogger("wanasah_logger")

# +++ توحيد الزمن المعماري لنسف تعارض الـ Timezone في قاعدة البيانات +++
def get_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

from models import ( Driver, WorkSession, SystemAuditLog, DamagedItemLog, MainWarehouse, InventoryLedger,
VehicleLoad, VisitReturn, ProductVariant, DispatchRoute, WarehouseLedger,Zone, Vehicle, Shop,Visit,
 SessionInventory, ShortageRequest, SystemSetting, InventoryTransfer, Country, Governorate, ImportLog, VisitItem, InventoryLocation)

from services import check_inventory_lock # +++ الحارس الجراحي للـ SaaS +++
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
    InventoryMovement,
    SessionInventorySnapshot,
)
from uuid import uuid4

from schemas import ( MessageResponse, AuthorizeSessionRequest, AdminDashboardDriverResponse,
SessionSettlementReportResponse, SettleSessionRequest, SettleSessionResponse, DispatchInitResponse,
DispatchRouteRequest, VehicleInventoryItemResponse, RouteLiveInventoryItemResponse, AdjustRouteInventoryRequest,
RouteTransferResponse, DispatchShopResponse, BulkUpdateShopItem, AdminAddShopRequest, ActiveRouteResponse,
UpdateRouteStatusRequest, AddZoneRequest, ArchivedZoneResponse, EditShopDetailsRequest, ShortageResponseItem,
CreateShortageItem, BulkImportRequest, UpdateZoneRequest)



# إنشاء روتر خاص بمسارات الإدارة (بتاج منفصل لتنظيم Swagger)
router = APIRouter(tags=["Admin & Dispatch Operations"])

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


async def _dispatch_driver_shortage_cash(
    db: AsyncSession,
    *,
    company_id: int,
    work_session_id: int,
) -> Decimal:
    rows = (
        await db.execute(
            select(InventoryMovement.quantity, ProductVariant.price_per_pack)
            .join(
                ProductVariant,
                and_(
                    ProductVariant.company_id == InventoryMovement.company_id,
                    ProductVariant.id == InventoryMovement.product_variant_id,
                ),
            )
            .filter(
                InventoryMovement.company_id == company_id,
                InventoryMovement.work_session_id == work_session_id,
                InventoryMovement.reference_type == "DRIVER_SHORTAGE",
                InventoryMovement.movement_kind == "PHYSICAL",
                ProductVariant.company_id == company_id,
            )
        )
    ).all()
    total = Decimal("0.000")
    for quantity, price_per_pack in rows:
        qty = int(quantity or 0)
        price = Decimal(str(price_per_pack or "0.000"))
        if qty < 0 or not price.is_finite() or price < 0:
            raise HTTPException(status_code=409, detail="قيد عجز المندوب يحمل قيمة مالية غير صالحة.")
        total += Decimal(qty) * price
    if not total.is_finite() or total < 0:
        raise HTTPException(status_code=409, detail="إجمالي قيمة عجز المندوب غير صالح.")
    return total


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
    limit_date = company_local_date - timedelta(days=14)

    sessions = (
        await db.execute(
            select(WorkSession)
            .options(joinedload(WorkSession.driver))
            .filter(
                WorkSession.company_id == company_id,
                or_(
                    WorkSession.session_date == company_local_date,
                    and_(
                        WorkSession.is_settled.is_(False),
                        WorkSession.session_date >= limit_date,
                    ),
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

    inventory_map, route_map = await _dispatch_session_inventory_projection(
        db,
        company_id=company_id,
        sessions=sessions,
    )

    result = []
    for session in sessions:
        driver = session.driver
        if driver is None or not driver.is_active or driver.is_admin:
            continue

        sid = int(session.id)
        stats = stats_map.get(sid)
        cash_from_sales = Decimal(str(stats.total_cash or "0.000")) if stats else Decimal("0.000")
        cash_from_debts = Decimal(str(stats.total_debt or "0.000")) if stats else Decimal("0.000")
        expected_cash = cash_from_sales + cash_from_debts
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
            select(VisitItem, Shop.name, ProductVariant.variant_name)
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
    expected_cash = cash_from_sales + cash_from_debts

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
    current_admin: Driver = Depends(get_current_admin)
):

    # 1. جلب الكيانات الأساسية بضربات متوازية
    stmt_zones = select(Zone).filter_by(
    company_id=current_admin.company_id,
    is_active=True
)
    zones = (await db.execute(stmt_zones)).scalars().all()

    stmt_drivers = select(Driver).filter_by(
    company_id=current_admin.company_id,
    is_active=True,
    is_admin=False
)
    drivers = (await db.execute(stmt_drivers)).scalars().all()

    stmt_vehicles = select(Vehicle).filter_by(
    company_id=current_admin.company_id,
    is_active=True
)
    vehicles = (await db.execute(stmt_vehicles)).scalars().all()

    stmt_products = select(ProductVariant).filter_by(
    company_id=current_admin.company_id,
    is_active=True
)
    products = (await db.execute(stmt_products)).scalars().all()

    # 2. +++ الحل السحري لمشكلة N+1 (O(1)): استعلام واحد يجلب عدد المحلات لكل المناطق +++
    stmt_shop_counts = select(Shop.zone_id, func.count(Shop.id)).filter(
    Shop.company_id == current_admin.company_id,
    Shop.is_archived == False,
    Shop.is_active == True
).group_by(Shop.zone_id)
    
    shop_counts = (await db.execute(stmt_shop_counts)).all()
    # تحويل النتيجة لقاموس (Dictionary) لسرعة البحث
    shop_count_map = {row.zone_id: row[1] for row in shop_counts if row.zone_id}

    today = datetime.now(timezone.utc).date()
    zones_data = []
    
    for z in zones:
        # استخدام الذاكرة المسبقة (O(1)) بدلاً من استعلام مهدر داخل الحلقة
        shops_count = shop_count_map.get(z.id, 0)
        
        # تحديد حالة الجدولة للترتيب واللون الأحمر (مطابق لمنطقك)
        schedule_status = "null"
        if z.start_date:
            if z.start_date < today: 
                schedule_status = "overdue"
            elif z.start_date == today: 
                schedule_status = "today"
            else: 
                schedule_status = "upcoming"

        zones_data.append({
            "id": str(z.id), 
            "name": z.name,
            "visitDay": z.visit_day or "غير محدد",
            "startDate": z.start_date.isoformat() if z.start_date else "",
            "frequency": z.schedule_frequency or "أسبوعي",
            "scheduleStatus": schedule_status,
            "shopsCount": shops_count
        })

    # تسليم العقد للواجهة كما في الفلاسك تماماً
    return {
        "zones": zones_data,
        "drivers": [{"id": str(d.id), "name": d.full_name} for d in drivers],
        "vehicles": [{"id": str(v.id), "label": f"{v.vehicle_type} - {v.plate_number}"} for v in vehicles],
        "products": [{"id": str(p.id), "name": p.variant_name} for p in products]
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

# =========================================
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

# =========================================
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

# =========================================
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

# =========================================
# 11. استرجاع المحلات (شاشة التوزيع - Pagination Limit)
# =========================================
@router.get("/dispatch/shops", response_model=List[DispatchShopResponse], status_code=200)
async def get_dispatch_shops(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    
    # تحذير هندسي: تم إزالة  ـ limit(2000) الكارثي لأن يسبب اختلاف المحلات (Data Truncation)
    # ملاحظة: يجب تطبيق Pagination 진ية لاحقاً، ولكن حالياً نجلب المحلات النشطة لoids كوارث التوزيع
    stmt = select(Shop).filter(
    Shop.company_id == current_admin.company_id,
    Shop.is_active == True,
    Shop.is_archived == False
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


# =========================================
# 12. التحديث الجماعي للمحلات (نقل، ترتيب، أرشفة، استعادة)
# =========================================
@router.put("/dispatch/shops/bulk_update", status_code=200)
async def bulk_update_shops(
    payload: List[BulkUpdateShopItem],
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    
        
    try:
        # 1. تنظيف الـ IDs من حرف s القادم من React (مطابق للفلاسك)
        shop_ids = [str(item.id).replace('s', '') for item in payload if item.id]
        if not shop_ids:
            return {"message": "لا توجد بيانات للتحديث"}

        # 2. جلب المحلات من الداتابيز دفعة واحدة O(1)
        stmt_shops = select(Shop).filter(
            Shop.company_id == current_admin.company_id,
            Shop.id.in_([int(i) for i in shop_ids if i.isdigit()])
        )
        bulk_shops = {str(sh.id): sh for sh in (await db.execute(stmt_shops)).scalars().all()}
        
        # 3. جلب المناطق للتحقق من سلامة استعادة المحلات المؤرشفة (Restore Shield)
        zone_ids_to_check = set()
        for s in payload:
            clean_id = str(s.id).replace('s', '')

            if s.zoneId is not None and str(s.zoneId).isdigit():
                zone_ids_to_check.add(int(s.zoneId))
            elif s.archived is False and clean_id in bulk_shops:
                z_id = bulk_shops[clean_id].zone_id
                if z_id:
                    zone_ids_to_check.add(int(z_id))
                    
        bulk_zones = {}
        if zone_ids_to_check:
            stmt_zones = select(Zone).filter(
                Zone.company_id == current_admin.company_id,
                Zone.id.in_(list(zone_ids_to_check))
            )
            bulk_zones = {z.id: z for z in (await db.execute(stmt_zones)).scalars().all()}

        archived_shop_ids = []
        
        # 4. التحديث الجراحي بالذاكرة
        for s_data in payload:
            clean_id = str(s_data.id).replace('s', '')
            shop = bulk_shops.get(clean_id)
            
            if shop:
                # حماية الاستعادة (منع استعادة محل لمنطقة ميتة)
                if s_data.archived is False:
                    raw_zone = s_data.zoneId if s_data.zoneId is not None else str(shop.zone_id)
                    z_id = int(raw_zone) if (raw_zone and raw_zone.isdigit()) else None
                    zone_exists = bulk_zones.get(z_id)
                    
                    if not zone_exists or not getattr(zone_exists, 'is_active', True):
                        await db.rollback()
                        raise HTTPException(status_code=400, detail=f"لا يمكن استعادة المحل '{shop.name}' لأن منطقته مؤرشفة. يرجى نقله لمنطقة نشطة أولاً.")

                # تحديث الترتيب مع حماية الفراغات (Empty Strings)
                if s_data.sequence is not None:
                    raw_seq = str(s_data.sequence).strip()
                    shop.sequence = int(raw_seq) if raw_seq.isdigit() else 999
                    
                # تحديث حالة الأرشيف
                if s_data.archived is not None:
                    shop.is_archived = s_data.archived
                    if s_data.archived is True:
                        archived_shop_ids.append(int(shop.id))
                        
                # تحديث النقل الجغرافي (Zone)
                if s_data.zoneId is not None and str(s_data.zoneId).isdigit():
                    target_zone_id = int(s_data.zoneId)

                    if target_zone_id not in bulk_zones:
                        await db.rollback()
                        raise HTTPException(
                            status_code=400,
                            detail="المنطقة المحددة غير موجودة أو لا تتبع شركتك."
                        )

                    shop.zone_id = target_zone_id
                    
        # 5.   إلغاء الزيارات المعلقة للمحلات التي تم أرشفتها للتو (Cascade Cancel)
        if archived_shop_ids:
            stmt_cancel = update(Visit).where(
                Visit.company_id == current_admin.company_id,
                Visit.shop_id.in_(archived_shop_ids),
                Visit.status == 'Pending'
            ).values(status='Cancelled')
            await db.execute(stmt_cancel)
            
        await db.commit()
        return {"message": "تم تحديث المحلات بنجاح"}

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"خطأ تعارض (FK): {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail="فشل الحفظ: تأكد من أن المنطقة المحددة للنقل موجودة وصالحة.")
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء التحديث الجماعي.")


# =========================================
# 13. إضافة محل جديد من لوحة التحكم (مع كاشف التكرار الذكي)
# =========================================
@router.post("/dispatch/shops", status_code=201)
async def admin_add_shop(
    payload: AdminAddShopRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    name = payload.name.strip()
    phone = payload.phone.strip() if payload.phone else ""
    map_link = payload.mapLink.strip() if payload.mapLink else ""
    zone_id = payload.zoneId
    
    # +++ حماية  ـ 500 Crash بمعالجة منفصلة للإحداثيات لمنع ضياع السليم منها +++
    lat, lng = None, None
    try:
        # +++ سحق لغم الصفر الجغرافي: 0.0 يعتبر Falsy في بايثون، يجب فحصه كـ is not None +++
        if payload.latitude is not None and str(payload.latitude).strip().lower() not in ['', 'none']:
            lat = float(str(payload.latitude).strip())
    except ValueError: pass
    
    try:
        if payload.longitude is not None and str(payload.longitude).strip().lower() not in ['', 'none']:
            lng = float(str(payload.longitude).strip())
    except ValueError: pass

    if not name: 
        raise HTTPException(status_code=400, detail="مرفوض: اسم المحل إجباري")
    if not zone_id: 
        raise HTTPException(status_code=400, detail="مرفوض: المنطقة إجبارية لإنشاء المحل")

    stmt_zone = select(Zone.id).filter_by(
        id=zone_id,
        company_id=current_admin.company_id,
        is_active=True
    )
    zone_exists = (await db.execute(stmt_zone)).scalar_one_or_none()

    if zone_exists is None:
        raise HTTPException(
            status_code=400,
            detail="المنطقة المحددة غير موجودة أو لا تتبع شركتك."
        )
    
    # ========================================================
    # 1. الفحص الذكي المركب (Duplicate Detection Shield) - مطابق للفلاسك 100%
    # ========================================================
    duplicate_shop = None

    # الفحص الأول: رقم الهاتف
    if phone:
        stmt = select(Shop).options(joinedload(Shop.zone)).filter(
            Shop.company_id == current_admin.company_id,
            Shop.phone_number == phone
        )
        duplicate_shop = (await db.execute(stmt)).scalars().first()

    # الفحص الثاني: التطابق بالاسم ورابط الموقع
    if not duplicate_shop and name and map_link:
        stmt = select(Shop).options(joinedload(Shop.zone)).filter(
            Shop.company_id == current_admin.company_id,
            Shop.name == name,
            Shop.location_link == map_link
        )
        duplicate_shop = (await db.execute(stmt)).scalars().first()

    # الفحص الثالث: الرادار الجغرافي (الإحداثيات)
    if not duplicate_shop and lat is not None and lng is not None:
        stmt = select(Shop).options(joinedload(Shop.zone)).filter(
            Shop.company_id == current_admin.company_id,
            Shop.name == name,
            Shop.latitude.isnot(None), 
            Shop.longitude.isnot(None),
            # +++ رياضيات الـ GPS الآمنة في SQLAlchemy +++
            func.abs(cast(Shop.latitude, Float) - lat) < 0.0001,
            func.abs(cast(Shop.longitude, Float) - lng) < 0.0001
        )
        duplicate_shop = (await db.execute(stmt)).scalars().first()

    # في حال اكتشاف تكرار ولم يتم طلب الحفظ الإجباري
    if duplicate_shop and not payload.force_save:
        zone_name = duplicate_shop.zone.name if duplicate_shop.zone else "بدون منطقة"
        is_arch_msg = " (مؤرشف)" if getattr(duplicate_shop, 'is_archived', False) else ""
        
        # نرجع 409 مع بيانات المحل المكرر ليتمكن الفرونت إند من عرضها للمشرف
        return JSONResponse(status_code=409, content={
            "message": "تنبيه: يوجد محل مسجل مسبقاً بمعلومات مطابقة.",
            "is_duplicate": True,
            "existing_shop": {
                "id": str(duplicate_shop.id),
                "name": duplicate_shop.name,
                "owner": duplicate_shop.contact_person or "غير مسجل",
                "phone": duplicate_shop.phone_number,
                "mapLink": duplicate_shop.location_link,
                "zone_name": zone_name + is_arch_msg
            }
        })

    # ========================================================
    # 2. التطهير المحاسبي ونسف الفراغات للحفظ النهائي
    # ========================================================
    try:
        try:
            raw_initial_debt = str(payload.initialDebt).strip()
            safe_initial_debt = Decimal(raw_initial_debt) if raw_initial_debt not in ['', 'None'] else Decimal('0.0')
        except Exception:
            safe_initial_debt = Decimal('0.0')
            
        try:
            raw_max_limit = str(payload.maxDebtLimit).strip()
            safe_max_limit = Decimal(raw_max_limit) if raw_max_limit not in ['', 'None'] else Decimal('0.0')
        except Exception:
            safe_max_limit = Decimal('0.0')
            
        # تنظيف الترتيب (Sequence)
        raw_seq = str(payload.sequence).strip()
        safe_sequence = int(raw_seq) if raw_seq.isdigit() else 999

        new_shop = Shop(
            company_id=current_admin.company_id,
            name=name,
            contact_person=payload.owner.strip() if payload.owner else "",
            phone_number=phone,
            location_link=map_link,
            latitude=lat,
            longitude=lng,
            zone_id=zone_id,
            is_active=True,
            is_archived=False,
            # حماية الداتابيز من الأرصدة والسقوف السالبة
            current_balance=max(Decimal('0.0'), safe_initial_debt),
            max_debt_limit=max(Decimal('0.0'), safe_max_limit),
            added_by_driver_id=current_admin.id,
            sequence=safe_sequence
        )
        db.add(new_shop)
        # +++ الدرع الفولاذي (O(1)): سحب الـ ID قبل الـ Commit لمنع MissingGreenlet بدون استعلام إضافي +++
        await db.flush() 
        shop_id = new_shop.id 
        
        await db.commit()
        return {"message": "تم إضافة المحل بنجاح", "shop_id": str(shop_id)}
        
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء إضافة المحل.")


# =========================================
# 14. استرجاع خطوط السير النشطة والمؤجلة (غرفة مراقبة المدير)
# =========================================
@router.get("/dispatch/active_routes", response_model=List[ActiveRouteResponse], status_code=200)
async def get_active_routes(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    
        
    stmt_routes = select(DispatchRoute).filter(
    DispatchRoute.company_id == current_admin.company_id,
    DispatchRoute.status.in_(['active', 'waiting', 'postponed'])
)
    routes = (await db.execute(stmt_routes)).scalars().all()
    
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
            "sessionEnded": session_ended 
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
    current_admin: Driver = Depends(get_current_admin)
):
    

    # +++ الدرع الاستباقي (Fail-Fast): سد ثغرة الجرد في أول سطر لمنع اختناق السيرفر ونسف مشاكل المحرر +++
    if payload.inventory is not None:
        # +++ سحق قنبلة الـ 500 (P0) عبر فلترة الشركة +++
        audit_check = (await db.execute(select(SystemSetting).filter_by(company_id=current_admin.company_id, setting_key='warehouse_status'))).scalar_one_or_none()
        if audit_check and audit_check.setting_value == 'AUDIT_LOCK':
            raise HTTPException(status_code=403, detail="مرفوض: المستودع مقفل حالياً لغايات الجرد (Stocktake). يرجى فتح المستودع أولاً.")
            
    # +++ قفل خط السير لمنع التضارب أثناء التبديل أو الإغلاق +++
    stmt_route_lock = select(DispatchRoute).filter_by(
    id=route_id,
    company_id=current_admin.company_id
    ).order_by(DispatchRoute.id.asc()).with_for_update()
    route = (await db.execute(stmt_route_lock)).scalar_one_or_none()
    if not route:
        await db.rollback() # +++ الدرع الفولاذي: نسف ثغرة تسريب الأقفال (Lock Leak) +++
        raise HTTPException(status_code=404, detail="خط السير غير موجود")

    new_status = payload.status
    new_driver_id = int(payload.driverId) if payload.driverId and str(payload.driverId).isdigit() else None
    new_vehicle_id = int(payload.vehicleId) if payload.vehicleId and str(payload.vehicleId).isdigit() else None
    
    # ========================================================
    # 1. الدرع المعماري الصارم: التحقق من التضارب
    # ========================================================
    target_driver_id = new_driver_id or route.driver_id
    is_activating = (new_status == 'active') or (not new_status and route.status == 'active')
    
    if is_activating:
        # +++  2 (Phase 3b): قفل الأصول وتصحيح الـ Status Code إلى 409 بدلاً من 400 ليتوافق مع اختبارات الضغط +++
        if target_driver_id:
            stmt_target_driver = select(Driver).filter_by(
                id=target_driver_id,
                company_id=current_admin.company_id
            ).order_by(Driver.id.asc()).with_for_update()

            target_driver = (await db.execute(stmt_target_driver)).scalar_one_or_none()

            if not target_driver:
                await db.rollback()
                raise HTTPException(status_code=404, detail="المندوب المحدد غير موجود أو لا يتبع شركتك.")

            stmt_dup_driver = select(DispatchRoute).filter(
                DispatchRoute.company_id == current_admin.company_id,
                DispatchRoute.driver_id == target_driver_id,
                DispatchRoute.status == 'active',
                DispatchRoute.id != route.id
            )

            if (await db.execute(stmt_dup_driver)).first():
                await db.rollback()
                raise HTTPException(status_code=409, detail="مرفوض: المندوب لديه خط سير نشط حالياً.")
        
        target_veh = new_vehicle_id or route.vehicle_id

        if target_veh:
            stmt_target_vehicle = select(Vehicle).filter_by(
                id=target_veh,
                company_id=current_admin.company_id
            ).order_by(Vehicle.id.asc()).with_for_update()

            target_vehicle = (await db.execute(stmt_target_vehicle)).scalar_one_or_none()

            if not target_vehicle:
                await db.rollback()
                raise HTTPException(status_code=404, detail="السيارة المحددة غير موجودة أو لا تتبع شركتك.")

            stmt_dup_veh = select(DispatchRoute).filter(
                DispatchRoute.company_id == current_admin.company_id,
                DispatchRoute.vehicle_id == target_veh,
                DispatchRoute.status == 'active',
                DispatchRoute.id != route.id
            )

            if (await db.execute(stmt_dup_veh)).first():
                await db.rollback()
                raise HTTPException(status_code=409, detail="مرفوض: هذه السيارة مستخدمة في خط سير نشط آخر.")

        stmt_target_zone = select(Zone).filter_by(
            id=route.zone_id,
            company_id=current_admin.company_id
        ).order_by(Zone.id.asc()).with_for_update()

        target_zone = (await db.execute(stmt_target_zone)).scalar_one_or_none()

        if not target_zone:
            await db.rollback()
            raise HTTPException(status_code=404, detail="منطقة خط السير غير موجودة أو لا تتبع شركتك.")

        stmt_dup_zone = select(DispatchRoute).filter(
            DispatchRoute.company_id == current_admin.company_id,
            DispatchRoute.zone_id == route.zone_id,
            DispatchRoute.status == 'active',
            DispatchRoute.id != route.id
        )

        if (await db.execute(stmt_dup_zone)).first():
            await db.rollback()
            raise HTTPException(status_code=409, detail="مرفوض: هذه المنطقة قيد العمل حالياً مع مندوب آخر.")

    try:
        # ========================================================
        # 2. تحديث الحالة (والجدولة التلقائية)
        # ========================================================
        if new_status: 
            route.status = new_status
            if new_status == 'closed':
                stmt_zone = select(Zone).filter_by(
                    id=route.zone_id,
                    company_id=current_admin.company_id
                )
                zone = (await db.execute(stmt_zone)).scalar_one_or_none()
                if zone and zone.start_date and zone.schedule_frequency:
                    freq = str(zone.schedule_frequency)
                    days_to_add = 7
                    if freq == 'أسبوعي': days_to_add = 7
                    elif freq == 'نصف شهري': days_to_add = 14
                    else:
                        numbers = re.findall(r'\d+', freq)
                        if numbers: days_to_add = int(numbers[0])
                    zone.start_date = zone.start_date + timedelta(days=days_to_add)

            if new_status in ['closed', 'waiting', 'postponed'] and route.driver_id:
                # +++ الدرع الجغرافي: حصر مسح الزيارات المعلقة بمنطقة خط السير فقط لمنع مسح طوارئ المناطق الأخرى +++
                stmt_zone_shops = select(Shop.id).filter(
                    Shop.company_id == current_admin.company_id,
                    Shop.zone_id == route.zone_id
                ).scalar_subquery()

                stmt_zombies = update(Visit).where(
                    Visit.company_id == current_admin.company_id,
                    Visit.driver_id == route.driver_id,
                    Visit.status == 'Pending',
                    Visit.shop_id.in_(stmt_zone_shops)
                ).values(
                    driver_id=None,
                    work_session_id=None,
                    is_emergency=False
                )

                await db.execute(stmt_zombies)

        # ========================================================
        # 3. تبديل المندوب (حماية الفراطة، ودرع الـ Null Driver)
        # ========================================================
        if new_driver_id: 
            if new_driver_id != route.driver_id:
                # +++ لغم الـ Null Driver (): لا ننظف إلا إذا كان هناك مندوب قديم فعلاً +++
                if route.driver_id:
                    # +++ قفل الجلسة القديمة لمنع تضارب الإنهاء أثناء التبديل +++
                    stmt_old_sess = select(WorkSession).with_for_update().filter_by(
                        company_id=current_admin.company_id,
                        driver_id=route.driver_id,
                        end_time=None
                    ).limit(1)
                    old_active_session = (await db.execute(stmt_old_sess)).scalars().first()
                    
                    if old_active_session:
                        # +++ الدرع المستودعي: جلب الحوالات المعلقة أولاً لضمان عدم ضياع أي منتج جديد بالطريق +++
                        stmt_pend_trans = select(InventoryTransfer).filter_by(
                            company_id=current_admin.company_id,
                            work_session_id=old_active_session.id,
                            status='pending'
                        )
                        old_pending_transfers = (await db.execute(stmt_pend_trans)).scalars().all()
                        
                        stmt_live_invs = select(SessionInventory).filter_by(
                            company_id=current_admin.company_id,
                            work_session_id=old_active_session.id
                        )
                        live_invs = (await db.execute(stmt_live_invs)).scalars().all()
                        
                        # دمج جميع IDs المنتجات من العهدة الحية والحوالات المعلقة بضربة واحدة
                        var_ids = list(set([inv.product_variant_id for inv in live_invs] + [t.product_variant_id for t in old_pending_transfers]))
                        
                        if var_ids:
                            stmt_vars = select(ProductVariant).filter(
                                ProductVariant.company_id == current_admin.company_id,
                                ProductVariant.id.in_(var_ids)
                            )
                            variants = (await db.execute(stmt_vars)).scalars().all()
                            var_map = {v.id: (v.packs_per_carton if v.packs_per_carton else 1) for v in variants}

                            stmt_vloads = select(VehicleLoad).filter(
                                VehicleLoad.company_id == current_admin.company_id,
                                VehicleLoad.vehicle_id == route.vehicle_id,
                                VehicleLoad.product_variant_id.in_(var_ids)
                            ).order_by(VehicleLoad.id.asc()).with_for_update()
                            v_loads = (await db.execute(stmt_vloads)).scalars().all()
                            v_load_map = {vl.product_variant_id: vl for vl in v_loads}

                            # +++ قفل المستودع لحماية الفراطة المرتجعة +++
                            stmt_wh = select(MainWarehouse).with_for_update().filter(
                                MainWarehouse.company_id == current_admin.company_id,
                                MainWarehouse.product_variant_id.in_(var_ids)
                            ).order_by(MainWarehouse.product_variant_id.asc())
                            bulk_wh_records = {w.product_variant_id: w for w in (await db.execute(stmt_wh)).scalars().all()}
                            
                            for live_inv in live_invs:
                                safe_packs = var_map.get(live_inv.product_variant_id, 1)
                                actual_cartons = live_inv.current_remaining_quantity // safe_packs
                                loose_packs = live_inv.current_remaining_quantity % safe_packs # +++ سحق ثغرة تآكل الفراطة +++
                                
                                # +++ إعادة الفراطة الصريحة للمستودع وتوثيقها +++
                                if loose_packs > 0:
                                    wh_rec = bulk_wh_records.get(live_inv.product_variant_id)
                                    if not wh_rec:
                                        wh_rec = MainWarehouse(company_id=current_admin.company_id, product_variant_id=live_inv.product_variant_id, available_quantity_packs=0, reserved_quantity_packs=0)
                                        db.add(wh_rec)
                                        bulk_wh_records[live_inv.product_variant_id] = wh_rec
                                        db.add(SystemAuditLog(
                                            company_id=current_admin.company_id,
                                            admin_id=current_admin.id, target_id=f"Product_{live_inv.product_variant_id}", action_type="SILENT_WH_HEALING",
                                            old_value="No WH Record", new_value="Created with 0 balance (Switch Driver Loose)"
                                        ))
                                        
                                    old_wh_balance = wh_rec.available_quantity_packs or 0
                                    wh_rec.available_quantity_packs += loose_packs
                                    db.add(WarehouseLedger(
                                        company_id=current_admin.company_id,
                                        product_variant_id=live_inv.product_variant_id, transaction_type='DISPATCH_UNLOAD',
                                        quantity_packs=loose_packs, balance_before_packs=old_wh_balance, balance_after_packs=wh_rec.available_quantity_packs,
                                        admin_id=current_admin.id, reference_id=f"SWITCH_{route.id}", notes="إرجاع فراطة صالحة للمستودع عند تبديل المندوب"
                                    ))

                                v_load = v_load_map.get(live_inv.product_variant_id)
                                # +++ سحق ثغرة الأشباح (Phantom Record) +++
                                if actual_cartons <= 0:
                                    if v_load: await db.delete(v_load) 
                                else:
                                    if v_load: v_load.quantity = actual_cartons
                                    else: db.add(VehicleLoad(company_id=current_admin.company_id, vehicle_id=route.vehicle_id, product_variant_id=live_inv.product_variant_id, quantity=actual_cartons))
                                
                                # +++  (The Stolen Goods Exploit): تصفير عهدة المندوب القديم بعد سحب البضاعة منه وتوثيق الحركة مالياً لمنع اتهامه بعجز وهمي بآلاف الدنانير +++
                                old_quantity = live_inv.current_remaining_quantity
                                live_inv.current_remaining_quantity = 0
                                db.add(InventoryLedger(
                                    company_id=current_admin.company_id,
                                    work_session_id=old_active_session.id, driver_id=route.driver_id, vehicle_id=route.vehicle_id,
                                    product_variant_id=live_inv.product_variant_id, transaction_type='ROUTE_REASSIGNMENT_PULL', 
                                    expected_quantity=old_quantity, actual_quantity=0, difference=-old_quantity, 
                                    admin_id=current_admin.id, notes=f"سحب العهدة آلياً بسبب تحويل خط السير لمندوب آخر (ID: {new_driver_id})."
                                ))
                                
                        old_active_session.end_time = get_utc_now()
                        
                        # +++ تحرير البضاعة المحجوزة للمنتجات الجديدة أو الموجودة +++
                        
                        for ptr in old_pending_transfers:
                            if ptr.quantity_packs > 0:
                                wh_r = bulk_wh_records.get(ptr.product_variant_id)
                                if wh_r:
                                    wh_r.reserved_quantity_packs = max(0, wh_r.reserved_quantity_packs - ptr.quantity_packs)
                                    wh_r.available_quantity_packs += ptr.quantity_packs
                                    db.add(WarehouseLedger(
                                        company_id=current_admin.company_id,
                                        product_variant_id=ptr.product_variant_id, transaction_type='HANDSHAKE_RELEASE',
                                        quantity_packs=ptr.quantity_packs, balance_after_packs=wh_r.available_quantity_packs,
                                        admin_id=current_admin.id, reference_id=f"TRANS_CANCEL_{ptr.id}", 
                                        notes="إرجاع بضاعة محجوزة للمستودع بسبب تبديل/إلغاء خط سير المندوب."
                                    ))
                            ptr.status = 'rejected'
                            
                    stmt_zone_shops = select(Shop.id).filter(
                        Shop.company_id == current_admin.company_id,
                        Shop.zone_id == route.zone_id
                    ).scalar_subquery()

                    stmt_trans_visits = update(Visit).where(
                        Visit.company_id == current_admin.company_id,
                        Visit.driver_id == route.driver_id,
                        Visit.status == 'Pending',
                        Visit.shop_id.in_(stmt_zone_shops)
                    ).values(
                        driver_id=new_driver_id,
                        work_session_id=None
                    )

                    await db.execute(stmt_trans_visits)
                    
            route.driver_id = new_driver_id
            route.work_session_id = None
            
        if new_vehicle_id: route.vehicle_id = new_vehicle_id
        
        # ========================================================
        # 4. تحديث الحمولة الجراحي (Guard & Zero Trust)
        # ========================================================
        if payload.inventory is not None:
            # +++ B-08: منع التخطي الصامت إذا لم يكن هناك سيارة مرتبطة بخط السير +++
            if not route.vehicle_id:
                await db.rollback()
                raise HTTPException(status_code=400, detail="مرفوض: لا يمكن تعديل حمولة لخط سير لا يحتوي على سيارة مرتبطة.")
                
            # +++ الدرع الفولاذي: قفل الجلسة بضربة واحدة من البداية لمنع إنهاء العمل أثناء التعديل +++
            stmt_active_sess = (
                select(WorkSession).with_for_update().filter_by(
                    company_id=current_admin.company_id,
                    driver_id=route.driver_id,
                    end_time=None
                ).limit(1)
                if route.driver_id
                else None
            )
            active_session = (await db.execute(stmt_active_sess)).scalars().first() if stmt_active_sess is not None else None
            
            if not active_session:
                # +++  لكارثة تبخر المستودع (Warehouse Evaporation): حساب الفروقات بدقة وإرجاعها/سحبها من المستودع المركزي قبل تعديل السيارة لمنع ضياع البضاعة +++
                prod_ids_to_check = [int(p) for p, q in payload.inventory.items() if str(q).strip() != '']
                # +++ قفل VehicleLoad أولاً لمنع Deadlock متصالب مع ترتيب أقفال باقي الدوال +++
                stmt_existing_vl = select(VehicleLoad).with_for_update().filter_by(
                    company_id=current_admin.company_id,
                    vehicle_id=route.vehicle_id
                )
                existing_vloads = (await db.execute(stmt_existing_vl)).scalars().all()
                existing_vl_map = {vl.product_variant_id: vl for vl in existing_vloads}
                
                all_pids = list(set(prod_ids_to_check + list(existing_vl_map.keys())))
                if all_pids:
                    stmt_vars = select(ProductVariant).filter(
                        ProductVariant.company_id == current_admin.company_id,
                        ProductVariant.id.in_(all_pids)
                    )
                    v_map = {v.id: v for v in (await db.execute(stmt_vars)).scalars().all()}
                    
                    stmt_wh_lock = select(MainWarehouse).with_for_update().filter(
                        MainWarehouse.company_id == current_admin.company_id,
                        MainWarehouse.product_variant_id.in_(all_pids)
                    ).order_by(MainWarehouse.product_variant_id.asc())

                    bulk_wh_records = {
                        w.product_variant_id: w
                        for w in (await db.execute(stmt_wh_lock)).scalars().all()
                    }
                    
                    for p_id in all_pids:
                        variant = v_map.get(p_id)
                        if not variant: 
                            await db.rollback()
                            raise HTTPException(status_code=404, detail=f"مرفوض: المنتج رقم ({p_id}) غير موجود في النظام.")
                        ppc = variant.packs_per_carton if variant.packs_per_carton else 1
                        
                        raw_qty = payload.inventory.get(str(p_id), payload.inventory.get(p_id, 0))
                        clean_str = str(raw_qty).strip() if raw_qty is not None else ''
                        # Fix: dispatch.md Finding #1 — Reject negative cartons before delta to prevent phantom stock fabrication
                        new_cartons = int(clean_str) if (clean_str.isdigit() or (clean_str.startswith('-') and clean_str[1:].isdigit())) else 0
                        if new_cartons < 0:
                            await db.rollback()
                            raise HTTPException(status_code=400, detail=f"مرفوض أمنياً: لا يمكن إدخال كمية سالبة ({new_cartons}) للمنتج {variant.variant_name}.")
                        new_packs = new_cartons * ppc
                        
                        curr_load = existing_vl_map.get(p_id)
                        curr_packs = (curr_load.quantity * ppc) if curr_load else 0
                        delta_packs = new_packs - curr_packs
                        
                        if delta_packs == 0: continue
                        
                        wh_rec = bulk_wh_records.get(p_id)
                        if not wh_rec:
                            wh_rec = MainWarehouse(company_id=current_admin.company_id, product_variant_id=p_id, available_quantity_packs=0, reserved_quantity_packs=0)
                            db.add(wh_rec)
                            db.add(SystemAuditLog(
                                company_id=current_admin.company_id,
                                admin_id=current_admin.id, target_id=f"Product_{p_id}", action_type="SILENT_WH_HEALING",
                                old_value="No WH Record", new_value="Created with 0 balance (Adjust Morning)"
                            ))
                            
                        old_wh_balance = wh_rec.available_quantity_packs or 0
                        if delta_packs > 0:
                            if wh_rec.available_quantity_packs < delta_packs:
                                await db.rollback()
                                raise HTTPException(status_code=400, detail=f"مرفوض: المستودع لا يملك ({delta_packs}) حبة متاحة من {variant.variant_name}.")
                            wh_rec.available_quantity_packs -= delta_packs
                            db.add(WarehouseLedger(company_id=current_admin.company_id, product_variant_id=p_id, transaction_type='DISPATCH_LOAD', quantity_packs=delta_packs, balance_before_packs=old_wh_balance, balance_after_packs=wh_rec.available_quantity_packs, admin_id=current_admin.id, reference_id=f"VEH_EDIT_{route.id}", notes="تعديل حمولة سيارة قبل الدوام: سحب من المستودع"))
                        else:
                            wh_rec.available_quantity_packs += abs(delta_packs)
                            db.add(WarehouseLedger(company_id=current_admin.company_id, product_variant_id=p_id, transaction_type='DISPATCH_UNLOAD', quantity_packs=abs(delta_packs), balance_before_packs=old_wh_balance, balance_after_packs=wh_rec.available_quantity_packs, admin_id=current_admin.id, reference_id=f"VEH_EDIT_{route.id}", notes="تعديل حمولة سيارة قبل الدوام: إعادة للمستودع"))
                            
                        if curr_load:
                            if new_cartons <= 0: db.delete(curr_load)
                            else: curr_load.quantity = new_cartons
                        elif new_cartons > 0:
                            db.add(VehicleLoad(company_id=current_admin.company_id, vehicle_id=route.vehicle_id, product_variant_id=p_id, quantity=new_cartons))
            else:
                admin_user_id = current_admin.id
                prod_ids_to_update = [int(p) for p, q in payload.inventory.items() if str(q).strip() != '']
                
                bulk_vloads = {}
                bulk_sinvs = {}
                pending_transfers_map = {}

                if prod_ids_to_update:
                    # +++ إعادة فرض الحماية المستودعية (Mid-day Handshake Guard) +++
                    stmt_wh_lock = select(MainWarehouse).with_for_update().filter(
                        MainWarehouse.company_id == current_admin.company_id,
                        MainWarehouse.product_variant_id.in_(prod_ids_to_update)
                    ).order_by(MainWarehouse.product_variant_id.asc())
                    bulk_wh_records = {w.product_variant_id: w for w in (await db.execute(stmt_wh_lock)).scalars().all()}

                    stmt_vl = select(VehicleLoad).filter(
                        VehicleLoad.company_id == current_admin.company_id,
                        VehicleLoad.vehicle_id == route.vehicle_id,
                        VehicleLoad.product_variant_id.in_(prod_ids_to_update)
                    )
                    bulk_vloads = {vl.product_variant_id: vl for vl in (await db.execute(stmt_vl)).scalars().all()}

                    stmt_sinv = select(SessionInventory).with_for_update().filter(
                        SessionInventory.company_id == current_admin.company_id,
                        SessionInventory.work_session_id == active_session.id,
                        SessionInventory.product_variant_id.in_(prod_ids_to_update)
                    )
                    bulk_sinvs = {si.product_variant_id: si for si in (await db.execute(stmt_sinv)).scalars().all()}

                    # +++ خريطتان منفصلتان: كل الحوالات المعلقة والسحوبات المعلقة +++
                    stmt_pending_all = select(
                        InventoryTransfer.product_variant_id,
                        func.sum(InventoryTransfer.quantity_packs)
                    ).filter(
                        InventoryTransfer.company_id == current_admin.company_id,
                        InventoryTransfer.work_session_id == active_session.id,
                        InventoryTransfer.product_variant_id.in_(prod_ids_to_update),
                        InventoryTransfer.status == 'pending'
                    ).group_by(InventoryTransfer.product_variant_id)

                    pending_all_map = {
                        v_id: int(total or 0)
                        for v_id, total in (await db.execute(stmt_pending_all)).all()
                    }

                    stmt_pending_pulls = select(
                        InventoryTransfer.product_variant_id,
                        func.sum(InventoryTransfer.quantity_packs)
                    ).filter(
                        InventoryTransfer.company_id == current_admin.company_id,
                        InventoryTransfer.work_session_id == active_session.id,
                        InventoryTransfer.product_variant_id.in_(prod_ids_to_update),
                        InventoryTransfer.status == 'pending',
                        InventoryTransfer.quantity_packs < 0
                    ).group_by(InventoryTransfer.product_variant_id)

                    pending_pulls_map = {
                        v_id: int(total or 0)
                        for v_id, total in (await db.execute(stmt_pending_pulls)).all()
                    }

                    stmt_vars = select(ProductVariant).filter(
                        ProductVariant.company_id == current_admin.company_id,
                        ProductVariant.id.in_(prod_ids_to_update)
                    )
                    variants_map = {v.id: v for v in (await db.execute(stmt_vars)).scalars().all()}
                    batch_timestamp = str(int(datetime.now(timezone.utc).timestamp()))
                    
                    for prod_id, new_qty_str in payload.inventory.items():
                        clean_qty_str = str(new_qty_str).strip()
                        if clean_qty_str == '': continue
                        try:
                            new_actual_qty_cartons = int(clean_qty_str)
                            p_id = int(prod_id)
                        except ValueError:
                            continue
                            
                        variant = variants_map.get(p_id)
                        if not variant: 
                            await db.rollback()
                            raise HTTPException(status_code=404, detail=f"مرفوض: المنتج رقم ({p_id}) غير موجود في النظام.")
                            
                        safe_packs_per_carton = variant.packs_per_carton if variant.packs_per_carton else 1
                        new_actual_qty_packs = new_actual_qty_cartons * safe_packs_per_carton
                            
                        # +++  لثغرة التدبيل: ترك VehicleLoad دون مساس. الاعتماد الكلي على المصافحة +++
                        sess_inv = bulk_sinvs.get(p_id)
                        current_live_packs = sess_inv.current_remaining_quantity if sess_inv else 0
                        existing_all_pending = pending_all_map.get(p_id, 0)
                        existing_pull_pending = pending_pulls_map.get(p_id, 0)
                        
                        difference_in_packs = new_actual_qty_packs - (current_live_packs + existing_all_pending)
                        
                        if difference_in_packs < 0:
                            # +++ الدرع الميداني: فحص قدرة المندوب على تغطية السحب +++
                            if current_live_packs + existing_pull_pending + difference_in_packs < 0:
                                await db.rollback()
                                raise HTTPException(status_code=400, detail=f"مرفوض: رصيد المندوب الحالي من ({variant.variant_name}) لا يكفي لتسجيل سحب {abs(difference_in_packs)} حبة.")

                        if difference_in_packs != 0:
                            wh_record = bulk_wh_records.get(p_id)
                            if not wh_record:
                                wh_record = MainWarehouse(company_id=current_admin.company_id, product_variant_id=p_id, available_quantity_packs=0, reserved_quantity_packs=0)
                                db.add(wh_record)
                                bulk_wh_records[p_id] = wh_record
                                db.add(SystemAuditLog(
                                    company_id=current_admin.company_id,
                                    admin_id=current_admin.id, target_id=f"Product_{p_id}", action_type="SILENT_WH_HEALING",
                                    old_value="No WH Record", new_value="Created with 0 balance (Adjust Mid-day)"
                                ))  
                                
                            # +++ الدرع المستودعي: حجز البضاعة في حال الزيادة +++
                            if difference_in_packs > 0:
                                if wh_record.available_quantity_packs < difference_in_packs:
                                    await db.rollback()
                                    raise HTTPException(status_code=400, detail=f"مرفوض: رصيد المستودع من ({variant.variant_name}) لا يكفي لتسجيل هذا التعديل.")
                                    
                                old_wh_balance = wh_record.available_quantity_packs or 0
                                wh_record.available_quantity_packs -= difference_in_packs
                                wh_record.reserved_quantity_packs += difference_in_packs
                                db.add(WarehouseLedger(
                                    company_id=current_admin.company_id,
                                    product_variant_id=p_id, transaction_type='HANDSHAKE_RESERVE',
                                    quantity_packs=difference_in_packs, balance_before_packs=old_wh_balance, balance_after_packs=wh_record.available_quantity_packs,
                                    admin_id=admin_user_id, reference_id=f"BATCH_{batch_timestamp}", notes="حجز بضاعة لتعديل خط سير نشط."
                                ))
                                
                            # إصدار الحوالة للمندوب
                            new_transfer = InventoryTransfer(
                                company_id=current_admin.company_id,
                                work_session_id=active_session.id,
                                product_variant_id=p_id,
                                quantity_packs=difference_in_packs,
                                status='pending',
                                admin_id=admin_user_id,
                                notes=f"BATCH_{batch_timestamp}"
                            )
                            db.add(new_transfer)

        # ========================================================
        # 5. التوليد الذكي (أشباح الشاشة وربط الجلسة)
        # ========================================================
        if route.status == 'active' and route.driver_id:
            today = datetime.now(timezone.utc).date()
            
            stmt_shops_zone = select(Shop).filter_by(
                company_id=current_admin.company_id,
                zone_id=route.zone_id,
                is_active=True,
                is_archived=False
            )
            shops_in_zone = (await db.execute(stmt_shops_zone)).scalars().all()
            shop_ids = [s.id for s in shops_in_zone]
            
            if shop_ids:
                # +++   جلب جلسة المندوب الجديد لربطها بالأيتام فوراً +++
                stmt_new_sess = select(WorkSession).filter_by(
                    company_id=current_admin.company_id,
                    driver_id=route.driver_id,
                    end_time=None
                ).limit(1)
                new_active_sess = (await db.execute(stmt_new_sess)).scalars().first()
                
                # التبني المباشر (Direct Update) لسحق استهلاك الذاكرة
                update_vals = {'driver_id': route.driver_id}
                if new_active_sess:
                    update_vals['work_session_id'] = new_active_sess.id
                    
                stmt_adopt_orphans = update(Visit).where(
                    Visit.company_id == current_admin.company_id,
                    Visit.shop_id.in_(shop_ids),
                    Visit.status == 'Pending',
                    Visit.driver_id.is_(None)
                ).values(**update_vals)
                await db.execute(stmt_adopt_orphans)
                
                # +++  الحقيقي: توحيد Naive UTC لمنع تعارض قواعد البيانات +++
                today_start = get_utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
                today_end = today_start + timedelta(days=1)
                
                stmt_existing = select(Visit).filter(
                    Visit.company_id == current_admin.company_id,
                    Visit.driver_id == route.driver_id,
                    Visit.shop_id.in_(shop_ids),
                    or_(
                        Visit.status == 'Pending',
                        and_(
                            Visit.visit_timestamp >= today_start,
                            Visit.visit_timestamp < today_end
                        )
                    )
                )
                existing_visits = (await db.execute(stmt_existing)).scalars().all()
                existing_visits_map = {v.shop_id: v for v in existing_visits}
                visited_shop_ids = set(existing_visits_map.keys())
                
                stmt_pending_shortages = select(ShortageRequest.shop_id).filter(
                    ShortageRequest.company_id == current_admin.company_id,
                    ShortageRequest.shop_id.in_(shop_ids),
                    ShortageRequest.status == 'pending'
                )
                shortage_shop_ids = set((await db.execute(stmt_pending_shortages)).scalars().all())
                
                for shop in shops_in_zone:
                    is_emerg = shop.id in shortage_shop_ids
                    if shop.id not in visited_shop_ids:
                        db.add(Visit(
                            company_id=current_admin.company_id,
                            driver_id=route.driver_id, 
                            shop_id=shop.id, 
                            status='Pending', 
                            sequence=shop.sequence,
                            is_emergency=is_emerg,
                            work_session_id=new_active_sess.id if new_active_sess else None # +++ سحق أشباح الشاشة للزيارات الجديدة +++
                        ))
                    else:
                        visit_to_update = existing_visits_map.get(shop.id)
                        if visit_to_update and is_emerg:
                             visit_to_update.is_emergency = True
 
        await db.commit()
        asyncio.create_task(dispatch_manager.broadcast({"event": "ROUTE_STATUS_UPDATED", "message": "تم تحديث حالة خط السير"}, company_id=current_admin.company_id))
        return {"message": "تم تحديث خط السير بنجاح"}
        
    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"خطأ تعارض (FK): {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail="فشل الحفظ: تأكد من أن المنطقة المحددة للنقل موجودة وصالحة.")
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء تحديث خط السير.")


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
            raise HTTPException(status_code=409, detail="المندوب لديه جلسة عمل أخرى نشطة؛ لا يمكن إعادة فتح الجلسة القديمة.")

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
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء التراجع عن إنهاء العمل.") from exc

# =========================================
# 17. إدارة المناطق (إضافة منطقة جديدة)
# =========================================
@router.post("/dispatch/zones", status_code=201)
async def add_zone(
    payload: AddZoneRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="اسم المنطقة مطلوب")

    # الفحص الصارم لوجود المنطقة (نشطة أو مؤرشفة)
    # +++ B-09: قفل التزامن لمنع سباق الإشارات (TOCTOU) عند إنشاء مناطق بنفس اللحظة +++
    stmt_existing = select(Zone).filter_by(
    name=name,
    company_id=current_admin.company_id
    ).with_for_update()
    existing_zone = (await db.execute(stmt_existing)).scalars().first()
    
    if existing_zone:
        await db.rollback() # +++ إغلاق تسريب الأقفال +++
        if not getattr(existing_zone, 'is_active', True):
            raise HTTPException(status_code=409, detail="هذه المنطقة موجودة مسبقاً في (أرشيف المناطق). يرجى استعادتها بدلاً من إنشائها من جديد.")
        raise HTTPException(status_code=409, detail="المنطقة موجودة ونشطة مسبقاً")

    try:
        # +++ المعالجة الذكية لحقل المحافظة الإجباري (Auto-Provisioning) O(1) +++
        stmt_gov = select(Governorate).limit(1)
        gov = (await db.execute(stmt_gov)).scalars().first()
        
        if not gov:
            stmt_country = select(Country).limit(1)
            country = (await db.execute(stmt_country)).scalars().first()
            if not country:
                country = Country(name="الأردن")
                db.add(country)
                await db.flush() # +++ توليد الـ ID للبلد +++
                
            gov = Governorate(name="العاصمة", country_id=country.id)
            db.add(gov)
            await db.flush() # +++ توليد الـ ID للمحافظة +++

        new_zone = Zone(company_id=current_admin.company_id, name=name, governorate_id=gov.id)
        db.add(new_zone)
        await db.flush() # +++ استخراج الـ ID للمنطقة بأمان قبل الـ Commit +++
        zone_id = new_zone.id
        
        await db.commit()
        return {"message": "تم إضافة المنطقة بنجاح", "zone_id": str(zone_id)}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء إضافة المنطقة.")


# =========================================
# 18. أرشفة المنطقة (مع حماية  ـ Rug-Pull ونسف الـ N+1)
# =========================================
@router.delete("/dispatch/zones/{zone_id}", status_code=200)
async def archive_zone(
    zone_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    stmt_zone = select(Zone).filter_by(
    id=zone_id,
    company_id=current_admin.company_id
    )
    zone = (await db.execute(stmt_zone)).scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=404, detail="المنطقة غير موجودة")

    # +++ الدرع المعماري (Rug-Pull Shield): منع سحب منطقة يعمل بها مندوب بالشارع +++
    stmt_active_routes = select(func.count(DispatchRoute.id)).filter(
        DispatchRoute.company_id == current_admin.company_id,
        DispatchRoute.zone_id == zone_id,
        DispatchRoute.status.in_(['active', 'waiting', 'postponed']) # +++ إضافة postponed +++
    )
    active_routes_count = (await db.execute(stmt_active_routes)).scalar() or 0

    if active_routes_count > 0:
        raise HTTPException(status_code=400, detail=f"مرفوض: يوجد خط سير نشط أو قيد الانتظار يعمل في منطقة ({zone.name}). يجب إغلاق خط السير أولاً.")

    try:
        # +++  لجريمة الـ N+1 (Cascade Archive O(1)) +++
        # تحديث آلاف المحلات بضربة واحدة في قاعدة البيانات بدون تحميلها في الذاكرة
        stmt_archive_shops = update(Shop).where(
            Shop.company_id == current_admin.company_id,
            Shop.zone_id == zone_id
        ).values(is_archived=True)
        await db.execute(stmt_archive_shops)
        
        # +++ الدرع المحاسبي الإضافي (الذي نسيته في الفلاسك): إلغاء أي زيارات معلقة لهذه المحلات المؤرشفة +++
        stmt_shop_ids = select(Shop.id).filter_by(
            company_id=current_admin.company_id,
            zone_id=zone_id
        ).scalar_subquery()
        stmt_cancel_visits = update(Visit).where(
            Visit.company_id == current_admin.company_id,
            Visit.shop_id.in_(stmt_shop_ids),
            Visit.status == 'Pending'
        ).values(status='Cancelled')
        await db.execute(stmt_cancel_visits)

        # أرشفة المنطقة نفسها
        zone.is_active = False
        
        await db.commit()
        return {"message": f"تم أرشفة المنطقة ({zone.name}) وجميع المحلات التابعة لها بنجاح"}

    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء أرشفة المنطقة.")


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
    

    # +++ قفل التزامن (Row-Level Lock) لمنع التضارب أثناء التعديل +++
    stmt_zone = select(Zone).with_for_update().filter_by(
        id=zone_id,
        company_id=current_admin.company_id
    )
    zone = (await db.execute(stmt_zone)).scalar_one_or_none()
    
    if not zone:
        await db.rollback()
        raise HTTPException(status_code=404, detail="المنطقة غير موجودة")

    new_name = payload.name.strip() if payload.name else None

    try:
        if new_name:
            stmt_exist = select(Zone).filter(
                Zone.company_id == current_admin.company_id,
                Zone.name == new_name,
                Zone.id != zone_id
            )
            if (await db.execute(stmt_exist)).first():
                await db.rollback() # +++ إغلاق تسريب الأقفال +++
                raise HTTPException(status_code=409, detail="يوجد منطقة أخرى بنفس الاسم")
            zone.name = new_name
            
        if payload.frequency:
            zone.schedule_frequency = payload.frequency
        if payload.visitDay:
            zone.visit_day = payload.visitDay
        if payload.startDate:
            # +++ Pydantic تكفل بتحويل التاريخ وحمايتنا من قنابل  ـ strptime +++
            zone.start_date = payload.startDate 
            
        await db.commit()
        return {"message": "تم التعديل بنجاح"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي أثناء تعديل المنطقة.")


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
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    stmt_zone = select(Zone).filter_by(
        id=zone_id,
        company_id=current_admin.company_id
    )
    zone = (await db.execute(stmt_zone)).scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=404, detail="المنطقة غير موجودة")

    # +++ درع إضافي: التحقق لكي لا نرهق الداتابيز بعملية Commit وهمية إذا كانت المنطقة نشطة أصلاً +++
    if getattr(zone, 'is_active', False):
        return {"message": "المنطقة نشطة بالفعل"}

    try:
        zone.is_active = True
        # +++  (B-03): استعادة جميع محلات المنطقة تلقائياً +++
        stmt_restore_shops = update(Shop).where(
            Shop.company_id == current_admin.company_id,
            Shop.zone_id == zone_id
)       .values(is_archived=False)
        await db.execute(stmt_restore_shops)
        
        await db.commit()
        return {"message": "تم استعادة المنطقة ومحلاتها بنجاح"}
        
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء استعادة المنطقة.")


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
    
        
    # 1. تنظيف المعرف القادم من React وحمايته من  ـ 500 Crash
    clean_id_str = str(shop_id).replace('s', '')
    if not clean_id_str.isdigit():
        raise HTTPException(status_code=400, detail="معرف المحل غير صالح.")
    clean_id = int(clean_id_str)

    # 2. الدرع المحاسبي: قفل المحل لمنع مسح مبيعات المندوب التي تحدث في نفس اللحظة (Row-Level Lock)
    stmt_shop = select(Shop).with_for_update().filter_by(
        id=clean_id,
        company_id=current_admin.company_id
    )
    shop = (await db.execute(stmt_shop)).scalar_one_or_none()
    
    if not shop:
        raise HTTPException(status_code=404, detail="المحل غير موجود")
        
    new_phone = payload.phone.strip() if payload.phone else ""
    
    # 3. فحص تكرار رقم الهاتف لمحل آخر لمنع التضارب
    if new_phone and new_phone != shop.phone_number:
        stmt_dup_phone = select(Shop).filter_by(
            company_id=current_admin.company_id,
            phone_number=new_phone
        )
        if (await db.execute(stmt_dup_phone)).first():
            await db.rollback()
            raise HTTPException(status_code=409, detail="رقم الهاتف مستخدم لمحل آخر")
            
    try:
        # 4. التحديث الجراحي للبيانات الأساسية (نحتفظ بالقديم إذا لم يتم إرسال جديد)
        if payload.name is not None:
            shop.name = payload.name
        if payload.owner is not None:
            shop.contact_person = payload.owner
            
        # حماية الهاتف من المسح العشوائي
        shop.phone_number = new_phone if new_phone else shop.phone_number
        
        if payload.mapLink is not None:
            shop.location_link = payload.mapLink
            
        if payload.zoneId is not None:
            zone_str = str(payload.zoneId).strip()

            if zone_str.isdigit():
                target_zone_id = int(zone_str)

                stmt_zone = select(Zone.id).filter_by(
                    id=target_zone_id,
                    company_id=current_admin.company_id,
                    is_active=True
                )
                zone_exists = (await db.execute(stmt_zone)).scalar_one_or_none()

                if zone_exists is None:
                    await db.rollback()
                    raise HTTPException(
                        status_code=400,
                        detail="المنطقة المحددة غير موجودة أو لا تتبع شركتك."
                    )

                shop.zone_id = target_zone_id
        
        # 5.   تحديث الأموال بـ Decimal نقي ومحمي من الفراغات (ونسف لغم الـ Falsy Zero)
        # +++ إصلاح AttributeError: alias يقبل camelCase في الإدخال فقط؛ الخاصية الفعلية max_debt_limit +++
        val_limit = payload.max_debt_limit
        if val_limit is not None:
            raw_limit = str(val_limit).strip()
            if raw_limit:  
                try:
                    new_limit = Decimal(raw_limit)
                    if new_limit < 0: raise ValueError()
                    shop.max_debt_limit = new_limit
                except Exception:
                    await db.rollback()
                    raise HTTPException(status_code=400, detail="سقف الدين يجب أن يكون رقماً موجباً.")
                
        val_debt = payload.initial_debt
        if val_debt is not None:
            raw_debt = str(val_debt).strip()
            if raw_debt:
                try:
                    new_balance = Decimal(raw_debt)
                    if new_balance < 0: raise ValueError()
                    old_balance = shop.current_balance or Decimal('0.0')
                    if new_balance != old_balance:
                        shop.current_balance = new_balance
                        # +++ الدرع الرقابي: توثيق أي تعديل يدوي على رصيد المحل +++
                        db.add(SystemAuditLog(
                            company_id=current_admin.company_id,
                            admin_id=current_admin.id,
                            target_id=f"Shop_{shop.id}",
                            action_type="SHOP_BALANCE_MANUAL_EDIT",
                            old_value=str(old_balance),
                            new_value=f"الرصيد الجديد: {new_balance} (تعديل يدوي من لوحة التحكم)"
                        ))
                except Exception:
                    await db.rollback()
                    raise HTTPException(status_code=400, detail="الرصيد يجب أن يكون رقماً موجباً صريحاً.")
        
        await db.commit()
        return {"message": "تم التعديل بنجاح"}
        
    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"خطأ تعارض (FK): {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail="فشل الحفظ: تأكد من أن المنطقة المحددة أو البيانات صالحة.")
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء تعديل المحل.")


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
    current_admin: Driver = Depends(get_current_admin)
):
    

    if not payload:
        raise HTTPException(status_code=400, detail="لا توجد بيانات لإضافتها.")

    try:
        # +++ 1. تحضير الذاكرة (Memory Maps) لنسف  ـ N+1 +++
        shop_ids = list({int(str(item.shopId).strip()) for item in payload if str(item.shopId).strip().isdigit()})
        
        # +++ الدرع الميداني: تجاهل المحلات المؤرشفة تماماً لمنع خلق زيارات أشباح +++
        stmt_shops = select(Shop).filter(
            Shop.company_id == current_admin.company_id,
            Shop.id.in_(shop_ids),
            Shop.is_archived == False
        )
        bulk_shops = {sh.id: sh for sh in (await db.execute(stmt_shops)).scalars().all()}
        # تحديث قائمة shop_ids بناءً على المحلات النشطة فقط
        shop_ids = list(bulk_shops.keys())
        
        if not shop_ids:
            return {"message": "لا توجد محلات صالحة لإضافة الطلبات (أو أنها مؤرشفة)."}
        
        # +++  الحقيقي: توحيد Naive UTC لمنع تعارض قواعد البيانات +++
        today_start = get_utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        # جلب زيارات اليوم (المعلقة أو المكتملة) لوسمها بالطوارئ
        # +++ قفل الزيارة لمنع المندوب من إنهائها أثناء وسمها بالطوارئ +++
        stmt_visits = select(Visit).with_for_update().filter(
            Visit.company_id == current_admin.company_id,
            Visit.shop_id.in_(shop_ids),
            or_(
                Visit.status == 'Pending',
                and_(Visit.visit_timestamp >= today_start, Visit.visit_timestamp < today_end)
            )
        ).order_by(Visit.id.asc())
        recent_visits = (await db.execute(stmt_visits)).scalars().all()
        bulk_visits = {v.shop_id: v for v in recent_visits} 
        
        # حماية الطلبات العاجلة المتعددة (جلب الطلبات القديمة)
        stmt_existing_reqs = select(ShortageRequest).options(
            joinedload(ShortageRequest.shop)
        ).filter(
            ShortageRequest.company_id == current_admin.company_id,
            ShortageRequest.shop_id.in_(shop_ids),
            ShortageRequest.status == 'pending'
        )
        existing_requests_map = {req.shop_id: req for req in (await db.execute(stmt_existing_reqs)).scalars().all()}

        # +++ سحق اصطدام الأسماء: الاعتماد على الـ ID أولاً، ثم الاسم كخيار بديل +++
        product_ids = list({int(str(item.productId).strip()) for item in payload if str(item.productId).strip().isdigit()})
        product_names = list({str(item.productName).strip() for item in payload if item.productName and not str(item.productId).strip().isdigit()})
        
        stmt_vars = select(ProductVariant).filter(
            ProductVariant.company_id == current_admin.company_id,
            or_(
                ProductVariant.id.in_(product_ids),
                ProductVariant.variant_name.in_(product_names)
            )
        )
        fetched_variants = (await db.execute(stmt_vars)).scalars().all()
        bulk_variants_map_id = {v.id: v for v in fetched_variants}
        bulk_variants_map_name = {v.variant_name: v for v in fetched_variants}
        zone_ids = list({
            int(str(item.zoneId).strip())
            for item in payload
            if str(item.zoneId).strip().isdigit()
        })

        driver_ids = list({
            int(str(item.driverId).strip())
            for item in payload
            if item.driverId and str(item.driverId).strip().isdigit()
        })

        valid_zone_ids = set()
        if zone_ids:
            stmt_zones = select(Zone.id).filter(
                Zone.company_id == current_admin.company_id,
                Zone.id.in_(zone_ids),
                Zone.is_active == True
            )
            valid_zone_ids = set((await db.execute(stmt_zones)).scalars().all())

        valid_driver_ids = set()
        if driver_ids:
            stmt_drivers = select(Driver.id).filter(
                Driver.company_id == current_admin.company_id,
                Driver.id.in_(driver_ids),
                Driver.is_active == True
            )
            valid_driver_ids = set((await db.execute(stmt_drivers)).scalars().all())

        # درع لمنع إرسال نفس المنتج مرتين بالخطأ في نفس الـ Payload
        payload_tracker = set()

        # +++ 2. المعالجة الجراحية +++
        for item in payload:
            shop_id_str = str(item.shopId).strip()
            if not shop_id_str.isdigit(): continue
            shop_id = int(shop_id_str)
            
            # الرفض إذا كان هناك طلب قديم معلق لهذا المحل
            if shop_id in existing_requests_map:
                req = existing_requests_map[shop_id]
                shop_name = req.shop.name if req.shop else str(shop_id)
                await db.rollback()
                raise HTTPException(status_code=409, detail=f"مرفوض: يوجد طلب عاجل قيد الانتظار للمحل ({shop_name}). يرجى تعديله أو حذفه أولاً.")

            prod_id_str = str(item.productId).strip()
            prod_name = str(item.productName).strip()
            variant = None
            
            if prod_id_str.isdigit(): variant = bulk_variants_map_id.get(int(prod_id_str))
            if not variant and prod_name: variant = bulk_variants_map_name.get(prod_name)
            
            if not variant:
                await db.rollback()
                raise HTTPException(status_code=404, detail=f"المنتج '{prod_name or prod_id_str}' غير موجود في النظام.")
                
            tracker_key = f"{shop_id}_{variant.id}"
            if tracker_key in payload_tracker: continue 
            payload_tracker.add(tracker_key)

            zone_id_str = str(item.zoneId).strip()
            if not zone_id_str.isdigit():
                await db.rollback()
                raise HTTPException(status_code=400, detail="مرفوض: المنطقة إجبارية للطلب العاجل.")
            zone_id = int(zone_id_str)
            if zone_id not in valid_zone_ids:
                await db.rollback()
                raise HTTPException(
                    status_code=400,
                    detail="المنطقة المحددة للطلب العاجل غير موجودة أو لا تتبع شركتك."
                )

            driver_id_str = str(item.driverId).strip() if item.driverId else ""
            driver_id = int(driver_id_str) if driver_id_str.isdigit() else None
            if driver_id is not None and driver_id not in valid_driver_ids:
                await db.rollback()
                raise HTTPException(
                    status_code=400,
                    detail="المندوب المحدد غير موجود أو لا يتبع شركتك."
                )

            # أ. إنشاء الطلب
            new_shortage = ShortageRequest(
                company_id=current_admin.company_id,
                zone_id=zone_id,
                shop_id=shop_id,
                driver_id=driver_id,
                product_variant_id=variant.id, 
                quantity=item.quantity or 1
            )
            db.add(new_shortage)
            
            # ب. دمج الزيارة والتفويض (التبني) - (معمارية حماية الأموال المكتملة)
            if driver_id:
                existing_visit = bulk_visits.get(shop_id)
                if existing_visit:
                    if existing_visit.driver_id == driver_id:
                        # نفس المندوب: نكتفي بختم الطوارئ
                        existing_visit.is_emergency = True
                        # +++ درع الزومبي: إحياء الزيارة إذا كان المندوب قد ألغاها صباحاً +++
                        if existing_visit.status == 'Cancelled':
                            existing_visit.status = 'Pending'
                    else:
                        # مندوب مختلف: هنا الخطر!
                        if existing_visit.status == 'Completed':
                            # +++ درع الفساد المالي: يمنع سرقة زيارة مكتملة، بل ننشئ زيارة جديدة للمندوب الجديد +++
                            shop_record = bulk_shops.get(shop_id)
                            new_visit = Visit(
                                company_id=current_admin.company_id,
                                driver_id=driver_id,
                                shop_id=shop_id,
                                status='Pending',
                                sequence=shop_record.sequence if shop_record else 999,
                                is_emergency=True
                            )
                            db.add(new_visit)
                            # نحدث الذاكرة لتشير للزيارة الجديدة في حال تكرر المحل في نفس الطلب
                            bulk_visits[shop_id] = new_visit
                        else:
                            # الزيارة معلقة (Pending) أو ملغاة (Cancelled): يمكن نقلها بأمان
                            existing_visit.is_emergency = True
                            existing_visit.driver_id = driver_id
                            existing_visit.work_session_id = None
                            existing_visit.status = 'Pending' # +++ إحياء الزيارة للمندوب الجديد +++
                else:
                    shop_record = bulk_shops.get(shop_id)
                    new_visit = Visit(
                        company_id=current_admin.company_id,
                        driver_id=driver_id,
                        shop_id=shop_id,
                        status='Pending',
                        sequence=shop_record.sequence if shop_record else 999,
                        is_emergency=True
                    )
                    db.add(new_visit)
                    bulk_visits[shop_id] = new_visit 
                    
        await db.commit()
        asyncio.create_task(dispatch_manager.broadcast({"event": "SHORTAGE_ADDED", "message": "تم إضافة نواقص جديدة"}, company_id=current_admin.company_id))
        return {"message": "تم تسجيل الطلبات بنجاح"}

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"خطأ تعارض (FK): {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail="فشل الحفظ: إحدى المناطق أو المندوبين غير مسجلة في النظام.")
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء حفظ الطلبات.")


# =========================================
# 25. حذف الطلب العاجل (وعملية تنظيف الأشباح) - DELETE
# =========================================
@router.delete("/dispatch/shortages/{shortage_id}", status_code=200)
async def delete_shortage(
    shortage_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    stmt_shortage = select(ShortageRequest).filter_by(
        id=shortage_id,
        company_id=current_admin.company_id
    )
    shortage = (await db.execute(stmt_shortage)).scalar_one_or_none()
    if not shortage:
        return {"message": "الطلب غير موجود أصلاً."}

    try:
        shop_id = shortage.shop_id
        await db.delete(shortage)
        await db.flush() # +++ تحديث الذاكرة فوراً قبل فحص المتبقي +++
        
        # +++ التزامن المعماري: سحب ختم (عاجل) إذا لم يتبقَ أي طلبات أخرى +++
        stmt_rem = select(func.count(ShortageRequest.id)).filter_by(
            company_id=current_admin.company_id,
            shop_id=shop_id,
            status='pending'
        )
        remaining = (await db.execute(stmt_rem)).scalar() or 0
        
        if remaining == 0:
            stmt_visit = select(Visit).filter_by(
                company_id=current_admin.company_id,
                shop_id=shop_id,
                status='Pending'
            ).limit(1)
            target_visit = (await db.execute(stmt_visit)).scalars().first()
            
            if target_visit:
                target_visit.is_emergency = False
                
                # +++ نسف الشبح: إذا كان المحل خارج منطقة المندوب (أضيف للطوارئ فقط)، نسحبه منه لكي لا يعلق الشبح في تطبيقه +++
                if target_visit.driver_id:
                    stmt_route = select(DispatchRoute).filter_by(
                        company_id=current_admin.company_id,
                        driver_id=target_visit.driver_id,
                        status='active'
                    ).limit(1)
                    route = (await db.execute(stmt_route)).scalars().first()
                    stmt_shop = select(Shop).filter_by(
                        id=shop_id,
                        company_id=current_admin.company_id
                    )
                    shop = (await db.execute(stmt_shop)).scalar_one_or_none()
                    
                    if route and shop and shop.zone_id != route.zone_id:
                        target_visit.driver_id = None
                        target_visit.work_session_id = None
        
        await db.commit()
        asyncio.create_task(dispatch_manager.broadcast({"event": "SHORTAGE_DELETED", "message": "تم معالجة نواقص"}, company_id=current_admin.company_id))
        return {"message": "تم حذف الطلب وتنظيف الميدان بنجاح"}
        
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي أثناء حذف الطلب.")


# =========================================
# 26. الاستيراد الآمن للمحلات بالجملة (Bulk Import O(1) & Memory Safe)
# =========================================
@router.post("/dispatch/shops/bulk_import", status_code=201)
async def bulk_import_shops(
    payload: BulkImportRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    zone_id = payload.zoneId
    shops_list = payload.shops
    file_name = payload.fileName

    if not zone_id or not shops_list:
        raise HTTPException(status_code=400, detail="المنطقة وقائمة المحلات مطلوبة")
    stmt_zone = select(Zone.id).filter_by(
        id=zone_id,
        company_id=current_admin.company_id,
        is_active=True
    )
    zone_exists = (await db.execute(stmt_zone)).scalar_one_or_none()

    if zone_exists is None:
        raise HTTPException(
            status_code=400,
            detail="المنطقة المحددة غير موجودة أو لا تتبع شركتك."
        )
    log_id = None
    try:
        # ========================================================
        # 1. توثيق العملية مبدئياً وحجز ID للـ Log
        # ========================================================
        import_log = ImportLog(
            company_id=current_admin.company_id,
            admin_id=current_admin.id, 
            zone_id=zone_id, 
            file_name=file_name, 
            total_records=len(shops_list), 
            status='Processing'
        )
        db.add(import_log)
        await db.flush() # +++ الدرع الفولاذي: سحب الـ ID من الداتابيز قبل إغلاق الجلسة لمنع الانفجار +++
        log_id = import_log.id
        await db.commit()

        # ========================================================
        # 2. تحضير القوائم الفريدة (Sets) للسرعة
        # ========================================================
        incoming_names = list({s.name.strip().lower() for s in shops_list if s.name and s.name.strip()})
        # +++ درع الإكسيل: إزالة الـ .0 من الهواتف قبل بناء فهارس البحث +++
        incoming_phones = list({(str(s.phone).strip()[:-2] if str(s.phone).strip().endswith('.0') else str(s.phone).strip()) for s in shops_list if s.phone and str(s.phone).strip()})
        incoming_links = list({s.mapLink.strip().lower() for s in shops_list if s.mapLink and s.mapLink.strip()})

        all_existing_shops_raw = []
        CHUNK_SIZE = 500 # التوازن المثالي لمنع انفجار الـ RAM و Timeout الداتابيز

        # ========================================================
        # 3. هندسة الطلب الموحد (Chunked Bulk Fetch O(1))
        # ========================================================
        max_len = max(len(incoming_names), len(incoming_phones), len(incoming_links))
        for i in range(0, max_len, CHUNK_SIZE):
            name_chunk = incoming_names[i:i + CHUNK_SIZE]
            phone_chunk = incoming_phones[i:i + CHUNK_SIZE]
            link_chunk = incoming_links[i:i + CHUNK_SIZE]

            filters = []
            if name_chunk: filters.append(func.lower(Shop.name).in_(name_chunk))
            if phone_chunk: filters.append(Shop.phone_number.in_(phone_chunk))
            if link_chunk: filters.append(func.lower(Shop.location_link).in_(link_chunk))

            if filters:
                # جلب الحقول المطلوبة فقط (Tuples) لنسف الـ Memory Bloat
                stmt = select(Shop.id, Shop.name, Shop.phone_number, Shop.location_link).filter(
                    Shop.company_id == current_admin.company_id,
                    Shop.is_archived == False,
                    or_(*filters)
                )
                results = (await db.execute(stmt)).all()
                all_existing_shops_raw.extend(results)

        # إزالة التكرار من النتائج
        all_existing_shops = list({res[0]: res for res in all_existing_shops_raw}.values())

        # ========================================================
        # 4. بناء الـ Hash Maps للمقارنة الفورية O(1)
        # ========================================================
        name_idx, phone_idx, link_idx = {}, {}, {}
        for ext_id, ext_name, ext_phone, ext_link in all_existing_shops:
            n = (ext_name or '').strip().lower()
            p = str(ext_phone or '').strip()
            l = (ext_link or '').strip().lower()
            if n: name_idx.setdefault(n, []).append(ext_id)
            if p: phone_idx.setdefault(p, []).append(ext_id)
            if l: link_idx.setdefault(l, []).append(ext_id)

        new_shops = []
        ignored_count = 0

        # ========================================================
        # 5. المعالجة النهائية والحماية من التكرار الداخلي (Intra-Excel)
        # ========================================================
        for s in shops_list:
            s_name = (s.name or '').strip().lower()
            s_phone = str(s.phone or '').strip()
            if s_phone.endswith('.0'): s_phone = s_phone[:-2] # +++ تنظيف الهاتف قبل الإدخال +++
            s_link = (s.mapLink or '').strip().lower()

            candidate_ids = []
            if s_name in name_idx: candidate_ids.extend(name_idx[s_name])
            if s_phone in phone_idx: candidate_ids.extend(phone_idx[s_phone])
            if s_link in link_idx: candidate_ids.extend(link_idx[s_link])
            
            # درع منع التكرار القاطع
            is_phone_duplicate = bool(s_phone and s_phone in phone_idx)
            is_duplicate = is_phone_duplicate or any(count >= 2 for count in Counter(candidate_ids).values())
            
            if is_duplicate:
                ignored_count += 1
                continue

            # +++ حماية  ـ Decimal من انهيار البيانات (Empty Strings or Chars) +++
            try:
                raw_debt = str(s.initialDebt or '0.0').strip()
                safe_debt = Decimal(raw_debt) if raw_debt else Decimal('0.0')
            except Exception:
                safe_debt = Decimal('0.0')

            try:
                # +++  (B-06): حماية الصفر (0) من اعتباره Falsy Value +++
                raw_seq = str(s.sequence).strip() if s.sequence is not None else '999'
                safe_seq = int(float(raw_seq)) 
            except Exception:
                safe_seq = 999

            new_shop = Shop(
                company_id=current_admin.company_id,
                name=(s.name or '').strip(),
                contact_person=(s.owner or '').strip(),
                phone_number=s_phone,
                location_link=(s.mapLink or '').strip(),
                zone_id=zone_id,
                is_active=True,
                is_archived=False, # 👈 إجبار القيمة لتفادي جدار الـ NULL في استعلامات SQL
                current_balance=max(Decimal('0.0'), safe_debt),
                added_by_driver_id=current_admin.id,
                sequence=safe_seq
            )
            new_shops.append(new_shop)
            
            # +++ تحديث الذاكرة فوراً لمنع التكرار داخل الإكسيل نفسه (Self-Healing) +++
            temp_id = f"temp_{len(new_shops)}"
            if s_name: name_idx.setdefault(s_name, []).append(temp_id)
            if s_phone: phone_idx.setdefault(s_phone, []).append(temp_id)
            if s_link: link_idx.setdefault(s_link, []).append(temp_id)

        # إضافة كل المحلات دفعة واحدة للـ DB
        db.add_all(new_shops)
        
        # جلب الـ Log لتحديثه
        stmt_log = select(ImportLog).filter_by(
            id=log_id,
            company_id=current_admin.company_id
        )
        current_log = (await db.execute(stmt_log)).scalar_one_or_none()
        if current_log:
            current_log.success_count = len(new_shops)
            current_log.status = 'Success'
            
        await db.commit()
        
        return {"message": f"تم رفع {len(new_shops)} محل بنجاح، وتجاهل {ignored_count} مكرر."}

    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        
        # +++ المعالجة الانفصالية للطوارئ: تحديث حالة الـ Log بمعاملة جديدة +++
        if log_id:
            try:
                stmt_fail = update(ImportLog).where(
                    ImportLog.id == log_id,
                    ImportLog.company_id == current_admin.company_id
                ).values(status='Failed')
                await db.execute(stmt_fail)
                await db.commit()
            except Exception:
                await db.rollback()

        raise HTTPException(status_code=500, detail="فشل في رفع البيانات، تم إلغاء العملية بالكامل لحماية قاعدة البيانات.")
