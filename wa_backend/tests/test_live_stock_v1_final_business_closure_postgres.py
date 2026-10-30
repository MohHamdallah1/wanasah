"""Final Live Stock V1 business/accounting closure acceptance.

This wave deliberately composes already-accepted canonical foundations instead
of copying them.  Inventory/cost/ledger truth is mutated only through production
commands.  The database is the disposable restricted PostgreSQL 16 gate used by
the existing V1 acceptance foundation.
"""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from api.warehouse import inbound, ledger, live_stock, stocktake, transfers
from models import (
    InventoryBalance,
    InventoryCostEvent,
    InventoryCostState,
    InventoryMovement,
    InventoryTransferHeader,
    StocktakeLine,
)
from domains.stocktake.contracts import (
    StocktakeApprovalCommand,
    StocktakeCountCommand,
    StocktakeRecountCommand,
    StocktakeStartCommand,
)
from schemas import (
    UnifiedDispatchRequest,
    UnifiedReceiveRequest,
    UnifiedTransferDecisionRequest,
)
from domains.inventory_vehicle_load.service import mutate_vehicle_load
from services import InventoryMutationError, apply_inventory_movement
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_live_stock_v1_quantity_reconciliation_postgres import (
    _create_vehicle_with_historical_attribution,
)
from tests.test_live_stock_v1_route_sale_unload_postgres import (
    test_route_sale_and_receiver_unload_preserve_quantity_and_cost_truth
    as run_route_sale_unload_foundation,
)
from tests.test_v1_warehouse_transfer_stocktake_postgres import twice
from tests.warehouse_transfer_stocktake_support import (
    D,
    OWNER_PASSWORD,
    PASSWORD,
    canonical_access,
    command,
    prepare,
)

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_FINAL_BUSINESS_PG_GATE") != "1",
        reason="Explicit migrated disposable PG16 final-business gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


def _warehouse_dispatch(tenant, quantity: str) -> UnifiedDispatchRequest:
    return UnifiedDispatchRequest(
        request_id=uuid4(),
        source_location_id=tenant.location_id,
        destination_location_id=tenant.other_location_id,
        transfer_purpose="WAREHOUSE_BALANCING",
        items=[{
            "product_variant_id": tenant.variant_id,
            "quantity": D(quantity),
            "uom_id": tenant.uom_id,
        }],
    )


async def _state_digest(pg_gate, tenant) -> tuple:
    """Read-only whole-company digest used to prove denials roll back fully."""
    async with pg_gate.session() as db:
        balances = (
            await db.execute(
                select(
                    InventoryBalance.location_id,
                    InventoryBalance.product_variant_id,
                    InventoryBalance.batch_id,
                    InventoryBalance.stock_status,
                    InventoryBalance.on_hand_quantity,
                    InventoryBalance.reserved_quantity,
                )
                .where(InventoryBalance.company_id == tenant.company_id)
                .order_by(
                    InventoryBalance.location_id,
                    InventoryBalance.product_variant_id,
                    InventoryBalance.batch_id,
                    InventoryBalance.stock_status,
                )
            )
        ).all()
        movements = (
            await db.execute(
                select(
                    InventoryMovement.id,
                    InventoryMovement.movement_kind,
                    InventoryMovement.reference_type,
                    InventoryMovement.quantity,
                    InventoryMovement.source_location_id,
                    InventoryMovement.destination_location_id,
                )
                .where(InventoryMovement.company_id == tenant.company_id)
                .order_by(InventoryMovement.id)
            )
        ).all()
        costs = (
            await db.execute(
                select(
                    InventoryCostEvent.id,
                    InventoryCostEvent.event_type,
                    InventoryCostEvent.quantity,
                    InventoryCostEvent.total_cost,
                    InventoryCostEvent.input_unit_cost,
                    InventoryCostEvent.input_uom_id,
                )
                .where(InventoryCostEvent.company_id == tenant.company_id)
                .order_by(InventoryCostEvent.id)
            )
        ).all()
        transfers_rows = (
            await db.execute(
                select(
                    InventoryTransferHeader.id,
                    InventoryTransferHeader.status,
                    InventoryTransferHeader.source_location_id,
                    InventoryTransferHeader.destination_location_id,
                )
                .where(InventoryTransferHeader.company_id == tenant.company_id)
                .order_by(InventoryTransferHeader.id)
            )
        ).all()
        return (
            tuple(map(tuple, balances)),
            tuple(map(tuple, movements)),
            tuple(map(tuple, costs)),
            tuple(map(tuple, transfers_rows)),
        )


