#!/usr/bin/env python3
from __future__ import annotations

import ast
import difflib
import re
import subprocess
import tempfile
from pathlib import Path

TARGET = Path("wa_backend/services.py")
PATCH_NAME = "services_unified_engine.patch"


def repo_root() -> Path:
    try:
        return Path(subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            encoding="utf-8",
            errors="replace",
            stderr=subprocess.STDOUT,
        ).strip())
    except Exception as exc:
        raise SystemExit("ERROR: شغّل الملف من داخل مستودع wanasah.") from exc


def replace_once(source: str, pattern: str, replacement: str, label: str) -> str:
    rx = re.compile(pattern, re.M | re.S)
    matches = list(rx.finditer(source))
    if len(matches) != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {len(matches)}")
    m = matches[0]
    return source[:m.start()] + replacement.rstrip() + "\n\n" + source[m.end():]


IMPORTS = """from datetime import date
from sqlalchemy import select, func, and_, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from models import (
    SystemSetting,
    OfferRule,
    Driver,
    Shop,
    WorkSession,
    ProductVariant,
    InventoryLock,
    InventoryLocation,
    InventoryBalance,
    InventoryMovement,
    InventoryMovementImpact,
    ProductBatch,
)"""

GET_SETTING = r"""
# جلب إعداد خاص بالشركة حصراً ومنع أي قراءة عابرة بين الـTenants.
async def get_setting(
    db_session: AsyncSession,
    company_id: int,
    key: str,
    default_value: Any,
    value_type: Type = str,
) -> Any:
    if not company_id:
        raise ValueError("company_id إجباري لقراءة إعدادات الشركة.")

    stmt = select(SystemSetting.setting_value).filter_by(
        company_id=int(company_id),
        setting_key=key,
    )
    value = (await db_session.execute(stmt)).scalar_one_or_none()

    if value is None:
        return default_value

    try:
        return value_type(value)
    except Exception:
        return default_value
"""

CHECK_DEBT = r"""
# التحقق من سقف الذمم داخل Tenant واحد مع قفل المحل لمنع السباقات المحاسبية.
async def check_debt_limits(
    db_session: AsyncSession,
    company_id: int,
    driver_id: int,
    shop_id: int,
    new_debt_amount: Decimal,
    pre_fetched_driver: Optional[Driver] = None,
    pre_fetched_shop: Optional[Shop] = None,
) -> Tuple[bool, str]:
    new_debt = Decimal(str(new_debt_amount))
    if new_debt <= Decimal("0"):
        return True, ""

    company_id = int(company_id)

    if pre_fetched_driver is not None:
        if pre_fetched_driver.id != driver_id or pre_fetched_driver.company_id != company_id:
            return False, "المندوب غير صالح لهذه الشركة."
        driver = pre_fetched_driver
    else:
        stmt_driver = select(Driver).filter_by(
            id=driver_id,
            company_id=company_id,
            is_active=True,
        )
        driver = (await db_session.execute(stmt_driver)).scalar_one_or_none()

    # لا نعتمد pre_fetched_shop في القرار المالي؛ يجب قفل الصف الحقيقي دائماً.
    stmt_shop = select(Shop).filter_by(
        id=shop_id,
        company_id=company_id,
    ).with_for_update()
    shop = (await db_session.execute(stmt_shop)).scalar_one_or_none()

    if not driver or not shop:
        return False, "المندوب أو المحل غير موجود."
    if not getattr(driver, "can_allow_debt", False):
        return False, "غير مصرح لك بإعطاء ذمم للمحلات."

    max_limit = Decimal(str(shop.max_debt_limit or "0.0"))
    if max_limit <= Decimal("0"):
        return False, "هذا المحل غير مصرح له بفتح ذمم (السقف صفر)."

    current_bal = Decimal(str(shop.current_balance or "0.0"))
    if current_bal + new_debt > max_limit:
        return False, f"مرفوض. سقف الذمة ({max_limit})، والرصيد سيصبح ({current_bal + new_debt})."

    return True, ""
"""

