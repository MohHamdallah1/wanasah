from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, text, update

sys.path.insert(0, "wa_backend")

from context import tenant_context
from database import AsyncSessionLocal, engine
from models import (
    Company,
    DispatchRoute,
    Driver,
    InventoryLocation,
    InventoryLock,
    StocktakeSession,
    Vehicle,
    WorkSession,
    Zone,
)
from schemas import UnifiedStocktakeStartRequest
from services import InventoryMutationError, validate_vehicle_recon_work_session
from api.warehouse import start_unified_stocktake


async def set_tenant(db, company_id: int) -> None:
    tenant_context.set(company_id)
    await db.execute(
        text("SELECT set_config('app.current_tenant', :tenant, false)"),
        {"tenant": str(company_id)},
    )


async def ensure_schema_ready() -> None:
    async with AsyncSessionLocal() as db:
        checks = dict(
            (
                await db.execute(
                    text(
                        """
                        SELECT conname, pg_get_constraintdef(oid)
                        FROM pg_constraint
                        WHERE conname IN (
                            'chk_work_session_settlement_requires_end',
                            'chk_stocktake_work_session_scope'
                        )
                        """
                    )
                )
            ).all()
        )
        if set(checks) != {
            "chk_work_session_settlement_requires_end",
            "chk_stocktake_work_session_scope",
        }:
            raise AssertionError(f"missing lifecycle CHECK constraints: {checks}")

        idx = (
            await db.execute(
                text(
                    """
                    SELECT indexdef
                    FROM pg_indexes
                    WHERE schemaname = current_schema()
                      AND tablename = 'stocktake_sessions'
                      AND indexname = 'uq_vehicle_recon_work_session'
                    """
                )
            )
        ).scalar_one_or_none()
        if idx is None:
            raise AssertionError("uq_vehicle_recon_work_session missing")
        upper = idx.upper()
        for token in ("UNIQUE", "RELATED_WORK_SESSION_ID", "VEHICLE_RECON", "CANCELLED"):
            if token not in upper:
                raise AssertionError(f"bad VEHICLE_RECON index: {idx}")


