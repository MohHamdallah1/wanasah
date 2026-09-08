from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import bcrypt
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, "wa_backend")

from config import Config
from context import tenant_context
from database import AsyncSessionLocal
from models import (
    Company,
    DispatchRoute,
    Driver,
    InventoryBalance,
    InventoryLocation,
    InventoryLock,
    InventoryMovement,
    InventoryTransferHeader,
    InventoryTransferLine,
    Product,
    ProductBatch,
    ProductVariant,
    SessionInventorySnapshot,
    Shop,
    ShortageRequest,
    StocktakeCountAttempt,
    StocktakeCountAttemptLine,
    StocktakeLine,
    StocktakeSession,
    UOM,
    Vehicle,
    Visit,
    WorkSession,
    Zone,
)
from schemas import (
    CreateShortageItem,
    EditShopDetailsRequest,
    ForceCancelHandshakeRequest,
    RestoreZoneRequest,
    UpdateRouteStatusRequest,
    VisitItemInput,
    VisitUpdateRequest,
)
from services import (
    apply_inventory_movements_batch,
    get_company_local_date,
    post_approved_stocktake_adjustments,
)
from api.dispatch import (
    _dispatch_driver_shortage_cash,
    add_shortages,
    archive_zone,
    edit_shop_details,
    force_cancel_handshake,
    restore_zone,
    update_route_status,
)
from api.driver import update_visit

PASSWORD = "PolicyTest!2026"


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


async def load_driver(db, company_id: int, driver_id: int) -> Driver:
    await set_tenant(db, company_id)
    return (
        await db.execute(
            select(Driver).where(Driver.company_id == company_id, Driver.id == driver_id)
        )
    ).scalar_one()


