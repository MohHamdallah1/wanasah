"""Disposable PostgreSQL 16 fixture for the real Live Stock browser gate.

This helper creates only synthetic catalog/auth/location setup rows directly.
All physical stock and purchase-cost evidence is created by the canonical
Supplier inbound command. The post-seed stock change uses the canonical
inventory movement engine. It refuses any database except the dedicated CI
database/port and never touches a developer or production database.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api.warehouse import inbound
from context import tenant_context
from domains.identity.models import CompanyPrincipal
from domains.live_stock_projection.service import rebuild_live_stock_company
from domains.suppliers.models import Supplier
from models import (
    Company,
    InventoryBalance,
    InventoryCostEvent,
    InventoryCostState,
    InventoryLocation,
    Permission,
    Product,
    ProductBatch,
    ProductLocation,
    ProductVariant,
    Role,
    UOM,
    UserLocationAccess,
    role_permissions,
    utc_now,
)
from schemas import InventoryCostPolicyUpdateRequest, UpgradedInboundRequest
from services import apply_inventory_movements_batch
from tests.canonical_actor_fixtures import (
    seed_company_owner_fixture,
    seed_ordinary_backoffice_fixture,
)

# Expected values are deliberately fixed before any browser assertion executes.
EXPECTED_INBOUND = Decimal("800")
EXPECTED_MOVE = Decimal("125")
EXPECTED_REMAINING = EXPECTED_INBOUND - EXPECTED_MOVE
EXPECTED_COST = Decimal("1.250000")
EXPECTED_VALUE = EXPECTED_INBOUND * EXPECTED_COST
FOREIGN_QUANTITY = Decimal("50")
FOREIGN_COST = Decimal("9.750000")
LOT_A = "RB-LOT-800"
LOT_B = "RB-FOREIGN-LOT"

DB_NAME = "wanasah_no_lot_contract_test"
DB_HOST = "127.0.0.1"
DB_PORT = 55439
RUNTIME_USER = "wanasah_app"
STATE_PATH = Path(os.environ.get("WANASAH_REAL_BROWSER_STATE", "/tmp/live-stock-real-browser-state.json"))


def _checked_urls():
    if os.getenv("WANASAH_REAL_BROWSER_GATE") != "1":
        raise RuntimeError("WANASAH_REAL_BROWSER_GATE=1 is required")
    runtime = make_url(os.environ["WANASAH_REAL_BROWSER_PG_URL"])
    admin = make_url(os.environ["WANASAH_REAL_BROWSER_PG_ADMIN_URL"])
    for url in (runtime, admin):
        if (
            url.drivername != "postgresql+asyncpg"
            or url.host != DB_HOST
            or url.port != DB_PORT
            or url.database != DB_NAME
        ):
            raise RuntimeError("Refusing database outside the disposable real-browser gate")
    if runtime.username != RUNTIME_USER or admin.username == RUNTIME_USER:
        raise RuntimeError("Real-browser gate requires a restricted runtime and distinct admin role")
    return runtime, admin


@asynccontextmanager
async def _runtime_session(engine, company_id: int):
    token = tenant_context.set(company_id)
    try:
        async with engine.connect() as connection:
            db = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                await db.execute(
                    text("SELECT set_config('app.current_tenant', :tenant, false)"),
                    {"tenant": str(company_id)},
                )
                await db.execute(text("SET statement_timeout='20000ms'"))
                yield db
            finally:
                await db.close()
    finally:
        tenant_context.reset(token)


async def _grant_location_reader(db, *, company_id: int, driver_id: int, location_id: int):
    role = Role(company_id=company_id, name="Real browser restricted reader " + uuid4().hex)
    db.add(role)
    await db.flush()
    for code in ("inventory.read", "location.read"):
        permission = await db.scalar(select(Permission).where(Permission.code == code))
        assert permission is not None, f"Missing migrated permission: {code}"
        await db.execute(
            role_permissions.insert().values(
                company_id=company_id,
                role_id=role.id,
                permission_id=permission.id,
            )
        )
    db.add(
        UserLocationAccess(
            company_id=company_id,
            driver_id=driver_id,
            role_id=role.id,
            location_id=location_id,
        )
    )
    await db.flush()


async def _verify_runtime_identity(runtime_engine):
    async with runtime_engine.connect() as connection:
        identity = (
            await connection.execute(
                text(
                    "SELECT current_database(), current_user, inet_server_port(), "
                    "current_setting('server_version_num')::int, r.rolsuper, r.rolbypassrls "
                    "FROM pg_roles r WHERE r.rolname=current_user"
                )
            )
        ).one()
        assert identity[0:3] == (DB_NAME, RUNTIME_USER, DB_PORT)
        assert 160000 <= int(identity[3]) < 170000
        assert tuple(identity[4:]) == (False, False)
        for table_name in (
            "product_batches",
            "inventory_balances",
            "inventory_movements",
            "inventory_cost_events",
            "inventory_cost_states",
        ):
            flags = (
                await connection.execute(
                    text(
                        "SELECT relrowsecurity, relforcerowsecurity "
                        "FROM pg_class WHERE oid=to_regclass(:name)"
                    ),
                    {"name": table_name},
                )
            ).one()
            assert tuple(flags) == (True, True), table_name


async def _verify_alembic_head(admin_engine):
    config = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    expected = set(ScriptDirectory.from_config(config).get_heads())
    async with AsyncSession(admin_engine, expire_on_commit=False) as db:
        actual = set((await db.execute(text("SELECT version_num FROM alembic_version"))).scalars())
    assert actual == expected, (actual, expected)


async def _post_inbound(runtime_engine, tenant, *, quantity: Decimal, cost: Decimal, lot: str, reference: str):
    async with _runtime_session(runtime_engine, tenant.company_id) as db:
        request = UpgradedInboundRequest(
            request_id=uuid4(),
            supplier_id=tenant.supplier_id,
            location_id=tenant.location_id,
            reference_id=reference,
            items=[
                {
                    "product_variant_id": tenant.variant_id,
                    "uom_id": tenant.uom_id,
                    "quantity": quantity,
                    "unit_cost": cost,
                    "batch_number": lot,
                    "production_date": date(2026, 10, 1),
                    "expiry_date": date(2027, 10, 1),
                }
            ],
        )
        result = await inbound.warehouse_inbound(
            request,
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )
        assert result == {"message": "INBOUND_POSTED"}


async def _assert_financial_truth(
    runtime_engine,
    *,
    company_id: int,
    variant_id: int,
    warehouse_id: int,
    expected_warehouse: Decimal,
    expected_total: Decimal,
    expected_cost: Decimal,
):
    async with _runtime_session(runtime_engine, company_id) as db:
        warehouse_qty = Decimal(
            await db.scalar(
                select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0)).where(
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.product_variant_id == variant_id,
                    InventoryBalance.location_id == warehouse_id,
                )
            )
        )
        total_qty = Decimal(
            await db.scalar(
                select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0)).where(
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.product_variant_id == variant_id,
                )
            )
        )
        state = await db.scalar(
            select(InventoryCostState).where(
                InventoryCostState.company_id == company_id,
                InventoryCostState.product_variant_id == variant_id,
            )
        )
        events = (
            await db.scalars(
                select(InventoryCostEvent).where(
                    InventoryCostEvent.company_id == company_id,
                    InventoryCostEvent.product_variant_id == variant_id,
                )
            )
        ).all()
        assert warehouse_qty == expected_warehouse
        assert total_qty == expected_total
        assert state is not None
        assert Decimal(state.quantity) == expected_total
        assert Decimal(state.inventory_value) == expected_total * expected_cost
        assert Decimal(state.average_unit_cost) == expected_cost
        assert len(events) == 1
        assert Decimal(events[0].total_cost) == expected_total * expected_cost


async def seed():
    runtime_url, admin_url = _checked_urls()
    runtime_engine = create_async_engine(runtime_url, poolclass=NullPool)
    admin_engine = create_async_engine(admin_url, poolclass=NullPool)
    try:
        await _verify_runtime_identity(runtime_engine)
        await _verify_alembic_head(admin_engine)

        async with AsyncSession(admin_engine, expire_on_commit=False) as db:
            each = await db.scalar(select(UOM).where(UOM.code == "EACH"))
            if each is None:
                each = UOM(code="EACH", name="Each")
                db.add(each)
                await db.flush()

            company_a = Company(
                name="Real Browser Company A",
                company_code="RB-A-" + uuid4().hex[:12],
                currency_code="JOD",
                timezone="Asia/Amman",
            )
            company_b = Company(
                name="Real Browser Company B",
                company_code="RB-B-" + uuid4().hex[:12],
                currency_code="JOD",
                timezone="Asia/Amman",
            )
            db.add_all([company_a, company_b])
            await db.flush()

            await db.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(company_a.id)},
            )
            owner_a = await seed_company_owner_fixture(
                db, company_a.id, password="RealBrowserOwnerA123!"
            )
            reader_a = await seed_ordinary_backoffice_fixture(
                db, company_a.id, password="RealBrowserReaderA123!"
            )
            a1 = InventoryLocation(
                company_id=company_a.id,
                code="RB-A1",
                name="Real Browser Warehouse A1",
                location_type="WAREHOUSE",
                is_active=True,
                is_system_managed=False,
            )
            a2 = InventoryLocation(
                company_id=company_a.id,
                code="RB-A2",
                name="Real Browser Warehouse A2",
                location_type="WAREHOUSE",
                is_active=True,
                is_system_managed=False,
            )
            db.add_all([a1, a2])
            await db.flush()
            product_a = Product(
                company_id=company_a.id,
                code="RB-P-A",
                name="Real Browser Product A",
            )
            db.add(product_a)
            await db.flush()
            variant_a = ProductVariant(
                company_id=company_a.id,
                product_id=product_a.id,
                name="Real Browser Product A",
                sku="RB-SKU-A",
                base_uom_id=each.id,
                quantity_scale=6,
                quantity_step=Decimal("0.000001"),
                lot_control_mode="REQUIRED",
                expiry_control_mode="OPTIONAL",
                lifecycle_status="ACTIVE",
                operational_hold="NONE",
                published_at=utc_now(),
            )
            supplier_a = Supplier(
                company_id=company_a.id,
                name="Real Browser Supplier A",
                code="RB-SUP-A",
                created_by=owner_a.driver_id,
                updated_by=owner_a.driver_id,
            )
            db.add_all([variant_a, supplier_a])
            await db.flush()
            db.add(
                ProductLocation(
                    company_id=company_a.id,
                    location_id=a1.id,
                    product_variant_id=variant_a.id,
                    created_by=owner_a.driver_id,
                    operational_flags={"inbound_enabled": True, "outbound_enabled": True},
                )
            )
            await _grant_location_reader(
                db,
                company_id=company_a.id,
                driver_id=reader_a.driver_id,
                location_id=a1.id,
            )
            # A2 starts readable only so the browser can warm genuine scoped data.
            # The revoke command removes this exact grant while preserving the
            # same principal/token and the A1 grant.
            await _grant_location_reader(
                db,
                company_id=company_a.id,
                driver_id=reader_a.driver_id,
                location_id=a2.id,
            )
            await rebuild_live_stock_company(db, company_id=company_a.id)
            await db.flush()

            await db.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(company_b.id)},
            )
            owner_b = await seed_company_owner_fixture(
                db, company_b.id, password="RealBrowserOwnerB123!"
            )
            b1 = InventoryLocation(
                company_id=company_b.id,
                code="RB-B1",
                name="Real Browser Warehouse B1",
                location_type="WAREHOUSE",
                is_active=True,
                is_system_managed=False,
            )
            db.add(b1)
            await db.flush()
            product_b = Product(
                company_id=company_b.id,
                code="RB-P-B",
                name="Foreign Browser Product B",
            )
            db.add(product_b)
            await db.flush()
            variant_b = ProductVariant(
                company_id=company_b.id,
                product_id=product_b.id,
                name="Foreign Browser Product B",
                sku="RB-SKU-B",
                base_uom_id=each.id,
                quantity_scale=6,
                quantity_step=Decimal("0.000001"),
                lot_control_mode="REQUIRED",
                expiry_control_mode="OPTIONAL",
                lifecycle_status="ACTIVE",
                operational_hold="NONE",
                published_at=utc_now(),
            )
            supplier_b = Supplier(
                company_id=company_b.id,
                name="Real Browser Supplier B",
                code="RB-SUP-B",
                created_by=owner_b.driver_id,
                updated_by=owner_b.driver_id,
            )
            db.add_all([variant_b, supplier_b])
            await db.flush()
            db.add(
                ProductLocation(
                    company_id=company_b.id,
                    location_id=b1.id,
                    product_variant_id=variant_b.id,
                    created_by=owner_b.driver_id,
                    operational_flags={"inbound_enabled": True, "outbound_enabled": True},
                )
            )
            await rebuild_live_stock_company(db, company_id=company_b.id)
            await db.commit()

            owner_a_username = await db.scalar(
                select(CompanyPrincipal.username).where(
                    CompanyPrincipal.id == owner_a.context.principal_id
                )
            )
            reader_a_username = await db.scalar(
                select(CompanyPrincipal.username).where(
                    CompanyPrincipal.id == reader_a.context.principal_id
                )
            )
            owner_b_username = await db.scalar(
                select(CompanyPrincipal.username).where(
                    CompanyPrincipal.id == owner_b.context.principal_id
                )
            )
            ids = NS(
                company_a=company_a.id,
                company_b=company_b.id,
                company_a_code=company_a.company_code,
                company_b_code=company_b.company_code,
                owner_a=owner_a,
                owner_b=owner_b,
                reader_a=reader_a,
                owner_a_username=str(owner_a_username),
                reader_a_username=str(reader_a_username),
                owner_b_username=str(owner_b_username),
                a1=a1.id,
                a2=a2.id,
                b1=b1.id,
                variant_a=variant_a.id,
                variant_b=variant_b.id,
                uom=each.id,
                supplier_a=supplier_a.id,
                supplier_b=supplier_b.id,
            )

        for company_id, owner in (
            (ids.company_a, ids.owner_a),
            (ids.company_b, ids.owner_b),
        ):
            async with _runtime_session(runtime_engine, company_id) as db:
                await inbound.update_warehouse_costing_policy(
                    InventoryCostPolicyUpdateRequest(
                        request_id=uuid4(),
                        method="FIFO",
                        expected_version=0,
                    ),
                    db,
                    owner.access(db),
                    owner.operational_driver,
                )

        tenant_a = NS(
            company_id=ids.company_a,
            supplier_id=ids.supplier_a,
            location_id=ids.a1,
            variant_id=ids.variant_a,
            uom_id=ids.uom,
            owner=ids.owner_a,
        )
        tenant_b = NS(
            company_id=ids.company_b,
            supplier_id=ids.supplier_b,
            location_id=ids.b1,
            variant_id=ids.variant_b,
            uom_id=ids.uom,
            owner=ids.owner_b,
        )
        await _post_inbound(
            runtime_engine,
            tenant_a,
            quantity=EXPECTED_INBOUND,
            cost=EXPECTED_COST,
            lot=LOT_A,
            reference="RB-REC-800",
        )
        await _post_inbound(
            runtime_engine,
            tenant_b,
            quantity=FOREIGN_QUANTITY,
            cost=FOREIGN_COST,
            lot=LOT_B,
            reference="RB-REC-FOREIGN",
        )

        async with _runtime_session(runtime_engine, ids.company_a) as db:
            batch_a = await db.scalar(
                select(ProductBatch).where(
                    ProductBatch.company_id == ids.company_a,
                    ProductBatch.product_variant_id == ids.variant_a,
                    ProductBatch.batch_number == LOT_A,
                )
            )
            assert batch_a is not None
        async with _runtime_session(runtime_engine, ids.company_b) as db:
            batch_b = await db.scalar(
                select(ProductBatch).where(
                    ProductBatch.company_id == ids.company_b,
                    ProductBatch.product_variant_id == ids.variant_b,
                    ProductBatch.batch_number == LOT_B,
                )
            )
            assert batch_b is not None

        await _assert_financial_truth(
            runtime_engine,
            company_id=ids.company_a,
            variant_id=ids.variant_a,
            warehouse_id=ids.a1,
            expected_warehouse=EXPECTED_INBOUND,
            expected_total=EXPECTED_INBOUND,
            expected_cost=EXPECTED_COST,
        )
        await _assert_financial_truth(
            runtime_engine,
            company_id=ids.company_b,
            variant_id=ids.variant_b,
            warehouse_id=ids.b1,
            expected_warehouse=FOREIGN_QUANTITY,
            expected_total=FOREIGN_QUANTITY,
            expected_cost=FOREIGN_COST,
        )

        state = {
            "companyA": {
                "id": ids.company_a,
                "code": ids.company_a_code,
                "ownerUsername": ids.owner_a_username,
                "ownerPassword": "RealBrowserOwnerA123!",
                "readerUsername": ids.reader_a_username,
                "readerPassword": "RealBrowserReaderA123!",
                "warehouseA1": ids.a1,
                "warehouseA2": ids.a2,
                "variantId": ids.variant_a,
                "batchId": int(batch_a.id),
                "productName": "Real Browser Product A",
                "lot": LOT_A,
                "ownerDriverId": ids.owner_a.driver_id,
                "readerDriverId": ids.reader_a.driver_id,
                "expectedInbound": str(EXPECTED_INBOUND),
                "expectedMove": str(EXPECTED_MOVE),
                "expectedRemaining": str(EXPECTED_REMAINING),
                "expectedCost": str(EXPECTED_COST),
                "expectedValue": str(EXPECTED_VALUE),
            },
            "companyB": {
                "id": ids.company_b,
                "code": ids.company_b_code,
                "ownerUsername": ids.owner_b_username,
                "ownerPassword": "RealBrowserOwnerB123!",
                "warehouse": ids.b1,
                "variantId": ids.variant_b,
                "batchId": int(batch_b.id),
                "productName": "Foreign Browser Product B",
                "lot": LOT_B,
                "expectedQuantity": str(FOREIGN_QUANTITY),
                "expectedCost": str(FOREIGN_COST),
            },
        }
        STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        print("REAL_BROWSER_SEED=PASS " + json.dumps(state, sort_keys=True), flush=True)
    finally:
        await runtime_engine.dispose()
        await admin_engine.dispose()


async def move():
    runtime_url, admin_url = _checked_urls()
    runtime_engine = create_async_engine(runtime_url, poolclass=NullPool)
    admin_engine = create_async_engine(admin_url, poolclass=NullPool)
    try:
        await _verify_runtime_identity(runtime_engine)
        await _verify_alembic_head(admin_engine)
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        company = state["companyA"]
        assert Decimal(company["expectedInbound"]) == EXPECTED_INBOUND
        assert Decimal(company["expectedMove"]) == EXPECTED_MOVE
        assert Decimal(company["expectedRemaining"]) == EXPECTED_REMAINING
        assert Decimal(company["expectedCost"]) == EXPECTED_COST

        async with _runtime_session(runtime_engine, int(company["id"])) as db:
            rows = await apply_inventory_movements_batch(
                db,
                company_id=int(company["id"]),
                performed_by=int(company["ownerDriverId"]),
                movements=[
                    {
                        "product_variant_id": int(company["variantId"]),
                        "batch_id": int(company["batchId"]),
                        "quantity": EXPECTED_MOVE,
                        "movement_kind": "PHYSICAL",
                        "reservation_action": None,
                        "source_location_id": int(company["warehouseA1"]),
                        "destination_location_id": int(company["warehouseA2"]),
                        "source_stock_status": "AVAILABLE",
                        "destination_stock_status": "AVAILABLE",
                        "reference_type": "REAL_BROWSER_CANONICAL_MOVE",
                        "reference_id": "RB-MOVE-125",
                        "idempotency_key": "RB-MOVE-125",
                    }
                ],
            )
            assert len(rows) == 1
            await db.commit()

        await _assert_financial_truth(
            runtime_engine,
            company_id=int(company["id"]),
            variant_id=int(company["variantId"]),
            warehouse_id=int(company["warehouseA1"]),
            expected_warehouse=EXPECTED_REMAINING,
            expected_total=EXPECTED_INBOUND,
            expected_cost=EXPECTED_COST,
        )
        async with _runtime_session(runtime_engine, int(company["id"])) as db:
            destination = Decimal(
                await db.scalar(
                    select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0)).where(
                        InventoryBalance.company_id == int(company["id"]),
                        InventoryBalance.product_variant_id == int(company["variantId"]),
                        InventoryBalance.location_id == int(company["warehouseA2"]),
                    )
                )
            )
            assert destination == EXPECTED_MOVE
        print(
            "REAL_BROWSER_MOVE=PASS "
            + json.dumps(
                {
                    "warehouseA1": str(EXPECTED_REMAINING),
                    "warehouseA2": str(EXPECTED_MOVE),
                    "companyTotal": str(EXPECTED_INBOUND),
                    "purchaseCost": str(EXPECTED_COST),
                },
                sort_keys=True,
            ),
            flush=True,
        )
    finally:
        await runtime_engine.dispose()
        await admin_engine.dispose()


async def revoke_a2():
    runtime_url, admin_url = _checked_urls()
    runtime_engine = create_async_engine(runtime_url, poolclass=NullPool)
    admin_engine = create_async_engine(admin_url, poolclass=NullPool)
    try:
        await _verify_runtime_identity(runtime_engine)
        await _verify_alembic_head(admin_engine)
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        company = state["companyA"]
        async with _runtime_session(runtime_engine, int(company["id"])) as db:
            result = await db.execute(
                delete(UserLocationAccess).where(
                    UserLocationAccess.company_id == int(company["id"]),
                    UserLocationAccess.driver_id == int(company["readerDriverId"]),
                    UserLocationAccess.location_id == int(company["warehouseA2"]),
                )
            )
            assert int(result.rowcount or 0) >= 1
            await db.commit()
        async with _runtime_session(runtime_engine, int(company["id"])) as db:
            remaining_a2 = await db.scalar(
                select(func.count()).select_from(UserLocationAccess).where(
                    UserLocationAccess.company_id == int(company["id"]),
                    UserLocationAccess.driver_id == int(company["readerDriverId"]),
                    UserLocationAccess.location_id == int(company["warehouseA2"]),
                )
            )
            remaining_a1 = await db.scalar(
                select(func.count()).select_from(UserLocationAccess).where(
                    UserLocationAccess.company_id == int(company["id"]),
                    UserLocationAccess.driver_id == int(company["readerDriverId"]),
                    UserLocationAccess.location_id == int(company["warehouseA1"]),
                )
            )
            assert int(remaining_a2 or 0) == 0
            assert int(remaining_a1 or 0) >= 1
        print("REAL_BROWSER_REVOKE_A2=PASS", flush=True)
    finally:
        await runtime_engine.dispose()
        await admin_engine.dispose()


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {"seed", "move", "revoke-a2"}:
        raise SystemExit("usage: live_stock_real_browser_support.py seed|move|revoke-a2")
    command = sys.argv[1]
    if command == "seed":
        coroutine = seed()
    elif command == "move":
        coroutine = move()
    else:
        coroutine = revoke_a2()
    asyncio.run(coroutine)


if __name__ == "__main__":
    main()
