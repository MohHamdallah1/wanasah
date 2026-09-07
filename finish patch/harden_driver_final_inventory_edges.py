from __future__ import annotations

import ast
import hashlib
import shutil
import sys
from pathlib import Path

PATCH_NAME = "DRIVER_FINAL_INVENTORY_EDGES"


def abort(msg: str) -> None:
    raise SystemExit(f"PATCH_ABORT: {msg}")


def find_project_root() -> Path:
    cwd = Path.cwd().resolve()
    candidates = [cwd, *cwd.parents]
    for root in candidates:
        if (root / "wa_backend" / "api" / "driver.py").is_file():
            return root
    abort("لم أجد wa_backend/api/driver.py. شغّل الباتش من جذر المشروع.")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_atomic(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp_patch")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    tmp.replace(path)


def replace_function(src: str, name: str, replacement: str) -> str:
    tree = ast.parse(src)
    matches = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    ]
    if len(matches) != 1:
        abort(f"تعذر تحديد الدالة {name} بشكل وحيد (وجدت {len(matches)}).")
    node = matches[0]
    lines = src.splitlines(keepends=True)
    start = node.lineno - 1
    end = node.end_lineno
    new = replacement.rstrip() + "\n"
    return "".join(lines[:start]) + new + "".join(lines[end:])


def function_source(src: str, name: str) -> str:
    tree = ast.parse(src)
    matches = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    ]
    if len(matches) != 1:
        abort(f"تعذر قراءة الدالة {name} بشكل وحيد.")
    node = matches[0]
    lines = src.splitlines()
    return "\n".join(lines[node.lineno - 1: node.end_lineno])


def must_replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        abort(f"{label}: توقعت تطابقاً واحداً ووجدت {count}.")
    return text.replace(old, new, 1)


def patch_start_session(src: str) -> str:
    fn = function_source(src, "start_work_session")
    if "dispatch_date=company_local_date" in fn and fn.count("get_company_local_date") == 1:
        return src

    anchor = '''        # لا يوم جديد قبل تسوية العهدة السابقة.\n'''
    insertion = '''        # تاريخ العمل يُحسم بتوقيت الشركة قبل اختيار Route؛ لا نقبل Route قديم بقي active بالخطأ.\n        company_local_date = await get_company_local_date(db, company_id)\n\n        # لا يوم جديد قبل تسوية العهدة السابقة.\n'''
    fn = must_replace_once(fn, anchor, insertion, "start_work_session local date")

    old_route = '''                    driver_id=driver_id,\n                    status="active",\n'''
    new_route = '''                    driver_id=driver_id,\n                    dispatch_date=company_local_date,\n                    status="active",\n'''
    fn = must_replace_once(fn, old_route, new_route, "start_work_session route date")

    old_late_date = '''        company_local_date = await get_company_local_date(\n            db,\n            company_id,\n        )\n\n'''
    fn = must_replace_once(fn, old_late_date, "", "start_work_session duplicate local date")

    old_opening = '''        opening_rows = (\n            await db.execute(\n                select(\n                    InventoryBalance.product_variant_id,\n                    func.sum(InventoryBalance.on_hand_quantity),\n                )\n                .filter(\n                    InventoryBalance.company_id == company_id,\n                    InventoryBalance.location_id == vehicle_location_id,\n                    InventoryBalance.on_hand_quantity > 0,\n                )\n                .group_by(InventoryBalance.product_variant_id)\n                .order_by(InventoryBalance.product_variant_id.asc())\n            )\n        ).all()\n\n        for product_variant_id, starting_quantity in opening_rows:\n            qty = int(starting_quantity or 0)\n\n            if qty < 0 or qty > 2_147_483_647:\n                raise RuntimeError(\n                    "Vehicle opening inventory exceeds SessionInventorySnapshot INTEGER bounds."\n                )\n\n            db.add(\n                SessionInventorySnapshot(\n                    company_id=company_id,\n                    work_session_id=new_session.id,\n                    location_id=vehicle_location_id,\n                    product_variant_id=product_variant_id,\n                    starting_quantity=qty,\n                )\n            )\n'''
    new_opening = '''        opening_rows = (\n            await db.execute(\n                select(\n                    InventoryBalance.product_variant_id,\n                    InventoryBalance.stock_status,\n                    func.sum(InventoryBalance.on_hand_quantity),\n                )\n                .filter(\n                    InventoryBalance.company_id == company_id,\n                    InventoryBalance.location_id == vehicle_location_id,\n                    InventoryBalance.on_hand_quantity > 0,\n                )\n                .group_by(\n                    InventoryBalance.product_variant_id,\n                    InventoryBalance.stock_status,\n                )\n                .order_by(\n                    InventoryBalance.product_variant_id.asc(),\n                    InventoryBalance.stock_status.asc(),\n                )\n            )\n        ).all()\n\n        for product_variant_id, stock_status, starting_quantity in opening_rows:\n            qty = int(starting_quantity or 0)\n            normalized_status = str(stock_status or "").upper()\n\n            if normalized_status not in {"AVAILABLE", "DAMAGED"}:\n                raise RuntimeError("Vehicle opening inventory has unsupported stock_status.")\n            if qty < 0 or qty > 2_147_483_647:\n                raise RuntimeError(\n                    "Vehicle opening inventory exceeds SessionInventorySnapshot INTEGER bounds."\n                )\n\n            db.add(\n                SessionInventorySnapshot(\n                    company_id=company_id,\n                    work_session_id=new_session.id,\n                    location_id=vehicle_location_id,\n                    product_variant_id=product_variant_id,\n                    stock_status=normalized_status,\n                    starting_quantity=qty,\n                )\n            )\n'''
    if old_opening in fn:
        fn = fn.replace(old_opening, new_opening, 1)
    elif "InventoryBalance.stock_status" not in fn or "stock_status=normalized_status" not in fn:
        abort("start_work_session opening snapshot لا يطابق النسخة المتوقعة.")

    old_exc = '''    except HTTPException:\n        raise\n'''
    new_exc = '''    except HTTPException:\n        await db.rollback()\n        raise\n'''
    fn = must_replace_once(fn, old_exc, new_exc, "start_work_session rollback")
    return replace_function(src, "start_work_session", fn)


