"""Real bearer ASGI/SQL measurements; production dependencies and endpoint contracts."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import tracemalloc
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy import func, select

from api.warehouse import live_stock
from api.warehouse._shared import _encode_batch_cursor, _encode_variant_cursor, _escape_like
from database import engine as http_engine
from main import app
from models import Product, ProductBatch, ProductVariant
from scripts import gate_r4_live_stock_perf_50k as r4
from scripts.live_stock_r4_final_metrics import (
    assert_bounded_plan, assert_constant_counts, distribution, plan_evidence, rss_high_water,
)
from tests.live_stock_r4_search_support import compile_endpoint

LIST = "/warehouse/inventory/cursor"


def _compile_runtime(source: str, label: str):
    """Compile the endpoint plus owned candidate helper from one source snapshot."""
    tree = ast.parse(source)
    wanted = {"_build_visible_inventory_stmt", "get_warehouse_inventory"}
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in wanted
    ]
    assert {node.name for node in nodes} == wanted
    for node in nodes:
        if isinstance(node, ast.AsyncFunctionDef):
            node.decorator_list = []
    namespace = vars(live_stock).copy()
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), f"<R4-{label}>", "exec"),
        namespace,
    )
    return namespace["get_warehouse_inventory"]


def implementations():
    """Compile exact PR base and execute HEAD against the same physical fixture.

    The original #661 gate required byte-identical runtime because it was
    evidence-only. This closure gate intentionally supports a measured SQL
    optimization: base is immutable evidence, HEAD is the candidate. Payload,
    cursor, authorization and physical quantity parity are still mandatory.
    """
    import subprocess
    base = os.environ["R4_FINAL_BASE_SHA"]
    frozen = subprocess.check_output(
        ["git", "show", base + ":wa_backend/api/warehouse/live_stock.py"],
        text=True,
    )
    current = Path(live_stock.__file__).read_text()
    condition = "if search_variant_ids is not None and limit == 1 and not use_alert_fast_path:"
    controls = {}
    if frozen.count(condition) == 1:
        control = frozen.replace(
            condition,
            "if False and search_variant_ids is not None and limit == 1 and not use_alert_fast_path:",
        )
        controls["probe_disabled_control"] = compile_endpoint(
            control, "unsafe-probe-disabled-control"
        )
    return ({
        "accepted_main": _compile_runtime(frozen, "exact-pr-base"),
        **controls,
        "implementation_head": live_stock.get_warehouse_inventory,
    }, {
        "base": hashlib.sha256(frozen.encode()).hexdigest(),
        "head": hashlib.sha256(current.encode()).hexdigest(),
        "changed": frozen != current,
    })


@contextmanager
def route_implementation(function):
    route = next(r for r in app.routes if getattr(r, "path", None) == LIST
                 and "GET" in (getattr(r, "methods", None) or ()))
    original = route.dependant.call
    # FastAPI now passes the optional "view" keyword to the current endpoint.
    # The historical endpoint never accepted it: compare the same catalog
    # behavior, and fail rather than reinterpret a warehouse-only request.
    import inspect
    if "view" not in inspect.signature(function).parameters:
        async def baseline_call(**kwargs):
            assert kwargs.get("view") == "catalog", "Historical baseline supports catalog view only"
            return await function(**{key: val for key, val in kwargs.items() if key != "view"})
        measured_call = baseline_call
    else:
        measured_call = function
    # Only the benchmark control's list callable changes. All real middleware,
    # response schemas, persisted bearer/session/capability/RLS dependencies stay.
    route.dependant.call = measured_call
    try:
        yield
    finally:
        route.dependant.call = original


async def login(identities):
    assert not app.dependency_overrides
    tokens = {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                base_url="http://r4-final.test") as client:
        for actor, credentials in identities.items():
            response = await client.post("/login", json=credentials)
            assert response.status_code == 200, response.text
            assert response.json().get("token")
            tokens[actor] = response.json()["token"]
    return tokens


async def specifications(engine, fixture):
    c, w, size = fixture["company_id"], fixture["warehouse_id"], fixture["products"]
    specs = []
    async with r4.session(engine, c) as db:
        anchor = (await db.execute(select(ProductVariant.name, ProductVariant.id).where(
            ProductVariant.company_id == c).order_by(ProductVariant.name, ProductVariant.id)
            .offset(fixture["deep_ordinal"] - 1).limit(1))).one()
        deep = _encode_variant_cursor(kind="warehouse-inventory", variant_name=anchor.name,
            variant_id=anchor.id, scope=f"inventory|{c}|{w}||all|0|000000|name_asc")
        batch_anchor = await db.scalar(select(ProductBatch.id).where(
            ProductBatch.company_id == c, ProductBatch.product_variant_id == fixture["heavy_variant_id"])
            .order_by(ProductBatch.id).offset(199).limit(1))
        batch_deep = _encode_batch_cursor(expiry_date=None, batch_id=batch_anchor,
            scope=f"company={c}|location={w}|variant={fixture['heavy_variant_id']}")
        family_anchor = (await db.execute(select(Product.name, Product.id).where(Product.company_id == c)
            .order_by(Product.name, Product.id).offset(fixture["families"] // 2 - 1).limit(1))).one()
        family_deep = _encode_variant_cursor(kind="warehouse-inventory-families",
            variant_name=family_anchor.name, variant_id=family_anchor.id,
            scope=f"warehouse-inventory-families|{c}|{w}|")
    for actor in ("owner", "restricted"):
        def add(kind, name, path, params, *, limit=None, representative=False, anchor=None):
            specs.append(dict(actor=actor, kind=kind, name=name, path=path,
                              params=params, limit=limit, representative=representative, anchor=anchor))
        for limit in (1, 50, 200):
            cases = [
                ("initial", {}), ("deep", {"cursor": deep}),
                ("broad", {"search": "Common"}), ("rare", {"search": fixture["rare_search"]}),
                ("short", {"search": "Co"}), ("low_stock", {"stock_state": "low_stock"}),
                ("combined", {"search": "Common", "stock_state": "low_stock",
                              "has_reserved": True, "has_unavailable": True, "has_damaged": True}),
                ("family_filter", {"family_id": fixture["family_id"]}),
            ]
            for name, filters in cases:
                representative = (name, limit) in {
                    ("initial", 50), ("broad", 1), ("broad", 50), ("rare", 1),
                    ("short", 200), ("combined", 50)}
                add("list", name, LIST, {"location_id": w, "limit": limit, **filters},
                    limit=limit, representative=representative,
                    anchor=list(anchor) if name == "deep" else None)
        for name, filters in (
            ("sellable", {"stock_state": "sellable"}), ("on_hand", {"stock_state": "on_hand"}),
            ("out_of_stock", {"stock_state": "out_of_stock"}), ("minimum_unset", {"minimum_unset": True}),
            ("vehicle_empty", {"has_vehicle": True}), ("recalled_empty", {"has_recalled": True}),
            ("alerts_only", {"only_alerts": True}),
        ):
            add("list", name, LIST, {"location_id": w, "limit": 50, **filters}, limit=50)
        add("summary", "summary", "/warehouse/inventory/summary", {"location_id": w}, representative=True)
        add("alerts", "alerts", "/warehouse/inventory/alerts/summary", {"location_id": w})
        for limit in (1, 50, 100):
            for name, filters in (
                ("initial", {}), ("deep", {"cursor": family_deep}),
                ("common", {"search": "Family"}), ("rare", {"search": f"{fixture['families']-2:04d}"}),
                ("short", {"search": "R4"}),
            ):
                add("families", name, "/warehouse/inventory/families",
                    {"location_id": w, "limit": limit, **filters}, limit=limit,
                    representative=(name, limit) == ("initial", 50),
                    anchor=list(family_anchor) if name == "deep" else None)
        for limit in (1, 50, 200):
            for name, cursor in (("initial", None), ("deep", batch_deep)):
                add("batches", name, f"/warehouse/inventory/{fixture['heavy_variant_id']}/batches",
                    {"location_id": w, "limit": limit, **({"cursor": cursor} if cursor else {})},
                    limit=limit, representative=(name, limit) == ("initial", 200),
                    anchor=batch_anchor if cursor else None)
        for name, variant, batch in (
            ("fanout", fixture["first_variant_id"], fixture["source_batch_id"]),
            ("single", fixture["heavy_variant_id"], fixture["heavy_batch_id"]),
        ):
            add("stock_sources", name, f"/warehouse/batches/{batch}/stock-sources", {},
                representative=name == "fanout")
            add("warehouse_source", name, f"/warehouse/inventory/{variant}/batches/{batch}/source",
                {"location_id": w}, representative=name == "fanout")
    return specs


async def expected_keys(engine, fixture, spec):
    kind, p, c = spec["kind"], spec["params"], fixture["company_id"]
    if kind not in {"list", "families", "batches"}:
        return None
    async with r4.session(engine, c) as db:
        if kind == "list":
            q = select(ProductVariant.name, ProductVariant.id).where(ProductVariant.company_id == c)
            expression = func.lower(ProductVariant.name + " " + ProductVariant.sku)
            for token in (p.get("search") or "").lower().split():
                q = q.where(expression.like("%" + _escape_like(token) + "%", escape="\\"))
            if p.get("family_id"):
                q = q.where(ProductVariant.product_id == p["family_id"])
            if p.get("stock_state") == "low_stock" or p.get("only_alerts") or p.get("has_reserved"):
                q = q.where(ProductVariant.sku <= f"R2-50K-{fixture['filter_rows']:06d}")
            if p.get("minimum_unset"):
                q = q.where(ProductVariant.sku > f"R2-50K-{fixture['filter_rows']:06d}")
            if p.get("stock_state") == "out_of_stock" or p.get("has_vehicle") or p.get("has_recalled"):
                from sqlalchemy import false
                q = q.where(false())
            if spec["anchor"]:
                from sqlalchemy import tuple_
                q = q.where(tuple_(ProductVariant.name, ProductVariant.id) > tuple_(*spec["anchor"]))
            rows = (await db.execute(q.order_by(ProductVariant.name, ProductVariant.id).limit(spec["limit"] + 1))).all()
        elif kind == "families":
            q = select(Product.name, Product.id).where(Product.company_id == c)
            from sqlalchemy import or_, tuple_
            for token in (p.get("search") or "").lower().split():
                pattern = "%" + _escape_like(token) + "%"
                q = q.where(or_(func.lower(Product.name).like(pattern, escape="\\"),
                                func.lower(Product.code).like(pattern, escape="\\")))
            if spec["anchor"]:
                q = q.where(tuple_(Product.name, Product.id) > tuple_(*spec["anchor"]))
            rows = (await db.execute(q.order_by(Product.name, Product.id).limit(spec["limit"] + 1))).all()
        else:
            q = select(ProductBatch.id).where(ProductBatch.company_id == c,
                ProductBatch.product_variant_id == fixture["heavy_variant_id"])
            if spec["anchor"]:
                q = q.where(ProductBatch.id > spec["anchor"])
            rows = (await db.execute(q.order_by(ProductBatch.id).limit(spec["limit"] + 1))).all()
        return [tuple(r) for r in rows]


def verify(payload, fixture, spec, expected):
    kind, limit = spec["kind"], spec["limit"]
    if expected is not None:
        rows = payload["batches"] if kind == "batches" else payload["items"]
        keys = [(r["batch_id"],) if kind == "batches" else (r["name"], r["id"]) for r in rows]
        assert keys == expected[:limit], (spec, keys, expected)
        assert len(keys) == len(set(keys))
        assert payload["has_more"] == (len(expected) > limit)
        assert bool(payload["next_cursor"]) == payload["has_more"]
        if kind == "batches":
            assert all(Decimal(r["on_hand_quantity"]) == Decimal("0.004") for r in rows)
        elif kind == "list":
            assert all(Decimal(r["on_hand_quantity"]) == (
                Decimal("1.5") if Decimal(r["reserved_quantity"]) else Decimal("1")) for r in rows)
    elif kind in {"summary", "alerts"}:
        assert payload["alert_count"] == fixture["filter_rows"]
        if kind == "summary":
            assert payload["stock_total"] == fixture["products"]
    elif kind == "stock_sources":
        expected_count = fixture["source_locations"] if spec["actor"] == "owner" and spec["name"] == "fanout" else 1
        assert len(payload["sources"]) == expected_count
        if spec["actor"] == "restricted":
            assert {r["location_id"] for r in payload["sources"]} == {fixture["warehouse_id"]}
    elif kind == "warehouse_source":
        statuses = {r["stock_status"]: r for r in payload["statuses"]}
        assert set(statuses) == ({"AVAILABLE", "DAMAGED"} if spec["name"] == "fanout" else {"AVAILABLE"})
        available = statuses["AVAILABLE"]
        assert Decimal(available["on_hand_quantity"]) == (
            Decimal("1") if spec["name"] == "fanout" else Decimal("0.004"))
        assert Decimal(available["reserved_quantity"]) == (
            Decimal("0.25") if spec["name"] == "fanout" else Decimal("0"))


async def measure(engine, fixture, spec, token, label, function, samples, ordinal, root):
    expected = await expected_keys(engine, fixture, spec)
    # Each synthetic client stays below the real per-IP limiter. No limiter,
    # authentication dependency, session, capability or RLS override is used.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False,
                                   client=(f"198.51.{ordinal // 250}.{ordinal % 250 + 1}", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://r4-final.test",
                                headers={"Authorization": "Bearer " + token}) as client:
        async def operation():
            return await client.get(spec["path"], params=spec["params"])
        with route_implementation(function):
            first, first_ms, _ = await r4.n1.capture_endpoint_call(http_engine, operation)
            assert first.status_code == 200, (spec, first.text)
            verify(first.json(), fixture, spec, expected)
            await operation()
            values, sql_counts, signatures, capture, payload = [], [], set(), [], None
            for _ in range(samples):
                response, elapsed, capture = await r4.n1.capture_endpoint_call(http_engine, operation)
                assert response.status_code == 200, (spec, response.text)
                assert response.headers.get("x-request-id")
                payload = response.json()
                verify(payload, fixture, spec, expected)
                signatures.add(json.dumps(payload, sort_keys=True))
                values.append(elapsed)
                sql_counts.append(len(capture))
            assert len(signatures) == 1
            assert_constant_counts(sql_counts)
            tracemalloc.start()
            try:
                memory_response = await operation()
                assert memory_response.status_code == 200
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
    plans = []
    async with r4.session(engine, fixture["company_id"]) as db:
        for record in capture:
            sql = record["statement"]
            assert sql.lstrip().upper().startswith(("SELECT", "WITH")), sql
            explained = await r4.n1.explain_statement(db, sql, record["parameters"])
            assert "plan" in explained
            if "inventory_page_candidates" in sql:
                assert_bounded_plan(explained["plan"], spec["limit"], "list")
            if (spec["kind"] == "batches" and "inventory_batch_candidates" in sql) or (
                    spec["kind"] == "families" and "FROM products" in sql):
                assert_bounded_plan(explained["plan"], spec["limit"], spec["kind"])
            plans.append({"sql": sql, "parameters": r4.n1.clean_json(record["parameters"]),
                          "driver_ms": record["duration_ms"], "explain": explained,
                          "metrics": plan_evidence(explained["plan"], fixture["products"])})
    result = {"spec": spec, "implementation": label, "http": distribution(values),
              "samples_ms": values, "first_observation_ms": first_ms,
              "sql_counts": sql_counts, "returned_bytes": len(response.content),
              "python_one_request_peak_bytes_separate_from_latency": peak,
              "python_process_rss_high_water_kib": rss_high_water(),
              "payload_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
              "plans": plans}
    path = f"cases/{ordinal:04d}-{label}.json"
    (root / "cases").mkdir(exist_ok=True)
    (root / path).write_text(json.dumps(result, indent=2, default=str))
    return {k: v for k, v in result.items() if k not in {"plans", "samples_ms", "sql_counts"}} | {
        "artifact": path, "sql_count": sql_counts[0],
        "plan_summary": [{"execution_ms": p["metrics"]["execution_ms"],
                          "root_buffers": p["metrics"]["root_buffers"],
                          "shared_buffer_hit_fraction": p["metrics"]["shared_buffer_hit_fraction"],
                          "indexes": p["metrics"]["indexes"],
                          "memory_nodes": p["metrics"]["memory_nodes"],
                          "catalog_work_nodes": [n for n in p["metrics"]["scans"] if n["catalog_sized_work"]]}
                         for p in plans],
        "page_work": next((p["metrics"]["scans"] for p in plans if "inventory_page_candidates" in p["sql"]), []),
    }
