from __future__ import annotations

import ast
import shutil
from pathlib import Path

MARKER = "RECONCILIATION_UNIFIED_VEHICLE_RECON"


def locate_root() -> Path:
    cwd = Path.cwd()
    candidates = [cwd, cwd / "wa_backend"]
    for candidate in candidates:
        if (candidate / "services.py").exists() and (candidate / "api" / "reconciliation.py").exists():
            return candidate
    raise SystemExit("PATCH_ABORT: شغّل السكربت من جذر المشروع أو من داخل wa_backend.")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"PATCH_ABORT: {label}: expected exactly 1 match, found {count}.")
    return text.replace(old, new, 1)


SERVICE_HELPERS = r'''

# فتح VEHICLE_RECON موجّه فقط للأصناف التي فشل عدّها التجميعي.
# يبقى InventoryLock على السيارة كاملة لأن الجلسة منتهية، لكن العد التفصيلي لا يرهق المشرف بأصناف مطابقة.
async def open_vehicle_reconciliation_stocktake(
    db_session: AsyncSession,
    *,
    company_id: int,
    work_session_id: int,
    vehicle_location_id: int,
    started_by: int,
    product_variant_ids: List[int],
    notes: Optional[str] = None,
) -> Tuple[StocktakeSession, bool]:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        work_session_id = _strict_int(work_session_id, "work_session_id", minimum=1)
        vehicle_location_id = _strict_int(vehicle_location_id, "vehicle_location_id", minimum=1)
        started_by = _strict_int(started_by, "started_by", minimum=1)
        normalized_variant_ids = sorted({
            _strict_int(value, "product_variant_id", minimum=1)
            for value in product_variant_ids
        })
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    if not normalized_variant_ids:
        raise InventoryMutationError("VEHICLE_RECON الموجّه يتطلب صنفاً واحداً على الأقل.")
    if len(normalized_variant_ids) > 5000:
        raise InventoryMutationError("عدد أصناف VEHICLE_RECON يتجاوز الحد الآمن.")

    if notes is not None:
        if not isinstance(notes, str):
            raise InventoryMutationError("notes يجب أن تكون نصاً أو None.")
        notes = notes.strip() or None
        if notes is not None and ("\x00" in notes or len(notes) > 4000):
            raise InventoryMutationError("notes غير صالحة أو تتجاوز 4000 حرف.")

    actor = (
        await db_session.execute(
            select(Driver.id, Driver.is_admin).filter_by(
                company_id=company_id,
                id=started_by,
                is_active=True,
            ).with_for_update(read=True)
        )
    ).one_or_none()
    if actor is None:
        raise InventoryMutationError("منشئ التسوية غير موجود/غير فعال أو خارج الشركة.")

    location = (
        await db_session.execute(
            select(InventoryLocation).filter_by(
                company_id=company_id,
                id=vehicle_location_id,
                location_type="VEHICLE",
                is_active=True,
            ).with_for_update(read=True)
        )
    ).scalar_one_or_none()
    if location is None or location.vehicle_id is None:
        raise InventoryMutationError("موقع السيارة غير موجود أو غير فعال أو لا يحمل vehicle_id صالحاً.")

    work_session = await validate_vehicle_recon_work_session(
        db_session,
        company_id=company_id,
        work_session_id=work_session_id,
        vehicle_id=int(location.vehicle_id),
    )
    if started_by != work_session.driver_id and not bool(actor.is_admin):
        raise InventoryMutationError("لا يجوز لمندوب آخر فتح تسوية عهدة هذه الجلسة.")

    valid_variant_ids = set((
        await db_session.execute(
            select(ProductVariant.id).filter(
                ProductVariant.company_id == company_id,
                ProductVariant.id.in_(normalized_variant_ids),
            )
        )
    ).scalars().all())
    if valid_variant_ids != set(normalized_variant_ids):
        raise InventoryMutationError("أحد أصناف فرق العهدة غير موجود أو لا يتبع الشركة.")

    await acquire_inventory_location_guard(
        db_session,
        company_id,
        vehicle_location_id,
        exclusive=True,
    )

    existing = (
        await db_session.execute(
            select(StocktakeSession)
            .filter(
                StocktakeSession.company_id == company_id,
                StocktakeSession.stocktake_type == "VEHICLE_RECON",
                StocktakeSession.related_work_session_id == work_session_id,
                StocktakeSession.status != "CANCELLED",
            )
            .order_by(StocktakeSession.id.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    conflicting_session_id = (
        await db_session.execute(
            select(StocktakeSession.id)
            .filter(
                StocktakeSession.company_id == company_id,
                StocktakeSession.location_id == vehicle_location_id,
                StocktakeSession.status.in_([
                    "DRAFT", "COUNTING", "PENDING_REVIEW", "RECOUNT_REQUIRED", "APPROVED"
                ]),
            )
            .order_by(StocktakeSession.id.asc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if conflicting_session_id is not None:
        raise InventoryMutationError("يوجد جرد نشط على السيارة؛ لا يمكن فتح تسوية موازية.")

    conflicting_lock_id = (
        await db_session.execute(
            select(InventoryLock.id)
            .filter(
                InventoryLock.company_id == company_id,
                InventoryLock.location_id == vehicle_location_id,
                InventoryLock.released_at.is_(None),
            )
            .order_by(InventoryLock.id.asc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if conflicting_lock_id is not None:
        raise InventoryMutationError("يوجد قفل جرد فعال على السيارة؛ لا يمكن فتح تسوية جديدة.")

    reference_number = f"VREC-{uuid4().hex[:12].upper()}"
    session = StocktakeSession(
        company_id=company_id,
        location_id=vehicle_location_id,
        reference_number=reference_number,
        stocktake_type="VEHICLE_RECON",
        status="DRAFT",
        related_work_session_id=work_session_id,
        started_by=started_by,
        notes=notes,
    )
    db_session.add(session)
    await db_session.flush()

    db_session.add(InventoryLock(
        company_id=company_id,
        stocktake_session_id=session.id,
        location_id=vehicle_location_id,
        product_variant_id=None,
        batch_id=None,
        created_by=started_by,
    ))
    await db_session.flush()

    balances = (
        await db_session.execute(
            select(InventoryBalance)
            .filter(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == vehicle_location_id,
                InventoryBalance.product_variant_id.in_(normalized_variant_ids),
                InventoryBalance.stock_status.in_(["AVAILABLE", "DAMAGED"]),
                InventoryBalance.on_hand_quantity > 0,
            )
            .order_by(
                InventoryBalance.product_variant_id.asc(),
                InventoryBalance.batch_id.asc(),
                InventoryBalance.stock_status.asc(),
                InventoryBalance.id.asc(),
            )
            .limit(_MAX_STOCKTAKE_POST_LINES + 1)
            .with_for_update()
        )
    ).scalars().all()
    if len(balances) > _MAX_STOCKTAKE_POST_LINES:
        raise InventoryMutationError("VEHICLE_RECON يتجاوز الحد الآمن لأسطر الجرد.")

    for balance in balances:
        db_session.add(StocktakeLine(
            company_id=company_id,
            stocktake_session_id=session.id,
            product_variant_id=balance.product_variant_id,
            batch_id=balance.batch_id,
            stock_status=balance.stock_status,
            line_origin="SNAPSHOT",
            expected_quantity=int(balance.on_hand_quantity),
        ))

    cutoff = utc_now()
    session.snapshot_cutoff_at = cutoff
    session.status = "COUNTING"
    session.updated_at = cutoff
    await db_session.flush()
    return session, True


# تثبيت عهدة نهاية الجلسة من الرصيد الحي بعد المطابقة/ترحيل VEHICLE_RECON.
# هذه الدالة لا تخمّن Batch ولا تغيّر InventoryBalance؛ فقط تجمّد Ending Snapshot وتغلق WorkSession مخزنياً.
async def finalize_vehicle_reconciliation_settlement(
    db_session: AsyncSession,
    *,
    company_id: int,
    work_session_id: int,
    vehicle_location_id: int,
    settled_by: int,
) -> WorkSession:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        work_session_id = _strict_int(work_session_id, "work_session_id", minimum=1)
        vehicle_location_id = _strict_int(vehicle_location_id, "vehicle_location_id", minimum=1)
        settled_by = _strict_int(settled_by, "settled_by", minimum=1)
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    actor_id = (
        await db_session.execute(
            select(Driver.id).filter_by(
                company_id=company_id,
                id=settled_by,
                is_active=True,
            ).with_for_update(read=True)
        )
    ).scalar_one_or_none()
    if actor_id is None:
        raise InventoryMutationError("منفذ التسوية غير موجود/غير فعال أو خارج الشركة.")

    await acquire_inventory_location_guard(
        db_session,
        company_id,
        vehicle_location_id,
        exclusive=True,
    )

    work_session = (
        await db_session.execute(
            select(WorkSession)
            .execution_options(populate_existing=True)
            .filter_by(company_id=company_id, id=work_session_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if work_session is None:
        raise InventoryMutationError("جلسة العمل غير موجودة أو لا تتبع الشركة.")
    if work_session.end_time is None:
        raise InventoryMutationError("لا يمكن تسوية عهدة جلسة عمل لم تنتهِ بعد.")

    location = (
        await db_session.execute(
            select(InventoryLocation).filter_by(
                company_id=company_id,
                id=vehicle_location_id,
                location_type="VEHICLE",
                is_active=True,
            ).with_for_update(read=True)
        )
    ).scalar_one_or_none()
    if location is None or location.vehicle_id is None:
        raise InventoryMutationError("موقع السيارة غير موجود أو غير فعال أو لا يحمل vehicle_id صالحاً.")

    route_id = (
        await db_session.execute(
            select(DispatchRoute.id).filter(
                DispatchRoute.company_id == company_id,
                DispatchRoute.work_session_id == work_session.id,
                DispatchRoute.driver_id == work_session.driver_id,
                DispatchRoute.vehicle_id == location.vehicle_id,
            ).order_by(DispatchRoute.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if route_id is None:
        raise InventoryMutationError("جلسة العمل لا ترتبط بموقع السيارة المحدد داخل الشركة.")

    snapshots = (
        await db_session.execute(
            select(SessionInventorySnapshot)
            .execution_options(populate_existing=True)
            .filter_by(company_id=company_id, work_session_id=work_session.id)
            .order_by(
                SessionInventorySnapshot.product_variant_id.asc(),
                SessionInventorySnapshot.stock_status.asc(),
                SessionInventorySnapshot.id.asc(),
            )
            .with_for_update()
        )
    ).scalars().all()

    if any(int(row.location_id) != vehicle_location_id for row in snapshots):
        raise InventoryMutationError("لقطة جلسة المندوب مرتبطة بموقع سيارة مختلف؛ تم رفض التسوية.")

    if work_session.is_settled:
        if any(
            row.ending_quantity is None
            or row.settled_by is None
            or row.settled_at is None
            for row in snapshots
        ):
            raise InventoryMutationError("جلسة معلّمة كمسواة لكن Ending Snapshot ناقص.")
        return work_session

    if any(
        row.ending_quantity is not None
        or row.settled_by is not None
        or row.settled_at is not None
        for row in snapshots
    ):
        raise InventoryMutationError("تم اكتشاف تسوية جزئية في SessionInventorySnapshot.")

    final_rows = (
        await db_session.execute(
            select(InventoryBalance)
            .filter(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == vehicle_location_id,
                InventoryBalance.stock_status.in_(["AVAILABLE", "DAMAGED"]),
                InventoryBalance.on_hand_quantity > 0,
            )
            .order_by(
                InventoryBalance.product_variant_id.asc(),
                InventoryBalance.batch_id.asc(),
                InventoryBalance.stock_status.asc(),
                InventoryBalance.id.asc(),
            )
            .limit(_MAX_STOCKTAKE_POST_LINES + 1)
            .with_for_update()
        )
    ).scalars().all()
    if len(final_rows) > _MAX_STOCKTAKE_POST_LINES:
        raise InventoryMutationError("رصيد السيارة يتجاوز الحد الآمن لتثبيت Ending Snapshot.")

    final_map: Dict[Tuple[int, str], int] = {}
    for balance in final_rows:
        key = (int(balance.product_variant_id), str(balance.stock_status))
        next_value = final_map.get(key, 0) + int(balance.on_hand_quantity or 0)
        if next_value < 0 or next_value > _DB_INT_MAX:
            raise InventoryMutationError("إجمالي عهدة نهاية الجلسة يتجاوز سعة INTEGER.")
        final_map[key] = next_value

    snapshot_map: Dict[Tuple[int, str], SessionInventorySnapshot] = {}
    for row in snapshots:
        key = (int(row.product_variant_id), str(row.stock_status))
        if key in snapshot_map:
            raise InventoryMutationError("لقطة الجلسة تحتوي صنف/حالة مكررة.")
        snapshot_map[key] = row

    settled_at = utc_now()
    for key in sorted(set(snapshot_map) | set(final_map)):
        ending_quantity = int(final_map.get(key, 0))
        row = snapshot_map.get(key)
        if row is None:
            product_variant_id, stock_status = key
            row = SessionInventorySnapshot(
                company_id=company_id,
                work_session_id=work_session.id,
                location_id=vehicle_location_id,
                product_variant_id=product_variant_id,
                stock_status=stock_status,
                starting_quantity=0,
            )
            db_session.add(row)
        row.ending_quantity = ending_quantity
        row.settled_by = settled_by
        row.settled_at = settled_at

    work_session.is_settled = True
    await db_session.flush()
    return work_session
'''


