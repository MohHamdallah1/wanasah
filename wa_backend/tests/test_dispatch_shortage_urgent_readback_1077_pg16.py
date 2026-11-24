"""#1077 focused restricted PG16 readback; no mutation implementation changes."""
import asyncio
from contextvars import ContextVar
from datetime import date, timedelta
from time import perf_counter
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, func, insert, literal, select, text, update

from database import engine as http_engine
from models import (
    InventoryLocation, OperationIdempotency, Shop, ShortageRequest, ShortageUrgentAssignment,
    UserLocationAccess, Visit, utc_now,
)
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_dispatch_shortage_phase_b_pg16 import (
    _command, _grant_location_dispatch_capability, _rls,
)
from tests.test_dispatch_shop_finance_edit_v1_postgres import (
    _add_shop, _grant_company_dispatch_capability, _real_field_sale_prerequisites,
    _real_http, _token,
)
from tests.test_dispatch_shortage_vehicle_availability_pg16 import _epoch, _vehicle_fixture
from tests.test_live_stock_v1_quantity_reconciliation_postgres import _seed_carton_conversion
from tests.test_live_stock_v1_route_sale_unload_postgres import _seed_mobile_uom_and_field

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_SHORTAGE_1077_PG_GATE") != "1",
        reason="Requires disposable migrated restricted PostgreSQL16",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


def _progress(row, fulfilled, outstanding, active, unassigned):
    assert (row["fulfilledBase"], row["outstandingBase"],
            row["activeUrgentBase"], row["unassignedBase"]) == (
                fulfilled, outstanding, active, unassigned,
            )
    assert not {"visit_id", "assignment_id", "vehicle_id", "custody_epoch_id"} & row.keys()


