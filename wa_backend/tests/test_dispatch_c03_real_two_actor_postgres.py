"""C03 genuine signed review / FIELD physical inspection / manager reconciliation.

Disposable NOBYPASSRLS PG16, real canonical Bearer and physical stock only.
The stock loader is the independently accepted C02 stock-movement fixture.
"""
from __future__ import annotations
import os
from uuid import uuid4

import pytest

from tests.test_dispatch_m03_period_postgres import gate, _headers
from tests.test_dispatch_c01_c02_custody_postgres import (
    _setup_cars, _login_owner, _movement_count, _offer,
)

pytestmark = [
    pytest.mark.skipif(os.getenv("RUN_C03_CUSTODY_PG16") != "1",
                       reason="C03 independent disposable PG16 only"),
    pytest.mark.asyncio(loop_scope="module"),
]


async def test_c03_signed_real_two_actor_stock_review_and_lost_reply(gate):
    g = gate
    (vehicle, location, _, _), _, _ = await _setup_cars(g)
    manager = await _login_owner(g)
    foreign_owner = await _login_owner(g, g.foreign)
    root = f"/vehicles/{vehicle}/custody"
    preview_path = f"/driver/vehicles/{vehicle}/custody/offer-preview"
    confirm_path = f"/driver/vehicles/{vehicle}/custody/confirm"
    before = await _movement_count(g)

    ready = await g.client.get(root + "/readiness", headers=manager)
    assert ready.status_code == 200 and ready.json()["state"] == "NEEDS_REVIEW"
    review = await g.client.get(root + "/stock-review", headers=manager)
    assert review.status_code == 200, review.text
    data = review.json()
    assert data["vehicle_id"] == vehicle and data["vehicle_plate"]
    assert data["stock_lines"] and data["stock_snapshot"] == ready.json()["stock_snapshot"]
    assert "batch_id" not in data["stock_lines"][0]  # no internal DB IDs for counting
    assert data["stock_lines"][0]["product_name"]
    assert data["stock_lines"][0]["batch_number"]

    assert (await g.client.get(root + "/stock-review")).status_code == 401
    assert (await g.client.get(root + "/stock-review", headers=foreign_owner)).status_code in (403, 404)
    offer = await _offer(g, manager, vehicle, g.field.driver.id, ready.json())
    offered = offer["offer_token"]

    # FIELD preview requires actual live identity, capability, correct target,
    # correct company and a signed, fresh offer. No GET query includes secrets.
    assert (await g.client.post(preview_path, json={"offer_token": offered})).status_code == 401
    for bad_field in (g.other_token, g.foreign_token):
        denied = await g.client.post(preview_path, headers=_headers(bad_field),
                                     json={"offer_token": offered})
        assert denied.status_code == 403, denied.text
    tampered = offered[:-5] + ("a" if offered[-5] != "a" else "b") + offered[-4:]
    denied = await g.client.post(preview_path, headers=_headers(g.token),
                                 json={"offer_token": tampered})
    assert denied.status_code == 409, denied.text
    accepted_preview = await g.client.post(preview_path, headers=_headers(g.token),
                                          json={"offer_token": offered})
    assert accepted_preview.status_code == 200, accepted_preview.text
    p = accepted_preview.json()
    assert p["vehicle_id"] == vehicle
    assert p["vehicle_plate"] == data["vehicle_plate"]
    assert p["stock_snapshot"] == data["stock_snapshot"]
    assert p["stock_lines"] == data["stock_lines"]
    assert await _movement_count(g) == before

    receipt = await g.client.post(confirm_path, headers=_headers(g.token), json={
        "offer_token": offered, "confirmed_stock_snapshot": p["stock_snapshot"],
        "receiver_confirms_physical_count": True,
    })
    assert receipt.status_code == 200, receipt.text
    operation = str(uuid4())
    status = await g.client.get(root + f"/accept-operations/{operation}", headers=manager)
    assert status.status_code == 200 and status.json()["state"] == "UNKNOWN"
    assert (await g.client.get(root + f"/accept-operations/{operation}",
                               headers=foreign_owner)).status_code in (403, 404)
    body = {"request_id": operation, "receiver_proof": receipt.json()["receiver_proof"]}
    complete = await g.client.post(root + "/accept", headers=manager, json=body)
    assert complete.status_code == 201 and complete.json()["state"] == "ACCEPTED", complete.text
    assert complete.json()["stock_movements"] == 0
    confirmed = await g.client.get(root + f"/accept-operations/{operation}", headers=manager)
    assert confirmed.status_code == 200 and confirmed.json()["state"] == "COMMITTED"
    assert confirmed.json()["epoch_id"] == complete.json()["epoch_id"]
    replay = await g.client.post(root + "/accept", headers=manager, json=body)
    assert replay.status_code == 201 and replay.json()["replayed"] is True, replay.text
    assert await _movement_count(g) == before

    # The accepted car must be selectable only for the SAME real FIELD rep.
    availability = await g.client.get("/dispatch/launch/resource-availability",
        headers=manager, params={
            "selected_driver_id": g.field.driver.id,
            "selected_vehicle_id": vehicle,
        })
    assert availability.status_code == 200
    matches = [v for v in availability.json()["vehicles"] if v["id"] == str(vehicle)]
    assert len(matches) == 1 and matches[0]["code"] == "AVAILABLE"
    print("C03_SIGNED_FIELD_STOCK_REVIEW_MANAGER_RECONCILIATION=PASS", flush=True)
