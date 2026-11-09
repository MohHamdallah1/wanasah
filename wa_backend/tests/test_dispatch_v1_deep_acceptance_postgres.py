"""#837: genuine PG16 / restricted role / FastAPI Bearer Dispatch discovery.

Intentionally red tests are evidence of bugs. DO NOT xfail, skip or relax.
Fixture access is constrained by tests.test_inbound_no_lot_frozen_postgres.pg,
which verifies a disposable 127.0.0.1:55439 database, PG RLS and Alembic.
No production DB, dependency overrides, mocked transports or code modifications.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from main import app
from database import engine as http_runtime_engine
from domains.identity.models import CompanyPrincipal
from domains.inventory_vehicle_load.service import mutate_vehicle_load
from models import (
    Company, DispatchRoute, InventoryBalance, InventoryCostEvent, InventoryMovement,
    Permission, Role, Shop, ShortageRequest, SystemAuditLog, UserLocationAccess,
    Visit, Zone, role_permissions,
)
from tests.test_inbound_no_lot_frozen_postgres import pg, checked_urls  # noqa: F401
from tests.canonical_actor_fixtures import FieldFixture
from tests.test_dispatch_p0_route_stock_safety_postgres import _vehicle
from tests.test_live_stock_v1_route_sale_unload_postgres import (
    _seed_commercial_master, _seed_mobile_uom_and_field,
)

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("WANASAH_DISPATCH_DEEP_PG_GATE") != "1",
        reason="Only dedicated disposable PostgreSQL16 deep Dispatch workflow",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


@asynccontextmanager
async def _client():
    # Fail before ANY HTTP request: the FastAPI engine is independent of the
    # fixture URLs and may otherwise point to a non-test database via .env.
    expected_runtime, _ = checked_urls()
    actual_runtime = http_runtime_engine.url
    identity = lambda u: (u.drivername, u.host, u.port, u.database, u.username)
    if identity(actual_runtime) != identity(expected_runtime):
        raise RuntimeError(
            "Refusing real HTTP: FastAPI engine != disposable PG16 restricted-role target"
        )
    assert not app.dependency_overrides, "Must exercise actual authentication/routers"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://dispatch-837-isolated-pg16.test",
            timeout=30,
        ) as client:
            yield client
    finally:
        # The global application pool must NOT retain asyncpg connections tied
        # to a pytest-asyncio function loop after that loop closes. No auth/DB
        # mocks; only release this disposable test runner's pooled connections.
        await http_runtime_engine.dispose()


async def _login(client, gate, tenant, actor, password):
    # The migration/fixture role is used for synthetic credential lookup only.
    # Actual API requests always go through real /login and the restricted app role.
    async with AsyncSession(gate.admin_engine) as db:
        company_code = await db.scalar(
            select(Company.company_code).where(Company.id == tenant.company_id)
        )
        username = await db.scalar(
            select(CompanyPrincipal.username).where(
                CompanyPrincipal.id == actor.context.principal_id
            )
        )
    path = "/driver/login" if isinstance(actor, FieldFixture) else "/login"
    response = await client.post(
        path,
        json={"company_code": company_code, "username": username, "password": password},
    )
    assert response.status_code == 200, (
        f"AUTHENTICATED_LOGIN_EXPECTED_200 actual={response.status_code} {response.text}"
    )
    return {"Authorization": "Bearer " + response.json()["token"]}


async def _owner(client, gate, tenant):
    return await _login(client, gate, tenant, tenant.owner, "NoLotSyntheticFixture123")


async def _simple_shop(gate, tenant, *, balance="0", debt_limit="1000"):
    # The gate has TWO actual tenant scopes. Foreign company seeds must use
    # party=1; creating Company B rows in Company A's RLS session is invalid.
    party = next(i for i, row in enumerate(gate.tenants)
                 if row.company_id == tenant.company_id)
    async with gate.session(party) as db:
        zone = Zone(
            company_id=tenant.company_id,
            name="Deep test zone " + uuid4().hex[:10],
            is_active=True,
        )
        db.add(zone)
        await db.flush()
        shop = Shop(
            company_id=tenant.company_id,
            name="Deep test shop " + uuid4().hex[:10],
            zone_id=zone.id,
            is_active=True,
            is_archived=False,
            current_balance=Decimal(balance),
            max_debt_limit=Decimal(debt_limit),
            phone_number="837-" + uuid4().hex[:10],
        )
        db.add(shop)
        await db.flush()
        ids = int(zone.id), int(shop.id)
        await db.commit()
        return ids


async def _shortage_scenario(gate, client, tenant, headers):
    field = await _seed_mobile_uom_and_field(gate, tenant)
    zone_id, shop_id = await _simple_shop(gate, tenant)
    payload = [{
        "shopId": shop_id, "zoneId": zone_id,
        "driverId": int(field.driver.id),
        "productId": int(tenant.variant_id), "quantity": 2,
    }]
    response = await client.post("/dispatch/shortages", json=payload, headers=headers)
    assert response.status_code == 201, (
        f"SHORTAGE_SEED_EXPECTED_201 actual={response.status_code} {response.text}"
    )
    async with gate.session() as db:
        shortage = await db.scalar(select(ShortageRequest).where(
            ShortageRequest.company_id == tenant.company_id,
            ShortageRequest.shop_id == shop_id,
            ShortageRequest.status == "pending",
        ))
        visits = (await db.scalars(select(Visit).where(
            Visit.company_id == tenant.company_id,
            Visit.shop_id == shop_id, Visit.driver_id == field.driver.id,
            Visit.status == "Pending",
        ))).all()
        assert shortage is not None and len(visits) == 1, (
            "A pending shortage with exactly one executable emergency Visit is required"
        )
        return zone_id, shop_id, int(shortage.id), int(visits[0].id), payload


async def _business_state(gate, tenant):
    async with gate.session() as db:
        counts = {}
        for model in (DispatchRoute, Visit, InventoryMovement, InventoryCostEvent):
            counts[model.__tablename__] = int(await db.scalar(
                select(func.count()).select_from(model).where(
                    model.company_id == tenant.company_id
                )
            ) or 0)
        counts["physical"] = str(await db.scalar(
            select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0))
            .where(InventoryBalance.company_id == tenant.company_id)
        ))
        return counts


async def _loaded_route_prerequisites(gate, tenant):
    field = await _seed_mobile_uom_and_field(gate, tenant)
    zone_id, shop_id = await _seed_commercial_master(gate, tenant, field)
    async with gate.session() as db:
        posted = await gate.post(
            db, gate.request(lot="DISPATCH-837-" + uuid4().hex[:12],
                             quantity="50", cost="2")
        )
        assert posted == {"message": "INBOUND_POSTED"}
    vehicle_id, vehicle_location = await _vehicle(gate, tenant)
    async with gate.session() as db:
        added = await mutate_vehicle_load(
            db, access=tenant.owner.access(db), actor_id=tenant.owner.driver_id,
            vehicle_id=vehicle_id, warehouse_id=tenant.location_id,
            direction="ADD", request_id=uuid4(),
            items=[{"product_variant_id": tenant.variant_id,
                    "quantity": Decimal("25")}],
        )
        assert added["movement_count"] > 0
    payload = {
        "zone_id": zone_id, "driver_id": int(field.driver.id),
        "vehicle_id": vehicle_id,
        "source_location_id": tenant.location_id,
        "inventory_base": {str(tenant.variant_id): "25"},
        "expected_inventory_base": {str(tenant.variant_id): "25"},
    }
    return field, zone_id, shop_id, vehicle_location, payload


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_f01_metadata_only_edit_must_not_reverse_authorized_field_collection(pg):
    """Actual /login Owner + FIELD; 100->80 through /visits; stale UI PUT cannot re-credit."""
    tenant = pg.tenants[0]
    field, zone, shop, _vehicle_location, launch = await _loaded_route_prerequisites(
        pg, tenant
    )
    async with _client() as client:
        owner = await _owner(client, pg, tenant)
        field_headers = await _login(client, pg, tenant, field, "SyntheticFixture123")
        opening = await client.put(
            f"/dispatch/shops/{shop}", headers=owner,
            json={"initialDebt": "100", "maxDebtLimit": "1000"},
        )
        assert opening.status_code == 200, opening.text
        route = await client.post("/dispatch/route", headers=owner, json=launch)
        assert route.status_code == 201, route.text

        started = await client.post(
            "/driver/sessions/start", headers=field_headers, json={}
        )
        assert started.status_code == 201, started.text
        session_id = int(started.json()["session_id"])
        authorized = await client.put(
            f"/admin/sessions/{session_id}/authorize", headers=owner,
            json={"is_authorized": True},
        )
        assert authorized.status_code == 200, authorized.text
        async with pg.session() as db:
            visit_id = await db.scalar(select(Visit.id).where(
                Visit.company_id == tenant.company_id, Visit.shop_id == shop,
                Visit.work_session_id == session_id, Visit.status == "Pending",
            ))
        assert visit_id is not None

        collected = await client.put(
            f"/visits/{visit_id}", headers=field_headers,
            json={"request_id": str(uuid4()), "outcome": "NoSale",
                  "notes": "Collected existing debt only",
                  "cart_items": [], "returns": [],
                  "cash_collected": "0", "debt_paid": "20"},
        )
        assert collected.status_code == 200, collected.text
        async with pg.session() as db:
            before = Decimal(await db.scalar(select(Shop.current_balance).where(
                Shop.company_id == tenant.company_id, Shop.id == shop
            )))
            manual_before = int(await db.scalar(select(func.count()).select_from(
                SystemAuditLog).where(
                SystemAuditLog.company_id == tenant.company_id,
                SystemAuditLog.action_type == "SHOP_BALANCE_MANUAL_EDIT",
            )) or 0)
            collection_count = int(await db.scalar(select(func.count()).select_from(
                SystemAuditLog).where(
                SystemAuditLog.company_id == tenant.company_id,
                SystemAuditLog.action_type == "DEBT_COLLECTION",
            )) or 0)
        assert before == Decimal("80") and collection_count == 1, (
            f"FIELD_COLLECTION_PRECONDITION expected=80 actual={before}"
            f" debt_audit={collection_count}"
        )

        stale = await client.put(
            f"/dispatch/shops/{shop}", headers=owner,
            json={"name": "Name-only stale edit", "owner": "",
                  "phone": "", "mapLink": "", "zoneId": zone,
                  "initialDebt": "100", "maxDebtLimit": "1000"},
        )
        assert stale.status_code == 200, stale.text
        async with pg.session() as db:
            after = Decimal(await db.scalar(select(Shop.current_balance).where(
                Shop.company_id == tenant.company_id, Shop.id == shop
            )))
            manual_after = int(await db.scalar(select(func.count()).select_from(
                SystemAuditLog).where(
                SystemAuditLog.company_id == tenant.company_id,
                SystemAuditLog.action_type == "SHOP_BALANCE_MANUAL_EDIT",
            )) or 0)
        print(f"F01 PG16 actual: FIELD 100->80, stale name-edit balance={after}, "
              f"manual_audit_delta={manual_after-manual_before}")
        assert after == Decimal("80") and manual_after == manual_before, (
            f"F01 FINANCE FAIL: expected balance=80 + no manual adjustment; "
            f"actual balance={after} manual_audit_delta={manual_after-manual_before}"
        )


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
@pytest.mark.parametrize("mode", ["edit", "delete"])
async def test_f02_atomic_group_shortages_real_registered_http(pg, mode):
    tenant = pg.tenants[0]
    async with _client() as client:
        owner = await _owner(client, pg, tenant)
        _zone, _shop, shortage_id, visit_id, items = await _shortage_scenario(
            pg, client, tenant, owner
        )
        replacement = (
            [{**items[0], "quantity": 3}] if mode == "edit" else []
        )
        response = await client.put(
            "/dispatch/shortages/group", headers=owner,
            json={"request_id": str(uuid4()), "shortage_ids": [shortage_id],
                  "items": replacement},
        )
        async with pg.session() as db:
            persisted = await db.scalar(select(ShortageRequest).where(
                ShortageRequest.company_id == tenant.company_id,
                ShortageRequest.id == shortage_id,
            ))
            visit = await db.get(Visit, visit_id)
            actual = (persisted.quantity if persisted else None, visit.status)
        print(f"F02 mode={mode} PUT /dispatch/shortages/group: HTTP={response.status_code}, "
              f"DB shortage_qty,visit_status={actual}")
        assert response.status_code == 200, (
            f"F02 P1 missing atomic group {mode}: expected 200, "
            f"actual={response.status_code}, body={response.text}, db={actual}"
        )
        assert (persisted is None if mode == "delete" else persisted.quantity == 3)


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
@pytest.mark.parametrize("archive_kind", ["shop", "zone"])
async def test_f03_archive_must_not_strand_pending_shortage_and_cancelled_visit(
    pg, archive_kind
):
    tenant = pg.tenants[0]
    async with _client() as client:
        owner = await _owner(client, pg, tenant)
        zone_id, shop_id, shortage_id, visit_id, _items = await _shortage_scenario(
            pg, client, tenant, owner
        )
        if archive_kind == "shop":
            response = await client.put(
                "/dispatch/shops/bulk_update", headers=owner,
                json=[{"id": str(shop_id), "archived": True}],
            )
        else:
            response = await client.delete(
                f"/dispatch/zones/{zone_id}", headers=owner
            )
        assert response.status_code == 200, response.text
        async with pg.session() as db:
            shortage = await db.get(ShortageRequest, shortage_id)
            visit = await db.get(Visit, visit_id)
            shop = await db.get(Shop, shop_id)
            state = {
                "shortage": shortage.status if shortage else None,
                "visit": visit.status if visit else None,
                "shop_archived": bool(shop.is_archived),
            }
        print(f"F03 archive_kind={archive_kind} actual DB={state}")
        assert not (state["shortage"] == "pending" and
                    state["visit"] == "Cancelled" and state["shop_archived"]), (
            f"F03 P1 stranded operational demand after {archive_kind} archive: "
            f"expected no pending shortage with cancelled Visit; actual={state}"
        )


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_f04_lost_route_201_must_allow_exact_safe_recovery(pg):
    tenant = pg.tenants[0]
    _field, _zone, _shop, _vehicle_loc, payload = (
        await _loaded_route_prerequisites(pg, tenant)
    )
    async with _client() as client:
        owner = await _owner(client, pg, tenant)
        first = await client.post("/dispatch/route", headers=owner, json=payload)
        assert first.status_code == 201, first.text
        first_route_id = int(first.json()["route_id"])
        after_first = await _business_state(pg, tenant)
        # Deliberately discard first response from client workflow; identical intent.
        second = await client.post("/dispatch/route", headers=owner, json=payload)
        after_retry = await _business_state(pg, tenant)
        print(f"F04 original=201/{first_route_id}, retry HTTP={second.status_code}, "
              f"before_retry={after_first}, after_retry={after_retry}")
        assert after_retry == after_first, (
            f"F04 duplicate stock/visit/cost on retry: {after_first} -> {after_retry}"
        )
        assert second.status_code == 201 and int(second.json()["route_id"]) == first_route_id, (
            f"F04 P1 lost-201 recovery: expected same 201 + route_id={first_route_id}; "
            f"actual HTTP={second.status_code} body={second.text}"
        )


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_f05_scoped_read_reports_actual_financial_visibility_and_revocation(pg):
    """Policy for cross-warehouse master visibility is NOT asserted before D03."""
    tenant, foreign = pg.tenants
    zone_a, shop_a = await _simple_shop(pg, tenant, balance="123", debt_limit="456")
    zone_b, shop_b = await _simple_shop(pg, tenant, balance="789", debt_limit="999")
    _zone_foreign, foreign_shop = await _simple_shop(
        pg, foreign, balance="4", debt_limit="6"
    )
    async with _client() as client:
        owner = await _owner(client, pg, tenant)
        foreign_owner = await _owner(client, pg, foreign)
        # A brand-new ordinary principal without any role is rejected by
        # the Dashboard login boundary (no usable access session). Mint the
        # genuine Bearer token only AFTER assigning the W1-only grant.
        async with pg.session() as db:
            permission = await db.scalar(
                select(Permission).where(Permission.code == "dispatch.read")
            )
            assert permission is not None
            role = Role(company_id=tenant.company_id, name="837 W1-only read")
            db.add(role)
            await db.flush()
            await db.execute(role_permissions.insert().values(
                company_id=tenant.company_id,
                role_id=role.id,
                permission_id=permission.id,
            ))
            db.add(UserLocationAccess(
                company_id=tenant.company_id, role_id=role.id,
                driver_id=tenant.ordinary.driver_id,
                location_id=tenant.location_id,
            ))
            role_id = int(role.id)
            await db.commit()

        limited = await _login(
            client, pg, tenant, tenant.ordinary, "SyntheticFixture123"
        )
        init = await client.get("/dispatch/init", headers=limited)
        shops = await client.get("/dispatch/shops", headers=limited)
        routes = await client.get("/dispatch/active_routes", headers=limited)
        assert (init.status_code, shops.status_code, routes.status_code) == (
            200, 200, 200
        ), (init.text, shops.text, routes.text)
        visible = {int(row["id"]): row for row in shops.json()}
        assert {shop_a, shop_b} <= set(visible)
        assert Decimal(str(visible[shop_b]["initialDebt"])) == Decimal("789")
        assert Decimal(str(visible[shop_b]["maxDebtLimit"])) == Decimal("999")
        print("F05 POLICY_UNPROVEN: one-warehouse-scoped reader sees company-wide "
              f"shop ids={sorted(visible)}, zone ids={[zone_a, zone_b]}, "
              f"other-warehouse shop balance={visible[shop_b]['initialDebt']}")
        foreign_read = await client.get("/dispatch/shops", headers=foreign_owner)
        assert foreign_read.status_code == 200, foreign_read.text
        foreign_ids = {int(row["id"]) for row in foreign_read.json()}
        assert foreign_shop in foreign_ids and shop_a not in foreign_ids
        async with pg.session(1) as db:
            # Explicit cross-company row access with no company WHERE.
            assert await db.scalar(select(Shop).where(Shop.id == shop_a)) is None
        async with pg.session() as db:
            await db.execute(delete(UserLocationAccess).where(
                UserLocationAccess.company_id == tenant.company_id,
                UserLocationAccess.driver_id == tenant.ordinary.driver_id,
                UserLocationAccess.role_id == role_id,
            ))
            await db.commit()
        revoked = await client.get("/dispatch/shops", headers=limited)
        assert revoked.status_code == 403, (
            f"F05 revoked-token permission expected 403, actual {revoked.status_code}"
        )


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_f06_identical_minimal_shop_post_after_lost_201_is_single_command(pg):
    tenant = pg.tenants[0]
    zone, _shop = await _simple_shop(pg, tenant)
    body = {"name": "837 Lost response " + uuid4().hex[:8], "zoneId": zone,
            "phone": "", "mapLink": ""}
    async with _client() as client:
        owner = await _owner(client, pg, tenant)
        first = await client.post("/dispatch/shops", headers=owner, json=body)
        assert first.status_code == 201, first.text
        second = await client.post("/dispatch/shops", headers=owner, json=body)
        async with pg.session() as db:
            matches = (await db.scalars(select(Shop.id).where(
                Shop.company_id == tenant.company_id,
                Shop.name == body["name"],
            ))).all()
        print(f"F06 POST shop first={first.status_code} second={second.status_code} "
              f"persisted_ids={matches}")
        assert len(matches) == 1, (
            f"F06 P1 duplicate minimal Shop after lost-201: expected 1, "
            f"actual persisted={len(matches)} ids={matches}, "
            f"first={first.text} second={second.text}"
        )


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_f09_shortage_post_retry_has_durable_original_result(pg):
    tenant = pg.tenants[0]
    zone, shop = await _simple_shop(pg, tenant)
    payload = [{
        "shopId": shop, "zoneId": zone, "productId": tenant.variant_id,
        "quantity": 3,
    }]
    async with _client() as client:
        owner = await _owner(client, pg, tenant)
        first = await client.post("/dispatch/shortages", headers=owner, json=payload)
        assert first.status_code == 201, first.text
        second = await client.post("/dispatch/shortages", headers=owner, json=payload)
        async with pg.session() as db:
            count = int(await db.scalar(select(func.count()).select_from(
                ShortageRequest).where(
                ShortageRequest.company_id == tenant.company_id,
                ShortageRequest.shop_id == shop,
                ShortageRequest.product_variant_id == tenant.variant_id,
                ShortageRequest.status == "pending",
            )) or 0)
        print(f"F09 create shortage original=201 retry={second.status_code} "
              f"pending_count={count}")
        assert count == 1
        assert second.status_code == 201 and second.json() == first.json(), (
            f"F09 P1 lost-response exact recovery expected original response; "
            f"actual HTTP={second.status_code} body={second.text} pending={count}"
        )


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_f07_new_shop_opening_debt_credit_and_metadata_preserve(pg):
    tenant = pg.tenants[0]
    zone, _ = await _simple_shop(pg, tenant)
    async with _client() as client:
        owner = await _owner(client, pg, tenant)
        created = await client.post(
            "/dispatch/shops", headers=owner,
            json={"name": "837 opening receivable", "zoneId": zone,
                  "phone": "837-" + uuid4().hex[:10],
                  "initialDebt": "100.125", "maxDebtLimit": "150.500"},
        )
        assert created.status_code == 201, created.text
        shop = int(created.json()["shop_id"])
        edited = await client.put(
            f"/dispatch/shops/{shop}", headers=owner,
            json={"name": "837 metadata edited without initialDebt"},
        )
        assert edited.status_code == 200, edited.text
        async with pg.session() as db:
            balance, limit = (await db.execute(
                select(Shop.current_balance, Shop.max_debt_limit).where(
                    Shop.company_id == tenant.company_id, Shop.id == shop
                )
            )).one()
        assert (Decimal(balance), Decimal(limit)) == (
            Decimal("100.125"), Decimal("150.500")
        ), f"F07 finance baseline: balance={balance} credit={limit}"
        print("F07 PASS transport: precise opening receivable and credit retained; "
              "finance booking-policy/independent audit remains UNPROVEN.")