RECONCILIATION_NEW = r'''from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from typing import List, Optional
import json
import logging

from database import get_db
from api.dependencies import get_current_driver
from models import (
    WorkSession,
    DispatchRoute,
    InventoryLocation,
    InventoryBalance,
    InventoryLock,
    StocktakeSession,
    ProductVariant,
    SystemAuditLog,
    Driver,
)
from services import (
    InventoryMutationError,
    acquire_inventory_location_guard,
    validate_vehicle_recon_work_session,
    open_vehicle_reconciliation_stocktake,
    finalize_vehicle_reconciliation_settlement,
)

router = APIRouter()
logger = logging.getLogger("wanasah_logger")
_DB_INT_MAX = 2_147_483_647
_MAX_RECON_COUNTS = 5000
_MAX_RECON_BALANCE_ROWS = 10000


class VehicleCountItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_variant_id: StrictInt = Field(gt=0, le=_DB_INT_MAX)
    actual_quantity: StrictInt = Field(ge=0, le=_DB_INT_MAX)


class VehicleReconciliationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    counts: List[VehicleCountItem] = Field(..., max_length=_MAX_RECON_COUNTS)
    notes: Optional[str] = Field(None, max_length=4000)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("notes يجب أن تكون نصاً.")
        value = value.strip()
        if "\x00" in value:
            raise ValueError("notes لا تقبل محرف NUL.")
        return value or None

    @model_validator(mode="after")
    def reject_duplicate_products(self):
        ids = [item.product_variant_id for item in self.counts]
        if len(ids) != len(set(ids)):
            raise ValueError("لا يجوز تكرار نفس الصنف في جرد السيارة؛ أرسل إجمالي الصنف مرة واحدة.")
        return self


@router.post("/driver/session/{session_id}/reconcile", status_code=200)
async def reconcile_driver_end_of_day(
    session_id: int,
    payload: VehicleReconciliationRequest,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver),
):
    """
    تسوية عهدة نهاية اليوم بدون إجبار المندوب على Batch count عندما تكون الإجماليات مطابقة.

    - يقارن العد الفعلي التجميعي مع إجمالي on_hand (AVAILABLE + DAMAGED) للسيارة.
    - المطابقة التامة: يثبت Ending Snapshot ويغلق WorkSession مخزنياً.
    - وجود فرق: يفتح VEHICLE_RECON موجهاً فقط للأصناف المختلفة؛ لا يخمّن Batch الفرق.
    """
    company_id = int(current_driver.company_id)
    driver_id = int(current_driver.id)

    try:
        work_session = (
            await db.execute(
                select(WorkSession)
                .filter_by(
                    company_id=company_id,
                    id=session_id,
                    driver_id=driver_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if work_session is None:
            raise HTTPException(status_code=404, detail="جلسة العمل غير موجودة أو لا تخصك.")
        if work_session.end_time is None:
            raise HTTPException(status_code=409, detail="يجب إنهاء يوم العمل قبل تسوية عهدة السيارة.")

        # State-idempotency: retry بعد نجاح المطابقة لا يعيد أي حركة أو يفتح جرداً جديداً.
        if work_session.is_settled:
            await db.rollback()
            return {
                "message": "تمت تسوية عهدة هذه الجلسة مسبقاً.",
                "requires_audit": False,
                "already_settled": True,
            }

        route = (
            await db.execute(
                select(DispatchRoute)
                .filter_by(
                    company_id=company_id,
                    work_session_id=work_session.id,
                    driver_id=driver_id,
                )
                .order_by(DispatchRoute.id.desc())
                .limit(1)
                .with_for_update(read=True)
            )
        ).scalar_one_or_none()
        if route is None or route.vehicle_id is None:
            raise HTTPException(status_code=409, detail="جلسة العمل لا ترتبط بسيارة صالحة للتسوية.")

        await validate_vehicle_recon_work_session(
            db,
            company_id=company_id,
            work_session_id=work_session.id,
            vehicle_id=int(route.vehicle_id),
        )

        vehicle_location = (
            await db.execute(
                select(InventoryLocation)
                .filter_by(
                    company_id=company_id,
                    vehicle_id=route.vehicle_id,
                    location_type="VEHICLE",
                    is_active=True,
                )
                .with_for_update(read=True)
            )
        ).scalar_one_or_none()
        if vehicle_location is None:
            raise HTTPException(status_code=409, detail="السيارة لا تملك موقع مخزون VEHICLE فعالاً.")

        vehicle_location_id = int(vehicle_location.id)
        await acquire_inventory_location_guard(
            db,
            company_id,
            vehicle_location_id,
            exclusive=True,
        )

        # إذا سبق فتح VEHICLE_RECON لهذه الجلسة فلا ننشئ نسخة ثانية ولا نتجاوز المراجعة المفتوحة.
        existing_recon = (
            await db.execute(
                select(StocktakeSession)
                .filter(
                    StocktakeSession.company_id == company_id,
                    StocktakeSession.stocktake_type == "VEHICLE_RECON",
                    StocktakeSession.related_work_session_id == work_session.id,
                    StocktakeSession.status != "CANCELLED",
                )
                .order_by(StocktakeSession.id.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if existing_recon is not None:
            if existing_recon.status == "POSTED":
                raise HTTPException(
                    status_code=409,
                    detail="VEHICLE_RECON بحالة POSTED لكن WorkSession غير مسواة؛ البيانات غير متسقة وتحتاج مراجعة.",
                )
            await db.rollback()
            return {
                "message": "يوجد VEHICLE_RECON مفتوح لهذه الجلسة؛ استخدم نفس جلسة المراجعة.",
                "requires_audit": True,
                "stocktake_reference": existing_recon.reference_number,
                "stocktake_session_id": existing_recon.id,
                "stocktake_status": existing_recon.status,
            }

        conflicting_lock = (
            await db.execute(
                select(InventoryLock.id)
                .filter(
                    InventoryLock.company_id == company_id,
                    InventoryLock.location_id == vehicle_location_id,
                    InventoryLock.released_at.is_(None),
                )
                .order_by(InventoryLock.id.asc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if conflicting_lock is not None:
            raise HTTPException(status_code=409, detail="يوجد جرد/قفل مخزني فعال على السيارة؛ أكمله قبل التسوية.")

        submitted_ids = sorted({item.product_variant_id for item in payload.counts})
        if submitted_ids:
            valid_ids = set((
                await db.execute(
                    select(ProductVariant.id).filter(
                        ProductVariant.company_id == company_id,
                        ProductVariant.id.in_(submitted_ids),
                    )
                )
            ).scalars().all())
            if valid_ids != set(submitted_ids):
                raise HTTPException(status_code=422, detail="أحد الأصناف المعدودة غير موجود أو لا يتبع شركتك.")

        balance_rows = (
            await db.execute(
                select(InventoryBalance)
                .filter(
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.location_id == vehicle_location_id,
                    InventoryBalance.stock_status.in_(["AVAILABLE", "DAMAGED"]),
                    or_(
                        InventoryBalance.on_hand_quantity > 0,
                        InventoryBalance.reserved_quantity > 0,
                    ),
                )
                .order_by(
                    InventoryBalance.product_variant_id.asc(),
                    InventoryBalance.batch_id.asc(),
                    InventoryBalance.stock_status.asc(),
                    InventoryBalance.id.asc(),
                )
                .limit(_MAX_RECON_BALANCE_ROWS + 1)
                .with_for_update()
            )
        ).scalars().all()
        if len(balance_rows) > _MAX_RECON_BALANCE_ROWS:
            raise HTTPException(status_code=409, detail="رصيد السيارة كبير جداً للتسوية التجميعية الآمنة.")

        expected_map = {}
        reserved_total = 0
        for balance in balance_rows:
            reserved_total += int(balance.reserved_quantity or 0)
            if balance.on_hand_quantity <= 0:
                continue
            product_variant_id = int(balance.product_variant_id)
            next_total = expected_map.get(product_variant_id, 0) + int(balance.on_hand_quantity or 0)
            if next_total > _DB_INT_MAX:
                raise HTTPException(status_code=409, detail="إجمالي أحد أصناف السيارة يتجاوز سعة INTEGER.")
            expected_map[product_variant_id] = next_total

        if reserved_total != 0:
            raise HTTPException(
                status_code=409,
                detail="يوجد مخزون محجوز على السيارة بعد إنهاء الجلسة؛ يجب تحرير الحجز قبل التسوية.",
            )

        actual_map = {item.product_variant_id: item.actual_quantity for item in payload.counts}
        missing_products = sorted(set(expected_map) - set(actual_map))
        if missing_products:
            raise HTTPException(
                status_code=422,
                detail=(
                    "محاولة العد ناقصة؛ الصنف غير المرسل لا يُعامل كصفر. "
                    f"الأصناف الناقصة: {missing_products[:20]}"
                ),
            )

        variances = []
        for product_variant_id in sorted(set(expected_map) | set(actual_map)):
            expected = int(expected_map.get(product_variant_id, 0))
            actual = int(actual_map.get(product_variant_id, 0))
            if expected != actual:
                variances.append({
                    "product_variant_id": product_variant_id,
                    "expected": expected,
                    "actual": actual,
                    "variance": actual - expected,
                })

        if not variances:
            await finalize_vehicle_reconciliation_settlement(
                db,
                company_id=company_id,
                work_session_id=work_session.id,
                vehicle_location_id=vehicle_location_id,
                settled_by=driver_id,
            )
            db.add(SystemAuditLog(
                company_id=company_id,
                admin_id=driver_id,
                target_id=f"WorkSession_{work_session.id}",
                action_type="VEHICLE_RECON_MATCHED",
                old_value="is_settled=false",
                new_value=json.dumps({
                    "is_settled": True,
                    "product_count": len(expected_map),
                    "vehicle_location_id": vehicle_location_id,
                }, ensure_ascii=False),
            ))
            await db.commit()
            return {
                "message": "التسوية المخزنية مطابقة 100% وتم تثبيت عهدة نهاية الجلسة.",
                "requires_audit": False,
                "already_settled": False,
            }

        variance_product_ids = [row["product_variant_id"] for row in variances]
        audit_note = (
            f"تسوية عهدة جلسة ({work_session.id})؛ فرق تجميعي في الأصناف: "
            + ",".join(str(value) for value in variance_product_ids[:100])
        )
        if payload.notes:
            audit_note = f"{audit_note}. {payload.notes}"

        stocktake_session, created = await open_vehicle_reconciliation_stocktake(
            db,
            company_id=company_id,
            work_session_id=work_session.id,
            vehicle_location_id=vehicle_location_id,
            started_by=driver_id,
            product_variant_ids=variance_product_ids,
            notes=audit_note[:4000],
        )

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=driver_id,
            target_id=f"WorkSession_{work_session.id}",
            action_type="VEHICLE_RECON_VARIANCE_DETECTED",
            old_value="aggregate_count",
            new_value=json.dumps({
                "stocktake_session_id": stocktake_session.id,
                "stocktake_reference": stocktake_session.reference_number,
                "variance_count": len(variances),
                "variance_product_ids": variance_product_ids[:100],
            }, ensure_ascii=False),
        ))
        await db.commit()
        return {
            "message": "يوجد فرق في العهدة؛ تم فتح VEHICLE_RECON فقط للأصناف المختلفة وتجميد السيارة للمراجعة.",
            "requires_audit": True,
            "stocktake_reference": stocktake_session.reference_number,
            "stocktake_session_id": stocktake_session.id,
            "stocktake_status": stocktake_session.status,
            "variance_count": len(variances),
            "variance_product_ids": variance_product_ids,
            "created": created,
        }

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("تعارض متزامن أثناء تسوية عهدة السيارة", exc_info=True)
        raise HTTPException(status_code=409, detail="حدث تعارض متزامن أثناء فتح/تثبيت التسوية؛ أعد المحاولة.") from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ داخلي أثناء تسوية عهدة السيارة: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء معالجة التسوية.") from exc
'''