PROJECTION_FN = r'''async def _load_vehicle_inventory_projection(
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

    starting_map = {}
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

    return int(vehicle_location_id), projection'''


ROUTE_HELPER_FN = r'''async def _load_active_driver_route_and_vehicle_location(
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

    return route, int(vehicle_location_id)'''


VALIDATE_LOC_FN = r'''async def _validate_handshake_locations(
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
        raise HTTPException(status_code=409, detail=detail)'''


BATCH_LIFECYCLE_FN = r'''async def _validate_incoming_handshake_batches(
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
            )'''


def patch_helper_area(src: str) -> str:
    src = replace_function(src, "_load_vehicle_inventory_projection", PROJECTION_FN)
    src = replace_function(src, "_load_active_driver_route_and_vehicle_location", ROUTE_HELPER_FN)
    src = replace_function(src, "_validate_handshake_locations", VALIDATE_LOC_FN)
    if "async def _validate_incoming_handshake_batches(" not in src:
        marker = "\ndef _handshake_signed_quantity("
        if marker not in src:
            abort("لم أجد موضع إدراج فحص Batch للمصافحة.")
        src = src.replace(marker, "\n\n" + BATCH_LIFECYCLE_FN + "\n\n\ndef _handshake_signed_quantity(", 1)
    return src


