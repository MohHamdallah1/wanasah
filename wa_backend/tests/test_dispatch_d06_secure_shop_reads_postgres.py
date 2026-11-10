"""D06 D03 owner-approved Shop/Zone company masters, route-scoped reads and money privacy.

Actual PG16 restricted app role + FORCE RLS, signed independent Backoffice
Bearer clients and additive migration. No in-process dependency overrides,
role claims, service stubs or cross-tenant shortcut. A1/A2 are route sources,
never Shop owners.
"""
from __future__ import annotations

from decimal import Decimal
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from models import (
    Company, Permission, Role, Shop, ShortageRequest, UserLocationAccess, UserRole, Zone,
    role_permissions,
)
from domains.identity.models import CompanyPrincipal
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_dispatch_route_launch_d07_postgres import _prepared_route
from tests.test_dispatch_shop_finance_edit_v1_postgres import (
    _grant_company_dispatch_capability, _owner, _real_http, _token,
)
pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_DISPATCH_D06_PG_GATE") != "1",
        reason="Requires isolated restricted PostgreSQL16 real Backoffice Bearer D06 gate",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _location_read(gate, tenant, *, warehouse: int, vehicle_custody: int) -> int:
    async with gate.session() as db:
        permission = await db.scalar(select(Permission).where(
            Permission.code == "dispatch.read",
        ))
        assert permission
        role = Role(company_id=tenant.company_id, name="D06 A1 only " + uuid4().hex[:9])
        db.add(role)
        await db.flush()
        await db.execute(role_permissions.insert().values(
            company_id=tenant.company_id, role_id=role.id, permission_id=permission.id,
        ))
        for location in (warehouse, vehicle_custody):
            db.add(UserLocationAccess(
                company_id=tenant.company_id,
                driver_id=tenant.ordinary.driver_id,
                location_id=location,
                role_id=role.id,
            ))
        role_id = int(role.id)
        await db.commit()
        return role_id


async def _second_zone_shops(gate, tenant, zone_id: int):
    """Create an unassigned Shop IN the route Zone and a separate A2 Zone Shop."""
    async with gate.session() as db:
        zone_b = Zone(
            company_id=tenant.company_id,
            name="D06 A2 " + uuid4().hex[:10],
            is_active=True,
        )
        db.add(zone_b)
        await db.flush()
        names = [
            ("D06 no-visit same-zone " + uuid4().hex[:9], zone_id, Decimal("301.125")),
            ("D06 A2 " + uuid4().hex[:10], int(zone_b.id), Decimal("901.125")),
        ]
        rows = []
        for name, zid, money in names:
            row = Shop(
                company_id=tenant.company_id, zone_id=zid, name=name,
                phone_number="55" + str(uuid4().int)[-8:],
                contact_person="Contact D06",
                current_balance=money,
                max_debt_limit=Decimal("990.125"),
                is_active=True, is_archived=False,
            )
            db.add(row)
            await db.flush()
            rows.append(int(row.id))
        zone_b_id = int(zone_b.id)
        await db.commit()
    return zone_b_id, rows[0], rows[1]


