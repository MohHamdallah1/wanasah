"""Independent M04 M01-backed read gate, NOT final count/finance acceptance.

Uses only an already Alembic-migrated synthetic PG16 DB on 127.0.0.1:55494.
Fixtures are retained; no DDL/create_all, production data or auth overrides.
Actual A/B/A commercial execution and signed checkpoint writes are the later
M02+M03+ordered-M04-migration integration gate.
"""
from datetime import timedelta
from decimal import Decimal
import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from database import engine as http_engine
from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from domains.identity.models import CompanyPrincipal
from domains.representative_settlement_multi_vehicle.contracts import CustodyRejected
from domains.representative_settlement_multi_vehicle.resolution import session_responsibilities
from main import app
from models import (
    Company, DispatchRoute, InventoryBalance, InventoryLocation, InventoryMovement,
    Product, ProductBatch, ProductVariant, UOM, UserLocationAccess, Vehicle, WorkSession,
    Zone, utc_now,
)
from services import apply_inventory_movement
from tests.canonical_actor_fixtures import seed_field_fixture, seed_ordinary_backoffice_fixture
from tests.test_cp14c_stocktake_lifecycle_postgres import (
    _ensure_permissions, _grant_company, _grant_location, _runtime_session,
)

pytestmark = [pytest.mark.skipif(os.getenv("RUN_M04_PG16") != "1",
                                reason="Explicit isolated M04 PG16 gate only"),
              pytest.mark.asyncio(loop_scope="function")]
PASSWORD = "M04ReceiverSynthetic123"


def checked_urls():
    urls = [make_url(os.environ[k]) for k in ("DATABASE_URL", "DATABASE_URL_MIGRATION")]
    for url in urls:
        assert (url.drivername, url.host, url.port, url.database) == (
            "postgresql+asyncpg", "127.0.0.1", 55494, "wanasah_m04_test")
    assert urls[0].username == "wanasah_app" and urls[1].username != urls[0].username
    assert http_engine.url == urls[0]
    return urls


