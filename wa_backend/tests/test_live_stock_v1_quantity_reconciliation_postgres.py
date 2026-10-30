from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.warehouse import live_stock
from domains.inventory_vehicle_load.service import mutate_vehicle_load
from domains.vehicles.contracts import CreateVehicleCommand, VehicleError
from domains.vehicles.management import create_vehicle
from models import (
    DispatchRoute,
    InventoryBalance,
    InventoryCostEvent,
    InventoryCostLayer,
    InventoryCostState,
    InventoryLocation,
    InventoryMovement,
    OperationIdempotency,
    ProductUomConversion,
    UOM,
    Zone,
)
from schemas import UpgradedInboundRequest
from tests.test_inbound_no_lot_frozen_postgres import pg


# Independent acceptance truth is fixed before any business command/API read.
CARTON_TO_BASE = Decimal("8")
INBOUND_CARTONS = Decimal("100")
LOAD_CARTONS = Decimal("30")
EXPECTED_INBOUND_BASE = INBOUND_CARTONS * CARTON_TO_BASE
EXPECTED_LOAD_BASE = LOAD_CARTONS * CARTON_TO_BASE
EXPECTED_WAREHOUSE_BASE = EXPECTED_INBOUND_BASE - EXPECTED_LOAD_BASE
EXPECTED_VEHICLE_BASE = EXPECTED_LOAD_BASE
EXPECTED_COMBINED_BASE = EXPECTED_WAREHOUSE_BASE + EXPECTED_VEHICLE_BASE
PURCHASE_COST_PER_CARTON = Decimal("16")
EXPECTED_BASE_UNIT_COST = PURCHASE_COST_PER_CARTON / CARTON_TO_BASE
EXPECTED_PURCHASE_VALUE = INBOUND_CARTONS * PURCHASE_COST_PER_CARTON

assert EXPECTED_INBOUND_BASE == Decimal("800")
assert EXPECTED_LOAD_BASE == Decimal("240")
assert EXPECTED_WAREHOUSE_BASE == Decimal("560")
assert EXPECTED_VEHICLE_BASE == Decimal("240")
assert EXPECTED_COMBINED_BASE == Decimal("800")
assert EXPECTED_BASE_UNIT_COST == Decimal("2")
assert EXPECTED_PURCHASE_VALUE == Decimal("1600")


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_NO_LOT_PG_GATE") != "1",
        reason="Explicit disposable PostgreSQL 16 acceptance only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _seed_carton_conversion(pg_gate, tenant) -> int:
    """Master-data fixture only; no inventory quantity is seeded here."""
    async with AsyncSession(pg_gate.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": str(tenant.company_id)},
        )
        carton = await seed.scalar(select(UOM).where(UOM.code == "CARTON-QTY-PROOF"))
        if carton is None:
            carton = UOM(name="Carton quantity proof", code="CARTON-QTY-PROOF")
            seed.add(carton)
            await seed.flush()

        conversion = ProductUomConversion(
            company_id=tenant.company_id,
            product_variant_id=tenant.variant_id,
            from_uom_id=int(carton.id),
            to_uom_id=tenant.uom_id,
            numerator=CARTON_TO_BASE,
            denominator=Decimal("1"),
            quantity_scale=0,
            version=1,
        )
        seed.add(conversion)
        await seed.commit()
        return int(carton.id)


