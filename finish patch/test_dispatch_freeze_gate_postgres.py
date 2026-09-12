from __future__ import annotations

import ast
import asyncio
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError

import test_dispatch_policy_operational_postgres as base

from database import AsyncSessionLocal
from models import (
    DispatchRoute,
    Driver,
    InventoryBalance,
    InventoryLocation,
    ShortageRequest,
    Shop,
    Vehicle,
    Visit,
    WorkSession,
    Zone,
)
from schemas import CreateShortageItem, DispatchRouteRequest, EditShopDetailsRequest, UpdateRouteStatusRequest
from api.dispatch import (
    add_shortages,
    dispatch_route,
    edit_shop_details,
    undo_end_work,
    update_route_status,
)


ROOT = Path(__file__).resolve().parent
DISPATCH_PATH = ROOT / "wa_backend" / "api" / "dispatch.py"
DATABASE_PATH = ROOT / "wa_backend" / "database.py"
DEPENDENCIES_PATH = ROOT / "wa_backend" / "api" / "dependencies.py"


def _fail(message: str) -> None:
    raise AssertionError(message)


def static_dispatch_freeze_audit() -> None:
    source = DISPATCH_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DISPATCH_PATH))

    # 1) لا محرك مخزون قديم داخل Dispatch.
    banned_legacy_names = {
        "MainWarehouse",
        "VehicleLoad",
        "SessionInventory",
        "InventoryTransfer",  # الاسم القديم فقط؛ لا يصطدم Header/Line
        "WarehouseLedger",
        "InventoryLedger",
    }
    for name in banned_legacy_names:
        if re.search(rf"\b{re.escape(name)}\b", source):
            _fail(f"STATIC_LEGACY_ENGINE_PRESENT:{name}")

    banned_legacy_table_tokens = {
        "main_warehouse",
        "vehicle_load",
        "session_inventory",
        "warehouse_ledger",
        "inventory_ledger",
    }
    lowered = source.lower()
    for token in banned_legacy_table_tokens:
        if re.search(
            rf"(?<![a-z0-9_]){re.escape(token)}(?![a-z0-9_])",
            lowered,
        ):
            _fail(f"STATIC_LEGACY_TABLE_PRESENT:{token}")

    # 2) Mutation Gate: Dispatch لا ينشئ Balance/Movement مباشرة ولا يكتب حقول الرصيد.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = node.func.id if isinstance(node.func, ast.Name) else None
            if func_name in {"InventoryBalance", "InventoryMovement"}:
                _fail(f"STATIC_DIRECT_INVENTORY_CONSTRUCTOR:{func_name}:line={node.lineno}")

            if func_name in {"update", "delete"} and node.args:
                first = node.args[0]
                if isinstance(first, ast.Name) and first.id == "InventoryBalance":
                    _fail(f"STATIC_DIRECT_BALANCE_MUTATION:{func_name}:line={node.lineno}")

        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = []
            if isinstance(node, ast.Assign):
                targets.extend(node.targets)
            else:
                targets.append(node.target)
            for target in targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Attribute) and sub.attr in {
                        "on_hand_quantity",
                        "reserved_quantity",
                    }:
                        _fail(f"STATIC_DIRECT_BALANCE_FIELD_WRITE:{sub.attr}:line={node.lineno}")

    if re.search(
        r"\b(?:update|delete\s+from|insert\s+into)\s+inventory_balances\b",
        source,
        flags=re.IGNORECASE,
    ):
        _fail("STATIC_RAW_SQL_INVENTORY_BALANCE_MUTATION")

    # 3) كل إنشاء لكيان Tenant داخل Dispatch يحمل company_id صراحة.
    tenant_constructors = {
        "SystemAuditLog",
        "DispatchRoute",
        "Visit",
        "ShortageRequest",
        "Shop",
        "Zone",
        "ImportLog",
        "DispatchLoadPlanLine",
        "InventoryTransferHeader",
        "InventoryTransferLine",
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in tenant_constructors:
            continue
        kw_names = {kw.arg for kw in node.keywords if kw.arg is not None}
        if "company_id" not in kw_names:
            _fail(
                f"STATIC_TENANT_CONSTRUCTOR_WITHOUT_COMPANY:"
                f"{node.func.id}:line={node.lineno}"
            )

    # 4) BUG 1: add_shortages ممنوع أن يفصل Visit موجودة عن WorkSession.
    start = source.index("async def add_shortages(")
    end = source.index("@router.delete", start)
    add_shortages_src = source[start:end]
    if "visit.work_session_id = None" in add_shortages_src:
        _fail("STATIC_ADD_SHORTAGES_SESSION_DETACHMENT")

    # 5) بوابات V4 الجوهرية يجب أن تبقى موجودة.
    required_markers = {
        "RECOVERY_UNRECONCILED_GATE": "bound_session.inventory_reconciled_at is not None",
        "BOUND_SESSION_VISIT_BINDING": "work_session_id = int(bound_session.id) if bound_session is not None else None",
        "UNASSIGNED_SHORTAGE_VISIBILITY": "ShortageRequest.driver_id.is_(None)",
        "ACTIVE_ROUTE_SHORTAGE_RESOLVER": "active_route_driver_by_zone",
        "FORCE_CANCEL_RESERVATION_ONLY": '"movement_kind": "RESERVATION"',
        "UNIFIED_ENGINE_CALL": "apply_inventory_movements_batch",
    }
    for label, marker in required_markers.items():
        if marker not in source:
            _fail(f"STATIC_REQUIRED_MARKER_MISSING:{label}")

    # 6) RLS connection hygiene: reset tenant on every checkout and set it before DB auth query.
    db_src = DATABASE_PATH.read_text(encoding="utf-8")
    dep_src = DEPENDENCIES_PATH.read_text(encoding="utf-8")
    if '@event.listens_for(engine.sync_engine, "checkout")' not in db_src:
        _fail("STATIC_RLS_CHECKOUT_HOOK_MISSING")
    if "set_config('app.current_tenant', '', false)" not in db_src:
        _fail("STATIC_RLS_EMPTY_CONTEXT_RESET_MISSING")
    tenant_set_pos = dep_src.find("tenant_context.set(int(company_id))")
    first_execute_pos = dep_src.find("await db.execute")
    if tenant_set_pos < 0 or first_execute_pos < 0 or tenant_set_pos > first_execute_pos:
        _fail("STATIC_TENANT_CONTEXT_NOT_SET_BEFORE_AUTH_DB_QUERY")
    if "set_config('app.current_tenant', :c, false)" not in dep_src:
        _fail("STATIC_EXPLICIT_CONNECTION_TENANT_SET_MISSING")

    print("STATIC_DISPATCH_ENGINE_AUDIT=OK")
    print("STATIC_TENANT_CONSTRUCTOR_AUDIT=OK")
    print("STATIC_RLS_CONTEXT_HYGIENE=OK")


async def seed_extra_assets(fx: dict) -> dict:
    suffix = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        await base.set_tenant(db, fx["company"])
        admin = (
            await db.execute(
                select(Driver).where(
                    Driver.company_id == fx["company"],
                    Driver.id == fx["admin"],
                )
            )
        ).scalar_one()

        driver_d = Driver(
            company_id=fx["company"],
            username=f"freeze_d_{suffix}",
            password_hash=admin.password_hash,
            full_name="Freeze Driver D",
            is_active=True,
            is_admin=False,
        )
        driver_e = Driver(
            company_id=fx["company"],
            username=f"freeze_e_{suffix}",
            password_hash=admin.password_hash,
            full_name="Freeze Driver E",
            is_active=True,
            is_admin=False,
        )
        zone_no_route = Zone(
            company_id=fx["company"],
            name=f"Freeze No Route {suffix}",
            is_active=True,
        )
        zone_dispatch = Zone(
            company_id=fx["company"],
            name=f"Freeze Dispatch {suffix}",
            is_active=True,
        )
        db.add_all([driver_d, driver_e, zone_no_route, zone_dispatch])
        await db.flush()

        shop_transfer = Shop(
            company_id=fx["company"],
            name=f"Freeze Transfer Shop {suffix}",
            zone_id=fx["zone_schedule"],
            current_balance=0,
            max_debt_limit=0,
            is_active=True,
            is_archived=False,
        )
        shop_no_route = Shop(
            company_id=fx["company"],
            name=f"Freeze No Route Shop {suffix}",
            zone_id=zone_no_route.id,
            current_balance=0,
            max_debt_limit=0,
            is_active=True,
            is_archived=False,
        )
        shop_dispatch = Shop(
            company_id=fx["company"],
            name=f"Freeze Dispatch Shop {suffix}",
            zone_id=zone_dispatch.id,
            current_balance=0,
            max_debt_limit=0,
            is_active=True,
            is_archived=False,
        )
        vehicle_e = Vehicle(
            company_id=fx["company"],
            plate_number=f"FE-{suffix[:7]}",
            maintenance_status="Active",
            is_active=True,
        )
        db.add_all([shop_transfer, shop_no_route, shop_dispatch, vehicle_e])
        await db.flush()

        vehicle_e_loc = InventoryLocation(
            company_id=fx["company"],
            name=f"Freeze Vehicle E {suffix}",
            code=f"FVE-{suffix}",
            location_type="VEHICLE",
            vehicle_id=vehicle_e.id,
            is_active=True,
        )
        db.add(vehicle_e_loc)

        route_schedule = (
            await db.execute(
                select(DispatchRoute).where(
                    DispatchRoute.company_id == fx["company"],
                    DispatchRoute.id == fx["route_schedule"],
                )
            )
        ).scalar_one()
        driver_c_id = int(route_schedule.driver_id)
        route_shortage = (
            await db.execute(
                select(DispatchRoute).where(
                    DispatchRoute.company_id == fx["company"],
                    DispatchRoute.work_session_id == fx["ws_shortage"],
                )
            )
        ).scalar_one()

        await db.commit()
        return {
            "driver_d": int(driver_d.id),
            "driver_e": int(driver_e.id),
            "driver_c": driver_c_id,
            "zone_no_route": int(zone_no_route.id),
            "zone_dispatch": int(zone_dispatch.id),
            "shop_transfer": int(shop_transfer.id),
            "shop_no_route": int(shop_no_route.id),
            "shop_dispatch": int(shop_dispatch.id),
            "vehicle_e": int(vehicle_e.id),
            "vehicle_e_loc": int(vehicle_e_loc.id),
            "route_shortage": int(route_shortage.id),
        }


async def test_active_session_shortage_preservation(fx: dict) -> None:
    async with AsyncSessionLocal() as db:
        await base.set_tenant(db, fx["company"])
        visit = Visit(
            company_id=fx["company"],
            driver_id=fx["driver_a"],
            shop_id=fx["shop"],
            work_session_id=fx["ws_a"],
            operational_date=fx["local_day"],
            status="Pending",
            outcome="Pending",
            is_emergency=False,
        )
        db.add(visit)
        await db.commit()
        visit_id = int(visit.id)

    async with AsyncSessionLocal() as db:
        admin = await base.load_driver(db, fx["company"], fx["admin"])
        await add_shortages(
            payload=[
                CreateShortageItem(
                    shopId=fx["shop"],
                    zoneId=fx["zone_main"],
                    productId=fx["variant_a"],
                    driverId=None,
                    quantity=1,
                )
            ],
            db=db,
            current_admin=admin,
        )

    async with AsyncSessionLocal() as db:
        await base.set_tenant(db, fx["company"])
        visit = (
            await db.execute(
                select(Visit).where(
                    Visit.company_id == fx["company"],
                    Visit.id == visit_id,
                )
            )
        ).scalar_one()
        shortage = (
            await db.execute(
                select(ShortageRequest).where(
                    ShortageRequest.company_id == fx["company"],
                    ShortageRequest.shop_id == fx["shop"],
                    ShortageRequest.product_variant_id == fx["variant_a"],
                    ShortageRequest.status == "pending",
                )
            )
        ).scalar_one()
        if int(visit.work_session_id or 0) != int(fx["ws_a"]):
            _fail(f"ACTIVE_SESSION_VISIT_DETACHED:{visit.work_session_id}")
        if not visit.is_emergency:
            _fail("ACTIVE_SESSION_VISIT_NOT_MARKED_EMERGENCY")
        if int(shortage.driver_id or 0) != int(fx["driver_a"]):
            _fail(f"UNASSIGNED_SHORTAGE_NOT_AUTO_RESOLVED:{shortage.driver_id}")

        await db.execute(
            delete(ShortageRequest).where(
                ShortageRequest.company_id == fx["company"],
                ShortageRequest.id == shortage.id,
            )
        )
        await db.execute(
            delete(Visit).where(
                Visit.company_id == fx["company"],
                Visit.id == visit_id,
            )
        )
        await db.commit()

    print("FREEZE_ACTIVE_SESSION_VISIT_PRESERVATION=OK")
    print("FREEZE_UNASSIGNED_SHORTAGE_ACTIVE_ROUTE_RESOLUTION=OK")


async def test_no_route_shortage_stays_unassigned(fx: dict, ex: dict) -> None:
    async with AsyncSessionLocal() as db:
        admin = await base.load_driver(db, fx["company"], fx["admin"])
        await add_shortages(
            payload=[
                CreateShortageItem(
                    shopId=ex["shop_no_route"],
                    zoneId=ex["zone_no_route"],
                    productId=fx["variant_a"],
                    driverId=None,
                    quantity=2,
                )
            ],
            db=db,
            current_admin=admin,
        )

    async with AsyncSessionLocal() as db:
        await base.set_tenant(db, fx["company"])
        shortage = (
            await db.execute(
                select(ShortageRequest).where(
                    ShortageRequest.company_id == fx["company"],
                    ShortageRequest.shop_id == ex["shop_no_route"],
                    ShortageRequest.product_variant_id == fx["variant_a"],
                    ShortageRequest.status == "pending",
                )
            )
        ).scalar_one()
        visits = (
            await db.execute(
                select(Visit.id).where(
                    Visit.company_id == fx["company"],
                    Visit.shop_id == ex["shop_no_route"],
                    Visit.status == "Pending",
                )
            )
        ).scalars().all()
        if shortage.driver_id is not None:
            _fail(f"NO_ROUTE_SHORTAGE_SHOULD_REMAIN_UNASSIGNED:{shortage.driver_id}")
        if visits:
            _fail(f"NO_ROUTE_SHORTAGE_CREATED_ORPHAN_VISIT:{visits}")

    print("FREEZE_NO_ROUTE_SHORTAGE_REMAINS_UNASSIGNED=OK")


async def test_route_queue_ownership_and_dates(fx: dict, ex: dict) -> None:
    prior_day = fx["local_day"] - timedelta(days=1)

    async with AsyncSessionLocal() as db:
        await base.set_tenant(db, fx["company"])
        visit = Visit(
            company_id=fx["company"],
            driver_id=ex["driver_c"],
            shop_id=ex["shop_transfer"],
            operational_date=prior_day,
            status="Pending",
            outcome="Pending",
            is_emergency=True,
        )
        shortage = ShortageRequest(
            company_id=fx["company"],
            zone_id=fx["zone_schedule"],
            shop_id=ex["shop_transfer"],
            driver_id=ex["driver_c"],
            product_variant_id=fx["variant_a"],
            quantity=1,
            status="pending",
        )
        db.add_all([visit, shortage])
        await db.commit()
        visit_id = int(visit.id)
        shortage_id = int(shortage.id)

    # Driver change + activation: both Visit and Shortage ownership must move together.
    async with AsyncSessionLocal() as db:
        admin = await base.load_driver(db, fx["company"], fx["admin"])
        await update_route_status(
            route_id=fx["route_schedule"],
            payload=UpdateRouteStatusRequest(
                status="active",
                driverId=ex["driver_d"],
            ),
            db=db,
            current_admin=admin,
        )

    async with AsyncSessionLocal() as db:
        await base.set_tenant(db, fx["company"])
        visit = (
            await db.execute(
                select(Visit).where(
                    Visit.company_id == fx["company"],
                    Visit.id == visit_id,
                )
            )
        ).scalar_one()
        shortage = (
            await db.execute(
                select(ShortageRequest).where(
                    ShortageRequest.company_id == fx["company"],
                    ShortageRequest.id == shortage_id,
                )
            )
        ).scalar_one()
        if int(visit.driver_id or 0) != ex["driver_d"]:
            _fail(f"EMERGENCY_VISIT_DRIVER_TRANSFER_FAILED:{visit.driver_id}")
        if int(shortage.driver_id or 0) != ex["driver_d"]:
            _fail(f"SHORTAGE_OWNER_TRANSFER_FAILED:{shortage.driver_id}")
        if visit.operational_date != prior_day:
            _fail(
                f"PRIOR_DAY_PENDING_DATE_REWRITTEN:"
                f"{visit.operational_date}!={prior_day}"
            )

    # Postpone must orphan both together.
    async with AsyncSessionLocal() as db:
        admin = await base.load_driver(db, fx["company"], fx["admin"])
        await update_route_status(
            route_id=fx["route_schedule"],
            payload=UpdateRouteStatusRequest(status="postponed"),
            db=db,
            current_admin=admin,
        )

    async with AsyncSessionLocal() as db:
        await base.set_tenant(db, fx["company"])
        visit = (
            await db.execute(select(Visit).where(Visit.id == visit_id))
        ).scalar_one()
        shortage = (
            await db.execute(select(ShortageRequest).where(ShortageRequest.id == shortage_id))
        ).scalar_one()
        if visit.driver_id is not None or visit.work_session_id is not None:
            _fail(
                f"POSTPONED_VISIT_NOT_ORPHANED:"
                f"driver={visit.driver_id},session={visit.work_session_id}"
            )
        if shortage.driver_id is not None:
            _fail(f"POSTPONED_SHORTAGE_NOT_UNASSIGNED:{shortage.driver_id}")
        if visit.operational_date != prior_day:
            _fail("POSTPONED_PRIOR_DAY_DATE_CORRUPTED")

    # Reactivation must adopt prior-day orphan without duplication or date rewrite.
    async with AsyncSessionLocal() as db:
        admin = await base.load_driver(db, fx["company"], fx["admin"])
        await update_route_status(
            route_id=fx["route_schedule"],
            payload=UpdateRouteStatusRequest(status="active"),
            db=db,
            current_admin=admin,
        )

    async with AsyncSessionLocal() as db:
        await base.set_tenant(db, fx["company"])
        pending = (
            await db.execute(
                select(Visit).where(
                    Visit.company_id == fx["company"],
                    Visit.shop_id == ex["shop_transfer"],
                    Visit.status == "Pending",
                )
            )
        ).scalars().all()
        shortage = (
            await db.execute(select(ShortageRequest).where(ShortageRequest.id == shortage_id))
        ).scalar_one()
        if len(pending) != 1:
            _fail(f"POSTPONED_ROUTE_DUPLICATED_PENDING:{len(pending)}")
        visit = pending[0]
        if int(visit.id) != visit_id:
            _fail(f"PRIOR_DAY_ORPHAN_REPLACED_INSTEAD_OF_ADOPTED:{visit.id}")
        if int(visit.driver_id or 0) != ex["driver_d"]:
            _fail(f"PRIOR_DAY_ORPHAN_NOT_ADOPTED:{visit.driver_id}")
        if int(shortage.driver_id or 0) != ex["driver_d"]:
            _fail(f"PRIOR_DAY_SHORTAGE_NOT_ADOPTED:{shortage.driver_id}")
        if visit.operational_date != prior_day:
            _fail("PRIOR_DAY_ORPHAN_DATE_REWRITTEN_ON_ADOPTION")

        # Convert this visit to a completed visit today for the next invariant.
        visit.status = "Completed"
        visit.outcome = "NoSale"
        visit.operational_date = fx["local_day"]
        visit.work_session_id = None
        await db.commit()

    # Completed today must not block a later Pending for the same shop.
    async with AsyncSessionLocal() as db:
        admin = await base.load_driver(db, fx["company"], fx["admin"])
        await update_route_status(
            route_id=fx["route_schedule"],
            payload=UpdateRouteStatusRequest(status="postponed"),
            db=db,
            current_admin=admin,
        )
    async with AsyncSessionLocal() as db:
        admin = await base.load_driver(db, fx["company"], fx["admin"])
        await update_route_status(
            route_id=fx["route_schedule"],
            payload=UpdateRouteStatusRequest(status="active"),
            db=db,
            current_admin=admin,
        )

    async with AsyncSessionLocal() as db:
        await base.set_tenant(db, fx["company"])
        visits = (
            await db.execute(
                select(Visit).where(
                    Visit.company_id == fx["company"],
                    Visit.shop_id == ex["shop_transfer"],
                ).order_by(Visit.id.asc())
            )
        ).scalars().all()
        completed = [v for v in visits if v.status == "Completed"]
        pending = [v for v in visits if v.status == "Pending"]
        if len(completed) != 1 or len(pending) != 1:
            _fail(
                f"COMPLETED_TODAY_BLOCKED_LATER_PENDING:"
                f"completed={len(completed)},pending={len(pending)}"
            )

    print("FREEZE_EMERGENCY_OWNERSHIP_TRANSITIONS=OK")
    print("FREEZE_PRIOR_DAY_PENDING_ADOPTION=OK")
    print("FREEZE_COMPLETED_DOES_NOT_BLOCK_LATER_PENDING=OK")


async def test_ended_session_recovery_gate(fx: dict, ex: dict) -> None:
    # Ended + unreconciled session may reactivate its historical route for undo_end_work recovery.
    async with AsyncSessionLocal() as db:
        admin = await base.load_driver(db, fx["company"], fx["admin"])
        await update_route_status(
            route_id=ex["route_shortage"],
            payload=UpdateRouteStatusRequest(status="active"),
            db=db,
            current_admin=admin,
        )

    async with AsyncSessionLocal() as db:
        admin = await base.load_driver(db, fx["company"], fx["admin"])
        await undo_end_work(
            session_id=fx["ws_shortage"],
            db=db,
            current_admin=admin,
        )

    async with AsyncSessionLocal() as db:
        await base.set_tenant(db, fx["company"])
        session = (
            await db.execute(
                select(WorkSession).where(
                    WorkSession.company_id == fx["company"],
                    WorkSession.id == fx["ws_shortage"],
                )
            )
        ).scalar_one()
        if session.end_time is not None:
            _fail(f"UNDO_END_WORK_DID_NOT_REOPEN_SESSION:{session.end_time}")

        route = (
            await db.execute(
                select(DispatchRoute).where(
                    DispatchRoute.company_id == fx["company"],
                    DispatchRoute.id == ex["route_shortage"],
                )
            )
        ).scalar_one()

        # Prepare the negative half: reconciled sessions must not reactivate.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        session.end_time = now
        session.inventory_reconciled_at = now
        session.inventory_reconciled_by = fx["admin"]
        route.status = "closed"
        await db.commit()

    async with AsyncSessionLocal() as db:
        admin = await base.load_driver(db, fx["company"], fx["admin"])
        try:
            await update_route_status(
                route_id=ex["route_shortage"],
                payload=UpdateRouteStatusRequest(status="active"),
                db=db,
                current_admin=admin,
            )
        except HTTPException as exc:
            if exc.status_code != 409:
                _fail(f"RECONCILED_ROUTE_REACTIVATION_WRONG_STATUS:{exc.status_code}")
        else:
            _fail("RECONCILED_ROUTE_REACTIVATION_UNEXPECTEDLY_SUCCEEDED")

    print("FREEZE_UNRECONCILED_ROUTE_RECOVERY=OK")
    print("FREEZE_RECONCILED_ROUTE_REACTIVATION_BLOCK=OK")


async def test_dispatch_sees_unassigned_shortage(fx: dict, ex: dict) -> None:
    # Before route exists, shortage legitimately remains unassigned.
    async with AsyncSessionLocal() as db:
        admin = await base.load_driver(db, fx["company"], fx["admin"])
        await add_shortages(
            payload=[
                CreateShortageItem(
                    shopId=ex["shop_dispatch"],
                    zoneId=ex["zone_dispatch"],
                    productId=fx["variant_b"],
                    driverId=None,
                    quantity=2,
                )
            ],
            db=db,
            current_admin=admin,
        )

    async with AsyncSessionLocal() as db:
        await base.set_tenant(db, fx["company"])
        shortage = (
            await db.execute(
                select(ShortageRequest).where(
                    ShortageRequest.company_id == fx["company"],
                    ShortageRequest.shop_id == ex["shop_dispatch"],
                    ShortageRequest.product_variant_id == fx["variant_b"],
                    ShortageRequest.status == "pending",
                )
            )
        ).scalar_one()
        if shortage.driver_id is not None:
            _fail("PRE_DISPATCH_SHORTAGE_SHOULD_BE_UNASSIGNED")
        shortage_id = int(shortage.id)

    # New dispatch must see that unassigned shortage and create an Emergency Visit.
    async with AsyncSessionLocal() as db:
        admin = await base.load_driver(db, fx["company"], fx["admin"])
        await dispatch_route(
            payload=DispatchRouteRequest(
                zone_id=ex["zone_dispatch"],
                driver_id=ex["driver_e"],
                vehicle_id=ex["vehicle_e"],
                source_location_id=fx["warehouse"],
                inventory={},
            ),
            db=db,
            current_admin=admin,
        )

    async with AsyncSessionLocal() as db:
        await base.set_tenant(db, fx["company"])
        route = (
            await db.execute(
                select(DispatchRoute).where(
                    DispatchRoute.company_id == fx["company"],
                    DispatchRoute.zone_id == ex["zone_dispatch"],
                    DispatchRoute.driver_id == ex["driver_e"],
                    DispatchRoute.status == "active",
                )
            )
        ).scalar_one()
        visit = (
            await db.execute(
                select(Visit).where(
                    Visit.company_id == fx["company"],
                    Visit.shop_id == ex["shop_dispatch"],
                    Visit.status == "Pending",
                )
            )
        ).scalar_one()
        if int(visit.driver_id or 0) != ex["driver_e"] or not visit.is_emergency:
            _fail(
                f"DISPATCH_BLIND_TO_UNASSIGNED_SHORTAGE:"
                f"driver={visit.driver_id},emergency={visit.is_emergency}"
            )
        route_id = int(route.id)

    # Waiting -> active must synchronize unassigned shortage ownership too.
    async with AsyncSessionLocal() as db:
        admin = await base.load_driver(db, fx["company"], fx["admin"])
        await update_route_status(
            route_id=route_id,
            payload=UpdateRouteStatusRequest(status="waiting"),
            db=db,
            current_admin=admin,
        )
    async with AsyncSessionLocal() as db:
        admin = await base.load_driver(db, fx["company"], fx["admin"])
        await update_route_status(
            route_id=route_id,
            payload=UpdateRouteStatusRequest(status="active"),
            db=db,
            current_admin=admin,
        )

    async with AsyncSessionLocal() as db:
        await base.set_tenant(db, fx["company"])
        shortage = (
            await db.execute(
                select(ShortageRequest).where(
                    ShortageRequest.company_id == fx["company"],
                    ShortageRequest.id == shortage_id,
                )
            )
        ).scalar_one()
        if int(shortage.driver_id or 0) != ex["driver_e"]:
            _fail(f"REACTIVATED_ROUTE_DID_NOT_ADOPT_SHORTAGE:{shortage.driver_id}")

    print("FREEZE_DISPATCH_SEES_UNASSIGNED_SHORTAGE=OK")
    print("FREEZE_ROUTE_REACTIVATION_ADOPTS_SHORTAGE=OK")


async def rls_metadata_and_role_audit(fx: dict) -> None:
    async with AsyncSessionLocal() as db:
        await base.set_tenant(db, fx["company"])

        role = (
            await db.execute(
                text(
                    """
                    SELECT r.rolname, r.rolsuper, r.rolbypassrls
                    FROM pg_roles r
                    WHERE r.rolname = current_user
                    """
                )
            )
        ).one()
        if bool(role.rolsuper) or bool(role.rolbypassrls):
            _fail(
                f"APP_DB_ROLE_BYPASSES_RLS:"
                f"user={role.rolname},super={role.rolsuper},bypass={role.rolbypassrls}"
            )

        tenant_tables = (
            await db.execute(
                text(
                    """
                    SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    JOIN information_schema.columns col
                      ON col.table_schema = n.nspname
                     AND col.table_name = c.relname
                     AND col.column_name = 'company_id'
                    WHERE n.nspname = 'public'
                      AND c.relkind = 'r'
                    ORDER BY c.relname
                    """
                )
            )
        ).all()
        if not tenant_tables:
            _fail("RLS_NO_TENANT_TABLES_FOUND")

        missing_flags = [
            name
            for name, enabled, forced in tenant_tables
            if not bool(enabled) or not bool(forced)
        ]
        if missing_flags:
            _fail(f"RLS_ENABLE_FORCE_MISSING:{missing_flags}")

        policies = (
            await db.execute(
                text(
                    """
                    SELECT tablename, cmd, qual, with_check
                    FROM pg_policies
                    WHERE schemaname = 'public'
                    ORDER BY tablename, policyname
                    """
                )
            )
        ).all()
        policy_map = {}
        for tablename, cmd, qual, with_check in policies:
            policy_map.setdefault(tablename, []).append(
                (str(cmd), str(qual or ""), str(with_check or ""))
            )

        policy_errors = []
        for table_name, _, _ in tenant_tables:
            candidates = policy_map.get(table_name, [])
            valid = False
            for cmd, qual, with_check in candidates:
                combined = f"{qual} {with_check}".lower()
                if (
                    cmd.upper() == "ALL"
                    and "company_id" in combined
                    and "app.current_tenant" in combined
                ):
                    valid = True
                    break
            if not valid:
                policy_errors.append(table_name)
        if policy_errors:
            _fail(f"RLS_TENANT_POLICY_MISSING_OR_WEAK:{policy_errors}")

        print(f"RLS_TENANT_TABLES_VERIFIED={len(tenant_tables)}")
        print(f"RLS_APP_ROLE={role.rolname}")
        print("RLS_ENABLE_FORCE_POLICY_AUDIT=OK")
        print("RLS_APP_ROLE_NO_BYPASS=OK")


async def cross_tenant_hostile_audit(fx: dict, ex: dict) -> None:
    # Read isolation without company_id predicates: RLS itself must hide A from B.
    async with AsyncSessionLocal() as db:
        await base.set_tenant(db, fx["other_company"])

        probes = [
            ("Driver", select(Driver.id).where(Driver.id == fx["driver_a"])),
            ("Shop", select(Shop.id).where(Shop.id == fx["shop"])),
            ("DispatchRoute", select(DispatchRoute.id).where(DispatchRoute.id == fx["route_a"])),
            ("WorkSession", select(WorkSession.id).where(WorkSession.id == fx["ws_a"])),
            (
                "InventoryBalance",
                select(InventoryBalance.id).where(
                    InventoryBalance.location_id == fx["vehicle_a_loc"]
                ),
            ),
            (
                "Visit",
                select(Visit.id).where(
                    Visit.shop_id == ex["shop_transfer"]
                ),
            ),
            (
                "ShortageRequest",
                select(ShortageRequest.id).where(
                    ShortageRequest.shop_id == ex["shop_dispatch"]
                ),
            ),
        ]
        for label, stmt in probes:
            rows = (await db.execute(stmt)).scalars().all()
            if rows:
                _fail(f"RLS_CROSS_TENANT_READ_LEAK:{label}:{rows}")

        # Direct UPDATE with no tenant predicate must affect zero rows.
        result = await db.execute(
            update(Shop)
            .where(Shop.id == fx["shop"])
            .values(name="RLS_CROSS_TENANT_HACK")
        )
        if int(result.rowcount or 0) != 0:
            _fail(f"RLS_CROSS_TENANT_UPDATE_SUCCEEDED:{result.rowcount}")
        await db.commit()

    # Direct INSERT carrying the other tenant's company_id must be rejected by WITH CHECK.
    async with AsyncSessionLocal() as db:
        await base.set_tenant(db, fx["other_company"])
        db.add(
            Visit(
                company_id=fx["company"],
                driver_id=fx["driver_a"],
                shop_id=fx["shop"],
                operational_date=fx["local_day"],
                status="Pending",
                outcome="Pending",
                is_emergency=False,
            )
        )
        try:
            await db.commit()
        except Exception as exc:
            msg = str(exc).lower()
            await db.rollback()
            if "row-level security" not in msg and "policy" not in msg:
                _fail(f"RLS_CROSS_TENANT_INSERT_FAILED_FOR_WRONG_REASON:{exc}")
        else:
            _fail("RLS_CROSS_TENANT_INSERT_UNEXPECTEDLY_SUCCEEDED")

    # Verify the failed hostile update left company A untouched.
    async with AsyncSessionLocal() as db:
        await base.set_tenant(db, fx["company"])
        shop_name = (
            await db.execute(
                select(Shop.name).where(
                    Shop.company_id == fx["company"],
                    Shop.id == fx["shop"],
                )
            )
        ).scalar_one()
        if shop_name == "RLS_CROSS_TENANT_HACK":
            _fail("RLS_CROSS_TENANT_UPDATE_PERSISTED")

    # App-layer IDOR probes: كل محاولة تستخدم Session/Admin مستقلين
    # حتى لا يؤثر rollback من Endpoint على الاختبار التالي.
    async def must_reject(label: str, operation_factory, allowed_statuses: set[int]) -> None:
        async with AsyncSessionLocal() as probe_db:
            other_admin = await base.load_driver(
                probe_db, fx["other_company"], fx["other_admin"]
            )
            try:
                await operation_factory(probe_db, other_admin)
            except HTTPException as exc:
                if exc.status_code not in allowed_statuses:
                    _fail(
                        f"{label}_WRONG_HTTP_STATUS:"
                        f"{exc.status_code},expected={sorted(allowed_statuses)}"
                    )
            else:
                _fail(f"{label}_UNEXPECTEDLY_SUCCEEDED")

    await must_reject(
        "CROSS_TENANT_ROUTE_STATUS",
        lambda probe_db, admin: update_route_status(
            route_id=fx["route_a"],
            payload=UpdateRouteStatusRequest(status="postponed"),
            db=probe_db,
            current_admin=admin,
        ),
        {404},
    )

    await must_reject(
        "CROSS_TENANT_SHOP_EDIT",
        lambda probe_db, admin: edit_shop_details(
            shop_id=str(fx["shop"]),
            payload=EditShopDetailsRequest(name="Cross Tenant Hack"),
            db=probe_db,
            current_admin=admin,
        ),
        {404},
    )

    await must_reject(
        "CROSS_TENANT_SHORTAGE_ADD",
        lambda probe_db, admin: add_shortages(
            payload=[
                CreateShortageItem(
                    shopId=fx["shop"],
                    zoneId=fx["zone_main"],
                    productId=fx["variant_a"],
                    driverId=None,
                    quantity=1,
                )
            ],
            db=probe_db,
            current_admin=admin,
        ),
        {404},
    )

    await must_reject(
        "CROSS_TENANT_DISPATCH_CREATE",
        lambda probe_db, admin: dispatch_route(
            payload=DispatchRouteRequest(
                zone_id=ex["zone_dispatch"],
                driver_id=ex["driver_e"],
                vehicle_id=ex["vehicle_e"],
                source_location_id=fx["warehouse"],
                inventory={},
            ),
            db=probe_db,
            current_admin=admin,
        ),
        {404},
    )

    print("RLS_CROSS_TENANT_RAW_READ=OK")
    print("RLS_CROSS_TENANT_RAW_UPDATE=OK")
    print("RLS_CROSS_TENANT_WITH_CHECK_INSERT=OK")
    print("DISPATCH_CROSS_TENANT_IDOR_PROBES=OK")


async def main() -> None:
    base.safety_gate()
    static_dispatch_freeze_audit()

    fx = await base.setup_fixture()
    failure = None
    try:
        ex = await seed_extra_assets(fx)

        await test_active_session_shortage_preservation(fx)
        await test_no_route_shortage_stays_unassigned(fx, ex)
        await test_route_queue_ownership_and_dates(fx, ex)
        await test_ended_session_recovery_gate(fx, ex)
        await test_dispatch_sees_unassigned_shortage(fx, ex)

        await rls_metadata_and_role_audit(fx)
        await cross_tenant_hostile_audit(fx, ex)

        print("DISPATCH_FREEZE_GATE_POSTGRES_OK")
        print("DISPATCH_HOSTILE_TENANT_AUDIT_OK")
        print("DISPATCH_UNIFIED_ENGINE_AUDIT_OK")

    except Exception as exc:
        failure = exc
    finally:
        try:
            await base.cleanup(fx)
            print("FREEZE_GATE_CLEANUP=OK")
        except Exception as cleanup_exc:
            if failure is None:
                failure = cleanup_exc
            else:
                failure = RuntimeError(
                    f"{failure} | freeze-gate cleanup failed: {cleanup_exc}"
                )

    if failure is not None:
        raise failure


if __name__ == "__main__":
    asyncio.run(main())