async def _connected_truth(
    pg_gate,
    tenant,
    *,
    batch_id: int,
    vehicle_location_id: int,
    expected_locations: dict[int, tuple[Decimal, Decimal]],
    cost_quantity: Decimal,
    inventory_value: Decimal,
    outbound_costs: list[Decimal],
) -> None:
    """Independently reconcile physical, reservation, read and financial truth."""
    async with pg_gate.session() as db:
        balance_rows = (
            await db.execute(
                select(
                    InventoryBalance.location_id,
                    InventoryBalance.on_hand_quantity,
                    InventoryBalance.reserved_quantity,
                ).where(
                    InventoryBalance.company_id == tenant.company_id,
                    InventoryBalance.product_variant_id == tenant.variant_id,
                    InventoryBalance.batch_id == batch_id,
                    InventoryBalance.stock_status == "AVAILABLE",
                )
            )
        ).all()
        actual = {
            int(location_id): (D(on_hand), D(reserved))
            for location_id, on_hand, reserved in balance_rows
            if D(on_hand) != 0 or D(reserved) != 0
        }
        assert actual == expected_locations
        assert all(on_hand >= 0 and reserved >= 0 and reserved <= on_hand
                   for on_hand, reserved in actual.values())
        assert sum((on_hand for on_hand, _ in actual.values()), D("0")) == cost_quantity

        state = await db.scalar(
            select(InventoryCostState).where(
                InventoryCostState.company_id == tenant.company_id,
                InventoryCostState.product_variant_id == tenant.variant_id,
            )
        )
        assert state is not None
        assert (D(state.quantity), D(state.inventory_value), D(state.average_unit_cost)) == (
            cost_quantity,
            inventory_value,
            D("2"),
        )

        events = (
            await db.scalars(
                select(InventoryCostEvent)
                .where(
                    InventoryCostEvent.company_id == tenant.company_id,
                    InventoryCostEvent.product_variant_id == tenant.variant_id,
                )
                .order_by(InventoryCostEvent.id)
            )
        ).all()
        purchase = [event for event in events if event.event_type == "PURCHASE_IN"]
        outbound = [event for event in events if event.event_type == "OUTBOUND"]
        assert len(purchase) == 1
        assert (
            D(purchase[0].quantity),
            D(purchase[0].input_quantity),
            D(purchase[0].input_unit_cost),
            D(purchase[0].total_cost),
        ) == (D("800"), D("100"), D("16"), D("1600"))
        assert [D(event.total_cost) for event in outbound] == outbound_costs

        for location_id, (expected_on_hand, expected_reserved) in expected_locations.items():
            # Live Stock list/batch routes are warehouse-only by contract.
            # Vehicle and IN_TRANSIT custody are already reconciled above from
            # canonical InventoryBalance and are never coerced into warehouses.
            if (
                location_id == vehicle_location_id
                or location_id not in {tenant.location_id, tenant.other_location_id}
                or expected_on_hand == 0
            ):
                continue
            page = await live_stock.get_warehouse_inventory(
                location_id=location_id,
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
            row = next(item for item in page["items"] if item["id"] == tenant.variant_id)
            assert D(row["on_hand_quantity"]) == expected_on_hand
            assert D(row["reserved_quantity"]) == expected_reserved
            assert D(row["average_cost_display"]) == D("2")
            assert D(row["last_purchase_cost"]) == D("16")
            assert row["last_purchase_uom_code"] == "CARTON-QTY-PROOF"

            detail = await live_stock.get_warehouse_inventory_batches(
                tenant.variant_id, location_id, None, 100, db, tenant.owner.access(db)
            )
            batch = next(item for item in detail["batches"] if item["batch_id"] == batch_id)
            assert D(batch["on_hand_quantity"]) == expected_on_hand
            assert D(batch["reserved_quantity"]) == expected_reserved
            assert D(batch["latest_purchase_cost"]) == D("16")
            assert batch["latest_purchase_uom_code"] == "CARTON-QTY-PROOF"
            assert batch["purchase_event_count"] == 1

        sources = await live_stock.get_batch_stock_sources(
            batch_id, db, tenant.owner.access(db)
        )
        source_quantities: dict[int, tuple[Decimal, Decimal]] = {}
        for source in sources["sources"]:
            available = next(
                (status for status in source["statuses"]
                 if status["stock_status"] == "AVAILABLE"),
                None,
            )
            if available is not None:
                source_quantities[int(source["location_id"])] = (
                    D(available["on_hand_quantity"]),
                    D(available["reserved_quantity"]),
                )
        for location_id, expected in expected_locations.items():
            if location_id == vehicle_location_id or location_id in {
                int(header.transit_location_id)
                for header in (
                    await db.scalars(
                        select(InventoryTransferHeader).where(
                            InventoryTransferHeader.company_id == tenant.company_id,
                            InventoryTransferHeader.transit_location_id.is_not(None),
                        )
                    )
                ).all()
            }:
                continue
            if expected[0] > 0:
                assert source_quantities.get(location_id) == expected

        for location_id in (tenant.location_id, tenant.other_location_id):
            if location_id not in expected_locations:
                continue
            ledger_page = await ledger.get_warehouse_ledger_cursor(
                location_id, None, 100, None, None, None, db, tenant.owner.access(db)
            )
            assert all(item["quantity"] is not None for item in ledger_page["items"])


async def test_connected_route_custody_warehouse_transfer_rejection_and_stocktake(pg):
    """One canonical supplier->vehicle->sale->custody->transfer->stocktake journey."""
    tenant = pg.tenants[0]

    # Reuse, do not copy, the accepted supplier->vehicle->route->sale->custody
    # journey exactly as already accepted.  Its display-UOM proof requires one
    # unambiguous carton conversion, so no later transfer fixture may run first.
    # It finishes with 720 base units back in warehouse A, vehicle=0,
    # PURCHASE_IN=1600 and sale COGS=160.
    await run_route_sale_unload_foundation(pg)

    # Transfer/stocktake master/auth preparation is deliberately delayed until
    # after the accepted route proof. It writes no inventory quantity/cost.
    case = await prepare(pg)

    async with pg.session() as db:
        handoff = await db.scalar(
            select(InventoryMovement)
            .where(
                InventoryMovement.company_id == tenant.company_id,
                InventoryMovement.reference_type == "REPRESENTATIVE_CUSTODY_RECEIPT",
            )
            .order_by(InventoryMovement.id.desc())
        )
        assert handoff is not None
        batch_id = int(handoff.batch_id)
        vehicle_location_id = int(handoff.source_location_id)

    await _connected_truth(
        pg,
        tenant,
        batch_id=batch_id,
        vehicle_location_id=vehicle_location_id,
        expected_locations={tenant.location_id: (D("720"), D("0"))},
        cost_quantity=D("720"),
        inventory_value=D("1440"),
        outbound_costs=[D("160")],
    )

    # The generic warehouse-transfer command itself must reject both directions
    # involving Vehicle custody.  Owner authority is used so the test reaches the
    # domain endpoint-type prohibition rather than failing earlier on a grant.
    before_forbidden = await _state_digest(pg, tenant)
    for source, destination in (
        (tenant.location_id, vehicle_location_id),
        (vehicle_location_id, tenant.other_location_id),
    ):
        forbidden = UnifiedDispatchRequest(
            request_id=uuid4(),
            source_location_id=source,
            destination_location_id=destination,
            transfer_purpose="WAREHOUSE_BALANCING",
            items=[{
                "product_variant_id": tenant.variant_id,
                "quantity": D("8"),
                "uom_id": tenant.uom_id,
            }],
        )
        with pytest.raises(HTTPException) as denied:
            await command(
                pg,
                tenant.owner,
                lambda db, access, actor, payload=forbidden:
                    transfers.unified_transfer_dispatch(payload, db, access, actor),
            )
        assert denied.value.status_code == 403
        assert "VEHICLE" in str(denied.value.detail).upper()
    assert await _state_digest(pg, tenant) == before_forbidden

    # Continue the SAME physical/cost history into a real A->IN_TRANSIT->B move.
    transfer_120 = _warehouse_dispatch(tenant, "120")
    sent = await twice(
        lambda: command(
            pg,
            case.sender,
            lambda db, access, actor:
                transfers.unified_transfer_dispatch(transfer_120, db, access, actor),
        )
    )
    header_id = int(sent["header_id"])
    async with pg.session() as db:
        header = await db.get(InventoryTransferHeader, header_id)
        assert header is not None
        assert header.status == "IN_TRANSIT"
        transit_id = int(header.transit_location_id)

    await _connected_truth(
        pg,
        tenant,
        batch_id=batch_id,
        vehicle_location_id=vehicle_location_id,
        expected_locations={
            tenant.location_id: (D("600"), D("0")),
            transit_id: (D("120"), D("0")),
        },
        cost_quantity=D("720"),
        inventory_value=D("1440"),
        outbound_costs=[D("160")],
    )

    receipt = UnifiedReceiveRequest(
        request_id=uuid4(),
        transfer_header_id=header_id,
        destination_location_id=tenant.other_location_id,
    )
    received = await twice(
        lambda: command(
            pg,
            case.receiver,
            lambda db, access, actor:
                transfers.unified_transfer_receive(receipt, db, access, actor),
        )
    )
    assert received["status"] == "POSTED"
    await _connected_truth(
        pg,
        tenant,
        batch_id=batch_id,
        vehicle_location_id=vehicle_location_id,
        expected_locations={
            tenant.location_id: (D("600"), D("0")),
            tenant.other_location_id: (D("120"), D("0")),
        },
        cost_quantity=D("720"),
        inventory_value=D("1440"),
        outbound_costs=[D("160")],
    )

    # A second shipment is physically rejected and must return to A without
    # changing valuation or historical purchase/sale cost.
    rejected_payload = _warehouse_dispatch(tenant, "16")
    rejected_sent = await command(
        pg,
        case.sender,
        lambda db, access, actor:
            transfers.unified_transfer_dispatch(rejected_payload, db, access, actor),
    )
    rejected_id = int(rejected_sent["header_id"])
    decision = UnifiedTransferDecisionRequest(
        request_id=uuid4(),
        decision_reason="Final business closure rejection proof",
    )
    rejected = await twice(
        lambda: command(
            pg,
            case.receiver,
            lambda db, access, actor:
                transfers.unified_transfer_reject(rejected_id, decision, db, access, actor),
        )
    )
    assert rejected["status"] == "REJECTED"
    await _connected_truth(
        pg,
        tenant,
        batch_id=batch_id,
        vehicle_location_id=vehicle_location_id,
        expected_locations={
            tenant.location_id: (D("600"), D("0")),
            tenant.other_location_id: (D("120"), D("0")),
        },
        cost_quantity=D("720"),
        inventory_value=D("1440"),
        outbound_costs=[D("160")],
    )

    # Count B from 120 to 104 through the existing independent-recount workflow.
    start = StocktakeStartCommand(
        request_id=uuid4(),
        location_id=tenant.other_location_id,
        stocktake_type="FULL_COUNT",
    )
    started = await twice(
        lambda: command(
            pg,
            case.receiver,
            lambda db, access, actor:
                stocktake.start_unified_stocktake(start, db, access, actor),
        )
    )
    session_id = int(started["session_id"])
    count = StocktakeCountCommand(
        request_id=uuid4(),
        items=[{
            "product_variant_id": tenant.variant_id,
            "batch_id": batch_id,
            "stock_status": "AVAILABLE",
            "actual_quantity": D("104"),
            "uom_id": tenant.uom_id,
        }],
    )
    first_count = await twice(
        lambda: command(
            pg,
            case.receiver,
            lambda db, access, actor:
                stocktake.submit_stocktake_count(session_id, count, db, access, actor),
        )
    )
    assert first_count["requires_independent_recount"] is True
    first_attempt = int(first_count["attempt_id"])

    recount = StocktakeRecountCommand(
        request_id=uuid4(),
        count_attempt_id=first_attempt,
        reason="Independent confirmation of sixteen-unit shortage",
        authorizer_username=case.recounter_username,
        authorizer_password=PASSWORD,
    )
    await twice(
        lambda: command(
            pg,
            case.receiver,
            lambda db, access, actor:
                stocktake.recount_stocktake_session(session_id, recount, db, access, actor),
        )
    )
    second_count = count.model_copy(update={"request_id": uuid4()})
    confirmed = await twice(
        lambda: command(
            pg,
            case.recounter,
            lambda db, access, actor:
                stocktake.submit_stocktake_count(session_id, second_count, db, access, actor),
        )
    )
    second_attempt = int(confirmed["attempt_id"])
    assert second_attempt != first_attempt

    approval = StocktakeApprovalCommand(
        request_id=uuid4(),
        count_attempt_id=second_attempt,
        password=OWNER_PASSWORD,
    )
    posted = await twice(
        lambda: command(
            pg,
            tenant.owner,
            lambda db, access, actor:
                stocktake.approve_stocktake_session(session_id, approval, db, access, actor),
        )
    )
    assert posted["status"] == "POSTED"
    assert posted["movement_count"] == 1

    # Final independent decimal truth:
    # 800 inbound - 80 sale - 16 stocktake = 704; cost 2/base => JOD 1408.
    await _connected_truth(
        pg,
        tenant,
        batch_id=batch_id,
        vehicle_location_id=vehicle_location_id,
        expected_locations={
            tenant.location_id: (D("600"), D("0")),
            tenant.other_location_id: (D("104"), D("0")),
        },
        cost_quantity=D("704"),
        inventory_value=D("1408"),
        outbound_costs=[D("160"), D("32")],
    )


async def test_partial_full_reservation_overallocation_and_negative_stock_are_atomic(pg):
    """Real reservations and concurrent outbound cannot over-allocate one balance."""
    tenant = pg.tenants[0]
    await prepare(pg)
    payload = pg.request(
        quantity="20",
        cost="2",
        lot="FINAL-RES-" + uuid4().hex[:12],
    )
    async with pg.session() as db:
        await pg.post(db, payload)
    async with pg.session() as db:
        movement = await db.scalar(
            select(InventoryMovement).where(
                InventoryMovement.company_id == tenant.company_id,
                InventoryMovement.reference_type == "INBOUND_SUPPLIER",
                InventoryMovement.reference_id == payload.reference_id,
            )
        )
        assert movement is not None
        batch_id = int(movement.batch_id)

    async def reserve(quantity: str, action: str, key: str):
        async with pg.session() as db:
            row = await apply_inventory_movement(
                db,
                company_id=tenant.company_id,
                performed_by=tenant.owner.driver_id,
                product_variant_id=tenant.variant_id,
                batch_id=batch_id,
                quantity=D(quantity),
                movement_kind="RESERVATION",
                reservation_action=action,
                reference_type="FINAL_BUSINESS_RESERVATION",
                reference_id=key,
                idempotency_key=key,
                source_location_id=tenant.location_id,
                destination_location_id=tenant.location_id,
                source_stock_status="AVAILABLE",
                destination_stock_status="AVAILABLE",
            )
            await db.commit()
            return int(row.id)

    async def balance() -> tuple[Decimal, Decimal]:
        async with pg.session() as db:
            row = (
                await db.execute(
                    select(
                        InventoryBalance.on_hand_quantity,
                        InventoryBalance.reserved_quantity,
                    ).where(
                        InventoryBalance.company_id == tenant.company_id,
                        InventoryBalance.location_id == tenant.location_id,
                        InventoryBalance.product_variant_id == tenant.variant_id,
                        InventoryBalance.batch_id == batch_id,
                        InventoryBalance.stock_status == "AVAILABLE",
                    )
                )
            ).one()
            return D(row.on_hand_quantity), D(row.reserved_quantity)

    partial_key = "FINAL-PARTIAL-" + uuid4().hex
    await reserve("5", "RESERVE", partial_key)
    assert await balance() == (D("20"), D("5"))
    full_key = "FINAL-FULL-" + uuid4().hex
    await reserve("15", "RESERVE", full_key)
    assert await balance() == (D("20"), D("20"))

    async with pg.session() as db:
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
        row = next(item for item in page["items"] if item["id"] == tenant.variant_id)
        assert (D(row["on_hand_quantity"]), D(row["reserved_quantity"]),
                D(row["available_for_sale_quantity"])) == (D("20"), D("20"), D("0"))

    before_overreserve = await _state_digest(pg, tenant)
    with pytest.raises(InventoryMutationError):
        await reserve("1", "RESERVE", "FINAL-OVER-" + uuid4().hex)
    assert await _state_digest(pg, tenant) == before_overreserve

    # A real warehouse transfer cannot consume physically-present but fully
    # reserved stock, and denial leaves every balance/movement/cost/header intact.
    overallocated = _warehouse_dispatch(tenant, "1")
    before_dispatch = await _state_digest(pg, tenant)
    with pytest.raises(HTTPException) as denied:
        await command(
            pg,
            tenant.owner,
            lambda db, access, actor:
                transfers.unified_transfer_dispatch(overallocated, db, access, actor),
        )
    assert denied.value.status_code == 409
    assert await _state_digest(pg, tenant) == before_dispatch

    await reserve("20", "RELEASE", "FINAL-RELEASE-" + uuid4().hex)
    assert await balance() == (D("20"), D("0"))

    # Competing reserve-vs-external-outbound transactions start from the same
    # 20 units. Row locking must allow only one 15-unit claim to commit.
    async def concurrent_reserve():
        return await reserve("15", "RESERVE", "FINAL-RACE-RES-" + uuid4().hex)

    outbound_key = "FINAL-RACE-OUT-" + uuid4().hex
    async def concurrent_outbound():
        async with pg.session() as db:
            movement = await apply_inventory_movement(
                db,
                company_id=tenant.company_id,
                performed_by=tenant.owner.driver_id,
                product_variant_id=tenant.variant_id,
                batch_id=batch_id,
                quantity=D("15"),
                movement_kind="PHYSICAL",
                reference_type="FINAL_BUSINESS_CONCURRENT_OUTBOUND",
                reference_id=outbound_key,
                idempotency_key=outbound_key,
                source_location_id=tenant.location_id,
                destination_location_id=None,
                source_stock_status="AVAILABLE",
                destination_stock_status=None,
            )
            await db.commit()
            return int(movement.id)

    results = await asyncio.wait_for(
        asyncio.gather(
            concurrent_reserve(),
            concurrent_outbound(),
            return_exceptions=True,
        ),
        timeout=20,
    )
    successes = [value for value in results if isinstance(value, int)]
    failures = [value for value in results if isinstance(value, BaseException)]
    assert len(successes) == 1 and len(failures) == 1
    assert isinstance(failures[0], InventoryMutationError)

    on_hand, reserved = await balance()
    assert (on_hand, reserved) in {
        (D("20"), D("15")),  # reservation won
        (D("5"), D("0")),    # outbound won
    }
    assert on_hand >= 0 and D("0") <= reserved <= on_hand

    async with pg.session() as db:
        state = await db.scalar(
            select(InventoryCostState).where(
                InventoryCostState.company_id == tenant.company_id,
                InventoryCostState.product_variant_id == tenant.variant_id,
            )
        )
        if (on_hand, reserved) == (D("20"), D("15")):
            assert (D(state.quantity), D(state.inventory_value)) == (D("20"), D("40"))
        else:
            assert (D(state.quantity), D(state.inventory_value)) == (D("5"), D("10"))
        assert not bool(
            await db.scalar(
                select(
                    func.count(InventoryBalance.id) > 0
                ).where(
                    InventoryBalance.company_id == tenant.company_id,
                    InventoryBalance.on_hand_quantity < 0,
                )
            )
        )



async def test_concurrent_direct_vehicle_load_and_unload_are_serialized_and_replay_safe(pg):
    """True ADD-vs-UNLOAD race preserves vehicle/warehouse custody and cost truth."""
    tenant = pg.tenants[0]
    payload = pg.request(
        quantity="40",
        cost="2",
        lot="FINAL-VRACE-" + uuid4().hex[:12],
    )
    async with pg.session() as db:
        await pg.post(db, payload)

    async with pg.session() as db:
        inbound_movement = await db.scalar(
            select(InventoryMovement).where(
                InventoryMovement.company_id == tenant.company_id,
                InventoryMovement.reference_type == "INBOUND_SUPPLIER",
                InventoryMovement.reference_id == payload.reference_id,
            )
        )
        assert inbound_movement is not None
        batch_id = int(inbound_movement.batch_id)

    vehicle_id, vehicle_location_id = await _create_vehicle_with_historical_attribution(
        pg, tenant
    )
    initial_key = uuid4()
    initial_items = [{
        "product_variant_id": tenant.variant_id,
        "quantity": D("20"),
    }]
    async with pg.session() as db:
        seeded = await mutate_vehicle_load(
            db,
            access=tenant.owner.access(db),
            actor_id=tenant.owner.driver_id,
            vehicle_id=vehicle_id,
            warehouse_id=tenant.location_id,
            direction="ADD",
            request_id=initial_key,
            items=initial_items,
        )
    assert seeded["direction"] == "ADD"

    async def pair() -> tuple[Decimal, Decimal]:
        async with pg.session() as db:
            rows = (
                await db.execute(
                    select(
                        InventoryBalance.location_id,
                        InventoryBalance.on_hand_quantity,
                    ).where(
                        InventoryBalance.company_id == tenant.company_id,
                        InventoryBalance.product_variant_id == tenant.variant_id,
                        InventoryBalance.batch_id == batch_id,
                        InventoryBalance.stock_status == "AVAILABLE",
                        InventoryBalance.location_id.in_(
                            [tenant.location_id, vehicle_location_id]
                        ),
                    )
                )
            ).all()
            values = {int(location): D(qty) for location, qty in rows}
            return (
                values.get(tenant.location_id, D("0")),
                values.get(vehicle_location_id, D("0")),
            )

    assert await pair() == (D("20"), D("20"))

    add_key, unload_key = uuid4(), uuid4()
    items = [{"product_variant_id": tenant.variant_id, "quantity": D("10")}]

    async def mutation(direction: str, request_id):
        async with pg.session() as db:
            return await mutate_vehicle_load(
                db,
                access=tenant.owner.access(db),
                actor_id=tenant.owner.driver_id,
                vehicle_id=vehicle_id,
                warehouse_id=tenant.location_id,
                direction=direction,
                request_id=request_id,
                items=items,
            )

    add_result, unload_result = await asyncio.wait_for(
        asyncio.gather(
            mutation("ADD", add_key),
            mutation("UNLOAD", unload_key),
        ),
        timeout=20,
    )
    assert add_result["direction"] == "ADD"
    assert unload_result["direction"] == "UNLOAD"
    # Whichever lock holder runs first, both are valid from the 20/20 starting
    # split and the serialized net result must be exactly unchanged.
    assert await pair() == (D("20"), D("20"))

    async with pg.session() as db:
        movement_count = int(
            await db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(InventoryMovement.company_id == tenant.company_id)
            )
            or 0
        )

    assert await mutation("ADD", add_key) == add_result
    assert await mutation("UNLOAD", unload_key) == unload_result

    async with pg.session() as db:
        assert (
            int(
                await db.scalar(
                    select(func.count())
                    .select_from(InventoryMovement)
                    .where(InventoryMovement.company_id == tenant.company_id)
                )
                or 0
            )
            == movement_count
        )
        state = await db.scalar(
            select(InventoryCostState).where(
                InventoryCostState.company_id == tenant.company_id,
                InventoryCostState.product_variant_id == tenant.variant_id,
            )
        )
        assert state is not None
        assert (D(state.quantity), D(state.inventory_value)) == (D("40"), D("80"))
        cost_events = (
            await db.scalars(
                select(InventoryCostEvent).where(
                    InventoryCostEvent.company_id == tenant.company_id,
                    InventoryCostEvent.product_variant_id == tenant.variant_id,
                )
            )
        ).all()
        assert [event.event_type for event in cost_events] == ["PURCHASE_IN"]
        negative = await db.scalar(
            select(func.count())
            .select_from(InventoryBalance)
            .where(
                InventoryBalance.company_id == tenant.company_id,
                InventoryBalance.on_hand_quantity < 0,
            )
        )
        assert int(negative or 0) == 0