UNIFIED_ENGINE = r"""
class InventoryMutationError(Exception):
    pass


# إنشاء صف رصيد صفري عند الوجهة فقط؛ الرصيد الحي يبقى حصرياً في InventoryBalance.
async def _ensure_inventory_balance(
    db_session: AsyncSession,
    *,
    company_id: int,
    location_id: int,
    product_variant_id: int,
    batch_id: int,
    stock_status: str,
) -> None:
    stmt = pg_insert(InventoryBalance).values(
        company_id=company_id,
        location_id=location_id,
        product_variant_id=product_variant_id,
        batch_id=batch_id,
        stock_status=stock_status,
        on_hand_quantity=0,
        reserved_quantity=0,
    ).on_conflict_do_nothing(
        index_elements=[
            "company_id",
            "location_id",
            "product_variant_id",
            "batch_id",
            "stock_status",
        ]
    )
    await db_session.execute(stmt)


# تسجيل لقطة قبل/بعد للحركة دون إنشاء مصدر حقيقة موازٍ للرصيد.
def _add_inventory_movement_impact(
    db_session: AsyncSession,
    *,
    company_id: int,
    movement_id: int,
    balance: InventoryBalance,
    before_on_hand: int,
    before_reserved: int,
) -> None:
    after_on_hand = int(balance.on_hand_quantity or 0)
    after_reserved = int(balance.reserved_quantity or 0)

    if before_on_hand == after_on_hand and before_reserved == after_reserved:
        return

    db_session.add(InventoryMovementImpact(
        company_id=company_id,
        movement_id=movement_id,
        inventory_balance_id=balance.id,
        on_hand_before=before_on_hand,
        on_hand_after=after_on_hand,
        reserved_before=before_reserved,
        reserved_after=after_reserved,
    ))


# تطبيق حركة مخزون واحدة بشكل ذري، Batch-aware، Idempotent، ومحمي من الأقفال والتزامن.
async def apply_inventory_movement(
    db_session: AsyncSession,
    *,
    company_id: int,
    performed_by: int,
    product_variant_id: int,
    batch_id: int,
    quantity: int,
    movement_kind: str,
    reference_type: str,
    reference_id: str,
    idempotency_key: str,
    source_location_id: Optional[int] = None,
    destination_location_id: Optional[int] = None,
    source_stock_status: Optional[str] = None,
    destination_stock_status: Optional[str] = None,
    reservation_action: Optional[str] = None,
    work_session_id: Optional[int] = None,
    transfer_header_id: Optional[int] = None,
    stocktake_session_id: Optional[int] = None,
    stocktake_count_attempt_id: Optional[int] = None,
    notes: Optional[str] = None,
    ignore_stocktake_session_id: Optional[int] = None,
) -> InventoryMovement:
    company_id = int(company_id)
    performed_by = int(performed_by)
    product_variant_id = int(product_variant_id)
    batch_id = int(batch_id)
    quantity = int(quantity)
    source_location_id = int(source_location_id) if source_location_id is not None else None
    destination_location_id = int(destination_location_id) if destination_location_id is not None else None

    if quantity <= 0:
        raise InventoryMutationError("الكمية يجب أن تكون أكبر من صفر.")

    movement_kind = str(movement_kind).strip().upper()
    if movement_kind not in {"PHYSICAL", "RESERVATION", "STATUS_CHANGE"}:
        raise InventoryMutationError("نوع حركة المخزون غير صالح.")

    reference_type = str(reference_type or "").strip()
    reference_id = str(reference_id or "").strip()
    idempotency_key = str(idempotency_key or "").strip()
    if not reference_type or not reference_id or not idempotency_key:
        raise InventoryMutationError("مرجع الحركة ومفتاح عدم التكرار إلزاميان.")
    if len(reference_type) > 50 or len(reference_id) > 100 or len(idempotency_key) > 100:
        raise InventoryMutationError("مرجع الحركة أو مفتاح عدم التكرار أطول من الحد المسموح.")

    if source_stock_status is not None:
        source_stock_status = str(source_stock_status).strip().upper()
    if destination_stock_status is not None:
        destination_stock_status = str(destination_stock_status).strip().upper()
    if reservation_action is not None:
        reservation_action = str(reservation_action).strip().upper()

    allowed_statuses = {"AVAILABLE", "DAMAGED"}
    if source_stock_status is not None and source_stock_status not in allowed_statuses:
        raise InventoryMutationError("حالة مخزون المصدر غير صالحة.")
    if destination_stock_status is not None and destination_stock_status not in allowed_statuses:
        raise InventoryMutationError("حالة مخزون الوجهة غير صالحة.")

    if (source_location_id is None) != (source_stock_status is None):
        raise InventoryMutationError("المصدر وحالته يجب أن يوجدا معاً أو يكونا فارغين معاً.")
    if (destination_location_id is None) != (destination_stock_status is None):
        raise InventoryMutationError("الوجهة وحالتها يجب أن توجدا معاً أو تكونا فارغتين معاً.")

    if movement_kind == "RESERVATION":
        if reservation_action not in {"RESERVE", "RELEASE"}:
            raise InventoryMutationError("حركة الحجز تتطلب RESERVE أو RELEASE.")
        if (
            source_location_id is None
            or destination_location_id != source_location_id
            or source_stock_status != "AVAILABLE"
            or destination_stock_status != "AVAILABLE"
        ):
            raise InventoryMutationError("شكل حركة الحجز غير صالح.")
    elif reservation_action is not None:
        raise InventoryMutationError("reservation_action مسموح فقط لحركة RESERVATION.")

    if movement_kind == "STATUS_CHANGE" and (
        source_location_id is None
        or destination_location_id != source_location_id
        or source_stock_status == destination_stock_status
    ):
        raise InventoryMutationError("شكل تغيير حالة المخزون غير صالح.")

    if movement_kind == "PHYSICAL":
        if source_location_id is None and destination_location_id is None:
            raise InventoryMutationError("الحركة الفيزيائية تحتاج مصدراً أو وجهة.")
        if source_location_id is not None and destination_location_id is not None and source_location_id == destination_location_id:
            raise InventoryMutationError("الحركة الفيزيائية بين نفس الموقع غير صالحة.")
        if (source_location_id is not None and source_stock_status is None) or (destination_location_id is not None and destination_stock_status is None):
            raise InventoryMutationError("حالة مخزون المصدر/الوجهة إلزامية.")

    advisory_key = f"inventory:{company_id}:{idempotency_key}"
    await db_session.execute(select(func.pg_advisory_xact_lock(func.hashtext(advisory_key))))

    existing = (await db_session.execute(select(InventoryMovement).filter_by(
        company_id=company_id,
        idempotency_key=idempotency_key,
    ))).scalar_one_or_none()
    if existing is not None:
        expected_existing = {
            "performed_by": performed_by,
            "source_location_id": source_location_id,
            "destination_location_id": destination_location_id,
            "source_stock_status": source_stock_status,
            "destination_stock_status": destination_stock_status,
            "product_variant_id": product_variant_id,
            "batch_id": batch_id,
            "movement_kind": movement_kind,
            "reservation_action": reservation_action,
            "quantity": quantity,
            "work_session_id": work_session_id,
            "transfer_header_id": transfer_header_id,
            "stocktake_session_id": stocktake_session_id,
            "stocktake_count_attempt_id": stocktake_count_attempt_id,
            "reference_type": reference_type,
            "reference_id": reference_id,
        }
        for field_name, expected_value in expected_existing.items():
            if getattr(existing, field_name) != expected_value:
                raise InventoryMutationError(
                    "مفتاح idempotency مستخدم مسبقاً لحركة مختلفة؛ تم رفض إعادة الاستخدام."
                )
        return existing

    batch_exists = (await db_session.execute(select(ProductBatch.id).filter_by(
        company_id=company_id,
        product_variant_id=product_variant_id,
        id=batch_id,
    ))).scalar_one_or_none()
    if batch_exists is None:
        raise InventoryMutationError("الدفعة لا تنتمي للصنف أو الشركة المحددة.")

    location_ids = {
        int(location_id)
        for location_id in (source_location_id, destination_location_id)
        if location_id is not None
    }
    if location_ids:
        existing_location_ids = set((await db_session.execute(select(InventoryLocation.id).filter(
            InventoryLocation.company_id == company_id,
            InventoryLocation.id.in_(location_ids),
            InventoryLocation.is_active.is_(True),
        ))).scalars().all())
        if existing_location_ids != location_ids:
            raise InventoryMutationError("أحد مواقع المخزون غير موجود أو غير فعال.")

    for location_id in sorted(location_ids):
        await check_inventory_lock(
            db_session,
            company_id,
            location_id,
            product_variant_id,
            batch_id,
            ignore_stocktake_session_id=ignore_stocktake_session_id,
        )

    source_key = None if source_location_id is None else (int(source_location_id), source_stock_status)
    destination_key = None if destination_location_id is None else (int(destination_location_id), destination_stock_status)

    if destination_key is not None and destination_key != source_key:
        await _ensure_inventory_balance(
            db_session,
            company_id=company_id,
            location_id=destination_key[0],
            product_variant_id=product_variant_id,
            batch_id=batch_id,
            stock_status=destination_key[1],
        )

    keys = sorted({key for key in (source_key, destination_key) if key is not None}, key=lambda x: (x[0], x[1]))
    if not keys:
        raise InventoryMutationError("لا يوجد رصيد متأثر بالحركة.")

    predicates = [
        and_(InventoryBalance.location_id == location_id, InventoryBalance.stock_status == stock_status)
        for location_id, stock_status in keys
    ]
    stmt_balances = select(InventoryBalance).filter(
        InventoryBalance.company_id == company_id,
        InventoryBalance.product_variant_id == product_variant_id,
        InventoryBalance.batch_id == batch_id,
        or_(*predicates),
    ).order_by(
        InventoryBalance.location_id.asc(),
        InventoryBalance.stock_status.asc(),
    ).with_for_update()

    balances = (await db_session.execute(stmt_balances)).scalars().all()
    balance_map = {(row.location_id, row.stock_status): row for row in balances}

    if source_key is not None and source_key not in balance_map:
        raise InventoryMutationError("رصيد المصدر غير موجود.")
    if destination_key is not None and destination_key not in balance_map:
        raise InventoryMutationError("تعذر إنشاء رصيد الوجهة.")

    before = {
        row.id: (int(row.on_hand_quantity or 0), int(row.reserved_quantity or 0))
        for row in balances
    }

    if movement_kind == "RESERVATION":
        balance = balance_map[source_key]
        on_hand = int(balance.on_hand_quantity or 0)
        reserved = int(balance.reserved_quantity or 0)
        if reservation_action == "RESERVE":
            if on_hand - reserved < quantity:
                raise InventoryMutationError("الرصيد المتاح لا يغطي كمية الحجز.")
            balance.reserved_quantity = reserved + quantity
        else:
            if reserved < quantity:
                raise InventoryMutationError("الرصيد المحجوز لا يغطي كمية التحرير.")
            balance.reserved_quantity = reserved - quantity
    else:
        if source_key is not None:
            source_balance = balance_map[source_key]
            source_on_hand = int(source_balance.on_hand_quantity or 0)
            source_reserved = int(source_balance.reserved_quantity or 0)
            if source_on_hand - source_reserved < quantity:
                raise InventoryMutationError("الرصيد الحر في المصدر لا يغطي الحركة.")
            source_balance.on_hand_quantity = source_on_hand - quantity

        if destination_key is not None:
            destination_balance = balance_map[destination_key]
            destination_balance.on_hand_quantity = int(destination_balance.on_hand_quantity or 0) + quantity

    movement = InventoryMovement(
        company_id=company_id,
        performed_by=performed_by,
        source_location_id=source_location_id,
        destination_location_id=destination_location_id,
        source_stock_status=source_stock_status,
        destination_stock_status=destination_stock_status,
        product_variant_id=product_variant_id,
        batch_id=batch_id,
        movement_kind=movement_kind,
        reservation_action=reservation_action,
        quantity=quantity,
        work_session_id=work_session_id,
        transfer_header_id=transfer_header_id,
        stocktake_session_id=stocktake_session_id,
        stocktake_count_attempt_id=stocktake_count_attempt_id,
        reference_type=reference_type,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
        notes=notes,
    )
    db_session.add(movement)
    await db_session.flush()

    for balance in balances:
        before_on_hand, before_reserved = before[balance.id]
        _add_inventory_movement_impact(
            db_session,
            company_id=company_id,
            movement_id=movement.id,
            balance=balance,
            before_on_hand=before_on_hand,
            before_reserved=before_reserved,
        )

    return movement


# تخصيص FEFO مقفل ترتيبياً دون استهلاك أي كمية؛ التنفيذ الفعلي يتم عبر apply_inventory_movement.
async def allocate_fefo_inventory(
    db_session: AsyncSession,
    *,
    company_id: int,
    location_id: int,
    product_variant_id: int,
    quantity: int,
    as_of_date: Optional[date] = None,
) -> List[Tuple[int, int]]:
    quantity = int(quantity)
    as_of_date = as_of_date or date.today()
    if quantity <= 0:
        return []

    await check_inventory_lock(db_session, int(company_id), int(location_id), int(product_variant_id))

    stmt = select(InventoryBalance, ProductBatch).join(
        ProductBatch,
        and_(
            ProductBatch.company_id == InventoryBalance.company_id,
            ProductBatch.product_variant_id == InventoryBalance.product_variant_id,
            ProductBatch.id == InventoryBalance.batch_id,
        ),
    ).filter(
        InventoryBalance.company_id == int(company_id),
        InventoryBalance.location_id == int(location_id),
        InventoryBalance.product_variant_id == int(product_variant_id),
        InventoryBalance.stock_status == "AVAILABLE",
        InventoryBalance.on_hand_quantity > InventoryBalance.reserved_quantity,
        ProductBatch.is_active.is_(True),
        ProductBatch.expiry_date >= as_of_date,
    ).order_by(ProductBatch.expiry_date.asc(), ProductBatch.id.asc()).with_for_update()

    rows = (await db_session.execute(stmt)).all()
    remaining = quantity
    allocation: List[Tuple[int, int]] = []
    for balance, batch in rows:
        available = int(balance.on_hand_quantity or 0) - int(balance.reserved_quantity or 0)
        if available <= 0:
            continue
        take = min(available, remaining)
        allocation.append((batch.id, take))
        remaining -= take
        if remaining == 0:
            break

    if remaining > 0:
        raise InventoryMutationError(f"الرصيد المتاح لا يغطي الكمية المطلوبة. العجز: {remaining} حبة.")

    return allocation


# إنشاء الحركة العكسية الدقيقة لحركة موحدة سابقة مع إبقاء السجل الأصلي دون تعديل.
async def reverse_inventory_movement(
    db_session: AsyncSession,
    *,
    original: InventoryMovement,
    performed_by: int,
    idempotency_key: str,
    reference_type: str,
    reference_id: str,
    notes: Optional[str] = None,
) -> InventoryMovement:
    common = dict(
        db_session=db_session,
        company_id=original.company_id,
        performed_by=performed_by,
        product_variant_id=original.product_variant_id,
        batch_id=original.batch_id,
        quantity=original.quantity,
        work_session_id=original.work_session_id,
        transfer_header_id=original.transfer_header_id,
        stocktake_session_id=original.stocktake_session_id,
        stocktake_count_attempt_id=original.stocktake_count_attempt_id,
        reference_type=reference_type,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
        notes=notes,
    )

    if original.movement_kind == "PHYSICAL":
        return await apply_inventory_movement(
            **common,
            movement_kind="PHYSICAL",
            source_location_id=original.destination_location_id,
            destination_location_id=original.source_location_id,
            source_stock_status=original.destination_stock_status,
            destination_stock_status=original.source_stock_status,
        )

    if original.movement_kind == "RESERVATION":
        reverse_action = "RELEASE" if original.reservation_action == "RESERVE" else "RESERVE"
        return await apply_inventory_movement(
            **common,
            movement_kind="RESERVATION",
            reservation_action=reverse_action,
            source_location_id=original.source_location_id,
            destination_location_id=original.destination_location_id,
            source_stock_status=original.source_stock_status,
            destination_stock_status=original.destination_stock_status,
        )

    if original.movement_kind == "STATUS_CHANGE":
        return await apply_inventory_movement(
            **common,
            movement_kind="STATUS_CHANGE",
            source_location_id=original.source_location_id,
            destination_location_id=original.destination_location_id,
            source_stock_status=original.destination_stock_status,
            destination_stock_status=original.source_stock_status,
        )

    raise InventoryMutationError("لا يمكن عكس نوع الحركة المحدد.")
"""

