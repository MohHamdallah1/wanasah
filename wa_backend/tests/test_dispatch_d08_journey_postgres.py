"""D08 complete first-company real PG16/Backoffice HTTP fixture, consumed by real Chromium.

No production data, fake identities, mocked network or newly invented settlement authority.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.identity.models import CompanyPrincipal
from models import Company, Shop, Zone
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_dispatch_route_launch_d07_postgres import _prepared_route, _state
from tests.test_dispatch_shop_finance_edit_v1_postgres import _owner, _real_http

STATE = Path(os.getenv("WANASAH_DISPATCH_D08_STATE", "/tmp/dispatch-d08-journey.json"))

pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_DISPATCH_D08_GATE") != "1",
                       reason="Only approved disposable PG16 D08 journey"),
    pytest.mark.asyncio(loop_scope="function"),
]


def success(reply, status, label):
    assert reply.status_code == status, (label, reply.status_code, reply.text[:600])
    return reply.json()


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_first_company_zone_shop_import_reorder_archive_restore_and_route_fixture(pg):
    assert not STATE.exists(), "Fresh disposable company data required"
    tenant, foreign = pg.tenants
    request_id, launch_body, vehicle_location = await _prepared_route(pg, tenant)
    pre_launch = await _state(pg, tenant, request_id, vehicle_location)

    async with _real_http() as http:
        owner = await _owner(http, pg, tenant)
        foreign_owner = await _owner(http, pg, foreign)

        zone = success(await http.post("/dispatch/zones", headers=owner, json={
            "name": "D08 Field Zone " + uuid4().hex[:7],
        }), 201, "create zone")
        zone_id = int(zone["zone_id"])
        renamed = "D08 Updated Zone " + uuid4().hex[:7]
        success(await http.put(f"/dispatch/zones/{zone_id}", headers=owner, json={
            "name": renamed,
        }), 200, "edit zone")

        add = success(await http.post("/dispatch/shops", headers=owner, json={
            "name": "D08 New Shop", "zoneId": zone_id,
            "phone": "D08-" + uuid4().hex[:12],
            "initialDebt": "0", "maxDebtLimit": "0",
            "request_id": str(uuid4()),
        }), 201, "new shop")
        shop_id = int(add["shop_id"])
        success(await http.put(f"/dispatch/shops/{shop_id}", headers=owner, json={
            "name": "D08 Edited Shop",
        }), 200, "edit shop")
        imported = success(await http.post("/dispatch/shops/bulk_import", headers=owner, json={
            "zoneId": zone_id, "fileName": "d08_synthetic.csv",
            "shops": [{"name": "D08 Imported Shop A", "phone": "D8-" + uuid4().hex[:11],
                       "sequence": 20},
                      {"name": "D08 Imported Shop B", "phone": "D8-" + uuid4().hex[:11],
                       "sequence": 21}],
        }), 201, "import 2 shops")
        initial = success(await http.get("/dispatch/shops", headers=owner), 200, "list shops")
        new_rows = [x for x in initial if x.get("name") in {"D08 Edited Shop", "D08 Imported Shop A", "D08 Imported Shop B"}]
        assert len(new_rows) == 3, new_rows
        imported_ids = [int(x["id"]) for x in new_rows if x["name"].startswith("D08 Imported")]
        target_zone = int(launch_body["zone_id"])
        # Safe bulk move before route activation; sort/order is independent of custody.
        success(await http.put("/dispatch/shops/bulk_update", headers=owner, json=[
            {"id": str(imported_ids[0]), "zoneId": str(target_zone), "sequence": 3},
            {"id": str(imported_ids[1]), "sequence": 2},
        ]), 200, "bulk move/order")
        success(await http.put("/dispatch/shops/bulk_update", headers=owner, json=[
            {"id": str(shop_id), "archived": True},
        ]), 200, "archive shop")
        success(await http.put("/dispatch/shops/bulk_update", headers=owner, json=[
            {"id": str(shop_id), "archived": False},
        ]), 200, "restore shop")
        # Archive/restore Zone with automatic restoration of owned Shop provenance.
        success(await http.delete(f"/dispatch/zones/{zone_id}", headers=owner),
                200, "archive zone")
        archive = success(await http.get("/dispatch/zones/archived", headers=owner),
                          200, "read zone archive")
        assert any(int(z["id"]) == zone_id for z in archive)
        restored = success(await http.put(f"/dispatch/zones/{zone_id}/restore",
                                          headers=owner, json={
                                              "mode": "shops_archived_by_same_zone",
                                          }), 200, "restore zone")
        assert restored["restored_shops"] >= 1

        # Real foreign authenticated tenant must not read/alter original Shop or Zone.
        foreign_zones = success(await http.get("/dispatch/init", headers=foreign_owner),
                                200, "foreign init")
        assert all(int(z["id"]) != zone_id for z in foreign_zones["zones"])
        foreign_edit = await http.put(f"/dispatch/shops/{shop_id}",
                                      headers=foreign_owner, json={"name": "ILLEGAL"})
        assert foreign_edit.status_code in (403, 404), foreign_edit.text

        # Same authorized published Pricing/Tax/rounding and stock fixture as accepted D07.
        started = success(await http.post("/dispatch/route", headers=owner,
                                          json=launch_body), 201, "launch")
        route_id = int(started["route_id"])
        replay = success(await http.post("/dispatch/route", headers=owner,
                                         json=launch_body), 201, "same UUID replay")
        assert int(replay["route_id"]) == route_id
        post_launch = await _state(pg, tenant, request_id, vehicle_location)
        assert len(post_launch["route_ids"]) == len(pre_launch["route_ids"]) + 1
        assert len(post_launch["operations"]) == 1
        assert post_launch["movements"] == pre_launch["movements"] + 1
        assert post_launch["cost_events"] == pre_launch["cost_events"]
        totals = lambda record, location: sum(
            (Decimal(quantity) for loc, _batch, _status, quantity, _reserved
             in record["balances"] if int(loc) == int(location)), Decimal(0))
        assert totals(pre_launch, vehicle_location) == 25
        assert totals(post_launch, vehicle_location) == 20
        assert totals(post_launch, tenant.location_id) - totals(pre_launch, tenant.location_id) == 5
        recovered = success(await http.get(
            f"/dispatch/route/create-operations/{request_id}", headers=owner),
            200, "authoritative route recovery")
        assert recovered is not None

        denied = await http.delete(f"/dispatch/zones/{target_zone}", headers=owner)
        assert denied.status_code == 409, (denied.status_code, denied.text)
        # Confirm real Shop data survives archive/move and exactly one route is active.
        async with pg.session() as db:
            shop = await db.scalar(select(Shop).where(
                Shop.company_id == tenant.company_id, Shop.id == shop_id))
            assert shop and shop.name == "D08 Edited Shop" and not shop.is_archived
            z = await db.scalar(select(Zone).where(Zone.company_id == tenant.company_id,
                                                   Zone.id == zone_id))
            assert z and z.is_active and z.name == renamed

        async with AsyncSession(pg.admin_engine) as db:
            code = await db.scalar(select(Company.company_code).where(
                Company.id == tenant.company_id))
            username = await db.scalar(select(CompanyPrincipal.username).where(
                CompanyPrincipal.id == tenant.owner.context.principal_id))
        STATE.write_text(json.dumps({
            "companyId": tenant.company_id, "routeId": route_id,
            "vehicleId": launch_body["vehicle_id"],
            "variantId": tenant.variant_id,
            "driverId": launch_body["driver_id"],
            "zoneId": target_zone, "shopId": shop_id,
            "importedShopId": imported_ids[0],
            "vehicleLocationId": vehicle_location,
            "warehouseId": tenant.location_id,
            "credentials": {
                "code": code, "username": username,
                "password": "NoLotSyntheticFixture123",
            },
            "before_after": {
                "vehicle_before": "25", "vehicle_after_launch": "20",
                "warehouse_increase": "5",
                "route_created": 1,
                "movement_delta": post_launch["movements"] - pre_launch["movements"],
                "cost_event_delta": post_launch["cost_events"] - pre_launch["cost_events"],
            },
            "confirmed": {
                "zone_create_edit_archive_restore": True,
                "shop_create_edit_archive_restore": True,
                "import_two_shops": True,
                "bulk_move_and_reorder": True,
                "route_launch_and_same_uuid_replay": True,
                "active_route_blocks_zone_archive": True,
                "foreign_company_no_leak": True,
            },
        }), encoding="utf-8")
        print("D08_REAL_PG16_BEARER_BUSINESS_JOURNEY=" +
              json.dumps(json.loads(STATE.read_text())["confirmed"]), flush=True)