def patch_services(src: str) -> str:
    if "async def open_vehicle_reconciliation_stocktake(" not in src:
        src = replace_once(
            src,
            "from uuid import UUID\n",
            "from uuid import UUID, uuid4\n",
            "services uuid4 import",
        )
        src = replace_once(
            src,
            "    OfferRule,\n    Driver,\n",
            "    OfferRule,\n    ProductVariant,\n    Driver,\n",
            "services ProductVariant import",
        )
        src = replace_once(
            src,
            "    WorkSession,\n    DispatchRoute,\n",
            "    WorkSession,\n    SessionInventorySnapshot,\n    DispatchRoute,\n",
            "services SessionInventorySnapshot import",
        )
        marker = "\n\n# ترحيل فروقات جرد معتمد دفعة واحدة دون N+1، مع قفل الموقع والتحقق من آخر محاولة مرة واحدة.\nasync def post_approved_stocktake_adjustments(\n"
        if marker not in src:
            raise SystemExit("PATCH_ABORT: services stocktake posting marker not found.")
        src = src.replace(marker, SERVICE_HELPERS + marker, 1)

    # VEHICLE_RECON الذي تفتحه reconciliation قد يكون موجهاً لعدة أصناف مختلفة، لا كامل السيارة.
    old_scope = '''    # اقرأ نطاق الجرد كله مرة واحدة لكشف أي رصيد موجب أغفلته اللقطة، بما فيه الأسطر بلا فرق.\n    stmt_balances = select(InventoryBalance).execution_options(populate_existing=True).filter(\n        InventoryBalance.company_id == company_id,\n        InventoryBalance.location_id == session.location_id,\n    )\n    if session.stocktake_type == "CYCLE_COUNT":\n        stmt_balances = stmt_balances.filter(\n            InventoryBalance.product_variant_id == session.scope_product_variant_id,\n        )\n        if session.scope_batch_id is not None:\n            stmt_balances = stmt_balances.filter(\n                InventoryBalance.batch_id == session.scope_batch_id,\n            )\n'''
    new_scope = '''    # اقرأ نطاق الجرد الفعلي مرة واحدة.\n    # VEHICLE_RECON قد يكون كاملاً (من warehouse) أو موجهاً فقط لأصناف ظهر بها فرق تجميعي.\n    stmt_balances = select(InventoryBalance).execution_options(populate_existing=True).filter(\n        InventoryBalance.company_id == company_id,\n        InventoryBalance.location_id == session.location_id,\n    )\n    if session.stocktake_type == "CYCLE_COUNT":\n        stmt_balances = stmt_balances.filter(\n            InventoryBalance.product_variant_id == session.scope_product_variant_id,\n        )\n        if session.scope_batch_id is not None:\n            stmt_balances = stmt_balances.filter(\n                InventoryBalance.batch_id == session.scope_batch_id,\n            )\n    elif session.stocktake_type == "VEHICLE_RECON":\n        recon_variant_ids = sorted({\n            int(stocktake_line.product_variant_id)\n            for stocktake_line, _ in line_rows\n        })\n        if recon_variant_ids:\n            stmt_balances = stmt_balances.filter(\n                InventoryBalance.product_variant_id.in_(recon_variant_ids)\n            )\n        else:\n            # جلسة موجّهة بلا Snapshot لا تفحص أصنافاً غير مكتشفة؛ أي DISCOVERED يضيف سطره قبل الاعتماد.\n            stmt_balances = stmt_balances.filter(InventoryBalance.id == -1)\n'''
    if old_scope in src:
        src = src.replace(old_scope, new_scope, 1)
    elif "VEHICLE_RECON قد يكون كاملاً" not in src:
        raise SystemExit("PATCH_ABORT: services stocktake balance scope block changed unexpectedly.")

    old_end = '''    session.status = "POSTED"\n    session.posted_at = now\n    session.updated_at = now\n\n    return [movement for _, movement, _ in movements]\n'''
    new_end = '''    session.status = "POSTED"\n    session.posted_at = now\n    session.updated_at = now\n\n    # VEHICLE_RECON لا يكتمل فعلياً قبل تثبيت Ending Snapshot وإغلاق WorkSession مخزنياً.\n    if session.stocktake_type == "VEHICLE_RECON":\n        await finalize_vehicle_reconciliation_settlement(\n            db_session,\n            company_id=company_id,\n            work_session_id=session.related_work_session_id,\n            vehicle_location_id=session.location_id,\n            settled_by=performed_by,\n        )\n\n    return [movement for _, movement, _ in movements]\n'''
    if old_end in src:
        src = src.replace(old_end, new_end, 1)
    elif "VEHICLE_RECON لا يكتمل فعلياً" not in src:
        raise SystemExit("PATCH_ABORT: services stocktake posting tail changed unexpectedly.")

    posted_return = '''        return ordered_existing

    if existing_movements:
'''
    posted_guarded = '''        if session.stocktake_type == "VEHICLE_RECON":
            settled_state = (
                await db_session.execute(
                    select(WorkSession.is_settled).filter_by(
                        company_id=company_id,
                        id=session.related_work_session_id,
                    )
                )
            ).scalar_one_or_none()
            if settled_state is not True:
                raise InventoryMutationError(
                    "VEHICLE_RECON بحالة POSTED لكن WorkSession غير مسواة؛ الحالة غير متسقة."
                )
        return ordered_existing

    if existing_movements:
'''
    if posted_return in src:
        src = src.replace(posted_return, posted_guarded, 1)
    elif "VEHICLE_RECON بحالة POSTED لكن WorkSession" not in src:
        raise SystemExit("PATCH_ABORT: services POSTED replay block changed unexpectedly.")

    return src


