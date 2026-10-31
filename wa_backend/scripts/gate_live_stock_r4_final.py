"""R4 final evidence gate. One 50k seed, real authorized HTTP, explicit OPEN status."""
from __future__ import annotations

import asyncio
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import time

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from database import engine as http_engine
from main import app
from models import ProductVariant
from scripts import gate_r4_live_stock_perf_50k as r4
from scripts.live_stock_r4_final_fixture import build, fingerprint
from scripts.live_stock_r4_final_metrics import (
    assert_selective_point_scans, distribution, hardware,
)
from scripts.live_stock_r4_final_profile import (
    LIST, implementations, login, measure, specifications,
)
from tests.test_live_stock_r4_selective_search_postgres import (
    PausedStatement,
    access_for,
    kwargs as r4_kwargs,
    negative_authority,
    set_reservation,
)


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


async def current_snapshot_controls(engine, admin, fixture, report):
    """Keep the real R1 race proof without pinning an obsolete CTE name."""
    async with r4.session(engine, fixture["company_id"]) as db:
        variant_id = await db.scalar(
            select(ProductVariant.id).where(
                ProductVariant.company_id == fixture["company_id"],
                ProductVariant.sku == "R2-50K-000001",
            )
        )
    records = []
    for actor in ("owner", "restricted"):
        for timing in ("before", "after"):
            await set_reservation(admin, fixture, variant_id, "0.25")
            async with r4.session(engine, fixture["company_id"]) as db:
                access = await access_for(db, fixture, actor)
                paused = PausedStatement(db, timing)
                values = r4_kwargs(
                    paused,
                    fixture,
                    access,
                    search="R2-50K-000001",
                    limit=1,
                    stock_state="sellable",
                )
                task = asyncio.create_task(
                    r4.n1.capture_endpoint_call(
                        engine,
                        lambda: __import__(
                            "api.warehouse.live_stock",
                            fromlist=["get_warehouse_inventory"],
                        ).get_warehouse_inventory(**values),
                    )
                )
                try:
                    await asyncio.wait_for(paused.reached.wait(), 20)
                    await set_reservation(admin, fixture, variant_id, "1")
                finally:
                    paused.release.set()
                payload, _, sql = await asyncio.wait_for(task, 20)
                assert len(sql) == 4
                combined = [
                    statement
                    for statement in sql
                    if "inventory_page_candidates" in statement["statement"]
                ]
                assert len(combined) == 1
                assert "inventory_detail_keys" in combined[0]["statement"]
                if timing == "before":
                    assert payload["items"] == []
                else:
                    assert [row["id"] for row in payload["items"]] == [variant_id]
                    assert Decimal(
                        payload["items"][0]["available_for_sale_quantity"]
                    ) == Decimal("0.75")
                records.append({
                    "actor": actor,
                    "timing": timing,
                    "sql_count": len(sql),
                    "single_candidate_detail_statement": True,
                })
    await set_reservation(admin, fixture, variant_id, "0.25")
    report["r1_snapshot_controls"] = records
    print("R4_CURRENT_SNAPSHOT " + json.dumps(records), flush=True)


