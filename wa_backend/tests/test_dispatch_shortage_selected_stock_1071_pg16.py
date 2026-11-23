"""#1071 genuine signed PostgreSQL16/RLS and 100k+ history acceptance.

Execute in the repository's ALREADY MIGRATED disposable DB ONLY, as in #1059:
  WANASAH_NO_LOT_PG_GATE=1 WANASAH_SHORTAGE_1071_PG_GATE=1
  pytest -q -s tests/test_dispatch_shortage_selected_stock_1071_pg16.py

The test never claims the controlled synthetic timings are production P99.
Runtime HTTP role must be NOSUPERUSER/NOBYPASSRLS and tables FORCE RLS.
Fixture migrator is used only to bulk seed synthetic *test tenant* load.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal
import json
import os
from statistics import median
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, text, update

from database import engine as http_engine
from domains.dispatch_shortage_selected_stock import (
    MAX_SELECTED_STOCK_LINES, read_selected_vehicle_stock,
)
from domains.dispatch.route_execution.custody.proofs import CustodyRejected
from domains.inventory_vehicle_load.service import mutate_vehicle_load
from models import InventoryBalance, InventoryMovement, ProductBatch, ProductVariant
from services import acquire_inventory_location_guard
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_dispatch_shop_finance_edit_v1_postgres import _real_http, _owner, _token, _grant_company_dispatch_capability
from tests.test_live_stock_v1_route_sale_unload_postgres import _seed_mobile_uom_and_field
from tests.test_dispatch_shortage_vehicle_availability_pg16 import (
    _assert_restricted_pg, _vehicle_fixture, _epoch, _grant_location, _params, URL,
)

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_SHORTAGE_1071_PG_GATE") != "1",
        reason="Explicit isolated PostgreSQL16 signed #1071 acceptance only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _signed_stock_fixture(pg):
    await _assert_restricted_pg()
    tenant, foreign = pg.tenants
    field = await _seed_mobile_uom_and_field(pg, tenant)
    vehicle, location = await _vehicle_fixture(pg, tenant)
    epoch_id = await _epoch(pg, tenant, field, vehicle, location)
    product = int(tenant.variant_id)
    receipt = pg.request(
        lot="1071-" + uuid4().hex[:18], quantity="25", cost="1",
        expiry=date.today() + timedelta(days=100),
    )
    async with pg.session() as db:
        assert await pg.post(db, receipt) == {"message": "INBOUND_POSTED"}
        result = await mutate_vehicle_load(
            db, access=tenant.owner.access(db),
            actor_id=tenant.owner.driver_id,
            vehicle_id=vehicle, warehouse_id=tenant.location_id,
            direction="ADD", request_id=uuid4(),
            items=[{"product_variant_id": product, "quantity": Decimal("12")}],
        )
        assert result["movement_count"] > 0
        selected = await db.scalar(select(InventoryBalance).where(
            InventoryBalance.company_id == tenant.company_id,
            InventoryBalance.location_id == location,
            InventoryBalance.product_variant_id == product,
            InventoryBalance.stock_status == "AVAILABLE",
        ))
        assert selected is not None
        batch_id = int(selected.batch_id)
    return tenant, foreign, field, vehicle, location, epoch_id, product, batch_id


async def _bulk_100k_source_dest_collisions(gate, tenant, vehicle_location, other_location, product, batch):
    """100,001 REAL append-only movement rows, synthetic load ONLY.

    Source and destination reference the same vehicle for RESERVATION
    movements. This stresses the old OR(source,destination) lifetime COUNT.
    No physical/reservation balance mutations are forged in live endpoints.
    """
    tag = uuid4().hex[:12]
    count = 100_001
    async with gate.admin_engine.begin() as db:
        await db.execute(text(
            "SELECT set_config('app.current_tenant', :tenant, true)"
        ), {"tenant": str(tenant.company_id)})
        await db.execute(text("""
            INSERT INTO inventory_movements (
                company_id, performed_by, product_variant_id, batch_id,
                source_location_id, destination_location_id,
                source_stock_status, destination_stock_status,
                movement_kind, reservation_action, quantity,
                reference_type, reference_id, idempotency_key
            )
            SELECT :company, :actor, :variant, :batch, :location, :location,
                   'AVAILABLE', 'AVAILABLE', 'RESERVATION', 'RESERVE', 1,
                   'PERF_SYNTHETIC', '1071-' || :tag,
                   '1071-' || :tag || '-' || gs::text
            FROM generate_series(1, 100001) AS gs
        """), {
            "company": tenant.company_id, "actor": tenant.owner.driver_id,
            "variant": product, "batch": batch, "location": vehicle_location, "tag": tag,
        })
        # Dedicated global-history rows with the location only on the
        # destination side, and no matching selected vehicle balance.
        await db.execute(text("""
            INSERT INTO inventory_movements (
                company_id, performed_by, product_variant_id, batch_id,
                source_location_id, destination_location_id,
                source_stock_status, destination_stock_status,
                movement_kind, reservation_action, quantity,
                reference_type, reference_id, idempotency_key
            )
            SELECT :company, :actor, :variant, :batch, :other, :location,
                   'AVAILABLE', 'AVAILABLE', 'PHYSICAL', NULL, 1,
                   'PERF_SYNTHETIC', '1071-d-' || :tag,
                   '1071-d-' || :tag || '-' || gs::text
            FROM generate_series(1, 1000) AS gs
        """), {
            "company": tenant.company_id, "actor": tenant.owner.driver_id,
            "variant": product, "batch": batch, "location": vehicle_location,
            "other": other_location, "tag": tag,
        })
        await db.execute(text("ANALYZE inventory_movements"))
    return count + 1000


async def _selected_plan(db, tenant_id, location_id, product):
    raw = (await db.execute(text("""
        EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
        SELECT product_variant_id, batch_id, stock_status,
               on_hand_quantity, reserved_quantity, last_updated
        FROM inventory_balances
        WHERE company_id = :company AND location_id = :location
          AND product_variant_id = :variant
        ORDER BY product_variant_id, batch_id, stock_status LIMIT 10001
    """), {"company": tenant_id, "location": location_id, "variant": product})).scalar_one()
    if isinstance(raw, str):
        raw = json.loads(raw)
    assert isinstance(raw, list) and raw
    return raw[0]


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_real_101k_history_signed_http_no_movement_or_whole_vehicle_read(pg):
    tenant, foreign, field, vehicle, location, epoch_id, product, batch = await _signed_stock_fixture(pg)
    movement_count = await _bulk_100k_source_dest_collisions(
        pg, tenant, location, tenant.location_id, product, batch,
    )
    assert movement_count == 101001
    async with pg.session() as db:
        history = int(await db.scalar(select(func.count(InventoryMovement.id)).where(
            InventoryMovement.company_id == tenant.company_id,
        )) or 0)
        assert history >= 101001
        plan = await _selected_plan(db, tenant.company_id, location, product)
        print("1071_SELECTED_EXPLAIN " + json.dumps({
            "node": plan["Plan"]["Node Type"],
            "total_ms": plan["Execution Time"],
            "shared_hit": plan["Plan"].get("Shared Hit Blocks"),
            "shared_read": plan["Plan"].get("Shared Read Blocks"),
            "actual_rows": plan["Plan"]["Actual Rows"],
        }, sort_keys=True))
        # The plan is a REAL PostgreSQL 16 planner result, not extrapolated.
        assert plan["Plan"]["Actual Rows"] <= MAX_SELECTED_STOCK_LINES

    elapsed = []
    captured = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        captured.append(statement)
    event.listen(http_engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with _real_http() as client:
            owner = await _owner(client, pg, tenant)
            wrong_tenant = await _owner(client, pg, foreign)
            query = _params(field.driver.id, [product])
            assert (await client.get(URL, headers=wrong_tenant, params=query)).status_code == 404
            for attempt in range(4):
                t0 = perf_counter()
                response = await client.get(URL, headers=owner, params=query)
                elapsed.append(round((perf_counter() - t0)*1000, 2))
                assert response.status_code == 200, response.text
                body = response.json()
                assert body["status"] == "VERIFIED"
                assert body["custody_epoch_id"] == epoch_id
                assert body["items"] == [{
                    "product_id": str(product), "available_base": "12", "base_uom": "EACH",
                }]
                assert body["stock_snapshot"].startswith("selected-quote-v1:")
                assert len(body["stock_snapshot"]) <= 100
                if attempt == 0:
                    first_marker = body["stock_snapshot"]
                else:
                    assert body["stock_snapshot"] == first_marker
            # Actual same signed role, explicitly unauthorized location.
            await _grant_company_dispatch_capability(
                pg, tenant, tenant.ordinary, "shortage.create",
            )
            await _grant_location(pg, tenant, tenant.ordinary, tenant.location_id)
            employee = await _token(client, pg, tenant, tenant.ordinary, "SyntheticFixture123")
            assert (await client.get(URL, headers=employee, params=query)).status_code == 403
    finally:
        event.remove(http_engine.sync_engine, "before_cursor_execute", capture)
    # Old unbounded movement-history COUNT/MAX is not even executed by GET.
    assert not any("FROM inventory_movements" in sql.lower() for sql in captured)
    selected_reads = [sql for sql in captured if "FROM inventory_balances" in sql.lower()]
    assert len(selected_reads) == 4
    assert all("product_variant_id IN" in sql for sql in selected_reads)
    assert all("LIMIT" in sql.upper() for sql in selected_reads)
    print("1071_REAL_PG16_LOAD " + json.dumps({
        "historical_movements": history, "samples_ms": elapsed,
        "min_ms": min(elapsed), "median_ms": median(elapsed),
        "max_ms": max(elapsed),
        "movement_reads": 0, "selected_stock_reads": len(selected_reads),
    }, sort_keys=True))


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_selected_lots_1_1000_10000_limit_10001_unknown_and_approval_reader(pg):
    tenant, _, field, vehicle, location, epoch, product, batch = await _signed_stock_fixture(pg)
    # Grow the selected SKU from 1 to 1k to 10k lots, then 10k+1 UNKNOWN.
    # The data remains a synthetic disposable test tenant.
    tag = uuid4().hex[:14]
    async with pg.admin_engine.begin() as db:
        await db.execute(text("SELECT set_config('app.current_tenant',:c,true)"),
                         {"c": str(tenant.company_id)})
        await db.execute(text("""
            INSERT INTO product_batches(company_id,product_variant_id,batch_number,
                                        expiry_date,disposition)
            SELECT :company, :variant, :prefix || gs::text,
                   CURRENT_DATE + 120, 'RELEASED'
            FROM generate_series(1,999) gs
        """), {"company": tenant.company_id, "variant": product, "prefix": "1071-" + tag})
        await db.execute(text("""
            INSERT INTO inventory_balances(company_id,location_id,product_variant_id,
                                           batch_id,stock_status,on_hand_quantity,reserved_quantity)
            SELECT :company,:location,:variant,b.id,'AVAILABLE',1,0
            FROM product_batches b
            WHERE b.company_id = :company AND b.product_variant_id = :variant
              AND b.batch_number LIKE :prefix
        """), {"company": tenant.company_id, "location": location,
               "variant": product, "prefix": "1071-" + tag + "%"})
        await db.execute(text("ANALYZE inventory_balances"))
    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        thousand = await client.get(URL, headers=owner, params=_params(field.driver.id,[product]))
        assert thousand.status_code == 200
        assert thousand.json()["status"] == "VERIFIED"
        assert thousand.json()["items"][0]["available_base"] == "1011"
        # Expand to 10k lots; all selected evidence is still bounded by 10k.
        async with pg.admin_engine.begin() as db:
            await db.execute(text("SELECT set_config('app.current_tenant',:c,true)"),
                             {"c": str(tenant.company_id)})
            await db.execute(text("""
                WITH inserted AS (
                    INSERT INTO product_batches(
                        company_id,product_variant_id,batch_number,expiry_date,disposition
                    )
                    SELECT :company, :variant, :prefix || gs::text,
                           CURRENT_DATE + 120, 'RELEASED'
                    FROM generate_series(1000,9999) gs
                    RETURNING id
                )
                INSERT INTO inventory_balances(
                    company_id,location_id,product_variant_id,batch_id,stock_status,
                    on_hand_quantity,reserved_quantity
                )
                SELECT :company,:location,:variant,id,'AVAILABLE',1,0
                FROM inserted
            """), {"company":tenant.company_id,"location":location,
                   "variant":product,"prefix":"1071-"+tag})
        response = await client.get(
            URL, headers=owner, params=_params(field.driver.id, [product])
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "VERIFIED"
        assert response.json()["items"][0]["available_base"] == "10011"
        async with pg.session() as db:
            evidence = await read_selected_vehicle_stock(
                db, tenant.company_id, vehicle, {product},
                expected_epoch_id=epoch,
                expected_representative_id=field.context.representative_id,
                for_approval=True,
            )
            assert len(evidence.lines) == 10000
            assert evidence.epoch.id == epoch
            await db.rollback()
        # An extra selected lot exceeds the resource window; no partial/zero.
        async with pg.admin_engine.begin() as db:
            await db.execute(text("SELECT set_config('app.current_tenant',:c,true)"),
                             {"c": str(tenant.company_id)})
            await db.execute(text("""
                INSERT INTO product_batches(company_id,product_variant_id,batch_number,
                                            expiry_date,disposition)
                VALUES(:company,:variant,:name,CURRENT_DATE+120,'RELEASED')
                RETURNING id
            """), {"company": tenant.company_id, "variant": product, "name": "1071-"+tag+"-overflow"})
            bid = (await db.execute(text(
                "SELECT id FROM product_batches WHERE company_id=:company AND "
                "product_variant_id=:variant AND batch_number=:name"
            ), {"company": tenant.company_id, "variant": product,
                "name": "1071-"+tag+"-overflow"})).scalar_one()
            await db.execute(text("""
                INSERT INTO inventory_balances(company_id,location_id,product_variant_id,
                                               batch_id,stock_status,on_hand_quantity,reserved_quantity)
                VALUES(:company,:location,:variant,:batch,'AVAILABLE',1,0)
            """), {"company": tenant.company_id, "location": location,
                   "variant": product, "batch": bid})
        overflow = await client.get(
            URL, headers=owner, params=_params(field.driver.id, [product])
        )
        assert overflow.status_code == 200
        assert overflow.json()["status"] == "UNKNOWN"
        assert overflow.json()["reason"] == "VEHICLE_STOCK_UNVERIFIED"


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_signed_quote_guard_fences_mid_read_stock_writer_and_hold_unknown(pg):
    tenant, _, field, vehicle, location, epoch, product, batch = await _signed_stock_fixture(pg)
    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        query = _params(field.driver.id, [product])
        # A genuine stock mutation waits for the same transaction guard; GET
        # cannot read a partially updated balance+lot state.
        async with pg.session() as db:
            await acquire_inventory_location_guard(
                db, tenant.company_id, location, exclusive=True,
            )
            await db.execute(update(InventoryBalance).where(
                InventoryBalance.company_id == tenant.company_id,
                InventoryBalance.location_id == location,
                InventoryBalance.product_variant_id == product,
            ).values(on_hand_quantity=Decimal("7")))
            pending = asyncio.create_task(
                client.get(URL, headers=owner, params=query),
            )
            await asyncio.sleep(0.08)
            assert not pending.done(), "Read must wait for the same location guard"
            await db.commit()
        response = await asyncio.wait_for(pending, timeout=10)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "VERIFIED"
        assert response.json()["items"][0]["available_base"] == "7"

        # Hold/recall is not a promise of 0; evidence is UNKNOWN.
        async with pg.session() as db:
            variant = await db.get(ProductVariant, product)
            variant.operational_hold = "SALES_HOLD"
            await db.commit()
        hold = await client.get(URL, headers=owner, params=query)
        assert hold.status_code == 200
        assert hold.json()["status"] == "UNKNOWN"
        async with pg.session() as db:
            variant = await db.get(ProductVariant, product)
            variant.operational_hold = "NONE"
            await db.commit()
        resumed = await client.get(URL, headers=owner, params=query)
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "VERIFIED"

        async with pg.session() as db:
            stock = await db.scalar(select(InventoryBalance).where(
                InventoryBalance.company_id == tenant.company_id,
                InventoryBalance.location_id == location,
                InventoryBalance.product_variant_id == product,
            ))
            stock.reserved_quantity = Decimal("3")
            await db.commit()
        reserved = await client.get(URL, headers=owner, params=query)
        assert reserved.json()["items"][0]["available_base"] == "4"
        assert reserved.json()["stock_snapshot"] != resumed.json()["stock_snapshot"]
        async with pg.session() as db:
            b = await db.get(ProductBatch, batch)
            b.disposition = "RECALLED"
            await db.commit()
        recalled = await client.get(URL, headers=owner, params=query)
        assert recalled.json()["items"][0]["available_base"] == "0"
        async with pg.session() as db:
            b = await db.get(ProductBatch, batch)
            b.disposition = "RELEASED"
            b.expiry_date = date.today() - timedelta(days=1)
            await db.commit()
        expired = await client.get(URL, headers=owner, params=query)
        assert expired.json()["items"][0]["available_base"] == "0"
