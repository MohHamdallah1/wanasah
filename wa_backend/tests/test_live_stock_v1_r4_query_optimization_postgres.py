"""Focused R4 production-query before/after on one immutable 50k fixture.

This is intentionally not the historical 140/240-case campaign. It measures
only the list/search query families changed by the R4 optimization and reuses
the accepted #661 fixture/profiling authority.
"""
from __future__ import annotations

import ast
import json
import os
from decimal import Decimal
from pathlib import Path
import statistics
import subprocess
from time import perf_counter

import pytest
from fastapi import HTTPException
from sqlalchemy import func, literal_column, select, text, tuple_
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api.warehouse import live_stock
from api.warehouse._shared import _encode_variant_cursor
from domains.live_stock_projection.service import rebuild_live_stock_company
from models import ProductVariant
from scripts import gate_r4_live_stock_perf_50k as r4
from scripts import profile_live_stock_explain as n1


pytestmark = pytest.mark.skipif(
    os.getenv("R4_QUERY_OPT_PG_GATE") != "1",
    reason="Explicit disposable PG16 R4 query-optimization gate only",
)

EVIDENCE = Path(os.environ.get(
    "R4_QUERY_OPT_EVIDENCE_DIR",
    "/tmp/r4-query-optimization-evidence",
))
BASE_SHA = os.environ["R4_OPT_BASE_SHA"]
SOURCE_DB = "wanasah_r2_perf_50k"
BEFORE_DB = "wanasah_r4_before"
AFTER_DB = "wanasah_r4_after"


def _compile_endpoint(source: str, label: str):
    node = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "get_warehouse_inventory"
    )
    node.decorator_list = []
    namespace = vars(live_stock).copy()
    exec(
        compile(
            ast.Module(body=[node], type_ignores=[]),
            f"<R4-query-opt-{label}>",
            "exec",
        ),
        namespace,
    )
    return namespace["get_warehouse_inventory"]


def _sources():
    base = subprocess.check_output(
        ["git", "show", f"{BASE_SHA}:wa_backend/api/warehouse/live_stock.py"],
        text=True,
    )
    current = Path(live_stock.__file__).read_text(encoding="utf-8")
    return base, current


def _function_ast(source: str, name: str) -> str:
    node = next(
        node for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )
    return ast.dump(node, include_attributes=False)


def _clone_url(env_name: str, database: str):
    return make_url(os.environ[env_name]).set(database=database)


