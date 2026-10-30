"""Focused setup/mutation helper for the real Live Stock browser gate.

The seed test deliberately reuses the existing disposable PostgreSQL/inbound
fixture. It adds only the exact browser identities/scopes and canonical receipts
needed by this proof. Physical stock and purchase history are never inserted
directly.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from context import tenant_context
from domains.identity.models import CompanyPrincipal
from models import (
    Company,
    InventoryBalance,
    InventoryCostEvent,
    InventoryCostState,
    Permission,
    ProductVariant,
    Role,
    UserLocationAccess,
    role_permissions,
)
from services import apply_inventory_movements_batch
from tests.test_inbound_no_lot_frozen_postgres import checked_urls, pg

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_REAL_BROWSER_GATE") != "1",
        reason="Explicit disposable real-browser PostgreSQL gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]

# Fixed independently of browser output.
EXPECTED_INBOUND = Decimal("800")
EXPECTED_MOVE = Decimal("125")
EXPECTED_REMAINING = EXPECTED_INBOUND - EXPECTED_MOVE
EXPECTED_COST = Decimal("1.250000")
EXPECTED_VALUE = EXPECTED_INBOUND * EXPECTED_COST
FOREIGN_QUANTITY = Decimal("50")
FOREIGN_COST = Decimal("9.750000")
LOT_A = "RB-LOT-800"
LOT_B = "RB-FOREIGN-LOT"
STATE_PATH = Path(
    os.environ.get(
        "WANASAH_REAL_BROWSER_STATE",
        "/tmp/live-stock-real-browser-state.json",
    )
)


async def _grant_reader(db, *, tenant, locations: tuple[int, ...]):
    role = Role(
        company_id=tenant.company_id,
        name="Real browser scoped reader " + uuid4().hex,
    )
    db.add(role)
    await db.flush()
    for code in ("inventory.read", "location.read"):
        permission = await db.scalar(
            select(Permission).where(Permission.code == code)
        )
        assert permission is not None, f"Missing migrated permission: {code}"
        await db.execute(
            role_permissions.insert().values(
                company_id=tenant.company_id,
                role_id=role.id,
                permission_id=permission.id,
            )
        )
    for location_id in locations:
        db.add(
            UserLocationAccess(
                company_id=tenant.company_id,
                driver_id=tenant.ordinary.driver_id,
                role_id=role.id,
                location_id=location_id,
            )
        )
    await db.flush()


@pytest.mark.asyncio
async def test_seed_real_browser_fixture(pg):
    """Reuse the established canonical inbound/PostgreSQL fixture.

    The fixture already proves PostgreSQL 16, restricted runtime role, FORCE RLS,
    Alembic heads, canonical Owner/Backoffice identities, suppliers, products,
    warehouses, ProductLocation and the selected costing policy.
    """
    a, b = pg.tenants

    # Catalog labels are test-only setup, not inventory truth.
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as db:
        await db.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": str(a.company_id)},
        )
        await db.execute(
            update(ProductVariant)
            .where(
                ProductVariant.company_id == a.company_id,
                ProductVariant.id == a.variant_id,
            )
            .values(name="Real Browser Product A", sku="RB-SKU-A")
        )
        await _grant_reader(
            db,
            tenant=a,
            locations=(a.location_id, a.other_location_id),
        )

        await db.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": str(b.company_id)},
        )
        await db.execute(
            update(ProductVariant)
            .where(
                ProductVariant.company_id == b.company_id,
                ProductVariant.id == b.variant_id,
            )
            .values(name="Foreign Browser Product B", sku="RB-SKU-B")
        )
        await db.commit()

    # Canonical supplier inbound creates all stock, batch and purchase-cost truth.
    async with pg.session(0) as db:
        await pg.post(
            db,
            pg.request(
                party=0,
                lot=LOT_A,
                quantity=str(EXPECTED_INBOUND),
                cost=str(EXPECTED_COST),
            ),
            party=0,
        )
    async with pg.session(1) as db:
        await pg.post(
            db,
            pg.request(
                party=1,
                lot=LOT_B,
                quantity=str(FOREIGN_QUANTITY),
                cost=str(FOREIGN_COST),
            ),
            party=1,
        )

    a_truth = await pg.snapshot(party=0)
    b_truth = await pg.snapshot(party=1)
    assert a_truth["quantity"] == EXPECTED_INBOUND
    assert a_truth["value"] == EXPECTED_VALUE
    assert a_truth["product_batches"] == 1
    assert a_truth["inventory_movements"] == 1
    assert a_truth["inventory_cost_events"] == 1
    assert a_truth["batches"][0][1] == LOT_A
    assert b_truth["quantity"] == FOREIGN_QUANTITY
    assert b_truth["value"] == FOREIGN_QUANTITY * FOREIGN_COST
    assert b_truth["product_batches"] == 1
    assert b_truth["inventory_movements"] == 1
    assert b_truth["inventory_cost_events"] == 1
    assert b_truth["batches"][0][1] == LOT_B

    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as db:
        company_a_code = await db.scalar(
            select(Company.company_code).where(Company.id == a.company_id)
        )
        company_b_code = await db.scalar(
            select(Company.company_code).where(Company.id == b.company_id)
        )
        owner_a_username = await db.scalar(
            select(CompanyPrincipal.username).where(
                CompanyPrincipal.id == a.owner.context.principal_id
            )
        )
        reader_a_username = await db.scalar(
            select(CompanyPrincipal.username).where(
                CompanyPrincipal.id == a.ordinary.context.principal_id
            )
        )
        owner_b_username = await db.scalar(
            select(CompanyPrincipal.username).where(
                CompanyPrincipal.id == b.owner.context.principal_id
            )
        )

    state = {
        "companyA": {
            "id": a.company_id,
            "code": str(company_a_code),
            "ownerUsername": str(owner_a_username),
            "ownerPassword": "NoLotSyntheticFixture123",
            "readerUsername": str(reader_a_username),
            "readerPassword": "SyntheticFixture123",
            "readerDriverId": a.ordinary.driver_id,
            "ownerDriverId": a.owner.driver_id,
            "warehouseA1": a.location_id,
            "warehouseA2": a.other_location_id,
            "variantId": a.variant_id,
            "batchId": int(a_truth["batches"][0][0]),
            "productName": "Real Browser Product A",
            "lot": LOT_A,
            "expectedInbound": str(EXPECTED_INBOUND),
            "expectedMove": str(EXPECTED_MOVE),
            "expectedRemaining": str(EXPECTED_REMAINING),
            "expectedCost": str(EXPECTED_COST),
        },
        "companyB": {
            "id": b.company_id,
            "code": str(company_b_code),
            "ownerUsername": str(owner_b_username),
            "ownerPassword": "NoLotSyntheticFixture123",
            "warehouse": b.location_id,
            "variantId": b.variant_id,
            "batchId": int(b_truth["batches"][0][0]),
            "productName": "Foreign Browser Product B",
            "lot": LOT_B,
            "expectedQuantity": str(FOREIGN_QUANTITY),
            "expectedCost": str(FOREIGN_COST),
        },
    }

    # The fixture is intentionally parameterized by the project's two costing
    # methods. Browser state is pinned to FIFO; the second pass remains a real
    # seed-contract check and never overwrites the selected browser identity.
    if pg.method == "FIFO":
        STATE_PATH.write_text(
            json.dumps(state, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    print(
        "REAL_BROWSER_SEED=PASS "
        + json.dumps(
            {"costing": pg.method, "state_written": pg.method == "FIFO"},
            sort_keys=True,
        ),
        flush=True,
    )


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


async def _engines():
    runtime_url, admin_url = checked_urls()
    return (
        create_async_engine(runtime_url, poolclass=NullPool),
        create_async_engine(admin_url, poolclass=NullPool),
    )


async def _assert_after_move(engine, company: dict):
    company_id = int(company["id"])
    variant_id = int(company["variantId"])
    a1 = int(company["warehouseA1"])
    a2 = int(company["warehouseA2"])
    async with _runtime_session(engine, company_id) as db:
        balances = dict(
            (
                int(location_id),
                Decimal(quantity),
            )
            for location_id, quantity in (
                await db.execute(
                    select(
                        InventoryBalance.location_id,
                        func.sum(InventoryBalance.on_hand_quantity),
                    )
                    .where(
                        InventoryBalance.company_id == company_id,
                        InventoryBalance.product_variant_id == variant_id,
                    )
                    .group_by(InventoryBalance.location_id)
                )
            ).all()
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
    assert balances.get(a1, Decimal("0")) == EXPECTED_REMAINING
    assert balances.get(a2, Decimal("0")) == EXPECTED_MOVE
    assert sum(balances.values(), Decimal("0")) == EXPECTED_INBOUND
    assert state is not None
    assert Decimal(state.quantity) == EXPECTED_INBOUND
    assert Decimal(state.inventory_value) == EXPECTED_VALUE
    assert Decimal(state.average_unit_cost) == EXPECTED_COST
    assert len(events) == 1
    assert Decimal(events[0].total_cost) == EXPECTED_VALUE


async def move():
    runtime_engine, admin_engine = await _engines()
    try:
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
        await _assert_after_move(runtime_engine, company)
        print("REAL_BROWSER_MOVE=PASS", flush=True)
    finally:
        await runtime_engine.dispose()
        await admin_engine.dispose()


async def revoke_a2():
    runtime_engine, admin_engine = await _engines()
    try:
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
                select(func.count())
                .select_from(UserLocationAccess)
                .where(
                    UserLocationAccess.company_id == int(company["id"]),
                    UserLocationAccess.driver_id == int(company["readerDriverId"]),
                    UserLocationAccess.location_id == int(company["warehouseA2"]),
                )
            )
            remaining_a1 = await db.scalar(
                select(func.count())
                .select_from(UserLocationAccess)
                .where(
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
    if len(sys.argv) != 2 or sys.argv[1] not in {"move", "revoke-a2"}:
        raise SystemExit(
            "usage: live_stock_real_browser_support.py move|revoke-a2"
        )
    asyncio.run(move() if sys.argv[1] == "move" else revoke_a2())


if __name__ == "__main__":
    main()
