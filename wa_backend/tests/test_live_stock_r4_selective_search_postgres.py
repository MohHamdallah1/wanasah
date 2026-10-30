"""One PG16 fixture: accepted R4 before/after, alternatives, exact regressions."""
from __future__ import annotations

import asyncio
import json
import os
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api.warehouse import live_stock
from models import ProductVariant
from scripts import gate_r4_live_stock_perf_50k as r4
from tests.live_stock_r4_search_support import (
    BASE_SHA, PausedStatement, access_for, endpoint, fingerprint, implementations,
    kwargs, page_plan, relation_work, set_reservation, work_nodes,
)

pytestmark = pytest.mark.skipif(
    os.getenv("R4_SEARCH_PG_GATE") != "1", reason="Explicit disposable R4 PG16 gate only")


def persist(report):
    (r4.ROOT / "r4-search-comparison.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8")


async def compare(engine, fixture, functions, report):
    """Reuse the unchanged accepted R4 measurement and all its assertions."""
    for spec in r4.scenarios():
        parity = None
        for label, function in functions.items():
            if label.startswith("materialized") and not spec["filters"].get("search"):
                continue
            payloads = []
            with endpoint(function, payloads):
                result = await r4.measure(engine, fixture, spec)
            if payloads:
                signature = fingerprint(payloads[-1])
                assert len({fingerprint(p) for p in payloads}) == 1
                if parity is None:
                    parity = signature
                else:
                    assert signature == parity, (label, spec)
            result["implementation"] = label
            report["results"].append(result)
            compact = {k: v for k, v in result.items() if k != "plans"}
            if spec["expected"] is not None:
                plan = page_plan(result)
                compact.update(plan=plan["metrics"], work=work_nodes(result))
                compact["plan"] = {k: v for k, v in compact["plan"].items() if k != "scans"}
            print("R4_SEARCH_SAMPLE " + json.dumps(compact, default=str), flush=True)
            persist(report)

    selected = [r for r in report["results"]
                if r["implementation"] == "scalar_array" and r["name"] == "rare"]
    assert len(selected) == 6
    for result in selected:
        # One matching variant: every variant scan/probe visits at most that
        # one match, including rows rejected by lifecycle filters.
        assert relation_work(result) <= 1, work_nodes(result)
        # A name-ordered index can hide examined entries in Index Cond. Require
        # the point-access path, not just a small emitted-row count.
        for node in work_nodes(result):
            if node["Relation Name"] == "product_variants" and node["Actual Loops"]:
                assert node["Index Name"] in {
                    "uq_product_variants_company_id", "pk_product_variants",
                }, node
        assert not any(n["Node Type"] == "Aggregate"
                       and (n["Actual Loops"] or 0) > 1 for n in work_nodes(result))
    old = [r for r in report["results"]
           if r["implementation"] == "baseline" and r["name"] == "rare" and r["limit"] == 1]
    assert len(old) == 2
    assert all(relation_work(r) >= fixture["products"] for r in old)
    assert sum(r["implementation"] == "baseline" for r in report["results"]) == 46
    assert sum(r["implementation"] == "scalar_array" for r in report["results"]) == 46
    assert len(report["results"]) == 140


