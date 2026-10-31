"""Supplement #673's disposable fixture using canonical Vehicle and load commands."""
from __future__ import annotations
import asyncio
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, os.environ["R3_BACKEND_ROOT"])
from sqlalchemy import delete, func, select
from models import DispatchRoute, InventoryBalance, InventoryCostState, InventoryLocation, UserLocationAccess
from domains.vehicles.contracts import CreateVehicleCommand
from domains.vehicles.management import create_vehicle
from domains.inventory_vehicle_load.service import mutate_vehicle_load
from tests.canonical_actor_fixtures import load_company_owner_fixture
from tests.live_stock_real_browser_support import _engines, _runtime_session

STATE = Path(os.environ["WANASAH_OPERATIONAL_BROWSER_STATE"])
D = Decimal

async def execute(action):
    state = json.loads(STATE.read_text())
    runtime, admin = await _engines()
    try:
        async with _runtime_session(runtime, state["companyId"]) as db:
            owner = await load_company_owner_fixture(db, state["companyId"])
            if action == "setup":
                vehicle = await create_vehicle(db, company_id=state["companyId"], actor_id=owner.driver_id,
                    command=CreateVehicleCommand(request_id=str(uuid4()), plate_number="CONSUMER-PHYSICAL-01",
                                                 vehicle_type="Van", maintenance_status="Active"))
                state["vehicleId"] = int(vehicle["id"])
                state["vehicleLocation"] = int(await db.scalar(select(InventoryLocation.id).where(
                    InventoryLocation.company_id == state["companyId"], InventoryLocation.vehicle_id == state["vehicleId"],
                    InventoryLocation.location_type == "VEHICLE")))
                STATE.write_text(json.dumps(state), encoding="utf-8")
            elif action == "grant":
                role = await db.scalar(select(UserLocationAccess.role_id).where(
                    UserLocationAccess.company_id == state["companyId"],
                    UserLocationAccess.driver_id == state["readerDriver"],
                    UserLocationAccess.location_id == state["warehouse"]))
                assert role is not None
                db.add(UserLocationAccess(company_id=state["companyId"], driver_id=state["readerDriver"],
                                         location_id=state["vehicleLocation"], role_id=role))
                await db.commit()
            elif action == "load":
                result = await mutate_vehicle_load(db, access=owner.access(db), actor_id=owner.driver_id,
                    vehicle_id=state["vehicleId"], warehouse_id=state["warehouse"], direction="ADD",
                    request_id=uuid4(), items=[{"product_variant_id": state["mainId"], "quantity": D("32")}])
                assert result["movement_count"] == 1
            elif action == "revoke":
                result = await db.execute(delete(UserLocationAccess).where(
                    UserLocationAccess.company_id == state["companyId"],
                    UserLocationAccess.driver_id == state["readerDriver"],
                    UserLocationAccess.location_id == state["vehicleLocation"]))
                assert result.rowcount == 1
                await db.commit()
            else:
                raise ValueError(action)
            # Independent expected truth, never calculated from HTTP responses.
            warehouse = await db.scalar(select(func.sum(InventoryBalance.on_hand_quantity)).where(
                InventoryBalance.company_id == state["companyId"], InventoryBalance.product_variant_id == state["mainId"],
                InventoryBalance.location_id == state["warehouse"]))
            vehicle = await db.scalar(select(func.sum(InventoryBalance.on_hand_quantity)).where(
                InventoryBalance.company_id == state["companyId"], InventoryBalance.product_variant_id == state["mainId"],
                InventoryBalance.location_id == state["vehicleLocation"]))
            expected_warehouse = D("968") if action in ("load", "revoke") else D("1000")
            expected_vehicle = D("32") if action in ("load", "revoke") else D("0")
            assert D(warehouse) == expected_warehouse and D(vehicle or 0) == expected_vehicle
            cost = await db.scalar(select(InventoryCostState).where(
                InventoryCostState.company_id == state["companyId"], InventoryCostState.product_variant_id == state["mainId"]))
            assert (D(cost.quantity), D(cost.inventory_value)) == (D("1000"), D("2200"))
            assert await db.scalar(select(func.count()).select_from(DispatchRoute).where(
                DispatchRoute.company_id == state["companyId"])) == 0
        print("PHYSICAL_CONSUMER_COMMAND PASS " + action, flush=True)
    finally:
        await runtime.dispose()
        await admin.dispose()

if __name__ == "__main__":
    asyncio.run(execute(sys.argv[1]))