def patch_update_visit(src: str) -> str:
    fn = function_source(src, "update_visit")

    old_hash = '''    canonical_payload = payload.model_dump(mode="json", exclude={"request_id"})\n    request_hash = hashlib.sha256(\n        json.dumps(\n            {"visit_id": visit_id, "payload": canonical_payload},\n            ensure_ascii=False,\n            sort_keys=True,\n            separators=(",", ":"),\n        ).encode("utf-8")\n    ).hexdigest()\n'''
    new_hash = '''    canonical_payload = payload.model_dump(mode="json", exclude={"request_id"})\n    # ترتيب أسطر Flutter ليس جزءاً من المعنى التجاري؛ retry مطابق لا يفشل لمجرد إعادة ترتيب القوائم.\n    canonical_payload["cart_items"] = sorted(\n        canonical_payload.get("cart_items", []),\n        key=lambda item: int(item["product_variant_id"]),\n    )\n    canonical_payload["returns"] = sorted(\n        canonical_payload.get("returns", []),\n        key=lambda item: (\n            int(item["product_variant_id"]),\n            int(item["batch_id"]),\n            str(item["return_type"]),\n        ),\n    )\n    request_hash = hashlib.sha256(\n        json.dumps(\n            {"visit_id": visit_id, "payload": canonical_payload},\n            ensure_ascii=False,\n            sort_keys=True,\n            separators=(",", ":"),\n        ).encode("utf-8")\n    ).hexdigest()\n'''
    if old_hash in fn:
        fn = fn.replace(old_hash, new_hash, 1)
    elif "canonical_payload[\"cart_items\"] = sorted" not in fn:
        abort("update_visit idempotency hash لا يطابق النسخة المتوقعة.")

    money_anchor = '''        fefo_allocations = {}\n        if outgoing_requests:\n'''
    money_insert = '''        # كل سطر مالي آمن منفرداً في calculate_invoice؛ هنا نحمي مجموع مئات الأسطر قبل PostgreSQL.\n        money_limit = Decimal("999999999.999")\n        for money_label, money_value in (\n            ("amount_before_tax_and_discount", total_base_amount),\n            ("discount_applied", total_discount),\n            ("tax_amount", total_tax),\n            ("final_amount_due", total_final_amount),\n        ):\n            if not money_value.is_finite() or money_value < 0 or money_value > money_limit:\n                raise HTTPException(\n                    status_code=400,\n                    detail=f"القيمة المجمعة ({money_label}) تتجاوز السعة المالية المسموحة.",\n                )\n\n        fefo_allocations = {}\n        if outgoing_requests:\n'''
    if "money_limit = Decimal(\"999999999.999\")" not in fn:
        if money_anchor in fn:
            fn = fn.replace(money_anchor, money_insert, 1)
        else:
            abort("تعذر إدراج حماية الإجماليات المالية في update_visit.")

    balance_anchor = '''            if new_balance < Decimal("0"):\n                raise HTTPException(\n                    status_code=400,\n                    detail=(\n                        "مرفوض محاسبياً: التحصيل أكبر من إجمالي الدين. "\n                        f"الرصيد سيصبح بالسالب ({new_balance})."\n                    ),\n                )\n            shop.current_balance = new_balance\n'''
    balance_new = '''            if new_balance < Decimal("0"):\n                raise HTTPException(\n                    status_code=400,\n                    detail=(\n                        "مرفوض محاسبياً: التحصيل أكبر من إجمالي الدين. "\n                        f"الرصيد سيصبح بالسالب ({new_balance})."\n                    ),\n                )\n            if not new_balance.is_finite() or new_balance > money_limit:\n                raise HTTPException(\n                    status_code=400,\n                    detail="الرصيد الناتج للمحل يتجاوز السعة المالية Numeric(12,3).",\n                )\n            shop.current_balance = new_balance\n'''
    if balance_anchor in fn:
        fn = fn.replace(balance_anchor, balance_new, 1)
    elif "الرصيد الناتج للمحل يتجاوز السعة المالية" not in fn:
        abort("تعذر إدراج حماية رصيد المحل.")

    return replace_function(src, "update_visit", fn)


def patch_dashboard(src: str) -> str:
    fn = function_source(src, "get_driver_dashboard")
    old_prefix = '''    active_route = (\n        await db.execute(\n            select(DispatchRoute)\n            .filter(\n                DispatchRoute.company_id == company_id,\n                DispatchRoute.driver_id == driver_id,\n                DispatchRoute.status.in_(["active", "waiting", "postponed"]),\n            )\n            .order_by(DispatchRoute.id.asc())\n            .limit(1)\n        )\n    ).scalars().first()\n\n    active_session = (\n        await db.execute(\n            select(WorkSession)\n            .filter_by(\n                company_id=company_id,\n                driver_id=driver_id,\n                end_time=None,\n            )\n            .order_by(WorkSession.id.desc())\n            .limit(1)\n        )\n    ).scalars().first()\n'''
    new_prefix = '''    active_session = (\n        await db.execute(\n            select(WorkSession)\n            .filter_by(\n                company_id=company_id,\n                driver_id=driver_id,\n                end_time=None,\n            )\n            .order_by(WorkSession.id.desc())\n            .limit(1)\n        )\n    ).scalars().first()\n\n    if active_session is not None:\n        # أثناء جلسة قائمة نعرض Route المرتبط بها حتى لو أوقفته الإدارة؛ البيع نفسه يبقى محظوراً إلا على active.\n        active_route = (\n            await db.execute(\n                select(DispatchRoute)\n                .filter_by(\n                    company_id=company_id,\n                    work_session_id=active_session.id,\n                    driver_id=driver_id,\n                )\n                .order_by(DispatchRoute.id.asc())\n                .limit(1)\n            )\n        ).scalars().first()\n    else:\n        company_local_date = await get_company_local_date(db, company_id)\n        active_route = (\n            await db.execute(\n                select(DispatchRoute)\n                .filter(\n                    DispatchRoute.company_id == company_id,\n                    DispatchRoute.driver_id == driver_id,\n                    DispatchRoute.dispatch_date == company_local_date,\n                    DispatchRoute.status.in_(["active", "waiting", "postponed"]),\n                )\n                .order_by(DispatchRoute.id.asc())\n                .limit(1)\n            )\n        ).scalars().first()\n'''
    if old_prefix in fn:
        fn = fn.replace(old_prefix, new_prefix, 1)
    elif "DispatchRoute.dispatch_date == company_local_date" not in fn:
        abort("Dashboard route projection لا يطابق النسخة المتوقعة.")
    return replace_function(src, "get_driver_dashboard", fn)


