"""Actual emitted SQL plans/counts on synthetic stock through the real engine."""
from __future__ import annotations

import ast
import json
import subprocess
from contextlib import asynccontextmanager
import os
from pathlib import Path
from functools import lru_cache
from time import perf_counter

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.warehouse import live_stock
from api.warehouse._shared import _encode_variant_cursor
from domains.inventory_costing.service import build_purchase_cost_input
from domains.live_stock_projection.service import (
    apply_live_stock_active_variant_delta, refresh_live_stock_keys,
)
from models import DispatchRoute, InventoryStockPolicy, ProductBatch, ProductVariant, utc_now
from services import apply_inventory_movements_batch
from tests.test_inbound_no_lot_frozen_postgres import pg
from tests.live_stock_r1_support import D, cursor_kwargs, emit, r1case

pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_R1_PG_GATE") != "1",
                       reason="Explicit disposable R1 PostgreSQL gate only"),
    pytest.mark.asyncio(loop_scope="function"),
]


async def seed_stock(case, target):
    """Bounded fixture batches; no direct balance, cost-state or projection writes."""
    async with case.pg.session() as db:
        original = await db.get(ProductVariant, case.tenant.variant_id)
        product_id = original.product_id
    remaining = target - 1
    offset = 0
    while remaining:
        size = min(1000, remaining)
        async with case.pg.session() as db:
            variants = [ProductVariant(
                company_id=case.tenant.company_id, product_id=product_id,
                name=f"Common R1 {offset+i:06d}", sku=f"R1-{offset+i:06d}",
                base_uom_id=case.tenant.uom_id, quantity_scale=6,
                quantity_step=D("0.000001"), lot_control_mode="OPTIONAL",
                expiry_control_mode="OPTIONAL", lifecycle_status="ACTIVE",
                published_at=utc_now(),
            ) for i in range(size)]
            db.add_all(variants)
            await db.flush()
            batches = [ProductBatch(
                company_id=case.tenant.company_id, product_variant_id=v.id,
                batch_number=f"R1-PERF-{offset+i}",
            ) for i, v in enumerate(variants)]
            db.add_all(batches)
            await db.flush()
            await apply_live_stock_active_variant_delta(
                db, company_id=case.tenant.company_id, delta=size)
            await apply_inventory_movements_batch(
                db, company_id=case.tenant.company_id,
                performed_by=case.tenant.owner.driver_id,
                movements=[dict(
                    product_variant_id=v.id, batch_id=b.id, quantity=D("1"),
                    movement_kind="PHYSICAL", reference_type="INBOUND_SUPPLIER",
                    reference_id=f"R1-PERF-{offset+i}",
                    idempotency_key=f"R1-PERF-{offset+i}",
                    source_location_id=None, source_stock_status=None,
                    destination_location_id=case.warehouse_id,
                    destination_stock_status="AVAILABLE",
                    inventory_cost_input=build_purchase_cost_input(
                        input_uom_id=case.tenant.uom_id, input_quantity=D("1"),
                        input_unit_cost=D("1"), base_quantity=D("1")),
                ) for i, (v, b) in enumerate(zip(variants, batches))],
            )
            if offset == 0:
                db.add_all([InventoryStockPolicy(
                    company_id=case.tenant.company_id, location_id=case.warehouse_id,
                    product_variant_id=v.id, minimum_quantity=D("2"),
                ) for v in variants[:100]])
                await db.flush()
                await refresh_live_stock_keys(
                    db, company_id=case.tenant.company_id,
                    keys=[(case.warehouse_id, v.id) for v in variants[:100]])
            await db.commit()
        offset += size
        remaining -= size
    async with case.pg.session() as db:
        count = await db.scalar(select(func.count()).select_from(ProductVariant).where(
            ProductVariant.company_id == case.tenant.company_id))
        assert count == target
    return product_id


