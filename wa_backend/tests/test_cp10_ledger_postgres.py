"""Real PostgreSQL 16 acceptance for CP10 Ledger and append-only inbound correction."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
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
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api.warehouse import inbound_adjustments, ledger
from context import tenant_context
from domains.ledger import inbound_adjustment as adjustment_domain
from domains.ledger.inbound_adjustment import LedgerAdjustmentError
from models import (
    Company,
    Driver,
    InventoryBalance,
    InventoryLocation,
    InventoryMovement,
    Permission,
    Product,
    ProductBatch,
    ProductVariant,
    Role,
    SystemAuditLog,
    UOM,
    UserLocationAccess,
    role_permissions,
    utc_now,
)
from services import apply_inventory_movement
from tests.canonical_actor_fixtures import (
    seed_company_owner_fixture,
    seed_ordinary_backoffice_fixture,
)


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CP10_PG_GATE") != "1",
        reason="Explicit disposable CP10 PostgreSQL gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


def _checked_urls():
    names = ("WANASAH_CP10_PG_URL", "WANASAH_CP10_PG_ADMIN_URL")
    urls = [make_url(os.environ[name]) for name in names]
    for url in urls:
        if (
            url.drivername != "postgresql+asyncpg"
            or url.host != "127.0.0.1"
            or url.port != 55450
            or url.database != "wanasah_cp10_test"
        ):
            raise RuntimeError("Refusing any database outside the disposable CP10 PostgreSQL gate")
    if urls[0].username != "cp10_app" or urls[1].username == urls[0].username:
        raise RuntimeError("CP10 requires distinct restricted runtime and migration roles")
    return urls


class Gate:
    def __init__(self, runtime_engine, admin_engine):
        self.runtime_engine = runtime_engine
        self.admin_engine = admin_engine
        self.a = None
        self.b = None

    @asynccontextmanager
    async def session(self, tenant):
        token = tenant_context.set(tenant.company_id)
        try:
            async with self.runtime_engine.connect() as connection:
                db = AsyncSession(bind=connection, expire_on_commit=False)
                try:
                    await db.execute(
                        text("SELECT set_config('app.current_tenant',:tenant,false)"),
                        {"tenant": str(tenant.company_id)},
                    )
                    await db.execute(text("SET statement_timeout='15000ms'"))
                    yield db
                finally:
                    await db.close()
        finally:
            tenant_context.reset(token)


async def _grant_location(seed: AsyncSession, tenant, location_id: int, *codes: str) -> None:
    for code in codes:
        permission = await seed.scalar(select(Permission).where(Permission.code == code))
        assert permission is not None, f"Missing migrated permission {code}"
        role = Role(company_id=tenant.company_id, name=f"CP10 {code} {uuid4().hex}")
        seed.add(role)
        await seed.flush()
        await seed.execute(
            role_permissions.insert().values(
                company_id=tenant.company_id,
                role_id=role.id,
                permission_id=permission.id,
            )
        )
        seed.add(
            UserLocationAccess(
                company_id=tenant.company_id,
                role_id=role.id,
                driver_id=tenant.ordinary.driver_id,
                location_id=location_id,
            )
        )


async def _seed_movement(db, tenant, *, location_id, reference_type, reference, quantity="10", batch_id=None):
    movement = await apply_inventory_movement(
        db,
        company_id=tenant.company_id,
        performed_by=tenant.owner.driver_id,
        product_variant_id=tenant.variant_id,
        batch_id=batch_id if batch_id is not None else tenant.batch_id,
        quantity=Decimal(quantity),
        movement_kind="PHYSICAL",
        reference_type=reference_type,
        reference_id=reference,
        idempotency_key=f"CP10-{tenant.company_id}-{location_id}-{reference_type}-{reference}-{uuid4().hex}",
        source_location_id=None,
        destination_location_id=location_id,
        source_stock_status=None,
        destination_stock_status="AVAILABLE",
        notes="overlap evidence",
    )
    return movement


@pytest_asyncio.fixture(loop_scope="function")
async def pg():
    runtime_url, admin_url = _checked_urls()
    runtime_engine = create_async_engine(runtime_url, poolclass=NullPool)
    admin_engine = create_async_engine(admin_url, poolclass=NullPool)
    gate = Gate(runtime_engine, admin_engine)
    try:
        async with runtime_engine.connect() as connection:
            identity = (
                await connection.execute(
                    text(
                        "SELECT current_database(),current_user,inet_server_port(),r.rolsuper,r.rolbypassrls "
                        "FROM pg_roles r WHERE r.rolname=current_user"
                    )
                )
            ).one()
            assert tuple(identity) == ("wanasah_cp10_test", "cp10_app", 55450, False, False)

        config = AlembicConfig(str(Path(__file__).parents[1] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
        expected_heads = set(ScriptDirectory.from_config(config).get_heads())
        async with AsyncSession(admin_engine, expire_on_commit=False) as seed:
            assert set((await seed.execute(text("SELECT version_num FROM alembic_version"))).scalars()) == expected_heads
            uom = await seed.scalar(select(UOM).where(UOM.code == "EACH"))
            if uom is None:
                uom = UOM(code="EACH", name="Each")
                seed.add(uom)
                await seed.flush()

            companies = [
                Company(name="CP10 Company A", company_code="CP10A-" + uuid4().hex, timezone="Asia/Amman", currency_code="JOD"),
                Company(name="CP10 Company B", company_code="CP10B-" + uuid4().hex, timezone="Asia/Amman", currency_code="JOD"),
            ]
            seed.add_all(companies)
            await seed.flush()

            tenants = []
            for index, company in enumerate(companies):
                await seed.execute(
                    text("SELECT set_config('app.current_tenant',:tenant,true)"),
                    {"tenant": str(company.id)},
                )
                owner = await seed_company_owner_fixture(seed, company.id, password="CP10FixturePassword123")
                ordinary = await seed_ordinary_backoffice_fixture(seed, company.id)
                product = Product(company_id=company.id, code="OVERLAP", name="Overlap Product")
                seed.add(product)
                await seed.flush()
                variant = ProductVariant(
                    company_id=company.id,
                    product_id=product.id,
                    name="Overlap Product",
                    sku="OVERLAP-SKU",
                    base_uom_id=uom.id,
                    quantity_scale=6,
                    quantity_step=Decimal("0.000001"),
                    lot_control_mode="REQUIRED",
                    expiry_control_mode="OPTIONAL",
                    lifecycle_status="ACTIVE",
                    published_at=utc_now(),
                )
                seed.add(variant)
                locations = [
                    InventoryLocation(company_id=company.id, code=f"WH-{index}-{i}", name="Overlap Warehouse", location_type="WAREHOUSE")
                    for i in range(2 if index == 0 else 1)
                ]
                seed.add_all(locations)
                await seed.flush()
                batch = ProductBatch(
                    company_id=company.id,
                    product_variant_id=variant.id,
                    batch_number="LOT-OVERLAP",
                )
                seed.add(batch)
                await seed.flush()
                tenants.append(
                    NS(
                        company_id=company.id,
                        owner=owner,
                        ordinary=ordinary,
                        variant_id=variant.id,
                        uom_id=uom.id,
                        batch_id=batch.id,
                        locations=[location.id for location in locations],
                    )
                )

            gate.a, gate.b = tenants
            await _grant_location(seed, gate.a, gate.a.locations[0], "ledger.read", "ledger.adjust")
            await seed.commit()

        async with gate.session(gate.a) as db:
            a1_inbound = await _seed_movement(
                db, gate.a, location_id=gate.a.locations[0], reference_type="INBOUND_SUPPLIER", reference="INV-OVERLAP"
            )
            a1_other = await _seed_movement(
                db, gate.a, location_id=gate.a.locations[0], reference_type="STOCKTAKE", reference="STK-A1", quantity="2"
            )
            a2_inbound = await _seed_movement(
                db, gate.a, location_id=gate.a.locations[1], reference_type="INBOUND_SUPPLIER", reference="INV-A2", quantity="10"
            )
            await db.commit()
            gate.a.a1_inbound = int(a1_inbound.id)
            gate.a.a1_other = int(a1_other.id)
            gate.a.a2_inbound = int(a2_inbound.id)

        async with gate.session(gate.b) as db:
            b1 = await _seed_movement(
                db, gate.b, location_id=gate.b.locations[0], reference_type="INBOUND_SUPPLIER", reference="INV-OVERLAP"
            )
            await db.commit()
            gate.b.b1_inbound = int(b1.id)

        yield gate
    finally:
        await runtime_engine.dispose()
        await admin_engine.dispose()


async def test_company_location_scope_search_reference_cursor_and_non_owner_grant(pg):
    async with pg.session(pg.a) as db:
        access = pg.a.ordinary.access(db)
        first = await ledger.get_warehouse_ledger_cursor(
            pg.a.locations[0], None, 1, None, None, None, db, access
        )
        assert len(first["items"]) == 1
        assert first["has_more"] is True and first["next_cursor"]
        assert first["total"] == 2
        visible_ids = {item["id"] for item in first["items"]}
        assert pg.a.a2_inbound not in visible_ids
        assert pg.b.b1_inbound not in visible_ids

        second = await ledger.get_warehouse_ledger_cursor(
            pg.a.locations[0], first["next_cursor"], 1, None, None, None, db, access
        )
        all_ids = visible_ids | {item["id"] for item in second["items"]}
        assert all_ids == {pg.a.a1_inbound, pg.a.a1_other}

        searched = await ledger.get_warehouse_ledger_cursor(
            pg.a.locations[0], None, 20, "Overlap", None, None, db, access
        )
        assert {item["id"] for item in searched["items"]} == all_ids

        exact_ref = await ledger.get_warehouse_ledger_cursor(
            pg.a.locations[0], None, 20, None, "INBOUND_SUPPLIER", "INV-OVERLAP", db, access
        )
        assert [item["id"] for item in exact_ref["items"]] == [pg.a.a1_inbound]

        tampered = first["next_cursor"][:-1] + ("A" if first["next_cursor"][-1] != "A" else "B")
        with pytest.raises(HTTPException) as invalid:
            await ledger.get_warehouse_ledger_cursor(
                pg.a.locations[0], tampered, 1, None, None, None, db, access
            )
        assert invalid.value.status_code == 400
        assert invalid.value.detail["code"] == "LEDGER_CURSOR_INVALID"

        with pytest.raises(HTTPException) as no_a2:
            await ledger.get_warehouse_ledger_cursor(
                pg.a.locations[1], None, 20, None, None, None, db, access
            )
        assert no_a2.value.status_code == 403

    async with pg.session(pg.a) as db:
        owner_access = pg.a.owner.access(db)
        a2 = await ledger.get_warehouse_ledger_cursor(
            pg.a.locations[1], None, 20, None, None, None, db, owner_access
        )
        assert {item["id"] for item in a2["items"]} == {pg.a.a2_inbound}
        with pytest.raises(HTTPException) as cursor_scope:
            await ledger.get_warehouse_ledger_cursor(
                pg.a.locations[1], first["next_cursor"], 1, None, None, None, db, owner_access
            )
        assert cursor_scope.value.detail["code"] == "LEDGER_CURSOR_INVALID"

    async with pg.session(pg.b) as db:
        with pytest.raises(HTTPException) as foreign:
            await ledger.get_warehouse_ledger_cursor(
                pg.a.locations[0], None, 20, None, None, None, db, pg.b.owner.access(db)
            )
        assert foreign.value.status_code == 404


async def test_append_only_positive_negative_replay_and_cross_warehouse_authority(pg):
    async with pg.session(pg.a) as db:
        ordinary_access = pg.a.ordinary.access(db)
        state_response = await inbound_adjustments.get_warehouse_entry_adjustment_state(
            pg.a.a1_inbound, db, ordinary_access
        )
        assert state_response["current_total_quantity"] == "10"
        assert state_response["warehouse_location_id"] == pg.a.locations[0]
        with pytest.raises(HTTPException) as denied_a2:
            await inbound_adjustments.get_warehouse_entry_adjustment_state(
                pg.a.a2_inbound, db, ordinary_access
            )
        assert denied_a2.value.status_code == 403

        original = await db.get(InventoryMovement, pg.a.a1_inbound)
        original_shape = (original.quantity, original.reference_id, original.reference_type, original.batch_id)
        before_count = int(await db.scalar(select(func.count(InventoryMovement.id)).where(
            InventoryMovement.company_id == pg.a.company_id,
            InventoryMovement.reference_id == "INV-OVERLAP",
        )))
        state, delta, positive_id = await adjustment_domain.apply_inbound_adjustment(
            db,
            company_id=pg.a.company_id,
            entry_id=pg.a.a1_inbound,
            actor_id=pg.a.ordinary.driver_id,
            new_total_quantity=Decimal("12.000001"),
            uom_id=pg.a.uom_id,
            notes="positive",
        )
        assert delta == Decimal("2.000001") and positive_id is not None
        await db.commit()

    async with pg.session(pg.a) as db:
        original = await db.get(InventoryMovement, pg.a.a1_inbound)
        assert (original.quantity, original.reference_id, original.reference_type, original.batch_id) == original_shape
        positive = await db.get(InventoryMovement, positive_id)
        assert positive.reference_type == "INBOUND_CORRECTION"
        assert positive.destination_location_id == pg.a.locations[0]
        assert positive.source_location_id is None
        assert await db.scalar(select(func.count(SystemAuditLog.id)).where(
            SystemAuditLog.company_id == pg.a.company_id,
            SystemAuditLog.action_type == "INBOUND_ADJUSTMENT",
        )) >= 1
        state, delta, negative_id = await adjustment_domain.apply_inbound_adjustment(
            db,
            company_id=pg.a.company_id,
            entry_id=pg.a.a1_inbound,
            actor_id=pg.a.ordinary.driver_id,
            new_total_quantity=Decimal("8.000001"),
            uom_id=pg.a.uom_id,
            notes="negative",
        )
        assert state.current_total_quantity == Decimal("12.000001")
        assert delta == Decimal("-4.000000") and negative_id is not None
        await db.commit()

    async with pg.session(pg.a) as db:
        state, delta, replay_id = await adjustment_domain.apply_inbound_adjustment(
            db,
            company_id=pg.a.company_id,
            entry_id=pg.a.a1_inbound,
            actor_id=pg.a.ordinary.driver_id,
            new_total_quantity=Decimal("8.000001"),
            uom_id=pg.a.uom_id,
            notes="replay",
        )
        assert state.current_total_quantity == Decimal("8.000001")
        assert delta == 0 and replay_id is None
        after_count = int(await db.scalar(select(func.count(InventoryMovement.id)).where(
            InventoryMovement.company_id == pg.a.company_id,
            InventoryMovement.reference_id == "INV-OVERLAP",
        )))
        assert after_count == before_count + 2

        with pytest.raises(LedgerAdjustmentError) as uom:
            await adjustment_domain.apply_inbound_adjustment(
                db,
                company_id=pg.a.company_id,
                entry_id=pg.a.a1_inbound,
                actor_id=pg.a.ordinary.driver_id,
                new_total_quantity=Decimal("9"),
                uom_id=pg.a.uom_id + 999,
                notes=None,
            )
        assert uom.value.code == "UOM_MISMATCH"

    async with pg.session(pg.b) as db:
        with pytest.raises(HTTPException) as foreign:
            await inbound_adjustments.get_warehouse_entry_adjustment_state(
                pg.a.a1_inbound, db, pg.b.owner.access(db)
            )
        assert foreign.value.status_code == 403 or foreign.value.status_code == 404


async def test_concurrent_equivalent_correction_serializes_to_one_final_delta(pg):
    async with pg.session(pg.a) as first, pg.session(pg.a) as second:
        async def correct(db):
            state, delta, movement_id = await adjustment_domain.apply_inbound_adjustment(
                db,
                company_id=pg.a.company_id,
                entry_id=pg.a.a1_inbound,
                actor_id=pg.a.ordinary.driver_id,
                new_total_quantity=Decimal("11"),
                uom_id=pg.a.uom_id,
                notes="concurrent",
            )
            await db.commit()
            return state, delta, movement_id

        left, right = await asyncio.wait_for(asyncio.gather(correct(first), correct(second)), 12)
    movement_ids = [result[2] for result in (left, right) if result[2] is not None]
    assert len(movement_ids) == 1
    async with pg.session(pg.a) as db:
        state = await adjustment_domain.load_inbound_adjustment_state(
            db,
            company_id=pg.a.company_id,
            entry_id=pg.a.a1_inbound,
            lock=False,
        )
        assert state.current_total_quantity == Decimal("11")
        assert await db.scalar(select(func.count(InventoryMovement.id)).where(
            InventoryMovement.company_id == pg.a.company_id,
            InventoryMovement.reference_type == "INBOUND_CORRECTION",
            InventoryMovement.reference_id == "INV-OVERLAP",
        )) == 1


async def test_transaction_rollback_leaves_no_partial_movement_or_balance_effect(pg):
    async with pg.session(pg.a) as db:
        before_movements = int(await db.scalar(select(func.count(InventoryMovement.id)).where(
            InventoryMovement.company_id == pg.a.company_id
        )))
        before_quantity = Decimal(await db.scalar(select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0)).where(
            InventoryBalance.company_id == pg.a.company_id,
            InventoryBalance.location_id == pg.a.locations[0],
        )))

        real_apply = adjustment_domain.apply_inventory_movement

        async def apply_then_fail(*args, **kwargs):
            await real_apply(*args, **kwargs)
            raise RuntimeError("synthetic transaction failure")

        with patch.object(adjustment_domain, "apply_inventory_movement", side_effect=apply_then_fail):
            with pytest.raises(RuntimeError):
                await adjustment_domain.apply_inbound_adjustment(
                    db,
                    company_id=pg.a.company_id,
                    entry_id=pg.a.a1_inbound,
                    actor_id=pg.a.ordinary.driver_id,
                    new_total_quantity=Decimal("13"),
                    uom_id=pg.a.uom_id,
                    notes="rollback",
                )
            await db.rollback()

    async with pg.session(pg.a) as db:
        assert int(await db.scalar(select(func.count(InventoryMovement.id)).where(
            InventoryMovement.company_id == pg.a.company_id
        ))) == before_movements
        assert Decimal(await db.scalar(select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0)).where(
            InventoryBalance.company_id == pg.a.company_id,
            InventoryBalance.location_id == pg.a.locations[0],
        ))) == before_quantity


async def test_query_count_is_row_independent_and_representative_explain_runs(pg):
    counts = []

    @event.listens_for(pg.runtime_engine.sync_engine, "before_cursor_execute")
    def _count(_conn, _cursor, statement, _parameters, _context, _executemany):
        if counts and statement.lstrip().upper().startswith(("SELECT", "WITH")):
            counts[-1] += 1

    try:
        async with pg.session(pg.a) as db:
            access = pg.a.owner.access(db)
            counts.append(0)
            await ledger.get_warehouse_ledger_cursor(pg.a.locations[0], None, 1, None, None, None, db, access)
            one_row_count = counts[-1]
            counts.append(0)
            await ledger.get_warehouse_ledger_cursor(pg.a.locations[0], None, 20, None, None, None, db, access)
            large_page_count = counts[-1]
            counts.append(0)
            await ledger.get_warehouse_ledger_cursor(
                pg.a.locations[0], None, 20, None, "INBOUND_SUPPLIER", "INV-OVERLAP", db, access
            )
            reference_count = counts[-1]
            assert one_row_count == large_page_count
            assert reference_count <= large_page_count
            print(f"CP10_LEDGER_QUERY_COUNTS first={one_row_count} larger={large_page_count} reference={reference_count}")

            explain_cases = [
                ("default", "company_id=:company AND (source_location_id=:location OR destination_location_id=:location)"),
                ("search", "company_id=:company AND (source_location_id=:location OR destination_location_id=:location) AND lower(coalesce(reference_id,'')) LIKE '%overlap%'"),
                ("reference_type", "company_id=:company AND (source_location_id=:location OR destination_location_id=:location) AND reference_type='INBOUND_SUPPLIER'"),
                ("exact_reference", "company_id=:company AND (source_location_id=:location OR destination_location_id=:location) AND reference_type='INBOUND_SUPPLIER' AND reference_id='INV-OVERLAP'"),
            ]
            for label, predicate in explain_cases:
                plan = (await db.execute(text(
                    f"EXPLAIN (FORMAT TEXT) SELECT id FROM inventory_movements WHERE {predicate} ORDER BY created_at DESC,id DESC LIMIT 20"
                ), {"company": pg.a.company_id, "location": pg.a.locations[0]})).scalars().all()
                assert plan and any("Limit" in line for line in plan)
                print(f"CP10_EXPLAIN_{label.upper()}=" + " | ".join(plan))
    finally:
        event.remove(pg.runtime_engine.sync_engine, "before_cursor_execute", _count)