async def setup_fixture():
    suffix = uuid.uuid4().hex[:10]
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    async with AsyncSessionLocal() as db:
        c1 = Company(
            name=f"Vehicle Recon Test {suffix}",
            company_code=f"VRC{suffix}",
            is_active=True,
            subscription_status="active",
            currency_code="JOD",
            timezone="Asia/Amman",
        )
        c2 = Company(
            name=f"Vehicle Recon Other {suffix}",
            company_code=f"VRO{suffix}",
            is_active=True,
            subscription_status="active",
            currency_code="JOD",
            timezone="Asia/Amman",
        )
        db.add_all([c1, c2])
        await db.flush()

        await set_tenant(db, c1.id)

        admin = Driver(
            company_id=c1.id,
            username=f"vrecon_admin_{suffix}",
            password_hash="test-only",
            full_name="Vehicle Recon Admin",
            is_active=True,
            is_admin=True,
        )
        route_driver = Driver(
            company_id=c1.id,
            username=f"vrecon_driver_{suffix}",
            password_hash="test-only",
            full_name="Vehicle Recon Driver",
            is_active=True,
            is_admin=False,
        )
        open_driver = Driver(
            company_id=c1.id,
            username=f"vrecon_open_{suffix}",
            password_hash="test-only",
            full_name="Open Session Driver",
            is_active=True,
            is_admin=False,
        )
        settled_driver = Driver(
            company_id=c1.id,
            username=f"vrecon_settled_{suffix}",
            password_hash="test-only",
            full_name="Settled Session Driver",
            is_active=True,
            is_admin=False,
        )
        zone = Zone(
            company_id=c1.id,
            name=f"VRecon Zone {suffix}",
            is_active=True,
        )
        vehicle = Vehicle(
            company_id=c1.id,
            plate_number=f"VR-{suffix}",
            maintenance_status="Active",
            is_active=True,
        )
        other_vehicle = Vehicle(
            company_id=c1.id,
            plate_number=f"VO-{suffix}",
            maintenance_status="Active",
            is_active=True,
        )
        db.add_all([
            admin,
            route_driver,
            open_driver,
            settled_driver,
            zone,
            vehicle,
            other_vehicle,
        ])
        await db.flush()

        warehouse_loc = InventoryLocation(
            company_id=c1.id,
            name="VRecon Warehouse",
            code=f"VRW-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        vehicle_loc = InventoryLocation(
            company_id=c1.id,
            name="VRecon Vehicle",
            code=f"VRV-{suffix}",
            location_type="VEHICLE",
            vehicle_id=vehicle.id,
            is_active=True,
        )
        db.add_all([warehouse_loc, vehicle_loc])
        await db.flush()

        valid_ws = WorkSession(
            company_id=c1.id,
            driver_id=route_driver.id,
            start_time=now - timedelta(hours=8),
            end_time=now - timedelta(minutes=10),
            session_date=date.today(),
            is_settled=False,
        )
        open_ws = WorkSession(
            company_id=c1.id,
            driver_id=open_driver.id,
            start_time=now - timedelta(hours=2),
            end_time=None,
            session_date=date.today(),
            is_settled=False,
        )
        settled_ws = WorkSession(
            company_id=c1.id,
            driver_id=settled_driver.id,
            start_time=now - timedelta(hours=6),
            end_time=now - timedelta(hours=1),
            session_date=date.today(),
            is_settled=True,
        )
        db.add_all([valid_ws, open_ws, settled_ws])
        await db.flush()

        route = DispatchRoute(
            company_id=c1.id,
            zone_id=zone.id,
            driver_id=route_driver.id,
            vehicle_id=vehicle.id,
            work_session_id=valid_ws.id,
            source_location_id=warehouse_loc.id,
            dispatch_date=date.today(),
            status="closed",
        )
        db.add(route)
        await db.commit()

        await set_tenant(db, c2.id)
        other_driver = Driver(
            company_id=c2.id,
            username=f"vrecon_other_{suffix}",
            password_hash="test-only",
            full_name="Other Tenant Driver",
            is_active=True,
            is_admin=False,
        )
        db.add(other_driver)
        await db.flush()
        other_ws = WorkSession(
            company_id=c2.id,
            driver_id=other_driver.id,
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(hours=1),
            session_date=date.today(),
            is_settled=False,
        )
        db.add(other_ws)
        await db.commit()

        return {
            "c1": c1.id,
            "c2": c2.id,
            "admin": admin.id,
            "vehicle": vehicle.id,
            "other_vehicle": other_vehicle.id,
            "vehicle_loc": vehicle_loc.id,
            "valid_ws": valid_ws.id,
            "open_ws": open_ws.id,
            "settled_ws": settled_ws.id,
            "other_ws": other_ws.id,
        }


async def cleanup_company(company_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await set_tenant(db, company_id)
        for table in (
            "inventory_movement_impacts",
            "inventory_movements",
            "inventory_locks",
            "stocktake_count_attempt_lines",
            "stocktake_count_attempts",
            "stocktake_lines",
            "stocktake_sessions",
            "dispatch_load_plan_lines",
            "dispatch_routes",
            "session_inventory_snapshots",
            "work_sessions",
            "inventory_balances",
            "inventory_locations",
            "vehicles",
            "shops",
            "zones",
            "drivers",
        ):
            await db.execute(
                text(f"DELETE FROM {table} WHERE company_id = :company_id"),
                {"company_id": company_id},
            )
        await db.execute(
            text("DELETE FROM companies WHERE id = :company_id"),
            {"company_id": company_id},
        )
        await db.commit()


async def load_admin(db, fx):
    await set_tenant(db, fx["c1"])
    return (
        await db.execute(
            select(Driver).where(
                Driver.company_id == fx["c1"],
                Driver.id == fx["admin"],
            )
        )
    ).scalar_one()


async def assert_helper_blocked(fx, ws_id: int, vehicle_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["c1"])
        try:
            await validate_vehicle_recon_work_session(
                db,
                company_id=fx["c1"],
                work_session_id=ws_id,
                vehicle_id=vehicle_id,
            )
        except InventoryMutationError:
            await db.rollback()
            return
        await db.rollback()
        raise AssertionError("VEHICLE_RECON helper unexpectedly allowed invalid context")


async def call_start(fx):
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, fx)
        payload = UnifiedStocktakeStartRequest(
            location_id=fx["vehicle_loc"],
            stocktake_type="VEHICLE_RECON",
            related_work_session_id=fx["valid_ws"],
        )
        try:
            result = await start_unified_stocktake(
                payload=payload,
                db=db,
                current_admin=admin,
            )
            return ("ok", result)
        except HTTPException as exc:
            return ("http", exc.status_code)