@lru_cache(maxsize=1)
def baseline_list():
    """Compile only the immutable accepted-main function; no router registration."""
    source = subprocess.check_output([
        "git", "show", "c0fe0187dbf326e9852e789fd2c38262ab648052:wa_backend/api/warehouse/live_stock.py",
    ], text=True)
    tree = ast.parse(source)
    node = next(n for n in tree.body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_warehouse_inventory")
    node.decorator_list = []
    historical_helpers = [
        part for part in tree.body
        if isinstance(part, (ast.FunctionDef, ast.AsyncFunctionDef))
        and part.name == "_latest_readable_vehicle_sources_subquery"
    ]
    assert len(historical_helpers) == 1
    namespace = vars(live_stock).copy()
    # The accepted-main comparison still owns latest-Route attribution. Compile
    # that helper and its historical model dependency only inside this test
    # namespace; production R3 remains Route-independent.
    namespace["DispatchRoute"] = DispatchRoute
    exec(
        compile(
            ast.Module(body=[*historical_helpers, node], type_ignores=[]),
            "<accepted-main-list>",
            "exec",
        ),
        namespace,
    )
    return namespace["get_warehouse_inventory"]


@asynccontextmanager
async def comparison_session(case, strategy):
    if strategy == "single-statement":
        async with case.pg.session() as db:
            yield db
    else:
        # Test-only fresh connection; never changes engine/global isolation.
        async with case.pg.runtime_engine.connect() as raw:
            connection = await raw.execution_options(isolation_level="REPEATABLE READ")
            async with AsyncSession(bind=connection, expire_on_commit=False) as db:
                await db.execute(text("SELECT set_config('app.current_tenant',:tenant,true)"),
                                 {"tenant": str(case.tenant.company_id)})
                await db.execute(text("SET LOCAL statement_timeout='15000ms'"))
                yield db


async def measured_page(case, *, owner, filters, strategy="single-statement"):
    records = []
    starts = []

    def before(_conn, _cursor, statement, parameters, _context, _many):
        starts.append(perf_counter())
        records.append({"sql": statement, "parameters": parameters})

    def after(*_args):
        records[-1]["wall_ms"] = (perf_counter() - starts.pop()) * 1000

    async with comparison_session(case, strategy) as db:
        kwargs = cursor_kwargs(case, db, **filters)
        if owner:
            kwargs["access"] = case.tenant.owner.access(db)
        function = live_stock.get_warehouse_inventory if strategy == "single-statement" else baseline_list()
        event.listen(case.pg.runtime_engine.sync_engine, "before_cursor_execute", before)
        event.listen(case.pg.runtime_engine.sync_engine, "after_cursor_execute", after)
        try:
            started = perf_counter()
            page = await function(**kwargs)
            elapsed = (perf_counter() - started) * 1000
        finally:
            event.remove(case.pg.runtime_engine.sync_engine, "before_cursor_execute", before)
            event.remove(case.pg.runtime_engine.sync_engine, "after_cursor_execute", after)
        combined = [r for r in records if "inventory_page_candidates" in r["sql"]]
        if strategy == "single-statement":
            assert len(combined) == 1
            assert len(records) == 4
        else:
            assert not combined
            assert len(records) == (5 if owner else 6)
        assert len(page["items"]) <= filters["limit"]
        plans = []
        connection = await db.connection()
        for record in records:
            result = await connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + record["sql"],
                record["parameters"])
            raw = result.scalar_one()
            document = raw if isinstance(raw, list) else json.loads(raw)
            plans.append({**record, "plan": document[0]})
        plan = plans[-1]["plan"]
        return page, {
            "strategy": strategy, "owner": owner, "filters": filters, "sql_count": len(records),
            "returned": len(page["items"]), "route_wall_ms": elapsed,
            "page_planning_ms": plan["Planning Time"],
            "page_execution_ms": plan["Execution Time"],
            "total_sql_execution_ms": sum(r["plan"]["Execution Time"] for r in plans),
            "total_sql_planning_ms": sum(r["plan"]["Planning Time"] for r in plans),
            "statements": plans,
        }


