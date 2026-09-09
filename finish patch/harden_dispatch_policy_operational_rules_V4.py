from __future__ import annotations

from pathlib import Path
import ast
import hashlib
import importlib
import json
import py_compile
import re
import sys
import tempfile

ROOT = Path.cwd()
BACKEND = ROOT / "wa_backend"
BACKUP = ROOT / ".patch_backups" / "DISPATCH_POLICY_OPERATIONAL_HARDENING_V4"

TARGETS = (
    "models.py",
    "schemas.py",
    "services.py",
    "api/driver.py",
    "api/dispatch.py",
)

# البصمات الفعلية للملفات النشطة في commit المثبت:
# 9527d423b6756ac511de2ced23fedaaa46e8c888
BASELINE_SHA256 = {
    "models.py": "51aed08e44b571b49156c0a0e966e4b8e990e69b3272774f35b437cd2859b0b6",
    "schemas.py": "413c5e21493edd613ddf85fb0b629a55887f7bfcaf82f6a8e198e3b61ad6d660",
    "services.py": "8f7d06f017ed19595c1d9d8dcdbe0e7726cb50f73d18c00e06714f4c8f64b632",
    "api/driver.py": "e5620fbc3f9e845dd0e5466dfc034f7bccdff04363b77ba9979e49d711a37d53",
    "api/dispatch.py": "51f0528612fff8ca80a8effcdf90e570d4977961cba9e9fbe8360197adf5d40c",
}

PATCH_MARKERS = {
    "models.py": "uq_visit_one_pending_owner_day",
    "schemas.py": 'Literal[\n        "zone_only",\n        "selected_shops",\n        "shops_archived_by_same_zone",',
    "services.py": "get_company_operational_day_utc_bounds",
    "api/driver.py": "ShortageRequest.driver_id == driver_id",
    "api/dispatch.py": "active_route_driver_by_zone",
}


class PatchError(RuntimeError):
    pass


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def digest(text: str) -> str:
    return hashlib.sha256(normalize_newlines(text).encode("utf-8")).hexdigest()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_atomic(path: Path, text: str) -> None:
    original = read_text(path)
    newline = "\r\n" if "\r\n" in original else "\n"
    materialized = normalize_newlines(text).replace("\n", newline)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as fh:
        fh.write(materialized)
        tmp = Path(fh.name)
    tmp.replace(path)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    new_count = text.count(new)
    # إذا كان old جزءاً حرفياً من new، لا نعيد تطبيقه على الحالة النهائية.
    if old in new and new_count == 1 and count == 1:
        return text
    if count == 1:
        return text.replace(old, new, 1)
    if count == 0 and new_count == 1:
        return text
    raise PatchError(
        f"{label}: توقعت تطابقاً واحداً للنص القديم أو الجديد؛ "
        f"old={count}, new={new_count}."
    )


def replace_between(
    text: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
    label: str,
) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise PatchError(f"{label}: لم أجد بداية المقطع.")
    end = text.find(end_marker, start)
    if end < 0:
        raise PatchError(f"{label}: لم أجد نهاية المقطع.")
    desired = replacement.rstrip() + "\n\n"
    current = text[start:end]
    if current == desired:
        return text
    return text[:start] + desired + text[end:]


def validate_source(source: str, label: str) -> None:
    try:
        ast.parse(source, filename=label)
        compile(source, label, "exec")
    except Exception as exc:
        raise PatchError(f"{label}: فشل AST/compile: {exc}") from exc


def transform_models(text: str) -> str:
    old = """        Index(
            'ix_visit_pending_owner_day',
            'company_id', 'driver_id', 'shop_id', 'operational_date', 'status'
        ),"""
    new = """        Index(
            'uq_visit_one_pending_owner_day',
            'company_id', 'driver_id', 'shop_id', 'operational_date',
            unique=True,
            postgresql_where=text("status = 'Pending' AND driver_id IS NOT NULL"),
        ),"""
    return replace_once(text, old, new, "models.py / قيد Pending Visit")


def transform_schemas(text: str) -> str:
    replacement = '''class RestoreZoneRequest(RequestModel):
    # الأسماء الرسمية للسياسة. الاسمان القديمان يُقبلان فقط كـ aliases
    # لمنع كسر Dashboard قديم، ثم يُطبّعان إلى العقد الجديد.
    mode: Literal[
        "zone_only",
        "selected_shops",
        "shops_archived_by_same_zone",
    ] = "shops_archived_by_same_zone"
    shop_ids: List[PositiveDbInt] = Field(default_factory=list, max_length=5000)

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_restore_mode(cls, v: Any) -> str:
        value = str(v or "").strip()
        aliases = {
            "selected": "selected_shops",
            "all_zone_archived": "shops_archived_by_same_zone",
        }
        return aliases.get(value, value)

    @model_validator(mode="after")
    def validate_restore_mode(self) -> "RestoreZoneRequest":
        if self.mode == "selected_shops" and not self.shop_ids:
            raise ValueError("وضع selected_shops يتطلب تحديد محل واحد على الأقل.")
        if self.mode != "selected_shops" and self.shop_ids:
            raise ValueError("shop_ids مسموحة فقط مع وضع selected_shops.")
        if len(self.shop_ids) != len(set(self.shop_ids)):
            raise ValueError("لا يجوز تكرار نفس المحل في قائمة الاستعادة.")
        return self
'''
    return replace_between(
        text,
        "class RestoreZoneRequest(RequestModel):",
        "class ArchivedZoneResponse",
        replacement,
        "schemas.py / RestoreZoneRequest",
    )


