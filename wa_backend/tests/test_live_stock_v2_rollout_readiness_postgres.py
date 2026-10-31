"""Live Stock persisted v1 -> physical Warehouse projection v2 acceptance.

Disposable PostgreSQL16 only: production FastAPI bearer HTTP, canonical inbound,
Vehicle and IN_TRANSIT movements, RLS, and the existing rebuild authority.
"""
from __future__ import annotations

import os
from decimal import Decimal as D
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api import dispatch
from database import engine as http_runtime_engine
from domains.inventory_vehicle_load.service import mutate_vehicle_load
from domains.live_stock_projection import service as projection
from domains.vehicles.contracts import CreateVehicleCommand
from domains.vehicles.management import create_vehicle
from main import app
from models import (
    Company, InventoryBalance, InventoryCostEvent, InventoryLocation,
    InventoryLiveStockCompanySummary, InventoryLiveStockProjection,
    InventoryLiveStockWarehouseSummary, InventoryMovement, ProductBatch,
)
from domains.identity.models import CompanyPrincipal
from schemas import DispatchRouteRequest
from services import apply_inventory_movement, ensure_system_transit_location
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_live_stock_v1_r3_physical_location_truth_postgres import (
    _enable_second_warehouse, _grant_restricted_reader,
)
from tests.test_live_stock_v1_route_sale_unload_postgres import (
    _seed_mobile_uom_and_field, _seed_commercial_master,
)

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_LIVE_STOCK_V2_ROLLOUT_PG_GATE") != "1",
        reason="Requires specifically provisioned disposable PG16 and real bearer HTTP",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]
PATH = "/warehouse/inventory/cursor"


async def _vehicle(pg_gate, tenant):
    async with pg_gate.session() as db:
        result = await create_vehicle(
            db, company_id=tenant.company_id,
            actor_id=int(tenant.owner.operational_driver.id),
            command=CreateVehicleCommand(
                request_id=str(uuid4()), plate_number="V2R-" + uuid4().hex[:10],
                vehicle_type="Van", maintenance_status="Active",
            ),
        )
        vehicle_id = int(result["id"])
        location_id = await db.scalar(
            select(InventoryLocation.id).where(
                InventoryLocation.company_id == tenant.company_id,
                InventoryLocation.vehicle_id == vehicle_id,
                InventoryLocation.location_type == "VEHICLE",
                InventoryLocation.is_active.is_(True),
            )
        )
        assert location_id is not None
        return vehicle_id, int(location_id)


async def _physical(pg_gate, tenant):
    async with pg_gate.session() as db:
        rows = (await db.execute(
            select(InventoryLocation.location_type, InventoryLocation.id,
                   func.sum(InventoryBalance.on_hand_quantity))
            .join(InventoryLocation, InventoryLocation.id == InventoryBalance.location_id)
            .where(InventoryBalance.company_id == tenant.company_id,
                   InventoryLocation.company_id == tenant.company_id,
                   InventoryBalance.product_variant_id == tenant.variant_id)
            .group_by(InventoryLocation.location_type, InventoryLocation.id)
        )).all()
        movements = int(await db.scalar(select(func.count()).select_from(InventoryMovement)
                                        .where(InventoryMovement.company_id == tenant.company_id)) or 0)
        costs = int(await db.scalar(select(func.count()).select_from(InventoryCostEvent)
                                    .where(InventoryCostEvent.company_id == tenant.company_id)) or 0)
    return {
        "locations": {(kind, int(location)): D(quantity) for kind, location, quantity in rows},
        "movements": movements, "costs": costs,
    }


async def _projection_rows(pg_gate, tenant):
    async with pg_gate.session() as db:
        rows = (await db.execute(select(
            InventoryLiveStockProjection.warehouse_location_id,
            InventoryLiveStockProjection.warehouse_on_hand,
            InventoryLiveStockProjection.vehicle_packs,
            InventoryLiveStockProjection.has_vehicle_presence,
        ).where(
            InventoryLiveStockProjection.company_id == tenant.company_id,
            InventoryLiveStockProjection.product_variant_id == tenant.variant_id,
        ).order_by(InventoryLiveStockProjection.warehouse_location_id))).all()
    return [(int(w), D(q), D(vehicle), bool(present)) for w, q, vehicle, present in rows]


async def _legacy_v1(pg_gate, tenant, warehouse_id):
    """Persist a real schema-valid v1 snapshot under the isolated fixture.

    v1's old latest-route vehicle attribution is represented by an actual
    persisted projection row. Only the *test fixture* is allowed to alter the
    derived projection directly; never touch canonical InventoryBalance.
    """
    async with pg_gate.session() as db:
        await projection._set_projection_write_trusted(db, trusted=True)
        updated = await db.execute(
            text("""
                UPDATE inventory_live_stock_projection
                   SET vehicle_packs=35, has_vehicle_presence=TRUE,
                       revision=revision+1
                 WHERE company_id=:company AND warehouse_location_id=:warehouse
                   AND product_variant_id=:variant
            """), {"company": tenant.company_id, "warehouse": warehouse_id,
                   "variant": tenant.variant_id},
        )
        assert updated.rowcount == 1
        for model in (InventoryLiveStockCompanySummary, InventoryLiveStockWarehouseSummary):
            stmt = text(
                "UPDATE " + model.__tablename__ +
                " SET projection_version=1, projection_state='READY', revision=revision+1 "
                "WHERE company_id=:company"
            )
            changed = await db.execute(stmt, {"company": tenant.company_id})
            assert changed.rowcount >= 1
        await projection._set_projection_write_trusted(db, trusted=False)
        await db.commit()