async def test_actual_sql_page_bounds_filters_and_plans(r1case):
    case = r1case
    target = int(os.environ.get("WANASAH_R1_SCALE_PRODUCTS", "50000"))
    assert target >= 201
    family = await seed_stock(case, target)
    output = Path("r1-query-plans-" + case.pg.method + ".json")
    evidence = []
    # Persist even if an acceptance assertion below fails.
    try:
        for owner in (True, False):
            for size in (1, 50, 200):
                for filters in (
                    {}, {"stock_state": "sellable"}, {"stock_state": "on_hand"},
                    {"stock_state": "out_of_stock"}, {"stock_state": "low_stock"},
                    {"has_vehicle": True}, {"minimum_unset": True},
                    {"family_id": family}, {"search": "Common"},
                    {"search": "000001"}, {"search": "Co"},
                    {"sort": "name_desc"}, {"has_reserved": True},
                    {"has_unavailable": True}, {"has_damaged": True},
                ):
                    query = {"limit": size, **filters}
                    page, record = await measured_page(case, owner=owner, filters=query)
                    evidence.append(record)
                    if not filters:
                        assert len(page["items"]) == size
                        assert page["has_more"] and page["next_cursor"]
                        next_page, next_record = await measured_page(
                            case, owner=owner,
                            filters={"limit": size, "cursor": page["next_cursor"]})
                        evidence.append(next_record)
                        assert len(next_page["items"]) == size
                        assert {r["id"] for r in page["items"]}.isdisjoint(
                            r["id"] for r in next_page["items"])
                    if filters.get("stock_state") == "sellable":
                        assert all(D(row["available_for_sale_quantity"]) > 0
                                   for row in page["items"])
                    if filters.get("stock_state") == "out_of_stock":
                        assert page["items"] == []
                    if filters.get("sort") == "name_desc":
                        keys = [(r["name"], r["id"]) for r in page["items"]]
                        assert keys == sorted(keys, reverse=True)
                    emit("sql_plan", products=target, **{
                        k: v for k, v in record.items() if k != "statements"})
            # Exercise both new server-owned rank sorts with real PG16/RLS,
            # materialized candidate snapshot and exact keyset continuation.
            for priority_sort in ("stock_first", "low_stock_first"):
                page, record = await measured_page(
                    case, owner=owner,
                    filters={"limit": 200, "sort": priority_sort},
                )
                evidence.append(record)
                assert len(page["items"]) == 200
                rank = (
                    (lambda item: 0 if item["is_low_stock"] else 1)
                    if priority_sort == "low_stock_first"
                    else (lambda item: 0 if D(item["on_hand_quantity"]) > 0 else 1)
                )
                keys = [(rank(row), row["name"], row["id"]) for row in page["items"]]
                assert keys == sorted(keys), (priority_sort, "first-page order")
                assert page["next_cursor"] and page["has_more"]
                continuation, next_record = await measured_page(
                    case, owner=owner,
                    filters={
                        "limit": 200, "sort": priority_sort,
                        "cursor": page["next_cursor"],
                    },
                )
                evidence.append(next_record)
                next_keys = [
                    (rank(row), row["name"], row["id"])
                    for row in continuation["items"]
                ]
                assert next_keys == sorted(next_keys), (priority_sort, "continuation order")
                assert next_keys and keys[-1] < next_keys[0], (
                    priority_sort, "keyset boundary", keys[-1], next_keys[0],
                )
                assert {row["id"] for row in page["items"]}.isdisjoint(
                    {row["id"] for row in continuation["items"]}
                )
            # Compare the narrow transaction-local alternative using the real old SQL.
            for size in (1, 50, 200):
                for selected in ({}, {"stock_state": "sellable"},
                                 {"search": "Common"}, {"search": "000001"},
                                 {"has_vehicle": True}):
                    page, record = await measured_page(
                        case, owner=owner, filters={"limit": size, **selected},
                        strategy="repeatable-read-baseline")
                    evidence.append(record)
                    if not selected:
                        assert len(page["items"]) == size
                    if selected.get("stock_state") == "sellable":
                        assert all(D(r["available_for_sale_quantity"]) > 0 for r in page["items"])
                    emit("sql_plan", products=target, **{
                        k: v for k, v in record.items() if k != "statements"})
            async with case.pg.session() as db:
                key = (await db.execute(select(ProductVariant.name, ProductVariant.id)
                    .where(ProductVariant.company_id == case.tenant.company_id)
                    .order_by(ProductVariant.name, ProductVariant.id)
                    .offset(target // 2).limit(1))).one()
            scope = f"inventory|{case.tenant.company_id}|{case.warehouse_id}||all|0|000000|name_asc"
            cursor = _encode_variant_cursor(kind="warehouse-inventory",
                variant_name=key.name, variant_id=key.id, scope=scope)
            page, record = await measured_page(
                case, owner=owner, filters={"limit": 50, "cursor": cursor})
            evidence.append(record)
            assert len(page["items"]) == 50
    finally:
        output.write_text(json.dumps({
            "method": case.pg.method, "products": target, "evidence": evidence,
        }, default=str), encoding="utf-8")