def transform_services(text: str) -> str:
    text = replace_once(
        text,
        "from datetime import date\n",
        "from datetime import date, datetime, time, timedelta, timezone\n"
        "from zoneinfo import ZoneInfo, ZoneInfoNotFoundError\n",
        "services.py / imports الزمن",
    )

    old = '''    if type(local_date) is not date:
        raise InventoryMutationError("تعذر حساب تاريخ العمل المحلي للشركة.")
    return local_date

def _normalize_inventory_movement_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
'''
    new = '''    if type(local_date) is not date:
        raise InventoryMutationError("تعذر حساب تاريخ العمل المحلي للشركة.")
    return local_date


async def get_company_operational_day_utc_bounds(
    db_session: AsyncSession,
    company_id: int,
    operational_date: Optional[date] = None,
) -> Tuple[datetime, datetime]:
    """تحويل يوم الشركة المحلي إلى الفترة UTC نصف المفتوحة [start_utc, end_utc)."""
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    timezone_name = (
        await db_session.execute(
            select(Company.timezone).filter(Company.id == company_id)
        )
    ).scalar_one_or_none()
    if not timezone_name:
        raise InventoryMutationError("الشركة غير موجودة أو لا تحمل منطقة زمنية صالحة.")

    if operational_date is None:
        operational_date = await get_company_local_date(db_session, company_id)
    if type(operational_date) is not date:
        raise InventoryMutationError("operational_date يجب أن يكون date صريحاً.")

    try:
        company_zone = ZoneInfo(str(timezone_name).strip())
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InventoryMutationError(
            f"المنطقة الزمنية للشركة غير صالحة: {timezone_name}"
        ) from exc

    local_start = datetime.combine(operational_date, time.min, tzinfo=company_zone)
    next_local_start = datetime.combine(
        operational_date + timedelta(days=1),
        time.min,
        tzinfo=company_zone,
    )
    start_utc = local_start.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = next_local_start.astimezone(timezone.utc).replace(tzinfo=None)
    if not start_utc < end_utc:
        raise InventoryMutationError("حدود يوم العمل UTC غير صالحة.")
    return start_utc, end_utc


def _normalize_inventory_movement_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
'''
    text = replace_once(text, old, new, "services.py / حدود اليوم التشغيلي")

    old = '''            "transfer_header_id": _optional_positive_int(
                spec.get("transfer_header_id"), "transfer_header_id"
            ),
'''
    new = '''            "transfer_header_id": _optional_positive_int(
                spec.get("transfer_header_id"), "transfer_header_id"
            ),
            "stocktake_session_id": _optional_positive_int(
                spec.get("stocktake_session_id"), "stocktake_session_id"
            ),
            "stocktake_count_attempt_id": _optional_positive_int(
                spec.get("stocktake_count_attempt_id"),
                "stocktake_count_attempt_id",
            ),
'''
    text = replace_once(text, old, new, "services.py / هوية حركة الجرد")

    old = '''    if reference_type in _STOCKTAKE_ONLY_REFERENCE_TYPES:
        raise InventoryMutationError(
            "مرجع حركة الجرد محجوز لخدمة ترحيل الجرد المعتمد ولا يجوز تمريره للمحرك العام."
        )
'''
    new = '''    raw_snapshot = spec.get("financial_unit_price_snapshot")
    if raw_snapshot is None:
        financial_unit_price_snapshot = None
    else:
        try:
            financial_unit_price_snapshot = _money_12_3(
                raw_snapshot,
                "financial_unit_price_snapshot",
            )
        except ValueError as exc:
            raise InventoryMutationError(str(exc)) from exc

    stocktake_session_id = normalized["stocktake_session_id"]
    stocktake_count_attempt_id = normalized["stocktake_count_attempt_id"]
    is_stocktake_reference = reference_type in _STOCKTAKE_ONLY_REFERENCE_TYPES

    if is_stocktake_reference:
        if movement_kind != "PHYSICAL":
            raise InventoryMutationError("حركة ترحيل الجرد يجب أن تكون PHYSICAL حصراً.")
        if stocktake_session_id is None or stocktake_count_attempt_id is None:
            raise InventoryMutationError(
                "حركة الجرد تتطلب stocktake_session_id وstocktake_count_attempt_id."
            )
        if reference_type in {"DRIVER_SHORTAGE", "DRIVER_SURPLUS"} and normalized["work_session_id"] is None:
            raise InventoryMutationError("حركة عهدة المندوب تتطلب work_session_id.")
        if reference_type == "DRIVER_SHORTAGE":
            if financial_unit_price_snapshot is None:
                raise InventoryMutationError(
                    "DRIVER_SHORTAGE يتطلب سعراً مالياً مثبتاً لحظة الترحيل."
                )
            total_value = financial_unit_price_snapshot * Decimal(normalized["quantity"])
            if not total_value.is_finite() or total_value > _MONEY_12_3_MAX:
                raise InventoryMutationError("قيمة DRIVER_SHORTAGE تتجاوز السعة المالية.")
        elif financial_unit_price_snapshot is not None:
            raise InventoryMutationError(
                "السعر المالي المثبت مسموح فقط لـ DRIVER_SHORTAGE."
            )
    else:
        if stocktake_session_id is not None or stocktake_count_attempt_id is not None:
            raise InventoryMutationError(
                "هوية جلسة الجرد غير مسموحة لحركة غير جردية."
            )
        if financial_unit_price_snapshot is not None:
            raise InventoryMutationError(
                "السعر المالي المثبت غير مسموح لحركة غير DRIVER_SHORTAGE."
            )
'''
    text = replace_once(text, old, new, "services.py / stocktake داخل المحرك الموحد")

    text = replace_once(
        text,
        '''        "reservation_action": reservation_action,
        "notes": notes,
    })
''',
        '''        "reservation_action": reservation_action,
        "financial_unit_price_snapshot": financial_unit_price_snapshot,
        "notes": notes,
    })
''',
        "services.py / normalized financial snapshot",
    )

    text = replace_once(
        text,
        '''        "transfer_header_id": spec["transfer_header_id"],
        "stocktake_session_id": None,
        "stocktake_count_attempt_id": None,
        "reference_type": spec["reference_type"],
''',
        '''        "transfer_header_id": spec["transfer_header_id"],
        "stocktake_session_id": spec["stocktake_session_id"],
        "stocktake_count_attempt_id": spec["stocktake_count_attempt_id"],
        "financial_unit_price_snapshot": spec["financial_unit_price_snapshot"],
        "reference_type": spec["reference_type"],
''',
        "services.py / idempotency stocktake fields",
    )

    text = replace_once(
        text,
        '''def _inventory_lock_conflicts_with_spec(
    lock: InventoryLock,
    spec: Dict[str, Any],
) -> bool:
    endpoints = {
''',
        '''def _inventory_lock_conflicts_with_spec(
    lock: InventoryLock,
    spec: Dict[str, Any],
) -> bool:
    # جلسة الجرد المالكة للقفل وحدها تستطيع ترحيل فروقاتها عبر المحرك.
    own_stocktake_id = spec.get("stocktake_session_id")
    if own_stocktake_id is not None and lock.stocktake_session_id == own_stocktake_id:
        return False

    endpoints = {
''',
        "services.py / own stocktake lock",
    )

    text = replace_once(
        text,
        '''            work_session_id=spec["work_session_id"],
            transfer_header_id=spec["transfer_header_id"],
            reference_type=spec["reference_type"],
''',
        '''            work_session_id=spec["work_session_id"],
            transfer_header_id=spec["transfer_header_id"],
            stocktake_session_id=spec["stocktake_session_id"],
            stocktake_count_attempt_id=spec["stocktake_count_attempt_id"],
            financial_unit_price_snapshot=spec["financial_unit_price_snapshot"],
            reference_type=spec["reference_type"],
''',
        "services.py / InventoryMovement الموحد",
    )

    # إزالة إنشاء الأرصدة الصفرية من مسار الجرد؛ المحرك ينشئ الوجهة عند الحاجة.
    if "    positive_rows = {" in text:
        start = text.find("    positive_rows = {")
        marker = "    # اقرأ نطاق الجرد الفعلي مرة واحدة."
        end = text.find(marker, start)
        if end < 0:
            raise PatchError("services.py / لم أجد نهاية positive_rows.")
        text = text[:start] + marker + text[end + len(marker):]

    # إزالة الكتابة اليدوية على InventoryBalance وإنشاء InventoryMovement اليدوي.
    if "    before_by_key = {}" in text:
        start = text.find("    before_by_key = {}")
        end = text.find("    now = utc_now()", start)
        if end < 0:
            raise PatchError("services.py / لم أجد نهاية الكتابة اليدوية لفروقات الجرد.")
        replacement = '''    movement_specs = []
    for spec in specs:
        movement_specs.append({
            "product_variant_id": spec["product_variant_id"],
            "batch_id": spec["batch_id"],
            "quantity": spec["quantity"],
            "movement_kind": "PHYSICAL",
            "reference_type": spec["reference_type"],
            "reference_id": spec["reference_id"],
            "idempotency_key": spec["idempotency_key"],
            "source_location_id": spec["source_location_id"],
            "destination_location_id": spec["destination_location_id"],
            "source_stock_status": spec["source_stock_status"],
            "destination_stock_status": spec["destination_stock_status"],
            "reservation_action": None,
            "work_session_id": spec["work_session_id"],
            "transfer_header_id": None,
            "stocktake_session_id": session.id,
            "stocktake_count_attempt_id": latest_attempt.id,
            "financial_unit_price_snapshot": spec.get("financial_unit_price_snapshot"),
            "notes": "ترحيل فرق آخر محاولة عد معتمدة.",
        })

    applied_movements = []
    if movement_specs:
        applied_movements = await apply_inventory_movements_batch(
            db_session,
            company_id=company_id,
            performed_by=performed_by,
            movements=movement_specs,
        )
        if len(applied_movements) != len(movement_specs):
            raise InventoryMutationError(
                "المحرك الموحد لم يعد جميع حركات فروقات الجرد المتوقعة."
            )

'''
        text = text[:start] + replacement + text[end:]
    elif "applied_movements = await apply_inventory_movements_batch(" not in text:
        raise PatchError("services.py / مسار فروقات الجرد غير معروف.")

    text = replace_once(
        text,
        "    return [movement for _, movement, _ in movements]\n",
        "    return applied_movements\n",
        "services.py / نتيجة فروقات الجرد",
    )
    return text


