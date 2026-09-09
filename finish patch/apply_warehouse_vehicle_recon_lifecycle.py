from __future__ import annotations

import ast
import os
import py_compile
from pathlib import Path

ROOT = Path.cwd()
BACKEND = ROOT / "wa_backend"

TARGETS = {
    "models": BACKEND / "models.py",
    "services": BACKEND / "services.py",
    "warehouse": BACKEND / "api" / "warehouse.py",
}


def normalize_newlines(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected exactly one match, found {count}. "
            "لم يتم تعديل أي ملف."
        )
    return text.replace(old, new, 1)


SERVICE_HELPER = '''# تثبيت أن VEHICLE_RECON مرتبط بجلسة عمل منتهية وغير مسواة وبنفس السيارة داخل Tenant واحد.
async def validate_vehicle_recon_work_session(
    db_session: AsyncSession,
    *,
    company_id: int,
    work_session_id: int,
    vehicle_id: int,
) -> WorkSession:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        work_session_id = _strict_int(
            work_session_id, "work_session_id", minimum=1
        )
        vehicle_id = _strict_int(vehicle_id, "vehicle_id", minimum=1)
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    work_session = (
        await db_session.execute(
            select(WorkSession)
            .execution_options(populate_existing=True)
            .filter_by(
                company_id=company_id,
                id=work_session_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if work_session is None:
        raise InventoryMutationError(
            "جلسة العمل غير موجودة أو لا تتبع الشركة."
        )

    if work_session.end_time is None:
        raise InventoryMutationError(
            "لا يمكن بدء أو ترحيل VEHICLE_RECON قبل إنهاء جلسة العمل."
        )

    if work_session.is_settled:
        raise InventoryMutationError(
            "جلسة العمل تمت تسويتها مسبقاً ولا تقبل VEHICLE_RECON جديداً."
        )

    route_id = (
        await db_session.execute(
            select(DispatchRoute.id).filter(
                DispatchRoute.company_id == company_id,
                DispatchRoute.work_session_id == work_session.id,
                DispatchRoute.driver_id == work_session.driver_id,
                DispatchRoute.vehicle_id == vehicle_id,
            )
            .order_by(DispatchRoute.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if route_id is None:
        raise InventoryMutationError(
            "جلسة العمل المحددة لا ترتبط بهذه السيارة داخل الشركة."
        )

    return work_session


'''


def patch_models(text: str) -> str:
    if "chk_work_session_settlement_requires_end" in text:
        raise RuntimeError("models.py: WorkSession lifecycle check موجود مسبقاً.")
    if "uq_vehicle_recon_work_session" in text:
        raise RuntimeError("models.py: VEHICLE_RECON unique index موجود مسبقاً.")

    old = '''        CheckConstraint(
            'end_time IS NULL OR end_time >= start_time',
            name='chk_work_session_time_order'
        ),
'''
    new = '''        CheckConstraint(
            'end_time IS NULL OR end_time >= start_time',
            name='chk_work_session_time_order'
        ),
        CheckConstraint(
            'is_settled IS FALSE OR end_time IS NOT NULL',
            name='chk_work_session_settlement_requires_end'
        ),
'''
    text = replace_once(text, old, new, "models.py WorkSession settlement check")

    old = '''        CheckConstraint("related_work_session_id IS NULL OR stocktake_type = 'VEHICLE_RECON'", name='chk_stocktake_work_session_scope'),
'''
    new = '''        CheckConstraint(
            "((stocktake_type = 'VEHICLE_RECON' AND related_work_session_id IS NOT NULL) OR "
            "(stocktake_type <> 'VEHICLE_RECON' AND related_work_session_id IS NULL))",
            name='chk_stocktake_work_session_scope'
        ),
'''
    text = replace_once(text, old, new, "models.py VEHICLE_RECON work-session scope")

    old = '''        Index('uq_active_full_stocktake_location', 'company_id', 'location_id', unique=True,
              postgresql_where=text("stocktake_type IN ('FULL_COUNT', 'VEHICLE_RECON') AND status IN ('DRAFT', 'COUNTING', 'PENDING_REVIEW', 'RECOUNT_REQUIRED', 'APPROVED')")),
'''
    new = '''        Index(
            'uq_vehicle_recon_work_session',
            'company_id',
            'related_work_session_id',
            unique=True,
            postgresql_where=text(
                "stocktake_type = 'VEHICLE_RECON' "
                "AND related_work_session_id IS NOT NULL "
                "AND status <> 'CANCELLED'"
            ),
        ),
        Index('uq_active_full_stocktake_location', 'company_id', 'location_id', unique=True,
              postgresql_where=text("stocktake_type IN ('FULL_COUNT', 'VEHICLE_RECON') AND status IN ('DRAFT', 'COUNTING', 'PENDING_REVIEW', 'RECOUNT_REQUIRED', 'APPROVED')")),
'''
    text = replace_once(text, old, new, "models.py VEHICLE_RECON unique partial index")
    return text