REVERSE_VISIT = r"""
# عكس زيارة سابقة مالياً ومخزنياً اعتماداً على دفتر InventoryMovement الموحد لا على رصيد مكرر.
async def reverse_previous_visit_state(
    db_session: AsyncSession,
    visit: Any,
    active_session: Optional[WorkSession],
    shop: Shop,
    admin_id: int,
    vehicle_id: Optional[int] = None,
) -> None:
    company_id = int(shop.company_id)

    if getattr(visit, "company_id", None) != company_id:
        raise InventoryReversalError("مرفوض: الزيارة والمحل لا ينتميان لنفس الشركة.")
    if active_session is not None and active_session.company_id != company_id:
        raise InventoryReversalError("مرفوض: جلسة العمل لا تنتمي لنفس الشركة.")

    old_cash = Decimal(str(visit.cash_collected or "0.0"))
    old_debt_paid = Decimal(str(visit.debt_paid or "0.0"))
    if old_cash > Decimal("0") or old_debt_paid > Decimal("0"):
        raise InventoryReversalError(
            f"مرفوض أمنياً ومحاسبياً: لا يمكن التراجع عن زيارة تم فيها تحصيل كاش ({old_cash}) أو سداد ذمة ({old_debt_paid}). يجب إصدار قيد عكسي مالي مستقل."
        )

    current_bal = Decimal(str(shop.current_balance or "0.0"))
    net_visit_debt = Decimal(str(visit.final_amount_due or "0.0")) - old_cash
    new_balance = current_bal - net_visit_debt + old_debt_paid
    if new_balance < Decimal("0"):
        raise InventoryReversalError(f"فشل التراجع: رصيد المحل الحالي ({current_bal}) لا يغطي أثر الزيارة السابقة.")

    active_items = (
        [item for item in visit.items if not getattr(item, "is_cancelled", False)]
        if visit.outcome in {"Sale", "NoSale"}
        else []
    )
    active_returns = [item for item in visit.returns if not getattr(item, "is_cancelled", False)]
    has_inventory_effect = bool(active_items or active_returns)

    if active_session is not None:
        stmt_movements = select(InventoryMovement).filter(
            InventoryMovement.company_id == company_id,
            InventoryMovement.work_session_id == active_session.id,
            InventoryMovement.reference_id == str(visit.id),
            InventoryMovement.reference_type.like("VISIT_%"),
            InventoryMovement.reference_type != "VISIT_REVERSAL",
        ).order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
        movements = (await db_session.execute(stmt_movements)).scalars().all()

        if has_inventory_effect and not movements:
            raise InventoryReversalError("مرفوض: لا توجد حركات مخزون موحدة مرتبطة بهذه الزيارة؛ لن يتم تعديل الرصيد بالتخمين.")

        for movement in movements:
            try:
                await reverse_inventory_movement(
                    db_session,
                    original=movement,
                    performed_by=admin_id,
                    idempotency_key=f"REV-VISIT-{visit.id}-MOV-{movement.id}",
                    reference_type="VISIT_REVERSAL",
                    reference_id=str(visit.id),
                    notes=f"عكس الزيارة {visit.id} للمحل {shop.name}",
                )
            except InventoryMutationError as exc:
                raise InventoryReversalError(str(exc)) from exc
    elif has_inventory_effect:
        raise InventoryReversalError("لا يمكن عكس أثر مخزني لزيارة بدون جلسة عمل مرتبطة.")

    for item in active_items:
        item.is_cancelled = True
    for ret in active_returns:
        ret.is_cancelled = True

    shop.current_balance = new_balance
    visit.amount_before_tax_and_discount = Decimal("0.0")
    visit.discount_applied = Decimal("0.0")
    visit.tax_amount = Decimal("0.0")
    visit.final_amount_due = Decimal("0.0")
    visit.cash_collected = Decimal("0.0")
    visit.debt_paid = Decimal("0.0")
    visit.shop_balance_before = None
    visit.shop_balance_after = None
    visit.tax_qr_code = None
    visit.outcome = "Pending"
    visit.status = "Pending"
"""