def transform_driver(text: str) -> str:
    text = replace_once(
        text,
        '''            .values(
                work_session_id=new_session.id,
                operational_date=company_local_date,
            )
''',
        '''            .values(
                work_session_id=new_session.id,
            )
''',
        "driver.py / تثبيت operational_date",
    )

    text = replace_once(
        text,
        '''                select(ShortageRequest.id)
                .filter_by(
                    company_id=company_id,
                    shop_id=shop.id,
                    status="pending",
                )
                .limit(1)
''',
        '''                select(ShortageRequest.id)
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
''',
        "driver.py / shortage authorization ownership",
    )

    text = replace_once(
        text,
        '''                        Visit.driver_id == active_session.driver_id,
                        Visit.status == "Pending",
                        Visit.id != visit.id,
''',
        '''                        Visit.driver_id == active_session.driver_id,
                        Visit.status == "Pending",
                        Visit.operational_date == visit.operational_date,
                        Visit.id != visit.id,
''',
        "driver.py / pending cleanup same operational day",
    )
    return text


def transform_dispatch(text: str) -> str:
    def replace_n(
        value: str,
        old: str,
        new: str,
        expected: int,
        label: str,
    ) -> str:
        old_count = value.count(old)
        if old_count == expected:
            return value.replace(old, new)
        if old_count == 0 and value.count(new) == expected:
            return value
        raise PatchError(
            f"{label}: توقعت {expected} تطابقاً للنص القديم ووجدت {old_count}."
        )

    # Completed لا يمنع زيارة لاحقة، بينما أي Pending قديم يبقى هو الطابور النشط
    # ولا نعيد كتابة operational_date التاريخي له.
    text = replace_once(
        text,
        '''                        Visit.driver_id == payload.driver_id,
                        Visit.shop_id.in_(shop_ids),
                        or_(
                            Visit.status == "Pending",
                            Visit.operational_date == company_local_date,
                        ),
                    ).order_by(Visit.shop_id.asc(), Visit.id.asc())
''',
        '''                        Visit.driver_id == payload.driver_id,
                        Visit.shop_id.in_(shop_ids),
                        Visit.status == "Pending",
                    ).order_by(Visit.shop_id.asc(), Visit.id.asc())
''',
        "dispatch.py / route creation pending queue ignores Completed",
    )
    text = replace_once(
        text,
        '''                            Visit.driver_id == route.driver_id,
                            Visit.shop_id.in_(shop_ids),
                            or_(
                                Visit.status == "Pending",
                                Visit.operational_date == company_local_date,
                            ),
                        ).order_by(Visit.shop_id.asc(), Visit.id.asc())
''',
        '''                            Visit.driver_id == route.driver_id,
                            Visit.shop_id.in_(shop_ids),
                            Visit.status == "Pending",
                        ).order_by(Visit.shop_id.asc(), Visit.id.asc())
''',
        "dispatch.py / route activation pending queue ignores Completed",
    )

    # توجد ثلاثة مواضع مقصودة بمستويات indentation مختلفة.
    for old_line in (
        "                    visit.operational_date = company_local_date\n",
        "                        visit.operational_date = company_local_date\n",
        "                visit.operational_date = company_local_date\n",
    ):
        if old_line in text:
            text = text.replace(old_line, "", 1)

    # BUG 1: يسمح بإعادة تفعيل Route المنتهي فقط كخطوة استرجاع undo_end_work
    # ما دامت التسوية المخزنية لم تُختم بعد.
    text = replace_once(
        text,
        '''        if (
            bound_session is not None
            and bound_session.end_time is not None
            and target_status == "active"
            and old_status != "active"
        ):
            raise HTTPException(
                status_code=409,
                detail="لا يمكن إعادة تفعيل خط سير تاريخي لجلسة منتهية؛ أنشئ خط سير جديد.",
            )
''',
        '''        if (
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
''',
        "dispatch.py / undo session recovery gate",
    )

    # BUG 2 + BUG 5: كل Pending في المنطقة هو active queue بغض النظر عن emergency/date.
    # ونزامن مالك النقص مع مالك Route حتى لا يبقى النقص مع المندوب السابق.
    text = replace_once(
        text,
        '''        # تغيير المندوب قبل بدء الجلسة ينقل الزيارات المعلقة لنفس المنطقة فقط.
        if driver_changed and old_driver_id is not None:
            await db.execute(
                update(Visit)
                .where(
                    Visit.company_id == company_id,
                    Visit.driver_id == old_driver_id,
                    Visit.status == "Pending",
                    Visit.is_emergency.is_(False),
                    Visit.operational_date == route.dispatch_date,
                    Visit.shop_id.in_(zone_shop_ids),
                    Visit.work_session_id.is_(None),
                )
                .values(driver_id=route.driver_id)
            )
''',
        '''        # تغيير المندوب قبل بدء الجلسة ينقل كل Pending لنفس المنطقة، بما فيها الطوارئ.
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
''',
        "dispatch.py / transfer all pending visits and shortage ownership",
    )

    text = replace_once(
        text,
        '''        if target_status in {"closed", "waiting", "postponed"} and route.driver_id is not None:
            await db.execute(
                update(Visit)
                .where(
                    Visit.company_id == company_id,
                    Visit.driver_id == route.driver_id,
                    Visit.status == "Pending",
                    Visit.is_emergency.is_(False),
                    Visit.operational_date == route.dispatch_date,
                    Visit.shop_id.in_(zone_shop_ids),
                )
                .values(
                    driver_id=None,
                    work_session_id=None,
                )
            )
''',
        '''        if target_status in {"closed", "waiting", "postponed"} and route.driver_id is not None:
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
''',
        "dispatch.py / unassign all pending queue",
    )

    text = replace_once(
        text,
        '''                # التبني التلقائي يخص زيارات Route العادية فقط؛ زيارة الطوارئ لا تنتقل بين المندوبين ضمنياً.
                await db.execute(
                    update(Visit)
                    .where(
                        Visit.company_id == company_id,
                        Visit.shop_id.in_(shop_ids),
                        Visit.status == "Pending",
                        Visit.is_emergency.is_(False),
                        Visit.operational_date == company_local_date,
                        Visit.driver_id.is_(None),
                    )
                    .values(
                        driver_id=route.driver_id,
                        work_session_id=work_session_id,
                    )
                )
''',
        '''                # عند التفعيل يتبنى Route كل Pending غير المعيّن في منطقته، بما فيه الطوارئ.
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
''',
        "dispatch.py / adopt all pending queue",
    )

    # عند إعادة تفعيل Route مرتبط بجلسة منتهية لغرض undo، نبقي الزيارات مرتبطة
    # بنفس WorkSession التاريخية ولا نحوّلها إلى orphan مؤقت.
    text = replace_once(
        text,
        "                work_session_id = int(active_session.id) if active_session is not None else None\n",
        "                work_session_id = int(bound_session.id) if bound_session is not None else None\n",
        "dispatch.py / preserve bound session during undo recovery",
    )

    # BUG 4: Route جديد يرى النواقص غير المعيّنة أيضاً.
    text = replace_once(
        text,
        '''                        ShortageRequest.shop_id.in_(shop_ids),
                        ShortageRequest.driver_id == payload.driver_id,
                        ShortageRequest.status == "pending",
''',
        '''                        ShortageRequest.shop_id.in_(shop_ids),
                        or_(
                            ShortageRequest.driver_id == payload.driver_id,
                            ShortageRequest.driver_id.is_(None),
                        ),
                        ShortageRequest.status == "pending",
''',
        "dispatch.py / new route adopts unassigned shortage",
    )

    # نفس العرض عند إعادة تفعيل Route؛ حتى لو بقي سجل unassigned تاريخياً لا يضيع.
    text = replace_once(
        text,
        '''                            ShortageRequest.shop_id.in_(shop_ids),
                            ShortageRequest.driver_id == route.driver_id,
                            ShortageRequest.status == "pending",
''',
        '''                            ShortageRequest.shop_id.in_(shop_ids),
                            or_(
                                ShortageRequest.driver_id == route.driver_id,
                                ShortageRequest.driver_id.is_(None),
                            ),
                            ShortageRequest.status == "pending",
''',
        "dispatch.py / active route sees unassigned shortage",
    )

    # BUG 3: إذا لم يحدد الأدمن مندوباً، نتبنى مندوب Route النشط لنفس المنطقة
    # دفعة واحدة بدون N+1. إذا لا يوجد Route نشط يبقى الطلب unassigned كما تسمح السياسة.
    text = replace_once(
        text,
        '''        company_local_date = await get_company_local_date(db, company_id)
        owner_pairs = sorted({
            (int(item.driverId), int(item.shopId))
            for item in payload
            if item.driverId is not None
        })
''',
        '''        company_local_date = await get_company_local_date(db, company_id)

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
''',
        "dispatch.py / resolve unassigned shortage from active route",
    )

    text = replace_once(
        text,
        '''            driver_id = int(item.driverId) if item.driverId is not None else None
            db.add(ShortageRequest(
''',
        '''            driver_id = resolve_shortage_driver_id(item)
            db.add(ShortageRequest(
''',
        "dispatch.py / persist resolved shortage owner",
    )

    # أسماء Restore الرسمية مع backward compatibility في schema.
    text = text.replace('payload.mode == "selected"', 'payload.mode == "selected_shops"')
    if text.count('payload.mode == "selected_shops"') != 2:
        raise PatchError("dispatch.py / توقعت موضعين selected_shops.")
    return text


