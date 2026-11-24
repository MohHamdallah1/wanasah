"""#1077 focused restricted PG16 readback; no mutation implementation changes."""
from datetime import date, timedelta
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, func, insert, literal, select, text, update

from database import engine as http_engine
from models import (
    InventoryLocation, ShortageRequest, ShortageUrgentAssignment,
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
            # INSERT..SELECT uses one statement per table; no Python history
            # loop and no live mutation implementation bypass outside fixture.
            async with pg.session() as db:
                series = func.generate_series(1, count).table_valued("n").render_derived()
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

        await add_history(2000, 1000)
        await analyze()
        await prove("small-fresh", 2000)
        # Deliberately grow history after ANALYZE; repeat without refreshing
        # stats, then with fresh stats, same genuine signed HTTP requests.
        await add_history(50000, 10000)
        await prove("large-stale", 52000)
        await analyze()
        await prove("large-fresh", 52000)
        # Compare actual mutation's existing locked all-history lookup;
        # read-only plan evidence, no mutation implementation change.
        async with pg.session() as db:
            conn = await db.connection()
            mutation = select(ShortageUrgentAssignment).where(
                ShortageUrgentAssignment.company_id == tenant.company_id,
                ShortageUrgentAssignment.shortage_id == demand_id,
            ).order_by(ShortageUrgentAssignment.id.asc()).with_for_update()
            from sqlalchemy.dialects import postgresql
            sql = str(mutation.compile(dialect=postgresql.dialect(),
                                       compile_kwargs={"literal_binds": True}))
            raw = (await conn.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql
            )).scalar_one()
            doc = json.loads(raw) if isinstance(raw, str) else raw
            print("1077_MUTATION_HISTORY", doc[0]["Execution Time"],
                  doc[0]["Plan"]["Actual Rows"], doc[0]["Plan"].get("Shared Hit Blocks"),
                  doc[0]["Plan"].get("Shared Read Blocks"))
            assert doc[0]["Plan"]["Actual Rows"] >= 52000
            await db.rollback()
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