def validate(reconciliation: str, services: str) -> None:
    ast.parse(reconciliation)
    ast.parse(services)

    forbidden = ["SessionInventory", "InventoryLocation.driver_id", "batch_id=None"]
    for token in forbidden:
        if token in reconciliation:
            raise SystemExit(f"PATCH_ABORT: legacy/unsafe token remains in reconciliation.py: {token}")

    required_recon = [
        "validate_vehicle_recon_work_session",
        "acquire_inventory_location_guard",
        "finalize_vehicle_reconciliation_settlement",
        "open_vehicle_reconciliation_stocktake",
        "reserved_total != 0",
        "missing_products",
        "variance_product_ids",
    ]
    for token in required_recon:
        if token not in reconciliation:
            raise SystemExit(f"PATCH_ABORT: reconciliation invariant missing: {token}")

    required_services = [
        "async def open_vehicle_reconciliation_stocktake(",
        "async def finalize_vehicle_reconciliation_settlement(",
        "SessionInventorySnapshot",
        "VEHICLE_RECON قد يكون كاملاً",
        "VEHICLE_RECON لا يكتمل فعلياً",
    ]
    for token in required_services:
        if token not in services:
            raise SystemExit(f"PATCH_ABORT: services integration invariant missing: {token}")


def main() -> None:
    root = locate_root()
    recon_path = root / "api" / "reconciliation.py"
    services_path = root / "services.py"

    reconciliation = recon_path.read_text(encoding="utf-8")
    services = services_path.read_text(encoding="utf-8")

    if MARKER in reconciliation:
        validate(reconciliation, services)
        print("RECONCILIATION_UNIFIED_VEHICLE_RECON_ALREADY_OK")
        return

    # لا نطبق على ملف حديث مجهول؛ هذا الباتش مخصص للنسخة Legacy المعروفة فقط.
    legacy_markers = [
        "SessionInventory",
        "async def reconcile_driver_end_of_day(",
        "stmt_inventory = select(SessionInventory)",
        "InventoryLocation).filter_by(\n            company_id=company_id, driver_id=current_driver.id",
    ]
    missing = [marker for marker in legacy_markers if marker not in reconciliation]
    if missing:
        raise SystemExit(
            "PATCH_ABORT: reconciliation.py لا يطابق النسخة Legacy التي دُققت. "
            f"Missing markers: {missing}"
        )

    patched_services = patch_services(services)
    patched_reconciliation = "# " + MARKER + "\n" + RECONCILIATION_NEW
    validate(patched_reconciliation, patched_services)

    backup_dir = root / ".patch_backups" / MARKER
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(recon_path, backup_dir / "reconciliation.py.before")
    shutil.copy2(services_path, backup_dir / "services.py.before")

    services_path.write_text(patched_services, encoding="utf-8", newline="\n")
    recon_path.write_text(patched_reconciliation, encoding="utf-8", newline="\n")

    print("RECONCILIATION_UNIFIED_VEHICLE_RECON_OK")
    print("LEGACY_OK: SessionInventory + InventoryLocation.driver_id removed from reconciliation")
    print("AGGREGATE_OK: driver counts product totals only; missing expected products are rejected, not treated as zero")
    print("MATCH_OK: exact aggregate match freezes Ending Snapshot and sets WorkSession.is_settled=True")
    print("VARIANCE_OK: opens targeted VEHICLE_RECON only for mismatched products; Batch is never guessed")
    print("POST_OK: approved VEHICLE_RECON posting now finalizes SessionInventorySnapshot + WorkSession")
    print("CONCURRENCY_OK: WorkSession/rows + exclusive vehicle advisory guard + InventoryLock/unique lifecycle")
    print("RESERVATION_OK: orphan reserved stock blocks reconciliation instead of being hidden")
    print("FILES_CHANGED: wa_backend/api/reconciliation.py + wa_backend/services.py")


if __name__ == "__main__":
    main()