TRANSFORMS = {
    "models.py": transform_models,
    "schemas.py": transform_schemas,
    "services.py": transform_services,
    "api/driver.py": transform_driver,
    "api/dispatch.py": transform_dispatch,
}


def paths() -> dict[str, Path]:
    return {name: BACKEND / name for name in TARGETS}


def load_sources() -> dict[str, str]:
    result = {}
    for name, path in paths().items():
        if not path.is_file():
            raise PatchError(f"ملف الهدف غير موجود: {path}")
        result[name] = read_text(path)
    return result


def is_final(sources: dict[str, str]) -> bool:
    return all(PATCH_MARKERS[name] in sources[name] for name in TARGETS)


def classify(sources: dict[str, str]) -> str:
    current = {name: digest(text) for name, text in sources.items()}
    if all(current[name] == BASELINE_SHA256[name] for name in TARGETS):
        return "baseline"
    if is_final(sources):
        return "final"
    details = "\n".join(
        f"{name}: الحالي={current[name]} المتوقع={BASELINE_SHA256[name]}"
        for name in TARGETS
    )
    raise PatchError(
        "الملفات ليست نسخة GitHub المثبتة ولا الحالة النهائية؛ تم الرفض دون تعديل.\n"
        + details
    )


def transform_all(sources: dict[str, str]) -> dict[str, str]:
    result = {}
    for name in TARGETS:
        result[name] = TRANSFORMS[name](sources[name])
        validate_source(result[name], name)
    return result