def patch_handshake_respond(src: str) -> str:
    fn = function_source(src, "respond_to_transfer")
    old_route = '''        _, vehicle_location_id = await _load_active_driver_route_and_vehicle_location(\n            db,\n            company_id=company_id,\n            driver_id=driver_id,\n            work_session_id=work_session.id,\n        )\n        await _validate_handshake_locations(\n            db,\n            company_id=company_id,\n            header=header,\n            vehicle_location_id=vehicle_location_id,\n        )\n\n        lines_by_header = await _load_handshake_lines_for_update(\n'''
    new_route = '''        vehicle_location_id = None\n        if response == "accepted":\n            _, vehicle_location_id = await _load_active_driver_route_and_vehicle_location(\n                db,\n                company_id=company_id,\n                driver_id=driver_id,\n                work_session_id=work_session.id,\n            )\n            await _validate_handshake_locations(\n                db,\n                company_id=company_id,\n                header=header,\n                vehicle_location_id=vehicle_location_id,\n            )\n        # الرفض لا يحتاج Route/وجهة فعالة؛ يجب أن يبقى ممكناً لتحرير الحجز وعدم تعليق المندوب.\n\n        lines_by_header = await _load_handshake_lines_for_update(\n'''
    if old_route in fn:
        fn = fn.replace(old_route, new_route, 1)
    elif "الرفض لا يحتاج Route/وجهة فعالة" not in fn:
        abort("respond_to_transfer route block غير متوقع.")

    old_variant_check = '''        # استلام جديد إلى السيارة لا يقبل صنفاً موقوفاً؛ السحب من السيارة يبقى مسموحاً.\n        if (\n            response == "accepted"\n            and int(header.destination_location_id) == vehicle_location_id\n            and not variant.is_active\n        ):\n            raise HTTPException(\n                status_code=400,\n                detail=f"لا يمكنك استلام حمولة جديدة من المنتج ({variant.variant_name}) لأنه موقوف حالياً.",\n            )\n\n        movement_specs = _build_handshake_movement_specs(\n'''
    new_variant_check = '''        # الاستلام AVAILABLE إلى السيارة يحتاج صنفاً وBatch صالحين لحظة القبول.\n        # هذا لا يغيّر مسار المرتجعات: VisitReturn يدخل DAMAGED فوراً حتى لو منتهي/موقوف.\n        if response == "accepted" and int(header.destination_location_id) == vehicle_location_id:\n            if not variant.is_active:\n                raise HTTPException(\n                    status_code=400,\n                    detail=f"لا يمكنك استلام حمولة جديدة من المنتج ({variant.variant_name}) لأنه موقوف حالياً.",\n                )\n            as_of_date = await get_company_local_date(db, company_id)\n            await _validate_incoming_handshake_batches(\n                db,\n                company_id=company_id,\n                header=header,\n                lines=lines,\n                vehicle_location_id=vehicle_location_id,\n                as_of_date=as_of_date,\n            )\n\n        movement_specs = _build_handshake_movement_specs(\n'''
    if old_variant_check in fn:
        fn = fn.replace(old_variant_check, new_variant_check, 1)
    elif "_validate_incoming_handshake_batches(" not in fn:
        abort("respond_to_transfer batch lifecycle block غير متوقع.")

    return replace_function(src, "respond_to_transfer", fn)