async def cancel_created_recon(fx, session_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["c1"])
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        session = (
            await db.execute(
                select(StocktakeSession).where(
                    StocktakeSession.company_id == fx["c1"],
                    StocktakeSession.id == session_id,
                ).with_for_update()
            )
        ).scalar_one()
        session.status = "CANCELLED"
        session.cancelled_by = fx["admin"]
        session.cancelled_at = now
        session.cancellation_reason = "Lifecycle test cancellation"
        session.updated_at = now
        await db.execute(
            update(InventoryLock)
            .where(
                InventoryLock.company_id == fx["c1"],
                InventoryLock.stocktake_session_id == session_id,
                InventoryLock.released_at.is_(None),
            )
            .values(
                released_by=fx["admin"],
                released_at=now,
                release_reason="LIFECYCLE_TEST_CANCEL",
            )
        )
        await db.commit()


async def main() -> None:
    await ensure_schema_ready()
    fx = await setup_fixture()
    try:
        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["c1"])
            ws = await validate_vehicle_recon_work_session(
                db,
                company_id=fx["c1"],
                work_session_id=fx["valid_ws"],
                vehicle_id=fx["vehicle"],
            )
            if ws.id != fx["valid_ws"]:
                raise AssertionError("valid WorkSession mismatch")
            await db.rollback()
        print("ENDED_UNSETTLED_MATCH=OK")

        await assert_helper_blocked(fx, fx["open_ws"], fx["vehicle"])
        print("OPEN_SESSION=BLOCKED")

        await assert_helper_blocked(fx, fx["settled_ws"], fx["vehicle"])
        print("SETTLED_SESSION=BLOCKED")

        await assert_helper_blocked(fx, fx["valid_ws"], fx["other_vehicle"])
        print("WRONG_VEHICLE=BLOCKED")

        await assert_helper_blocked(fx, fx["other_ws"], fx["vehicle"])
        print("CROSS_TENANT_SESSION=BLOCKED")

        results = await asyncio.gather(call_start(fx), call_start(fx))
        ok_results = [value for kind, value in results if kind == "ok"]
        blocked = [value for kind, value in results if kind == "http"]
        if len(ok_results) != 1 or blocked != [409]:
            raise AssertionError(f"concurrent start unexpected: {results}")
        first_session_id = int(ok_results[0]["session_id"])
        print("CONCURRENT_DUPLICATE_RECON=ONE_CREATED")

        again = await call_start(fx)
        if again[0] != "http" or again[1] != 409:
            raise AssertionError(f"sequential duplicate not blocked: {again}")
        print("SEQUENTIAL_DUPLICATE_RECON=BLOCKED")

        await cancel_created_recon(fx, first_session_id)
        retry = await call_start(fx)
        if retry[0] != "ok":
            raise AssertionError(f"cancelled recon retry should be allowed: {retry}")
        print("CANCELLED_RECON_RETRY=ALLOWED")

        print("WAREHOUSE_VEHICLE_RECON_LIFECYCLE_POSTGRES_OK")
    finally:
        await cleanup_company(fx["c1"])
        await cleanup_company(fx["c2"])
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
