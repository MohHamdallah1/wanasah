"""Disposable PG16 production-Dashboard wire fixture; never runs on a real database."""
from __future__ import annotations

import asyncio
import json
import os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api import dispatch
from domains.identity.models import CompanyPrincipal
from domains.inventory_vehicle_load.service import mutate_vehicle_load
from domains.vehicles.contracts import CreateVehicleCommand
from domains.vehicles.management import create_vehicle
from models import Company, InventoryBalance, InventoryCostEvent, InventoryLocation, InventoryMovement
from schemas import DispatchRouteRequest, UpdateRouteStatusRequest
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_live_stock_v1_route_sale_unload_postgres import (
    _seed_mobile_uom_and_field, _seed_commercial_master,
)
from tests.live_stock_real_browser_support import _engines, _runtime_session

D = Decimal
STATE = Path(os.environ.get("WANASAH_DISPATCH_P0_WIRE_STATE", "/tmp/dispatch-p0-wire.json"))
pytestmark = [
    pytest.mark.skipif(os.environ.get("WANASAH_DISPATCH_P0_WIRE_GATE") != "1",
                       reason="Only isolated real Dashboard/PG16 wire fixture"),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _totals(db, company_id, variant_id, warehouse_id, vehicle_id):
    result = {}
    for kind, loc in (("warehouse", warehouse_id), ("vehicle", vehicle_id)):
        result[kind] = str(D(await db.scalar(
            select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0))
            .where(InventoryBalance.company_id == company_id,
                   InventoryBalance.product_variant_id == variant_id,
                   InventoryBalance.location_id == loc)
        ) or 0))
    result["movements"] = int(await db.scalar(select(func.count()).select_from(InventoryMovement)
        .where(InventoryMovement.company_id == company_id)) or 0)
    result["cost_events"] = int(await db.scalar(select(func.count()).select_from(InventoryCostEvent)
        .where(InventoryCostEvent.company_id == company_id)) or 0)
    return result


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_seed_dispatch_browser(pg):
    assert os.environ["WANASAH_DISPATCH_P0_WIRE_GATE"] == "1"
    assert not STATE.exists(), "One fresh disposable fixture per CI run"
    a = pg.tenants[0]
    field = await _seed_mobile_uom_and_field(pg, a)
    zone_id, _ = await _seed_commercial_master(pg, a, field)
    for count in ("16", "64"):
        async with pg.session() as db:
            assert await pg.post(db, pg.request(
                lot="P0-WIRE-" + uuid4().hex[:12], quantity=count, cost="2",
            )) == {"message": "INBOUND_POSTED"}
    async with pg.session() as db:
        made = await create_vehicle(
            db, company_id=a.company_id, actor_id=a.owner.operational_driver.id,
            command=CreateVehicleCommand(
                request_id=str(uuid4()), plate_number="P0-W-" + uuid4().hex[:8],
                vehicle_type="Van", maintenance_status="Active",
            ),
        )
        vehicle_id = int(made["id"])
        vehicle_location_id = int(await db.scalar(
            select(InventoryLocation.id).where(
                InventoryLocation.company_id == a.company_id,
                InventoryLocation.vehicle_id == vehicle_id,
                InventoryLocation.location_type == "VEHICLE",
                InventoryLocation.is_active.is_(True),
            ),
        ))
    async with pg.session() as db:
        posted = await mutate_vehicle_load(
            db, access=a.owner.access(db), actor_id=a.owner.driver_id,
            vehicle_id=vehicle_id, warehouse_id=a.location_id, direction="ADD",
            request_id=uuid4(), items=[{"product_variant_id": a.variant_id, "quantity": D("25")}],
        )
        assert posted["movement_count"] > 0
    async with pg.session() as db:
        created = await dispatch.dispatch_route(
            DispatchRouteRequest(
                zone_id=zone_id, driver_id=field.driver.id, vehicle_id=vehicle_id,
                source_location_id=a.location_id,
                inventory_base={str(a.variant_id): D("25")},
                expected_inventory_base={str(a.variant_id): D("25")},
            ),
            db, a.owner.access(db), a.owner.operational_driver,
        )
    route_id = int(created["route_id"])
    async with pg.session() as db:
        await dispatch.update_route_status(
            route_id, UpdateRouteStatusRequest(status="waiting"),
            db, a.owner.access(db), a.owner.operational_driver,
        )
    async with AsyncSession(pg.admin_engine) as db:
        code = await db.scalar(select(Company.company_code).where(Company.id == a.company_id))
        username = await db.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.id == a.owner.context.principal_id))
    async with pg.session() as db:
        before = await _totals(db, a.company_id, a.variant_id, a.location_id, vehicle_location_id)
    assert (D(before["warehouse"]), D(before["vehicle"])) == (D("55"), D("25"))
    STATE.write_text(json.dumps({
        "companyId": a.company_id, "principalId": a.owner.context.principal_id,
        "routeId": route_id, "variantId": a.variant_id,
        "warehouseId": a.location_id, "vehicleLocationId": vehicle_location_id,
        "vehicleId": vehicle_id, "driverId": field.driver.id,
        "credentials": {"code": code, "username": username, "password": "NoLotSyntheticFixture123"},
        "before": before,
    }), encoding="utf-8")
    print("DISPATCH_BROWSER_WIRE_SEED=PASS warehouse=55 vehicle=25", flush=True)


async def verify(phase):
    state = json.loads(STATE.read_text(encoding="utf-8"))
    runtime, admin = await _engines()
    try:
        async with _runtime_session(runtime, state["companyId"]) as db:
            current = await _totals(
                db, state["companyId"], state["variantId"],
                state["warehouseId"], state["vehicleLocationId"],
            )
        previous = state["before"]
        assert current["cost_events"] == previous["cost_events"], (phase, current, previous)
        if phase == "status":
            assert current == previous, (phase, current, previous)
        elif phase == "adjust":
            assert (D(current["warehouse"]), D(current["vehicle"])) == (D("54"), D("26"))
            assert current["movements"] > previous["movements"], (current, previous)
            state["after"] = current
            STATE.write_text(json.dumps(state), encoding="utf-8")
        elif phase in {"replay", "cancel"}:
            assert current == state["after"], (phase, current, state["after"])
        else:
            raise ValueError(phase)
        print("DISPATCH_BROWSER_WIRE_" + phase.upper() + "=PASS " + json.dumps(current), flush=True)
    finally:
        await runtime.dispose()
        await admin.dispose()


if __name__ == "__main__":
    asyncio.run(verify(os.environ.get("WANASAH_DISPATCH_P0_VERIFY_PHASE", "")))