async def test_concurrent_warehouse_transfer_and_stocktake_are_serialized_without_partial_state(pg):
    """True transfer-vs-stocktake race has only coherent serialized outcomes."""
    tenant = pg.tenants[0]
    await prepare(pg)

    payload = pg.request(
        quantity="40",
        cost="2",
        lot="FINAL-TR-STK-" + uuid4().hex[:12],
    )
    async with pg.session() as db:
        await pg.post(db, payload)

    transfer_payload = _warehouse_dispatch(tenant, "8")
    before_race = await _state_digest(pg, tenant)
    stocktake_payload = StocktakeStartCommand(
        request_id=uuid4(),
        location_id=tenant.location_id,
        stocktake_type="FULL_COUNT",
    )

    ready: asyncio.Queue[bool] = asyncio.Queue()
    start = asyncio.Event()

    async def race_transfer():
        await ready.put(True)
        await start.wait()
        try:
            result = await command(
                pg,
                tenant.owner,
                lambda db, access, actor:
                    transfers.unified_transfer_dispatch(
                        transfer_payload, db, access, actor
                    ),
            )
            return ("transfer", "ok", result)
        except HTTPException as exc:
            return ("transfer", "denied", exc)

    async def race_stocktake():
        await ready.put(True)
        await start.wait()
        try:
            result = await command(
                pg,
                tenant.owner,
                lambda db, access, actor:
                    stocktake.start_unified_stocktake(
                        stocktake_payload, db, access, actor
                    ),
            )
            return ("stocktake", "ok", result)
        except HTTPException as exc:
            return ("stocktake", "denied", exc)

    tasks = [
        asyncio.create_task(race_transfer()),
        asyncio.create_task(race_stocktake()),
    ]
    try:
        await asyncio.wait_for(ready.get(), 20)
        await asyncio.wait_for(ready.get(), 20)
        start.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 25)
    finally:
        start.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    transfer_result = next(row for row in results if row[0] == "transfer")
    stocktake_result = next(row for row in results if row[0] == "stocktake")
    assert stocktake_result[1] == "ok", results

    stocktake_response = stocktake_result[2]
    session_id = int(stocktake_response["session_id"])

    async with pg.session() as db:
        snapshot_qty = D(
            await db.scalar(
                select(StocktakeLine.expected_quantity).where(
                    StocktakeLine.company_id == tenant.company_id,
                    StocktakeLine.stocktake_session_id == session_id,
                    StocktakeLine.product_variant_id == tenant.variant_id,
                )
            )
            or 0
        )
        balances = (
            await db.execute(
                select(
                    InventoryBalance.location_id,
                    InventoryBalance.on_hand_quantity,
                ).where(
                    InventoryBalance.company_id == tenant.company_id,
                    InventoryBalance.product_variant_id == tenant.variant_id,
                    InventoryBalance.stock_status == "AVAILABLE",
                    InventoryBalance.on_hand_quantity > 0,
                )
            )
        ).all()
        physical = {int(location): D(qty) for location, qty in balances}
        state = await db.scalar(
            select(InventoryCostState).where(
                InventoryCostState.company_id == tenant.company_id,
                InventoryCostState.product_variant_id == tenant.variant_id,
            )
        )
        assert state is not None
        assert (D(state.quantity), D(state.inventory_value)) == (
            D("40"), D("80")
        )

    if transfer_result[1] == "ok":
        # Transfer acquired the shared location guard first and committed before
        # stocktake took its exclusive guard; the count snapshot is post-transfer.
        header_id = int(transfer_result[2]["header_id"])
        async with pg.session() as db:
            header = await db.get(InventoryTransferHeader, header_id)
            assert header is not None and header.status == "IN_TRANSIT"
            transit_id = int(header.transit_location_id)
        assert snapshot_qty == D("32")
        assert physical.get(tenant.location_id, D("0")) == D("32")
        assert physical.get(transit_id, D("0")) == D("8")
    else:
        # Stocktake acquired the exclusive location guard first; after it commits
        # the active InventoryLock is re-read by the movement engine and blocks
        # the transfer atomically.
        denied = transfer_result[2]
        assert isinstance(denied, HTTPException)
        assert denied.status_code == 409
        assert snapshot_qty == D("40")
        assert physical.get(tenant.location_id, D("0")) == D("40")
        # Stocktake start itself owns no inventory/cost movement. A denied
        # transfer must therefore leave the complete inventory/cost/transfer
        # digest byte-for-byte equivalent to the pre-race state.
        assert await _state_digest(pg, tenant) == before_race

    # Both legitimate schedules conserve all forty base units and never create
    # COGS/value change for an internal transfer.
    assert sum(physical.values(), D("0")) == D("40")
    async with pg.session() as db:
        costs = (
            await db.scalars(
                select(InventoryCostEvent).where(
                    InventoryCostEvent.company_id == tenant.company_id,
                    InventoryCostEvent.product_variant_id == tenant.variant_id,
                )
            )
        ).all()
        assert len(costs) == 1
        assert costs[0].event_type == "PURCHASE_IN"
        assert D(costs[0].total_cost) == D("80")
        negative = await db.scalar(
            select(func.count())
            .select_from(InventoryBalance)
            .where(
                InventoryBalance.company_id == tenant.company_id,
                InventoryBalance.on_hand_quantity < 0,
            )
        )
        assert int(negative or 0) == 0
