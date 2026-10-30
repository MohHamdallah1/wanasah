"""One disposable PG16 / 50k acceptance. No runtime SQL substitution or SLA."""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from scripts import gate_r2_live_stock_perf_50k as seed
from scripts import profile_live_stock_explain as n1
from api.warehouse import live_stock
from api.warehouse._shared import _encode_variant_cursor
from domains.identity.models import CompanyOwner
from domains.live_stock_projection.service import refresh_live_stock_keys
from models import ProductVariant

ROOT = Path(os.environ.get("R4_EVIDENCE_DIR", "/tmp/r4-evidence"))


def plan_nodes(node):
    yield node
    for child in node.get("Plans", []):
        yield from plan_nodes(child)


def plan_metrics(top):
    root = top["Plan"]
    nodes = list(plan_nodes(root))
    # PostgreSQL parent BUFFERS include child work: never sum for actual totals.
    return {
        "execution_ms": top["Execution Time"],
        "planning_ms": top["Planning Time"],
        "root_buffers": {k: root.get(k, 0) for k in (
            "Shared Hit Blocks", "Shared Read Blocks",
            "Temp Read Blocks", "Temp Written Blocks")},
        "legacy_inclusive_hit_sum": sum(n.get("Shared Hit Blocks", 0) for n in nodes),
        "indexes": sorted({n["Index Name"] for n in nodes if "Index Name" in n}),
        "scans": [{
            k: n.get(k) for k in (
                "Node Type", "Relation Name", "Alias", "Index Name", "CTE Name",
                "Subplan Name", "Actual Rows", "Actual Loops", "Rows Removed by Filter",
                "Rows Removed by Join Filter", "Plan Rows", "Index Cond", "Filter",
                "Actual Total Time", "Shared Hit Blocks", "Shared Read Blocks",
                "Temp Read Blocks", "Temp Written Blocks", "Sort Method")
        } for n in nodes if (
            "Scan" in n.get("Node Type", "")
            or "Subplan Name" in n
            or n.get("Actual Loops", 0) > 1000
            or n.get("Temp Written Blocks", 0))],
    }


def bounded_candidates(top, limit):
    candidates = [n for n in plan_nodes(top["Plan"])
                  if n.get("Subplan Name") == "CTE inventory_page_candidates"]
    details = [n for n in plan_nodes(top["Plan"])
               if n.get("Subplan Name") == "CTE inventory_detail_keys"]
    assert len(candidates) == len(details) == 1
    assert candidates[0]["Actual Rows"] <= limit + 1
    assert details[0]["Actual Rows"] <= limit


@asynccontextmanager
async def session(engine, company_id):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        await db.begin()
        await db.execute(text("SET TRANSACTION READ ONLY"))
        await db.execute(text("SELECT set_config('app.current_tenant', :c, true)"),
                         {"c": str(company_id)})
        # Execution budget inherited from accepted R1 gate; NOT a latency SLA.
        await db.execute(text("SET LOCAL statement_timeout='15000ms'"))
        yield db
        await db.rollback()