async def exact_membership(engine, fixture, report):
    """Independent expected membership, bounded to 201 rows; no catalog in Python."""
    checks = 0
    filters = [
        {}, {"stock_state": "sellable"}, {"stock_state": "on_hand"},
        {"stock_state": "low_stock"}, {"only_alerts": True},
        {"stock_state": "out_of_stock"}, {"has_reserved": True},
        {"has_unavailable": True}, {"has_damaged": True}, {"has_recalled": True},
        {"has_vehicle": True}, {"minimum_unset": True}, {"family_id": fixture["family_id"]},
        {"stock_state": "low_stock", "has_reserved": True,
         "has_unavailable": True, "has_damaged": True},
    ]
    # Duplicate names exercise the ID tie-breaker without changing fixture size.
    async with AsyncSession(report.pop("_admin"), expire_on_commit=False) as db:
        c = fixture["company_id"]
        await db.execute(text("SELECT set_config('app.current_tenant', :c, true)"), {"c": str(c)})
        first_two = list((await db.scalars(select(ProductVariant.id)
            .where(ProductVariant.company_id == c)
            .order_by(ProductVariant.name, ProductVariant.id).limit(2))).all())
        first_name = await db.scalar(select(ProductVariant.name).where(ProductVariant.id == first_two[0]))
        await db.execute(text("UPDATE product_variants SET name=:n WHERE company_id=:c AND id=:i"),
                         {"n": first_name, "c": c, "i": first_two[1]})
        await r4.refresh_live_stock_keys(db, company_id=c,
            keys=[(fixture["warehouse_id"], i) for i in first_two])
        await db.commit()

    for actor in ("owner", "restricted"):
        async with r4.session(engine, fixture["company_id"]) as db:
            access = await access_for(db, fixture, actor)
            for search in ("  cOmMoN   R2  ", "049999", "04999", "Co", "%%", "__", "zzzzmissing", "00000"):
                for sort in ("name_asc", "name_desc"):
                    for selected in filters:
                        query = kwargs(db, fixture, access, search=search, sort=sort, **selected)
                        page = await live_stock.get_warehouse_inventory(**query)
                        expected = select(ProductVariant.name, ProductVariant.id).where(
                            ProductVariant.company_id == fixture["company_id"])
                        expression = func.lower(ProductVariant.name + " " + ProductVariant.sku)
                        for token in search.lower().split():
                            literal = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                            expected = expected.where(expression.like("%" + literal + "%", escape="\\"))
                        if (selected.get("stock_state") == "low_stock"
                            or selected.get("only_alerts") or any(selected.get(k) for k in (
                                "has_reserved", "has_unavailable", "has_damaged"))):
                            expected = expected.where(ProductVariant.sku <= "R2-50K-000400")
                        if selected.get("minimum_unset"):
                            expected = expected.where(ProductVariant.sku > "R2-50K-000400")
                        if (selected.get("stock_state") == "out_of_stock"
                            or selected.get("has_recalled") or selected.get("has_vehicle")):
                            expected = expected.where(text("false"))
                        ordering = (ProductVariant.name, ProductVariant.id)
                        if sort == "name_desc":
                            ordering = tuple(column.desc() for column in ordering)
                        rows = (await db.execute(expected.order_by(*ordering).limit(51))).all()
                        assert [(r["name"], r["id"]) for r in page["items"]] == [
                            tuple(row) for row in rows[:50]]
                        assert page["has_more"] == (len(rows) > 50)
                        checks += 1
            # Real continuation tokens through every matching row, both orders.
            for sort in ("name_asc", "name_desc"):
                cursor, found = None, []
                while True:
                    page = await live_stock.get_warehouse_inventory(**kwargs(
                        db, fixture, access, search="00000", limit=1, sort=sort, cursor=cursor))
                    found.extend((r["name"], r["id"]) for r in page["items"])
                    if not page["has_more"]:
                        break
                    assert page["next_cursor"] and page["next_cursor"] != cursor
                    cursor = page["next_cursor"]
                    assert len(found) < 10
                ordered = (await db.execute(select(ProductVariant.name, ProductVariant.id)
                    .where(ProductVariant.company_id == fixture["company_id"],
                           ProductVariant.sku <= "R2-50K-000009")
                    .order_by(*(column.desc() if sort == "name_desc" else column
                                for column in (ProductVariant.name, ProductVariant.id))))).all()
                assert found == [tuple(row) for row in ordered]
                assert len(found) == len(set(found)) == 9
                first = await live_stock.get_warehouse_inventory(**kwargs(
                    db, fixture, access, search="00000", limit=1, sort=sort))
                for changed in ({"search": "Common"}, {"sort": "name_desc" if sort == "name_asc" else "name_asc"},
                                {"has_reserved": True}):
                    values = kwargs(db, fixture, access, search="00000", limit=1, sort=sort,
                                    cursor=first["next_cursor"])
                    values.update(changed)
                    with pytest.raises(HTTPException) as error:
                        await live_stock.get_warehouse_inventory(**values)
                    assert error.value.status_code == 400
    report["membership_checks"] = checks
    report["cursor_walks"] = 4
    print("R4_SEARCH_MEMBERSHIP " + json.dumps({"cases": checks, "cursor_walks": 4}), flush=True)