def patch_services(text: str) -> str:
    if "async def validate_vehicle_recon_work_session(" in text:
        raise RuntimeError("services.py: VEHICLE_RECON helper موجود مسبقاً.")

    text = replace_once(
        text,
        "    WorkSession,\n    Visit,\n",
        "    WorkSession,\n    DispatchRoute,\n    Visit,\n",
        "services.py DispatchRoute import",
    )

    text = replace_once(
        text,
        "class InventoryMutationError(Exception):\n    pass\n\n\n",
        "class InventoryMutationError(Exception):\n    pass\n\n\n" + SERVICE_HELPER,
        "services.py VEHICLE_RECON helper insertion",
    )

    old = '''    location_row = (
        await db_session.execute(
            select(
                InventoryLocation.location_type,
                InventoryLocation.is_active,
            ).filter_by(
                company_id=company_id,
                id=session.location_id,
            ).with_for_update(read=True)
        )
    ).one_or_none()
    if location_row is None:
        raise InventoryMutationError("موقع جلسة الجرد غير موجود أو لا يتبع الشركة.")
    location_type, location_is_active = location_row
    expected_location_type = (
        "VEHICLE" if session.stocktake_type == "VEHICLE_RECON" else "WAREHOUSE"
    )
    if location_type != expected_location_type:
        raise InventoryMutationError(
            "نوع موقع جلسة الجرد لا يطابق نوع الجرد المعتمد."
        )
    if session.status == "APPROVED" and not location_is_active:
        raise InventoryMutationError(
            "لا يمكن ترحيل جرد جديد على موقع مخزون غير فعال."
        )

'''
    new = '''    location_row = (
        await db_session.execute(
            select(
                InventoryLocation.location_type,
                InventoryLocation.is_active,
                InventoryLocation.vehicle_id,
            ).filter_by(
                company_id=company_id,
                id=session.location_id,
            ).with_for_update(read=True)
        )
    ).one_or_none()
    if location_row is None:
        raise InventoryMutationError("موقع جلسة الجرد غير موجود أو لا يتبع الشركة.")
    location_type, location_is_active, location_vehicle_id = location_row
    expected_location_type = (
        "VEHICLE" if session.stocktake_type == "VEHICLE_RECON" else "WAREHOUSE"
    )
    if location_type != expected_location_type:
        raise InventoryMutationError(
            "نوع موقع جلسة الجرد لا يطابق نوع الجرد المعتمد."
        )
    if session.status == "APPROVED" and not location_is_active:
        raise InventoryMutationError(
            "لا يمكن ترحيل جرد جديد على موقع مخزون غير فعال."
        )

    # POSTED replay يبقى idempotent حتى لو تمت التسوية المالية لاحقاً.
    if (
        session.stocktake_type == "VEHICLE_RECON"
        and session.status == "APPROVED"
    ):
        if location_vehicle_id is None:
            raise InventoryMutationError(
                "موقع VEHICLE_RECON لا يحمل vehicle_id صالحاً."
            )
        await validate_vehicle_recon_work_session(
            db_session,
            company_id=company_id,
            work_session_id=session.related_work_session_id,
            vehicle_id=location_vehicle_id,
        )

'''
    text = replace_once(text, old, new, "services.py posting VEHICLE_RECON revalidation")
    return text