LOCK_GUARD = r"""
# حارس الجرد المركزي مع إمكانية تجاهل قفل الجلسة نفسها عند ترحيل نتيجة الجرد.
async def check_inventory_lock(
    db_session: AsyncSession,
    company_id: int,
    location_id: int,
    variant_id: Optional[int] = None,
    batch_id: Optional[int] = None,
    ignore_stocktake_session_id: Optional[int] = None,
) -> None:
    company_id = int(company_id)
    location_id = int(location_id)

    if batch_id is not None and variant_id is None:
        raise ValueError("batch_id لا يمكن استخدامه بدون variant_id.")

    base_filters = [
        InventoryLock.company_id == company_id,
        InventoryLock.location_id == location_id,
        InventoryLock.released_at.is_(None),
    ]
    if ignore_stocktake_session_id is not None:
        base_filters.append(InventoryLock.stocktake_session_id != int(ignore_stocktake_session_id))

    stmt_full = select(InventoryLock.id).filter(
        *base_filters,
        InventoryLock.product_variant_id.is_(None),
        InventoryLock.batch_id.is_(None),
    )
    if (await db_session.execute(stmt_full)).first():
        raise ValueError(f"الموقع ({location_id}) تحت الجرد الشامل ومقفل بالكامل.")

    if variant_id is None:
        return

    partial_filters = [*base_filters, InventoryLock.product_variant_id == int(variant_id)]
    if batch_id is not None:
        partial_filters.append(or_(InventoryLock.batch_id == int(batch_id), InventoryLock.batch_id.is_(None)))

    stmt_partial = select(InventoryLock.id).filter(*partial_filters)
    if (await db_session.execute(stmt_partial)).first():
        raise ValueError("الصنف/الدفعة مقفل جراحياً بسبب جرد دوري نشط.")
"""