async def _shop_data(client, auth):
    response = await client.get("/dispatch/shops", headers=auth)
    return response, {x["id"]: x for x in response.json()} if response.status_code == 200 else {}


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_d06_owner_company_a1_a2_companyfinance_revoke_same_bearer(pg):
    home, foreign = pg.tenants
    # Reuse accepted D07 authentic commercial+FIELD fixture; no repeat D07 lost-201.
    _, route_request, vehicle_custody = await _prepared_route(pg, home)
    async with _real_http() as client:
        owner = await _owner(client, pg, home)
        # D06 is exclusively BACKOFFICE: a genuine, signed Flutter FIELD token
        # from the persisted field principal must not access these Dashboard URLs.
        async with pg.session() as db:
            field_name = await db.scalar(select(CompanyPrincipal.username).where(
                CompanyPrincipal.company_id == home.company_id,
                CompanyPrincipal.principal_type == "FIELD_REPRESENTATIVE",
            ))
            company_code = await db.scalar(select(Company.company_code).where(
                Company.id == home.company_id,
            ))
        assert field_name and company_code
        field_login = await client.post("/driver/login", json={
            "company_code": company_code, "username": field_name,
            "password": "SyntheticFixture123",
        })
        assert field_login.status_code == 200, field_login.text
        field_headers = {"Authorization": "Bearer " + field_login.json()["token"]}
        for field_only_url in (
            "/dispatch/init", "/dispatch/shops", "/dispatch/active_routes",
            "/dispatch/shortages",
        ):
            rejected = await client.get(field_only_url, headers=field_headers)
            assert rejected.status_code in (401, 403), (field_only_url, rejected.text)
        launched = await client.post("/dispatch/route", json=route_request, headers=owner)
        assert launched.status_code == 201, launched.text

        async with pg.session() as db:
            assigned = await db.scalar(select(Shop).where(
                Shop.company_id == home.company_id, Shop.zone_id == route_request["zone_id"],
            ))
            assert assigned
            assigned_id = str(assigned.id)
            assigned_balance = str(assigned.current_balance)
        zone_b, no_visit, shop_b = await _second_zone_shops(
            pg, home, route_request["zone_id"],
        )
        route_zone = str(route_request["zone_id"])
        # Foreign company B must not appear even for a company-wide grant.
        async with pg.session(1) as db:
            foreign_zone = Zone(company_id=foreign.company_id,
                                name="D06 foreign " + uuid4().hex[:8], is_active=True)
            db.add(foreign_zone)
            await db.flush()
            foreign_shop = Shop(company_id=foreign.company_id, zone_id=foreign_zone.id,
                                name="D06 private B", current_balance=Decimal("500.125"),
                                max_debt_limit=Decimal("800.125"), is_active=True)
            db.add(foreign_shop)
            await db.flush()
            foreign_id = str(foreign_shop.id)
            await db.commit()

        owner_resp, owner_shops = await _shop_data(client, owner)
        assert owner_resp.status_code == 200
        assert {assigned_id, str(no_visit), str(shop_b)} <= set(owner_shops)
        assert owner_shops[assigned_id]["financeRedacted"] is False
        assert owner_shops[assigned_id]["initialDebt"] is not None
        assert owner_shops[str(shop_b)]["maxDebtLimit"] == "990.125"
        assert foreign_id not in owner_shops or owner_shops.get(foreign_id, {}).get("name") != "D06 private B"

        limited_role = await _location_read(
            pg, home, warehouse=home.location_id, vehicle_custody=vehicle_custody,
        )
        ordinary = await _token(
            client, pg, home, home.ordinary, "SyntheticFixture123",
        )
        limited_resp, limited = await _shop_data(client, ordinary)
        assert limited_resp.status_code == 200
        assert assigned_id in limited, limited
        assert str(no_visit) not in limited, "same Zone is NOT Shop ownership"
        assert str(shop_b) not in limited, "A2 Company Shop requires genuine assignment"
        assert limited[assigned_id]["initialDebt"] is None
        assert limited[assigned_id]["maxDebtLimit"] is None
        assert limited[assigned_id]["financeRedacted"] is True
        scope = await client.get("/dispatch/init", headers=ordinary)
        assert scope.status_code == 200, scope.text
        assert scope.json()["shopScope"] == "authorized_routes"
        assert [x["id"] for x in scope.json()["zones"]] == [route_zone]
        assert scope.json()["zones"][0]["shopsCount"] == 1
        routes = await client.get("/dispatch/active_routes", headers=ordinary)
        assert routes.status_code == 200 and len(routes.json()) == 1
        # Grant company-wide dispatch.read; directory expands, financials remain null.
        company_read_role = await _grant_company_dispatch_capability(
            pg, home, home.ordinary, "dispatch.read",
        )
        company_resp, directory = await _shop_data(client, ordinary)
        assert company_resp.status_code == 200
        assert {assigned_id, str(no_visit), str(shop_b)} <= set(directory)
        assert all(row["financeRedacted"] is True and row["initialDebt"] is None
                   and row["maxDebtLimit"] is None for row in directory.values())
        whole = await client.get("/dispatch/init", headers=ordinary)
        assert whole.status_code == 200 and whole.json()["shopScope"] == "company"
        assert zone_b in {int(x["id"]) for x in whole.json()["zones"]}
        # Explicit financial permission is independent, company-only.
        finance_role = await _grant_company_dispatch_capability(
            pg, home, home.ordinary, "shop.financial.read",
        )
        permitted, published = await _shop_data(client, ordinary)
        assert permitted.status_code == 200
        assert published[assigned_id]["financeRedacted"] is False
        assert published[assigned_id]["initialDebt"] == f"{Decimal(assigned_balance):.3f}"
        assert published[str(shop_b)]["initialDebt"] == "901.125"
        assert published[str(shop_b)]["maxDebtLimit"] == "990.125"
        # Revoke SAME TOKEN. JWT is identity only; current live grants control response.
        async with pg.session() as db:
            await db.execute(delete(UserRole).where(
                UserRole.company_id == home.company_id, UserRole.driver_id == home.ordinary.driver_id,
                UserRole.role_id == finance_role,
            ))
            await db.commit()
        revoked, hidden = await _shop_data(client, ordinary)
        assert revoked.status_code == 200
        assert hidden[assigned_id]["initialDebt"] is None
        assert hidden[str(shop_b)]["maxDebtLimit"] is None
        # Revoke company-wide Shop master but retain only A1 active assigned route.
        async with pg.session() as db:
            await db.execute(delete(UserRole).where(
                UserRole.company_id == home.company_id, UserRole.driver_id == home.ordinary.driver_id,
                UserRole.role_id == company_read_role,
            ))
            await db.commit()
        narrow, narrowed = await _shop_data(client, ordinary)
        assert narrow.status_code == 200 and set(narrowed) == {assigned_id}
        assert narrowed[assigned_id]["financeRedacted"] is True
        async with pg.session() as db:
            await db.execute(delete(UserLocationAccess).where(
                UserLocationAccess.company_id == home.company_id,
                UserLocationAccess.driver_id == home.ordinary.driver_id,
                UserLocationAccess.role_id == limited_role,
            ))
            await db.commit()
        forbidden = await client.get("/dispatch/shops", headers=ordinary)
        assert forbidden.status_code == 403
        forbidden_init = await client.get("/dispatch/init", headers=ordinary)
        assert forbidden_init.status_code == 403
        assert (await client.get("/dispatch/shops")).status_code == 401
        assert (await client.get("/dispatch/active_routes", headers=ordinary)).status_code == 403


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_d06_shortage_search_unassigned_shop_direct_id_and_no_finance_escalation(pg):
    home, foreign = pg.tenants
    _, route_request, vehicle_custody = await _prepared_route(pg, home)
    async with _real_http() as client:
        owner = await _owner(client, pg, home)
        route = await client.post("/dispatch/route", json=route_request, headers=owner)
        assert route.status_code == 201, route.text
        async with pg.session() as db:
            assigned_id = await db.scalar(select(Shop.id).where(
                Shop.company_id == home.company_id, Shop.zone_id == route_request["zone_id"],
            ))
            assert assigned_id
        zone_b, no_visit, shop_b = await _second_zone_shops(pg, home, route_request["zone_id"])
        async with pg.session() as db:
            requests = []
            for zid, shop in ((route_request["zone_id"], assigned_id), (zone_b, shop_b)):
                record = ShortageRequest(company_id=home.company_id, zone_id=zid,
                    shop_id=shop, product_variant_id=home.variant_id,
                    quantity=2, status="pending")
                db.add(record)
                await db.flush()
                requests.append(int(record.id))
            await db.commit()
        await _location_read(pg, home, warehouse=home.location_id, vehicle_custody=vehicle_custody)
        await _grant_company_dispatch_capability(pg, home, home.ordinary, "shortage.read")
        # settlement.read cannot imply Shop finance or company-wide Shop directory.
        await _grant_company_dispatch_capability(pg, home, home.ordinary, "settlement.read")
        ordinary = await _token(client, pg, home, home.ordinary, "SyntheticFixture123")
        for path in ("/dispatch/shortages", f"/dispatch/shortages?shortage_id={requests[1]}"):
            response = await client.get(path, headers=ordinary)
            assert response.status_code == 200
            items = response.json()
            assert {x["id"] for x in items} <= {str(requests[0])}
            assert not any(x.get("shopId") == str(shop_b) for x in items)
        response, shops = await _shop_data(client, ordinary)
        assert response.status_code == 200 and set(shops) == {str(assigned_id)}
        assert shops[str(assigned_id)]["initialDebt"] is None
        # A company financial role assigned to a different tenant cannot grant money.
        assert (await client.get("/dispatch/shops", headers=await _owner(client, pg, foreign))).status_code == 200
