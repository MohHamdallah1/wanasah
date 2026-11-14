"""C03-FINAL genuine PG16 scoped browser seed, never a production migration.

This isolated test leaves an authenticated tenant's *real* physical stock in
an unconfirmed C01 epoch, then writes a private local browser-login fixture.
Only the browser+FIELD/manager real HTTP flow is allowed to accept it.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

import pytest
from tests.field_authorization_phase3_fixture import PASSWORD
from tests.test_dispatch_m03_period_postgres import gate
from tests.test_dispatch_c01_c02_custody_postgres import (
    _setup_cars, _login_owner, _movement_count,
)

pytestmark = [
    pytest.mark.skipif(os.environ.get("RUN_C03_FINAL_BROWSER_PG16") != "1",
                       reason="C03-FINAL disposable PG16 live-browser acceptance only"),
    pytest.mark.asyncio(loop_scope="module"),
]


async def test_seed_real_unselectable_car_for_manager_browser(gate):
    g = gate
    path = Path(os.environ["WANASAH_C03_FINAL_BROWSER_STATE"])
    assert path.parent.exists() and not path.exists(), "Fresh private C03 evidence file required"
    unknown, different, empty = await _setup_cars(g)
    vehicle_id, location_id, stage, amount = unknown
    assert stage == "UNKNOWN" and amount == 12
    owner_headers = await _login_owner(g)
    original = await g.client.get(
        "/dispatch/launch/resource-availability", headers=owner_headers,
        params={"selected_driver_id":g.field.driver.id},
    )
    assert original.status_code == 200, original.text
    matched = [row for row in original.json()["vehicles"]
               if row["id"] == str(vehicle_id)]
    assert len(matched) == 1 and matched[0]["available"] is False
    assert matched[0]["code"] == "CUSTODY_NEEDS_REVIEW"
    ready = await g.client.get(
        f"/vehicles/{vehicle_id}/custody/readiness", headers=owner_headers,
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["state"] == "NEEDS_REVIEW"
    stock = await g.client.get(
        f"/vehicles/{vehicle_id}/custody/stock-review", headers=owner_headers,
    )
    assert stock.status_code == 200, stock.text
    assert sum(float(x["on_hand_base"]) for x in stock.json()["stock_lines"]) == 12
    count = await _movement_count(g)
    secret = {
        "credentials": {
            "company_code": g.company_code,
            "owner": g.owner_name, "field": g.field_name,
            "other_field": g.other_name,
            "password": PASSWORD,
        },
        "ownerPrincipal": int(g.owner.context.principal_id),
        "vehicleId": vehicle_id, "vehicleLabel": matched[0]["label"],
        "locationId": location_id,
        "fieldDriverId": int(g.field.driver.id),
        "stockSnapshot": stock.json()["stock_snapshot"],
        "stockLines": stock.json()["stock_lines"],
        "movementsBefore": count,
        "otherCar": int(different[0]),
    }
    path.write_text(json.dumps(secret, ensure_ascii=False), encoding="utf-8")
    print("C03_FINAL_DISPOSABLE_PG16_SIGNED_BLOCKED_CAR_SEEDED=PASS",flush=True)
