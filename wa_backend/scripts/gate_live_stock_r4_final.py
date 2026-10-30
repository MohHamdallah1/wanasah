"""R4 final evidence gate. One 50k seed, real authorized HTTP, explicit OPEN status."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from database import engine as http_engine
from main import app
from models import ProductVariant
from scripts import gate_r4_live_stock_perf_50k as r4
from scripts.live_stock_r4_final_fixture import build, fingerprint
from scripts.live_stock_r4_final_metrics import hardware, assert_selective_point_scans
from scripts.live_stock_r4_final_profile import (
    LIST, implementations, login, measure, specifications,
)
from tests.test_live_stock_r4_selective_search_postgres import snapshot_controls, negative_authority


def save(root, report):
    (root / "final-report.json").write_text(json.dumps(report, indent=2, default=str))


async def http_controls(engine, fixture, tokens, report):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                base_url="http://r4-controls.test") as client:
        records = []
        async def denied(label, path, params, actor, status):
            headers = {"Authorization": "Bearer " + tokens[actor]} if actor else {}
            response = await client.get(path, params=params, headers=headers)
            assert response.status_code == status, (label, response.text)
            assert response.headers.get("x-request-id")
            records.append({"control": label, "status": status})
        await denied("unauthenticated", LIST, {"location_id": fixture["warehouse_id"]}, None, 401)
        for actor in ("owner", "restricted"):
            for path in (LIST, f"/warehouse/inventory/{fixture['heavy_variant_id']}/batches"):
                await denied(actor + " hard limit201", path,
                    {"location_id": fixture["warehouse_id"], "limit": 201}, actor, 422)
            await denied(actor + " family public cap100", "/warehouse/inventory/families",
                {"location_id": fixture["warehouse_id"], "limit": 200}, actor, 422)
            await denied(actor + " foreign warehouse", LIST,
                {"location_id": fixture["foreign_warehouse_id"]}, actor, 404)
        for path in (LIST, "/warehouse/inventory/families",
                     f"/warehouse/inventory/{fixture['heavy_variant_id']}/batches",
                     f"/warehouse/inventory/{fixture['first_variant_id']}/batches/{fixture['source_batch_id']}/source"):
            await denied("restricted ungranted warehouse", path,
                {"location_id": fixture["denied_warehouse_id"]}, "restricted", 403)
        await denied("foreign owner warehouse", LIST,
            {"location_id": fixture["warehouse_id"]}, "foreign", 404)
        await denied("foreign owner batch sources",
            f"/warehouse/batches/{fixture['source_batch_id']}/stock-sources", {}, "foreign", 404)

        walks = []
        async with r4.session(engine, fixture["company_id"]) as db:
            expected = (await db.execute(select(ProductVariant.name, ProductVariant.id).where(
                ProductVariant.company_id == fixture["company_id"],
                ProductVariant.sku <= "R2-50K-000009").order_by(
                    ProductVariant.name, ProductVariant.id).limit(10))).all()
        for actor in ("owner", "restricted"):
            for sort in ("name_asc", "name_desc"):
                cursor, found, cursors = None, [], set()
                while True:
                    params = {"location_id": fixture["warehouse_id"], "limit": 1,
                              "search": "00000", "sort": sort}
                    if cursor:
                        params["cursor"] = cursor
                    response = await client.get(LIST, params=params,
                        headers={"Authorization": "Bearer " + tokens[actor]})
                    assert response.status_code == 200, response.text
                    page = response.json()
                    found.extend((r["name"], r["id"]) for r in page["items"])
                    assert len(found) <= 9
                    if not page["has_more"]:
                        break
                    cursor = page["next_cursor"]
                    assert cursor and cursor not in cursors
                    cursors.add(cursor)
                assert found == sorted([tuple(r) for r in expected], reverse=sort == "name_desc")
                assert len(found) == len(set(found)) == 9
                await denied("cursor scope search binding", LIST,
                    {"location_id": fixture["warehouse_id"], "limit": 1, "search": "Common",
                     "sort": sort, "cursor": next(iter(cursors))}, actor, 400)
                walks.append({"actor": actor, "sort": sort, "unique_rows": len(found), "pages": 9})
        report["http_denials"] = records
        report["http_cursor_walks"] = walks


def assert_counts_and_selective(report, fixture):
    final = [r for r in report["results"] if r["implementation"] == "implementation_head"]
    # Exact statement-count invariance, including all canonical HTTP dependencies.
    for actor in ("owner", "restricted"):
        for kind, names in (("list", ("initial", "broad", "rare", "short", "low_stock", "combined", "family_filter")),
                            ("families", ("initial", "deep", "common", "rare", "short")),
                            ("batches", ("initial", "deep"))):
            for name in names:
                subset = [r for r in final if r["spec"]["actor"] == actor and
                          r["spec"]["kind"] == kind and r["spec"]["name"] == name]
                assert len(subset) == 3
                assert len({r["sql_count"] for r in subset}) == 1, (kind, name, subset)
        subset = [r for r in final if r["spec"]["actor"] == actor and r["spec"]["kind"] == "stock_sources"]
        assert len(subset) == 2 and len({r["sql_count"] for r in subset}) == 1
    if fixture["products"] == 50000:
        rare = [r for r in final if r["spec"]["kind"] == "list" and r["spec"]["name"] == "rare"]
        assert len(rare) == 6
        for result in rare:
            assert_selective_point_scans(result["page_work"])
        controls = [r for r in report["results"] if r["implementation"] == "probe_disabled_control"
                    and r["spec"]["name"] == "rare"]
        assert len(controls) == 2
        assert all(any(n["Relation Name"] == "product_variants" and n["catalog_sized_work"]
                       for n in r["page_work"]) for r in controls)
        report["bounded_selective_search"] = "PASS; rejected probe-off control reproduces catalog work"
    else:
        report["bounded_selective_search"] = "SMOKE ONLY: small-table planner choices are not 50k evidence"
    report["n_plus_one_query_growth"] = "NONE in measured page/fanout matrix; exact constant counts"


async def acceptance():
    size = int(os.environ["R4_FINAL_SCALE"])
    assert size in {240, 50000}, "Only explicit synthetic smoke or ONE 50k acceptance"
    root = Path(os.environ["R4_FINAL_EVIDENCE_DIR"])
    root.mkdir(parents=True, exist_ok=True)
    r4.seed.PRODUCTS = size
    report = {"status": "RED", "r4_release": "OPEN", "scale": size,
        "accepted_base": os.environ["R4_FINAL_BASE_SHA"], "head_sha": os.environ["R4_FINAL_HEAD_SHA"],
        "results": [], "hardware_before": hardware(),
        "measurement": {
            "cache": "Seed, ANALYZE and login have run. First-observation values are not cold-cache proof. "
                     "One first observation + one unmeasured warm call precede each measured group. "
                     "Shared PostgreSQL/OS caches and prepared connection state stay warm; no cache flush.",
            "http": "Production main.app, real /login bearer/session/capability/scope/RLS and response schemas. "
                    "httpx local ASGI, no TCP/TLS/browser/network latency. No app lifespan/background relays.",
            "samples": "100 serial requests in EACH baseline/final representative group at50k; 100 for limit1 search controls. "
                       "Other cases3 plan/shape samples. Smoke3 only. Nearest-rank p99 at100 observations "
                       "has only about one observation in the upper1%; no production-tail confidence claim.",
            "memory": "Separate single-request tracemalloc peak (Python allocations only) is outside timed samples. "
                      "RSS includes pytest/imports/profiler. PostgreSQL plan memory nodes and docker stats "
                      "are evidence, not an invented memory/latency SLA.",
            "comparison": "accepted_main and implementation_head have byte-identical immutable runtime source. "
                          "They are paired before/final measurement windows, not an optimization claim. "
                          "Probe-disabled experimental control isolates #645 cost and must NOT ship.",
            "limits": "List and batch limits1/50/200; family contract max100 tested1/50/100, HTTP200 must422. "
                      "Source contract max500 locations, tested1/201 with exact auth-visible membership.",
        }}
    engine = create_async_engine(r4.seed.checked_url("DATABASE_URL"), poolclass=NullPool)
    admin = create_async_engine(r4.seed.checked_url("DATABASE_URL_MIGRATION"), poolclass=NullPool)
    save(root, report)
    try:
        functions, source_hash = implementations()
        report["runtime_sha256"] = source_hash
        fixture, identities = await build(root, size, admin)
        report["fixture"] = fixture
        report["environment"] = await r4.metadata(engine, fixture)
        report["inventory_before"] = await fingerprint(engine, fixture)
        tokens = await login(identities)
        specs = await specifications(engine, fixture)
        ordinal = 0
        for spec in specs:
            labels = ["accepted_main", "implementation_head"]
            if spec["kind"] == "list" and spec["limit"] == 1 and spec["name"] in {"broad", "rare", "short", "combined"}:
                labels.insert(1, "probe_disabled_control")
            signatures = set()
            for label in labels:
                ordinal += 1
                samples = 100 if size == 50000 and (spec["representative"] or label == "probe_disabled_control") else 3
                # Both current-code windows use identical sample counts.
                if spec["kind"] == "list" and spec["limit"] == 1 and spec["name"] in {"short", "combined"} and size == 50000:
                    samples = 100
                result = await measure(engine, fixture, spec, tokens[spec["actor"]], label,
                                       functions[label], samples, ordinal, root)
                signatures.add(result["payload_sha256"])
                report["results"].append(result)
                print("R4_FINAL_SAMPLE " + json.dumps({
                    "spec": spec, "implementation": label, "http": result["http"],
                    "sql_count": result["sql_count"], "returned_bytes": result["returned_bytes"],
                    "python_peak_bytes": result["python_one_request_peak_bytes_separate_from_latency"],
                    "artifact": result["artifact"], "payload_sha256": result["payload_sha256"],
                    "plans": [{k: v for k, v in p.items() if k != "catalog_work_nodes"}
                              for p in result["plan_summary"]]}, default=str), flush=True)
                save(root, report)
            assert len(signatures) == 1, ("membership/cursor/quantity parity", spec)
        assert len(specs) == 116, len(specs)
        assert len(report["results"]) == 240, len(report["results"])
        assert_counts_and_selective(report, fixture)
        report["inventory_after"] = await fingerprint(engine, fixture)
        assert report["inventory_after"] == report["inventory_before"]
        await http_controls(engine, fixture, tokens, report)
        # Reuse unchanged R4 real R1 race controls and least-privilege SQL checks.
        await snapshot_controls(engine, admin, fixture, report)
        await negative_authority(engine, admin, fixture, report)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                    base_url="http://r4-revocation.test") as client:
            denied = await client.get(LIST, params={"location_id": fixture["warehouse_id"]},
                headers={"Authorization": "Bearer " + tokens["restricted"]})
            assert denied.status_code == 403, denied.text
        report["same_bearer_after_grant_revocation"] = 403
        report["status"] = "EVIDENCE_PASS" if size == 50000 else "SMOKE_PASS"
        report["disposition"] = (
            "Evidence only. No safe new SQL/index improvement is proven. Preserve #645. "
            "Multi-match search helper work and broad/restricted plans remain measured bottlenecks. "
            "Synthetic CI is not production qualification; R4 release remains OPEN.")
        print("R4_FINAL_GATE " + report["status"] + " R4_OPEN " + json.dumps({
            "scale": size, "cases": len(report["results"]), "http_controls": len(report["http_denials"]),
            "cursor_walks": 4, "r1_snapshot_controls": 4}), flush=True)
    except BaseException as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        report["hardware_after"] = hardware()
        save(root, report)
        await engine.dispose()
        await admin.dispose()
        await http_engine.dispose()


if __name__ == "__main__":
    asyncio.run(acceptance())
