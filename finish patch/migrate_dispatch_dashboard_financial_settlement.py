from __future__ import annotations

from pathlib import Path
import ast
import shutil
import re

ROOT = Path.cwd()
TARGET = ROOT / "wa_backend" / "api" / "dispatch.py"
BACKUP_DIR = ROOT / ".patch_backups" / "DISPATCH_DASHBOARD_FINANCIAL_SETTLEMENT"
CORE_MARKER = "# PATCH: DISPATCH_UNIFIED_INVENTORY_CORE"
MARKER = "# PATCH: DISPATCH_DASHBOARD_FINANCIAL_SETTLEMENT"


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
    print("DISPATCH_DASHBOARD_FINANCIAL_SETTLEMENT_ALREADY_OK")
    raise SystemExit(0)
if CORE_MARKER not in text:
    fail("Phase 1 unified inventory core marker is missing; run migrate_dispatch_unified_inventory_core.py first")

# Phase 1 added this compact import block. Extend it; do not touch frozen model/service files.
imports_old = '''from models import (
    InventoryBalance,
    InventoryTransferHeader,
    InventoryTransferLine,
    DispatchLoadPlanLine,
    ProductBatch,
)
'''
imports_new = '''from models import (
    InventoryBalance,
    InventoryTransferHeader,
    InventoryTransferLine,
    DispatchLoadPlanLine,
    ProductBatch,
    InventoryMovement,
    SessionInventorySnapshot,
)
'''
text = replace_once(text, imports_old, imports_new, "unified model imports")

section2_start = "# =========================================\n# 2. جلب ملخص كل الجلسات"
section3_start = "# =========================================\n# 3. تقرير التسوية اليومية"
section4_start = "# =========================================\n# 4. اعتماد التسوية اليومية"
section5_start = "# =========================================\n# 5. تهيئة شاشة التوزيع"
section16_start = "# =========================================\n# 16. تراجع عن إنهاء العمل"
section17_start = "# =========================================\n# 17. إدارة المناطق"

section2_new = r'''# PATCH: DISPATCH_DASHBOARD_FINANCIAL_SETTLEMENT
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
'''
text = replace_section(text, section2_start, section3_start, section2_new, "section 2 dashboard")

section3_new = r'''# =========================================
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
'''
text = replace_section(text, section3_start, section4_start, section3_new, "section 3 report")

section4_new = r'''# =========================================
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
'''
text = replace_section(text, section4_start, section5_start, section4_new, "section 4 financial settlement")

section16_new = r'''# =========================================
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
'''
text = replace_section(text, section16_start, section17_start, section16_new, "section 16 undo end")

# Whole-file parse before touching disk.
try:
    ast.parse(text)
except SyntaxError as exc:
    fail(f"patched dispatch.py does not parse: {exc}")

# Critical postconditions for this phase.
phase2_start = text.index(MARKER)
phase2_end = text.index(section5_start, phase2_start)
phase2 = text[phase2_start:phase2_end]
for legacy in ("SessionInventory", "MainWarehouse", "VehicleLoad", "WarehouseLedger", "InventoryLedger", "DamagedItemLog"):
    if re.search(rf"\b{re.escape(legacy)}\b", phase2):
        fail(f"legacy inventory symbol still present in dashboard/financial phase: {legacy}")

required = [
    "SessionInventorySnapshot",
    "InventoryBalance",
    "InventoryMovement",
    "inventory_reconciled_at",
    'action_type="FINANCIAL_SETTLEMENT"',
    "DRIVER_SHORTAGE",
]
for needle in required:
    if needle not in phase2:
        fail(f"required phase-2 invariant missing: {needle}")

undo_start = text.index(section16_start)
undo_end = text.index(section17_start, undo_start)
undo_block = text[undo_start:undo_end]
if "inventory_reconciled_at" not in undo_block:
    fail("undo_end_work does not block inventory-reconciled sessions")

BACKUP_DIR.mkdir(parents=True, exist_ok=True)
backup = BACKUP_DIR / "dispatch.py.before_dashboard_financial_settlement"
if not backup.exists():
    shutil.copy2(TARGET, backup)

TARGET.write_text(text, encoding="utf-8", newline="\n")

print("DISPATCH_DASHBOARD_FINANCIAL_SETTLEMENT_OK")
print("DASHBOARD_OK: SessionInventory removed from admin projections; Snapshot + Balance + Movement only")
print("LOCAL_DATE_OK: dashboard uses WorkSession.session_date + company-local date")
print("REPORT_OK: historical inventory comes from SessionInventorySnapshot; live inventory from InventoryBalance")
print("FINANCE_SPLIT_OK: settle_session is financial-only and requires inventory_reconciled_at")
print("SHORTAGE_CASH_OK: DRIVER_SHORTAGE value remains part of expected financial settlement")
print("ROUTE_HISTORY_OK: financial settlement never clears route.work_session_id")
print("UNDO_END_OK: session cannot reopen after inventory reconciliation")
print("FILE_CHANGED: wa_backend/api/dispatch.py only")
print("NEXT: py_compile + git diff --check, then migrate update_route_status and final legacy cleanup")