def patch_warehouse(text: str) -> str:
    text = replace_once(
        text,
        "    get_company_local_date,\n    begin_idempotent_operation,\n",
        "    get_company_local_date,\n    validate_vehicle_recon_work_session,\n    begin_idempotent_operation,\n",
        "warehouse.py VEHICLE_RECON helper import",
    )

    old = '''        if payload.stocktake_type == 'VEHICLE_RECON':
            if location.vehicle_id is None:
                raise HTTPException(status_code=409, detail="موقع السيارة لا يحمل vehicle_id صالحاً.")
            route_id = (
                await db.execute(
                    select(DispatchRoute.id).filter(
                        DispatchRoute.company_id == company_id,
                        DispatchRoute.work_session_id == payload.related_work_session_id,
                        DispatchRoute.vehicle_id == location.vehicle_id,
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if route_id is None:
                raise HTTPException(
                    status_code=409,
                    detail="جلسة العمل المحددة لا ترتبط بهذه السيارة داخل شركتك؛ تم رفض VEHICLE_RECON.",
                )

        # Exclusive فقط أثناء إنشاء Snapshot/Lock؛ بعد commit يبقى القفل الجراحي للنطاق وحده.
        await acquire_inventory_location_guard(db, company_id, payload.location_id, exclusive=True)

'''
    new = '''        # ترتيب القفل ثابت: موقع المخزون أولاً، ثم WorkSession.
        # هذا يطابق posting ويمنع سباق Start/Approve مع التسوية.
        await acquire_inventory_location_guard(
            db,
            company_id,
            payload.location_id,
            exclusive=True,
        )

        if payload.stocktake_type == 'VEHICLE_RECON':
            if location.vehicle_id is None:
                raise HTTPException(
                    status_code=409,
                    detail="موقع السيارة لا يحمل vehicle_id صالحاً.",
                )

            try:
                await validate_vehicle_recon_work_session(
                    db,
                    company_id=company_id,
                    work_session_id=payload.related_work_session_id,
                    vehicle_id=location.vehicle_id,
                )
            except InventoryMutationError as exc:
                raise HTTPException(
                    status_code=409,
                    detail=str(exc),
                ) from exc

            existing_recon_id = (
                await db.execute(
                    select(StocktakeSession.id).filter(
                        StocktakeSession.company_id == company_id,
                        StocktakeSession.stocktake_type == 'VEHICLE_RECON',
                        StocktakeSession.related_work_session_id
                        == payload.related_work_session_id,
                        StocktakeSession.status != 'CANCELLED',
                    )
                    .order_by(StocktakeSession.id.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            if existing_recon_id is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "جلسة العمل مرتبطة مسبقاً بـ VEHICLE_RECON غير ملغى؛ "
                        "لا يمكن إنشاء تسوية مخزون ثانية لنفس الجلسة."
                    ),
                )

'''
    text = replace_once(text, old, new, "warehouse.py VEHICLE_RECON start lifecycle")
    return text


def validate_cross_file(prepared: dict[str, str]) -> None:
    required = {
        "models": (
            "chk_work_session_settlement_requires_end",
            "uq_vehicle_recon_work_session",
            "stocktake_type <> 'VEHICLE_RECON' AND related_work_session_id IS NULL",
        ),
        "services": (
            "async def validate_vehicle_recon_work_session(",
            "DispatchRoute,",
            'session.status == "APPROVED"',
            "location_vehicle_id",
        ),
        "warehouse": (
            "validate_vehicle_recon_work_session,",
            "existing_recon_id",
            "StocktakeSession.status != 'CANCELLED'",
        ),
    }
    for name, tokens in required.items():
        for token in tokens:
            if token not in prepared[name]:
                raise RuntimeError(f"{name}: missing invariant after patch: {token}")

    start = prepared["warehouse"].index('@router.post("/warehouse/unified/stocktake/start"')
    end = prepared["warehouse"].index(
        '@router.get("/warehouse/unified/stocktake/{session_id}/count-sheet"',
        start,
    )
    if "route_id = (" in prepared["warehouse"][start:end]:
        raise RuntimeError(
            "warehouse.py: legacy inline VEHICLE_RECON route validation ما زال موجوداً."
        )


def main() -> None:
    if not BACKEND.is_dir():
        raise SystemExit("ERROR: شغّل السكربت من جذر مشروع wanasah.")

    for name, path in TARGETS.items():
        if not path.is_file():
            raise SystemExit(f"ERROR: الملف مفقود ({name}): {path}")

    originals: dict[str, bytes] = {}
    newline_styles: dict[str, str] = {}
    prepared: dict[str, str] = {}

    for name, path in TARGETS.items():
        raw = path.read_bytes()
        originals[name] = raw
        newline_styles[name] = "CRLF" if b"\r\n" in raw else "LF"
        text = normalize_newlines(raw).decode("utf-8")

        if name == "models":
            text = patch_models(text)
        elif name == "services":
            text = patch_services(text)
        else:
            text = patch_warehouse(text)

        ast.parse(text, filename=str(path))
        prepared[name] = text

    validate_cross_file(prepared)

    temp_paths: dict[str, Path] = {}
    replaced: list[str] = []

    try:
        for name, path in TARGETS.items():
            output = prepared[name].encode("utf-8")
            if newline_styles[name] == "CRLF":
                output = output.replace(b"\n", b"\r\n")

            tmp = path.with_suffix(path.suffix + ".vehicle_recon.tmp")
            tmp.write_bytes(output)
            py_compile.compile(str(tmp), doraise=True)
            temp_paths[name] = tmp

        try:
            for name in ("models", "services", "warehouse"):
                os.replace(temp_paths[name], TARGETS[name])
                replaced.append(name)
        except Exception:
            for name in replaced:
                TARGETS[name].write_bytes(originals[name])
            raise

    finally:
        for tmp in temp_paths.values():
            if tmp.exists():
                tmp.unlink()

    print("WAREHOUSE_VEHICLE_RECON_LIFECYCLE_OK")
    print("models.py: DB lifecycle invariants added")
    print("services.py: ended/unsettled/session-vehicle guard added")
    print("warehouse.py: duplicate/race-safe VEHICLE_RECON start enabled")


if __name__ == "__main__":
    main()
