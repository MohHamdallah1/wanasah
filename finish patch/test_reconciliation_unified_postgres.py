from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import bcrypt
from fastapi import HTTPException
from sqlalchemy import select, text

sys.path.insert(0, "wa_backend")

from context import tenant_context
from database import AsyncSessionLocal, engine
from models import (
    Company,
    DispatchRoute,
    Driver,
    InventoryBalance,
    InventoryLock,
    InventoryLocation,
    InventoryMovement,
    Product,
    ProductBatch,
    ProductVariant,
    SessionInventorySnapshot,
    StocktakeLine,
    StocktakeSession,
    UOM,
    Vehicle,
    WorkSession,
    Zone,
)
from schemas import StocktakeApprovalRequest, StocktakeCountItem, UnifiedStocktakeCountRequest
from api.reconciliation import VehicleCountItem, VehicleReconciliationRequest, reconcile_driver_end_of_day
from api.warehouse import approve_stocktake_session, submit_stocktake_count

PASSWORD = "ReconTest!2026"


async def set_tenant(db, company_id: int) -> None:
    tenant_context.set(company_id)
    await db.execute(
        text("SELECT set_config('app.current_tenant', :tenant, false)"),
        {"tenant": str(company_id)},
    )


async def setup_fixture():
    suffix = uuid.uuid4().hex[:10]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    password_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()

    async with AsyncSessionLocal() as db:
        uom = UOM(name=f"Recon Unit {suffix}", code=f"RU{suffix[:8]}")
        company = Company(
            name=f"Recon Company {suffix}",
            company_code=f"RC{suffix}",
            is_active=True,
            subscription_status="active",
            currency_code="JOD",
            timezone="Asia/Amman",
        )
        other_company = Company(
            name=f"Recon Other {suffix}",
            company_code=f"RO{suffix}",
            is_active=True,
            subscription_status="active",
            currency_code="JOD",
            timezone="Asia/Amman",
        )
        db.add_all([uom, company, other_company])
        await db.flush()

        await set_tenant(db, company.id)
        admin = Driver(
            company_id=company.id,
            username=f"recon_admin_{suffix}",
            password_hash=password_hash,
            full_name="Recon Admin",
            is_active=True,
            is_admin=True,
        )
        driver = Driver(
            company_id=company.id,
            username=f"recon_driver_{suffix}",
            password_hash=password_hash,
            full_name="Recon Driver",
            is_active=True,
            is_admin=False,
        )
        zone = Zone(company_id=company.id, name=f"Recon Zone {suffix}", is_active=True)
        vehicle = Vehicle(
            company_id=company.id,
            plate_number=f"R-{suffix[:8]}",
            maintenance_status="Active",
            is_active=True,
        )
        product = Product(company_id=company.id, base_name=f"Recon Product {suffix}")
        db.add_all([admin, driver, zone, vehicle, product])
        await db.flush()

        variant = ProductVariant(
            company_id=company.id,
            product_id=product.id,
            base_uom_id=uom.id,
            variant_name=f"Recon Variant {suffix}",
            sku=f"RSKU-{suffix}",
            packs_per_carton=24,
            price_per_carton=Decimal("24.000"),
            price_per_pack=Decimal("1.000"),
            is_active=True,
        )
        db.add(variant)
        await db.flush()

        batch = ProductBatch(
            company_id=company.id,
            product_variant_id=variant.id,
            batch_number=f"RB-{suffix}",
            production_date=date.today() - timedelta(days=5),
            expiry_date=date.today() + timedelta(days=365),
            is_active=True,
        )
        warehouse_loc = InventoryLocation(
            company_id=company.id,
            name="Recon Warehouse",
            code=f"RW-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        vehicle_loc = InventoryLocation(
            company_id=company.id,
            name="Recon Vehicle",
            code=f"RV-{suffix}",
            location_type="VEHICLE",
            vehicle_id=vehicle.id,
            is_active=True,
        )
        db.add_all([batch, warehouse_loc, vehicle_loc])
        await db.flush()

        db.add_all([
            InventoryBalance(
                company_id=company.id,
                location_id=vehicle_loc.id,
                product_variant_id=variant.id,
                batch_id=batch.id,
                stock_status="AVAILABLE",
                on_hand_quantity=10,
                reserved_quantity=0,
            ),
            InventoryBalance(
                company_id=company.id,
                location_id=vehicle_loc.id,
                product_variant_id=variant.id,
                batch_id=batch.id,
                stock_status="DAMAGED",
                on_hand_quantity=2,
                reserved_quantity=0,
            ),
        ])

        match_ws = WorkSession(
            company_id=company.id,
            driver_id=driver.id,
            start_time=now - timedelta(hours=10),
            end_time=now - timedelta(hours=6),
            session_date=date.today(),
            is_settled=False,
        )
        variance_ws = WorkSession(
            company_id=company.id,
            driver_id=driver.id,
            start_time=now - timedelta(hours=5),
            end_time=now - timedelta(minutes=30),
            session_date=date.today(),
            is_settled=False,
        )
        db.add_all([match_ws, variance_ws])
        await db.flush()

        for ws in (match_ws, variance_ws):
            db.add_all([
                SessionInventorySnapshot(
                    company_id=company.id,
                    work_session_id=ws.id,
                    location_id=vehicle_loc.id,
                    product_variant_id=variant.id,
                    stock_status="AVAILABLE",
                    starting_quantity=10,
                ),
                SessionInventorySnapshot(
                    company_id=company.id,
                    work_session_id=ws.id,
                    location_id=vehicle_loc.id,
                    product_variant_id=variant.id,
                    stock_status="DAMAGED",
                    starting_quantity=2,
                ),
                DispatchRoute(
                    company_id=company.id,
                    zone_id=zone.id,
                    driver_id=driver.id,
                    vehicle_id=vehicle.id,
                    work_session_id=ws.id,
                    source_location_id=warehouse_loc.id,
                    dispatch_date=date.today(),
                    status="closed",
                ),
            ])

        await db.commit()

        await set_tenant(db, other_company.id)
        other_driver = Driver(
            company_id=other_company.id,
            username=f"recon_other_{suffix}",
            password_hash=password_hash,
            full_name="Other Tenant Driver",
            is_active=True,
            is_admin=False,
        )
        db.add(other_driver)
        await db.commit()

        return {
            "company": company.id,
            "other_company": other_company.id,
            "uom": uom.id,
            "admin": admin.id,
            "driver": driver.id,
            "other_driver": other_driver.id,
            "variant": variant.id,
            "batch": batch.id,
            "vehicle_loc": vehicle_loc.id,
            "match_ws": match_ws.id,
            "variance_ws": variance_ws.id,
        }