def _walk(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from _walk(child)


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_1077_real_pending_terminal_partial_scope_and_history(pg):
    await _rls()
    tenant, foreign = pg.tenants
    await _seed_carton_conversion(pg, tenant)
    field, zone, jurisdiction, launch = await _real_field_sale_prerequisites(pg, tenant)
    driver = int(field.driver.id)
    vehicle = int(launch["vehicle_id"])
    async with pg.session() as db:
        version = int(await db.scalar(text("SHOW server_version_num")))
        assert 160000 <= version < 170000
        vehicle_loc = await db.scalar(select(InventoryLocation.id).where(
            InventoryLocation.company_id == tenant.company_id,
            InventoryLocation.vehicle_id == vehicle,
            InventoryLocation.location_type == "VEHICLE",
        ))
        assert vehicle_loc is not None
    await _grant_company_dispatch_capability(pg, tenant, tenant.ordinary, "shortage.read")
    await _grant_location_dispatch_capability(
        pg, tenant, tenant.ordinary, "dispatch.read", tenant.location_id,
    )
    vehicle_role = await _grant_location_dispatch_capability(
        pg, tenant, tenant.ordinary, "dispatch.read", int(vehicle_loc),
    )
    async with _real_http() as client:
        owner = await _token(client, pg, tenant, tenant.owner, "NoLotSyntheticFixture123")
        ordinary = await _token(client, pg, tenant, tenant.ordinary, "SyntheticFixture123")
        other = await _token(client, pg, foreign, foreign.owner, "NoLotSyntheticFixture123")
        field_auth = await _token(client, pg, tenant, field, "SyntheticFixture123")
        response = await client.post("/dispatch/route", headers=owner, json=launch)
        assert response.status_code == 201, response.text
        epoch = await _epoch(pg, tenant, field, vehicle, int(vehicle_loc))
        started = await client.post("/driver/sessions/start",
                                    headers={**field_auth, "Idempotency-Key": str(uuid4())},
                                    json={})
        assert started.status_code == 201, started.text
        session = started.json()["session_id"]
        response = await client.put(f"/admin/sessions/{session}/authorize",
                                    headers=owner, json={"is_authorized": True})
        assert response.status_code == 200, response.text
        context = await client.get("/driver/sessions/execution-context", headers=field_auth)
        assert context.status_code == 200, context.text
        signed = dict(field_auth)
        proof = context.json()["execution_context"]
        if proof is not None:
            assert int(proof["custody_epoch_id"]) == epoch
            signed.update({
                "X-Execution-Period-ID": str(proof["period_id"]),
                "X-Assignment-Context-Revision": str(proof["assignment_context_revision"]),
                "X-Vehicle-Custody-Epoch-ID": str(proof["custody_epoch_id"]),
            })
        shop, _ = await _add_shop(client, owner, zone, balance="0", cap="100000",
                                  jurisdiction_id=jurisdiction)
        response = await client.post("/dispatch/shortage-commands", headers=owner,
            json=_command(uuid4(), shop, zone, None, tenant.variant_id, 10))
        assert response.status_code == 201, response.text
        demand_id = int(response.json()["lines"][0]["shortage_id"])
        path = f"/dispatch/shortages?shortage_id={demand_id}"

        async def row(auth=owner):
            r = await client.get(path, headers=auth)
            assert r.status_code == 200, r.text
            assert len(r.json()) == 1, r.text
            return r.json()[0]

        async def approve(quantity):
            response = await client.post(
                f"/dispatch/shortages/{demand_id}/promote-urgent", headers=owner,
                json={"request_id": str(uuid4()), "driver_id": driver,
                      "quantity_base": quantity},
            )
            assert response.status_code == 201, response.text
            return int(response.json()["visit_id"])

        _progress(await row(), 0, 10, 0, 10)
        first_visit = await approve(4)
        _progress(await row(), 0, 10, 4, 6)
        _progress(await row(ordinary), 0, 10, 4, 6)
        assert (await client.get(path, headers=other)).json() == []
        assert (await client.get(path, headers=field_auth)).status_code in (401, 403)
        sold = await client.put(f"/visits/{first_visit}", headers=signed, json={
            "request_id": str(uuid4()), "outcome": "Sale",
            "cash_collected": "1", "debt_paid": "0",
            "cart_items": [{"product_variant_id": tenant.variant_id, "packs_quantity": 1}],
        })
        assert sold.status_code == 200, sold.text
        _progress(await row(), 1, 9, 0, 9)
        second_visit = await approve(3)
        _progress(await row(), 1, 9, 3, 6)
        no_sale = await client.put(f"/visits/{second_visit}", headers=signed, json={
            "request_id": str(uuid4()), "outcome": "NoSale",
            "notes": "Synthetic no purchase", "cart_items": [],
            "cash_collected": "0", "debt_paid": "0",
        })
        assert no_sale.status_code == 200, no_sale.text
        _progress(await row(), 1, 9, 0, 9)
        active_visit = await approve(2)
        _progress(await row(), 1, 9, 2, 7)

        # Same-shop legacy row is still visible, but never guessed quantitative.
        async with pg.session() as db:
            legacy = ShortageRequest(company_id=tenant.company_id, zone_id=zone,
                shop_id=shop, product_variant_id=tenant.variant_id,
                quantity=8, status="pending")
            db.add(legacy)
            await db.flush()
            legacy_id = int(legacy.id)
            await db.commit()
        legacy_row = (await client.get(f"/dispatch/shortages?shortage_id={legacy_id}",
                                       headers=owner)).json()[0]
        _progress(legacy_row, None, None, None, None)

        # Seed a second representative's persisted pending evidence only in
        # this synthetic DB, while the first authorized route keeps Shop visible.
        # No production mutation bypass is exercised or modified.
        second_field = await _seed_mobile_uom_and_field(pg, tenant)
        second_vehicle, second_loc = await _vehicle_fixture(pg, tenant)
        second_epoch = await _epoch(pg, tenant, second_field, second_vehicle, second_loc)
        async with pg.session() as db:
            second = Visit(company_id=tenant.company_id, shop_id=shop,
                driver_id=int(second_field.driver.id), operational_date=date.today(),
                status="Pending", is_emergency=True)
            db.add(second)
            await db.flush()
            hidden_visit = int(second.id)
            db.add(ShortageUrgentAssignment(company_id=tenant.company_id,
                shortage_id=demand_id, visit_id=hidden_visit,
                driver_id=int(second_field.driver.id), vehicle_id=second_vehicle,
                custody_epoch_id=second_epoch, approved_base=3))
            await db.commit()
        _progress(await row(), 1, 9, 5, 4)
        _progress(await row(ordinary), 1, 9, None, None)
        # Redaction is all-or-nothing, even if one of two assignments is readable.
        async with pg.session() as db:
            await db.execute(update(ShortageUrgentAssignment).where(
                ShortageUrgentAssignment.company_id == tenant.company_id,
                ShortageUrgentAssignment.shortage_id == demand_id,
                ShortageUrgentAssignment.visit_id == hidden_visit,
            ).values(approved_base=10))
            await db.commit()
        _progress(await row(), 1, 9, None, None)
        async with pg.session() as db:
            await db.execute(update(Visit).where(
                Visit.company_id == tenant.company_id, Visit.id == hidden_visit,
            ).values(status="Cancelled"))
            await db.commit()
        _progress(await row(), 1, 9, 2, 7)
        _progress(await row(ordinary), 1, 9, 2, 7)

        # A corrupt cross-Shop assignment cannot be silently filtered away.
        unrelated_shop, _ = await _add_shop(
            client, owner, zone, balance="0", cap="100000",
            jurisdiction_id=jurisdiction,
        )
        async with pg.session() as db:
            await db.execute(update(Visit).where(
                Visit.company_id == tenant.company_id, Visit.id == hidden_visit,
            ).values(status="Pending", shop_id=unrelated_shop))
            await db.execute(update(ShortageUrgentAssignment).where(
                ShortageUrgentAssignment.company_id == tenant.company_id,
                ShortageUrgentAssignment.shortage_id == demand_id,
                ShortageUrgentAssignment.visit_id == hidden_visit,
            ).values(approved_base=1))
            await db.commit()
        _progress(await row(), 1, 9, None, None)
        async with pg.session() as db:
            await db.execute(update(Visit).where(
                Visit.company_id == tenant.company_id, Visit.id == hidden_visit,
            ).values(shop_id=shop, driver_id=driver,
                     operational_date=date.today() - timedelta(days=600)))
            await db.commit()
        _progress(await row(), 1, 9, None, None)
        async with pg.session() as db:
            await db.execute(update(Visit).where(
                Visit.company_id == tenant.company_id, Visit.id == hidden_visit,
            ).values(status="Cancelled", driver_id=int(second_field.driver.id)))
            await db.commit()
        _progress(await row(), 1, 9, 2, 7)

        # W2 signed seam: the initial response is captured as evidence, but
        # the business caller does not use it to infer completion. A terminal
        # sale removes the demand from GET; exact UUID retry must still return
        # the original immutable approval receipt.
        seam_shop, _ = await _add_shop(
            client, owner, zone, balance="0", cap="100000",
            jurisdiction_id=jurisdiction,
        )
        seam_demand = await client.post("/dispatch/shortage-commands", headers=owner,
            json=_command(uuid4(), seam_shop, zone, driver, tenant.variant_id, 2))
        assert seam_demand.status_code == 201, seam_demand.text
        seam_id = int(seam_demand.json()["lines"][0]["shortage_id"])
        seam_path = f"/dispatch/shortages?shortage_id={seam_id}"
        before = (await client.get(seam_path, headers=owner)).json()[0]
        _progress(before, 0, 2, 0, 2)
        quote_response = await client.get("/dispatch/shortages/vehicle-availability",
            headers=owner, params={"driver_id": driver, "product_ids": tenant.variant_id})
        assert quote_response.status_code == 200, quote_response.text
        quote = quote_response.json()
        assert quote["status"] == "VERIFIED", quote
        intent = {"request_id": str(uuid4()), "driver_id": driver, "quantity_base": 2}
        seam_endpoint = f"/dispatch/shortages/{seam_id}/promote-urgent"
        seam_first = await client.post(seam_endpoint, headers=owner, json=intent)
        assert seam_first.status_code == 201, seam_first.text
        receipt = seam_first.json()
        assert receipt["request_id"] == intent["request_id"]
        assert receipt["shortage_id"] == seam_id and receipt["approved_base"] == 2
        after = (await client.get(seam_path, headers=owner)).json()[0]
        _progress(after, 0, 2, 2, 0)
        seam_sale = await client.put(f"/visits/{receipt['visit_id']}", headers=signed, json={
            "request_id": str(uuid4()), "outcome": "Sale",
            "cash_collected": "2", "debt_paid": "0",
            "cart_items": [{"product_variant_id": tenant.variant_id, "packs_quantity": 2}],
        })
        assert seam_sale.status_code == 200, seam_sale.text
        assert (await client.get(seam_path, headers=owner)).json() == []
        seam_replay = await client.post(seam_endpoint, headers=owner, json=intent)
        assert seam_replay.status_code == 201 and seam_replay.json() == receipt, seam_replay.text
        final_rows = (await client.get("/dispatch/shortages", headers=owner)).json()
        assert str(seam_id) not in {r["id"] for r in final_rows}
        if os.getenv("WANASAH_1078_SEAM_JSON"):
            from pathlib import Path
            Path(os.environ["WANASAH_1078_SEAM_JSON"]).write_text(json.dumps({
                "before": before, "quote": quote, "request": intent,
                "receipt": receipt, "after": after, "replay": seam_replay.json(),
                "finalRows": final_rows,
            }, ensure_ascii=False), encoding="utf-8")
        print("1077_SIGNED_SEAM", seam_id, "same UUID/receipt after terminal GET []")

        # Scale independently: 500 unrelated visible signed demands and 500
        # unrelated live Visits, only 20 matched. Every unrelated demand must
        # still appear in the list, never silently truncated.
        breadth = 500
        matched = 20
        async with pg.session() as db:
            demand_ids = (await db.scalars(insert(ShortageRequest).returning(
                ShortageRequest.id), [
                dict(company_id=tenant.company_id, zone_id=zone,
                     shop_id=unrelated_shop, product_variant_id=tenant.variant_id,
                     quantity=10, status="pending", fulfillment_version=1,
                     fulfilled_base=0)
                for _ in range(breadth)
            ])).all()
            visit_ids = (await db.scalars(insert(Visit).returning(Visit.id), [
                dict(company_id=tenant.company_id, shop_id=unrelated_shop,
                     driver_id=driver, operational_date=date.today() - timedelta(days=1+i),
                     status="Pending", is_emergency=True)
                for i in range(breadth)
            ])).all()
            await db.execute(insert(ShortageUrgentAssignment), [
                dict(company_id=tenant.company_id, shortage_id=did, visit_id=vid,
                     driver_id=driver, vehicle_id=vehicle, custody_epoch_id=epoch,
                     approved_base=2)
                for did, vid in zip(demand_ids[:matched], visit_ids[:matched])
            ])
            await db.commit()

        async def add_history(count, offset):
            # Bounded INSERT..SELECT batches in one transaction keep fixture
            # seeding below statement timeout; no per-row Python loop.
            async with pg.session() as db:
                for start in range(0, count, 5000):
                    series = func.generate_series(start + 1, min(start + 5000, count)).table_valued("n").render_derived()
                    visits = insert(Visit).from_select(
                        ["company_id", "shop_id", "driver_id", "operational_date",
                         "status", "is_emergency"],
                        select(literal(tenant.company_id), literal(shop), literal(driver),
                               literal(date.today() - timedelta(days=offset)) - series.c.n,
                               literal("Cancelled"), literal(True)).select_from(series),
                    ).returning(Visit.id).cte("seed_terminal_visits")
                    await db.execute(insert(ShortageUrgentAssignment).from_select(
                        ["company_id", "shortage_id", "visit_id", "driver_id",
                         "vehicle_id", "custody_epoch_id", "approved_base", "created_at"],
                        select(literal(tenant.company_id), literal(demand_id), visits.c.id,
                               literal(driver), literal(vehicle), literal(epoch), literal(1),
                               literal(utc_now())),
                    ))
                await db.commit()

        async def analyze():
            # Test-only statistics refresh, not part of request or migration.
            async with pg.admin_engine.begin() as conn:
                await conn.execute(text("ANALYZE visits;"))
                await conn.execute(text("ANALYZE shortage_urgent_assignments;"))
                await conn.execute(text("ANALYZE shortage_requests;"))

        async def prove(label, history):
            captured = []
            def record(conn, cursor, statement, parameters, context, executemany):
                captured.append((statement, parameters))
            event.listen(http_engine.sync_engine, "before_cursor_execute", record)
            try:
                _progress(await row(), 1, 9, 2, 7)
                exact_calls = list(captured)
                captured.clear()
                whole = await client.get("/dispatch/shortages", headers=owner)
                assert whole.status_code == 200, whole.text
                rows = {int(x["id"]): x for x in whole.json()}
                assert set(demand_ids) <= rows.keys()
                _progress(rows[demand_id], 1, 9, 2, 7)
                for did in demand_ids[:matched]:
                    _progress(rows[did], 0, 10, 2, 8)
                for did in demand_ids[matched:]:
                    _progress(rows[did], 0, 10, 0, 10)
                list_calls = list(captured)
            finally:
                event.remove(http_engine.sync_engine, "before_cursor_execute", record)
            assert len(list_calls) == len(exact_calls), (len(exact_calls), len(list_calls))
            for kind, calls in (("exact", exact_calls), ("list", list_calls)):
                projections = [(sql, args) for sql, args in calls if "pending_shortage_urgent" in sql]
                assert len(projections) == 1
                assert not any("inventory_movements" in sql.lower() for sql, _ in calls)
                statement, params = projections[0]
                async with pg.session() as db:
                    conn = await db.connection()
                    raw = (await conn.exec_driver_sql(
                        "EXPLAIN (ANALYZE, VERBOSE, BUFFERS, FORMAT JSON) " + statement, params,
                    )).scalar_one()
                    # Test-only generic prepared plan; production never changes
                    # planner settings. Bind values are synthetic scalars.
                    def sql_value(v):
                        if v is None:
                            return "NULL"
                        if isinstance(v, bool):
                            return "TRUE" if v else "FALSE"
                        if isinstance(v, int):
                            return str(v)
                        assert isinstance(v, str), type(v)
                        return "'" + v.replace("'", "''") + "'"
                    await conn.exec_driver_sql("SET LOCAL plan_cache_mode = force_generic_plan")
                    await conn.exec_driver_sql("PREPARE w1077_plan AS " + statement)
                    generic = (await conn.exec_driver_sql(
                        "EXPLAIN (ANALYZE, VERBOSE, BUFFERS, FORMAT JSON) EXECUTE w1077_plan("
                        + ",".join(map(sql_value, params)) + ")"
                    )).scalar_one()
                    counts = (await conn.exec_driver_sql(
                        "SELECT generic_plans, custom_plans FROM pg_prepared_statements "
                        "WHERE name='w1077_plan'"
                    )).one()
                    assert counts[0] >= 1 and counts[1] == 0, counts
                    await conn.exec_driver_sql("DEALLOCATE w1077_plan")

                for mode, result in (("custom", raw), ("generic", generic)):
                    doc = json.loads(result) if isinstance(result, str) else result
                    nodes = list(_walk(doc[0]["Plan"]))
                    def work(n):
                        return (n.get("Actual Rows", 0) + n.get("Rows Removed by Filter", 0)
                                + n.get("Rows Removed by Index Recheck", 0)) * n.get("Actual Loops", 0)
                    relevant = [n for n in nodes if n.get("Relation Name") in
                                ("shortage_urgent_assignments", "visits")]
                    scans = [{k: n.get(k) for k in ("Relation Name", "Node Type", "Index Name",
                              "Actual Rows", "Actual Loops", "Rows Removed by Filter",
                              "Index Cond", "Shared Hit Blocks", "Shared Read Blocks")}
                             for n in relevant]
                    print("1077_SCALE", label, kind, mode, history, breadth, matched,
                          doc[0]["Execution Time"], json.dumps(scans))
                    assignment_nodes = [n for n in relevant if n["Relation Name"] == "shortage_urgent_assignments"]
                    visit_nodes = [n for n in relevant if n["Relation Name"] == "visits"]
                    assert len(assignment_nodes) == 1, scans
                    assert "visit_id" in assignment_nodes[0].get("Index Cond", ""), scans
                    assert assignment_nodes[0]["Actual Loops"] <= breadth + 10, scans
                    assert work(assignment_nodes[0]) <= matched + 10, scans
                    # Each ordered batch must use both tenant and status in
                    # its index condition, never filter historical rows.
                    pending_nodes = [n for n in visit_nodes if "status" in n.get("Index Cond", "")]
                    assert len(pending_nodes) == 2, scans
                    assert all("company_id" in n.get("Index Cond", "") for n in pending_nodes), scans
                    assert all(n.get("Rows Removed by Filter", 0) == 0 for n in pending_nodes), scans
                    assert sum(work(n) for n in pending_nodes) <= breadth + 40, scans
                    assert sum(n["Actual Loops"] for n in pending_nodes) <= 20, scans
                    pending_buffers = sum(n.get("Shared Hit Blocks", 0) + n.get("Shared Read Blocks", 0)
                                          for n in pending_nodes)
                    assert pending_buffers <= 150, scans
                    evidence_nodes = [n for n in visit_nodes if n not in pending_nodes]
                    assert len(evidence_nodes) == 1, scans
                    assert "id" in evidence_nodes[0].get("Index Cond", ""), scans
                    assert work(evidence_nodes[0]) <= matched + 10, scans
                    assert evidence_nodes[0]["Actual Loops"] <= matched + 10, scans
                    # EXPLAIN rounds per-loop rows; producer count is exact.
                    producers = [n for n in nodes if n.get("Subplan Name") == "CTE current_pending_assignments"]
                    assert len(producers) == 1 and producers[0]["Actual Rows"] == matched + 1, scans
                    print("1077_BOUNDED", label, kind, mode, "pending_buffers", pending_buffers,
                          "live_assignments", producers[0]["Actual Rows"])
            return len(rows)

        endpoint = f"/dispatch/shortages/{demand_id}/promote-urgent"

        def intent_for(qty):
            return {"request_id": str(uuid4()), "driver_id": driver,
                    "quantity_base": qty}

        async def no_sale_visit(visit_id):
            response = await client.put(f"/visits/{visit_id}", headers=signed, json={
                "request_id": str(uuid4()), "outcome": "NoSale",
                "notes": "Synthetic scale closure", "cart_items": [],
                "cash_collected": "0", "debt_paid": "0",
            })
            assert response.status_code == 200, response.text

        async def prove_promotion(label, history, previous_visit):
            await no_sale_visit(previous_visit)
            _progress(await row(), 1, 9, 0, 9)
            captured = []
            def record(conn, cursor, statement, parameters, context, executemany):
                captured.append((statement, parameters))
            # An independent transaction holds an actual terminal assignment
            # row lock. The old all-history FOR UPDATE would block here.
            async with pg.session() as blocker:
                terminal = await blocker.scalar(select(ShortageUrgentAssignment.id).where(
                    ShortageUrgentAssignment.company_id == tenant.company_id,
                    ShortageUrgentAssignment.shortage_id == demand_id,
                    ShortageUrgentAssignment.visit_id == first_visit,
                ).with_for_update())
                assert terminal is not None
                event.listen(http_engine.sync_engine, "before_cursor_execute", record)
                try:
                    start = perf_counter()
                    payload = intent_for(2)
                    response = await asyncio.wait_for(client.post(
                        endpoint, headers=owner, json=payload), timeout=20)
                    elapsed = (perf_counter() - start) * 1000
                finally:
                    event.remove(http_engine.sync_engine, "before_cursor_execute", record)
                    await blocker.rollback()
            assert response.status_code == 201, response.text
            receipt = response.json()
            assert receipt["approved_base"] == 2
            _progress(await row(), 1, 9, 2, 7)
            replay = await client.post(endpoint, headers=owner, json=payload)
            assert replay.status_code == 201 and replay.json() == receipt, replay.text
            duplicate = await client.post(endpoint, headers=owner, json=intent_for(1))
            assert duplicate.status_code == 409, duplicate.text
            assert duplicate.json()["error"]["code"] == "SHORTAGE_ALREADY_ASSIGNED_TO_VISIT"
            queries = [(sql, args) for sql, args in captured
                       if "shortage_urgent_assignments" in sql.lower() and "select" in sql.lower()]
            assert len(queries) == 2, [(sql[:200], len(args)) for sql, args in queries]
            assert not any("FOR UPDATE" in sql.upper() for sql, _ in queries)
            assert not any("inventory_movements" in sql.lower() for sql, _ in captured)
            assert max(len(args) for sql, args in captured) < 100
            assert len([sql for sql, _ in queries if "promotion_pending_assignment" in sql]) == 1
            visit_locks = [(sql,args) for sql,args in captured if "FROM visits" in sql and "FOR UPDATE" in sql.upper()]
            assert len(visit_locks) == 1, [sql for sql,_ in visit_locks]
            print("1077_POST_HTTP", label, history, "ms", round(elapsed, 3),
                  "sql", len(captured), "assignment_selects", len(queries),
                  "terminal_row_lock_not_blocking", terminal)
            for statement, params in queries + visit_locks:
                kind = ("budget" if "promotion_pending_assignment" in statement else
                        "visit-lock" if "FOR UPDATE" in statement.upper() else "duplicate")
                async with pg.session() as db:
                    conn = await db.connection()
                    raw = (await conn.exec_driver_sql(
                        "EXPLAIN (ANALYZE, VERBOSE, BUFFERS, FORMAT JSON) "
                        + statement, params,
                    )).scalar_one()
                    await db.rollback()
                doc = json.loads(raw) if isinstance(raw, str) else raw
                nodes = list(_walk(doc[0]["Plan"]))
                relevant = [n for n in nodes if n.get("Relation Name") in
                            ("shortage_urgent_assignments", "visits")]
                scans = [{k:n.get(k) for k in ("Relation Name", "Node Type",
                          "Index Name", "Index Cond", "Actual Rows", "Actual Loops",
                          "Rows Removed by Filter", "Shared Hit Blocks", "Shared Read Blocks")}
                         for n in relevant]
                print("1077_POST_PLAN", label, kind, history,
                      doc[0]["Execution Time"], json.dumps(scans))
                def work(n):
                    return (n.get("Actual Rows", 0) + n.get("Rows Removed by Filter", 0)
                            + n.get("Rows Removed by Index Recheck", 0)) * n.get("Actual Loops", 0)
                if kind == "budget":
                    visits = [n for n in relevant if n["Relation Name"] == "visits"]
                    assignments = [n for n in relevant if n["Relation Name"] == "shortage_urgent_assignments"]
                    assert len(visits) == 2 and len(assignments) == 1, scans
                    assert all("company_id" in n.get("Index Cond", "") and
                               "status" in n.get("Index Cond", "") for n in visits), scans
                    assert sum(work(n) for n in visits) <= breadth + 40, scans
                    assert all(n.get("Rows Removed by Filter", 0) == 0 for n in visits), scans
                    assert assignments[0]["Actual Loops"] <= breadth + 10, scans
                    assert all(x in assignments[0].get("Index Cond", "") for x in
                               ("company_id", "shortage_id", "visit_id")), scans
                    assert work(assignments[0]) <= 2, scans
                    assert not any(n.get("Node Type") == "LockRows" for n in nodes), scans
                elif kind == "duplicate":
                    assert len(relevant) == 1, scans
                    assert all(x in relevant[0].get("Index Cond", "") for x in
                               ("company_id", "shortage_id", "visit_id")), scans
                    assert work(relevant[0]) <= 1, scans
                else:
                    assert doc[0]["Plan"]["Actual Rows"] <= 2, scans
                    assert sum(work(n) for n in relevant) <= 10, scans
            return int(receipt["visit_id"]), len(captured)

        await add_history(2000, 1000)
        await analyze()
        await prove("small-fresh", 2000)
        active_visit, small_sql = await prove_promotion("small-fresh", 2000, active_visit)
        await add_history(50000, 10000)
        await prove("large-stale", 52000)
        active_visit, stale_sql = await prove_promotion("large-stale", 52000, active_visit)
        await analyze()
        await prove("large-fresh", 52000)
        active_visit, fresh_sql = await prove_promotion("large-fresh", 52000, active_visit)
        assert small_sql == stale_sql == fresh_sql, (small_sql, stale_sql, fresh_sql)

        # Independent genuine HTTP requests contend on the same demand, not
        # mocks. Concurrent identical UUIDs must resolve to one receipt.
        race_shop, _ = await _add_shop(client, owner, zone, balance="0", cap="100000",
                                       jurisdiction_id=jurisdiction)
        created = await client.post("/dispatch/shortage-commands", headers=owner,
            json=_command(uuid4(), race_shop, zone, driver, tenant.variant_id, 3))
        assert created.status_code == 201, created.text
        race_id = int(created.json()["lines"][0]["shortage_id"])
        race_path = f"/dispatch/shortages/{race_id}/promote-urgent"
        same = intent_for(1)
        left, right = await asyncio.wait_for(asyncio.gather(
            client.post(race_path, headers=owner, json=same),
            client.post(race_path, headers=owner, json=same),
        ), timeout=35)
        assert left.status_code == right.status_code == 201, (left.text, right.text)
        assert left.json() == right.json()
        await no_sale_visit(int(left.json()["visit_id"]))
        different = [intent_for(2), intent_for(2)]
        results = await asyncio.wait_for(asyncio.gather(*(
            client.post(race_path, headers=owner, json=body) for body in different
        )), timeout=35)
        assert sorted(r.status_code for r in results) == [201, 409], [r.text for r in results]
        winner = next(r.json() for r in results if r.status_code == 201)
        loser = next(body for body, r in zip(different, results) if r.status_code == 409)
        rejected = await client.post(race_path, headers=owner, json=loser)
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["error"]["code"] == "SHORTAGE_URGENT_EXCEEDS_OUTSTANDING"
        race_rows = (await client.get(f"/dispatch/shortages?shortage_id={race_id}", headers=owner)).json()
        _progress(race_rows[0], 0, 3, 2, 1)
        # Race a real FIELD terminal transition with another manager approval.
        # The manager either rejects the original budget or sees the released
        # budget; neither order can create two live assignments or exceed 3.
        closing = {"request_id": str(uuid4()), "outcome": "NoSale",
                   "notes": "Concurrent terminal", "cart_items": [],
                   "cash_collected": "0", "debt_paid": "0"}
        candidate = intent_for(2)
        field_result, manager_result = await asyncio.wait_for(asyncio.gather(
            client.put(f"/visits/{winner['visit_id']}", headers=signed, json=closing),
            client.post(race_path, headers=owner, json=candidate),
        ), timeout=35)
        if field_result.status_code != 200:
            assert field_result.status_code == 409, field_result.text
            field_result = await client.put(f"/visits/{winner['visit_id']}", headers=signed, json=closing)
        assert field_result.status_code == 200, field_result.text
        if manager_result.status_code != 201:
            assert manager_result.status_code == 409, manager_result.text
            manager_result = await client.post(race_path, headers=owner, json=candidate)
        assert manager_result.status_code == 201, manager_result.text
        race_rows = (await client.get(f"/dispatch/shortages?shortage_id={race_id}", headers=owner)).json()
        _progress(race_rows[0], 0, 3, 2, 1)
        async with pg.session() as db:
            assignments = (await db.scalars(select(ShortageUrgentAssignment).where(
                ShortageUrgentAssignment.company_id == tenant.company_id,
                ShortageUrgentAssignment.shortage_id == race_id,
            ))).all()
            assert sorted(a.approved_base for a in assignments) == [1, 2, 2]
            assert len({a.visit_id for a in assignments}) == 3
            receipts = await db.scalar(select(func.count()).select_from(OperationIdempotency).where(
                OperationIdempotency.company_id == tenant.company_id,
                OperationIdempotency.operation == "DISPATCH_SHORTAGE_PROMOTE_V1",
                OperationIdempotency.request_id.in_([same["request_id"], candidate["request_id"],
                                                    *[d["request_id"] for d in different]]),
            ))
            assert receipts == 3
        print("1077_POST_CONCURRENCY same UUID=1 receipt, distinct UUID=one winner,"
              " concurrent FIELD NoSale=conserved, 3 immutable assignments/receipts")

        # Reproduce the stale pre-lock ORM hazard deterministically: FIELD
        # and then manager both queue on a held Shop lock. The manager has
        # already probed the demand before the FIELD sale commits. A qty=3
        # approval must reject after observing the newly locked fulfilled=1.
        live_visit = int(manager_result.json()["visit_id"])
        label = ContextVar("shortage_race_actor", default="")
        waiting = {name: asyncio.Event() for name in ("field", "manager")}
        def on_shop_lock(conn, cursor, statement, parameters, context, executemany):
            actor = label.get()
            if actor in waiting and "FROM shops" in statement and "FOR UPDATE" in statement.upper():
                waiting[actor].set()

        async def tagged(actor, method, path, auth, body):
            token = label.set(actor)
            try:
                return await client.request(method, path, headers=auth, json=body)
            finally:
                label.reset(token)

        sale_body = {"request_id": str(uuid4()), "outcome": "Sale",
                     "cash_collected": "1", "debt_paid": "0",
                     "cart_items": [{"product_variant_id": tenant.variant_id,
                                     "packs_quantity": 1}]}
        excessive = intent_for(3)
        async with pg.session() as blocker:
            locked = await blocker.scalar(select(Shop.id).where(
                Shop.company_id == tenant.company_id, Shop.id == race_shop,
            ).with_for_update())
            assert locked == race_shop
            event.listen(http_engine.sync_engine, "before_cursor_execute", on_shop_lock)
            tasks = []
            try:
                tasks.append(asyncio.create_task(tagged(
                    "field", "PUT", f"/visits/{live_visit}", signed, sale_body)))
                await asyncio.wait_for(waiting["field"].wait(), timeout=15)
                # Yield to the actual PostgreSQL query before queuing manager.
                await asyncio.sleep(0.05)
                tasks.append(asyncio.create_task(tagged(
                    "manager", "POST", race_path, owner, excessive)))
                await asyncio.wait_for(waiting["manager"].wait(), timeout=15)
                await asyncio.sleep(0.05)
                assert not any(task.done() for task in tasks)
                await blocker.rollback()
                sold, overshoot = await asyncio.wait_for(asyncio.gather(*tasks), timeout=35)
            finally:
                event.remove(http_engine.sync_engine, "before_cursor_execute", on_shop_lock)
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
        assert sold.status_code == 200, sold.text
        assert overshoot.status_code == 409, overshoot.text
        assert overshoot.json()["error"]["code"] == "SHORTAGE_URGENT_EXCEEDS_OUTSTANDING", overshoot.text
        race_rows = (await client.get(f"/dispatch/shortages?shortage_id={race_id}", headers=owner)).json()
        _progress(race_rows[0], 1, 2, 0, 2)
        print("1077_POST_SERIALIZED_PARTIAL queued FIELD then manager, fulfilled=1, outstanding=2, rejected qty=3")

        _progress(await row(ordinary), 1, 9, 2, 7)
        assert (await client.get(path, headers=other)).json() == []

        # Revoke the actual vehicle read scope under the same signed token.
        async with pg.session() as db:
            await db.execute(delete(UserLocationAccess).where(
                UserLocationAccess.company_id == tenant.company_id,
                UserLocationAccess.driver_id == tenant.ordinary.driver_id,
                UserLocationAccess.role_id == vehicle_role,
            ))
            await db.commit()
        assert (await client.get(path, headers=ordinary)).json() == []
        _progress(await row(), 1, 9, 2, 7)