def patch_handshake_batch(src: str) -> str:
    fn = function_source(src, "batch_respond_to_transfers")

    old_session_route = '''            _, vehicle_location_id = await _load_active_driver_route_and_vehicle_location(\n                db,\n                company_id=company_id,\n                driver_id=driver_id,\n                work_session_id=work_session_id,\n            )\n\n            for header in pending_headers:\n                await _validate_handshake_locations(\n                    db,\n                    company_id=company_id,\n                    header=header,\n                    vehicle_location_id=vehicle_location_id,\n                )\n\n            pending_ids = [int(header.id) for header in pending_headers]\n'''
    new_session_route = '''            accepted_headers = [\n                header\n                for header in pending_headers\n                if request_map[int(header.id)].status == "accepted"\n            ]\n            vehicle_location_id = None\n            if accepted_headers:\n                _, vehicle_location_id = await _load_active_driver_route_and_vehicle_location(\n                    db,\n                    company_id=company_id,\n                    driver_id=driver_id,\n                    work_session_id=work_session_id,\n                )\n                for header in accepted_headers:\n                    await _validate_handshake_locations(\n                        db,\n                        company_id=company_id,\n                        header=header,\n                        vehicle_location_id=vehicle_location_id,\n                    )\n            # المصافحات المرفوضة لا تعتمد على استمرار Route/الوجهة؛ الرفض يحرر الحجز فقط.\n\n            pending_ids = [int(header.id) for header in pending_headers]\n'''
    if old_session_route in fn:
        fn = fn.replace(old_session_route, new_session_route, 1)
    elif "المصافحات المرفوضة لا تعتمد" not in fn:
        abort("batch_respond route block غير متوقع.")

    old_loop_start = '''            movement_specs = []\n            now_utc = get_utc_now()\n            for header in pending_headers:\n'''
    new_loop_start = '''            movement_specs = []\n            now_utc = get_utc_now()\n            as_of_date = (\n                await get_company_local_date(db, company_id)\n                if accepted_headers\n                else None\n            )\n            for header in pending_headers:\n'''
    if old_loop_start in fn:
        fn = fn.replace(old_loop_start, new_loop_start, 1)
    elif "if accepted_headers\n                else None" not in fn:
        abort("batch_respond as_of_date insertion failed.")

    old_variant = '''                if (\n                    accepted\n                    and int(header.destination_location_id) == vehicle_location_id\n                    and not variant.is_active\n                ):\n                    raise HTTPException(\n                        status_code=400,\n                        detail=f"مرفوض في الحوالة ({header.id}): المنتج ({variant.variant_name}) موقوف حالياً.",\n                    )\n\n                movement_specs.extend(\n'''
    new_variant = '''                if accepted and int(header.destination_location_id) == vehicle_location_id:\n                    if not variant.is_active:\n                        raise HTTPException(\n                            status_code=400,\n                            detail=f"مرفوض في الحوالة ({header.id}): المنتج ({variant.variant_name}) موقوف حالياً.",\n                        )\n                    await _validate_incoming_handshake_batches(\n                        db,\n                        company_id=company_id,\n                        header=header,\n                        lines=lines,\n                        vehicle_location_id=vehicle_location_id,\n                        as_of_date=as_of_date,\n                    )\n\n                movement_specs.extend(\n'''
    if old_variant in fn:
        fn = fn.replace(old_variant, new_variant, 1)
    elif "await _validate_incoming_handshake_batches(" not in fn:
        abort("batch_respond lifecycle insertion failed.")

    return replace_function(src, "batch_respond_to_transfers", fn)


def patch_pending(src: str) -> str:
    fn = function_source(src, "get_pending_transfers")
    old_helper = '''    _, vehicle_location_id = await _load_active_driver_route_and_vehicle_location(\n        db,\n        company_id=company_id,\n        driver_id=driver_id,\n        work_session_id=active_session.id,\n    )\n'''
    new_helper = '''    _, vehicle_location_id = await _load_active_driver_route_and_vehicle_location(\n        db,\n        company_id=company_id,\n        driver_id=driver_id,\n        work_session_id=active_session.id,\n        require_active_route=False,\n        require_active_vehicle_location=False,\n    )\n'''
    if old_helper in fn:
        fn = fn.replace(old_helper, new_helper, 1)

    old_valid = '''            vehicle_location_id=vehicle_location_id,\n        )\n'''
    new_valid = '''            vehicle_location_id=vehicle_location_id,\n            require_active_warehouse=False,\n        )\n'''
    # Only one validation call in this endpoint.
    if "require_active_warehouse=False" not in fn:
        fn = must_replace_once(fn, old_valid, new_valid, "get_pending_transfers inactive cleanup")
    return replace_function(src, "get_pending_transfers", fn)