def assert_idempotent(sources: dict[str, str]) -> None:
    second = transform_all(sources)
    changed = [
        name for name in TARGETS
        if normalize_newlines(second[name]) != normalize_newlines(sources[name])
    ]
    if changed:
        raise PatchError("فشل التشغيل الثاني للملفات: " + ", ".join(changed))


def function_source(tree: ast.AST, source: str, name: str) -> str:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            segment = ast.get_source_segment(source, node)
            if segment is None:
                break
            return segment
    raise PatchError(f"لم أجد الدالة المطلوبة للتدقيق: {name}")


class MutationGateAudit(ast.NodeVisitor):
    def __init__(self) -> None:
        self.stack: list[str] = []
        self.violations: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def current(self) -> str:
        return self.stack[-1] if self.stack else "<module>"

    def check_target(self, target: ast.AST, line: int) -> None:
        for item in ast.walk(target):
            if isinstance(item, ast.Attribute) and item.attr in {
                "on_hand_quantity",
                "reserved_quantity",
            }:
                if self.current() != "apply_inventory_movements_batch":
                    self.violations.append(
                        f"سطر {line}: كتابة {item.attr} داخل {self.current()}"
                    )

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self.check_target(target, node.lineno)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.check_target(node.target, node.lineno)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.check_target(node.target, node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "InventoryMovement":
            if self.current() != "apply_inventory_movements_batch":
                self.violations.append(
                    f"سطر {node.lineno}: إنشاء InventoryMovement داخل {self.current()}"
                )
        if isinstance(node.func, ast.Name) and node.func.id == "InventoryBalance":
            self.violations.append(
                f"سطر {node.lineno}: إنشاء InventoryBalance ORM مباشر داخل {self.current()}"
            )
        self.generic_visit(node)


def audit_visit_constructors(source: str, label: str) -> None:
    tree = ast.parse(source, filename=label)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "Visit":
            continue
        keys = {kw.arg for kw in node.keywords if kw.arg is not None}
        if "operational_date" not in keys:
            raise PatchError(f"{label}:{node.lineno}: Visit بلا operational_date.")


def static_hostile_audit(sources: dict[str, str]) -> None:
    models = sources["models.py"]
    schemas = sources["schemas.py"]
    services = sources["services.py"]
    driver = sources["api/driver.py"]
    dispatch = sources["api/dispatch.py"]

    checks = {
        "قيد Pending الجزئي": (
            "uq_visit_one_pending_owner_day" in models
            and "unique=True" in models
            and "status = 'Pending' AND driver_id IS NOT NULL" in models
        ),
        "سعر DRIVER_SHORTAGE المثبت": (
            "financial_unit_price_snapshot" in models
            and "financial_unit_price_snapshot" in services
        ),
        "أوضاع Restore الرسمية": all(
            x in schemas for x in (
                '"zone_only"',
                '"selected_shops"',
                '"shops_archived_by_same_zone"',
            )
        ),
        "حدود اليوم UTC": (
            "get_company_operational_day_utc_bounds" in services
            and "return start_utc, end_utc" in services
        ),
        "ملكية النقص للمندوب": (
            "ShortageRequest.driver_id.is_(None)" in driver
            and "ShortageRequest.driver_id == driver_id" in driver
        ),
        "بوابة نقل المحل": "_dispatch_blocking_shop_zone_move_ids" in dispatch,
        "Provenance Restore": "Shop.archived_due_to_zone_id == zone_id" in dispatch,
        "جدولة رقمية": "timedelta(days=int(zone.interval_days))" in dispatch,
        "Force Cancel": all(
            x in dispatch for x in (
                "async def force_cancel_handshake(",
                '"reservation_action": "RELEASE"',
                'header.status = "CANCELLED"',
                "HANDSHAKE_FORCE_CANCELLED",
            )
        ),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise PatchError("فشل التدقيق الثابت: " + ", ".join(failed))

    dispatch_tree = ast.parse(dispatch, filename="api/dispatch.py")
    force_cancel = function_source(dispatch_tree, dispatch, "force_cancel_handshake")
    if '"movement_kind": "PHYSICAL"' in force_cancel:
        raise PatchError("Force Cancel يحتوي PHYSICAL movement.")
    for marker in (
        "InventoryTransferHeader.company_id == company_id",
        "InventoryTransferLine.company_id == company_id",
        "SystemAuditLog(",
        "decision_reason = payload.reason",
    ):
        if marker not in force_cancel:
            raise PatchError(f"Force Cancel يفتقد: {marker}")

    # السطوح المتأثرة يجب أن تبقى tenant-scoped.
    policy_functions = {
        "api/dispatch.py": (
            "dispatch_route",
            "update_route_status",
            "add_shortages",
            "restore_zone",
            "force_cancel_handshake",
            "_dispatch_blocking_shop_zone_move_ids",
        ),
        "api/driver.py": ("start_work_session", "update_visit"),
        "services.py": (
            "get_company_local_date",
            "get_company_operational_day_utc_bounds",
            "post_approved_stocktake_adjustments",
            "apply_inventory_movements_batch",
        ),
    }
    for filename, names in policy_functions.items():
        source = sources[filename]
        tree = ast.parse(source, filename=filename)
        for name in names:
            segment = function_source(tree, source, name)
            if "company_id" not in segment:
                raise PatchError(f"{filename}.{name}: لا يوجد company_id.")

    audit_visit_constructors(driver, "api/driver.py")
    audit_visit_constructors(dispatch, "api/dispatch.py")

    gate = MutationGateAudit()
    gate.visit(ast.parse(services, filename="services.py"))
    if gate.violations:
        raise PatchError("خرق Mutation Gate:\n- " + "\n- ".join(gate.violations))

    for filename in ("api/driver.py", "api/dispatch.py"):
        tree = ast.parse(sources[filename], filename=filename)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"InventoryBalance", "InventoryMovement"}:
                    raise PatchError(
                        f"{filename}:{node.lineno}: إنشاء مباشر لـ {node.func.id}."
                    )

    if re.search(
        r'or_\(\s*Visit\.status == "Pending",\s*Visit\.operational_date == company_local_date',
        dispatch,
    ):
        raise PatchError("Completed ما زال يستطيع منع زيارة لاحقة بنفس اليوم.")

    update_route = function_source(dispatch_tree, dispatch, "update_route_status")
    for forbidden in (
        'Visit.is_emergency.is_(False)',
        'Visit.operational_date == route.dispatch_date',
    ):
        if forbidden in update_route:
            raise PatchError(f"update_route_status ما زال يحتوي: {forbidden}")
    for marker in (
        "bound_session.inventory_reconciled_at is not None",
        "work_session_id = int(bound_session.id) if bound_session is not None else None",
        "update(ShortageRequest)",
        "ShortageRequest.driver_id.is_(None)",
    ):
        if marker not in update_route:
            raise PatchError(f"update_route_status يفتقد: {marker}")

    dispatch_route_source = function_source(dispatch_tree, dispatch, "dispatch_route")
    if "ShortageRequest.driver_id.is_(None)" not in dispatch_route_source:
        raise PatchError("dispatch_route لا يتبنى shortage غير المعيّن.")

    add_shortages = function_source(dispatch_tree, dispatch, "add_shortages")
    for marker in (
        "active_route_driver_by_zone",
        "resolve_shortage_driver_id",
        'DispatchRoute.status == "active"',
        'Visit.status == "Pending"',
    ):
        if marker not in add_shortages:
            raise PatchError(f"add_shortages يفتقد: {marker}")
    if "visit.operational_date = company_local_date" in add_shortages:
        raise PatchError("add_shortages يعيد كتابة operational_date التاريخي.")


def mapper_and_postgres_ddl_check() -> None:
    backend_str = str(BACKEND.resolve())
    if backend_str not in sys.path:
        sys.path.insert(0, backend_str)

    models = importlib.import_module("models")
    from sqlalchemy.orm import configure_mappers
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable

    configure_mappers()
    dialect = postgresql.dialect()
    for table_name in (
        "companies",
        "zones",
        "shops",
        "visits",
        "shortage_requests",
        "inventory_movements",
        "inventory_transfer_headers",
    ):
        table = models.Base.metadata.tables.get(table_name)
        if table is None:
            raise PatchError(f"الجدول غير مسجل في metadata: {table_name}")
        ddl = str(CreateTable(table).compile(dialect=dialect))
        if not ddl.strip():
            raise PatchError(f"فشل DDL compile: {table_name}")

    visit_table = models.Base.metadata.tables["visits"]
    indexes = [
        idx for idx in visit_table.indexes
        if idx.name == "uq_visit_one_pending_owner_day"
    ]
    if len(indexes) != 1 or not indexes[0].unique:
        raise PatchError("Partial unique index للزيارات غير مسجل بشكل صحيح.")
    ddl = str(CreateIndex(indexes[0]).compile(dialect=dialect))
    if "WHERE status = 'Pending' AND driver_id IS NOT NULL" not in ddl:
        raise PatchError("شرط PostgreSQL partial unique index غير صحيح.")


def py_compile_targets() -> None:
    for name, path in paths().items():
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:
            raise PatchError(f"{name}: فشل py_compile: {exc}") from exc


def backup(sources: dict[str, str]) -> None:
    if BACKUP.exists():
        return
    for name, source in sources.items():
        path = BACKUP / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def restore(sources: dict[str, str]) -> None:
    for name, source in sources.items():
        try:
            (BACKEND / name).write_text(source, encoding="utf-8")
        except Exception:
            pass


def main() -> int:
    if not BACKEND.is_dir():
        raise PatchError("شغّل السكربت من جذر المشروع الذي يحتوي wa_backend.")

    original = load_sources()
    state = classify(original)

    if state == "baseline":
        print("تم تثبيت بصمات نسخة GitHub الحالية.")
        patched = transform_all(original)
        assert_idempotent(patched)
        static_hostile_audit(patched)
        backup(original)

        wrote = False
        try:
            for name in TARGETS:
                write_atomic(BACKEND / name, patched[name])
            wrote = True
            py_compile_targets()
            after = load_sources()
            assert_idempotent(after)
            static_hostile_audit(after)
            mapper_and_postgres_ddl_check()
        except Exception:
            if wrote:
                restore(original)
            raise

        manifest = {
            "baseline_commit": "9527d423b6756ac511de2ced23fedaaa46e8c888",
            "files": {name: digest(read_text(BACKEND / name)) for name in TARGETS},
        }
        (ROOT / ".dispatch_policy_hardening_v4_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print("تم تطبيق الباتش على الملفات الخمسة بنجاح.")
        print("نجح اختبار التشغيل الثاني وعدم التكرار.")
        print("نجح AST وpy_compile.")
        print("نجح تسجيل SQLAlchemy mappers وتجميع PostgreSQL DDL.")
        print("نجح التدقيق العدائي الثابت للعزل وMutation Gate.")
        print("لم يتم تجميد dispatch.py؛ يلزم PostgreSQL E2E وHostile Audit النهائي.")
        return 0

    # لا نخرج مبكراً عند التشغيل الثاني؛ نعيد كل البوابات.
    print("الملفات تحمل الحالة النهائية؛ سيتم إعادة التحقق الكامل.")
    second = transform_all(original)
    if any(
        normalize_newlines(second[name]) != normalize_newlines(original[name])
        for name in TARGETS
    ):
        raise PatchError("الحالة تحمل علامات الباتش لكنها ليست idempotent.")
    assert_idempotent(original)
    static_hostile_audit(original)
    py_compile_targets()
    mapper_and_postgres_ddl_check()
    print("نجح التشغيل الثاني: لا تغييرات إضافية وجميع بوابات التحقق سليمة.")
    print("لم يتم تجميد dispatch.py؛ يلزم PostgreSQL E2E وHostile Audit النهائي.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PatchError as exc:
        print(f"فشل الباتش: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"فشل غير متوقع أثناء الباتش: {exc}", file=sys.stderr)
        raise