def assert_counts_and_selective(report, fixture):
    final = [r for r in report["results"] if r["implementation"] == "implementation_head"]
    # Exact statement-count invariance, including all canonical HTTP dependencies.
    for actor in ("owner", "restricted"):
        for kind, names in (("list", ("initial", "deep", "broad", "rare", "short", "low_stock", "combined", "family_filter")),
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
        base = [r for r in report["results"] if r["implementation"] == "accepted_main"]
        restricted_initial_head = [
            r for r in final
            if r["spec"]["actor"] == "restricted"
            and r["spec"]["kind"] == "list"
            and r["spec"]["name"] == "initial"
        ]
        restricted_initial_base = [
            r for r in base
            if r["spec"]["actor"] == "restricted"
            and r["spec"]["kind"] == "list"
            and r["spec"]["name"] == "initial"
        ]
        assert len(restricted_initial_head) == len(restricted_initial_base) == 3

        def catalog_variant_work(result):
            return max(
                (
                    int(node["emitted_plus_filter_rows_x_loops"])
                    for node in result["page_work"]
                    if node.get("Relation Name") == "product_variants"
                    and node.get("catalog_sized_work")
                ),
                default=0,
            )

        before_work = {
            r["spec"]["limit"]: catalog_variant_work(r)
            for r in restricted_initial_base
        }
        after_work = {
            r["spec"]["limit"]: catalog_variant_work(r)
            for r in restricted_initial_head
        }
        assert all(before_work[limit] >= fixture["products"] for limit in (1, 50, 200)), before_work
        assert all(after_work[limit] == 0 for limit in (1, 50, 200)), after_work
        base50 = next(r for r in restricted_initial_base if r["spec"]["limit"] == 50)
        head50 = next(r for r in restricted_initial_head if r["spec"]["limit"] == 50)
        report["restricted_initial_permission_scan_fix"] = {
            "status": "PASS",
            "before_catalog_variant_work": before_work,
            "after_catalog_variant_work": after_work,
            "limit50_before_http": base50["http"],
            "limit50_after_http": head50["http"],
            "authority": (
                "Payload/cursor parity is mandatory in the paired measurement; "
                "Vehicle visibility remains readable-location scoped."
            ),
        }

        rare = [r for r in final if r["spec"]["kind"] == "list" and r["spec"]["name"] == "rare"]
        assert len(rare) == 6
        for result in rare:
            assert_selective_point_scans(result["page_work"])
        controls = [r for r in report["results"] if r["implementation"] == "probe_disabled_control"
                    and r["spec"]["name"] == "rare"]
        if controls:
            assert len(controls) == 2
            assert all(any(
                n["Relation Name"] == "product_variants" and n["catalog_sized_work"]
                for n in r["page_work"]
            ) for r in controls)
            report["bounded_selective_search"] = (
                "PASS; current rare search is point access and the reusable "
                "historical probe-off control reproduces catalog work"
            )
        else:
            report["bounded_selective_search"] = (
                "PASS; current exact-base and HEAD rare searches are selective "
                "point access. The old #645 source-shaped negative control no "
                "longer exists in current runtime and is not fabricated."
            )
    else:
        report["bounded_selective_search"] = "SMOKE ONLY: small-table planner choices are not 50k evidence"
    report["n_plus_one_query_growth"] = (
        "PASS: exact statement counts are constant across list/family/batch "
        "page sizes and source fanout in the measured matrix"
    )

    catalog_cases = []
    for result in final:
        nodes = [
            node
            for plan in result.get("plan_summary", [])
            for node in plan.get("catalog_work_nodes", [])
        ]
        if nodes:
            catalog_cases.append({
                "actor": result["spec"]["actor"],
                "kind": result["spec"]["kind"],
                "name": result["spec"]["name"],
                "limit": result["spec"]["limit"],
                "largest_work": max(
                    int(node["emitted_plus_filter_rows_x_loops"])
                    for node in nodes
                ),
                "relations": sorted({
                    str(node.get("Relation Name") or node.get("CTE Name") or "")
                    for node in nodes
                }),
            })
    report["catalog_sized_plan_cases"] = catalog_cases


def active_consumer_scope(report):
    """Record tracked callers and fail closed on a new report/export consumer."""
    root = Path(__file__).resolve().parents[1]
    matches = subprocess.check_output(
        ["git", "grep", "-n", "/warehouse/inventory/cursor", "--",
         ":(exclude)wa_backend/perf_reports/**"],
        cwd=root.parent,
        text=True,
    ).splitlines()
    paths = sorted({line.split(":", 1)[0] for line in matches})
    runtime_paths = [
        path for path in paths
        if not path.startswith(("docs/", "wa_backend/tests/", "dashboard/e2e/"))
        and not path.endswith("LIVE_STOCK_V1_CLOSURE_PLAN.md")
    ]
    report_like = [
        path for path in runtime_paths
        if any(token in path.lower() for token in (
            "report", "export", "csv", "xlsx", "spreadsheet",
        ))
    ]
    assert not report_like, (
        "New active Live Stock report/export consumer needs explicit "
        f"Warehouse/Vehicle/total scope acceptance: {report_like}"
    )
    report["consumer_scope"] = {
        "tracked_cursor_paths": paths,
        "active_runtime_paths": runtime_paths,
        "active_report_export_paths": report_like,
        "finding": (
            "No active report/export caller of the Live Stock cursor was found "
            "in tracked runtime source. Existing ledger/transfer/quality reports "
            "keep their independent contracts; this is repository-scope evidence, "
            "not a claim about unknown external clients."
        ),
    }


async def concurrent_controls(fixture, tokens, specs, report):
    """Bounded non-production concurrency; never presented as production p95/p99."""
    chosen = []
    wanted = {
        ("owner", "list", "initial", 50),
        ("restricted", "list", "initial", 50),
        ("owner", "list", "broad", 50),
        ("restricted", "list", "out_of_stock", 50),
        ("owner", "batches", "initial", 200),
        ("owner", "stock_sources", "fanout", None),
    }
    for spec in specs:
        key = (spec["actor"], spec["kind"], spec["name"], spec["limit"])
        if key in wanted:
            chosen.append(spec)
    assert len(chosen) == len(wanted), [s["name"] for s in chosen]

    records = []
    for round_index in range(5):
        async def one(index, spec):
            transport = httpx.ASGITransport(
                app=app,
                raise_app_exceptions=False,
                client=(f"203.0.113.{round_index * len(chosen) + index + 1}", 12345),
            )
            started = time.perf_counter()
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://r4-concurrency.test",
                headers={"Authorization": "Bearer " + tokens[spec["actor"]]},
            ) as client:
                response = await client.get(spec["path"], params=spec["params"])
            elapsed = (time.perf_counter() - started) * 1000
            assert response.status_code == 200, (spec, response.text)
            assert response.headers.get("x-request-id")
            return {
                "actor": spec["actor"],
                "kind": spec["kind"],
                "name": spec["name"],
                "limit": spec["limit"],
                "elapsed_ms": elapsed,
                "payload_sha256": __import__("hashlib").sha256(response.content).hexdigest(),
            }

        round_rows = await asyncio.gather(
            *(one(index, spec) for index, spec in enumerate(chosen))
        )
        records.extend(round_rows)

    by_case = {}
    for row in records:
        key = f'{row["actor"]}:{row["kind"]}:{row["name"]}:{row["limit"]}'
        bucket = by_case.setdefault(key, {"values": [], "payloads": set()})
        bucket["values"].append(row["elapsed_ms"])
        bucket["payloads"].add(row["payload_sha256"])
    summary = {}
    for key, bucket in by_case.items():
        assert len(bucket["payloads"]) == 1, (key, bucket["payloads"])
        summary[key] = distribution(bucket["values"])
    report["bounded_concurrency"] = {
        "parallel_width": len(chosen),
        "rounds": 5,
        "requests": len(records),
        "cases": summary,
        "interpretation": (
            "Shared GitHub runner + local ASGI + loopback PostgreSQL16. "
            "This is representative non-production contention evidence only; "
            "it is NOT production p95/p99, network, browser or cold-cache evidence."
        ),
    }


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
            "comparison": "accepted_main is the exact pull-request base and implementation_head is the candidate. "
                          "Both execute against the same fixture and must preserve payload/cursor/authority parity. "
                          "If source hashes differ, before/after evidence is an optimization comparison; if not, "
                          "this is current-main acceptance evidence. Probe-disabled control is test-only.",
            "limits": "List and batch limits1/50/200; family contract max100 tested1/50/100, HTTP200 must422. "
                      "Source contract max500 locations, tested1/201 with exact auth-visible membership.",
        }}
    engine = create_async_engine(r4.seed.checked_url("DATABASE_URL"), poolclass=NullPool)
    admin = create_async_engine(r4.seed.checked_url("DATABASE_URL_MIGRATION"), poolclass=NullPool)
    save(root, report)
    try:
        functions, source_hashes = implementations()
        report["runtime_sha256"] = source_hashes
        active_consumer_scope(report)
        fixture, identities = await build(root, size, admin)
        report["fixture"] = fixture
        report["environment"] = await r4.metadata(engine, fixture)
        print("R4_FINAL_ENVIRONMENT " + json.dumps({
            "hardware": report["hardware_before"],
            "runtime": report["environment"]["runtime"],
            "postgres": report["environment"]["postgres"],
            "stocked_variants": report["environment"]["stocked_variants"],
            "rls": report["environment"]["rls"],
            "runtime_sha256": report["runtime_sha256"]}, default=str), flush=True)
        report["inventory_before"] = await fingerprint(engine, fixture)
        tokens = await login(identities)
        specs = await specifications(engine, fixture)
        ordinal = 0
        for spec in specs:
            labels = ["accepted_main", "implementation_head"]
            if (
                "probe_disabled_control" in functions
                and spec["kind"] == "list"
                and spec["limit"] == 1
                and spec["name"] in {"broad", "rare", "short", "combined"}
            ):
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
                    "rss_high_water_kib": result["python_process_rss_high_water_kib"],
                    "artifact": result["artifact"], "payload_sha256": result["payload_sha256"],
                    "plans": [{**{k: v for k, v in p.items() if k != "catalog_work_nodes"},
                               "largest_catalog_work_nodes": sorted(p["catalog_work_nodes"],
                                   key=lambda n: n["emitted_plus_filter_rows_x_loops"], reverse=True)[:3]}
                              for p in result["plan_summary"]]}, default=str), flush=True)
                save(root, report)
            assert len(signatures) == 1, ("membership/cursor/quantity parity", spec)
        assert len(specs) == 116, len(specs)
        expected_results = len(specs) * 2 + sum(
            1
            for spec in specs
            if "probe_disabled_control" in functions
            and spec["kind"] == "list"
            and spec["limit"] == 1
            and spec["name"] in {"broad", "rare", "short", "combined"}
        )
        assert len(report["results"]) == expected_results, (
            len(report["results"]), expected_results
        )
        assert_counts_and_selective(report, fixture)
        report["inventory_after"] = await fingerprint(engine, fixture)
        assert report["inventory_after"] == report["inventory_before"]
        await http_controls(engine, fixture, tokens, report)
        await concurrent_controls(fixture, tokens, specs, report)
        # Reuse unchanged R4 real R1 race controls and least-privilege SQL checks.
        await current_snapshot_controls(engine, admin, fixture, report)
        await negative_authority(engine, admin, fixture, report)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                    base_url="http://r4-revocation.test") as client:
            denied = await client.get(LIST, params={"location_id": fixture["warehouse_id"]},
                headers={"Authorization": "Bearer " + tokens["restricted"]})
            assert denied.status_code == 403, denied.text
        report["same_bearer_after_grant_revocation"] = 403
        report["status"] = "EVIDENCE_PASS" if size == 50000 else "SMOKE_PASS"
        changed = bool(report["runtime_sha256"]["changed"])
        report["disposition"] = (
            "Bounded current-main SQL/performance/cursor/consumer acceptance passed. "
            + (
                "Candidate runtime differs from base; use the recorded before/after plans "
                "and latency distributions to judge the measured optimization. "
                if changed else
                "No production runtime change was required by this wave; the gate closes "
                "the missing current-main measurement/consumer evidence. "
            )
            + "Synthetic PG16 concurrency is not production qualification; real production "
              "p95/p99 and unknown external consumers remain outside this evidence."
        )
        print("R4_FINAL_GATE " + report["status"] + " BOUNDED_SQL_PASS " + json.dumps({
            "scale": size, "cases": len(report["results"]), "http_controls": len(report["http_denials"]),
            "cursor_walks": 4, "r1_snapshot_controls": 4}), flush=True)
    except BaseException as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        report["hardware_after"] = hardware()
        print("R4_FINAL_RESOURCES " + json.dumps({
            "hardware_after": report["hardware_after"],
            "inventory_before": report.get("inventory_before"),
            "inventory_after": report.get("inventory_after"),
            "status": report["status"], "error": report.get("error")}, default=str), flush=True)
        save(root, report)
        await engine.dispose()
        await admin.dispose()
        await http_engine.dispose()


if __name__ == "__main__":
    asyncio.run(acceptance())
