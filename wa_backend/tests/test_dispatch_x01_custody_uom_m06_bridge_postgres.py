"""X01: NEW cross-feature bridge only; historical C03/U03/M06 suites stay untouched.

Real disposable PG16, restricted FORCE RLS, canonical manager and FIELD Bearer.
Existing accepted C02 handoff and D07 fixtures are prerequisites, not re-tests.
The delta measured here is C03 accepted -> largest UOM + remainder -> load and
unload once -> signed POSTPONE/RESUME on the same stocked vehicle.
M06's separate accepted A->B->A, cash/count/S2 proof is not claimed as this test.
"""
from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from models import ProductUomConversion, UOM
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_dispatch_route_launch_d07_postgres import _prepared_route, LoseRoute201
from tests.test_dispatch_shop_finance_edit_v1_postgres import _owner, _real_http
from tests.test_dispatch_p0_route_stock_safety_postgres import (
    _snapshot, _total, _route_adjust_context,
)
from tests.test_dispatch_m02_lifecycle_postgres import _body
from tests.c02_signed_custody_real_http import accept_prepared_vehicle_by_real_http


pytestmark = [
    pytest.mark.skipif(
        os.environ.get("RUN_X01_M06_PG16") != "1",
        reason="X01 only: restricted disposable PG16 with genuine HTTP",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_x01_signed_custody_then_uom_load_unload_and_m06_reentry_no_phantom_stock(pg):
    home, foreign = pg.tenants
    request_id, payload, car_location = await _prepared_route(pg, home)
    car_id = int(payload["vehicle_id"])
    rep_id = int(payload["driver_id"])
    product_id = str(home.variant_id)
    availability_path = "/dispatch/launch/resource-availability"

    async with _real_http() as http:
        manager = await _owner(http, pg, home)
        foreign_manager = await _owner(http, pg, foreign)

        # C03's previously certified REAL two-person signed handoff is reused
        # as a prerequisite, not tested with any mocked custody or JWT.
        custody_revision = await accept_prepared_vehicle_by_real_http(
            pg, home, http, manager, payload, car_location,
        )
        assert custody_revision == 1

        # Genuine company-owned largest display UOM: 1 PACK = 8 BASE.
        # The manager intends 3 packs + 3 base = 27 BASE, not 3 nor 24.
        async with pg.session() as db:
            outer = UOM(
                name="X01 PACK " + uuid4().hex[:8],
                code="X01" + uuid4().hex[:9],
            )
            db.add(outer)
            await db.flush()
            db.add(ProductUomConversion(
                company_id=home.company_id,
                product_variant_id=home.variant_id,
                from_uom_id=outer.id, to_uom_id=home.uom_id,
                numerator=Decimal("8"), denominator=Decimal("1"),
                quantity_scale=0,
            ))
            await db.commit()

        uom_path = "/dispatch/route-load/uom"
        params = {"vehicle_id": car_id, "product_ids": [home.variant_id]}
        metadata = await http.get(uom_path, headers=manager, params=params)
        assert metadata.status_code == 200, metadata.text
        unit = metadata.json()[product_id]
        assert unit["display_factor_to_base"] == "8"
        assert unit["display_uom_name"].startswith("X01 PACK")
        assert (3 * int(unit["display_factor_to_base"]) + 3) == 27

        foreign_uom = await http.get(uom_path, headers=foreign_manager, params=params)
        assert foreign_uom.status_code in (403, 404), foreign_uom.text

        before = await _snapshot(pg, home, [car_location])
        assert _total(before, car_location) == Decimal("25")
        target = {**payload,
            "inventory_base": {product_id: "27"},
            "expected_inventory_base": {product_id: "25"},
        }
        no_auth = await http.post("/dispatch/route", json=target)
        assert no_auth.status_code == 401
        rejected = await http.post("/dispatch/route", headers=foreign_manager, json=target)
        assert rejected.status_code in (400, 403, 404, 409, 422)
        assert await _snapshot(pg, home, [car_location]) == before

        # Deliberate lost response AFTER the actual server commits to PG16.
        dropped = LoseRoute201()
        async with httpx.AsyncClient(
            transport=dropped, base_url="http://x01-committed-lost201.test",
            timeout=30,
        ) as unreliable:
            with pytest.raises(httpx.ReadError):
                await unreliable.post("/dispatch/route", headers=manager, json=target)
        assert dropped.dropped

        operation = await http.get(
            f"/dispatch/route/create-operations/{request_id}", headers=manager,
        )
        assert operation.status_code == 200 and operation.json()["state"] == "COMMITTED"
        after_load = await _snapshot(pg, home, [car_location])
        assert _total(after_load, car_location) == Decimal("27")
        assert _total(after_load, home.location_id) == _total(
            before, home.location_id,
        ) - Decimal("2")
        assert after_load["movements"] > before["movements"]
        assert after_load["cost_events"] == before["cost_events"]

        replay = await http.post("/dispatch/route", headers=manager, json=target)
        assert replay.status_code == 201, replay.text
        route_id = int(replay.json()["route_id"])
        assert await _snapshot(pg, home, [car_location]) == after_load
        altered = await http.post(
            "/dispatch/route", headers=manager,
            json={**target, "inventory_base": {product_id: "28"}},
        )
        assert altered.status_code == 409
        assert await _snapshot(pg, home, [car_location]) == after_load

        # The same real vehicle later returns precisely three base units.
        # No internal batch choice, implicit carton conversion or double replay.
        adjust_path = f"/dispatch/route/{route_id}/adjust_inventory"
        adjustment = {
            "request_id": str(uuid4()),
            "context": await _route_adjust_context(pg, route_id),
            "deltas": [{"product_id": home.variant_id, "delta_base": "-3"}],
        }
        expected = {
            **manager,
            "X-Dispatch-Expected-Vehicle-Id": str(car_id),
            "X-Dispatch-Expected-Source-Warehouse-Id": str(home.location_id),
        }
        returned = await http.put(adjust_path, headers=expected, json=adjustment)
        assert returned.status_code == 200, returned.text
        after_unload = await _snapshot(pg, home, [car_location])
        assert _total(after_unload, car_location) == Decimal("24")
        assert _total(after_unload, home.location_id) == _total(
            after_load, home.location_id,
        ) + Decimal("3")
        assert after_unload["movements"] > after_load["movements"]
        assert after_unload["cost_events"] == after_load["cost_events"]
        same_adjust = await http.put(adjust_path, headers=expected, json=adjustment)
        assert same_adjust.status_code == 200
        assert same_adjust.json() == returned.json()
        assert await _snapshot(pg, home, [car_location]) == after_unload

        # M06 transition on the exact newly accepted/loaded car, not an
        # unrelated test fixture: POSTPONE releases resources without stock.
        lifecycle = f"/dispatch/route/{route_id}/lifecycle"
        postpone = await http.put(
            lifecycle, headers=manager, json=_body("POSTPONE", 1),
        )
        assert postpone.status_code == 200, postpone.text
        assert postpone.json()["status"] == "postponed"
        available = await http.get(availability_path, headers=manager)
        assert available.status_code == 200
        row = next(
            x for x in available.json()["vehicles"] if x["id"] == str(car_id)
        )
        assert row["available"] is True and row["code"] == "AVAILABLE"
        assert await _snapshot(pg, home, [car_location]) == after_unload

        resume = await http.put(
            lifecycle, headers=manager,
            json=_body("RESUME", 2, driver=rep_id,
                       vehicle=car_id, custody=custody_revision),
        )
        assert resume.status_code == 200, resume.text
        assert resume.json()["status"] == "active"
        assert await _snapshot(pg, home, [car_location]) == after_unload
        print("X01_REAL_C03_TO_UOM_LOAD_UNLOAD_M06_RESUME_PASS", {
            "base_from": "25", "base_loaded": "27", "base_returned": "24",
            "display_factor": "8", "load_uuid_replayed": True,
            "unload_uuid_replayed": True, "custody_revision": custody_revision,
            "no_lifecycle_movements": True,
        }, flush=True)
