"""D06 read-only authorization audit of EXACT approved runtime MAIN.

New synthetic data in disposable PG16 only. Do not merge this audit harness.
No mocks, FastAPI dependency overrides, business-policy redaction or grants.
"""
from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from models import (
    DispatchRoute, Permission, Role, Shop, UserLocationAccess, Zone, role_permissions,
)
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_dispatch_shop_finance_edit_v1_postgres import _real_http, _token, _owner
from tests.test_dispatch_p0_route_stock_safety_postgres import _vehicle


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_DISPATCH_D06_PG_GATE") != "1",
        reason="Only dedicated disposable restricted PG16 D06 evidence gate",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


def _ids(response):
    assert response.status_code == 200, response.text
    return {int(row["id"]) for row in response.json()}


def _assert_shop(row, *, name, phone, balance, cap, zone):
    assert row["name"] == name, row
    assert row["phone"] == phone, row
    assert row["zoneId"] == str(zone), row
    assert Decimal(str(row["initialDebt"])) == Decimal(balance), row
    assert Decimal(str(row["maxDebtLimit"])) == Decimal(cap), row
    for field in ("name", "phone", "initialDebt", "maxDebtLimit", "zoneId", "owner", "mapLink"):
        assert field in row, field


async def _seed_shop(gate, tenant, party, title, balance, cap):
    async with gate.session(party) as db:
        zone = Zone(company_id=tenant.company_id, name=title + " Zone " + uuid4().hex[:8], is_active=True)
        db.add(zone)
        await db.flush()
        phone = title[:7] + uuid4().hex[:11]
        shop = Shop(
            company_id=tenant.company_id,
            name=title + " Shop",
            zone_id=zone.id,
            phone_number=phone,
            contact_person="D06 contact " + title,
            current_balance=Decimal(balance),
            max_debt_limit=Decimal(cap),
            is_active=True,
            is_archived=False,
        )
        db.add(shop)
        await db.flush()
        ids = (int(zone.id), int(shop.id))
        await db.commit()
        return ids, phone