def main() -> int:
    root = repo_root()
    path = root / TARGET
    if not path.exists():
        raise SystemExit(f"ERROR: الملف غير موجود: {path}")

    source = path.read_text(encoding="utf-8")
    required = [
        "SessionInventory",
        "MainWarehouse",
        "InventoryLedger",
        "WarehouseLedger",
        "async def adjust_inventory(",
        "async def reverse_previous_visit_state(",
        "async def check_inventory_lock(",
    ]
    missing = [x for x in required if x not in source]
    if missing:
        raise SystemExit("ERROR: services.py ليس النسخة المتوقعة. Missing: " + ", ".join(missing))

    updated = source
    updated = replace_once(
        updated,
        r"from sqlalchemy\.future import select\s*\nfrom sqlalchemy\.dialects\.postgresql import insert\s*\nfrom models import .*?\n(?=from typing import)",
        IMPORTS,
        "imports",
    )
    updated = replace_once(updated, r"async def get_setting\(.*?(?=def calculate_invoice\()", GET_SETTING, "get_setting")
    updated = replace_once(updated, r"async def check_debt_limits\(.*?(?=async def adjust_inventory\()", CHECK_DEBT, "check_debt_limits")
    updated = replace_once(updated, r"async def adjust_inventory\(.*?(?=def format_qty\()", UNIFIED_ENGINE, "legacy adjust_inventory")
    updated = replace_once(
        updated,
        r"async def reverse_previous_visit_state\(.*?(?=# ={20,}\n# \[المرحلة الثالثة\])",
        REVERSE_VISIT,
        "reverse_previous_visit_state",
    )
    updated = replace_once(updated, r"async def check_inventory_lock\(.*\Z", LOCK_GUARD, "check_inventory_lock")
    updated = updated.rstrip() + "\n"

    forbidden = ["SessionInventory", "MainWarehouse", "InventoryLedger", "WarehouseLedger", "adjust_inventory("]
    leftovers = [x for x in forbidden if x in updated]
    if leftovers:
        raise SystemExit("ERROR: بقيت مراجع للمحرك القديم داخل services.py: " + ", ".join(leftovers))

    try:
        ast.parse(updated, filename=str(TARGET))
        compile(updated, str(TARGET), "exec")
    except SyntaxError as exc:
        raise SystemExit(f"ERROR: generated services.py invalid: {exc}") from exc

    expected = [
        "async def apply_inventory_movement(",
        "async def allocate_fefo_inventory(",
        "async def reverse_inventory_movement(",
        "InventoryMovementImpact(",
        "ignore_stocktake_session_id",
    ]
    missing_expected = [x for x in expected if x not in updated]
    if missing_expected:
        raise SystemExit("ERROR: internal validation failed: " + ", ".join(missing_expected))

    # ولّد الـpatch بواسطة Git نفسه بدل difflib لضمان Patch صالح حتى مع اختلاف EOF/line endings.
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        temp_target = temp_root / TARGET
        temp_target.parent.mkdir(parents=True, exist_ok=True)
        temp_target.write_text(source, encoding="utf-8", newline="")

        subprocess.run(["git", "init"], cwd=temp_root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "add", TARGET.as_posix()], cwd=temp_root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(
            ["git", "-c", "user.name=patch", "-c", "user.email=patch@local", "commit", "-m", "base"],
            cwd=temp_root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        temp_target.write_text(updated, encoding="utf-8", newline="")
        diff_proc = subprocess.run(
            ["git", "diff", "--no-ext-diff", "--binary", "--", TARGET.as_posix()],
            cwd=temp_root, text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        patch = diff_proc.stdout
        if diff_proc.returncode != 0:
            raise SystemExit("ERROR: Git فشل أثناء توليد الـpatch: " + diff_proc.stderr.strip())
        if not patch:
            raise SystemExit("ERROR: لم يتم توليد أي تغييرات.")

        # تحقق من نفس الـpatch ضد نسخة المصدر نفسها قبل تسليمه للمستخدم.
        verify_root = temp_root / "verify"
        verify_target = verify_root / TARGET
        verify_target.parent.mkdir(parents=True, exist_ok=True)
        verify_target.write_text(source, encoding="utf-8", newline="")
        subprocess.run(["git", "init"], cwd=verify_root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "add", TARGET.as_posix()], cwd=verify_root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(
            ["git", "-c", "user.name=patch", "-c", "user.email=patch@local", "commit", "-m", "base"],
            cwd=verify_root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        patch_file = verify_root / PATCH_NAME
        patch_file.write_text(patch, encoding="utf-8", newline="")
        check_proc = subprocess.run(
            ["git", "apply", "--check", PATCH_NAME],
            cwd=verify_root, text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if check_proc.returncode != 0:
            raise SystemExit("ERROR: التحقق الذاتي من الـpatch فشل: " + check_proc.stderr.strip())

    out = root / PATCH_NAME
    out.write_text(patch, encoding="utf-8", newline="")
    print("SERVICES_PATCH_READY")
    print(f"Patch: {out}")
    print("services.py was NOT modified.")
    print("Next:")
    print(f"  git apply --check {PATCH_NAME}")
    print(f"  git apply {PATCH_NAME}")
    print("  python -m py_compile wa_backend/services.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
