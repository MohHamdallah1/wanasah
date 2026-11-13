"""D17 browser acceptance fixture: genuine PG16 actors, car custody and source product.

Opt-in ONLY for the isolated 127.0.0.1:55439 no-lot PostgreSQL test gate.
No fake HTTP, authorization overrides or production changes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from domains.identity.models import CompanyPrincipal
from models import Company
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_dispatch_route_launch_d07_postgres import _prepared_route
from tests.test_dispatch_shop_finance_edit_v1_postgres import _owner, _real_http

STATE = Path(os.environ.get("WANASAH_DISPATCH_D17_BROWSER_STATE",
                            "/tmp/dispatch-d17-real-browser-private.json"))
pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_DISPATCH_D17_BROWSER_GATE") != "1",
                       reason="Dedicated isolated signed PG16 D17 visual gate"),
    pytest.mark.asyncio(loop_scope="function"),
]


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_seed_real_car_and_warehouse_for_d17(pg):
    assert not STATE.exists(), "D17 accepted only with a fresh private fixture"
    home = pg.tenants[0]
    _request_id, proposed, vehicle_location = await _prepared_route(pg, home)
    async with pg.session() as db:
        code = await db.scalar(select(Company.company_code).where(
            Company.id == home.company_id))
        username = await db.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.id == home.owner.context.principal_id))
    assert code and username
    async with _real_http() as client:
        owner_header = await _owner(client, pg, home)
        base = await client.get("/dispatch/inventory/" + str(proposed["vehicle_id"]),
                                headers=owner_header)
        assert base.status_code == 200, base.text
        assert isinstance(base.json(), list) and base.json()
        first = await client.get("/dispatch/products", params={
            "purpose": "LOAD",
            "vehicle_id": proposed["vehicle_id"],
            "warehouse_id": proposed["source_location_id"],
            "limit": 80,
        }, headers=owner_header)
        assert first.status_code == 200, first.text
        assert first.json()["items"], first.text
        assert len(first.json()["items"]) <= 80
        car_ids = {str(x["product_id"]) for x in base.json()}
        stock_ids = {str(x["id"]) for x in first.json()["items"]}
        assert car_ids and stock_ids
    payload = {
        "credentials": {"code": str(code), "username": str(username),
                        "password": "NoLotSyntheticFixture123"},
        "companyId": int(home.company_id),
        "vehicleId": str(proposed["vehicle_id"]),
        "warehouseId": str(proposed["source_location_id"]),
        "productId": str(home.variant_id),
        "carProductIds": sorted(car_ids),
        "sourceProductIds": sorted(stock_ids),
        "vehicleLocation": int(vehicle_location),
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(payload), encoding="utf-8")
    STATE.chmod(0o600)
    print("D17_SIGNED_PG16_FIXTURE_PASS="+json.dumps({
        "carRows": len(car_ids), "firstWarehouseRows": len(stock_ids),
        "sameStock": bool(car_ids & stock_ids),
    }), flush=True)