def patch_add_shop(src: str) -> str:
    fn = function_source(src, "add_new_shop")
    if "shop-phone:" in fn:
        return src
    old = '''    stmt_dup = select(Shop).filter_by(company_id=current_driver.company_id, phone_number=clean_phone)\n    existing_shop = (await db.execute(stmt_dup)).scalars().first()\n    if existing_shop:\n        raise HTTPException(status_code=409, detail=f"فشل الحفظ: رقم الهاتف مسجل مسبقاً للمحل ({existing_shop.name}).")\n'''
    new = '''    # نفس الهاتف قرار uniqueness داخل الشركة؛ Advisory Lock يمنع سباق SELECT ثم INSERT.\n    await db.execute(\n        select(\n            func.pg_advisory_xact_lock(\n                current_driver.company_id,\n                func.hashtext(f"shop-phone:{clean_phone}")\n            )\n        )\n    )\n    stmt_dup = select(Shop).filter_by(\n        company_id=current_driver.company_id,\n        phone_number=clean_phone,\n    )\n    existing_shop = (await db.execute(stmt_dup)).scalars().first()\n    if existing_shop:\n        await db.rollback()\n        raise HTTPException(status_code=409, detail=f"فشل الحفظ: رقم الهاتف مسجل مسبقاً للمحل ({existing_shop.name}).")\n'''
    fn = must_replace_once(fn, old, new, "add_new_shop concurrency")
    return replace_function(src, "add_new_shop", fn)


def patch_visits(src: str) -> str:
    fn = function_source(src, "get_driver_visits")
    old_route = '''    active_route = (\n        await db.execute(\n            select(DispatchRoute)\n            .filter(\n                DispatchRoute.company_id == company_id,\n                DispatchRoute.driver_id == driver_id,\n                DispatchRoute.status.in_(["active", "waiting", "postponed"]),\n            )\n            .order_by(DispatchRoute.id.asc())\n            .limit(1)\n        )\n    ).scalars().first()\n'''
    new_route = '''    if active_session is not None:\n        active_route = (\n            await db.execute(\n                select(DispatchRoute)\n                .filter_by(\n                    company_id=company_id,\n                    work_session_id=active_session.id,\n                    driver_id=driver_id,\n                )\n                .order_by(DispatchRoute.id.asc())\n                .limit(1)\n            )\n        ).scalars().first()\n    else:\n        company_local_date = await get_company_local_date(db, company_id)\n        active_route = (\n            await db.execute(\n                select(DispatchRoute)\n                .filter(\n                    DispatchRoute.company_id == company_id,\n                    DispatchRoute.driver_id == driver_id,\n                    DispatchRoute.dispatch_date == company_local_date,\n                    DispatchRoute.status.in_(["active", "waiting", "postponed"]),\n                )\n                .order_by(DispatchRoute.id.asc())\n                .limit(1)\n            )\n        ).scalars().first()\n'''
    if old_route in fn:
        fn = fn.replace(old_route, new_route, 1)
    elif "DispatchRoute.dispatch_date == company_local_date" not in fn:
        abort("get_driver_visits route block غير متوقع.")

    old_helper = '''            _, vehicle_location_id = await _load_active_driver_route_and_vehicle_location(\n                db,\n                company_id=company_id,\n                driver_id=driver_id,\n                work_session_id=active_session.id,\n            )\n'''
    new_helper = '''            _, vehicle_location_id = await _load_active_driver_route_and_vehicle_location(\n                db,\n                company_id=company_id,\n                driver_id=driver_id,\n                work_session_id=active_session.id,\n                require_active_route=False,\n                require_active_vehicle_location=False,\n            )\n'''
    if old_helper in fn:
        fn = fn.replace(old_helper, new_helper, 1)

    old_valid = '''                    vehicle_location_id=vehicle_location_id,\n                )\n'''
    new_valid = '''                    vehicle_location_id=vehicle_location_id,\n                    require_active_warehouse=False,\n                )\n'''
    if "require_active_warehouse=False" not in fn:
        fn = must_replace_once(fn, old_valid, new_valid, "get_driver_visits pending cleanup")
    return replace_function(src, "get_driver_visits", fn)


