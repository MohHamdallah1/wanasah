"""#1077 focused restricted PG16 readback; no mutation implementation changes."""
from datetime import date, timedelta
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, insert, select, text, update

from database import engine as http_engine
from models import (
    InventoryLocation, ShortageRequest, ShortageUrgentAssignment,
    UserLocationAccess, Visit,
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

        # Same-demand terminal history is deliberately much larger than the
        # live set. Seed by batches only in the isolated test database.
        history = 2000
        async with pg.session() as db:
            for start in range(0, history, 200):
                ids = (await db.scalars(insert(Visit).returning(Visit.id), [
                    dict(company_id=tenant.company_id, shop_id=shop,
                         driver_id=driver, operational_date=date.today() - timedelta(days=1+i),
                         status="Cancelled", is_emergency=True)
                    for i in range(start, min(start+200, history))
                ])).all()
                await db.execute(insert(ShortageUrgentAssignment), [
                    dict(company_id=tenant.company_id, shortage_id=demand_id, visit_id=v,
                         driver_id=driver, vehicle_id=vehicle, custody_epoch_id=epoch,
                         approved_base=1) for v in ids
                ])
            await db.commit()
        # Capture ACTUAL HTTP SQL, not an invented EXPLAIN surrogate.
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
            _progress(next(x for x in whole.json() if int(x["id"]) == demand_id),
                      1, 9, 2, 7)
            list_calls = list(captured)
        finally:
            event.remove(http_engine.sync_engine, "before_cursor_execute", record)
        for calls in (exact_calls, list_calls):
            projections = [(sql, args) for sql, args in calls if "pending_shortage_urgent" in sql]
            assert len(projections) == 1
            assert not any("inventory_movements" in sql.lower() for sql, _ in calls)
            statement, params = projections[0]
            async with pg.session() as db:
                conn = await db.connection()
                raw = (await conn.exec_driver_sql(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, params,
                )).scalar_one()
            doc = json.loads(raw) if isinstance(raw, str) else raw
            nodes = list(_walk(doc[0]["Plan"]))
            scans = [(n.get("Relation Name"), n.get("Index Name"),
                      n.get("Actual Rows"), n.get("Actual Loops"))
                     for n in nodes if n.get("Relation Name") in
                     ("shortage_urgent_assignments", "visits")]
            print("1077_HISTORY_PLAN", history, doc[0]["Execution Time"], scans)
            assignment_nodes = [n for n in nodes
                                if n.get("Relation Name") == "shortage_urgent_assignments"]
            assert assignment_nodes, scans
            assert all(n.get("Index Name") == "uq_shortage_assignment_visit"
                       for n in assignment_nodes), scans
            assert sum((n.get("Actual Rows", 0) + n.get("Rows Removed by Filter", 0))
                       * n.get("Actual Loops", 0) for n in assignment_nodes) < 20, scans
            assert sum(n.get("Actual Loops", 0) for n in assignment_nodes) < 20, scans
        assert len(list_calls) == len(exact_calls), (len(exact_calls), len(list_calls))

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
