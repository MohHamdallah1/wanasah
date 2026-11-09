"""#849: real restricted PG16 and authenticated Bearer atomic Dispatch shortage group.

The shared fixture proves NOBYPASSRLS/FORCE RLS against disposable PG16 only.
This test never substitutes auth dependencies or a mocked HTTP transport.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete as sa_delete, func, select

from models import (
    InventoryCostEvent, InventoryMovement, OperationIdempotency, ProductVariant,
    ShortageRequest, SystemAuditLog, UserRole, Visit, utc_now,
)
from tests.test_dispatch_shop_finance_edit_v1_postgres import (
    _add_shop, _grant_company_dispatch_capability, _real_field_sale_prerequisites,
    _real_http, _token, _zone,
)
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_live_stock_v1_route_sale_unload_postgres import _seed_mobile_uom_and_field

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_SHORTAGE_GROUP_PG_GATE") != "1",
        reason="Requires isolated PostgreSQL 16 and genuine Backoffice Bearer",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _seed_variants(gate, tenant, count=4):
    ids = [tenant.variant_id]
    async with gate.session() as db:
        base = await db.get(ProductVariant, tenant.variant_id)
        assert base is not None
        for _ in range(count - 1):
            code = "SG849-" + uuid4().hex[:16]
            new = ProductVariant(
                company_id=tenant.company_id, product_id=base.product_id,
                name=code, sku=code, base_uom_id=tenant.uom_id,
                quantity_scale=6, quantity_step=Decimal("0.000001"),
                lot_control_mode="OPTIONAL", expiry_control_mode="OPTIONAL",
                lifecycle_status="ACTIVE", published_at=utc_now(),
            )
            db.add(new)
            await db.flush()
            ids.append(int(new.id))
        await db.commit()
    return ids


async def _snapshot(gate, tenant, shop_id):
    async with gate.session() as db:
        rows = (await db.execute(select(
            ShortageRequest.id, ShortageRequest.product_variant_id,
            ShortageRequest.driver_id, ShortageRequest.quantity, ShortageRequest.status,
        ).where(
            ShortageRequest.company_id == tenant.company_id,
            ShortageRequest.shop_id == shop_id,
        ).order_by(ShortageRequest.id.asc()))).all()
        visits = (await db.execute(select(
            Visit.driver_id, Visit.status, Visit.is_emergency, Visit.work_session_id,
        ).where(
            Visit.company_id == tenant.company_id, Visit.shop_id == shop_id,
        ).order_by(Visit.id.asc()))).all()
        audit = int(await db.scalar(select(func.count()).select_from(
            SystemAuditLog).where(
                SystemAuditLog.company_id == tenant.company_id,
                SystemAuditLog.action_type.in_(
                    ["SHORTAGE_GROUP_REPLACE", "SHORTAGE_GROUP_DELETE"]
                ),
            )) or 0)
        idem = int(await db.scalar(select(func.count()).select_from(
            OperationIdempotency).where(
                OperationIdempotency.company_id == tenant.company_id,
                OperationIdempotency.operation == "DISPATCH_SHORTAGES_GROUP_V1",
            )) or 0)
        physical = int(await db.scalar(select(func.count()).select_from(
            InventoryMovement).where(InventoryMovement.company_id == tenant.company_id)) or 0)
        finance = int(await db.scalar(select(func.count()).select_from(
            InventoryCostEvent).where(InventoryCostEvent.company_id == tenant.company_id)) or 0)
        return ([(int(a), int(b), int(c) if c else None, int(d), e)
                 for a, b, c, d, e in rows],
                [(int(a) if a else None, b, bool(c), d) for a, b, c, d in visits],
                audit, idem, physical, finance)


def _item(shop, zone, driver, product, qty=1):
    return {
        "shopId": shop, "zoneId": zone, "driverId": driver,
        "productId": product, "quantity": qty,
    }


async def _setup(gate):
    company = gate.tenants[0]
    zone = await _zone(gate, company)
    products = await _seed_variants(gate, company)
    field = await _seed_mobile_uom_and_field(gate, company)
    driver_id = int(field.driver.id)
    return company, zone, products, driver_id


async def test_http_group_edit_delete_replay_atomic_and_other_shop(pg):
    tenant, zone, products, driver = await _setup(pg)
    other_company = pg.tenants[1]

    async with _real_http() as client:
        owner = await _token(client, pg, tenant, tenant.owner, "NoLotSyntheticFixture123")
        foreign_owner = await _token(
            client, pg, other_company, other_company.owner, "NoLotSyntheticFixture123",
        )
        shop, _ = await _add_shop(client, owner, zone, balance="0", cap="0")
        outside, _ = await _add_shop(client, owner, zone, balance="0", cap="0")

        first = await client.post("/dispatch/shortages", headers=owner, json=[
            _item(shop, zone, driver, products[0], 2),
            _item(shop, zone, driver, products[1], 3),
        ])
        assert first.status_code == 201, first.text
        other = await client.post("/dispatch/shortages", headers=owner, json=[
            _item(outside, zone, driver, products[0], 1),
        ])
        assert other.status_code == 201, other.text

        listed = await client.get("/dispatch/shortages", headers=owner)
        assert listed.status_code == 200, listed.text
        old_ids = sorted(int(row["id"]) for row in listed.json()
                         if int(row["shopId"]) == shop)
        assert len(old_ids) == 2
        old = await _snapshot(pg, tenant, shop)
        assert any(v[1] == "Pending" and v[2] for v in old[1])

        edited = {
            "request_id": str(uuid4()), "shortage_ids": old_ids,
            "items": [
                _item(shop, zone, driver, products[0], 4),
                _item(shop, zone, driver, products[2], 5),
                _item(shop, zone, driver, products[3], 6),
            ],
        }
        # Company B must not see (or mutate) Company A's selected identifiers.
        foreign = await client.put("/dispatch/shortages/group", headers=foreign_owner, json=edited)
        assert foreign.status_code == 404, foreign.text

        response = await client.put("/dispatch/shortages/group", headers=owner, json=edited)
        assert response.status_code == 200, response.text
        assert len(response.json()["shortage_ids"]) == 3
        saved = await _snapshot(pg, tenant, shop)
        assert len([row for row in saved[0] if row[4] == "pending"]) == 3
        assert sorted(row[3] for row in saved[0]) == [4, 5, 6]
        assert saved[2] == old[2] + 1 and saved[3] == old[3] + 1
        assert saved[4:] == old[4:], "No physical movement or COGS"

        # Lost HTTP 200 replay is durable: same ids, no new audit/Visit/stock.
        retry = await client.put("/dispatch/shortages/group", headers=owner, json=edited)
        assert retry.status_code == 200 and retry.json() == response.json(), retry.text
        assert await _snapshot(pg, tenant, shop) == saved

        changed = {**edited, "items": [
            {**edited["items"][0], "quantity": 7},
            *edited["items"][1:],
        ]}
        reused = await client.put("/dispatch/shortages/group", headers=owner, json=changed)
        assert reused.status_code == 409, reused.text
        assert await _snapshot(pg, tenant, shop) == saved

        # A stale selected ID can never partially destroy the new group.
        stale = {**edited, "request_id": str(uuid4())}
        outdated = await client.put("/dispatch/shortages/group", headers=owner, json=stale)
        # These IDs were deleted during the successful replace; not-found is the
        # expected fail-closed response (processed but extant IDs use 409).
        assert outdated.status_code == 404, outdated.text
        assert await _snapshot(pg, tenant, shop) == saved

        current_ids = response.json()["shortage_ids"]
        dropped = {"request_id": str(uuid4()), "shortage_ids": current_ids, "items": []}
        deleted = await client.put("/dispatch/shortages/group", headers=owner, json=dropped)
        assert deleted.status_code == 200, deleted.text
        gone = await _snapshot(pg, tenant, shop)
        assert not gone[0] and gone[2] == saved[2] + 1
        assert gone[4:] == saved[4:]
        # Legacy delete keeps the Visit row but cancels its pending emergency task.
        assert any(v[1] == "Cancelled" and not v[2] for v in gone[1])
        assert await client.put("/dispatch/shortages/group", headers=owner, json=dropped)
        replayed = await client.put("/dispatch/shortages/group", headers=owner, json=dropped)
        assert replayed.status_code == 200 and replayed.json() == deleted.json()
        assert await _snapshot(pg, tenant, shop) == gone

        outside_list = await client.get("/dispatch/shortages", headers=owner)
        assert outside_list.status_code == 200
        assert len([x for x in outside_list.json()
                    if int(x["shopId"]) == outside]) == 1


async def test_capabilities_and_rejected_lines_leave_all_records_unchanged(pg):
    tenant, zone, products, driver = await _setup(pg)
    async with _real_http() as client:
        owner = await _token(client, pg, tenant, tenant.owner, "NoLotSyntheticFixture123")
        shop, _ = await _add_shop(client, owner, zone, balance="0", cap="0")
        assert (await client.post("/dispatch/shortages", headers=owner, json=[
            _item(shop, zone, driver, products[0], 1),
        ])).status_code == 201
        existing = await client.get("/dispatch/shortages", headers=owner)
        ids = [int(r["id"]) for r in existing.json() if int(r["shopId"]) == shop]
        assert len(ids) == 1
        before = await _snapshot(pg, tenant, shop)

        # A real /login requires at least one persisted Backoffice grant.
        # Grant only shortage.read first; it must NOT authorize group writes.
        await _grant_company_dispatch_capability(
            pg, tenant, tenant.ordinary, "shortage.read",
        )
        ordinary = await _token(
            client, pg, tenant, tenant.ordinary, "SyntheticFixture123",
        )
        payload = {"request_id": str(uuid4()), "shortage_ids": ids,
                   "items": [_item(shop, zone, driver, products[1], 2)]}
        assert (await client.put(
            "/dispatch/shortages/group", headers=ordinary, json=payload,
        )).status_code == 403

        cancel_role_id = await _grant_company_dispatch_capability(
            pg, tenant, tenant.ordinary, "shortage.cancel",
        )
        assert (await client.put(
            "/dispatch/shortages/group", headers=ordinary, json=payload,
        )).status_code == 403, "Edit also requires shortage.create"
        assert await _snapshot(pg, tenant, shop) == before

        mismatch = {**payload, "request_id": str(uuid4()),
                    "items": [_item(shop, zone + 1, driver, products[1], 2)]}
        assert (await client.put(
            "/dispatch/shortages/group", headers=owner, json=mismatch,
        )).status_code == 400
        duplicate = {**payload, "request_id": str(uuid4()),
                     "items": [payload["items"][0], payload["items"][0]]}
        assert (await client.put(
            "/dispatch/shortages/group", headers=owner, json=duplicate,
        )).status_code == 422
        invalid_product = {**payload, "request_id": str(uuid4()),
                           "items": [_item(shop, zone, driver, 2_147_483_646)]}
        assert (await client.put(
            "/dispatch/shortages/group", headers=owner, json=invalid_product,
        )).status_code == 404
        assert await _snapshot(pg, tenant, shop) == before

        # Cancel permission without create is sufficient only for Delete All.
        delete = {"request_id": str(uuid4()), "shortage_ids": ids, "items": []}
        permitted = await client.put(
            "/dispatch/shortages/group", headers=ordinary, json=delete,
        )
        assert permitted.status_code == 200, permitted.text
        after_delete = await _snapshot(pg, tenant, shop)
        assert not after_delete[0]

        # Same valid JWT must not replay a committed mutation after its persisted
        # cancellation grant is revoked. Authorization is checked on every call.
        async with pg.session() as db:
            await db.execute(sa_delete(UserRole).where(
                UserRole.company_id == tenant.company_id,
                UserRole.driver_id == tenant.ordinary.driver_id,
                UserRole.role_id == cancel_role_id,
            ))
            await db.commit()
        rejected_replay = await client.put(
            "/dispatch/shortages/group", headers=ordinary, json=delete,
        )
        assert rejected_replay.status_code == 403, rejected_replay.text
        assert await _snapshot(pg, tenant, shop) == after_delete


async def test_concurrent_group_writers_cannot_double_replace(pg):
    tenant, zone, products, driver = await _setup(pg)
    async with _real_http() as client:
        owner = await _token(client, pg, tenant, tenant.owner, "NoLotSyntheticFixture123")
        shop, _ = await _add_shop(client, owner, zone, balance="0", cap="0")
        assert (await client.post("/dispatch/shortages", headers=owner, json=[
            _item(shop, zone, driver, products[0], 1),
        ])).status_code == 201
        listed = await client.get("/dispatch/shortages", headers=owner)
        ids = [int(x["id"]) for x in listed.json() if int(x["shopId"]) == shop]
        before = await _snapshot(pg, tenant, shop)

        a = {"request_id": str(uuid4()), "shortage_ids": ids,
             "items": [_item(shop, zone, driver, products[1], 2)]}
        b = {"request_id": str(uuid4()), "shortage_ids": ids,
             "items": [_item(shop, zone, driver, products[2], 3)]}
        left, right = await asyncio.wait_for(asyncio.gather(
            client.put("/dispatch/shortages/group", headers=owner, json=a),
            client.put("/dispatch/shortages/group", headers=owner, json=b),
        ), timeout=30)
        assert sorted([left.status_code, right.status_code]) == [200, 409], (
            left.text, right.text,
        )
        after = await _snapshot(pg, tenant, shop)
        assert len(after[0]) == 1 and after[0][0][3] in (2, 3)
        assert after[2] == before[2] + 1 and after[3] == before[3] + 1
        assert after[4:] == before[4:]


async def test_active_route_auto_and_explicit_driver_groups_never_deadlock(pg):
    """Real route + two shops in one zone: no deadlock/500 across lock inversions."""
    tenant = pg.tenants[0]
    field, zone, jurisdiction, route_request = await _real_field_sale_prerequisites(
        pg, tenant,
    )
    driver = int(field.driver.id)
    products = await _seed_variants(pg, tenant, count=3)
    async with _real_http() as client:
        owner = await _token(client, pg, tenant, tenant.owner, "NoLotSyntheticFixture123")
        launch = await client.post("/dispatch/route", headers=owner, json=route_request)
        assert launch.status_code == 201, launch.text
        shops = [
            (await _add_shop(client, owner, zone, balance="0", cap="0",
                             jurisdiction_id=jurisdiction))[0]
            for _ in range(2)
        ]
        for shop_id in shops:
            created = await client.post(
                "/dispatch/shortages", headers=owner,
                json=[_item(shop_id, zone, driver, products[0])],
            )
            assert created.status_code == 201, created.text
        listed = await client.get("/dispatch/shortages", headers=owner)
        assert listed.status_code == 200, listed.text
        per_shop = {
            shop_id: [int(row["id"]) for row in listed.json()
                      if int(row["shopId"]) == shop_id]
            for shop_id in shops
        }
        assert all(len(ids) == 1 for ids in per_shop.values())
        explicit = {
            "request_id": str(uuid4()), "shortage_ids": per_shop[shops[0]],
            "items": [_item(shops[0], zone, driver, products[1], 4)],
        }
        automatic = {
            "request_id": str(uuid4()), "shortage_ids": per_shop[shops[1]],
            "items": [_item(shops[1], zone, None, products[2], 5)],
        }
        replies = await asyncio.wait_for(asyncio.gather(
            client.put("/dispatch/shortages/group", headers=owner, json=explicit),
            client.put("/dispatch/shortages/group", headers=owner, json=automatic),
        ), timeout=30)
        assert all(resp.status_code in (200, 409) for resp in replies), [
            (r.status_code, r.text) for r in replies
        ]
        # A NOWAIT lock-conflict has no partial mutation; the SAME durable
        # request_id may be retried and must then commit or replay exactly.
        for command, response in zip((explicit, automatic), replies):
            if response.status_code == 409:
                retry = await client.put(
                    "/dispatch/shortages/group", headers=owner, json=command,
                )
                assert retry.status_code == 200, retry.text
        for shop_id, quantity in zip(shops, (4, 5)):
            snapshot = await _snapshot(pg, tenant, shop_id)
            assert len(snapshot[0]) == 1, snapshot
            assert snapshot[0][0][2] == driver
            assert snapshot[0][0][3] == quantity