def patch_models(src: str) -> str:
    # 1) هاتف المحل unique داخل Tenant (NULL مسموح لأكثر من سجل في PostgreSQL).
    if "uq_shop_company_phone" not in src:
        old = "        UniqueConstraint('company_id', 'id', name='uq_shops_company_id'),\n"
        new = (
            "        UniqueConstraint('company_id', 'id', name='uq_shops_company_id'),\n"
            "        # PostgreSQL يسمح بعدة NULL؛ أي هاتف فعلي يبقى فريداً داخل Tenant.\n"
            "        UniqueConstraint('company_id', 'phone_number', name='uq_shop_company_phone'),\n"
        )
        src = must_replace_once(src, old, new, "Shop phone DB uniqueness")

    # 2) لقطة الجلسة يجب أن تفصل AVAILABLE عن DAMAGED؛ جمعهما يفقد معنى رصيد بداية البيع.
    if "chk_session_snapshot_stock_status" not in src:
        old_unique = '''        UniqueConstraint(
            'company_id', 'work_session_id', 'product_variant_id',
            name='uq_session_inventory_snapshot_variant'
        ),
'''
        new_unique = '''        UniqueConstraint(
            'company_id', 'work_session_id', 'product_variant_id', 'stock_status',
            name='uq_session_inventory_snapshot_variant_status'
        ),
'''
        src = must_replace_once(src, old_unique, new_unique, "Session snapshot status uniqueness")

        old_check = "        CheckConstraint('starting_quantity >= 0', name='chk_session_snapshot_starting'),\n"
        new_check = (
            "        CheckConstraint(\"stock_status IN ('AVAILABLE', 'DAMAGED')\", name='chk_session_snapshot_stock_status'),\n"
            "        CheckConstraint('starting_quantity >= 0', name='chk_session_snapshot_starting'),\n"
        )
        src = must_replace_once(src, old_check, new_check, "Session snapshot status check")

        old_cols = '''    product_variant_id = Column(Integer, nullable=False, index=True)

    starting_quantity = Column(Integer, nullable=False)
'''
        new_cols = '''    product_variant_id = Column(Integer, nullable=False, index=True)
    stock_status       = Column(String(50), nullable=False, index=True)

    starting_quantity = Column(Integer, nullable=False)
'''
        src = must_replace_once(src, old_cols, new_cols, "Session snapshot status column")

    return src


def validate_support(models: str, schemas: str, services: str, driver: str) -> None:
    required = {
        "models SessionInventorySnapshot": "class SessionInventorySnapshot",
        "models ProductBatch": "class ProductBatch",
        "models unified transfer": "class InventoryTransferHeader",
        "schemas request_id": "request_id: UUID",
        "schemas return batch": "batch_id: PositiveDbInt",
        "services movement batch": "async def apply_inventory_movements_batch",
        "services FEFO": "async def allocate_fefo_inventory_batch",
        "services reversal": 'reference_type="VISIT_REVERSAL"',
        "driver unified visit": "PATCH: DRIVER_UNIFIED_VISIT_INVENTORY",
        "driver unified handshake": "HANDSHAKE_POST",
    }
    haystacks = {
        "models": models,
        "schemas": schemas,
        "services": services,
        "driver": driver,
    }
    for label, needle in required.items():
        group = label.split()[0]
        if needle not in haystacks[group]:
            abort(f"الدعم المطلوب مفقود: {label}")


