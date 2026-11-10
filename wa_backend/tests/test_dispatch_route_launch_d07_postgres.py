"""D07 route launch: real restricted PG16, canonical Bearer, lost-201 and rollback.

The existing disposable fixture owns the only writable data; production models,
authorization, published Pricing/Tax/rounding, movement and FIELD identities are
real. No fake JWT, patched HTTP dependencies or in-memory database.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from main import app
from models import (
    DispatchRoute, InventoryBalance, InventoryCostEvent, InventoryMovement,
    OperationIdempotency, RouteCommercialContext, UserRole, Visit,
)
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_dispatch_p0_route_stock_safety_postgres import _vehicle
from tests.test_dispatch_shop_finance_edit_v1_postgres import (
    _grant_company_dispatch_capability, _owner, _real_http, _token,
)
from tests.test_live_stock_v1_route_sale_unload_postgres import (
    _seed_commercial_master, _seed_mobile_uom_and_field,
)
from domains.inventory_vehicle_load.service import mutate_vehicle_load


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_DISPATCH_D07_PG_GATE") != "1",
        reason="Requires isolated PG16 D07 real Bearer acceptance",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _prepared_route(gate, tenant):
    field = await _seed_mobile_uom_and_field(gate, tenant)
    zone, _shop = await _seed_commercial_master(gate, tenant, field)
    async with gate.session() as db:
        result = await gate.post(
            db, gate.request(lot="D07-" + uuid4().hex[:10], quantity="80", cost="2"),
        )
        assert result == {"message": "INBOUND_POSTED"}
    vehicle, vehicle_location = await _vehicle(gate, tenant)
    async with gate.session() as db:
        loaded = await mutate_vehicle_load(
            db, access=tenant.owner.access(db), actor_id=tenant.owner.driver_id,
            vehicle_id=vehicle, warehouse_id=tenant.location_id,
            direction="ADD", request_id=uuid4(),
            items=[{"product_variant_id": tenant.variant_id, "quantity": Decimal("25")}],
        )
        assert loaded["movement_count"] > 0
    key = uuid4()
    payload = {
        "request_id": str(key),
        "zone_id": zone,
        "driver_id": int(field.driver.id),
        "vehicle_id": vehicle,
        "source_location_id": tenant.location_id,
        # The launch DOES unload a real 5 base units on the first execution.
        "inventory_base": {str(tenant.variant_id): "20"},
        "expected_inventory_base": {str(tenant.variant_id): "25"},
    }
    return key, payload, vehicle_location


async def _state(gate, tenant, key, vehicle_location, party=0):
    async with gate.session(party) as db:
        routes = (await db.scalars(select(DispatchRoute).where(
            DispatchRoute.company_id == tenant.company_id,
        ).order_by(DispatchRoute.id))).all()
        visits = (await db.scalars(select(Visit).where(
            Visit.company_id == tenant.company_id,
        ).order_by(Visit.id))).all()
        locks = (await db.scalars(select(RouteCommercialContext).where(
            RouteCommercialContext.company_id == tenant.company_id,
        ).order_by(RouteCommercialContext.id))).all()
        operations = (await db.scalars(select(OperationIdempotency).where(
            OperationIdempotency.company_id == tenant.company_id,
            OperationIdempotency.operation == "DISPATCH_ROUTE_LAUNCH_V1",
            OperationIdempotency.request_id == str(key),
        ))).all()
        balances = (await db.execute(
            select(InventoryBalance.location_id, InventoryBalance.batch_id,
                   InventoryBalance.stock_status, InventoryBalance.on_hand_quantity,
                   InventoryBalance.reserved_quantity).where(
                InventoryBalance.company_id == tenant.company_id,
                InventoryBalance.location_id.in_([tenant.location_id, vehicle_location]),
            ).order_by(InventoryBalance.location_id, InventoryBalance.batch_id)
        )).all()
        movements = int(await db.scalar(select(func.count()).select_from(
            InventoryMovement).where(InventoryMovement.company_id == tenant.company_id)
        ) or 0)
        costs = int(await db.scalar(select(func.count()).select_from(
            InventoryCostEvent).where(InventoryCostEvent.company_id == tenant.company_id)
        ) or 0)
        return {
            "route_ids": [int(r.id) for r in routes],
            "visits": [(int(v.id), int(v.shop_id), str(v.status)) for v in visits],
            "context_ids": [(int(x.id), int(x.dispatch_route_id),
                             int(x.price_publication_revision),
                             int(x.tax_ruleset_version), int(x.rounding_policy_version))
                            for x in locks],
            "operations": [(x.state, x.created_by, x.request_hash,
                            x.response_json, x.completed_at is not None) for x in operations],
            "balances": [(int(loc), int(batch), status, str(qty), str(reserved))
                         for loc, batch, status, qty, reserved in balances],
            "movements": movements, "cost_events": costs,
        }


class LoseRoute201(httpx.AsyncBaseTransport):
    """Drop actual HTTP response only after the original DB commit succeeded."""

    def __init__(self):
        self.inner = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        self.dropped = False

    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        if (
            not self.dropped and request.method == "POST"
            and request.url.path == "/dispatch/route"
            and response.status_code == 201
        ):
            self.dropped = True
            await response.aclose()
            raise httpx.ReadError("D07 lost committed 201", request=request)
        return response

    async def aclose(self):
        await self.inner.aclose()


@pytest.mark.parametrize("pg", ["FIFO", "MOVING_AVERAGE"], indirect=True)
async def test_d07_real_lost_201_authoritative_lookup_and_same_uuid_replay(pg):
    home = pg.tenants[0]
    key, body, vehicle_location = await _prepared_route(pg, home)
    original_state = await _state(pg, home, key, vehicle_location)
    dropped = LoseRoute201()
    async with _real_http() as client:
        owner = await _owner(client, pg, home)
        async with httpx.AsyncClient(
            transport=dropped, base_url="http://d07-lost-201.test", timeout=30,
        ) as unreliable:
            with pytest.raises(httpx.ReadError, match="D07 lost committed 201"):
                await unreliable.post("/dispatch/route", json=body, headers=owner)
        assert dropped.dropped
        after_first = await _state(pg, home, key, vehicle_location)
        assert len(after_first["route_ids"]) == 1
        assert len(after_first["context_ids"]) == len(after_first["operations"]) == 1
        assert after_first["movements"] > original_state["movements"]
        assert after_first["cost_events"] == original_state["cost_events"]
        assert after_first["visits"]

        lookup = await client.get(
            f"/dispatch/route/create-operations/{key}", headers=owner,
        )
        assert lookup.status_code == 200, lookup.text
        assert lookup.json()["state"] == "COMMITTED"
        original = lookup.json()["response"]
        assert original["request_id"] == str(key)
        assert original["state"] == "COMMITTED"
        assert original["route_id"] == after_first["route_ids"][0]
        assert original["commercial_context"]["commercial_context_id"] == after_first["context_ids"][0][0]
        assert original["commercial_context"]["price_publication_revision"] > 0
        assert original["commercial_context"]["tax_ruleset_version"] > 0
        assert original["commercial_context"]["rounding_policy_version"] > 0

        replay = await client.post("/dispatch/route", json=body, headers=owner)
        assert replay.status_code == 201, replay.text
        assert replay.json() == original
        assert await _state(pg, home, key, vehicle_location) == after_first

        changed = await client.post(
            "/dispatch/route", headers=owner,
            json={**body, "inventory_base": {str(home.variant_id): "19"}},
        )
        assert changed.status_code == 409, changed.text
        assert "IDEMPOTENCY_PAYLOAD_CONFLICT" in changed.text
        assert await _state(pg, home, key, vehicle_location) == after_first
        new_key = await client.post(
            "/dispatch/route", headers=owner,
            json={**body, "request_id": str(uuid4())},
        )
        assert new_key.status_code == 409, new_key.text
        assert await _state(pg, home, key, vehicle_location) == after_first
        no_auth = await client.get(f"/dispatch/route/create-operations/{key}")
        assert no_auth.status_code == 401, no_auth.text
        print("D07_LOST_201_REPLAY_LOOKUP_PUBLISHED_CONTEXT_STOCK_ONCE PASS")


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_d07_parallel_actor_tenant_and_revocation(pg):
    home, foreign = pg.tenants
    key, body, vehicle_location = await _prepared_route(pg, home)
    role = await _grant_company_dispatch_capability(
        pg, home, home.ordinary, "dispatch.execute",
    )
    async with _real_http() as client:
        ordinary = await _token(client, pg, home, home.ordinary, "SyntheticFixture123")
        owner = await _owner(client, pg, home)
        other_owner = await _owner(client, pg, foreign)
        responses = await asyncio.gather(*[
            client.post("/dispatch/route", headers=ordinary, json=body)
            for _ in range(2)
        ])
        assert [res.status_code for res in responses] == [201, 201], [
            res.text for res in responses
        ]
        assert responses[0].json() == responses[1].json()
        baseline = await _state(pg, home, key, vehicle_location)
        assert len(baseline["route_ids"]) == len(baseline["operations"]) == 1
        assert baseline["operations"][0][1] == home.ordinary.driver_id
        wrong_actor = await client.post("/dispatch/route", headers=owner, json=body)
        assert wrong_actor.status_code == 409, wrong_actor.text
        assert "IDEMPOTENCY_ACTOR_CONFLICT" in wrong_actor.text
        wrong_lookup = await client.get(
            f"/dispatch/route/create-operations/{key}", headers=owner,
        )
        assert wrong_lookup.status_code == 200
        assert wrong_lookup.json()["state"] == "UNKNOWN"
        foreign_lookup = await client.get(
            f"/dispatch/route/create-operations/{key}", headers=other_owner,
        )
        assert foreign_lookup.status_code == 200
        assert foreign_lookup.json()["state"] == "UNKNOWN"
        foreign_post = await client.post("/dispatch/route", headers=other_owner, json=body)
        assert foreign_post.status_code in (403, 404), foreign_post.text
        assert await _state(pg, home, key, vehicle_location) == baseline
        async with pg.session() as db:
            await db.execute(delete(UserRole).where(
                UserRole.company_id == home.company_id,
                UserRole.driver_id == home.ordinary.driver_id,
                UserRole.role_id == role,
            ))
            await db.commit()
        revoked_lookup = await client.get(
            f"/dispatch/route/create-operations/{key}", headers=ordinary,
        )
        assert revoked_lookup.status_code == 403, revoked_lookup.text
        revoked_post = await client.post("/dispatch/route", headers=ordinary, json=body)
        assert revoked_post.status_code == 403, revoked_post.text
        assert await _state(pg, home, key, vehicle_location) == baseline
        print("D07_CONCURRENT_UUID_ONE_ROUTE_ACTOR_COMPANY_REVOKE PASS")


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_d07_real_pg_failure_before_commit_rolls_back_route_stock_and_receipt(pg):
    tenant = pg.tenants[0]
    key, body, vehicle_location = await _prepared_route(pg, tenant)
    baseline = await _state(pg, tenant, key, vehicle_location)
    # Real DB trigger aborts AFTER the route/stock write, before Visit insert.
    # DDL/trigger on disposable admin engine only, not production source.
    function, trigger = "d07_abort_visit_after_route", "d07_abort_visit_after_route_row"
    async with AsyncSession(pg.admin_engine) as admin:
        await admin.execute(text(f"""
            CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.company_id = {tenant.company_id} THEN
                    RAISE EXCEPTION 'D07_TEST_REAL_ROLLBACK' USING ERRCODE = 'P0001';
                END IF;
                RETURN NEW;
            END $$;
        """))
        await admin.execute(text(
            f"CREATE TRIGGER {trigger} BEFORE INSERT ON visits "
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        ))
        await admin.commit()
    try:
        async with _real_http() as client:
            owner = await _owner(client, pg, tenant)
            response = await client.post("/dispatch/route", headers=owner, json=body)
            assert response.status_code == 500, response.text
            assert await _state(pg, tenant, key, vehicle_location) == baseline
    finally:
        async with AsyncSession(pg.admin_engine) as admin:
            await admin.execute(text(f"DROP TRIGGER {trigger} ON visits"))
            await admin.execute(text(f"DROP FUNCTION {function}()"))
            await admin.commit()
    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        unknown = await client.get(
            f"/dispatch/route/create-operations/{key}", headers=owner,
        )
        assert unknown.status_code == 200 and unknown.json() == {
            "request_id": str(key), "state": "UNKNOWN",
        }
        created = await client.post("/dispatch/route", headers=owner, json=body)
        assert created.status_code == 201, created.text
        latest = await _state(pg, tenant, key, vehicle_location)
        assert len(latest["route_ids"]) == len(latest["operations"]) == 1
        assert latest["movements"] > baseline["movements"]
        print("D07_REAL_PG_TRIGGER_ALL_OR_NOTHING_AND_RETRY PASS")


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_d07_legacy_no_uuid_explicitly_nonrecoverable(pg):
    tenant = pg.tenants[0]
    key, body, vehicle_location = await _prepared_route(pg, tenant)
    legacy = {k: v for k, v in body.items() if k != "request_id"}
    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        first = await client.post("/dispatch/route", headers=owner, json=legacy)
        assert first.status_code == 201, first.text
        assert "request_id" not in first.json()
        unknown = await client.get(
            f"/dispatch/route/create-operations/{key}", headers=owner,
        )
        assert unknown.status_code == 200 and unknown.json()["state"] == "UNKNOWN"
        again = await client.post("/dispatch/route", headers=owner, json=legacy)
        assert again.status_code == 409, again.text
        assert len((await _state(pg, tenant, key, vehicle_location))["route_ids"]) == 1
        print("D07_LEGACY_COMPATIBILITY_NON_IDEMPOTENT_NO_FALSE_SUCCESS PASS")