async def _accounts(pg_gate):
    async with AsyncSession(pg_gate.admin_engine) as db:
        rows = []
        for tenant in pg_gate.tenants:
            code = await db.scalar(select(Company.company_code).where(Company.id == tenant.company_id))
            owner = await db.scalar(select(CompanyPrincipal.username)
                                    .where(CompanyPrincipal.id == tenant.owner.context.principal_id))
            reader = await db.scalar(select(CompanyPrincipal.username)
                                     .where(CompanyPrincipal.id == tenant.ordinary.context.principal_id))
            rows.append((code, owner, reader))
        return rows


async def _login(client, company_code, username, password):
    result = await client.post("/login", json={
        "company_code": company_code, "username": username, "password": password,
    })
    assert result.status_code == 200, result.text
    return result.json()["token"]


async def _read(client, token, warehouse):
    return await client.get(PATH, params={"location_id": warehouse, "limit": 50},
                            headers={"Authorization": "Bearer " + token})


@pytest.mark.parametrize("rollout", ["persisted_v1"])
async def test_v1_to_v2_fail_closed_interruption_rebuild_and_physical_rls(pg, rollout):
    tenant, foreign = pg.tenants
    w1, w2 = int(tenant.location_id), int(tenant.other_location_id)
    await _enable_second_warehouse(pg, tenant)
    field = await _seed_mobile_uom_and_field(pg, tenant)
    zone, _ = await _seed_commercial_master(pg, tenant, field)

    # Two distinct physical origins, two lots, independently costed via actual
    # canonical receipts. No direct InventoryBalance or cost edits.
    w1_lot, w2_lot = "V2-W1-" + uuid4().hex[:9], "V2-W2-" + uuid4().hex[:9]
    async with pg.session() as db:
        assert await pg.post(db, pg.request(lot=w1_lot, quantity="100", cost="2")) == {"message": "INBOUND_POSTED"}
    async with pg.session() as db:
        assert await pg.post(db, pg.request(lot=w2_lot, quantity="100", cost="4")
                             .model_copy(update={"location_id": w2})) == {"message": "INBOUND_POSTED"}
    async with pg.session(1) as db:
        assert await pg.post(db, pg.request(party=1, lot="V2-OTHER-" + uuid4().hex[:9],
                                          quantity="11", cost="9"), party=1) == {"message": "INBOUND_POSTED"}

    car1, loc1 = await _vehicle(pg, tenant)
    car2, loc2 = await _vehicle(pg, tenant)
    await _grant_restricted_reader(pg, tenant, vehicle_location_id=loc1)
    for car, wh, qty in [(car1, w2, "30"), (car1, w1, "5"), (car2, w2, "7")]:
        async with pg.session() as db:
            result = await mutate_vehicle_load(
                db, access=tenant.owner.access(db),
                actor_id=tenant.owner.driver_id, vehicle_id=car,
                warehouse_id=wh, direction="ADD", request_id=uuid4(),
                items=[{"product_variant_id": tenant.variant_id, "quantity": D(qty)}],
            )
            assert result["movement_count"] >= 1

    # A posted physical transit movement, not an unposted transfer request.
    async with pg.session() as db:
        transit = await ensure_system_transit_location(db, tenant.company_id)
        transit_id = int(transit.id)
        batch_id = await db.scalar(select(ProductBatch.id).where(
            ProductBatch.company_id == tenant.company_id,
            ProductBatch.product_variant_id == tenant.variant_id,
            ProductBatch.batch_number == w1_lot,
        ))
        assert batch_id
        await apply_inventory_movement(
            db, company_id=tenant.company_id, performed_by=tenant.owner.driver_id,
            product_variant_id=tenant.variant_id, batch_id=int(batch_id),
            quantity=D("4"), movement_kind="PHYSICAL",
            reference_type="V2_ROLLOUT_TRANSIT_PROOF",
            reference_id="V2-" + uuid4().hex[:12], idempotency_key="V2-" + uuid4().hex,
            source_location_id=w1, destination_location_id=transit_id,
            source_stock_status="AVAILABLE", destination_stock_status="AVAILABLE",
        )
        await db.commit()

    # A Route declares W1 while vehicle1 holds stock originating in W2.
    # Vehicle2 has no Route. Neither fact reallocates physical custody.
    async with pg.session() as db:
        launched = await dispatch.dispatch_route(
            DispatchRouteRequest(
                zone_id=zone, driver_id=field.driver.id,
                vehicle_id=car1, source_location_id=w1,
                inventory_base={str(tenant.variant_id): D("35")},
                expected_inventory_base={str(tenant.variant_id): D("35")},
            ),
            db, tenant.owner.access(db), tenant.owner.operational_driver,
        )
        assert int(launched["route_id"]) > 0
    before = await _physical(pg, tenant)
    foreign_before = await _physical(pg, foreign)
    assert before["locations"] == {
        ("WAREHOUSE", w1): D("91"),
        ("WAREHOUSE", w2): D("63"),
        ("VEHICLE", loc1): D("35"),
        ("VEHICLE", loc2): D("7"),
        ("IN_TRANSIT", transit_id): D("4"),
    }
    assert sum(before["locations"].values()) == D("200")
    assert sum(foreign_before["locations"].values()) == D("11")

    await _legacy_v1(pg, tenant, w1)
    assert (await _projection_rows(pg, tenant))[0][2:] == (D("35"), True)
    identities = await _accounts(pg)
    assert not app.dependency_overrides
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                 base_url="http://v2-rollout-pg16.test") as client:
        owner = await _login(client, identities[0][0], identities[0][1], "NoLotSyntheticFixture123")
        reader = await _login(client, identities[0][0], identities[0][2], "SyntheticFixture123")
        foreign_owner = await _login(client, identities[1][0], identities[1][1], "NoLotSyntheticFixture123")
        for token in (owner, reader):
            for warehouse in (w1, w2):
                denied = await _read(client, token, warehouse)
                assert denied.status_code == 503, denied.text
                assert denied.json()["detail"]["code"] == "LIVE_STOCK_PROJECTION_NOT_READY"
                assert denied.headers.get("x-request-id")
                assert "items" not in denied.json()
        # Other-company readiness does not regress while A is stale.
        other_good = await _read(client, foreign_owner, foreign.location_id)
        assert other_good.status_code == 200, other_good.text
        assert (await _read(client, foreign_owner, w1)).status_code == 404

        original = projection._rebuild_live_stock_warehouse_locked
        built = 0
        async def interrupt(*args, **kwargs):
            nonlocal built
            built += 1
            if built == 2:
                raise RuntimeError("TEST_INJECTED_ROLLOUT_INTERRUPTION")
            return await original(*args, **kwargs)

        # First warehouse work is rolled back with the second warehouse failure.
        with patch.object(projection, "_rebuild_live_stock_warehouse_locked", interrupt):
            async with pg.session() as db:
                with pytest.raises(RuntimeError, match="TEST_INJECTED"):
                    await projection.rebuild_live_stock_company(
                        db, company_id=tenant.company_id, batch_size=1,
                    )
                await db.rollback()
        assert built == 2
        assert await _physical(pg, tenant) == before
        assert (await _projection_rows(pg, tenant))[0][2:] == (D("35"), True)
        assert (await _read(client, owner, w1)).status_code == 503

        # Company-scoped RLS session; bounded, ordered one-variant chunks.
        async with pg.session() as db:
            report = await projection.rebuild_live_stock_company(
                db, company_id=tenant.company_id, batch_size=1,
            )
            assert report.warehouse_count == 2
            assert report.candidate_keys >= 2
            for warehouse in (w1, w2):
                await projection.assert_live_stock_projection_ready(
                    db, company_id=tenant.company_id,
                    warehouse_location_id=warehouse,
                )
            await db.commit()

        rows = await _projection_rows(pg, tenant)
        assert rows == [(w1, D("91"), D("0"), False), (w2, D("63"), D("0"), False)]
        assert await _physical(pg, tenant) == before
        assert await _physical(pg, foreign) == foreign_before
        for wh, expected in ((w1, D("91")), (w2, D("63"))):
            ready = await _read(client, owner, wh)
            assert ready.status_code == 200, ready.text
            item = next(v for v in ready.json()["items"] if v["id"] == tenant.variant_id)
            assert D(item["on_hand_quantity"]) == expected
            assert D(item["total_quantity"]) == expected
            assert item["total_quantity_scope"] == "WAREHOUSE_PHYSICAL"
            assert D(item["vehicle_quantity"]) == D("42")
            assert item["vehicle_quantity_scope"] == "COMPANY_WIDE"
            scoped = await _read(client, reader, wh)
            assert scoped.status_code == 200, scoped.text
            row = next(v for v in scoped.json()["items"] if v["id"] == tenant.variant_id)
            assert D(row["on_hand_quantity"]) == expected
            assert D(row["vehicle_quantity"]) == D("35")
            assert row["vehicle_quantity_scope"] == "AUTHORIZED_LOCATIONS"
            assert foreign.variant_id not in {v["id"] for v in ready.json()["items"]}

        # Repeating the canonical company rebuild must be truly idempotent.
        async with pg.session() as db:
            clean = await projection.rebuild_live_stock_company(
                db, company_id=tenant.company_id, batch_size=1,
            )
            assert clean.drifted_keys == 0
            assert clean.summary_repairs == 0
            await db.commit()
        assert await _projection_rows(pg, tenant) == rows
        assert await _physical(pg, tenant) == before
        assert await _physical(pg, foreign) == foreign_before
        assert (await _read(client, owner, w1)).status_code == 200

    await http_runtime_engine.dispose()
