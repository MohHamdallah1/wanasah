"""Focused PG16 acceptance for the two remaining negative Live Stock filters.

One 50k seed is reused. Exact accepted #675 code is compiled from the requested
base SHA and compared with HEAD on identical cloned databases. No production
latency SLA is asserted; SQL shape, buffers, payload parity and semantics are
the acceptance authority.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api.warehouse import live_stock
from api.warehouse._shared import _encode_variant_cursor
from models import ProductVariant
from scripts import gate_r4_live_stock_perf_50k as r4
from tests import test_live_stock_v1_r4_query_optimization_postgres as accepted


BASE_SHA = os.environ["R4_NEGATIVE_BASE_SHA"]
EVIDENCE = Path(os.environ.get(
    "R4_NEGATIVE_EVIDENCE_DIR",
    "/tmp/r4-negative-filter-evidence",
))


def _compact(result):
    relations = result["plan"]["relations"]
    return {
        "wall": result["wall"],
        "sql_count": result["sql_count"],
        "page_driver_ms": result["page_driver_ms"],
        "plan_execution_ms": round(
            float(result["plan"]["execution_ms"]), 3
        ),
        "root_buffers": result["plan"]["root_buffers"],
        "catalog_correlated_nodes": sum(
            1 for row in relations if row["catalog_correlated"]
        ),
        "max_relation_work": max(
            (int(row["work"]) for row in relations),
            default=0,
        ),
    }


def _source_at_base():
    return subprocess.check_output(
        ["git", "show", f"{BASE_SHA}:wa_backend/api/warehouse/live_stock.py"],
        text=True,
    )


async def _admin_engine(database: str):
    return create_async_engine(
        accepted._clone_url("DATABASE_URL_MIGRATION", database),
        poolclass=NullPool,
    )


async def _analyze(engine):
    async with engine.begin() as conn:
        for table in (
            "product_variants",
            "inventory_balances",
            "inventory_stock_policies",
            "inventory_live_stock_projection",
            "inventory_live_stock_company_summaries",
            "inventory_live_stock_warehouse_summaries",
        ):
            await conn.execute(text(f"ANALYZE {table}"))


async def _add_semantic_fixture(database: str, fixture: dict) -> dict:
    engine = await _admin_engine(database)
    c = fixture["company_id"]
    w = fixture["warehouse_id"]
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            await db.begin()
            await db.execute(
                text("SELECT set_config('app.current_tenant', :c, true)"),
                {"c": str(c)},
            )

            policy_ids = list((await db.scalars(text("""
                SELECT pv.id
                FROM product_variants pv
                JOIN inventory_stock_policies p
                  ON p.company_id=pv.company_id
                 AND p.product_variant_id=pv.id
                 AND p.location_id=:w
                 AND p.is_active IS TRUE
                WHERE pv.company_id=:c
                ORDER BY pv.id
                LIMIT 2
            """), {"c": c, "w": w})).all())
            assert len(policy_ids) == 2

            nonpolicy_ids = list((await db.scalars(text("""
                SELECT pv.id
                FROM product_variants pv
                WHERE pv.company_id=:c
                  AND NOT EXISTS (
                    SELECT 1
                    FROM inventory_stock_policies p
                    WHERE p.company_id=pv.company_id
                      AND p.product_variant_id=pv.id
                      AND p.location_id=:w
                      AND p.is_active IS TRUE
                  )
                ORDER BY pv.id
                LIMIT 2
            """), {"c": c, "w": w})).all())
            assert len(nonpolicy_ids) == 2

            zero_defined, defined_positive = map(int, policy_ids)
            unset_positive, hold_positive = map(int, nonpolicy_ids)

            await db.execute(text("""
                UPDATE product_variants
                SET name=CASE id
                    WHEN :zero THEN '001 NEG ZERO DEFINED'
                    WHEN :defined THEN '004 NEG DEFINED POSITIVE'
                    WHEN :unset THEN '002 NEG UNSET POSITIVE'
                    WHEN :hold THEN '003 NEG HOLD POSITIVE'
                    ELSE name END,
                    operational_hold=CASE
                        WHEN id=:hold THEN 'SALES_HOLD'
                        ELSE operational_hold END,
                    lifecycle_revision=CASE
                        WHEN id=:hold THEN lifecycle_revision + 1
                        ELSE lifecycle_revision END,
                    updated_at=NOW()
                WHERE company_id=:c
                  AND id IN (:zero,:defined,:unset,:hold)
            """), {
                "c": c,
                "zero": zero_defined,
                "defined": defined_positive,
                "unset": unset_positive,
                "hold": hold_positive,
            })
            await db.execute(text("""
                UPDATE inventory_balances
                SET on_hand_quantity=0,
                    reserved_quantity=0,
                    last_updated=NOW()
                WHERE company_id=:c
                  AND location_id=:w
                  AND product_variant_id=:zero
            """), {"c": c, "w": w, "zero": zero_defined})

            insert_sql = text("""
                INSERT INTO product_variants
                    (company_id, product_id, base_uom_id, name, sku,
                     quantity_scale, quantity_step,
                     lot_control_mode, expiry_control_mode,
                     lifecycle_status, operational_hold,
                     lifecycle_revision, version, published_at,
                     packs_per_carton, package_uses_base_barcode,
                     default_max_samples_per_day,
                     created_at, updated_at)
                SELECT
                    company_id, product_id, base_uom_id, :name, :sku,
                    quantity_scale, quantity_step,
                    lot_control_mode, expiry_control_mode,
                    'ACTIVE', 'NONE',
                    1, 1, NOW(),
                    packs_per_carton, package_uses_base_barcode,
                    default_max_samples_per_day,
                    NOW(), NOW()
                FROM product_variants
                WHERE company_id=:c
                ORDER BY id
                LIMIT 1
                RETURNING id
            """)
            missing_early = int((await db.execute(insert_sql, {
                "c": c,
                "name": "000 NEG MISSING PROJECTION",
                "sku": "R4-NEG-MISSING-EARLY",
            })).scalar_one())
            missing_deep = int((await db.execute(insert_sql, {
                "c": c,
                "name": "Common R2 040000A NEG MISSING PROJECTION",
                "sku": "R4-NEG-MISSING-DEEP",
            })).scalar_one())

            await db.execute(text("""
                UPDATE inventory_live_stock_company_summaries
                SET active_variant_count=active_variant_count + 2,
                    revision=revision + 1,
                    updated_at=NOW()
                WHERE company_id=:c
            """), {"c": c})

            await r4.refresh_live_stock_keys(
                db,
                company_id=c,
                keys=[
                    (w, zero_defined),
                    (w, defined_positive),
                    (w, unset_positive),
                    (w, hold_positive),
                ],
            )
            await db.commit()

        await _analyze(engine)
        return {
            "missing_early": missing_early,
            "missing_deep": missing_deep,
            "zero_defined": zero_defined,
            "defined_positive": defined_positive,
            "unset_positive": unset_positive,
            "hold_positive": hold_positive,
        }
    finally:
        await engine.dispose()


async def _runtime_identity(engine, fixture):
    async with r4.session(engine, fixture["company_id"]) as db:
        identity = (await db.execute(text("""
            SELECT current_user, rolsuper, rolbypassrls
            FROM pg_roles
            WHERE rolname=current_user
        """))).one()
        assert tuple(identity) == ("wanasah_app", False, False)
        version = str(await db.scalar(text("SHOW server_version")))
        assert version.startswith("16.")
        for table in (
            "product_variants",
            "inventory_balances",
            "inventory_live_stock_projection",
        ):
            flags = (await db.execute(text("""
                SELECT relrowsecurity, relforcerowsecurity
                FROM pg_class
                WHERE oid=to_regclass(:t)
            """), {"t": table})).one()
            assert tuple(flags) == (True, True), table


async def _anchor_and_cursor(
    engine,
    fixture,
    *,
    stock_state: str,
    minimum_unset: bool,
):
    async with r4.session(engine, fixture["company_id"]) as db:
        anchor = (await db.execute(
            select(ProductVariant.name, ProductVariant.id)
            .where(ProductVariant.company_id == fixture["company_id"])
            .order_by(ProductVariant.name, ProductVariant.id)
            .offset(24999)
            .limit(1)
        )).one()
    flags = "000001" if minimum_unset else "000000"
    scope = (
        f"inventory|{fixture['company_id']}|{fixture['warehouse_id']}||"
        f"{stock_state}|0|{flags}|name_asc"
    )
    return (
        (str(anchor.name), int(anchor.id)),
        _encode_variant_cursor(
            kind="warehouse-inventory",
            variant_name=str(anchor.name),
            variant_id=int(anchor.id),
            scope=scope,
        ),
    )


def _ids(payload):
    return {int(row["id"]) for row in payload["items"]}


async def _run():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    fixture_path = EVIDENCE / "fixture.json"
    assert not fixture_path.exists(), "Refuse a second 50k seed"

    await r4.seed.seed_fixture(fixture_path)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    await r4.enrich_fixture(fixture)
    fixture["products"] = r4.seed.PRODUCTS
    fixture_path.write_text(
        json.dumps(fixture, indent=2),
        encoding="utf-8",
    )

    await accepted._clone_fixture_databases()
    before = await accepted._runtime_engine(accepted.BEFORE_DB)
    after = await accepted._runtime_engine(accepted.AFTER_DB)
    base_function = accepted._compile_endpoint(
        _source_at_base(),
        "accepted-675",
    )
    head_function = live_stock.get_warehouse_inventory

    report = {
        "base_sha": BASE_SHA,
        "head_sha": os.environ["R4_NEGATIVE_HEAD_SHA"],
        "measurement": (
            "One 50k seed; exact cloned datasets; 3 warmups + 5 descriptive "
            "samples per measured case; real EXPLAIN ANALYZE BUFFERS. "
            "No production p95/p99 claim."
        ),
        "accepted_fixture_cases": [],
        "semantic_cases": [],
        "deep_cursor_cases": [],
    }

    try:
        await _runtime_identity(before, fixture)
        await _runtime_identity(after, fixture)

        # First compare exactly the two remaining #675 negative-filter families
        # on the accepted 50k fixture before adding semantic edge rows.
        measured = [
            ("owner", "out_of_stock", {"stock_state": "out_of_stock"}),
            ("restricted", "out_of_stock", {"stock_state": "out_of_stock"}),
            ("owner", "minimum_unset", {"minimum_unset": True}),
            ("restricted", "minimum_unset", {"minimum_unset": True}),
        ]
        for actor, name, filters in measured:
            old = await accepted._measure(
                before, fixture, actor, base_function,
                limit=50, search=None, **filters,
            )
            new = await accepted._measure(
                after, fixture, actor, head_function,
                limit=50, search=None, **filters,
            )
            assert new["payload"] == old["payload"], (actor, name)
            assert new["sql_count"] == old["sql_count"], (actor, name)

            old_correlated = [
                row for row in old["plan"]["relations"]
                if row["catalog_correlated"]
            ]
            new_correlated = [
                row for row in new["plan"]["relations"]
                if row["catalog_correlated"]
            ]
            assert old_correlated, (actor, name, old["plan"])
            assert not new_correlated, (actor, name, new["plan"])

            row = {
                "actor": actor,
                "filter": name,
                "payload_equal": True,
                "before": _compact(old),
                "after": _compact(new),
            }
            report["accepted_fixture_cases"].append(row)
            print(
                "R4_NEGATIVE_MEASURE "
                + json.dumps(row, default=str),
                flush=True,
            )

        before_semantics = await _add_semantic_fixture(
            accepted.BEFORE_DB, fixture
        )
        after_semantics = await _add_semantic_fixture(
            accepted.AFTER_DB, fixture
        )
        assert before_semantics == after_semantics
        special = before_semantics

        # Exact membership cases for missing projection, zero projection,
        # positive stock, defined/unset minimum, lifecycle hold and both actors.
        for actor in ("owner", "restricted"):
            out_old = await accepted._measure(
                before, fixture, actor, base_function,
                limit=50, search=None, stock_state="out_of_stock",
                warmups=1, samples=2,
            )
            out_new = await accepted._measure(
                after, fixture, actor, head_function,
                limit=50, search=None, stock_state="out_of_stock",
                warmups=1, samples=2,
            )
            assert out_new["payload"] == out_old["payload"]
            out_ids = _ids(out_new["payload"])
            assert special["missing_early"] in out_ids
            assert special["missing_deep"] in out_ids
            assert special["zero_defined"] in out_ids
            assert special["hold_positive"] in out_ids
            assert special["unset_positive"] not in out_ids
            assert special["defined_positive"] not in out_ids

            min_old = await accepted._measure(
                before, fixture, actor, base_function,
                limit=50, search=None, minimum_unset=True,
                warmups=1, samples=2,
            )
            min_new = await accepted._measure(
                after, fixture, actor, head_function,
                limit=50, search=None, minimum_unset=True,
                warmups=1, samples=2,
            )
            assert min_new["payload"] == min_old["payload"]
            min_ids = _ids(min_new["payload"])
            assert special["missing_early"] in min_ids
            assert special["unset_positive"] in min_ids
            assert special["hold_positive"] in min_ids
            assert special["zero_defined"] not in min_ids
            assert special["defined_positive"] not in min_ids

            report["semantic_cases"].append({
                "actor": actor,
                "out_of_stock": {
                    "returned": len(out_new["payload"]["items"]),
                    "before": _compact(out_old),
                    "after": _compact(out_new),
                },
                "minimum_unset": {
                    "returned": len(min_new["payload"]["items"]),
                    "before": _compact(min_old),
                    "after": _compact(min_new),
                },
                "special_ids": special,
                "payload_equal": True,
            })

        # Deep continuation uses the same cursor contract and must preserve
        # exact accepted #675 membership/order for owner and restricted actor.
        out_anchor, out_cursor = await _anchor_and_cursor(
            before,
            fixture,
            stock_state="out_of_stock",
            minimum_unset=False,
        )
        min_anchor, min_cursor = await _anchor_and_cursor(
            before,
            fixture,
            stock_state="all",
            minimum_unset=True,
        )
        for actor in ("owner", "restricted"):
            for name, filters, cursor, anchor in (
                (
                    "out_of_stock_deep",
                    {"stock_state": "out_of_stock"},
                    out_cursor,
                    out_anchor,
                ),
                (
                    "minimum_unset_deep",
                    {"minimum_unset": True},
                    min_cursor,
                    min_anchor,
                ),
            ):
                old = await accepted._measure(
                    before, fixture, actor, base_function,
                    limit=50, search=None, cursor=cursor,
                    warmups=1, samples=2, **filters,
                )
                new = await accepted._measure(
                    after, fixture, actor, head_function,
                    limit=50, search=None, cursor=cursor,
                    warmups=1, samples=2, **filters,
                )
                assert new["payload"] == old["payload"], (actor, name)
                keys = [
                    (row["name"], int(row["id"]))
                    for row in new["payload"]["items"]
                ]
                assert keys == sorted(set(keys))
                assert all(key > anchor for key in keys)
                if name == "out_of_stock_deep":
                    assert special["missing_deep"] in _ids(new["payload"])
                report["deep_cursor_cases"].append({
                    "actor": actor,
                    "filter": name,
                    "anchor": anchor,
                    "returned": len(keys),
                    "payload_equal": True,
                    "before": _compact(old),
                    "after": _compact(new),
                })

        report["status"] = "PASS"
        (EVIDENCE / "report.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )
        print(
            "R4_NEGATIVE_FILTER_PASS "
            + json.dumps({
                "measured_cases": len(report["accepted_fixture_cases"]),
                "semantic_actors": len(report["semantic_cases"]),
                "deep_cursor_cases": len(report["deep_cursor_cases"]),
            }),
            flush=True,
        )
    finally:
        if "status" not in report:
            report["status"] = "FAIL"
        (EVIDENCE / "report.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )
        await before.dispose()
        await after.dispose()


def test_negative_filter_query_closure():
    asyncio.run(_run())


if __name__ == "__main__":
    test_negative_filter_query_closure()
