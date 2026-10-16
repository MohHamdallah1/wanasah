from __future__ import annotations

import inspect
import json
import math
import os
from decimal import Decimal
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api import inventory_stock_policy, product_locations
from api.warehouse import batch_index, ledger, live_stock, locations, stocktake
from domains.live_stock_projection.service import rebuild_live_stock_company
from domains.stocktake.contracts import StocktakeStartCommand
from models import (
    InventoryBalance,
    InventoryLocation,
    Product,
    ProductBatch,
    ProductLocation,
    ProductVariant,
    utc_now,
)
from tests.test_cp12_inventory_security_postgres import (
    _batch_kwargs,
    _grant_scoped_permissions,
)
from tests.test_cp7_live_stock_postgres import _cursor_kwargs, _prepare_cp7
from tests.test_inbound_no_lot_frozen_postgres import pg


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CP12_PERF_PG_GATE") != "1",
        reason="Explicit migrated disposable CP12 PostgreSQL performance gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _seed_volume(pg, case, *, variants: int = 96, warehouses: int = 64, movements: int = 48):
    a = case.a
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(
            text("SELECT set_config('app.current_tenant',:tenant,true)"),
            {"tenant": str(a.company_id)},
        )
        base = await seed.get(ProductVariant, a.variant_id)
        assert base is not None
        product = await seed.get(Product, base.product_id)
        assert product is not None

        extra_variants: list[ProductVariant] = []
        for index in range(variants):
            variant = ProductVariant(
                company_id=a.company_id,
                product_id=product.id,
                name=f"CP12 Volume Product {index:04d}",
                sku=f"CP12-SKU-{index:04d}",
                base_uom_id=a.uom_id,
                quantity_scale=6,
                quantity_step=Decimal("0.000001"),
                lot_control_mode="OPTIONAL",
                expiry_control_mode="OPTIONAL",
                lifecycle_status="ACTIVE",
                published_at=utc_now(),
            )
            seed.add(variant)
            extra_variants.append(variant)
        await seed.flush()

        for index, variant in enumerate(extra_variants):
            seed.add(
                ProductLocation(
                    company_id=a.company_id,
                    location_id=a.location_id,
                    product_variant_id=variant.id,
                    created_by=a.owner.driver_id,
                    operational_flags={
                        "inbound_enabled": True,
                        "outbound_enabled": True,
                    },
                )
            )
            batch = ProductBatch(
                company_id=a.company_id,
                product_variant_id=variant.id,
                batch_number=f"CP12-VOL-{index:04d}",
                disposition="RELEASED",
                is_active=True,
            )
            seed.add(batch)
            await seed.flush()
            seed.add(
                InventoryBalance(
                    company_id=a.company_id,
                    location_id=a.location_id,
                    product_variant_id=variant.id,
                    batch_id=batch.id,
                    stock_status="AVAILABLE",
                    on_hand_quantity=Decimal("10"),
                    reserved_quantity=Decimal("0"),
                )
            )

        for index in range(warehouses):
            seed.add(
                InventoryLocation(
                    company_id=a.company_id,
                    name=f"CP12 Warehouse {index:04d}",
                    code=f"CP12-WH-{index:04d}-{uuid4().hex[:6]}",
                    location_type="WAREHOUSE",
                    is_active=True,
                    version=1,
                )
            )
        await seed.flush()
        await rebuild_live_stock_company(seed, company_id=a.company_id)
        await seed.commit()

    async with pg.session() as db:
        for index in range(movements):
            await pg.post(
                db,
                pg.request(
                    lot=f"CP12-MOVE-{index:04d}",
                    quantity="1.000001",
                    cost="1.250000",
                ),
            )

    await _grant_scoped_permissions(
        pg,
        a,
        (
            "location.read",
            "product_location.read",
            "ledger.read",
            "stocktake.read",
            "stocktake.start",
            "stocktake.count",
        ),
        a.location_id,
    )
    return extra_variants