def self_checks(driver: str, models: str) -> None:
    ast.parse(driver)
    ast.parse(models)

    checks = [
        ("projection snapshot", "SessionInventorySnapshot.starting_quantity" in function_source(driver, "_load_vehicle_inventory_projection")),
        ("projection available snapshot", 'SessionInventorySnapshot.stock_status == "AVAILABLE"' in function_source(driver, "_load_vehicle_inventory_projection")),
        ("start snapshot by status", "stock_status=normalized_status" in function_source(driver, "start_work_session")),
        ("reversal net", 'InventoryMovement.reference_type == "VISIT_REVERSAL"' in function_source(driver, "_load_vehicle_inventory_projection")),
        ("no current+issued start", "starting_display = current_quantity + issued_quantity" not in driver),
        ("route date", "dispatch_date=company_local_date" in function_source(driver, "start_work_session")),
        ("stable cart hash", 'canonical_payload["cart_items"] = sorted' in function_source(driver, "update_visit")),
        ("money aggregate guard", "money_limit = Decimal" in function_source(driver, "update_visit")),
        ("reject without route", "الرفض لا يحتاج Route/وجهة فعالة" in function_source(driver, "respond_to_transfer")),
        ("batch reject without route", "المصافحات المرفوضة لا تعتمد" in function_source(driver, "batch_respond_to_transfers")),
        ("incoming batch lifecycle", "_validate_incoming_handshake_batches" in driver),
        ("return still DAMAGED", '"destination_stock_status": "DAMAGED"' in function_source(driver, "update_visit")),
        ("return does not require active batch", "ProductBatch.is_active" not in function_source(driver, "update_visit")),
        ("shop advisory lock", "shop-phone:" in function_source(driver, "add_new_shop")),
        ("shop DB unique", "uq_shop_company_phone" in models),
        ("snapshot DB status", "chk_session_snapshot_stock_status" in models and "uq_session_inventory_snapshot_variant_status" in models),
    ]
    failed = [label for label, ok in checks if not ok]
    if failed:
        abort("فشل self-check: " + ", ".join(failed))


root = find_project_root()
driver_path = root / "wa_backend" / "api" / "driver.py"
models_path = root / "wa_backend" / "models.py"
schemas_path = root / "wa_backend" / "schemas.py"
services_path = root / "wa_backend" / "services.py"
for p in (driver_path, models_path, schemas_path, services_path):
    if not p.is_file():
        abort(f"الملف غير موجود: {p}")

original_driver = read_text(driver_path)
original_models = read_text(models_path)
schemas = read_text(schemas_path)
services = read_text(services_path)
validate_support(original_models, schemas, services, original_driver)

new_driver = original_driver
new_driver = must_replace_once(
    new_driver,
    "from sqlalchemy import func, update, or_, and_, delete",
    "from sqlalchemy import func, update, or_, and_, delete, case",
    "sqlalchemy case import",
) if "from sqlalchemy import func, update, or_, and_, delete, case" not in new_driver else new_driver
new_driver = patch_start_session(new_driver)
new_driver = patch_update_visit(new_driver)
new_driver = patch_helper_area(new_driver)
new_driver = patch_dashboard(new_driver)
new_driver = patch_handshake_respond(new_driver)
new_driver = patch_handshake_batch(new_driver)
new_driver = patch_pending(new_driver)
new_driver = patch_add_shop(new_driver)
new_driver = patch_visits(new_driver)
new_models = patch_models(original_models)

self_checks(new_driver, new_models)

# Idempotency: إعادة تطبيق المنطق على النتيجة يجب ألا تحتاج أي كتابة إضافية كبيرة.
# نكتفي بأن كل علامات الإصلاح موجودة؛ الدوال أعلاه تتعرف على النسخة المصلحة.

if new_driver == original_driver and new_models == original_models:
    print("DRIVER_FINAL_INVENTORY_EDGES_ALREADY_OK")
    sys.exit(0)

backup_dir = root / ".patch_backups" / PATCH_NAME
backup_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(driver_path, backup_dir / "driver.py.before")
shutil.copy2(models_path, backup_dir / "models.py.before")

write_atomic(driver_path, new_driver)
write_atomic(models_path, new_models)

print("DRIVER_FINAL_INVENTORY_EDGES_OK")
print("PROJECTION_OK: starting=SessionInventorySnapshot[AVAILABLE]; issued=net VISIT out minus VISIT_REVERSAL")
print("SNAPSHOT_OK: opening custody separated by AVAILABLE/DAMAGED; no status mixing")
print("ROUTE_DATE_OK: session starts only on company-local dispatch_date")
print("HANDSHAKE_OK: reject never depends on active route/destination; accept validates active sellable batch")
print("RETURNS_OK: field returns remain immediate DAMAGED; no ProductBatch active/expiry gate added to update_visit")
print("OFFLINE_OK: visit request hash ignores cart/return list ordering")
print("MONEY_OK: aggregate Numeric(12,3) bounds checked before persistence")
print("SHOP_CONCURRENCY_OK: advisory lock + DB unique(company_id, phone_number)")
print("FILES_CHANGED: wa_backend/api/driver.py + wa_backend/models.py")
print("NEXT: py_compile + git diff --check, then independent final driver audit")
