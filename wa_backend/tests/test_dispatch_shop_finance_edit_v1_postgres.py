"""#842: corrected Shop metadata edit money isolation — real PG16 + restricted Bearer HTTP.

The 100 -> 80 P0 is reproduced by genuine approved FIELD debt collection.
Opening receivable and credit ceiling are created through actual Owner HTTP.
The legacy metadata edit may carry old money, but NEVER writes that money.
No mock auth, dependency overrides, bypass RLS, fake ledger, or production DB.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import engine as http_runtime_engine
from domains.identity.models import CompanyPrincipal
from domains.inventory_vehicle_load.service import mutate_vehicle_load
from main import app
from models import (
    Company, InventoryBalance, InventoryCostEvent, InventoryMovement,
    Permission, Role, Shop, SystemAuditLog, UserRole, Visit, Zone,
    role_permissions,
)
from tests.canonical_actor_fixtures import FieldFixture
from tests.test_dispatch_p0_route_stock_safety_postgres import _vehicle
from tests.test_inbound_no_lot_frozen_postgres import checked_urls, pg  # noqa: F401
from tests.test_live_stock_v1_route_sale_unload_postgres import (
    _seed_commercial_master,
    _seed_mobile_uom_and_field,
)

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_SHOP_FINANCE_PG_GATE") != "1",
        reason="Only the approved disposable PG16 Shop finance safety gate",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


@asynccontextmanager
async def _real_http():
    runtime, _ = checked_urls()
    identity = lambda url: (
        url.drivername, url.host, url.port, url.database, url.username
    )
    if identity(http_runtime_engine.url) != identity(runtime):
        raise RuntimeError("Real Shop HTTP engine must be the checked disposable PG16 restricted DB")
    assert not app.dependency_overrides, "Real authentication/authorization required"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://dispatch-842-isolated-pg16.test",
            timeout=30,
        ) as client:
            yield client
    finally:
        # A new pytest function event loop cannot reuse an asyncpg engine pool
        # borrowed by a different loop, including after assertion failures.
        await http_runtime_engine.dispose()


async def _token(client, gate, tenant, actor, password):
    async with AsyncSession(gate.admin_engine) as seed:
        company_code = await seed.scalar(select(Company.company_code).where(
            Company.id == tenant.company_id
        ))
        username = await seed.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.id == actor.context.principal_id
        ))
    path = "/driver/login" if isinstance(actor, FieldFixture) else "/login"
    response = await client.post(
        path,
        json={"company_code": company_code, "username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


async def _owner(client, gate, tenant):
    return await _token(client, gate, tenant, tenant.owner, "NoLotSyntheticFixture123")


async def _zone(gate, tenant, party=0):
    async with gate.session(party) as db:
        zone = Zone(
            company_id=tenant.company_id,
            name=f"842 isolated shop zone {uuid4().hex[:10]}",
            is_active=True,
        )
        db.add(zone)
        await db.flush()
        identifier = int(zone.id)
        await db.commit()
        return identifier


async def _add_shop(client, owner_headers, zone_id, *, name=None,
                    balance="100.125", cap="150.500", jurisdiction_id=None):
    request = {
        "name": name or ("842 shop " + uuid4().hex[:12]),
        "zoneId": zone_id,
        "phone": "842-" + uuid4().hex[:11],
        "initialDebt": balance,
        "maxDebtLimit": cap,
    }
    if jurisdiction_id is not None:
        request["taxJurisdictionId"] = jurisdiction_id
    response = await client.post("/dispatch/shops", headers=owner_headers, json=request)
    assert response.status_code == 201, response.text
    return int(response.json()["shop_id"]), request


async def _fingerprint(gate, tenant, shop_id, *, party=0):
    async with gate.session(party) as db:
        row = (await db.execute(
            select(Shop.name, Shop.current_balance, Shop.max_debt_limit)
            .where(Shop.company_id == tenant.company_id, Shop.id == shop_id)
        )).one()
        actions = (await db.execute(
            select(SystemAuditLog.action_type, func.count(SystemAuditLog.id)).where(
                SystemAuditLog.company_id == tenant.company_id,
                SystemAuditLog.target_id == f"Shop_{shop_id}",
            ).group_by(SystemAuditLog.action_type)
        )).all()
        movements = int(await db.scalar(select(func.count()).select_from(
            InventoryMovement).where(
                InventoryMovement.company_id == tenant.company_id
            )) or 0)
        cost_events = int(await db.scalar(select(func.count()).select_from(
            InventoryCostEvent).where(
                InventoryCostEvent.company_id == tenant.company_id
            )) or 0)
        physical = str(await db.scalar(
            select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0))
            .where(InventoryBalance.company_id == tenant.company_id)
        ))
        return {
            "name": row[0],
            "receivable": Decimal(row[1]),
            "credit_cap": Decimal(row[2]),
            "audit": {key: int(n) for key, n in actions},
            "movements": movements,
            "cost_events": cost_events,
            "physical": physical,
        }


def _assert_conflict(response, *, stale: bool):
    assert response.status_code == 409, response.text
    contract = response.json()
    error = contract["error"]
    code = ("SHOP_FINANCIAL_STALE_FORM" if stale
            else "SHOP_FINANCIAL_ACTION_REQUIRES_AUTHORITY")
    assert error["code"] == code, response.text
    assert error["request_id"] and contract["request_id"] == error["request_id"]
    assert error["context"].get("fields"), response.text
    assert error["message"] and "حدّث" in error["message"] if stale else bool(error["message"])


async def _grant_dispatch_execute(gate, tenant, actor):
    async with gate.session() as db:
        permission = await db.scalar(select(Permission).where(
            Permission.code == "dispatch.execute"
        ))
        assert permission is not None
        role = Role(
            company_id=tenant.company_id,
            name="842 shop execute " + uuid4().hex[:10],
        )
        db.add(role)
        await db.flush()
        await db.execute(role_permissions.insert().values(
            company_id=tenant.company_id, role_id=role.id,
            permission_id=permission.id,
        ))
        db.add(UserRole(
            company_id=tenant.company_id, role_id=role.id,
            driver_id=actor.driver_id,
        ))
        identifier = int(role.id)
        await db.commit()
        return identifier


async def _real_field_sale_prerequisites(gate, tenant):
    field = await _seed_mobile_uom_and_field(gate, tenant)
    zone_id, master_shop = await _seed_commercial_master(gate, tenant, field)
    async with gate.session() as db:
        jurisdiction = await db.scalar(select(Shop.tax_jurisdiction_id).where(
            Shop.company_id == tenant.company_id, Shop.id == master_shop,
        ))
        assert jurisdiction is not None
        assert await gate.post(
            db, gate.request(lot="842-FIN-" + uuid4().hex[:11],
                             quantity="50", cost="2")
        ) == {"message": "INBOUND_POSTED"}
    vehicle_id, vehicle_location_id = await _vehicle(gate, tenant)
    async with gate.session() as db:
        loaded = await mutate_vehicle_load(
            db, access=tenant.owner.access(db),
            actor_id=tenant.owner.driver_id,
            vehicle_id=vehicle_id,
            warehouse_id=tenant.location_id,
            direction="ADD", request_id=uuid4(),
            items=[{
                "product_variant_id": tenant.variant_id,
                "quantity": Decimal("25"),
            }],
        )
        assert loaded["movement_count"] > 0
    route_request = {
        "zone_id": zone_id,
        "driver_id": int(field.driver.id),
        "vehicle_id": vehicle_id,
        "source_location_id": tenant.location_id,
        "inventory_base": {str(tenant.variant_id): "25"},
        "expected_inventory_base": {str(tenant.variant_id): "25"},
    }
    return field, zone_id, int(jurisdiction), route_request


async def _real_field_collect(client, gate, tenant, field, route_request, shop_id, owner):
    field_headers = await _token(client, gate, tenant, field, "SyntheticFixture123")
    route = await client.post("/dispatch/route", headers=owner, json=route_request)
    assert route.status_code == 201, route.text
    started = await client.post(
        "/driver/sessions/start", headers=field_headers, json={}
    )
    assert started.status_code == 201, started.text
    session_id = int(started.json()["session_id"])
    approved = await client.put(
        f"/admin/sessions/{session_id}/authorize",
        headers=owner, json={"is_authorized": True},
    )
    assert approved.status_code == 200, approved.text
    async with gate.session() as db:
        visit_id = await db.scalar(select(Visit.id).where(
            Visit.company_id == tenant.company_id,
            Visit.shop_id == shop_id,
            Visit.work_session_id == session_id,
            Visit.status == "Pending",
        ))
    assert visit_id is not None
    collected = await client.put(
        f"/visits/{visit_id}", headers=field_headers,
        json={
            "request_id": str(uuid4()),
            "outcome": "NoSale",
            "notes": "842 recorded real debt collection",
            "cart_items": [],
            "returns": [],
            "cash_collected": "0",
            "debt_paid": "20",
        },
    )
    assert collected.status_code == 200, collected.text
    return visit_id


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_f01_real_field_collection_stale_metadata_fails_closed_no_receivable_overwrite(pg):
    """P0: Owner HTTP opening 100 -> genuine FIELD collection 80 -> old form 409."""
    tenant = pg.tenants[0]
    field, zone, jurisdiction, launch = await _real_field_sale_prerequisites(pg, tenant)
    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        shop, _ = await _add_shop(
            client, owner, zone, balance="100", cap="1000",
            jurisdiction_id=jurisdiction,
        )
        await _real_field_collect(client, pg, tenant, field, launch, shop, owner)
        before = await _fingerprint(pg, tenant, shop)
        assert before["receivable"] == Decimal("80")
        assert before["audit"].get("SHOP_BALANCE_MANUAL_EDIT", 0) == 0

        stale = await client.put(f"/dispatch/shops/{shop}", headers=owner, json={
            "name": "842 old form must not save",
            "owner": "", "phone": "", "mapLink": "", "zoneId": zone,
            "initialDebt": "100", "maxDebtLimit": "1000",
        })
        _assert_conflict(stale, stale=True)
        assert stale.json()["error"]["context"]["fields"] == ["initialDebt"]
        after = await _fingerprint(pg, tenant, shop)
        assert after == before, f"F01 P0 financial truth rollback {before} -> {after}"

        safe = await client.put(
            f"/dispatch/shops/{shop}", headers=owner,
            json={"name": "842 safe metadata only"},
        )
        assert safe.status_code == 200, safe.text
        safe_after = await _fingerprint(pg, tenant, shop)
        assert safe_after["name"] == "842 safe metadata only"
        for key in ("receivable", "credit_cap", "audit", "movements", "cost_events", "physical"):
            assert safe_after[key] == before[key], f"F01 {key} altered by metadata"
        print(f"F01_REAL_FIELD_100_TO_80_SAFE: stale_http=409, "
              f"current={after['receivable']}, audit={after['audit']}, "
              f"safe_metadata_http={safe.status_code}")


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_f10_two_authorized_backoffice_actors_stale_credit_cap_denied(pg):
    """P1: old 150 screen cannot reset now-authoritative 75.125 Shop cap."""
    tenant = pg.tenants[0]
    zone = await _zone(pg, tenant)
    await _grant_dispatch_execute(pg, tenant, tenant.ordinary)
    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        ordinary = await _token(
            client, pg, tenant, tenant.ordinary, "SyntheticFixture123"
        )
        shop, _ = await _add_shop(
            client, owner, zone, balance="0", cap="75.125"
        )
        before = await _fingerprint(pg, tenant, shop)
        assert before["credit_cap"] == Decimal("75.125")

        stale = await client.put(f"/dispatch/shops/{shop}", headers=ordinary,
                                 json={
                                     "name": "842 stale ordinary editor",
                                     "zoneId": zone,
                                     "initialDebt": "0",
                                     "maxDebtLimit": "150",
                                 })
        _assert_conflict(stale, stale=True)
        assert stale.json()["error"]["context"]["fields"] == ["maxDebtLimit"]
        after = await _fingerprint(pg, tenant, shop)
        assert after == before, f"F10 failed cap isolation {before} -> {after}"

        safe = await client.put(
            f"/dispatch/shops/{shop}", headers=ordinary,
            json={"name": "842 authorized metadata edit"},
        )
        assert safe.status_code == 200, safe.text
        actual = await _fingerprint(pg, tenant, shop)
        assert actual["credit_cap"] == before["credit_cap"]
        assert actual["receivable"] == before["receivable"]
        assert actual["audit"] == before["audit"]
        print(f"F10_REAL_ROLE_CAP=75.125, STALE_150_HTTP={stale.status_code}, "
              f"cap_after={actual['credit_cap']}")


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_opening_money_decimal_metadata_and_matching_legacy_form_preserved(pg):
    tenant = pg.tenants[0]
    zone = await _zone(pg, tenant)
    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        shop, _ = await _add_shop(
            client, owner, zone, balance="100.125", cap="150.500"
        )
        before = await _fingerprint(pg, tenant, shop)
        assert (before["receivable"], before["credit_cap"]) == (
            Decimal("100.125"), Decimal("150.500")
        )
        # Backward-compatible old client carrying values that actually still
        # match the locked row may legitimately edit *metadata only*.
        metadata = await client.put(
            f"/dispatch/shops/{shop}", headers=owner,
            json={"name": "842 unchanged-financial-form metadata", "zoneId": zone,
                  "initialDebt": "100.125", "maxDebtLimit": "150.500"},
        )
        assert metadata.status_code == 200, metadata.text
        after = await _fingerprint(pg, tenant, shop)
        assert after["name"] == "842 unchanged-financial-form metadata"
        for key in ("receivable", "credit_cap", "audit", "movements", "cost_events", "physical"):
            assert after[key] == before[key]
        print("OPENING_DECIMAL_AND_LEGACY_MATCH PASS: 100.125 / 150.500")


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
@pytest.mark.parametrize("attempt", [
    {"initialDebt": "200"},
    {"maxDebtLimit": "999"},
    {"initialDebt": "100.125", "maxDebtLimit": "150.500"},
])
async def test_finance_only_put_never_acknowledges_unapproved_manual_money_change(pg, attempt):
    tenant = pg.tenants[0]
    zone = await _zone(pg, tenant)
    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        shop, _ = await _add_shop(client, owner, zone)
        before = await _fingerprint(pg, tenant, shop)
        denied = await client.put(
            f"/dispatch/shops/{shop}", headers=owner, json=attempt,
        )
        _assert_conflict(denied, stale=(attempt != {
            "initialDebt": "100.125", "maxDebtLimit": "150.500"
        }))
        assert await _fingerprint(pg, tenant, shop) == before
        print(f"FINANCE_ONLY_FAIL_CLOSED attempt={attempt}, "
              f"HTTP={denied.status_code}, PENDING_D03_MANUAL_FINANCE_POLICY")


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_unauthorized_and_cross_tenant_finance_edit_never_reveals_or_mutates(pg):
    home, foreign = pg.tenants
    zone_a = await _zone(pg, home)
    zone_b = await _zone(pg, foreign, party=1)
    async with _real_http() as client:
        owner = await _owner(client, pg, home)
        foreign_owner = await _owner(client, pg, foreign)
        unauthorized = await _token(
            client, pg, home, home.ordinary, "SyntheticFixture123"
        )
        shop_a, _ = await _add_shop(
            client, owner, zone_a, balance="100.125", cap="150.500"
        )
        shop_b, _ = await _add_shop(
            client, foreign_owner, zone_b, balance="25.125", cap="50.125"
        )
        a_before = await _fingerprint(pg, home, shop_a)
        b_before = await _fingerprint(pg, foreign, shop_b, party=1)

        unauth = await client.put(
            f"/dispatch/shops/{shop_a}", headers=unauthorized,
            json={"name": "unauthorized", "initialDebt": "999"},
        )
        assert unauth.status_code == 403, unauth.text
        cross = await client.put(
            f"/dispatch/shops/{shop_b}", headers=owner,
            json={"name": "wrong tenant", "initialDebt": "999"},
        )
        assert cross.status_code == 404, cross.text
        assert await _fingerprint(pg, home, shop_a) == a_before
        assert await _fingerprint(pg, foreign, shop_b, party=1) == b_before
        async with pg.session(1) as db:
            # Even a non-company-predicated direct SQL query is hidden by FORCE RLS.
            assert await db.get(Shop, shop_a) is None
        print("UNAUTHORIZED_403/CROSS_TENANT_404/STRICT_B_RLS PASS")


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_concurrent_field_collection_and_stale_shop_form_never_reverse_cash(pg):
    """True independent requests: either stale 409 or pre-collection safe metadata 200."""
    tenant = pg.tenants[0]
    field, zone, jurisdiction, launch = await _real_field_sale_prerequisites(pg, tenant)
    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        shop, _ = await _add_shop(
            client, owner, zone, balance="100", cap="1000",
            jurisdiction_id=jurisdiction,
        )
        field_headers = await _token(client, pg, tenant, field, "SyntheticFixture123")
        route = await client.post("/dispatch/route", headers=owner, json=launch)
        assert route.status_code == 201, route.text
        started = await client.post(
            "/driver/sessions/start", headers=field_headers, json={}
        )
        assert started.status_code == 201, started.text
        session_id = int(started.json()["session_id"])
        approved = await client.put(
            f"/admin/sessions/{session_id}/authorize",
            headers=owner, json={"is_authorized": True},
        )
        assert approved.status_code == 200, approved.text
        async with pg.session() as db:
            visit_id = await db.scalar(select(Visit.id).where(
                Visit.company_id == tenant.company_id,
                Visit.shop_id == shop,
                Visit.work_session_id == session_id, Visit.status == "Pending",
            ))
        assert visit_id is not None
        base = await _fingerprint(pg, tenant, shop)
        assert base["receivable"] == Decimal("100")
        field_payload = {
            "request_id": str(uuid4()), "outcome": "NoSale",
            "notes": "842 simultaneous authentic debt collection",
            "cart_items": [], "returns": [],
            "cash_collected": "0", "debt_paid": "20",
        }
        stale_payload = {
            "name": "842 concurrent old form",
            "initialDebt": "100", "maxDebtLimit": "1000",
        }
        sale, metadata = await asyncio.wait_for(asyncio.gather(
            client.put(f"/visits/{visit_id}", headers=field_headers,
                       json=field_payload),
            client.put(f"/dispatch/shops/{shop}", headers=owner,
                       json=stale_payload),
        ), timeout=30)
        assert sale.status_code == 200, sale.text
        assert metadata.status_code in (200, 409), metadata.text
        if metadata.status_code == 409:
            _assert_conflict(metadata, stale=True)
        after = await _fingerprint(pg, tenant, shop)
        assert after["receivable"] == Decimal("80")
        assert after["credit_cap"] == Decimal("1000")
        assert after["audit"].get("SHOP_BALANCE_MANUAL_EDIT", 0) == 0
        assert after["movements"] == base["movements"]
        assert after["cost_events"] == base["cost_events"]
        print(f"CONCURRENT FIELD 100->80; metadata={metadata.status_code}; "
              f"final=80; manual_money_audit=0")