async def enrich_fixture(fixture):
    """Extend existing synthetic R2 stock; only 400 keys use real projector.

    This is a read-performance fixture, not financial/movement acceptance.
    Bulk initial stock has no receipt-cost history, as in accepted R2 evidence.
    """
    engine = create_async_engine(seed.checked_url("DATABASE_URL_MIGRATION"), poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            c, w = fixture["company_id"], fixture["warehouse_id"]
            await db.execute(text("SELECT set_config('app.current_tenant', :c, true)"), {"c": str(c)})
            ids = list((await db.scalars(select(ProductVariant.id).where(
                ProductVariant.company_id == c).order_by(ProductVariant.name, ProductVariant.id)
                .limit(400))).all())
            await db.execute(text("""
                INSERT INTO inventory_stock_policies
                    (company_id, location_id, product_variant_id, minimum_quantity,
                     minimum_remaining_shelf_life_days, is_active, created_at, updated_at)
                SELECT :c, :w, id, 2, 0, true, NOW(), NOW()
                FROM product_variants WHERE company_id=:c AND id=ANY(:ids)
            """), {"c": c, "w": w, "ids": ids})
            await db.execute(text("""
                UPDATE inventory_balances SET reserved_quantity=0.25
                WHERE company_id=:c AND location_id=:w AND product_variant_id=ANY(:ids)
            """), {"c": c, "w": w, "ids": ids})
            await db.execute(text("""
                INSERT INTO inventory_balances
                    (company_id, location_id, product_variant_id, batch_id,
                     stock_status, on_hand_quantity, reserved_quantity, last_updated)
                SELECT company_id, location_id, product_variant_id, batch_id,
                       'DAMAGED', 0.5, 0, NOW()
                FROM inventory_balances WHERE company_id=:c AND location_id=:w
                    AND product_variant_id=ANY(:ids) AND stock_status='AVAILABLE'
            """), {"c": c, "w": w, "ids": ids})
            await refresh_live_stock_keys(db, company_id=c, keys=[(w, i) for i in ids])
            other = await db.scalar(text("""
                INSERT INTO inventory_locations
                    (company_id, branch_id, name, code, location_type,
                     is_system_managed, version, is_active, created_at, updated_at)
                SELECT company_id, branch_id, 'R4 denied warehouse', 'R4-DENIED',
                       'WAREHOUSE', false, 1, true, NOW(), NOW()
                FROM inventory_locations WHERE company_id=:c AND id=:w RETURNING id
            """), {"c": c, "w": w})
            fixture["denied_warehouse_id"] = int(other)
            fixture["owner_backoffice_user_id"] = int(await db.scalar(
                select(CompanyOwner.backoffice_user_id).where(CompanyOwner.company_id == c)))
            fixture["family_id"] = int(await db.scalar(
                select(ProductVariant.product_id).where(ProductVariant.company_id == c).limit(1)))
            fixture["filter_rows"] = len(ids)
            await db.commit()
        async with engine.begin() as conn:
            for table in ("inventory_stock_policies", "inventory_balances",
                          "inventory_live_stock_projection", "inventory_locations"):
                await conn.execute(text(f"ANALYZE {table}"))
    finally:
        await engine.dispose()


async def metadata(engine, fixture):
    async with session(engine, fixture["company_id"]) as db:
        identity = (await db.execute(text("""
            SELECT current_user, rolsuper, rolbypassrls FROM pg_roles
            WHERE rolname=current_user
        """))).one()
        assert tuple(identity) == ("wanasah_app", False, False)
        settings = {k: await db.scalar(text(f"SHOW {k}")) for k in (
            "server_version", "work_mem", "shared_buffers", "effective_cache_size",
            "random_page_cost", "seq_page_cost", "jit", "track_io_timing",
            "transaction_read_only")}
        assert str(settings["server_version"]).startswith("16.")
        assert settings["transaction_read_only"] == "on"
        count = await db.scalar(text("""
            SELECT count(DISTINCT product_variant_id) FROM inventory_balances
            WHERE company_id=:c AND location_id=:w AND on_hand_quantity>0
        """), {"c": fixture["company_id"], "w": fixture["warehouse_id"]})
        assert count == seed.PRODUCTS
        indexes = (await db.execute(text("""
            SELECT tablename, indexname, indexdef FROM pg_indexes
            WHERE schemaname='public' AND tablename IN (
                'product_variants', 'inventory_balances', 'inventory_live_stock_projection',
                'inventory_stock_policies', 'inventory_cost_events')
            ORDER BY tablename, indexname
        """))).mappings().all()
        rls = (await db.execute(text("""
            SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class
            WHERE relname IN ('product_variants', 'inventory_balances',
                'inventory_live_stock_projection')
        """))).mappings().all()
        assert all(r["relrowsecurity"] and r["relforcerowsecurity"] for r in rls)
        for actor in ("owner", "restricted"):
            user_id = fixture[actor + "_backoffice_user_id"] if actor == "owner" else fixture["ordinary_backoffice_user_id"]
            access, context = await n1.load_backoffice_access(
                db, company_id=fixture["company_id"], backoffice_user_id=user_id,
                location_id=fixture["warehouse_id"])
            assert context.is_company_owner == (actor == "owner")
            if actor == "restricted":
                assert not await db.scalar(select(access.allows("inventory.read")))
                try:
                    await n1.load_backoffice_access(db, company_id=fixture["company_id"],
                        backoffice_user_id=user_id, location_id=fixture["denied_warehouse_id"])
                except RuntimeError as exc:
                    assert "lacks inventory.read" in str(exc)
                else:
                    raise AssertionError("restricted identity can access ungranted warehouse")
        return {"runtime": list(identity), "postgres": settings, "stocked_variants": count,
                "indexes": [dict(r) for r in indexes], "rls": [dict(r) for r in rls]}


def scenarios():
    for actor in ("owner", "restricted"):
        for limit in (1, 50, 200):
            for name, filters, expected in (
                ("initial", {}, limit),
                ("deep_40000", {}, limit),
                ("broad", {"search": "Common"}, limit),
                ("rare", {"search": "049999"}, 1),
                ("short", {"search": "Co"}, limit),
                ("low_stock", {"stock_state": "low_stock"}, limit),
                ("combined", {"search": "Common", "stock_state": "low_stock",
                              "has_reserved": True, "has_unavailable": True,
                              "has_damaged": True}, limit),
            ):
                yield {"actor": actor, "limit": limit, "name": name,
                       "filters": filters, "expected": expected}
        for name in ("summary", "alerts"):
            yield {"actor": actor, "limit": 50, "name": name, "filters": {}, "expected": None}


async def measure(engine, fixture, spec):
    c, w = fixture["company_id"], fixture["warehouse_id"]
    async with session(engine, c) as db:
        user_id = fixture["owner_backoffice_user_id"] if spec["actor"] == "owner" else fixture["ordinary_backoffice_user_id"]
        access, _ = await n1.load_backoffice_access(db, company_id=c,
            backoffice_user_id=user_id, location_id=w)
        kwargs = n1.inventory_page_kwargs(db=db, access=access, location_id=w,
            limit=spec["limit"], cursor=None, search=None, only_alerts=False)
        kwargs.update(spec["filters"])
        anchor = None
        if spec["name"] == "deep_40000":
            anchor = (await db.execute(select(ProductVariant.name, ProductVariant.id)
                .where(ProductVariant.company_id == c)
                .order_by(ProductVariant.name, ProductVariant.id).offset(39999).limit(1))).one()
            kwargs["cursor"] = _encode_variant_cursor(kind="warehouse-inventory",
                variant_name=anchor.name, variant_id=anchor.id,
                scope=f"inventory|{c}|{w}||all|0|000000|name_asc")
        async def operation():
            if spec["name"] in ("summary", "alerts"):
                fn = (live_stock.get_warehouse_inventory_summary if spec["name"] == "summary"
                      else live_stock.get_warehouse_inventory_alert_summary)
                return await fn(location_id=w, db=db, access=access)
            return await live_stock.get_warehouse_inventory(**kwargs)
        # One warm sample, three measured samples; do not reseed.
        await operation()
        samples, capture, payload = [], [], None
        counts = []
        for _ in range(3):
            payload, elapsed, capture = await n1.capture_endpoint_call(engine, operation)
            samples.append(elapsed)
            counts.append(len(capture))
        assert len(set(counts)) == 1
        expected_sql = 3 if spec["name"] == "alerts" or (
            spec["name"] == "summary" and spec["actor"] == "owner") else 4
        assert counts == [expected_sql] * 3, counts
        if spec["expected"] is not None:
            assert len(payload["items"]) == spec["expected"]
            keys = [(r["name"], r["id"]) for r in payload["items"]]
            assert keys == sorted(set(keys))
            if anchor:
                assert all(key > (anchor.name, anchor.id) for key in keys)
            if spec["name"] in ("low_stock", "combined"):
                assert all(r["is_low_stock"] for r in payload["items"])
            if spec["name"] == "combined":
                assert all(Decimal(r["reserved_quantity"]) > 0 and
                           Decimal(r["damaged_quantity"]) > 0 for r in payload["items"])
        else:
            assert payload["alert_count"] == fixture["filter_rows"]
            if spec["name"] == "summary":
                assert payload["stock_total"] == seed.PRODUCTS
        plans = []
        for record in capture:
            sql = record["statement"]
            assert sql.lstrip().upper().startswith(("SELECT", "WITH")), sql
            assert "live_stock_expected_truth" not in sql
            explained = await n1.explain_statement(db, sql, record["parameters"])
            assert "plan" in explained
            if "inventory_page_candidates" in sql:
                bounded_candidates(explained["plan"], spec["limit"])
            plans.append({
                "sql": sql, "parameters": n1.clean_json(record["parameters"]),
                "driver_ms": record["duration_ms"],
                "metrics": plan_metrics(explained["plan"]), "explain": explained,
            })
        return {**spec, "wall": seed.summary(samples), "samples_ms": samples,
                "sql_counts": counts, "returned": len(payload.get("items", [])),
                "cursor_anchor": list(anchor) if anchor else None,
                "plans": plans}


async def run():
    ROOT.mkdir(parents=True, exist_ok=True)
    fixture_path = ROOT / "fixture.json"
    assert not fixture_path.exists(), "Refuse repeated giant fixture"
    await seed.seed_fixture(fixture_path)
    fixture = json.loads(fixture_path.read_text())
    await enrich_fixture(fixture)
    fixture_path.write_text(json.dumps(fixture, indent=2))
    engine = create_async_engine(seed.checked_url("DATABASE_URL"), poolclass=NullPool)
    report = {
        "accepted_base": os.environ["R4_BASE_SHA"],
        "head_sha": os.environ["R4_HEAD_SHA"],
        "baseline_run": "https://github.com/MohHamdallah1/wanasah/actions/runs/40999601182",
        "fixture": fixture, "results": [], "failures": [],
        "measurement": "Direct endpoint including persisted endpoint authorization; identity resolution excluded. Warm three-sample distribution; p95 is sample max, not production p95. Root buffers are inclusive; legacy sum retained solely for historical comparison.",
    }
    try:
        report["environment"] = await metadata(engine, fixture)
        for spec in scenarios():
            try:
                result = await measure(engine, fixture, spec)
                report["results"].append(result)
                compact = {k: v for k, v in result.items() if k != "plans"}
                compact["plans"] = []
                for p in result["plans"]:
                    metrics = p["metrics"]
                    compact["plans"].append({
                        **{k: v for k, v in metrics.items() if k != "scans"},
                        "largest_scan_work": sorted(metrics["scans"], key=lambda n:
                            (n.get("Actual Loops") or 0) * (
                                (n.get("Actual Rows") or 0) +
                                (n.get("Rows Removed by Filter") or 0)),
                            reverse=True)[:6],
                    })
                print("R4_SAMPLE " + json.dumps(compact, default=str), flush=True)
            except Exception as exc:
                failure = {**spec, "error": f"{type(exc).__name__}: {exc}"}
                report["failures"].append(failure)
                print("R4_FAILURE " + json.dumps(failure), flush=True)
            finally:
                (ROOT / "r4-report.json").write_text(json.dumps(report, indent=2, default=str))
        assert len(report["results"]) + len(report["failures"]) == 46
        assert not report["failures"], report["failures"]
        print("R4_GATE PASS: 46 scenarios; SQL count and candidate bounds. Latency/plan review remains evidence-based.", flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
