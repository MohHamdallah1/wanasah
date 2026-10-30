"""Real PostgreSQL helpers for R1; no stock writes outside the movement engine."""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from decimal import Decimal
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from api.warehouse import live_stock
from models import (
    DispatchRoute, InventoryBalance, InventoryCostEvent, InventoryCostState,
    InventoryLocation, InventoryMovement, InventoryMovementImpact,
    Permission, Role, UserLocationAccess, Vehicle, Zone, role_permissions,
)
from services import apply_inventory_movements_batch

D = Decimal
WAIT = 20


async def grant_read(db, tenant, location_id):
    permission_id = await db.scalar(select(Permission.id).where(Permission.code == "inventory.read"))
    assert permission_id is not None
    role = Role(company_id=tenant.company_id, name="R1 reader " + uuid4().hex)
    db.add(role)
    await db.flush()
    await db.execute(role_permissions.insert().values(
        company_id=tenant.company_id, role_id=role.id, permission_id=permission_id,
    ))
    db.add(UserLocationAccess(
        company_id=tenant.company_id, driver_id=tenant.ordinary.driver_id,
        location_id=location_id, role_id=role.id,
    ))


@pytest_asyncio.fixture(loop_scope="function")
async def r1case(pg):
    """Reuse the existing guarded, migrated, restricted-role PostgreSQL fixture."""
    tenant = pg.tenants[0]
    async with pg.session() as db:
        await pg.post(db, pg.request(quantity="20", cost="2", lot="R1-" + uuid4().hex))
    snapshot = await pg.snapshot()
    assert snapshot["quantity"] == D("20")
    assert snapshot["value"] == D("40")
    batch_id = snapshot["batches"][0][0]
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(text("SELECT set_config('app.current_tenant',:tenant,true)"),
                           {"tenant": str(tenant.company_id)})
        vehicle = Vehicle(company_id=tenant.company_id, plate_number="R1-" + uuid4().hex[:12])
        zone = Zone(company_id=tenant.company_id, name="R1-" + uuid4().hex)
        seed.add_all([vehicle, zone])
        await seed.flush()
        location = InventoryLocation(
            company_id=tenant.company_id, code="R1-V", name="R1 vehicle",
            location_type="VEHICLE", vehicle_id=vehicle.id, is_active=True,
        )
        seed.add(location)
        await seed.flush()
        # Closed historical attribution only: no invented active route/work session.
        seed.add(DispatchRoute(
            company_id=tenant.company_id, zone_id=zone.id, vehicle_id=vehicle.id,
            source_location_id=tenant.location_id, status="closed",
        ))
        await grant_read(seed, tenant, tenant.location_id)
        await grant_read(seed, tenant, location.id)
        await seed.commit()
        vehicle_location_id = location.id

    case = NS(pg=pg, tenant=tenant, batch_id=batch_id,
              warehouse_id=tenant.location_id, vehicle_id=vehicle_location_id)
    async with pg.session() as db:
        await move(db, case, spec(case, source=case.warehouse_id,
                                  destination=case.vehicle_id, quantity="10"))
        await db.commit()
    await assert_truth(case, warehouse="10", vehicle="10")
    return case


def spec(case, *, source=None, destination=None, quantity="10",
         reservation=None, key=None):
    return dict(
        product_variant_id=case.tenant.variant_id, batch_id=case.batch_id,
        quantity=D(quantity), movement_kind="RESERVATION" if reservation else "PHYSICAL",
        reservation_action=reservation,
        source_location_id=source, destination_location_id=destination,
        source_stock_status="AVAILABLE" if source is not None else None,
        destination_stock_status="AVAILABLE" if destination is not None else None,
        reference_type="R1_RESERVATION" if reservation else "R1_TRANSFER",
        reference_id="R1-" + (key or uuid4().hex),
        idempotency_key=key or "R1-" + uuid4().hex,
    )


async def move(db, case, command):
    rows = await apply_inventory_movements_batch(
        db, company_id=case.tenant.company_id,
        performed_by=case.tenant.owner.driver_id, movements=[command],
    )
    return rows[0].id


async def truth(case):
    """Single statement physical snapshot, independent of Live Stock projection."""
    async with case.pg.session() as db:
        rows = (await db.execute(select(
            InventoryBalance.location_id, InventoryBalance.on_hand_quantity,
            InventoryBalance.reserved_quantity,
        ).where(
            InventoryBalance.company_id == case.tenant.company_id,
            InventoryBalance.product_variant_id == case.tenant.variant_id,
        ))).all()
    on_hand, reserved = defaultdict(lambda: D("0")), defaultdict(lambda: D("0"))
    for location, quantity, held in rows:
        on_hand[int(location)] += D(quantity)
        reserved[int(location)] += D(held)
    return dict(on_hand), dict(reserved)