async def _create_vehicle_with_historical_attribution(pg_gate, tenant) -> tuple[int, int]:
    async with pg_gate.session() as db:
        created = await create_vehicle(
            db,
            company_id=tenant.company_id,
            actor_id=int(tenant.owner.operational_driver.id),
            command=CreateVehicleCommand(
                request_id=str(uuid4()),
                plate_number="QTY-" + uuid4().hex[:12],
                vehicle_type="Van",
                maintenance_status="Active",
            ),
        )
        vehicle_id = int(created["id"])
        vehicle_location_id = int(
            await db.scalar(
                select(InventoryLocation.id).where(
                    InventoryLocation.company_id == tenant.company_id,
                    InventoryLocation.vehicle_id == vehicle_id,
                    InventoryLocation.location_type == "VEHICLE",
                    InventoryLocation.is_active.is_(True),
                )
            )
        )

        # Existing Live Stock semantics attribute vehicle custody to the latest
        # route source. A CLOSED historical route supplies attribution only; it
        # does not own the vehicle or perform/seed any inventory movement.
        zone = Zone(
            company_id=tenant.company_id,
            name="Quantity proof " + uuid4().hex[:10],
        )
        db.add(zone)
        await db.flush()
        db.add(
            DispatchRoute(
                company_id=tenant.company_id,
                zone_id=int(zone.id),
                driver_id=int(tenant.owner.operational_driver.id),
                vehicle_id=vehicle_id,
                source_location_id=tenant.location_id,
                dispatch_date=date(2026, 10, 30),
                status="closed",
            )
        )
        await db.commit()
        return vehicle_id, vehicle_location_id


async def _counts(db, company_id: int) -> tuple[int, int, int]:
    return (
        int(
            await db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(InventoryMovement.company_id == company_id)
            )
            or 0
        ),
        int(
            await db.scalar(
                select(func.count())
                .select_from(InventoryCostEvent)
                .where(InventoryCostEvent.company_id == company_id)
            )
            or 0
        ),
        int(
            await db.scalar(
                select(func.count())
                .select_from(OperationIdempotency)
                .where(OperationIdempotency.company_id == company_id)
            )
            or 0
        ),
    )


async def _physical_pair(
    db,
    *,
    company_id: int,
    variant_id: int,
    batch_id: int,
    warehouse_id: int,
    vehicle_location_id: int,
) -> tuple[Decimal, Decimal]:
    rows = (
        await db.execute(
            select(
                InventoryBalance.location_id,
                InventoryBalance.stock_status,
                InventoryBalance.on_hand_quantity,
                InventoryBalance.reserved_quantity,
            ).where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.product_variant_id == variant_id,
                InventoryBalance.batch_id == batch_id,
            )
        )
    ).all()
    by_location = {
        (int(row.location_id), str(row.stock_status)): (
            Decimal(row.on_hand_quantity),
            Decimal(row.reserved_quantity),
        )
        for row in rows
    }
    assert by_location[(warehouse_id, "AVAILABLE")][1] == Decimal("0")
    assert by_location[(vehicle_location_id, "AVAILABLE")][1] == Decimal("0")
    return (
        by_location[(warehouse_id, "AVAILABLE")][0],
        by_location[(vehicle_location_id, "AVAILABLE")][0],
    )