async def load_driver(db, company_id: int, driver_id: int):
    await set_tenant(db, company_id)
    return (
        await db.execute(
            select(Driver).where(Driver.company_id == company_id, Driver.id == driver_id)
        )
    ).scalar_one()


async def call_reconcile(fx, ws_id: int, actual: int):
    async with AsyncSessionLocal() as db:
        driver = await load_driver(db, fx["company"], fx["driver"])
        payload = VehicleReconciliationRequest(
            counts=[VehicleCountItem(product_variant_id=fx["variant"], actual_quantity=actual)]
        )
        return await reconcile_driver_end_of_day(
            session_id=ws_id,
            payload=payload,
            db=db,
            current_driver=driver,
        )


async def cleanup(fx):
    errors = []
    for company_id in (fx["company"], fx["other_company"]):
        try:
            async with AsyncSessionLocal() as db:
                await set_tenant(db, company_id)
                for table in (
                    "system_audit_logs",
                    "inventory_movement_impacts",
                    "inventory_movements",
                    "inventory_locks",
                    "stocktake_count_attempt_lines",
                    "stocktake_count_attempts",
                    "stocktake_lines",
                    "stocktake_sessions",
                    "session_inventory_snapshots",
                    "dispatch_routes",
                    "work_sessions",
                    "inventory_balances",
                    "product_batches",
                    "inventory_locations",
                    "vehicles",
                    "product_variants",
                    "products",
                    "zones",
                    "drivers",
                ):
                    await db.execute(
                        text(f"DELETE FROM {table} WHERE company_id = :company_id"),
                        {"company_id": company_id},
                    )
                await db.execute(text("DELETE FROM companies WHERE id = :id"), {"id": company_id})
                await db.commit()
        except Exception as exc:
            errors.append(f"company {company_id}: {exc}")

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("DELETE FROM uom WHERE id = :id"), {"id": fx["uom"]})
            await db.commit()
    except Exception as exc:
        errors.append(f"uom: {exc}")

    if errors:
        raise RuntimeError("RECON_TEST_CLEANUP_FAILED: " + " | ".join(errors))


