"""Opt-in committed PostgreSQL specification for the frozen inbound contract.

NEVER use the shared development/production database. Requires an ALREADY
Alembic-migrated disposable database named wanasah_no_lot_contract_test on
127.0.0.1:55439. Runtime must be wanasah_app, non-superuser and non-BYPASSRLS.
Set WANASAH_NO_LOT_PG_GATE=1, WANASAH_NO_LOT_PG_URL and
WANASAH_NO_LOT_PG_ADMIN_URL explicitly. The admin URL must name that SAME
database/server and a distinct migration/fixture role.

Tests insert NEW synthetic companies/identities only and make real commits.
They run no DDL, migrations, create_all, schema cloning, or destructive cleanup.
Fixtures are retained in that disposable database for independent inspection.
No engine, costing, idempotency, authorization or RLS boundary is mocked.
The two concurrency/failure tests wrap the real posting call solely to pause it
or inject a failure at the transaction boundary.

After provisioning the disposable PostgreSQL server and its migration/runtime
roles, migrate it with this checkout's normal Alembic path, then run:
python -B -m pytest -p no:cacheprovider -q tests/test_inbound_no_lot_frozen_postgres.py
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
import os
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tests import test_inbound_no_lot_frozen_contract as contract
from tests.canonical_actor_fixtures import seed_company_owner_fixture, seed_ordinary_backoffice_fixture
from api.warehouse import inbound, ledger, live_stock, stocktake
from context import tenant_context
from domains.live_stock_projection.service import rebuild_live_stock_company
from domains.suppliers.models import Supplier
from models import (Company, InventoryBalance, InventoryCostEvent, InventoryCostLayer,
                    InventoryCostState, InventoryLocation,
                    InventoryMovement, OperationIdempotency, Permission, Product,
                    ProductBatch, ProductLocation, ProductVariant, Role, UOM,
                    UserLocationAccess, UserRole, role_permissions, utc_now)
from schemas import InventoryCostPolicyUpdateRequest, UpgradedInboundRequest

pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_NO_LOT_PG_GATE") != "1",
                       reason="Explicit migrated disposable no-lot PostgreSQL database only"),
    pytest.mark.asyncio(loop_scope="function"),
]


def checked_urls():
    urls = [make_url(os.environ[name]) for name in ("WANASAH_NO_LOT_PG_URL", "WANASAH_NO_LOT_PG_ADMIN_URL")]
    for url in urls:
        if (url.host != "127.0.0.1" or url.port != 55439
                or url.database != "wanasah_no_lot_contract_test"
                or url.drivername != "postgresql+asyncpg"):
            raise RuntimeError("Refusing any database outside the disposable no-lot gate target")
    if urls[0].username != "wanasah_app" or urls[1].username == urls[0].username:
        raise RuntimeError("Require distinct restricted runtime and migration fixture roles")
    return urls


class PostgresGate:
    def __init__(self, runtime_engine, admin_engine, method):
        self.runtime_engine, self.admin_engine, self.method = runtime_engine, admin_engine, method
        self.tenants = []

    @asynccontextmanager
    async def session(self, party=0):
        tenant = self.tenants[party]
        token = tenant_context.set(tenant.company_id)
        try:
            async with self.runtime_engine.connect() as connection:
                db = AsyncSession(bind=connection, expire_on_commit=False)
                try:
                    await db.execute(text("SELECT set_config('app.current_tenant',:tenant,false)"), {"tenant": str(tenant.company_id)})
                    await db.execute(text("SET statement_timeout='15000ms'"))
                    yield db
                finally:
                    await db.close()
        finally:
            tenant_context.reset(token)

    def request(self, *, party=0, request_id=None, lot=None, quantity="10", cost="2", production=None, expiry=None):
        tenant = self.tenants[party]
        resolved_request_id = request_id or uuid4()
        return UpgradedInboundRequest(
            request_id=resolved_request_id, supplier_id=tenant.supplier_id,
            location_id=tenant.location_id, reference_id=f"NOLOT-{resolved_request_id.hex}",
            items=[dict(
                product_variant_id=tenant.variant_id, uom_id=tenant.uom_id,
                quantity=quantity, unit_cost=cost, batch_number=lot,
                production_date=production, expiry_date=expiry)])

    async def post(self, db, payload, *, party=0, identity=None):
        tenant = self.tenants[party]
        actor = identity or tenant.owner
        return await inbound.warehouse_inbound(payload, db, actor.access(db), actor.operational_driver)

    async def snapshot(self, *, party=0):
        tenant = self.tenants[party]
        async with self.session(party) as db:
            counts = {}
            for model in (ProductBatch, InventoryMovement, InventoryBalance, InventoryCostEvent,
                          InventoryCostLayer, OperationIdempotency):
                counts[model.__tablename__] = int(await db.scalar(select(func.count()).select_from(model).where(model.company_id == tenant.company_id)))
            counts["quantity"] = Decimal(await db.scalar(select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0)).where(
                InventoryBalance.company_id == tenant.company_id)))
            state = await db.scalar(select(InventoryCostState).where(InventoryCostState.company_id == tenant.company_id))
            counts["value"] = Decimal(state.inventory_value) if state else Decimal("0")
            counts["batches"] = [(row.id, row.batch_number) for row in (await db.scalars(select(ProductBatch).where(
                ProductBatch.company_id == tenant.company_id).order_by(ProductBatch.id))).all()]
            return counts


@pytest_asyncio.fixture(params=["FIFO", "MOVING_AVERAGE"], loop_scope="function")
async def pg(request):
    runtime_url, admin_url = checked_urls()
    runtime_engine = create_async_engine(runtime_url, poolclass=NullPool)
    admin_engine = create_async_engine(admin_url, poolclass=NullPool)
    gate = PostgresGate(runtime_engine, admin_engine, request.param)
    try:
        async with runtime_engine.connect() as connection:
            identity = (await connection.execute(text(
                "SELECT current_database(), current_user, inet_server_port(), r.rolsuper, r.rolbypassrls "
                "FROM pg_roles r WHERE r.rolname=current_user"))).one()
            assert tuple(identity) == ("wanasah_no_lot_contract_test", "wanasah_app", 55439, False, False)
            for name in ("product_batches", "inventory_balances", "inventory_movements", "operation_idempotency"):
                flags = (await connection.execute(text(
                    "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=to_regclass(:name)"), {"name": name})).one()
                assert tuple(flags) == (True, True), f"Missing FORCE RLS on {name}"
        config = AlembicConfig(str(Path(__file__).parents[1] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
        expected_heads = set(ScriptDirectory.from_config(config).get_heads())
        async with AsyncSession(admin_engine, expire_on_commit=False) as seed:
            assert set((await seed.execute(text("SELECT version_num FROM alembic_version"))).scalars()) == expected_heads
            uom = await seed.scalar(select(UOM).where(UOM.code == "EACH"))
            if uom is None:
                uom = UOM(code="EACH", name="No-lot synthetic each")
                seed.add(uom)
                await seed.flush()
            for _index in range(2):
                company = Company(name="No-lot synthetic contract", company_code="NLC-" + uuid4().hex, timezone="Asia/Amman")
                seed.add(company)
                await seed.flush()
                await seed.execute(text("SELECT set_config('app.current_tenant',:tenant,true)"), {"tenant": str(company.id)})
                owner = await seed_company_owner_fixture(seed, company.id, password="NoLotSyntheticFixture123")
                ordinary = await seed_ordinary_backoffice_fixture(seed, company.id)
                product = Product(company_id=company.id, code="P", name="No-lot synthetic product")
                seed.add(product)
                await seed.flush()
                variant = ProductVariant(company_id=company.id, product_id=product.id, name="No-lot SKU", sku="P",
                    base_uom_id=uom.id, quantity_scale=6, quantity_step=Decimal("0.000001"),
                    lot_control_mode="OPTIONAL", expiry_control_mode="OPTIONAL", lifecycle_status="ACTIVE", published_at=utc_now())
                locations = [InventoryLocation(company_id=company.id, code=f"WH-{i}", name=f"Synthetic warehouse {i}", location_type="WAREHOUSE") for i in range(2)]
                supplier = Supplier(company_id=company.id, name="No-lot synthetic supplier", created_by=owner.driver_id, updated_by=owner.driver_id)
                seed.add_all([variant, supplier, *locations])
                await seed.flush()
                seed.add(ProductLocation(company_id=company.id, location_id=locations[0].id,
                    product_variant_id=variant.id, created_by=owner.driver_id,
                    operational_flags={"inbound_enabled": True, "outbound_enabled": True}))
                await seed.flush()
                await rebuild_live_stock_company(seed, company_id=company.id)
                await seed.commit()
                gate.tenants.append(NS(company_id=company.id, owner=owner, ordinary=ordinary,
                    variant_id=variant.id, uom_id=uom.id, location_id=locations[0].id,
                    other_location_id=locations[1].id, supplier_id=supplier.id))
        for party in range(2):
            async with gate.session(party) as db:
                owner = gate.tenants[party].owner
                await inbound.update_warehouse_costing_policy(InventoryCostPolicyUpdateRequest(
                    request_id=uuid4(), method=request.param, expected_version=0), db, owner.access(db), owner.operational_driver)
        yield gate
    finally:
        await runtime_engine.dispose()
        await admin_engine.dispose()


async def test_committed_replay_costs_and_changed_payload(pg):
    payload = pg.request(quantity="2.500001", cost="0.123456")
    async with pg.session() as db:
        response = await pg.post(db, payload)
    before = await pg.snapshot()
    async with pg.session() as db:
        assert await pg.post(db, payload) == response
    assert await pg.snapshot() == before
    assert before["product_batches"] == before["inventory_movements"] == before["inventory_cost_events"] == 1
    assert before["quantity"] == Decimal("2.500001")
    assert before["value"] == Decimal("0.308640")
    assert before["inventory_cost_layers"] == (1 if pg.method == "FIFO" else 0)
    async with pg.session() as db:
        changed = payload.model_copy(update={"items": [payload.items[0].model_copy(update={"unit_cost": Decimal("1")})]})
        with pytest.raises(HTTPException) as caught:
            await pg.post(db, changed)
        assert caught.value.status_code == 409
        contract.assert_no_leak(caught.value.detail)
    assert await pg.snapshot() == before


async def test_same_request_inflight_conflict_then_committed_replay(pg):
    payload = pg.request()
    reached, release = asyncio.Event(), asyncio.Event()
    real_post = inbound.apply_inventory_movements_batch
    async with pg.session() as first, pg.session() as second:
        await second.execute(text("SET lock_timeout='500ms'"))

        async def pause(db, **kwargs):
            result = await real_post(db, **kwargs)
            if db is first:
                reached.set()
                await release.wait()
            return result

        first_task = None
        with patch.object(inbound, "apply_inventory_movements_batch", side_effect=pause):
            try:
                first_task = asyncio.create_task(pg.post(first, payload))
                await asyncio.wait_for(reached.wait(), 10)
                with pytest.raises(HTTPException) as caught:
                    await asyncio.wait_for(pg.post(second, payload), 5)
                assert caught.value.status_code == 409
                assert caught.value.detail["code"] == "INBOUND_CONCURRENT_CONFLICT"
                contract.assert_no_leak(caught.value.detail)
            finally:
                release.set()
                if first_task is not None:
                    await asyncio.wait_for(first_task, 10)
    async with pg.session() as db:
        assert await pg.post(db, payload) == {"message": "INBOUND_POSTED"}
    snapshot = await pg.snapshot()
    assert snapshot["inventory_movements"] == snapshot["inventory_cost_events"] == snapshot["product_batches"] == 1


async def test_concurrent_distinct_receipts_identical_dates_keep_separate_batches(pg):
    left, right = pg.request(), pg.request(quantity="5", cost="3")
    async with pg.session() as a, pg.session() as b:
        await asyncio.wait_for(asyncio.gather(pg.post(a, left), pg.post(b, right)), 20)
    snapshot = await pg.snapshot()
    assert snapshot["product_batches"] == snapshot["inventory_movements"] == snapshot["inventory_cost_events"] == 2
    assert len({number for _identity, number in snapshot["batches"]}) == 2
    assert snapshot["quantity"] == Decimal("15") and snapshot["value"] == Decimal("35")


async def test_failure_before_commit_rolls_back_stock_cost_and_generated_identity(pg):
    payload = pg.request()
    before = await pg.snapshot()
    async with pg.session() as db:
        with patch.object(inbound, "complete_idempotent_operation", side_effect=RuntimeError("Synthetic pre-commit failure")):
            with pytest.raises(HTTPException) as caught:
                await pg.post(db, payload)
            assert caught.value.status_code == 500
            contract.assert_no_leak(caught.value.detail)
    assert await pg.snapshot() == before
    async with pg.session() as db:
        await pg.post(db, payload)
    assert (await pg.snapshot())["inventory_cost_events"] == 1


@pytest.mark.parametrize("before,after", [(None, date(2026, 1, 1)), (date(2026, 1, 1), None)])
async def test_real_lot_null_production_metadata_is_exact_and_immutable(pg, before, after):
    async with pg.session() as db:
        await pg.post(db, pg.request(lot=contract.REAL_LOT, production=before))
    original = await pg.snapshot()
    async with pg.session() as db:
        with pytest.raises(HTTPException) as caught:
            await pg.post(db, pg.request(lot=contract.REAL_LOT, production=after))
        assert caught.value.detail["code"] == "INBOUND_BATCH_METADATA_CONFLICT"
    assert await pg.snapshot() == original


async def test_cross_company_request_and_rls_boundaries(pg):
    request_id = uuid4()
    for party in range(2):
        async with pg.session(party) as db:
            await pg.post(db, pg.request(party=party, request_id=request_id), party=party)
    left, right = await pg.snapshot(), await pg.snapshot(party=1)
    assert left["product_batches"] == right["product_batches"] == 1
    assert left["batches"][0][0] != right["batches"][0][0]
    async with pg.session(1) as db:
        # Deliberately omit company predicate: FORCE RLS must still protect it.
        assert await db.scalar(select(ProductBatch).where(ProductBatch.id == left["batches"][0][0])) is None


async def test_real_non_owner_grants_and_product_location_denial(pg):
    tenant = pg.tenants[0]
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(text("SELECT set_config('app.current_tenant',:tenant,true)"), {"tenant": str(tenant.company_id)})
        for code, location_scoped in (("inbound.create", True), ("supplier.read", False)):
            permission = await seed.scalar(select(Permission).where(Permission.code == code))
            assert permission is not None, "Migrated permission catalog is incomplete"
            role = Role(company_id=tenant.company_id, name="No-lot synthetic " + code)
            seed.add(role)
            await seed.flush()
            await seed.execute(role_permissions.insert().values(company_id=tenant.company_id, role_id=role.id, permission_id=permission.id))
            assignment = dict(company_id=tenant.company_id, role_id=role.id, driver_id=tenant.ordinary.driver_id)
            seed.add(UserLocationAccess(**assignment, location_id=tenant.location_id) if location_scoped else UserRole(**assignment))
        await seed.commit()
    async with pg.session() as db:
        await pg.post(db, pg.request(lot=contract.REAL_LOT), identity=tenant.ordinary)
    other = pg.request(lot="OTHER").model_copy(update={"location_id": tenant.other_location_id})
    async with pg.session() as db:
        with pytest.raises(HTTPException) as caught:
            await pg.post(db, other, identity=tenant.ordinary)
        assert caught.value.status_code == 403
    async with AsyncSession(pg.admin_engine) as seed:
        await seed.execute(text("SELECT set_config('app.current_tenant',:tenant,true)"), {"tenant": str(tenant.company_id)})
        await seed.execute(ProductLocation.__table__.update().where(ProductLocation.company_id == tenant.company_id).values(
            operational_flags={"inbound_enabled": False, "outbound_enabled": True}))
        await seed.commit()
    async with pg.session() as db:
        with pytest.raises(HTTPException) as caught:
            await pg.post(db, pg.request(lot="ANOTHER"), identity=tenant.ordinary)
        assert caught.value.detail["code"] == "PRODUCT_LOCATION_INBOUND_DISABLED"
    assert (await pg.snapshot())["inventory_movements"] == 1


async def test_database_rejects_null_balance_batch_id(pg):
    tenant = pg.tenants[0]
    async with pg.session() as db:
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await db.execute(InventoryBalance.__table__.insert().values(company_id=tenant.company_id,
                    location_id=tenant.location_id, product_variant_id=tenant.variant_id,
                    batch_id=None, stock_status="AVAILABLE", on_hand_quantity=Decimal("1"), reserved_quantity=Decimal("0")))


async def test_committed_anonymous_operator_reads_have_null_business_lot(pg):
    async with pg.session() as db:
        await pg.post(db, pg.request())
    tenant = pg.tenants[0]
    snapshot = await pg.snapshot()
    batch_id = snapshot["batches"][0][0]
    async with pg.session() as db:
        access = tenant.owner.access(db)
        responses = [
            await live_stock.get_warehouse_inventory_batches(tenant.variant_id, tenant.location_id, None, 100, db, access),
            await live_stock.get_batch_stock_sources(batch_id, db, access),
            await ledger.get_warehouse_ledger_cursor(tenant.location_id, None, 50, None, None, None, db, access),
            await stocktake.list_stocktake_cycle_batches(tenant.location_id, tenant.variant_id, None, None, 50, db, access),
        ]
        for response in responses:
            contract.assert_business_lots(response, None)