async def _count_sql(pg, callback):
    count = 0

    def before_cursor_execute(*_args, **_kwargs):
        nonlocal count
        count += 1

    event.listen(pg.runtime_engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    try:
        result = await callback()
        return result, count
    finally:
        event.remove(pg.runtime_engine.sync_engine, "before_cursor_execute", before_cursor_execute)


async def _percentiles(callback, *, samples: int = 18):
    for _ in range(2):
        await callback()
    values: list[float] = []
    for _ in range(samples):
        started = perf_counter()
        await callback()
        values.append((perf_counter() - started) * 1000.0)
    values.sort()

    def percentile(p: float) -> float:
        index = max(0, min(len(values) - 1, math.ceil((p / 100.0) * len(values)) - 1))
        return round(values[index], 3)

    return {"p50_ms": percentile(50), "p95_ms": percentile(95), "p99_ms": percentile(99)}


def _plan_nodes(plan: dict) -> tuple[list[str], list[str]]:
    nodes: list[str] = []
    indexes: list[str] = []

    def walk(node: dict):
        nodes.append(str(node.get("Node Type")))
        if node.get("Index Name"):
            indexes.append(str(node["Index Name"]))
        for child in node.get("Plans") or []:
            walk(child)

    walk(plan)
    return nodes, indexes


async def _explain(db, label: str, sql: str, params: dict):
    raw = await db.scalar(text("EXPLAIN (FORMAT JSON) " + sql), params)
    assert isinstance(raw, list) and raw and "Plan" in raw[0]
    plan = raw[0]["Plan"]
    nodes, indexes = _plan_nodes(plan)
    evidence = {
        "root": plan.get("Node Type"),
        "plan_rows": plan.get("Plan Rows"),
        "nodes": nodes,
        "indexes": sorted(set(indexes)),
    }
    print("CP12_EXPLAIN", label, json.dumps(evidence, sort_keys=True), flush=True)
    return evidence


async def test_cp12_hard_bounds_and_filter_before_pagination_contracts():
    contracts = {
        "live_stock": (inspect.getsource(live_stock.get_warehouse_inventory), "le=200"),
        "batches": (inspect.getsource(batch_index.get_warehouse_inventory_batch_index_cursor), "le=100"),
        "warehouses": (inspect.getsource(locations.manage_warehouse_locations), "le=200"),
        "product_locations": (inspect.getsource(product_locations.list_product_locations), "le=200"),
        "stocktake_sessions": (inspect.getsource(stocktake.list_active_stocktake_sessions), "le=200"),
        "ledger": (inspect.getsource(ledger.get_warehouse_ledger_cursor), "le=200"),
    }
    for name, (source, bound) in contracts.items():
        compact = "".join(source.split())
        assert bound in compact, f"{name} lacks an explicit hard page maximum"

    batch_source = inspect.getsource(batch_index.get_warehouse_inventory_batch_index_cursor)
    assert batch_source.index("*_search_predicates(tokens)") < batch_source.index(".limit(limit + 1)")
    assert batch_source.index("ProductBatch.company_id == company_id") < batch_source.index(".limit(limit + 1)")

    warehouse_source = inspect.getsource(locations.manage_warehouse_locations)
    assert warehouse_source.index("clean_search") < warehouse_source.index(".limit(limit + 1)")
    assert warehouse_source.index("access.location_filter('location.read')") < warehouse_source.index(".limit(limit + 1)")

    from domains.ledger import read as ledger_read

    ledger_source = inspect.getsource(ledger_read.read_warehouse_ledger_page)
    assert ledger_source.index("_apply_filters(") < ledger_source.index(".limit(limit + 1)")
    assert "InventoryMovement.company_id == company_id" in inspect.getsource(ledger_read._apply_filters)

    product_location_source = inspect.getsource(product_locations.list_product_locations)
    assert product_location_source.index("ProductLocation.company_id == access.company_id") < product_location_source.index(".limit(limit + 1)")
    assert product_location_source.index("access.location_filter(") < product_location_source.index(".limit(limit + 1)")


async def test_cp12_query_counts_percentiles_and_large_company_paths(pg):
    case = await _prepare_cp7(pg)
    extra_variants = await _seed_volume(pg, case)
    a = case.a

    async with pg.session() as db:
        scoped = a.ordinary.access(db)
        owner = a.owner.access(db)

        live_small, live_small_count = await _count_sql(
            pg,
            lambda: live_stock.get_warehouse_inventory(
                **_cursor_kwargs(a.location_id, db, scoped, limit=5)
            ),
        )
        live_large, live_large_count = await _count_sql(
            pg,
            lambda: live_stock.get_warehouse_inventory(
                **_cursor_kwargs(a.location_id, db, scoped, limit=100)
            ),
        )
        _, live_summary_count = await _count_sql(
            pg,
            lambda: live_stock.get_warehouse_inventory_summary(a.location_id, db, scoped),
        )

        batch_small, batch_small_count = await _count_sql(
            pg,
            lambda: batch_index.get_warehouse_inventory_batch_index_cursor(
                **_batch_kwargs(a.location_id, db, scoped, limit=5)
            ),
        )
        batch_large, batch_large_count = await _count_sql(
            pg,
            lambda: batch_index.get_warehouse_inventory_batch_index_cursor(
                **_batch_kwargs(a.location_id, db, scoped, limit=100)
            ),
        )
        _, batch_summary_count = await _count_sql(
            pg,
            lambda: batch_index.get_warehouse_inventory_batch_index_summary(
                location_id=a.location_id,
                expiry_warning_days=30,
                search=None,
                family_id=None,
                product_variant_id=None,
                db=db,
                access=scoped,
            ),
        )

        ledger_small, ledger_small_count = await _count_sql(
            pg,
            lambda: ledger.get_warehouse_ledger_cursor(
                location_id=a.location_id,
                cursor=None,
                limit=5,
                search=None,
                reference_type=None,
                reference_id=None,
                db=db,
                access=scoped,
            ),
        )
        ledger_large, ledger_large_count = await _count_sql(
            pg,
            lambda: ledger.get_warehouse_ledger_cursor(
                location_id=a.location_id,
                cursor=None,
                limit=50,
                search=None,
                reference_type=None,
                reference_id=None,
                db=db,
                access=scoped,
            ),
        )

        warehouses_small, warehouses_small_count = await _count_sql(
            pg,
            lambda: locations.manage_warehouse_locations(
                search=None,
                include_inactive=False,
                cursor=None,
                limit=5,
                db=db,
                access=owner,
            ),
        )
        warehouses_large, warehouses_large_count = await _count_sql(
            pg,
            lambda: locations.manage_warehouse_locations(
                search=None,
                include_inactive=False,
                cursor=None,
                limit=200,
                db=db,
                access=owner,
            ),
        )

        product_locations_small, product_locations_small_count = await _count_sql(
            pg,
            lambda: product_locations.list_product_locations(
                location_id=a.location_id,
                product_variant_id=None,
                cursor=None,
                limit=5,
                db=db,
                access=scoped,
            ),
        )
        product_locations_large, product_locations_large_count = await _count_sql(
            pg,
            lambda: product_locations.list_product_locations(
                location_id=a.location_id,
                product_variant_id=None,
                cursor=None,
                limit=200,
                db=db,
                access=scoped,
            ),
        )

        bulk_payload = inventory_stock_policy.BulkMinimumStockBase(
            location_id=a.location_id,
            scope="ALL",
            family_ids=[],
            product_variant_ids=[],
            minimum_quantity=Decimal("1"),
            apply_mode="ONLY_UNSET",
        )
        candidates, minimum_candidate_count = await _count_sql(
            pg,
            lambda: inventory_stock_policy._load_bulk_minimum_candidates(
                db,
                company_id=a.company_id,
                payload=bulk_payload,
            ),
        )

        started = await stocktake.start_unified_stocktake(
            StocktakeStartCommand(
                request_id=uuid4(),
                location_id=a.location_id,
                stocktake_type="FULL_COUNT",
                product_variant_id=None,
                batch_id=None,
                related_work_session_id=None,
            ),
            db=db,
            access=scoped,
            legacy_actor=a.ordinary.operational_driver,
        )
        session_id = int(started["session_id"])
        active_sessions, active_count = await _count_sql(
            pg,
            lambda: stocktake.list_active_stocktake_sessions(
                location_id=a.location_id,
                cursor=None,
                limit=200,
                db=db,
                access=scoped,
            ),
        )
        count_sheet, count_sheet_count = await _count_sql(
            pg,
            lambda: stocktake.get_stocktake_count_sheet(
                session_id,
                db=db,
                access=scoped,
                legacy_actor=a.ordinary.operational_driver,
            ),
        )

        assert len(live_large["items"]) > len(live_small["items"]) >= 5
        assert len(batch_large["items"]) > len(batch_small["items"]) >= 5
        assert len(ledger_large["items"]) > len(ledger_small["items"]) >= 5
        assert len(warehouses_large["items"]) > len(warehouses_small["items"]) >= 5
        assert len(product_locations_large["items"]) > len(product_locations_small["items"]) >= 5
        assert len(candidates) >= len(extra_variants)
        assert len(count_sheet) >= len(extra_variants)
        assert any(int(item["id"]) == session_id for item in active_sessions["items"])

        # Stable query-count evidence: larger pages must not add one SQL statement per returned row.
        assert live_large_count <= live_small_count + 2
        assert batch_large_count <= batch_small_count + 2
        assert ledger_large_count <= ledger_small_count + 3
        assert warehouses_large_count <= warehouses_small_count + 1
        assert product_locations_large_count <= product_locations_small_count + 1
        assert minimum_candidate_count <= 3
        assert active_count < 10
        assert count_sheet_count < 10

        counts = {
            "live_cursor_small": live_small_count,
            "live_cursor_large": live_large_count,
            "live_summary": live_summary_count,
            "batches_cursor_small": batch_small_count,
            "batches_cursor_large": batch_large_count,
            "batches_summary": batch_summary_count,
            "ledger_cursor_small": ledger_small_count,
            "ledger_cursor_large": ledger_large_count,
            "warehouse_list_small": warehouses_small_count,
            "warehouse_list_large": warehouses_large_count,
            "product_location_small": product_locations_small_count,
            "product_location_large": product_locations_large_count,
            "minimum_candidates": minimum_candidate_count,
            "stocktake_sessions": active_count,
            "stocktake_count_sheet": count_sheet_count,
        }
        print("CP12_QUERY_COUNTS", json.dumps(counts, sort_keys=True), flush=True)

        percentiles = {
            "live_stock_cursor": await _percentiles(
                lambda: live_stock.get_warehouse_inventory(
                    **_cursor_kwargs(a.location_id, db, scoped, limit=50)
                )
            ),
            "batches_cursor": await _percentiles(
                lambda: batch_index.get_warehouse_inventory_batch_index_cursor(
                    **_batch_kwargs(a.location_id, db, scoped, limit=50)
                )
            ),
            "ledger_cursor": await _percentiles(
                lambda: ledger.get_warehouse_ledger_cursor(
                    location_id=a.location_id,
                    cursor=None,
                    limit=50,
                    search=None,
                    reference_type=None,
                    reference_id=None,
                    db=db,
                    access=scoped,
                )
            ),
        }
        print("CP12_PERCENTILES", json.dumps(percentiles, sort_keys=True), flush=True)

        await _explain(
            db,
            "live_normal",
            "SELECT product_variant_id FROM inventory_live_stock_projection "
            "WHERE company_id=:company AND warehouse_location_id=:location "
            "ORDER BY variant_name, product_variant_id LIMIT 50",
            {"company": a.company_id, "location": a.location_id},
        )
        await _explain(
            db,
            "live_search",
            "SELECT product_variant_id FROM inventory_live_stock_projection "
            "WHERE company_id=:company AND warehouse_location_id=:location "
            "AND lower(variant_name) LIKE :pattern ORDER BY variant_name, product_variant_id LIMIT 50",
            {"company": a.company_id, "location": a.location_id, "pattern": "%cp12%"},
        )
        await _explain(
            db,
            "batches_normal",
            "SELECT pb.id FROM product_batches pb JOIN inventory_balances ib "
            "ON ib.company_id=pb.company_id AND ib.batch_id=pb.id "
            "WHERE pb.company_id=:company AND ib.location_id=:location "
            "ORDER BY pb.expiry_date NULLS LAST, pb.id LIMIT 50",
            {"company": a.company_id, "location": a.location_id},
        )
        await _explain(
            db,
            "batches_search_filter",
            "SELECT pb.id FROM product_batches pb JOIN product_variants pv "
            "ON pv.company_id=pb.company_id AND pv.id=pb.product_variant_id "
            "JOIN inventory_balances ib ON ib.company_id=pb.company_id AND ib.batch_id=pb.id "
            "WHERE pb.company_id=:company AND ib.location_id=:location "
            "AND lower(pv.name) LIKE :pattern AND pb.disposition='RELEASED' "
            "ORDER BY pb.expiry_date NULLS LAST, pb.id LIMIT 50",
            {"company": a.company_id, "location": a.location_id, "pattern": "%cp12%"},
        )
        await _explain(
            db,
            "ledger_default",
            "SELECT id FROM inventory_movements WHERE company_id=:company "
            "AND (source_location_id=:location OR destination_location_id=:location) "
            "ORDER BY created_at DESC, id DESC LIMIT 50",
            {"company": a.company_id, "location": a.location_id},
        )
        await _explain(
            db,
            "ledger_reference",
            "SELECT id FROM inventory_movements WHERE company_id=:company "
            "AND (source_location_id=:location OR destination_location_id=:location) "
            "AND reference_type='INBOUND' ORDER BY created_at DESC, id DESC LIMIT 50",
            {"company": a.company_id, "location": a.location_id},
        )
        await _explain(
            db,
            "stocktake_active",
            "SELECT id FROM stocktake_sessions WHERE company_id=:company AND location_id=:location "
            "AND status IN ('DRAFT','COUNTING','PENDING_REVIEW','RECOUNT_REQUIRED','APPROVED') "
            "ORDER BY id DESC LIMIT 50",
            {"company": a.company_id, "location": a.location_id},
        )
        await _explain(
            db,
            "stocktake_count_sheet",
            "SELECT id FROM stocktake_lines WHERE company_id=:company AND stocktake_session_id=:session "
            "ORDER BY id LIMIT 500",
            {"company": a.company_id, "session": session_id},
        )