@pytest.mark.parametrize("unused_method_marker", [None])
async def test_supplier_inbound_then_direct_vehicle_load_reconciles_exact_base_truth(
    pg,
    unused_method_marker,
):
    del unused_method_marker
    tenant = pg.tenants[0]
    foreign = pg.tenants[1]

    carton_uom_id = await _seed_carton_conversion(pg, tenant)
    vehicle_id, vehicle_location_id = await _create_vehicle_with_historical_attribution(
        pg, tenant
    )

    inbound_request_id = uuid4()
    batch_number = "QTY-" + uuid4().hex[:14]
    inbound_payload = UpgradedInboundRequest(
        request_id=inbound_request_id,
        supplier_id=tenant.supplier_id,
        location_id=tenant.location_id,
        reference_id="QTY-IN-" + inbound_request_id.hex,
        items=[
            {
                "product_variant_id": tenant.variant_id,
                "uom_id": carton_uom_id,
                "quantity": INBOUND_CARTONS,
                "unit_cost": PURCHASE_COST_PER_CARTON,
                "batch_number": batch_number,
                "production_date": None,
                "expiry_date": None,
            }
        ],
    )

    # Real supplier inbound command: 100 CARTON x 8 = 800 base units.
    async with pg.session() as db:
        first_inbound = await pg.post(db, inbound_payload)
    assert first_inbound == {"message": "INBOUND_POSTED"}

    # Durable replay rolls its transaction back before returning, so each
    # before/after read uses a fresh tenant-scoped session.
    async with pg.session() as db:
        before_inbound_replay = await _counts(db, tenant.company_id)
    async with pg.session() as db:
        replay_inbound = await pg.post(db, inbound_payload)
    async with pg.session() as db:
        after_inbound_replay = await _counts(db, tenant.company_id)
    assert replay_inbound == first_inbound
    assert after_inbound_replay == before_inbound_replay

    async with pg.session() as db:
        inbound_movement = (
            await db.execute(
                select(InventoryMovement).where(
                    InventoryMovement.company_id == tenant.company_id,
                    InventoryMovement.product_variant_id == tenant.variant_id,
                    InventoryMovement.reference_type == "INBOUND_SUPPLIER",
                    InventoryMovement.reference_id == inbound_payload.reference_id,
                )
            )
        ).scalar_one()
        batch_id = int(inbound_movement.batch_id)
        assert Decimal(inbound_movement.quantity) == EXPECTED_INBOUND_BASE
        assert inbound_movement.source_location_id is None
        assert int(inbound_movement.destination_location_id) == tenant.location_id
        assert inbound_movement.destination_stock_status == "AVAILABLE"

        cost_event = (
            await db.execute(
                select(InventoryCostEvent).where(
                    InventoryCostEvent.company_id == tenant.company_id,
                    InventoryCostEvent.inventory_movement_id == inbound_movement.id,
                )
            )
        ).scalar_one()
        assert cost_event.event_type == "PURCHASE_IN"
        assert cost_event.cost_basis == "PURCHASE_ACTUAL"
        assert int(cost_event.batch_id) == batch_id
        assert Decimal(cost_event.quantity) == EXPECTED_INBOUND_BASE
        assert int(cost_event.input_uom_id) == carton_uom_id
        assert Decimal(cost_event.input_quantity) == INBOUND_CARTONS
        assert Decimal(cost_event.input_unit_cost) == PURCHASE_COST_PER_CARTON
        assert Decimal(cost_event.unit_cost) == EXPECTED_BASE_UNIT_COST
        assert Decimal(cost_event.total_cost) == EXPECTED_PURCHASE_VALUE

        warehouse_after_inbound = await db.scalar(
            select(InventoryBalance.on_hand_quantity).where(
                InventoryBalance.company_id == tenant.company_id,
                InventoryBalance.location_id == tenant.location_id,
                InventoryBalance.product_variant_id == tenant.variant_id,
                InventoryBalance.batch_id == batch_id,
                InventoryBalance.stock_status == "AVAILABLE",
            )
        )
        assert Decimal(warehouse_after_inbound) == EXPECTED_INBOUND_BASE

    load_request_id = uuid4()
    load_items = [
        {
            "product_variant_id": tenant.variant_id,
            # Canonical Vehicle Load accepts base quantity. 30 CARTON x 8 was
            # independently fixed above as EXPECTED_LOAD_BASE=240.
            "quantity": EXPECTED_LOAD_BASE,
        }
    ]

    # Real canonical direct Vehicle Load V1 command: warehouse -> vehicle custody.
    async with pg.session() as db:
        first_load = await mutate_vehicle_load(
            db,
            access=tenant.owner.access(db),
            actor_id=int(tenant.owner.operational_driver.id),
            vehicle_id=vehicle_id,
            warehouse_id=tenant.location_id,
            direction="ADD",
            request_id=load_request_id,
            items=load_items,
        )
    assert first_load["movement_count"] == 1

    # Vehicle-load replay is exact and creates no second physical/cost event.
    async with pg.session() as db:
        before_load_replay = await _counts(db, tenant.company_id)
    async with pg.session() as db:
        replay_load = await mutate_vehicle_load(
            db,
            access=tenant.owner.access(db),
            actor_id=int(tenant.owner.operational_driver.id),
            vehicle_id=vehicle_id,
            warehouse_id=tenant.location_id,
            direction="ADD",
            request_id=load_request_id,
            items=load_items,
        )
    async with pg.session() as db:
        after_load_replay = await _counts(db, tenant.company_id)
    assert replay_load == first_load
    assert after_load_replay == before_load_replay

    async with pg.session() as db:
        warehouse_quantity, vehicle_quantity = await _physical_pair(
            db,
            company_id=tenant.company_id,
            variant_id=tenant.variant_id,
            batch_id=batch_id,
            warehouse_id=tenant.location_id,
            vehicle_location_id=vehicle_location_id,
        )
        assert warehouse_quantity == EXPECTED_WAREHOUSE_BASE
        assert vehicle_quantity == EXPECTED_VEHICLE_BASE
        assert warehouse_quantity + vehicle_quantity == EXPECTED_COMBINED_BASE

        movements = (
            await db.scalars(
                select(InventoryMovement)
                .where(
                    InventoryMovement.company_id == tenant.company_id,
                    InventoryMovement.product_variant_id == tenant.variant_id,
                )
                .order_by(InventoryMovement.id)
            )
        ).all()
        relevant = [
            row
            for row in movements
            if row.reference_type in {"INBOUND_SUPPLIER", "VEHICLE_LOAD_DIRECT"}
        ]
        assert len(relevant) == 2
        assert len({int(row.id) for row in relevant}) == 2
        assert len({str(row.idempotency_key) for row in relevant}) == 2
        inbound_row = next(row for row in relevant if row.reference_type == "INBOUND_SUPPLIER")
        load_row = next(row for row in relevant if row.reference_type == "VEHICLE_LOAD_DIRECT")
        assert int(inbound_row.batch_id) == int(load_row.batch_id) == batch_id
        assert Decimal(inbound_row.quantity) == EXPECTED_INBOUND_BASE
        assert Decimal(load_row.quantity) == EXPECTED_LOAD_BASE
        assert int(load_row.source_location_id) == tenant.location_id
        assert int(load_row.destination_location_id) == vehicle_location_id
        assert load_row.source_stock_status == load_row.destination_stock_status == "AVAILABLE"

        cost_events = (
            await db.scalars(
                select(InventoryCostEvent).where(
                    InventoryCostEvent.company_id == tenant.company_id,
                    InventoryCostEvent.product_variant_id == tenant.variant_id,
                )
            )
        ).all()
        assert len(cost_events) == 1
        assert int(cost_events[0].inventory_movement_id) == int(inbound_row.id)

        cost_state = await db.scalar(
            select(InventoryCostState).where(
                InventoryCostState.company_id == tenant.company_id,
                InventoryCostState.product_variant_id == tenant.variant_id,
            )
        )
        assert Decimal(cost_state.quantity) == EXPECTED_COMBINED_BASE
        assert Decimal(cost_state.inventory_value) == EXPECTED_PURCHASE_VALUE
        assert Decimal(cost_state.average_unit_cost) == EXPECTED_BASE_UNIT_COST

        layers = (
            await db.execute(
                select(
                    func.coalesce(func.sum(InventoryCostLayer.remaining_quantity), 0),
                    func.coalesce(func.sum(InventoryCostLayer.remaining_value), 0),
                ).where(
                    InventoryCostLayer.company_id == tenant.company_id,
                    InventoryCostLayer.product_variant_id == tenant.variant_id,
                )
            )
        ).one()
        if pg.method == "FIFO":
            assert Decimal(layers[0]) == EXPECTED_COMBINED_BASE
            assert Decimal(layers[1]) == EXPECTED_PURCHASE_VALUE
        else:
            assert Decimal(layers[0]) == Decimal("0")
            assert Decimal(layers[1]) == Decimal("0")

        route = await db.scalar(
            select(DispatchRoute).where(
                DispatchRoute.company_id == tenant.company_id,
                DispatchRoute.vehicle_id == vehicle_id,
            )
        )
        assert route.status == "closed"
        assert int(route.source_location_id) == tenant.location_id

        # Live Stock is read only after the independent expected table above is fixed
        # and authoritative balances/ledger/cost evidence have reconciled.
        page = await live_stock.get_warehouse_inventory(
            location_id=tenant.location_id,
            cursor=None,
            limit=50,
            search=None,
            only_alerts=False,
            stock_state="all",
            family_id=None,
            has_reserved=False,
            has_unavailable=False,
            has_damaged=False,
            has_recalled=False,
            has_vehicle=False,
            minimum_unset=False,
            sort="name_asc",
            db=db,
            access=tenant.owner.access(db),
        )
        live_row = next(row for row in page["items"] if row["id"] == tenant.variant_id)
        assert Decimal(live_row["on_hand_quantity"]) == EXPECTED_WAREHOUSE_BASE
        assert Decimal(live_row["vehicle_quantity"]) == EXPECTED_VEHICLE_BASE
        assert Decimal(live_row["total_quantity"]) == EXPECTED_COMBINED_BASE
        assert Decimal(live_row["display_factor_to_base"]) == CARTON_TO_BASE

    # Insufficient source stock is rejected and the whole attempt rolls back.
    async with pg.session() as db:
        stable_before_rejection = await _counts(db, tenant.company_id)
    async with pg.session() as db:
        with pytest.raises(VehicleError) as rejected:
            await mutate_vehicle_load(
                db,
                access=tenant.owner.access(db),
                actor_id=int(tenant.owner.operational_driver.id),
                vehicle_id=vehicle_id,
                warehouse_id=tenant.location_id,
                direction="ADD",
                request_id=uuid4(),
                items=[
                    {
                        "product_variant_id": tenant.variant_id,
                        "quantity": EXPECTED_WAREHOUSE_BASE + Decimal("1"),
                    }
                ],
            )
        assert rejected.value.code == "VEHICLE_LOAD_SOURCE_STOCK_CHANGED"
        await db.rollback()
    async with pg.session() as db:
        stable_after_rejection = await _counts(db, tenant.company_id)
        rejected_pair = await _physical_pair(
            db,
            company_id=tenant.company_id,
            variant_id=tenant.variant_id,
            batch_id=batch_id,
            warehouse_id=tenant.location_id,
            vehicle_location_id=vehicle_location_id,
        )
    assert stable_after_rejection == stable_before_rejection
    assert rejected_pair == (EXPECTED_WAREHOUSE_BASE, EXPECTED_VEHICLE_BASE)

    # Same-tenant user without the required location capabilities cannot mutate
    # either endpoint of the warehouse->vehicle movement.
    async with pg.session() as db:
        before_location_denial = await _counts(db, tenant.company_id)
    async with pg.session() as db:
        with pytest.raises(VehicleError) as denied:
            await mutate_vehicle_load(
                db,
                access=tenant.ordinary.access(db),
                actor_id=int(tenant.ordinary.operational_driver.id),
                vehicle_id=vehicle_id,
                warehouse_id=tenant.location_id,
                direction="ADD",
                request_id=uuid4(),
                items=[{"product_variant_id": tenant.variant_id, "quantity": Decimal("1")}],
            )
        assert denied.value.code == "VEHICLE_LOAD_PERMISSION_DENIED"
        assert denied.value.status_code == 403
        await db.rollback()
    async with pg.session() as db:
        assert await _counts(db, tenant.company_id) == before_location_denial

    # A foreign-company owner cannot target company A IDs, and FORCE RLS hides
    # company A balances from the foreign tenant connection.
    foreign_before = await pg.snapshot(party=1)
    async with pg.session(party=1) as db:
        with pytest.raises(VehicleError):
            await mutate_vehicle_load(
                db,
                access=foreign.owner.access(db),
                actor_id=int(foreign.owner.operational_driver.id),
                vehicle_id=vehicle_id,
                warehouse_id=tenant.location_id,
                direction="ADD",
                request_id=uuid4(),
                items=[{"product_variant_id": tenant.variant_id, "quantity": Decimal("1")}],
            )
        await db.rollback()
    async with pg.session(party=1) as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(InventoryBalance)
                .where(InventoryBalance.company_id == tenant.company_id)
            )
            == 0
        )
    assert await pg.snapshot(party=1) == foreign_before

    async with pg.session() as db:
        final_pair = await _physical_pair(
            db,
            company_id=tenant.company_id,
            variant_id=tenant.variant_id,
            batch_id=batch_id,
            warehouse_id=tenant.location_id,
            vehicle_location_id=vehicle_location_id,
        )
        assert final_pair == (EXPECTED_WAREHOUSE_BASE, EXPECTED_VEHICLE_BASE)
        assert sum(final_pair, Decimal("0")) == EXPECTED_COMBINED_BASE