async def seed(admin):
    async with AsyncSession(admin, expire_on_commit=False) as db:
        company = Company(name="M04 read gate", company_code="M04-" + uuid4().hex,
                          timezone="Asia/Amman", currency_code="JOD")
        db.add(company)
        await db.flush()
        await db.execute(text("SELECT set_config('app.current_tenant',:c,true)"), {"c": str(company.id)})
        receiver = await seed_ordinary_backoffice_fixture(db, company.id, password=PASSWORD)
        limited = await seed_ordinary_backoffice_fixture(db, company.id, password=PASSWORD)
        field = await seed_field_fixture(db, company.id)
        await _ensure_permissions(db, {"settlement.read", "inventory.read"})
        for actor in (receiver, limited):
            await _grant_company(db, company_id=company.id, driver_id=actor.driver_id,
                                 code="settlement.read")
        uom = await db.scalar(select(UOM).where(UOM.code == "EACH"))
        product = Product(company_id=company.id, code="M04P", name="M04 stock")
        db.add(product)
        await db.flush()
        variant = ProductVariant(company_id=company.id, product_id=product.id,
                                 base_uom_id=uom.id, name="M04 SKU", sku="M04SKU",
                                 quantity_scale=3, quantity_step=Decimal(".001"),
                                 lifecycle_status="ACTIVE", published_at=utc_now())
        db.add(variant)
        await db.flush()
        batch = ProductBatch(company_id=company.id, product_variant_id=variant.id,
                             batch_number="M04-LOT")
        db.add(batch)
        zone = Zone(company_id=company.id, name="M04 zone", is_active=True)
        db.add(zone)
        await db.flush()
        start = utc_now() - timedelta(hours=4)
        work = WorkSession(company_id=company.id, driver_id=field.driver.id,
                           start_time=start, end_time=start + timedelta(hours=3),
                           session_date=start.date(), is_settled=False)
        db.add(work)
        await db.flush()
        cars, locations, routes = [], [], []
        for name in ("A", "B"):
            car = Vehicle(company_id=company.id, plate_number="M04-" + name + uuid4().hex[:5],
                          maintenance_status="Active", is_active=True)
            db.add(car)
            await db.flush()
            location = InventoryLocation(company_id=company.id, code="M04-" + name,
                                         name="M04 car " + name, location_type="VEHICLE",
                                         vehicle_id=car.id, is_active=True)
            db.add(location)
            await db.flush()
            # Deliberately NO legacy route.work_session_id. M04 must use periods.
            route = DispatchRoute(company_id=company.id, zone_id=zone.id,
                                  driver_id=field.driver.id, vehicle_id=car.id,
                                  source_location_id=location.id, dispatch_date=start.date(), status="closed")
            db.add(route)
            await db.flush()
            cars.append(car.id)
            locations.append(location.id)
            routes.append(route.id)
            await _grant_location(db, company_id=company.id, driver_id=receiver.driver_id,
                                  location_id=location.id, codes=("inventory.read",))
        await _grant_location(db, company_id=company.id, driver_id=limited.driver_id,
                              location_id=locations[0], codes=("inventory.read",))
        for i, car_index in enumerate((0, 1, 0)):
            began = start + timedelta(hours=i)
            ended = began + timedelta(minutes=50)
            db.add(DispatchRouteExecutionPeriod(
                company_id=company.id, route_id=routes[car_index], work_session_id=work.id,
                driver_id=field.driver.id, field_representative_id=field.context.representative_id,
                vehicle_id=cars[car_index], vehicle_location_id=locations[car_index], state="CLOSED",
                context_revision=1 if i < 2 else 2, started_at=began, ended_at=ended,
                started_by_principal_id=receiver.context.principal_id,
                ended_by_principal_id=receiver.context.principal_id,
                request_id=str(uuid4()), payload_hash="a" * 64, evidence_origin="CANONICAL",
            ))
            db.add(VehicleCustodyEpoch(
                company_id=company.id, vehicle_id=cars[car_index],
                vehicle_location_id=locations[car_index], custodian_kind="FIELD_REPRESENTATIVE",
                custodian_principal_id=field.context.principal_id,
                field_representative_id=field.context.representative_id,
                # M03 accepts pre-session custody without rewriting its signed
                # related_session_id. Period+identity+time is the explicit link.
                related_session_id=work.id if i == 1 else None,
                accepted_by_principal_id=receiver.context.principal_id, state="ACCEPTED",
                context_revision=1 if i < 2 else 2, started_at=began,
                ended_at=began + timedelta(hours=1),
                request_id=str(uuid4()), payload_hash="b" * 64, evidence_origin="CANONICAL",
            ))
        await db.commit()
        return dict(company=company.id, code=company.company_code, receiver=receiver,
                    limited=limited, session=work.id, cars=cars, locations=locations,
                    variant=variant.id, batch=batch.id)


async def token(http, admin, state, actor):
    async with AsyncSession(admin) as db:
        username = await db.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.company_id == state["company"],
            CompanyPrincipal.id == actor.context.principal_id))
    reply = await http.post("/login", json={"company_code": state["code"],
                                            "username": username, "password": PASSWORD})
    assert reply.status_code == 200, reply.text
    return {"Authorization": "Bearer " + reply.json()["token"]}


async def fingerprint(db, company):
    return (list((await db.execute(select(
        InventoryBalance.location_id, InventoryBalance.batch_id, InventoryBalance.stock_status,
        InventoryBalance.on_hand_quantity, InventoryBalance.reserved_quantity,
    ).where(InventoryBalance.company_id == company).order_by(InventoryBalance.id))).all()),
        await db.scalar(select(func.count()).select_from(InventoryMovement).where(
            InventoryMovement.company_id == company)))


