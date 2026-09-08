from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import bcrypt
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, "wa_backend")

from config import Config
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
    Shop,
    ShortageRequest,
    Visit,
    SessionInventorySnapshot,
    StocktakeLine,
    StocktakeSession,
    UOM,
    Vehicle,
    WorkSession,
    Zone,
)
from schemas import StocktakeApprovalRequest, StocktakeCountItem, UnifiedStocktakeCountRequest, VisitItemInput, VisitUpdateRequest
from api.reconciliation import VehicleCountItem, VehicleReconciliationRequest, reconcile_driver_end_of_day
from api.driver import update_visit
from services import InventoryMutationError, finalize_vehicle_inventory_reconciliation, post_approved_stocktake_adjustments, reverse_previous_visit_state
from api.warehouse import approve_stocktake_session, submit_stocktake_count

PASSWORD = "ReconTest!2026"


def safety_gate() -> None:
    url = make_url(Config.SQLALCHEMY_DATABASE_URI)
    host = (url.host or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"} and os.getenv("WANASAH_ALLOW_REMOTE_TEST_DB") != "YES":
        raise SystemExit(
            "REFUSED: DATABASE_URL is not local. This test mutates temporary fixtures. "
            "Set WANASAH_ALLOW_REMOTE_TEST_DB=YES only for an intentional remote TEST DB."
        )


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

        # Field-visit fixture for shortage fulfillment/reversal hardening.
        field_driver = Driver(
            company_id=company.id,
            username=f"field_driver_{suffix}",
            password_hash=password_hash,
            full_name="Field Driver",
            is_active=True,
            is_admin=False,
            can_allow_debt=True,
            max_debt_limit=Decimal("1000.000"),
        )
        field_vehicle = Vehicle(
            company_id=company.id,
            plate_number=f"F-{suffix[:8]}",
            maintenance_status="Active",
            is_active=True,
        )
        field_zone = Zone(company_id=company.id, name=f"Field Zone {suffix}", is_active=True)
        db.add_all([field_driver, field_vehicle, field_zone])
        await db.flush()

        variant2 = ProductVariant(
            company_id=company.id,
            product_id=product.id,
            base_uom_id=uom.id,
            variant_name=f"Recon Variant 2 {suffix}",
            sku=f"RSKU2-{suffix}",
            packs_per_carton=24,
            price_per_carton=Decimal("24.000"),
            price_per_pack=Decimal("1.000"),
            is_active=True,
        )
        db.add(variant2)
        await db.flush()
        batch2 = ProductBatch(
            company_id=company.id,
            product_variant_id=variant2.id,
            batch_number=f"RB2-{suffix}",
            production_date=date.today() - timedelta(days=5),
            expiry_date=date.today() + timedelta(days=365),
            is_active=True,
        )
        field_vehicle_loc = InventoryLocation(
            company_id=company.id,
            name="Field Vehicle",
            code=f"FV-{suffix}",
            location_type="VEHICLE",
            vehicle_id=field_vehicle.id,
            is_active=True,
        )
        db.add_all([batch2, field_vehicle_loc])
        await db.flush()
        db.add_all([
            InventoryBalance(
                company_id=company.id,
                location_id=field_vehicle_loc.id,
                product_variant_id=variant.id,
                batch_id=batch.id,
                stock_status="AVAILABLE",
                on_hand_quantity=50,
                reserved_quantity=0,
            ),
            InventoryBalance(
                company_id=company.id,
                location_id=field_vehicle_loc.id,
                product_variant_id=variant2.id,
                batch_id=batch2.id,
                stock_status="AVAILABLE",
                on_hand_quantity=50,
                reserved_quantity=0,
            ),
        ])
        field_ws = WorkSession(
            company_id=company.id,
            driver_id=field_driver.id,
            start_time=now - timedelta(hours=1),
            end_time=None,
            session_date=date.today(),
            is_authorized_to_sell=True,
            is_settled=False,
        )
        db.add(field_ws)
        await db.flush()
        field_route = DispatchRoute(
            company_id=company.id,
            zone_id=field_zone.id,
            driver_id=field_driver.id,
            vehicle_id=field_vehicle.id,
            work_session_id=field_ws.id,
            source_location_id=warehouse_loc.id,
            dispatch_date=date.today(),
            status="active",
        )
        shop = Shop(
            company_id=company.id,
            name=f"Shortage Shop {suffix}",
            phone_number=f"07{suffix[:8]}",
            zone_id=field_zone.id,
            current_balance=Decimal("0.000"),
            max_debt_limit=Decimal("1000.000"),
            is_active=True,
            is_archived=False,
        )
        db.add_all([field_route, shop])
        await db.flush()
        visit = Visit(
            company_id=company.id,
            driver_id=field_driver.id,
            shop_id=shop.id,
            work_session_id=field_ws.id,
            status="Pending",
            outcome="Pending",
            visit_timestamp=now,
        )
        db.add(visit)
        await db.flush()
        shortage_sold = ShortageRequest(
            company_id=company.id,
            zone_id=field_zone.id,
            shop_id=shop.id,
            driver_id=field_driver.id,
            product_variant_id=variant.id,
            quantity=5,
            status="pending",
        )
        shortage_unsold = ShortageRequest(
            company_id=company.id,
            zone_id=field_zone.id,
            shop_id=shop.id,
            driver_id=field_driver.id,
            product_variant_id=variant2.id,
            quantity=5,
            status="pending",
        )
        db.add_all([shortage_sold, shortage_unsold])

        # Separate ended session/vehicle for finalizer actor+reservation guard tests.
        guard_driver = Driver(
            company_id=company.id,
            username=f"guard_driver_{suffix}",
            password_hash=password_hash,
            full_name="Guard Driver",
            is_active=True,
            is_admin=False,
        )
        intruder_driver = Driver(
            company_id=company.id,
            username=f"intruder_driver_{suffix}",
            password_hash=password_hash,
            full_name="Intruder Driver",
            is_active=True,
            is_admin=False,
        )
        guard_vehicle = Vehicle(
            company_id=company.id,
            plate_number=f"G-{suffix[:8]}",
            maintenance_status="Active",
            is_active=True,
        )
        guard_zone = Zone(company_id=company.id, name=f"Guard Zone {suffix}", is_active=True)
        db.add_all([guard_driver, intruder_driver, guard_vehicle, guard_zone])
        await db.flush()
        guard_loc = InventoryLocation(
            company_id=company.id,
            name="Guard Vehicle",
            code=f"GV-{suffix}",
            location_type="VEHICLE",
            vehicle_id=guard_vehicle.id,
            is_active=True,
        )
        db.add(guard_loc)
        await db.flush()
        guard_ws = WorkSession(
            company_id=company.id,
            driver_id=guard_driver.id,
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(hours=2),
            session_date=date.today(),
            is_settled=False,
        )
        db.add(guard_ws)
        await db.flush()
        db.add_all([
            DispatchRoute(
                company_id=company.id,
                zone_id=guard_zone.id,
                driver_id=guard_driver.id,
                vehicle_id=guard_vehicle.id,
                work_session_id=guard_ws.id,
                source_location_id=warehouse_loc.id,
                dispatch_date=date.today(),
                status="closed",
            ),
            SessionInventorySnapshot(
                company_id=company.id,
                work_session_id=guard_ws.id,
                location_id=guard_loc.id,
                product_variant_id=variant.id,
                stock_status="AVAILABLE",
                starting_quantity=7,
            ),
            InventoryBalance(
                company_id=company.id,
                location_id=guard_loc.id,
                product_variant_id=variant.id,
                batch_id=batch.id,
                stock_status="AVAILABLE",
                on_hand_quantity=7,
                reserved_quantity=1,
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
            "vehicle": vehicle.id,
            "warehouse_loc": warehouse_loc.id,
            "zone": zone.id,
            "match_ws": match_ws.id,
            "variance_ws": variance_ws.id,
            "field_driver": field_driver.id,
            "field_ws": field_ws.id,
            "field_visit": visit.id,
            "field_shop": shop.id,
            "shortage_sold": shortage_sold.id,
            "shortage_unsold": shortage_unsold.id,
            "guard_driver": guard_driver.id,
            "intruder_driver": intruder_driver.id,
            "guard_ws": guard_ws.id,
            "guard_loc": guard_loc.id,
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
                    "operation_idempotency",
                    "inventory_movement_impacts",
                    "inventory_movements",
                    "inventory_locks",
                    "stocktake_count_attempt_lines",
                    "stocktake_count_attempts",
                    "stocktake_lines",
                    "stocktake_sessions",
                    "session_inventory_snapshots",
                    "shortage_requests",
                    "visit_returns",
                    "visit_items",
                    "visits",
                    "dispatch_routes",
                    "work_sessions",
                    "inventory_balances",
                    "product_batches",
                    "inventory_locations",
                    "vehicles",
                    "shops",
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
    safety_gate()
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

        # Hostile path-ID bound: reject before PostgreSQL can overflow INTEGER binding.
        async with AsyncSessionLocal() as db:
            driver = await load_driver(db, fx["company"], fx["driver"])
            try:
                await reconcile_driver_end_of_day(
                    session_id=2_147_483_648,
                    payload=VehicleReconciliationRequest(counts=[]),
                    db=db,
                    current_driver=driver,
                )
            except HTTPException as exc:
                if exc.status_code != 422:
                    raise AssertionError(f"oversized session_id expected 422, got {exc.status_code}")
            else:
                raise AssertionError("oversized session_id unexpectedly reached reconciliation")
        print("SESSION_ID_BOUND=OK")

        # DB invariant: a WorkSession can belong to only one DispatchRoute.
        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            duplicate_route = DispatchRoute(
                company_id=fx["company"],
                zone_id=fx["zone"],
                driver_id=fx["driver"],
                vehicle_id=fx["vehicle"],
                work_session_id=fx["match_ws"],
                source_location_id=fx["warehouse_loc"],
                dispatch_date=date.today(),
                status="closed",
            )
            db.add(duplicate_route)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
            else:
                raise AssertionError("DB allowed two DispatchRoutes for one WorkSession")
        print("ROUTE_WORK_SESSION_UNIQUENESS=OK")

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

        # Field sale fulfills only the actually sold product shortage and records Visit provenance.
        async with AsyncSessionLocal() as db:
            field_driver = await load_driver(db, fx["company"], fx["field_driver"])
            result = await update_visit(
                visit_id=fx["field_visit"],
                payload=VisitUpdateRequest(
                    request_id=uuid.uuid4(),
                    outcome="Sale",
                    cash_collected=Decimal("0.000"),
                    debt_paid=Decimal("0.000"),
                    cart_items=[
                        VisitItemInput(
                            product_variant_id=fx["variant"],
                            quantity=0,
                            packs_quantity=1,
                        )
                    ],
                    returns=[],
                ),
                db=db,
                current_driver=field_driver,
            )
            if result.get("message") != "Visit updated successfully":
                raise AssertionError(f"field sale failed: {result}")

        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            sold = (
                await db.execute(
                    select(ShortageRequest).where(
                        ShortageRequest.company_id == fx["company"],
                        ShortageRequest.id == fx["shortage_sold"],
                    )
                )
            ).scalar_one()
            unsold = (
                await db.execute(
                    select(ShortageRequest).where(
                        ShortageRequest.company_id == fx["company"],
                        ShortageRequest.id == fx["shortage_unsold"],
                    )
                )
            ).scalar_one()
            if sold.status != "fulfilled" or sold.fulfilled_by_visit_id != fx["field_visit"] or sold.fulfilled_at is None:
                raise AssertionError("sold product shortage was not fulfilled with Visit provenance")
            if unsold.status != "pending" or unsold.fulfilled_by_visit_id is not None or unsold.fulfilled_at is not None:
                raise AssertionError("unsold product shortage was incorrectly fulfilled")
        print("SHORTAGE_PRODUCT_SCOPE=OK")

        # Reversing that Visit reopens only requests fulfilled by that exact Visit.
        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            ws = (
                await db.execute(
                    select(WorkSession).where(
                        WorkSession.company_id == fx["company"],
                        WorkSession.id == fx["field_ws"],
                    )
                )
            ).scalar_one()
            visit = (
                await db.execute(
                    select(Visit).where(
                        Visit.company_id == fx["company"],
                        Visit.id == fx["field_visit"],
                    )
                )
            ).scalar_one()
            shop = (
                await db.execute(
                    select(Shop).where(
                        Shop.company_id == fx["company"],
                        Shop.id == fx["field_shop"],
                    )
                )
            ).scalar_one()
            await reverse_previous_visit_state(
                db,
                visit,
                ws,
                shop,
                admin_id=fx["field_driver"],
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            rows = (
                await db.execute(
                    select(ShortageRequest).where(
                        ShortageRequest.company_id == fx["company"],
                        ShortageRequest.id.in_([fx["shortage_sold"], fx["shortage_unsold"]]),
                    )
                )
            ).scalars().all()
            if any(row.status != "pending" or row.fulfilled_by_visit_id is not None or row.fulfilled_at is not None for row in rows):
                raise AssertionError("Visit reversal did not restore shortage provenance exactly")
        print("SHORTAGE_REVERSAL_PROVENANCE=OK")

        # 3) Exact aggregate count reconciles inventory only and freezes ending snapshot by status.
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
            if ws.is_settled:
                raise AssertionError("inventory reconciliation must not financially settle WorkSession")
            if ws.inventory_reconciled_at is None or ws.inventory_reconciled_by != fx["driver"]:
                raise AssertionError("exact match did not stamp inventory reconciliation")
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
        print("EXACT_MATCH_INVENTORY_RECONCILIATION=OK")

        replay = await call_reconcile(fx, fx["match_ws"], 12)
        if replay.get("already_reconciled") is not True:
            raise AssertionError(f"exact replay not state-idempotent: {replay}")
        print("EXACT_REPLAY_IDEMPOTENCY=OK")

        # Finalizer must reject another non-admin driver even inside the same Tenant.
        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            try:
                await finalize_vehicle_inventory_reconciliation(
                    db,
                    company_id=fx["company"],
                    work_session_id=fx["guard_ws"],
                    vehicle_location_id=fx["guard_loc"],
                    settled_by=fx["intruder_driver"],
                )
            except InventoryMutationError:
                await db.rollback()
            else:
                raise AssertionError("non-owner non-admin finalized another driver's vehicle custody")
        print("FINALIZER_ACTOR_GUARD=OK")

        # Finalizer must reject any outstanding reservation even when called directly as a service.
        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            try:
                await finalize_vehicle_inventory_reconciliation(
                    db,
                    company_id=fx["company"],
                    work_session_id=fx["guard_ws"],
                    vehicle_location_id=fx["guard_loc"],
                    settled_by=fx["guard_driver"],
                )
            except InventoryMutationError as exc:
                await db.rollback()
                if "محجوز" not in str(exc):
                    raise AssertionError(f"reservation guard raised wrong error: {exc}")
            else:
                raise AssertionError("finalizer stamped Ending Snapshot with reserved stock")
        print("FINALIZER_RESERVATION_GUARD=OK")

        # DB invariant: financial settlement is forbidden before inventory reconciliation.
        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            ws = (
                await db.execute(
                    select(WorkSession).where(
                        WorkSession.company_id == fx["company"],
                        WorkSession.id == fx["variance_ws"],
                    ).with_for_update()
                )
            ).scalar_one()
            if ws.inventory_reconciled_at is not None:
                raise AssertionError("variance fixture unexpectedly inventory-reconciled")
            ws.is_settled = True
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
            else:
                raise AssertionError("DB allowed financial settlement before inventory reconciliation")
        print("FINANCIAL_SETTLEMENT_REQUIRES_INVENTORY_RECON=OK")

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
                raise AssertionError("variance WorkSession financially settled before approval")
            if ws.inventory_reconciled_at is not None:
                raise AssertionError("variance WorkSession inventory-reconciled before approval/posting")
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

        # 5) Admin detailed batch/status count -> approval -> posting -> inventory reconciliation only.
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
            if ws.is_settled:
                raise AssertionError("POSTED VEHICLE_RECON must not financially settle WorkSession")
            if ws.inventory_reconciled_at is None or ws.inventory_reconciled_by != fx["admin"]:
                raise AssertionError("POSTED VEHICLE_RECON did not stamp inventory reconciliation")
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
        print("APPROVED_RECON_POST_AND_INVENTORY_RECONCILIATION=OK")

        # POSTED replay must remain idempotent before financial settlement.
        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            replay_movements = await post_approved_stocktake_adjustments(
                db,
                company_id=fx["company"],
                stocktake_session_id=stocktake_id,
                stocktake_count_attempt_id=attempt_id,
                performed_by=fx["admin"],
            )
            if len(replay_movements) != 1 or replay_movements[0].reference_type != "DRIVER_SURPLUS":
                raise AssertionError("POSTED replay did not return the existing DRIVER_SURPLUS movement")
            ws = (
                await db.execute(
                    select(WorkSession).where(
                        WorkSession.company_id == fx["company"],
                        WorkSession.id == fx["variance_ws"],
                    )
                )
            ).scalar_one()
            if ws.is_settled:
                raise AssertionError("POSTED replay unexpectedly required/performed financial settlement")
            await db.rollback()
        print("POSTED_REPLAY_BEFORE_FINANCE=OK")

        # Once inventory is reconciled, a later accountant-owned financial settlement is DB-valid.
        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            ws = (
                await db.execute(
                    select(WorkSession).where(
                        WorkSession.company_id == fx["company"],
                        WorkSession.id == fx["match_ws"],
                    ).with_for_update()
                )
            ).scalar_one()
            if ws.inventory_reconciled_at is None:
                raise AssertionError("cannot test finance: inventory reconciliation marker missing")
            ws.is_settled = True
            await db.commit()

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
                raise AssertionError("financial settlement after inventory reconciliation did not persist")
        print("FINANCIAL_SETTLEMENT_AFTER_INVENTORY_ALLOWED=OK")

        print("DRIVER_RECONCILIATION_FREEZE_GATE_POSTGRES_OK")

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