async def snapshot_controls(engine, admin, fixture, report):
    async with r4.session(engine, fixture["company_id"]) as db:
        variant_id = await db.scalar(select(ProductVariant.id).where(
            ProductVariant.company_id == fixture["company_id"],
            ProductVariant.sku == "R2-50K-000001"))
    records = []
    for actor in ("owner", "restricted"):
        for timing in ("before", "after"):
            await set_reservation(admin, fixture, variant_id, "0.25")
            async with r4.session(engine, fixture["company_id"]) as db:
                access = await access_for(db, fixture, actor)
                paused = PausedStatement(db, timing)
                values = kwargs(paused, fixture, access, search="000001", limit=1, stock_state="sellable")
                task = asyncio.create_task(r4.n1.capture_endpoint_call(
                    engine, lambda: live_stock.get_warehouse_inventory(**values)))
                try:
                    await asyncio.wait_for(paused.reached.wait(), 20)
                    await set_reservation(admin, fixture, variant_id, "1")
                finally:
                    paused.release.set()
                payload, _, sql = await asyncio.wait_for(task, 20)
                assert len(sql) == 4
                combined = [s for s in sql if "inventory_page_candidates" in s["statement"]]
                assert len(combined) == 1
                assert "inventory_detail_keys" in combined[0]["statement"]
                assert "array_agg" in combined[0]["statement"]
                if timing == "before":
                    assert payload["items"] == []
                else:
                    assert [r["id"] for r in payload["items"]] == [variant_id]
                    assert Decimal(payload["items"][0]["available_for_sale_quantity"]) == Decimal("0.75")
                records.append({"actor": actor, "timing": timing, "sql_count": len(sql)})
    await set_reservation(admin, fixture, variant_id, "0.25")
    report["r1_snapshot_controls"] = records
    print("R4_SEARCH_SNAPSHOT " + json.dumps(records), flush=True)


async def negative_authority(engine, admin, fixture, report):
    c = fixture["company_id"]
    async with r4.session(engine, c) as db:
        access = await access_for(db, fixture, "restricted")
        with pytest.raises(HTTPException) as error:
            await live_stock.get_warehouse_inventory(**kwargs(
                db, fixture, access, search="049999", location_id=fixture["denied_warehouse_id"]))
        assert error.value.status_code == 403
    async with r4.session(engine, c + 1) as db:
        assert await db.scalar(select(func.count()).select_from(ProductVariant).where(
            ProductVariant.company_id == c)) == 0
        with pytest.raises(DBAPIError) as error:
            await db.execute(text("SELECT public.live_stock_search_variant_ids(:c, ARRAY['%049999%'])"), {"c": c})
        assert getattr(error.value.orig, "sqlstate", None) == "42501"
    # Deliberately revoke the actual persisted location grant, not a token claim.
    async with AsyncSession(admin, expire_on_commit=False) as db:
        await db.execute(text("SELECT set_config('app.current_tenant', :c, true)"), {"c": str(c)})
        changed = await db.execute(text("""
            DELETE FROM user_location_access WHERE company_id=:c
                AND driver_id=:d AND location_id=:w RETURNING location_id
        """), {"c": c, "d": fixture["ordinary_driver_id"], "w": fixture["warehouse_id"]})
        assert len(changed.all()) == 1
        await db.commit()
    async with r4.session(engine, c) as db:
        with pytest.raises(RuntimeError, match="lacks inventory.read"):
            await access_for(db, fixture, "restricted")
    report["negative_authority"] = {
        "ungranted_warehouse": "403", "cross_tenant_rls_rows": 0,
        "search_helper_wrong_tenant_sqlstate": "42501", "revoked_grant": "denied"}
    print("R4_SEARCH_AUTHORITY " + json.dumps(report["negative_authority"]), flush=True)


async def acceptance():
    r4.ROOT.mkdir(parents=True, exist_ok=True)
    fixture_path = r4.ROOT / "fixture.json"
    assert not fixture_path.exists(), "Refuse repeated giant fixture"
    await r4.seed.seed_fixture(fixture_path)
    fixture = json.loads(fixture_path.read_text())
    await r4.enrich_fixture(fixture)
    fixture_path.write_text(json.dumps(fixture, indent=2))
    engine = create_async_engine(r4.seed.checked_url("DATABASE_URL"), poolclass=NullPool)
    admin = create_async_engine(r4.seed.checked_url("DATABASE_URL_MIGRATION"), poolclass=NullPool)
    report = {"accepted_base": BASE_SHA, "head": os.environ["R4_HEAD_SHA"],
              "results": [], "fixture": fixture}
    try:
        report["environment"] = await r4.metadata(engine, fixture)
        functions = implementations()
        await compare(engine, fixture, functions, report)
        report["_admin"] = admin
        await exact_membership(engine, fixture, report)
        await snapshot_controls(engine, admin, fixture, report)
        await negative_authority(engine, admin, fixture, report)
        report["status"] = "PASS"
        print("R4_SEARCH_GATE PASS: one fixture; 46 baseline + 46 runtime + 48 alternatives", flush=True)
    finally:
        report.pop("_admin", None)
        persist(report)
        await engine.dispose()
        await admin.dispose()


def test_one_fixture_r4_search_acceptance():
    asyncio.run(acceptance())