async def assert_truth(case, *, warehouse, vehicle, reserved_vehicle="0"):
    physical, reserved = await truth(case)
    assert physical.get(case.warehouse_id, D("0")) == D(warehouse)
    assert physical.get(case.vehicle_id, D("0")) == D(vehicle)
    assert sum(physical.values(), D("0")) == D("20")
    assert reserved.get(case.warehouse_id, D("0")) == D("0")
    assert reserved.get(case.vehicle_id, D("0")) == D(reserved_vehicle)
    async with case.pg.session() as db:
        movements = (await db.scalars(select(InventoryMovement).where(
            InventoryMovement.company_id == case.tenant.company_id,
            InventoryMovement.product_variant_id == case.tenant.variant_id,
        ).order_by(InventoryMovement.id))).all()
        impacts = (await db.execute(select(
            InventoryMovementImpact.movement_id,
            InventoryMovementImpact.on_hand_before, InventoryMovementImpact.on_hand_after,
            InventoryMovementImpact.reserved_before, InventoryMovementImpact.reserved_after,
        ).where(InventoryMovementImpact.company_id == case.tenant.company_id))).all()
        state = await db.scalar(select(InventoryCostState).where(
            InventoryCostState.company_id == case.tenant.company_id,
            InventoryCostState.product_variant_id == case.tenant.variant_id,
        ))
        costs = (await db.scalars(select(InventoryCostEvent).where(
            InventoryCostEvent.company_id == case.tenant.company_id,
        ))).all()
        assert state.quantity == D("20") and state.inventory_value == D("40")
        assert state.average_unit_cost == D("2")
        assert len(costs) == 1 and costs[0].total_cost == D("40")
    ledger, holds = defaultdict(lambda: D("0")), defaultdict(lambda: D("0"))
    by_movement = defaultdict(list)
    for row in impacts:
        by_movement[row.movement_id].append(row)
    for movement in movements:
        quantity = D(movement.quantity)
        evidence = by_movement[movement.id]
        assert evidence
        if movement.movement_kind == "RESERVATION":
            delta = quantity if movement.reservation_action == "RESERVE" else -quantity
            holds[movement.source_location_id] += delta
            assert sum((r.on_hand_after - r.on_hand_before for r in evidence), D("0")) == D("0")
            assert sum((r.reserved_after - r.reserved_before for r in evidence), D("0")) == delta
        else:
            if movement.source_location_id is not None:
                ledger[movement.source_location_id] -= quantity
            if movement.destination_location_id is not None:
                ledger[movement.destination_location_id] += quantity
            expected_delta = quantity if movement.source_location_id is None else D("0")
            assert sum((r.on_hand_after - r.on_hand_before for r in evidence), D("0")) == expected_delta
            if movement.source_location_id is not None and movement.destination_location_id is not None:
                assert len(evidence) == 2
                assert sorted(r.on_hand_after - r.on_hand_before for r in evidence) == [-quantity, quantity]
    for location in set(physical) | set(ledger):
        assert physical.get(location, D("0")) == ledger[location]
        assert reserved.get(location, D("0")) == holds[location]
    return {"warehouse": str(D(warehouse)), "vehicle": str(D(vehicle)),
            "physical_total": "20", "cost_quantity": "20", "inventory_value": "40",
            "movement_count": len(movements), "impact_count": len(impacts),
            "cost_event_count": len(costs)}


def cursor_kwargs(case, db, **filters):
    values = dict(
        location_id=case.warehouse_id, cursor=None, limit=50, search=None,
        only_alerts=False, stock_state="all", family_id=None, has_reserved=False,
        has_unavailable=False, has_damaged=False, has_recalled=False,
        has_vehicle=False, minimum_unset=False, sort="name_asc",
        db=db, access=case.tenant.ordinary.access(db),
    )
    values.update(filters)
    return values


class PausingReader:
    """Instrumentation around REAL SQL; never substitutes a row or a query result."""
    def __init__(self, db, boundary):
        self.db, self.boundary = db, boundary
        self.reached, self.release = asyncio.Event(), asyncio.Event()
        self.statements = []
        self.paused = False

    def __getattr__(self, name):
        return getattr(self.db, name)

    async def execute(self, statement, *args, **kwargs):
        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.statements.append(sql)
        result = await self.db.execute(statement, *args, **kwargs)
        marker = ("inventory_vehicle_page_variant_ids" if self.boundary == "vehicle"
                  else "visible_inventory_candidates")
        if not self.paused and marker in sql:
            self.paused = True
            self.reached.set()
            await asyncio.wait_for(self.release.wait(), WAIT)
        return result


async def raced_read(case, *, boundary, command, filters=None, commit=True):
    async with case.pg.session() as raw:
        assert await raw.scalar(text("SHOW transaction_isolation")) == "read committed"
        reader = PausingReader(raw, boundary)
        task = asyncio.create_task(live_stock.get_warehouse_inventory(
            **cursor_kwargs(case, reader, **(filters or {}))))
        try:
            await asyncio.wait_for(reader.reached.wait(), WAIT)
            async with case.pg.session() as writer:
                await move(writer, case, command)
                if commit:
                    await writer.commit()
                else:
                    await writer.rollback()
        finally:
            reader.release.set()
            if not task.done():
                # A timeout/DB error still drains the real reader before closing its connection.
                try:
                    result = await asyncio.wait_for(task, WAIT)
                except BaseException:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise
            else:
                result = await task
        assert reader.paused, "SQL boundary was not reached; do not accept an unexercised race"
        return result, reader.statements


def emit(label, **evidence):
    print("R1_EVIDENCE " + json.dumps({"case": label, **evidence}, sort_keys=True), flush=True)