async def _grant_a1_read(gate, tenant):
    async with gate.session() as db:
        permission = await db.scalar(select(Permission).where(Permission.code == "dispatch.read"))
        assert permission is not None
        role = Role(company_id=tenant.company_id, name="D06 Warehouse-only read " + uuid4().hex[:8])
        db.add(role)
        await db.flush()
        await db.execute(role_permissions.insert().values(
            company_id=tenant.company_id, role_id=role.id, permission_id=permission.id
        ))
        db.add(UserLocationAccess(
            company_id=tenant.company_id,
            role_id=role.id,
            driver_id=tenant.ordinary.driver_id,
            location_id=tenant.location_id,
        ))
        await db.commit()
        return int(role.id)


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_d06_a1_a2_b_real_http_and_read_field_matrix(pg):
    """Actual Backoffice bearer, 2 A warehouses and separate B RLS tenant."""
    home, foreign = pg.tenants
    assert home.company_id != foreign.company_id
    assert home.location_id != home.other_location_id
    assert home.company_id > 0 and foreign.company_id > 0

    (zone_a1, shop_a1), phone_a1 = await _seed_shop(
        pg, home, 0, "D06-A1", "123.125", "456.500"
    )
    (zone_a2, shop_a2), phone_a2 = await _seed_shop(
        pg, home, 0, "D06-A2", "789.125", "999.500"
    )
    (zone_b, shop_b), phone_b = await _seed_shop(
        pg, foreign, 1, "D06-B", "25.125", "50.500"
    )
    assert len({zone_a1, zone_a2, zone_b}) == 3
    assert len({shop_a1, shop_a2, shop_b}) == 3

    # Genuine dispatch vehicle/custody records; route visibility also requires
    # that exact vehicle-location grant, NOT only source Warehouse permission.
    vehicle_a1, vehicle_loc_a1 = await _vehicle(pg, home)
    vehicle_a2, vehicle_loc_a2 = await _vehicle(pg, home)
    assert vehicle_a1 != vehicle_a2 and vehicle_loc_a1 != vehicle_loc_a2
    async with pg.session() as db:
        r1 = DispatchRoute(
            company_id=home.company_id, zone_id=zone_a1,
            driver_id=home.owner.driver_id, vehicle_id=vehicle_a1,
            source_location_id=home.location_id, status="waiting",
        )
        r2 = DispatchRoute(
            company_id=home.company_id, zone_id=zone_a2,
            driver_id=home.ordinary.driver_id, vehicle_id=vehicle_a2,
            source_location_id=home.other_location_id, status="waiting",
        )
        db.add_all([r1, r2])
        await db.flush()
        route_a1, route_a2 = int(r1.id), int(r2.id)
        await db.commit()

    role_id = await _grant_a1_read(pg, home)
    async with _real_http() as client:
        owner_a = await _owner(client, pg, home)
        owner_b = await _owner(client, pg, foreign)
        limited = await _token(client, pg, home, home.ordinary, "SyntheticFixture123")

        for path in ("/dispatch/init", "/dispatch/shops", "/dispatch/active_routes"):
            missing = await client.get(path)
            assert missing.status_code == 401, (path, missing.status_code, missing.text)
            invalid = await client.get(path, headers={"Authorization": "Bearer invalid-test-token"})
            assert invalid.status_code == 401, (path, invalid.status_code, invalid.text)

        owner_shops = await client.get("/dispatch/shops", headers=owner_a)
        owner_rows = {int(row["id"]): row for row in owner_shops.json()}
        assert {shop_a1, shop_a2} <= set(owner_rows) and shop_b not in owner_rows
        foreign_shops = await client.get("/dispatch/shops", headers=owner_b)
        foreign_rows = {int(row["id"]): row for row in foreign_shops.json()}
        assert shop_b in foreign_rows and not ({shop_a1, shop_a2} & set(foreign_rows))
        _assert_shop(foreign_rows[shop_b], name="D06-B Shop", phone=phone_b,
                     balance="25.125", cap="50.500", zone=zone_b)
        print("D06_OWNER_A_B_SHOP_RLS PASS ownerA=A1+A2; ownerB=B_only")

        # A1-only dispatch.read does NOT imply company-wide warehouse scope.
        initial = await client.get("/dispatch/init", headers=limited)
        assert initial.status_code == 200, initial.text
        warehouse_ids = {int(w["id"]) for w in initial.json()["warehouses"]}
        zone_ids = {int(z["id"]) for z in initial.json()["zones"]}
        assert warehouse_ids == {home.location_id}, warehouse_ids
        assert {zone_a1, zone_a2} <= zone_ids and zone_b not in zone_ids
        assert initial.json()["vehicles"] == []
        counts = {int(z["id"]): z["shopsCount"] for z in initial.json()["zones"]}
        assert counts[zone_a1] == counts[zone_a2] == 1
        print("D06_A1_READER_INIT PASS warehouse=A1_only, zones=A1+A2, count_A2=1")

        response = await client.get("/dispatch/shops", headers=limited)
        visible = {int(row["id"]): row for row in response.json()}
        assert {shop_a1, shop_a2} <= set(visible) and shop_b not in visible
        _assert_shop(visible[shop_a1], name="D06-A1 Shop", phone=phone_a1,
                     balance="123.125", cap="456.500", zone=zone_a1)
        _assert_shop(visible[shop_a2], name="D06-A2 Shop", phone=phone_a2,
                     balance="789.125", cap="999.500", zone=zone_a2)
        print("D06_A1_READER_SHOPS PASS A2_name,phone,initialDebt=789.125,"
              "maxDebtLimit=999.500,zoneId exposed; B_not_exposed")

        # A1 source grant without corresponding vehicle custody grants means
        # no visible operational route; Owner still has both.
        owner_routes = _ids(await client.get("/dispatch/active_routes", headers=owner_a))
        assert {route_a1, route_a2} <= owner_routes
        scoped_initial = _ids(await client.get("/dispatch/active_routes", headers=limited))
        assert route_a1 not in scoped_initial and route_a2 not in scoped_initial
        denied_route = await client.get(
            f"/dispatch/active_routes?route_id={route_a2}", headers=limited
        )
        assert _ids(denied_route) == set()
        print("D06_ROUTE_A1_ONLY_SOURCE PASS no_vehicle_grant=empty; ownerA=A1+A2")

        # Adding A1 vehicle-location READ keeps A2 route impossible and does not
        # add dispatch.execute / shortage.read or any new financial capability.
        async with pg.session() as db:
            db.add(UserLocationAccess(
                company_id=home.company_id, role_id=role_id,
                driver_id=home.ordinary.driver_id, location_id=vehicle_loc_a1,
            ))
            await db.commit()
        with_vehicle = _ids(await client.get("/dispatch/active_routes", headers=limited))
        assert route_a1 in with_vehicle and route_a2 not in with_vehicle, with_vehicle
        assert _ids(await client.get(
            f"/dispatch/active_routes?route_id={route_a2}", headers=limited
        )) == set()
        denied_shortages = await client.get("/dispatch/shortages", headers=limited)
        assert denied_shortages.status_code == 403, denied_shortages.text
        denied_write = await client.put(
            f"/dispatch/shops/{shop_a1}", headers=limited, json={"name": "D06 forbidden edit"}
        )
        assert denied_write.status_code == 403, denied_write.text
        print("D06_A1_ROUTE_READ PASS A1_route_only_with_vehicle, A2_denied, shortage=403,edit=403")

        # Supplying company/warehouse IDs in a query cannot override trusted
        # tenant/access context. Company B records stay isolated.
        malicious = await client.get(
            f"/dispatch/shops?company_id={foreign.company_id}&warehouse_id={home.other_location_id}",
            headers=limited,
        )
        assert malicious.status_code == 200, malicious.text
        malicious_rows = {int(row["id"]) for row in malicious.json()}
        assert {shop_a1, shop_a2} <= malicious_rows and shop_b not in malicious_rows
        assert _ids(await client.get(
            f"/dispatch/active_routes?route_id={route_a2}&company_id={foreign.company_id}",
            headers=limited,
        )) == set()
        async with pg.session(1) as db:
            assert await db.scalar(select(Shop.id).where(Shop.id == shop_a1)) is None
        print("D06_MALICIOUS_FOREIGN_IDS PASS B_read_denied_RLS; ignored_query_params_no_company_switch")

        # Warehouse switch with the SAME bearer: replace A1 + vehicle grants
        # with only A2 + A2 vehicle, proves grant read is not cached by JWT.
        async with pg.session() as db:
            await db.execute(delete(UserLocationAccess).where(
                UserLocationAccess.company_id == home.company_id,
                UserLocationAccess.driver_id == home.ordinary.driver_id,
                UserLocationAccess.role_id == role_id,
            ))
            db.add_all([
                UserLocationAccess(
                    company_id=home.company_id, role_id=role_id,
                    driver_id=home.ordinary.driver_id, location_id=home.other_location_id,
                ),
                UserLocationAccess(
                    company_id=home.company_id, role_id=role_id,
                    driver_id=home.ordinary.driver_id, location_id=vehicle_loc_a2,
                ),
            ])
            await db.commit()
        switched_init = await client.get("/dispatch/init", headers=limited)
        assert switched_init.status_code == 200, switched_init.text
        assert {int(x["id"]) for x in switched_init.json()["warehouses"]} == {
            home.other_location_id
        }
        assert {zone_a1, zone_a2} <= {int(z["id"]) for z in switched_init.json()["zones"]}
        switched_routes = _ids(await client.get("/dispatch/active_routes", headers=limited))
        assert route_a1 not in switched_routes and route_a2 in switched_routes
        switched_shops = {int(z["id"]): z for z in (
            await client.get("/dispatch/shops", headers=limited)
        ).json()}
        assert {shop_a1, shop_a2} <= set(switched_shops) and shop_b not in switched_shops
        print("D06_A1_TO_A2_SWITCH PASS route_A2_only, warehouse_A2_only, shops_both")

        # Revocation after token issue must fail immediately in all three reads.
        async with pg.session() as db:
            await db.execute(delete(UserLocationAccess).where(
                UserLocationAccess.company_id == home.company_id,
                UserLocationAccess.driver_id == home.ordinary.driver_id,
                UserLocationAccess.role_id == role_id,
            ))
            await db.commit()
        for path in ("/dispatch/init", "/dispatch/shops", "/dispatch/active_routes"):
            revoked = await client.get(path, headers=limited)
            assert revoked.status_code == 403, (path, revoked.status_code, revoked.text)
        # Owner token and foreign Owner token retain their distinct real scopes.
        assert {shop_a1, shop_a2} <= _ids(
            await client.get("/dispatch/shops", headers=owner_a)
        )
        assert shop_b in _ids(await client.get("/dispatch/shops", headers=owner_b))
        print("D06_REVOKE_403_AND_OWNER_CONTINUITY PASS 3/3 fresh reads revoked")

    print("D06_FINAL PG16_NOBYPASSRLS_FORCE + BACKOFFICE_REAL_BEARER PASS A1/A2/B")