async def test_real_pg16_rls_and_bearer_two_vehicle_count_sheets_are_read_only_and_scoped():
    runtime_url, admin_url = checked_urls()
    runtime = create_async_engine(runtime_url, poolclass=NullPool)
    admin = create_async_engine(admin_url, poolclass=NullPool)
    try:
        state, foreign = await seed(admin), await seed(admin)
        company = state["company"]
        async with _runtime_session(runtime, company) as db:
            assert 160000 <= int(await db.scalar(text("SHOW server_version_num"))) < 170000
            role = (await db.execute(text(
                "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"))).one()
            assert role == (False, False)
            for table in ("dispatch_route_execution_periods", "vehicle_custody_epochs", "inventory_balances"):
                assert (await db.execute(text(
                    "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=to_regclass(:t)"
                ), {"t": table})).one() == (True, True)
            work, responsibilities = await session_responsibilities(
                db, company_id=company, session_id=state["session"])
            assert len(responsibilities) == 2
            assert len(responsibilities[0].period_ids) == 2
            # These are movement-engine fixtures, NOT FIELD sale/finance proof.
            for index, quantity in ((0, "100"), (1, "60")):
                await apply_inventory_movement(
                    db, company_id=company, performed_by=state["receiver"].driver_id,
                    product_variant_id=state["variant"], batch_id=state["batch"],
                    quantity=Decimal(quantity), movement_kind="PHYSICAL",
                    reference_type="M04_TEST_OPENING", reference_id=str(work.id),
                    idempotency_key="M04-" + uuid4().hex,
                    destination_location_id=state["locations"][index], destination_stock_status="AVAILABLE")
            for index, quantity in ((0, "12"), (1, "7"), (0, "5")):
                await apply_inventory_movement(
                    db, company_id=company, performed_by=state["receiver"].driver_id,
                    product_variant_id=state["variant"], batch_id=state["batch"],
                    quantity=Decimal(quantity), movement_kind="PHYSICAL",
                    reference_type="M04_TEST_USAGE", reference_id=str(work.id),
                    idempotency_key="M04-" + uuid4().hex,
                    source_location_id=state["locations"][index], source_stock_status="AVAILABLE")
            await db.commit()
            before = await fingerprint(db, company)
            with pytest.raises(CustodyRejected, match="NOT_FOUND"):
                await session_responsibilities(db, company_id=company, session_id=foreign["session"])
            # Even an explicit foreign tenant predicate cannot escape FORCE RLS.
            assert await db.scalar(select(DispatchRouteExecutionPeriod.id).where(
                DispatchRouteExecutionPeriod.company_id == foreign["company"]).limit(1)) is None
        assert not app.dependency_overrides
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                     base_url="http://m04-isolated.test") as http:
            headers = await token(http, admin, state, state["receiver"])
            limited = await token(http, admin, state, state["limited"])
            other = await token(http, admin, foreign, foreign["receiver"])
            path = f'/admin/sessions/{state["session"]}/inventory-custody/vehicles/'
            for index, quantity in ((0, "83"), (1, "53")):
                reply = await http.get(path + str(state["cars"][index]), headers=headers)
                assert reply.status_code == 200, reply.text
                assert reply.json()["lines"][0]["expected_quantity"] == quantity
                assert len(reply.json()["snapshot_token"]) == 64
                assert "batch_id" not in reply.json()["lines"][0]
            assert (await http.get(path + str(state["cars"][0]))).status_code == 401
            assert (await http.get(path + str(state["cars"][0]), headers=limited)).status_code == 200
            assert (await http.get(path + str(state["cars"][1]), headers=limited)).status_code == 403
            assert (await http.get(path + str(state["cars"][0]), headers=other)).status_code == 404
            assert (await http.get(path + str(foreign["cars"][0]), headers=headers)).status_code == 404
            async with AsyncSession(admin) as db:
                await db.execute(delete(UserLocationAccess).where(
                    UserLocationAccess.company_id == company,
                    UserLocationAccess.driver_id == state["receiver"].driver_id))
                await db.commit()
            revoked = await http.get(path + str(state["cars"][0]), headers=headers)
            assert revoked.status_code == 403
            assert revoked.json()["error"]["request_id"]
        async with _runtime_session(runtime, company) as db:
            assert await fingerprint(db, company) == before
    finally:
        await runtime.dispose()
        await admin.dispose()
        await http_engine.dispose()