async def setup_fixture() -> dict:
    suffix = uuid.uuid4().hex[:10]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    password_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()

    async with AsyncSessionLocal() as db:
        uom = UOM(name=f"Policy Unit {suffix}", code=f"PU{suffix[:8]}")
        company = Company(
            name=f"Policy Company {suffix}",
            company_code=f"PC{suffix}",
            is_active=True,
            subscription_status="active",
            currency_code="JOD",
            timezone="Asia/Amman",
        )
        other_company = Company(
            name=f"Policy Other {suffix}",
            company_code=f"PO{suffix}",
            is_active=True,
            subscription_status="active",
            currency_code="JOD",
            timezone="Asia/Amman",
        )
        db.add_all([uom, company, other_company])
        await db.flush()

        await set_tenant(db, company.id)
        local_day = await get_company_local_date(db, company.id)

        admin = Driver(
            company_id=company.id,
            username=f"policy_admin_{suffix}",
            password_hash=password_hash,
            full_name="Policy Admin",
            is_active=True,
            is_admin=True,
        )
        driver_a = Driver(
            company_id=company.id,
            username=f"policy_a_{suffix}",
            password_hash=password_hash,
            full_name="Driver A",
            is_active=True,
            is_admin=False,
            can_allow_debt=True,
            max_debt_limit=Decimal("1000.000"),
        )
        driver_b = Driver(
            company_id=company.id,
            username=f"policy_b_{suffix}",
            password_hash=password_hash,
            full_name="Driver B",
            is_active=True,
            is_admin=False,
        )
        driver_c = Driver(
            company_id=company.id,
            username=f"policy_c_{suffix}",
            password_hash=password_hash,
            full_name="Driver C",
            is_active=True,
            is_admin=False,
        )
        zone_main = Zone(
            company_id=company.id,
            name=f"Main Zone {suffix}",
            start_date=local_day,
            interval_days=7,
            is_active=True,
        )
        zone_target = Zone(company_id=company.id, name=f"Target Zone {suffix}", is_active=True)
        zone_restore = Zone(company_id=company.id, name=f"Restore Zone {suffix}", is_active=True)
        zone_schedule = Zone(
            company_id=company.id,
            name=f"Schedule Zone {suffix}",
            start_date=local_day,
            interval_days=14,
            is_active=True,
        )
        product = Product(company_id=company.id, base_name=f"Policy Product {suffix}")
        db.add_all([admin, driver_a, driver_b, driver_c, zone_main, zone_target, zone_restore, zone_schedule, product])
        await db.flush()

        variant_a = ProductVariant(
            company_id=company.id,
            product_id=product.id,
            base_uom_id=uom.id,
            variant_name=f"Variant A {suffix}",
            sku=f"PA-{suffix}",
            packs_per_carton=24,
            price_per_carton=Decimal("24.000"),
            price_per_pack=Decimal("1.000"),
            is_active=True,
        )
        variant_b = ProductVariant(
            company_id=company.id,
            product_id=product.id,
            base_uom_id=uom.id,
            variant_name=f"Variant B {suffix}",
            sku=f"PB-{suffix}",
            packs_per_carton=12,
            price_per_carton=Decimal("12.000"),
            price_per_pack=Decimal("1.000"),
            is_active=True,
        )
        db.add_all([variant_a, variant_b])
        await db.flush()

        batch_a = ProductBatch(
            company_id=company.id,
            product_variant_id=variant_a.id,
            batch_number=f"BA-{suffix}",
            production_date=local_day - timedelta(days=5),
            expiry_date=local_day + timedelta(days=365),
            is_active=True,
        )
        batch_b = ProductBatch(
            company_id=company.id,
            product_variant_id=variant_b.id,
            batch_number=f"BB-{suffix}",
            production_date=local_day - timedelta(days=5),
            expiry_date=local_day + timedelta(days=365),
            is_active=True,
        )
        vehicle_a = Vehicle(
            company_id=company.id,
            plate_number=f"A-{suffix[:8]}",
            maintenance_status="Active",
            is_active=True,
        )
        vehicle_shortage = Vehicle(
            company_id=company.id,
            plate_number=f"S-{suffix[:8]}",
            maintenance_status="Active",
            is_active=True,
        )
        vehicle_c = Vehicle(
            company_id=company.id,
            plate_number=f"C-{suffix[:8]}",
            maintenance_status="Active",
            is_active=True,
        )
        db.add_all([batch_a, batch_b, vehicle_a, vehicle_shortage, vehicle_c])
        await db.flush()

        warehouse = InventoryLocation(
            company_id=company.id,
            name=f"Policy Warehouse {suffix}",
            code=f"PW-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        vehicle_a_loc = InventoryLocation(
            company_id=company.id,
            name=f"Vehicle A {suffix}",
            code=f"VA-{suffix}",
            location_type="VEHICLE",
            vehicle_id=vehicle_a.id,
            is_active=True,
        )
        shortage_loc = InventoryLocation(
            company_id=company.id,
            name=f"Shortage Vehicle {suffix}",
            code=f"SV-{suffix}",
            location_type="VEHICLE",
            vehicle_id=vehicle_shortage.id,
            is_active=True,
        )
        vehicle_c_loc = InventoryLocation(
            company_id=company.id,
            name=f"Vehicle C {suffix}",
            code=f"VC-{suffix}",
            location_type="VEHICLE",
            vehicle_id=vehicle_c.id,
            is_active=True,
        )
        db.add_all([warehouse, vehicle_a_loc, shortage_loc, vehicle_c_loc])
        await db.flush()

        shop = Shop(
            company_id=company.id,
            name=f"Emergency Shop {suffix}",
            phone_number=f"079{suffix[:7]}",
            zone_id=zone_main.id,
            current_balance=Decimal("0.000"),
            max_debt_limit=Decimal("1000.000"),
            is_active=True,
            is_archived=False,
        )
        restore_shop = Shop(
            company_id=company.id,
            name=f"Restore Auto {suffix}",
            zone_id=zone_restore.id,
            current_balance=Decimal("0.000"),
            max_debt_limit=Decimal("0.000"),
            is_active=True,
            is_archived=False,
        )
        restore_shop_2 = Shop(
            company_id=company.id,
            name=f"Restore Auto 2 {suffix}",
            zone_id=zone_restore.id,
            current_balance=Decimal("0.000"),
            max_debt_limit=Decimal("0.000"),
            is_active=True,
            is_archived=False,
        )
        manual_archived = Shop(
            company_id=company.id,
            name=f"Manual Archived {suffix}",
            zone_id=zone_restore.id,
            current_balance=Decimal("0.000"),
            max_debt_limit=Decimal("0.000"),
            is_active=True,
            is_archived=True,
        )
        db.add_all([shop, restore_shop, restore_shop_2, manual_archived])
        await db.flush()

        ws_a = WorkSession(
            company_id=company.id,
            driver_id=driver_a.id,
            session_date=local_day,
            start_time=now - timedelta(hours=1),
            end_time=None,
            is_authorized_to_sell=True,
            is_settled=False,
        )
        db.add(ws_a)
        await db.flush()
        route_a = DispatchRoute(
            company_id=company.id,
            zone_id=zone_main.id,
            driver_id=driver_a.id,
            vehicle_id=vehicle_a.id,
            work_session_id=ws_a.id,
            source_location_id=warehouse.id,
            dispatch_date=local_day,
            status="active",
        )
        route_schedule = DispatchRoute(
            company_id=company.id,
            zone_id=zone_schedule.id,
            driver_id=driver_c.id,
            vehicle_id=vehicle_c.id,
            source_location_id=warehouse.id,
            dispatch_date=local_day,
            status="waiting",
        )
        db.add_all([route_a, route_schedule])

        db.add_all([
            InventoryBalance(
                company_id=company.id,
                location_id=vehicle_a_loc.id,
                product_variant_id=variant_a.id,
                batch_id=batch_a.id,
                stock_status="AVAILABLE",
                on_hand_quantity=100,
                reserved_quantity=0,
            ),
            InventoryBalance(
                company_id=company.id,
                location_id=warehouse.id,
                product_variant_id=variant_b.id,
                batch_id=batch_b.id,
                stock_status="AVAILABLE",
                on_hand_quantity=50,
                reserved_quantity=0,
            ),
            InventoryBalance(
                company_id=company.id,
                location_id=shortage_loc.id,
                product_variant_id=variant_a.id,
                batch_id=batch_a.id,
                stock_status="AVAILABLE",
                on_hand_quantity=10,
                reserved_quantity=0,
            ),
        ])

        # Ended session prepared for a direct approved VEHICLE_RECON shortage posting.
        ws_shortage = WorkSession(
            company_id=company.id,
            driver_id=driver_b.id,
            session_date=local_day,
            start_time=now - timedelta(hours=5),
            end_time=now - timedelta(hours=2),
            is_authorized_to_sell=True,
            is_settled=False,
        )
        db.add(ws_shortage)
        await db.flush()
        route_shortage = DispatchRoute(
            company_id=company.id,
            zone_id=zone_target.id,
            driver_id=driver_b.id,
            vehicle_id=vehicle_shortage.id,
            work_session_id=ws_shortage.id,
            source_location_id=warehouse.id,
            dispatch_date=local_day,
            status="closed",
        )
        snap = SessionInventorySnapshot(
            company_id=company.id,
            work_session_id=ws_shortage.id,
            location_id=shortage_loc.id,
            product_variant_id=variant_a.id,
            stock_status="AVAILABLE",
            starting_quantity=10,
        )
        db.add_all([route_shortage, snap])
        await db.flush()

        t0 = now - timedelta(minutes=20)
        stocktake = StocktakeSession(
            company_id=company.id,
            location_id=shortage_loc.id,
            reference_number=f"POL-ST-{suffix}",
            stocktake_type="VEHICLE_RECON",
            status="APPROVED",
            related_work_session_id=ws_shortage.id,
            snapshot_cutoff_at=t0 + timedelta(minutes=1),
            started_by=admin.id,
            approved_by=admin.id,
            created_at=t0,
            approved_at=t0 + timedelta(minutes=3),
        )
        db.add(stocktake)
        await db.flush()
        st_line = StocktakeLine(
            company_id=company.id,
            stocktake_session_id=stocktake.id,
            product_variant_id=variant_a.id,
            batch_id=batch_a.id,
            stock_status="AVAILABLE",
            line_origin="SNAPSHOT",
            expected_quantity=10,
        )
        attempt = StocktakeCountAttempt(
            company_id=company.id,
            stocktake_session_id=stocktake.id,
            attempt_number=1,
            counted_by=admin.id,
            requires_independent_recount=False,
            submitted_at=t0 + timedelta(minutes=2),
        )
        db.add_all([st_line, attempt])
        await db.flush()
        attempt_line = StocktakeCountAttemptLine(
            company_id=company.id,
            stocktake_session_id=stocktake.id,
            count_attempt_id=attempt.id,
            stocktake_line_id=st_line.id,
            expected_quantity=10,
            actual_quantity=9,
            variance_quantity=-1,
        )
        lock = InventoryLock(
            company_id=company.id,
            stocktake_session_id=stocktake.id,
            location_id=shortage_loc.id,
            product_variant_id=None,
            batch_id=None,
            created_by=admin.id,
        )
        db.add_all([attempt_line, lock])
        await db.commit()

        await set_tenant(db, other_company.id)
        other_admin = Driver(
            company_id=other_company.id,
            username=f"policy_other_{suffix}",
            password_hash=password_hash,
            full_name="Other Admin",
            is_active=True,
            is_admin=True,
        )
        db.add(other_admin)
        await db.commit()

        return {
            "company": company.id,
            "other_company": other_company.id,
            "uom": uom.id,
            "local_day": local_day,
            "admin": admin.id,
            "other_admin": other_admin.id,
            "driver_a": driver_a.id,
            "driver_b": driver_b.id,
            "zone_main": zone_main.id,
            "zone_target": zone_target.id,
            "zone_restore": zone_restore.id,
            "zone_schedule": zone_schedule.id,
            "shop": shop.id,
            "restore_shop": restore_shop.id,
            "restore_shop_2": restore_shop_2.id,
            "manual_archived": manual_archived.id,
            "variant_a": variant_a.id,
            "variant_b": variant_b.id,
            "batch_a": batch_a.id,
            "batch_b": batch_b.id,
            "warehouse": warehouse.id,
            "vehicle_a_loc": vehicle_a_loc.id,
            "shortage_loc": shortage_loc.id,
            "ws_a": ws_a.id,
            "route_a": route_a.id,
            "route_schedule": route_schedule.id,
            "ws_shortage": ws_shortage.id,
            "stocktake": stocktake.id,
            "attempt": attempt.id,
        }