async def main():
    fx = await setup_fixture()
    failure = None
    try:
        # 1) Tenant isolation: company B cannot see company A's session through endpoint.
        async with AsyncSessionLocal() as db:
            other_driver = await load_driver(db, fx["other_company"], fx["other_driver"])
            try:
                await reconcile_driver_end_of_day(
                    session_id=fx["match_ws"],
                    payload=VehicleReconciliationRequest(counts=[]),
                    db=db,
                    current_driver=other_driver,
                )
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise AssertionError(f"cross tenant expected 404, got {exc.status_code}")
            else:
                raise AssertionError("cross tenant reconciliation unexpectedly succeeded")
        print("TENANT_ISOLATION=OK")

        # 2) Missing expected product must not silently mean zero.
        async with AsyncSessionLocal() as db:
            driver = await load_driver(db, fx["company"], fx["driver"])
            try:
                await reconcile_driver_end_of_day(
                    session_id=fx["match_ws"],
                    payload=VehicleReconciliationRequest(counts=[]),
                    db=db,
                    current_driver=driver,
                )
            except HTTPException as exc:
                if exc.status_code != 422:
                    raise AssertionError(f"missing count expected 422, got {exc.status_code}")
            else:
                raise AssertionError("missing expected product was silently treated as zero")
        print("MISSING_COUNT=BLOCKED")

        # 3) Exact aggregate count settles immediately and freezes ending snapshot by status.
        result = await call_reconcile(fx, fx["match_ws"], 12)
        if result.get("requires_audit") is not False:
            raise AssertionError(f"exact match unexpectedly opened audit: {result}")

        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            ws = (
                await db.execute(
                    select(WorkSession).where(
                        WorkSession.company_id == fx["company"],
                        WorkSession.id == fx["match_ws"],
                    )
                )
            ).scalar_one()
            if not ws.is_settled:
                raise AssertionError("exact match did not settle WorkSession")
            snaps = (
                await db.execute(
                    select(SessionInventorySnapshot).where(
                        SessionInventorySnapshot.company_id == fx["company"],
                        SessionInventorySnapshot.work_session_id == fx["match_ws"],
                    )
                )
            ).scalars().all()
            ending = {row.stock_status: row.ending_quantity for row in snaps}
            if ending != {"AVAILABLE": 10, "DAMAGED": 2}:
                raise AssertionError(f"bad exact ending snapshot: {ending}")
            if any(row.settled_by != fx["driver"] or row.settled_at is None for row in snaps):
                raise AssertionError("exact ending snapshot settlement triplet missing")
        print("EXACT_MATCH_SETTLEMENT=OK")

        replay = await call_reconcile(fx, fx["match_ws"], 12)
        if replay.get("already_settled") is not True:
            raise AssertionError(f"exact replay not state-idempotent: {replay}")
        print("EXACT_REPLAY_IDEMPOTENCY=OK")

        # 4) Aggregate variance opens one targeted VEHICLE_RECON and leaves WorkSession unsettled.
        variance_result = await call_reconcile(fx, fx["variance_ws"], 13)
        if variance_result.get("requires_audit") is not True:
            raise AssertionError(f"variance did not open audit: {variance_result}")
        stocktake_id = int(variance_result["stocktake_session_id"])

        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            st = (
                await db.execute(
                    select(StocktakeSession).where(
                        StocktakeSession.company_id == fx["company"],
                        StocktakeSession.id == stocktake_id,
                    )
                )
            ).scalar_one()
            if st.stocktake_type != "VEHICLE_RECON" or st.status != "COUNTING":
                raise AssertionError(f"bad variance stocktake state: {st.stocktake_type}/{st.status}")
            if st.related_work_session_id != fx["variance_ws"]:
                raise AssertionError("VEHICLE_RECON not linked to WorkSession")
            lines = (
                await db.execute(
                    select(StocktakeLine).where(
                        StocktakeLine.company_id == fx["company"],
                        StocktakeLine.stocktake_session_id == stocktake_id,
                    )
                )
            ).scalars().all()
            if {(row.product_variant_id, row.stock_status, row.expected_quantity) for row in lines} != {
                (fx["variant"], "AVAILABLE", 10),
                (fx["variant"], "DAMAGED", 2),
            }:
                raise AssertionError("targeted VEHICLE_RECON snapshot is incorrect")
            ws = (
                await db.execute(
                    select(WorkSession).where(
                        WorkSession.company_id == fx["company"],
                        WorkSession.id == fx["variance_ws"],
                    )
                )
            ).scalar_one()
            if ws.is_settled:
                raise AssertionError("variance WorkSession settled before approval")
            active_lock = (
                await db.execute(
                    select(InventoryLock.id).where(
                        InventoryLock.company_id == fx["company"],
                        InventoryLock.stocktake_session_id == stocktake_id,
                        InventoryLock.released_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if active_lock is None:
                raise AssertionError("variance VEHICLE_RECON did not lock vehicle")
        print("TARGETED_VARIANCE_RECON=OK")

        duplicate = await call_reconcile(fx, fx["variance_ws"], 13)
        if int(duplicate.get("stocktake_session_id")) != stocktake_id:
            raise AssertionError("reconciliation retry created a second VEHICLE_RECON")
        print("VARIANCE_REPLAY_IDEMPOTENCY=OK")

        # 5) Admin detailed batch/status count -> approval -> posting -> WorkSession settlement.
        async with AsyncSessionLocal() as db:
            admin = await load_driver(db, fx["company"], fx["admin"])
            count_result = await submit_stocktake_count(
                session_id=stocktake_id,
                payload=UnifiedStocktakeCountRequest(items=[
                    StocktakeCountItem(
                        product_variant_id=fx["variant"],
                        batch_id=fx["batch"],
                        stock_status="AVAILABLE",
                        actual_quantity=11,
                    ),
                    StocktakeCountItem(
                        product_variant_id=fx["variant"],
                        batch_id=fx["batch"],
                        stock_status="DAMAGED",
                        actual_quantity=2,
                    ),
                ]),
                db=db,
                current_admin=admin,
            )
            attempt_id = int(count_result["attempt_id"])
            if count_result.get("requires_independent_recount"):
                raise AssertionError("surplus-only test unexpectedly requires independent recount")

        async with AsyncSessionLocal() as db:
            admin = await load_driver(db, fx["company"], fx["admin"])
            approve_result = await approve_stocktake_session(
                session_id=stocktake_id,
                payload=StocktakeApprovalRequest(
                    count_attempt_id=attempt_id,
                    password=PASSWORD,
                ),
                db=db,
                current_admin=admin,
            )
            if approve_result.get("status") != "POSTED":
                raise AssertionError(f"approval did not post: {approve_result}")

        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            ws = (
                await db.execute(
                    select(WorkSession).where(
                        WorkSession.company_id == fx["company"],
                        WorkSession.id == fx["variance_ws"],
                    )
                )
            ).scalar_one()
            if not ws.is_settled:
                raise AssertionError("POSTED VEHICLE_RECON did not settle WorkSession")
            snaps = (
                await db.execute(
                    select(SessionInventorySnapshot).where(
                        SessionInventorySnapshot.company_id == fx["company"],
                        SessionInventorySnapshot.work_session_id == fx["variance_ws"],
                    )
                )
            ).scalars().all()
            ending = {row.stock_status: row.ending_quantity for row in snaps}
            if ending != {"AVAILABLE": 11, "DAMAGED": 2}:
                raise AssertionError(f"bad post-recon ending snapshot: {ending}")
            balances = (
                await db.execute(
                    select(InventoryBalance).where(
                        InventoryBalance.company_id == fx["company"],
                        InventoryBalance.location_id == fx["vehicle_loc"],
                        InventoryBalance.product_variant_id == fx["variant"],
                    )
                )
            ).scalars().all()
            physical = {row.stock_status: row.on_hand_quantity for row in balances}
            if physical != {"AVAILABLE": 11, "DAMAGED": 2}:
                raise AssertionError(f"bad posted vehicle balances: {physical}")
            movement_count = (
                await db.execute(
                    select(InventoryMovement).where(
                        InventoryMovement.company_id == fx["company"],
                        InventoryMovement.stocktake_session_id == stocktake_id,
                    )
                )
            ).scalars().all()
            if len(movement_count) != 1 or movement_count[0].reference_type != "DRIVER_SURPLUS":
                raise AssertionError("expected exactly one DRIVER_SURPLUS movement")
        print("APPROVED_RECON_POST_AND_SETTLEMENT=OK")

        print("RECONCILIATION_UNIFIED_POSTGRES_OK")

    except BaseException as exc:
        failure = exc
    finally:
        try:
            await cleanup(fx)
            print("TEST_CLEANUP=OK")
        finally:
            await engine.dispose()

    if failure is not None:
        raise failure


if __name__ == "__main__":
    asyncio.run(main())