async def _clone_fixture_databases():
    admin = create_async_engine(
        _clone_url("DATABASE_URL_MIGRATION", "postgres"),
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with admin.connect() as conn:
            for name in (BEFORE_DB, AFTER_DB):
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
                await conn.execute(text(
                    f'CREATE DATABASE "{name}" TEMPLATE "{SOURCE_DB}"'
                ))
    finally:
        await admin.dispose()


async def _runtime_engine(database: str):
    return create_async_engine(
        _clone_url("DATABASE_URL", database),
        poolclass=NullPool,
    )


async def _access(db, fixture, actor):
    key = (
        "owner_backoffice_user_id"
        if actor == "owner"
        else "ordinary_backoffice_user_id"
    )
    return (
        await n1.load_backoffice_access(
            db,
            company_id=fixture["company_id"],
            backoffice_user_id=fixture[key],
            location_id=fixture["warehouse_id"],
        )
    )[0]


def _kwargs(db, fixture, access, *, limit, search, cursor=None, **filters):
    values = n1.inventory_page_kwargs(
        db=db,
        access=access,
        location_id=fixture["warehouse_id"],
        limit=limit,
        cursor=cursor,
        search=search,
        only_alerts=False,
    )
    values.update(filters)
    return values


def _summary(values):
    ordered = sorted(values)
    return {
        "n": len(values),
        "min_ms": round(ordered[0], 3),
        "median_ms": round(statistics.median(ordered), 3),
        "max_ms": round(ordered[-1], 3),
    }


def _walk_plan(node):
    yield node
    for child in node.get("Plans", []) or []:
        yield from _walk_plan(child)


def _page_record(capture):
    rows = [
        row for row in capture
        if "inventory_page_candidates" in str(row["statement"])
    ]
    assert len(rows) == 1, [row["statement_one_line"] for row in capture]
    return rows[0]


def _plan_evidence(explained, products):
    top = explained["plan"]["Plan"]
    nodes = list(_walk_plan(top))
    relation_nodes = []
    for node in nodes:
        relation = node.get("Relation Name")
        if relation not in {
            "product_variants",
            "inventory_live_stock_projection",
        }:
            continue
        loops = int(node.get("Actual Loops", 0) or 0)
        rows = int(node.get("Actual Rows", 0) or 0)
        removed = int(node.get("Rows Removed by Filter", 0) or 0)
        relation_nodes.append({
            "node": node.get("Node Type"),
            "relation": relation,
            "index": node.get("Index Name"),
            "rows": rows,
            "loops": loops,
            "removed": removed,
            "work": (rows + removed) * loops,
            "catalog_correlated": loops >= products,
        })
    root_buffers = {
        key: int(top.get(key, 0) or 0)
        for key in (
            "Shared Hit Blocks",
            "Shared Read Blocks",
            "Temp Read Blocks",
            "Temp Written Blocks",
        )
    }
    return {
        "planning_ms": explained["plan"].get("Planning Time"),
        "execution_ms": explained["plan"].get("Execution Time"),
        "root_buffers": root_buffers,
        "relations": relation_nodes,
    }


async def _measure(
    engine,
    fixture,
    actor,
    function,
    *,
    limit,
    search,
    cursor=None,
    warmups=3,
    samples=5,
    **filters,
):
    async with r4.session(engine, fixture["company_id"]) as db:
        access = await _access(db, fixture, actor)
        values = _kwargs(
            db, fixture, access,
            limit=limit, search=search, cursor=cursor, **filters,
        )

        async def operation():
            return await function(**values)

        for _ in range(warmups):
            await operation()

        times = []
        payload = None
        for _ in range(samples):
            started = perf_counter()
            payload = await operation()
            times.append((perf_counter() - started) * 1000)

        captured_payload, captured_ms, capture = await n1.capture_endpoint_call(
            engine, operation
        )
        assert captured_payload == payload
        page = _page_record(capture)
        explained = await n1.explain_statement(
            db,
            str(page["statement"]),
            page["parameters"],
        )
        assert "plan" in explained
        r4.bounded_candidates(explained["plan"], limit)
        return {
            "payload": payload,
            "wall": _summary(times),
            "captured_ms": round(captured_ms, 3),
            "sql_count": len(capture),
            "page_driver_ms": round(float(page["duration_ms"]), 3),
            "plan": _plan_evidence(explained, fixture["products"]),
        }


async def _first_list_observation(
    engine,
    fixture,
    actor,
    function,
    *,
    limit,
    search,
):
    """First list call in a fresh database clone.

    Canonical identity and permission reads happen first in both clones.
    No prior Live Stock list call is made. PostgreSQL shared buffers for the
    cloned database are fresh; OS page cache on the hosted runner is not
    controllable and is reported as a limitation, not hidden.
    """
    async with r4.session(engine, fixture["company_id"]) as db:
        access = await _access(db, fixture, actor)
        values = _kwargs(
            db, fixture, access, limit=limit, search=search,
        )
        started = perf_counter()
        payload, _, capture = await n1.capture_endpoint_call(
            engine, lambda: function(**values)
        )
        elapsed = (perf_counter() - started) * 1000
        return {
            "wall_ms": round(elapsed, 3),
            "sql_count": len(capture),
            "returned": len(payload["items"]),
            "payload": payload,
        }


async def _independent_expected(engine, fixture, *, search, limit, cursor=None):
    async with r4.session(engine, fixture["company_id"]) as db:
        expression = func.lower(
            ProductVariant.name
            + literal_column("' '")
            + ProductVariant.sku
        )
        query = select(ProductVariant.name, ProductVariant.id).where(
            ProductVariant.company_id == fixture["company_id"]
        )
        for token in search.strip().lower().split():
            escaped = (
                token.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            query = query.where(
                expression.like(f"%{escaped}%", escape="\\")
            )
        if cursor is not None:
            query = query.where(
                tuple_(ProductVariant.name, ProductVariant.id)
                > tuple_(cursor[0], cursor[1])
            )
        rows = (
            await db.execute(
                query.order_by(
                    ProductVariant.name.asc(),
                    ProductVariant.id.asc(),
                ).limit(limit + 1)
            )
        ).all()
        return [tuple(row) for row in rows]


async def _deep_cursor(engine, fixture, actor, function):
    c = fixture["company_id"]
    async with r4.session(engine, c) as db:
        access = await _access(db, fixture, actor)
        anchor = (
            await db.execute(
                select(ProductVariant.name, ProductVariant.id)
                .where(ProductVariant.company_id == c)
                .order_by(ProductVariant.name, ProductVariant.id)
                .offset(24999)
                .limit(1)
            )
        ).one()
        scope = (
            f"inventory|{c}|{fixture['warehouse_id']}|common|"
            "all|0|000000|name_asc"
        )
        cursor = _encode_variant_cursor(
            kind="warehouse-inventory",
            variant_name=str(anchor.name),
            variant_id=int(anchor.id),
            scope=scope,
        )
        page = await function(
            **_kwargs(
                db, fixture, access,
                limit=50, search="Common", cursor=cursor,
            )
        )
        return {
            "anchor": (str(anchor.name), int(anchor.id)),
            "payload": page,
        }


async def _acceptance():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    fixture_path = EVIDENCE / "fixture.json"
    assert not fixture_path.exists(), "Refuse a second 50k seed in one acceptance"

    # One seed only. The two comparison databases are physical clones of this
    # exact migrated/statistics-bearing source database.
    await r4.seed.seed_fixture(fixture_path)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    await r4.enrich_fixture(fixture)
    fixture["products"] = r4.seed.PRODUCTS
    fixture["rare_search"] = "049999"
    fixture_path.write_text(json.dumps(fixture, indent=2), encoding="utf-8")

    base_source, current_source = _sources()
    base_function = _compile_endpoint(base_source, "exact-base")
    head_function = live_stock.get_warehouse_inventory

    # R3 intentionally changes only the Vehicle-custody portion of the
    # inventory summary. Keep every non-Vehicle query family byte-structural
    # against the accepted R4 base so this performance gate cannot hide drift.
    unchanged = (
        "get_warehouse_inventory_alert_summary",
        "get_warehouse_inventory_families",
        "get_warehouse_inventory_batches",
        "get_batch_stock_sources",
    )
    for name in unchanged:
        assert _function_ast(base_source, name) == _function_ast(
            current_source, name
        ), name

    summary_body = ast.unparse(
        next(
            node
            for node in ast.parse(current_source).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "get_warehouse_inventory_summary"
        )
    )
    assert "_readable_vehicle_locations_subquery" in summary_body
    assert "InventoryBalance.on_hand_quantity > 0" in summary_body
    assert "_latest_readable_vehicle_sources_subquery" not in summary_body
    assert "DispatchRoute" not in summary_body
    assert "has_vehicle_presence" not in summary_body

    await _clone_fixture_databases()
    before = await _runtime_engine(BEFORE_DB)
    after = await _runtime_engine(AFTER_DB)
    source = create_async_engine(
        r4.seed.checked_url("DATABASE_URL"),
        poolclass=NullPool,
    )

    report = {
        "base_sha": BASE_SHA,
        "head_sha": os.environ["R4_OPT_HEAD_SHA"],
        "fixture": {
            "products": fixture["products"],
            "company_id": fixture["company_id"],
            "warehouse_id": fixture["warehouse_id"],
            "filter_rows": fixture["filter_rows"],
        },
        "measurement": {
            "seed_count": 1,
            "comparison_databases": [BEFORE_DB, AFTER_DB],
            "cold_definition": (
                "first Live Stock list call after creating each physical database "
                "clone; identity/permission reads precede both equally"
            ),
            "cold_limit": (
                "PostgreSQL shared-buffer residency is clone-local; hosted-runner "
                "OS page cache cannot be controlled, so this is not production cold-cache"
            ),
            "warmup_calls_per_case": 3,
            "warm_samples_per_case": 5,
            "latency_claim": "descriptive only; structural EXPLAIN evidence is the gate",
        },
        "cold": {},
        "cases": [],
        "deep_cursor": [],
    }

    try:
        for engine in (before, after):
            async with r4.session(engine, fixture["company_id"]) as db:
                identity = (
                    await db.execute(text(
                        "SELECT current_user, rolsuper, rolbypassrls "
                        "FROM pg_roles WHERE rolname=current_user"
                    ))
                ).one()
                assert tuple(identity) == ("wanasah_app", False, False)
                version = str(await db.scalar(text("SHOW server_version")))
                assert version.startswith("16.")
                for table in (
                    "product_variants",
                    "inventory_balances",
                    "inventory_live_stock_projection",
                ):
                    flags = (
                        await db.execute(text(
                            "SELECT relrowsecurity, relforcerowsecurity "
                            "FROM pg_class WHERE oid=to_regclass(:t)"
                        ), {"t": table})
                    ).one()
                    assert tuple(flags) == (True, True), table

                # Projection v2 intentionally rejects stale v1 persisted state.
                # Rebuild each physical clone before any timed/list observation
                # so before/after compare identical READY projection data.
                await rebuild_live_stock_company(
                    db,
                    company_id=int(fixture["company_id"]),
                )
                await db.commit()

        # Controlled first-list observation: identical cloned data and owner scope.
        report["cold"]["before"] = await _first_list_observation(
            before, fixture, "owner", base_function,
            limit=50, search="Common",
        )
        report["cold"]["after"] = await _first_list_observation(
            after, fixture, "owner", head_function,
            limit=50, search="Common",
        )
        assert report["cold"]["before"]["payload"] == report["cold"]["after"]["payload"]
        report["cold"]["before"].pop("payload")
        report["cold"]["after"].pop("payload")

        cases = [
            ("owner", "broad_1", 1, "Common", {}),
            ("owner", "broad_50", 50, "Common", {}),
            ("owner", "short_200", 200, "Co", {}),
            ("owner", "rare_1", 1, fixture["rare_search"], {}),
            ("restricted", "broad_1", 1, "Common", {}),
            ("restricted", "broad_50", 50, "Common", {}),
            ("restricted", "short_200", 200, "Co", {}),
            ("restricted", "rare_1", 1, fixture["rare_search"], {}),
            (
                "owner", "combined_50", 50, "Common",
                {
                    "stock_state": "low_stock",
                    "has_reserved": True,
                    "has_unavailable": True,
                    "has_damaged": True,
                },
            ),
            (
                "restricted", "combined_50", 50, "Common",
                {
                    "stock_state": "low_stock",
                    "has_reserved": True,
                    "has_unavailable": True,
                    "has_damaged": True,
                },
            ),
            ("owner", "sellable_50", 50, None, {"stock_state": "sellable"}),
            ("restricted", "sellable_50", 50, None, {"stock_state": "sellable"}),
            ("owner", "on_hand_50", 50, None, {"stock_state": "on_hand"}),
            ("restricted", "on_hand_50", 50, None, {"stock_state": "on_hand"}),
            ("owner", "empty_vehicle", 50, None, {"has_vehicle": True}),
            ("restricted", "empty_vehicle", 50, None, {"has_vehicle": True}),
            ("owner", "empty_recalled", 50, None, {"has_recalled": True}),
            ("restricted", "empty_recalled", 50, None, {"has_recalled": True}),
            ("owner", "out_of_stock_empty", 50, None, {"stock_state": "out_of_stock"}),
            ("restricted", "out_of_stock_empty", 50, None, {"stock_state": "out_of_stock"}),
            ("owner", "minimum_unset_50", 50, None, {"minimum_unset": True}),
            ("restricted", "minimum_unset_50", 50, None, {"minimum_unset": True}),
        ]

        for actor, name, limit, search, filters in cases:
            base_result = await _measure(
                before, fixture, actor, base_function,
                limit=limit, search=search, **filters,
            )
            head_result = await _measure(
                after, fixture, actor, head_function,
                limit=limit, search=search, **filters,
            )
            assert head_result["payload"] == base_result["payload"], (
                actor, name
            )
            assert head_result["sql_count"] == base_result["sql_count"], (
                actor, name, base_result["sql_count"], head_result["sql_count"]
            )

            if search and name not in {"combined_50"}:
                expected = await _independent_expected(
                    source, fixture, search=search, limit=limit
                )
                actual = [
                    (row["name"], row["id"])
                    for row in head_result["payload"]["items"]
                ]
                assert actual == expected[:limit], (actor, name)
                assert head_result["payload"]["has_more"] == (
                    len(expected) > limit
                )

            if name == "combined_50":
                assert all(
                    row["is_low_stock"]
                    and Decimal(row["reserved_quantity"]) > 0
                    and Decimal(row["damaged_quantity"]) > 0
                    for row in head_result["payload"]["items"]
                )
            if name in {"empty_vehicle", "empty_recalled", "out_of_stock_empty"}:
                assert head_result["payload"]["items"] == []

            # Positive stock predicates guarantee a projection row. HEAD must
            # not retain the old catalog-correlated ProductVariant/projection
            # lookup shape for either populated or empty positive filters.
            if name in {
                "sellable_50",
                "on_hand_50",
                "empty_vehicle",
                "empty_recalled",
            }:
                new_correlated = [
                    row for row in head_result["plan"]["relations"]
                    if row["catalog_correlated"]
                ]
                assert not new_correlated, (
                    actor, name, head_result["plan"]
                )

            # These exact-base empty filters are independently known from #661
            # to suffer the catalog-correlated projection lookup. Require the
            # focused comparison to reproduce that cause before calling it fixed.
            if (
                name == "empty_recalled"
                or (name == "empty_vehicle" and actor == "owner")
            ):
                old_correlated = [
                    row for row in base_result["plan"]["relations"]
                    if row["catalog_correlated"]
                ]
                assert old_correlated, (
                    actor, name, base_result["plan"]
                )

            # The measured defect was a correlated point lookup once per search
            # member. Broad/short HEAD plans must eliminate that 50k-loop shape.
            if name in {"broad_50", "short_200"}:
                old_correlated = [
                    row for row in base_result["plan"]["relations"]
                    if row["catalog_correlated"]
                ]
                assert old_correlated, (actor, name, base_result["plan"])
                new_correlated = [
                    row for row in head_result["plan"]["relations"]
                    if row["catalog_correlated"]
                ]
                assert not new_correlated, (actor, name, head_result["plan"])
            elif name == "broad_1":
                # #661 measured this defect as singleton-probe overhead rather
                # than a 50k correlated-loop shape. Keep the structural gate
                # honest: HEAD must not introduce catalog-correlated lookup,
                # while latency/buffers stay descriptive before/after evidence.
                assert not [
                    row for row in head_result["plan"]["relations"]
                    if row["catalog_correlated"]
                ], (actor, name, head_result["plan"])

            # Preserve #645's rare-search point-access result: no catalog-sized
            # ProductVariant work and a tenant/id point index remains visible.
            if name == "rare_1":
                pv = [
                    row for row in head_result["plan"]["relations"]
                    if row["relation"] == "product_variants"
                ]
                assert pv
                assert max(row["work"] for row in pv) < fixture["products"]
                assert any(
                    row["index"] in {
                        "uq_product_variants_company_id",
                        "pk_product_variants",
                    }
                    for row in pv
                ), pv

            report["cases"].append({
                "actor": actor,
                "name": name,
                "limit": limit,
                "search": search,
                "filters": filters,
                "before": {
                    key: value
                    for key, value in base_result.items()
                    if key != "payload"
                },
                "after": {
                    key: value
                    for key, value in head_result.items()
                    if key != "payload"
                },
                "payload_equal": True,
            })
            (EVIDENCE / "report.json").write_text(
                json.dumps(report, indent=2, default=str),
                encoding="utf-8",
            )

        # Deep broad-search cursor continuation through the changed branch.
        for actor in ("owner", "restricted"):
            base_deep = await _deep_cursor(
                before, fixture, actor, base_function
            )
            head_deep = await _deep_cursor(
                after, fixture, actor, head_function
            )
            assert head_deep == base_deep
            expected = await _independent_expected(
                source,
                fixture,
                search="Common",
                limit=50,
                cursor=head_deep["anchor"],
            )
            actual = [
                (row["name"], row["id"])
                for row in head_deep["payload"]["items"]
            ]
            assert actual == expected[:50]
            assert len(actual) == len(set(actual))
            report["deep_cursor"].append({
                "actor": actor,
                "anchor": head_deep["anchor"],
                "returned": len(actual),
                "has_more": head_deep["payload"]["has_more"],
                "payload_equal": True,
            })

        report["status"] = "PASS"
        print(
            "R4_QUERY_OPT_PASS "
            + json.dumps({
                "cases": len(report["cases"]),
                "deep_cursor_checks": len(report["deep_cursor"]),
                "cold": report["cold"],
            }),
            flush=True,
        )
    finally:
        (EVIDENCE / "report.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )
        await before.dispose()
        await after.dispose()
        await source.dispose()


def test_r4_changed_query_families_one_seed_before_after():
    import asyncio
    asyncio.run(_acceptance())