async def cleanup(fx: dict) -> None:
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
                    "inventory_transfer_lines",
                    "inventory_transfer_headers",
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
                    "dispatch_load_plan_lines",
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
        raise RuntimeError("POLICY_TEST_CLEANUP_FAILED: " + " | ".join(errors))


async def main() -> None:
    safety_gate()
    fx = await setup_fixture()
    failure = None
    try:
        # 1) Two drivers may own independent emergency visits to the same shop on the same company-local day.
        async with AsyncSessionLocal() as db:
            admin = await load_driver(db, fx["company"], fx["admin"])
            await add_shortages(
                payload=[
                    CreateShortageItem(
                        shopId=fx["shop"], zoneId=fx["zone_main"], productId=fx["variant_a"],
                        driverId=fx["driver_a"], quantity=2,
                    ),
                    CreateShortageItem(
                        shopId=fx["shop"], zoneId=fx["zone_main"], productId=fx["variant_b"],
                        driverId=fx["driver_b"], quantity=3,
                    ),
                ],
                db=db,
                current_admin=admin,
            )

        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            visits = (
                await db.execute(
                    select(Visit).where(
                        Visit.company_id == fx["company"],
                        Visit.shop_id == fx["shop"],
                        Visit.status == "Pending",
                        Visit.is_emergency.is_(True),
                    ).order_by(Visit.driver_id.asc())
                )
            ).scalars().all()
            owners = {(int(v.driver_id), v.operational_date) for v in visits}
            expected = {(fx["driver_a"], fx["local_day"]), (fx["driver_b"], fx["local_day"])}
            if owners != expected:
                raise AssertionError(f"emergency ownership mismatch: {owners}")
            visit_a = next(v for v in visits if int(v.driver_id) == fx["driver_a"])
            visit_a.work_session_id = fx["ws_a"]
            # Same product, different owner: sale by A must not fulfill B's shortage.
            db.add(ShortageRequest(
                company_id=fx["company"],
                zone_id=fx["zone_main"],
                shop_id=fx["shop"],
                driver_id=fx["driver_b"],
                product_variant_id=fx["variant_a"],
                quantity=1,
                status="pending",
            ))
            await db.commit()
            visit_a_id = int(visit_a.id)
        print("EMERGENCY_DRIVER_OWNERSHIP=OK")

        # 2) Field sale fulfills only its own/unassigned shortage, never another driver's same-product shortage.
        async with AsyncSessionLocal() as db:
            driver_a = await load_driver(db, fx["company"], fx["driver_a"])
            await update_visit(
                visit_id=visit_a_id,
                payload=VisitUpdateRequest(
                    request_id=uuid.uuid4(),
                    outcome="Sale",
                    cash_collected=Decimal("24.000"),
                    debt_paid=Decimal("0.000"),
                    cart_items=[VisitItemInput(product_variant_id=fx["variant_a"], quantity=1)],
                    returns=[],
                ),
                db=db,
                current_driver=driver_a,
            )

        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            rows = (
                await db.execute(
                    select(ShortageRequest).where(
                        ShortageRequest.company_id == fx["company"],
                        ShortageRequest.shop_id == fx["shop"],
                        ShortageRequest.product_variant_id == fx["variant_a"],
                    ).order_by(ShortageRequest.id.asc())
                )
            ).scalars().all()
            by_driver = {int(r.driver_id): r.status for r in rows if r.driver_id is not None}
            if by_driver.get(fx["driver_a"]) != "fulfilled" or by_driver.get(fx["driver_b"]) != "pending":
                raise AssertionError(f"shortage owner fulfillment corrupted: {by_driver}")
        print("EMERGENCY_FULFILLMENT_SCOPE=OK")

        # 3) Active-route Pending visit blocks moving the shop to another zone.
        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            db.add(Visit(
                company_id=fx["company"],
                driver_id=fx["driver_a"],
                shop_id=fx["shop"],
                work_session_id=fx["ws_a"],
                operational_date=fx["local_day"],
                status="Pending",
                outcome="Pending",
                is_emergency=False,
            ))
            await db.commit()

        async with AsyncSessionLocal() as db:
            admin = await load_driver(db, fx["company"], fx["admin"])
            try:
                await edit_shop_details(
                    shop_id=str(fx["shop"]),
                    payload=EditShopDetailsRequest(zoneId=fx["zone_target"]),
                    db=db,
                    current_admin=admin,
                )
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise AssertionError(f"zone move expected 409, got {exc.status_code}")
            else:
                raise AssertionError("shop moved while active-route Pending visit existed")
        print("SHOP_ZONE_MOVE_GUARD=OK")

        # 4) Numeric schedule: closing a route advances from company-local close day by interval_days.
        async with AsyncSessionLocal() as db:
            admin = await load_driver(db, fx["company"], fx["admin"])
            await update_route_status(
                route_id=fx["route_schedule"],
                payload=UpdateRouteStatusRequest(status="closed"),
                db=db,
                current_admin=admin,
            )
        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            zone = (await db.execute(select(Zone).where(Zone.id == fx["zone_schedule"], Zone.company_id == fx["company"]))).scalar_one()
            if zone.start_date != fx["local_day"] + timedelta(days=14) or int(zone.interval_days) != 14:
                raise AssertionError(f"numeric schedule mismatch: {zone.start_date}/{zone.interval_days}")
        print("NUMERIC_SCHEDULE=OK")

        # 5) Zone restore provenance: zone-only does not resurrect shops; selected/all never revive manually archived shop.
        async with AsyncSessionLocal() as db:
            admin = await load_driver(db, fx["company"], fx["admin"])
            await archive_zone(zone_id=fx["zone_restore"], db=db, current_admin=admin)

        async with AsyncSessionLocal() as db:
            admin = await load_driver(db, fx["company"], fx["admin"])
            await restore_zone(
                zone_id=fx["zone_restore"], payload=RestoreZoneRequest(mode="zone_only"), db=db, current_admin=admin
            )
        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            states = {
                int(s.id): (bool(s.is_archived), s.archived_due_to_zone_id)
                for s in (await db.execute(select(Shop).where(Shop.company_id == fx["company"], Shop.zone_id == fx["zone_restore"]))).scalars().all()
            }
            if states[fx["restore_shop"]][0] is not True or states[fx["restore_shop_2"]][0] is not True:
                raise AssertionError("zone_only resurrected auto-archived shops")
            if states[fx["manual_archived"]][1] is not None:
                raise AssertionError("manual archive incorrectly received zone provenance")

        async with AsyncSessionLocal() as db:
            admin = await load_driver(db, fx["company"], fx["admin"])
            await restore_zone(
                zone_id=fx["zone_restore"],
                payload=RestoreZoneRequest(mode="selected", shop_ids=[fx["restore_shop"]]),
                db=db,
                current_admin=admin,
            )
        async with AsyncSessionLocal() as db:
            admin = await load_driver(db, fx["company"], fx["admin"])
            await restore_zone(
                zone_id=fx["zone_restore"],
                payload=RestoreZoneRequest(mode="all_zone_archived"),
                db=db,
                current_admin=admin,
            )
        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            states = {
                int(s.id): bool(s.is_archived)
                for s in (await db.execute(select(Shop).where(Shop.company_id == fx["company"], Shop.zone_id == fx["zone_restore"]))).scalars().all()
            }
            if states[fx["restore_shop"]] or states[fx["restore_shop_2"]]:
                raise AssertionError("auto-archived shops were not restored")
            if not states[fx["manual_archived"]]:
                raise AssertionError("manual archived shop was resurrected")
        print("ZONE_RESTORE_PROVENANCE=OK")

        # 6) Force-cancel HANDSHAKE releases reservation only and is tenant-safe/idempotent.
        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            header = InventoryTransferHeader(
                company_id=fx["company"],
                reference_number=f"POL-HS-{uuid.uuid4().hex[:10]}",
                source_location_id=fx["warehouse"],
                destination_location_id=fx["vehicle_a_loc"],
                workflow_type="HANDSHAKE",
                status="PENDING",
                work_session_id=fx["ws_a"],
                expected_receiver_id=fx["driver_a"],
                dispatched_by=fx["admin"],
            )
            db.add(header)
            await db.flush()
            line = InventoryTransferLine(
                company_id=fx["company"],
                transfer_header_id=header.id,
                product_variant_id=fx["variant_b"],
                batch_id=fx["batch_b"],
                quantity=5,
            )
            db.add(line)
            await db.flush()
            await apply_inventory_movements_batch(
                db,
                company_id=fx["company"],
                performed_by=fx["admin"],
                movements=[{
                    "product_variant_id": fx["variant_b"],
                    "batch_id": fx["batch_b"],
                    "quantity": 5,
                    "movement_kind": "RESERVATION",
                    "reservation_action": "RESERVE",
                    "reference_type": "HANDSHAKE_RESERVE",
                    "reference_id": str(header.reference_number),
                    "idempotency_key": f"HS-RES-{header.id}-{line.id}",
                    "source_location_id": fx["warehouse"],
                    "destination_location_id": fx["warehouse"],
                    "source_stock_status": "AVAILABLE",
                    "destination_stock_status": "AVAILABLE",
                    "work_session_id": fx["ws_a"],
                    "transfer_header_id": header.id,
                    "notes": "policy test reserve",
                }],
            )
            await db.commit()
            transfer_id = int(header.id)

        request_id = uuid.uuid4()
        async with AsyncSessionLocal() as db:
            other_admin = await load_driver(db, fx["other_company"], fx["other_admin"])
            try:
                await force_cancel_handshake(
                    transfer_id=transfer_id,
                    payload=ForceCancelHandshakeRequest(request_id=uuid.uuid4(), reason="cross tenant attempt"),
                    db=db,
                    current_admin=other_admin,
                )
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise AssertionError(f"cross tenant force cancel expected 404, got {exc.status_code}")
            else:
                raise AssertionError("cross tenant force cancel unexpectedly succeeded")

        async with AsyncSessionLocal() as db:
            admin = await load_driver(db, fx["company"], fx["admin"])
            first = await force_cancel_handshake(
                transfer_id=transfer_id,
                payload=ForceCancelHandshakeRequest(request_id=request_id, reason="tablet unavailable"),
                db=db,
                current_admin=admin,
            )
            if first.get("status") != "CANCELLED":
                raise AssertionError(first)
        async with AsyncSessionLocal() as db:
            admin = await load_driver(db, fx["company"], fx["admin"])
            replay = await force_cancel_handshake(
                transfer_id=transfer_id,
                payload=ForceCancelHandshakeRequest(request_id=request_id, reason="tablet unavailable"),
                db=db,
                current_admin=admin,
            )
            if replay != first:
                raise AssertionError("force cancel replay changed response")

        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            bal = (await db.execute(select(InventoryBalance).where(
                InventoryBalance.company_id == fx["company"],
                InventoryBalance.location_id == fx["warehouse"],
                InventoryBalance.product_variant_id == fx["variant_b"],
                InventoryBalance.batch_id == fx["batch_b"],
                InventoryBalance.stock_status == "AVAILABLE",
            ))).scalar_one()
            hdr = (await db.execute(select(InventoryTransferHeader).where(
                InventoryTransferHeader.company_id == fx["company"], InventoryTransferHeader.id == transfer_id
            ))).scalar_one()
            movements = (await db.execute(select(InventoryMovement).where(
                InventoryMovement.company_id == fx["company"],
                InventoryMovement.transfer_header_id == transfer_id,
            ))).scalars().all()
            if int(bal.reserved_quantity or 0) != 0 or hdr.status != "CANCELLED":
                raise AssertionError("force cancel did not release reservation/close header")
            if any(m.movement_kind == "PHYSICAL" for m in movements):
                raise AssertionError("force cancel created PHYSICAL movement")
            if {m.reservation_action for m in movements} != {"RESERVE", "RELEASE"}:
                raise AssertionError("force cancel reservation ledger incomplete")
        print("HANDSHAKE_FORCE_CANCEL=OK")
        print("HANDSHAKE_TENANT_ISOLATION=OK")
        print("HANDSHAKE_FORCE_CANCEL_IDEMPOTENCY=OK")

        # 7) DRIVER_SHORTAGE price freezes at posting; later product-price change cannot rewrite liability.
        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            movements = await post_approved_stocktake_adjustments(
                db,
                company_id=fx["company"],
                stocktake_session_id=fx["stocktake"],
                stocktake_count_attempt_id=fx["attempt"],
                performed_by=fx["admin"],
            )
            if len(movements) != 1 or movements[0].reference_type != "DRIVER_SHORTAGE":
                raise AssertionError("expected one DRIVER_SHORTAGE")
            if Decimal(str(movements[0].financial_unit_price_snapshot)) != Decimal("1.000"):
                raise AssertionError("shortage price snapshot mismatch")
            variant = (await db.execute(select(ProductVariant).where(
                ProductVariant.company_id == fx["company"], ProductVariant.id == fx["variant_a"]
            ).with_for_update())).scalar_one()
            variant.price_per_pack = Decimal("7.000")
            await db.commit()

        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            liability = await _dispatch_driver_shortage_cash(
                db,
                company_id=fx["company"],
                work_session_id=fx["ws_shortage"],
            )
            if liability != Decimal("1.000"):
                raise AssertionError(f"historical shortage repriced to live price: {liability}")
            movement = (await db.execute(select(InventoryMovement).where(
                InventoryMovement.company_id == fx["company"],
                InventoryMovement.work_session_id == fx["ws_shortage"],
                InventoryMovement.reference_type == "DRIVER_SHORTAGE",
            ))).scalar_one()
            if Decimal(str(movement.financial_unit_price_snapshot)) != Decimal("1.000"):
                raise AssertionError("persisted shortage snapshot changed")
        print("DRIVER_SHORTAGE_PRICE_SNAPSHOT=OK")

        # 8) Company-local operational day is explicit and independent from UTC audit timestamps.
        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company"])
            local_day = await get_company_local_date(db, fx["company"])
            visit_days = set((await db.execute(select(Visit.operational_date).where(
                Visit.company_id == fx["company"], Visit.shop_id == fx["shop"]
            ))).scalars().all())
            if local_day not in visit_days or None in visit_days:
                raise AssertionError(f"operational day mismatch: local={local_day}, visits={visit_days}")
        print("COMPANY_LOCAL_OPERATIONAL_DAY=OK")

        print("DISPATCH_POLICY_OPERATIONAL_POSTGRES_OK")

    except Exception as exc:
        failure = exc
    finally:
        try:
            await cleanup(fx)
            print("TEST_CLEANUP=OK")
        except Exception as cleanup_exc:
            if failure is None:
                failure = cleanup_exc
            else:
                failure = RuntimeError(f"{failure} | cleanup failed: {cleanup_exc}")

    if failure is not None:
        raise failure


if __name__ == "__main__":
    asyncio.run(main())
