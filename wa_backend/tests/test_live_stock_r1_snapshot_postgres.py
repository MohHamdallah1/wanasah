"""Strict R1 read-integrity gates. Known base defects stay red, never xfail."""
from __future__ import annotations

import os

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from api.warehouse import live_stock
from models import InventoryBalance, UserLocationAccess
from tests.test_inbound_no_lot_frozen_postgres import pg
from tests.live_stock_r1_support import (
    D, assert_truth, cursor_kwargs, emit, raced_read, r1case, spec,
)

pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_R1_PG_GATE") != "1",
                       reason="Explicit disposable R1 PostgreSQL gate only"),
    pytest.mark.asyncio(loop_scope="function"),
]


def item(case, response):
    return next(row for row in response["items"] if row["id"] == case.tenant.variant_id)


def partition(row):
    assert D(row["on_hand_quantity"]) == (
        D(row["reserved_quantity"]) + D(row["available_for_sale_quantity"])
        + D(row["unavailable_quantity"])
    )


async def test_restricted_reader_never_combines_old_vehicle_with_new_warehouse(r1case):
    case = r1case
    response, statements = await raced_read(
        case, boundary="vehicle",
        command=spec(case, source=case.vehicle_id, destination=case.warehouse_id),
    )
    physical = await assert_truth(case, warehouse="20", vehicle="0")
    row = item(case, response)
    partition(row)
    observed = (D(row["on_hand_quantity"]), D(row["vehicle_quantity"]))
    emit("restricted_snapshot", physical=physical, observed=list(map(str, observed)),
         observed_total=str(sum(observed, D("0"))),
         paused_after="combined_inventory_page_statement",
         query_boundary_count=len(statements))
    # Both coherent instants are valid. (20,10) must fail this acceptance gate.
    assert observed in {(D("10"), D("10")), (D("20"), D("0"))}, (
        f"R1 mixed snapshot: {observed}; persisted W=20,V=0,total=20"
    )
    assert sum(observed, D("0")) == D("20")


async def test_sellable_filter_candidates_and_details_share_snapshot(r1case):
    case = r1case
    response, statements = await raced_read(
        case, boundary="candidates", filters={"stock_state": "sellable"},
        command=spec(case, source=case.warehouse_id, destination=case.vehicle_id),
    )
    physical = await assert_truth(case, warehouse="0", vehicle="20")
    observed = [
        (row["id"], row["available_for_sale_quantity"]) for row in response["items"]
    ]
    emit("sellable_candidate_detail", physical=physical, observed=observed,
         paused_before="combined_inventory_page_statement",
         query_boundary_count=len(statements))
    # A before snapshot may include sellable=10; an after snapshot excludes it.
    assert all(D(row["available_for_sale_quantity"]) > D("0")
               for row in response["items"]), "R1 candidate matched sellable but detail is zero"
    for row in response["items"]:
        partition(row)


async def test_rolled_back_writer_cannot_change_read_response(r1case):
    case = r1case
    response, _ = await raced_read(
        case, boundary="vehicle", commit=False,
        command=spec(case, source=case.vehicle_id, destination=case.warehouse_id),
    )
    physical = await assert_truth(case, warehouse="10", vehicle="10")
    row = item(case, response)
    partition(row)
    assert (D(row["on_hand_quantity"]), D(row["vehicle_quantity"])) == (D("10"), D("10"))
    emit("reader_writer_rollback", physical=physical)


async def test_exact_warehouse_vehicle_and_company_read_permissions(r1case):
    case = r1case
    async with case.pg.session() as db:
        access = case.tenant.ordinary.access(db)
        assert not bool(await db.scalar(select(access.allows("inventory.read"))))
        assert bool(await db.scalar(select(access.allows("inventory.read", case.warehouse_id))))
        assert bool(await db.scalar(select(access.allows("inventory.read", case.vehicle_id))))
        row = item(case, await live_stock.get_warehouse_inventory(**cursor_kwargs(case, db)))
        assert D(row["vehicle_quantity"]) == D("10")
        for location in (case.tenant.other_location_id, case.pg.tenants[1].location_id):
            with pytest.raises(HTTPException) as denied:
                await live_stock.get_warehouse_inventory(
                    **cursor_kwargs(case, db, location_id=location))
            assert denied.value.status_code in {403, 404}
        # FORCE RLS, even with the explicit company condition deliberately absent.
        assert await db.scalar(select(InventoryBalance.id).where(
            InventoryBalance.location_id == case.pg.tenants[1].location_id
        )) is None

        async with case.pg.session() as revoke:
            await revoke.execute(delete(UserLocationAccess).where(
                UserLocationAccess.company_id == case.tenant.company_id,
                UserLocationAccess.driver_id == case.tenant.ordinary.driver_id,
                UserLocationAccess.location_id == case.vehicle_id,
            ))
            await revoke.commit()
        # Reuse the same persisted capability subject/session after committed revoke.
        hidden = item(case, await live_stock.get_warehouse_inventory(**cursor_kwargs(case, db)))
        assert D(hidden["on_hand_quantity"]) == D("10")
        assert D(hidden["vehicle_quantity"]) == D("0")
        filtered = await live_stock.get_warehouse_inventory(
            **cursor_kwargs(case, db, has_vehicle=True))
        assert filtered["items"] == []

        async with case.pg.session() as revoke:
            await revoke.execute(delete(UserLocationAccess).where(
                UserLocationAccess.company_id == case.tenant.company_id,
                UserLocationAccess.driver_id == case.tenant.ordinary.driver_id,
                UserLocationAccess.location_id == case.warehouse_id,
            ))
            await revoke.commit()
        with pytest.raises(HTTPException) as denied:
            await live_stock.get_warehouse_inventory(**cursor_kwargs(case, db))
        assert denied.value.status_code == 403
    emit("exact_read_scope_and_live_revocation", physical=await assert_truth(
        case, warehouse="10", vehicle="10"))


@pytest.mark.parametrize("boundary,expected", [
    ("before-statement", (D("20"), D("0"))),
    ("after-statement", (D("10"), D("10"))),
])
async def test_combined_statement_before_and_after_controls(r1case, boundary, expected):
    case = r1case
    response, _ = await raced_read(
        case, boundary=boundary,
        command=spec(case, source=case.vehicle_id, destination=case.warehouse_id),
    )
    await assert_truth(case, warehouse="20", vehicle="0")
    row = item(case, response)
    assert (D(row["on_hand_quantity"]), D(row["vehicle_quantity"])) == expected
    partition(row)


@pytest.mark.parametrize("boundary", ["before-statement", "after-statement"])
async def test_sellable_filter_before_and_after_controls(r1case, boundary):
    case = r1case
    response, _ = await raced_read(
        case, boundary=boundary, filters={"stock_state": "sellable"},
        command=spec(case, source=case.warehouse_id, destination=case.vehicle_id),
    )
    await assert_truth(case, warehouse="0", vehicle="20")
    if boundary == "before-statement":
        assert response["items"] == []
    else:
        row = item(case, response)
        assert D(row["available_for_sale_quantity"]) == D("10")
        assert D(row["vehicle_quantity"]) == D("10")
        partition(row)
