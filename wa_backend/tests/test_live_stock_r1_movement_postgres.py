"""Movement-only R1 proofs: real commits, independent ledger and Decimal custody."""
from __future__ import annotations

import asyncio
import os
import pytest
from services import InventoryMutationError
from tests.test_inbound_no_lot_frozen_postgres import pg
from tests.live_stock_r1_support import (
    D, WAIT, assert_truth, emit, move, r1case, spec,
)

pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_R1_PG_GATE") != "1",
                       reason="Explicit disposable R1 PostgreSQL gate only"),
    pytest.mark.asyncio(loop_scope="function"),
]


async def test_movement_commit_is_atomic_and_ledger_conserves_twenty(r1case):
    case = r1case
    command = spec(case, source=case.vehicle_id, destination=case.warehouse_id)
    before = await assert_truth(case, warehouse="10", vehicle="10")
    async with case.pg.session() as writer:
        movement_id = await move(writer, case, command)
        # Another connection sees the entire pre-commit state, never one side.
        assert await assert_truth(case, warehouse="10", vehicle="10") == before
        await writer.commit()
    after = await assert_truth(case, warehouse="20", vehicle="0")
    assert after["movement_count"] == before["movement_count"] + 1
    assert after["impact_count"] == before["impact_count"] + 2
    async with case.pg.session() as db:
        assert await move(db, case, command) == movement_id
        await db.commit()
    assert await assert_truth(case, warehouse="20", vehicle="0") == after
    async with case.pg.session() as db:
        with pytest.raises(InventoryMutationError):
            await move(db, case, {**command, "quantity": D("9")})
        await db.rollback()
    assert await assert_truth(case, warehouse="20", vehicle="0") == after
    emit("movement_commit_and_replay", before=before, after=after)


async def test_rollback_discards_both_sides_ledger_and_projection(r1case):
    case = r1case
    command = spec(case, source=case.vehicle_id, destination=case.warehouse_id)
    before = await assert_truth(case, warehouse="10", vehicle="10")
    async with case.pg.session() as db:
        await move(db, case, command)
        assert await assert_truth(case, warehouse="10", vehicle="10") == before
        await db.rollback()  # Failure after engine flush, before caller commit.
    assert await assert_truth(case, warehouse="10", vehicle="10") == before
    # A rolled-back key is not poisoned; the identical command can succeed once.
    async with case.pg.session() as db:
        await move(db, case, command)
        await db.commit()
    emit("rollback_then_retry", after=await assert_truth(case, warehouse="20", vehicle="0"))


async def test_concurrent_identical_commands_have_one_movement(r1case):
    case = r1case
    command = spec(case, source=case.vehicle_id, destination=case.warehouse_id)
    before = await assert_truth(case, warehouse="10", vehicle="10")
    ready, start = asyncio.Queue(), asyncio.Event()

    async def worker():
        async with case.pg.session() as db:
            await ready.put(True)
            await asyncio.wait_for(start.wait(), WAIT)
            result = await move(db, case, command)
            await db.commit()
            return result

    tasks = [asyncio.create_task(worker()) for _ in range(2)]
    try:
        await asyncio.wait_for(ready.get(), WAIT)
        await asyncio.wait_for(ready.get(), WAIT)
        start.set()
        ids = await asyncio.wait_for(asyncio.gather(*tasks), WAIT)
    finally:
        start.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert ids[0] == ids[1]
    after = await assert_truth(case, warehouse="20", vehicle="0")
    assert after["movement_count"] == before["movement_count"] + 1
    assert after["impact_count"] == before["impact_count"] + 2
    emit("concurrent_replay", movement_id=ids[0], after=after)


async def test_competing_reservation_and_transfer_never_overspend(r1case):
    case = r1case
    transfer = spec(case, source=case.vehicle_id, destination=case.warehouse_id)
    reservation = spec(case, source=case.vehicle_id, destination=case.vehicle_id,
                       quantity="1", reservation="RESERVE")
    ready, start = asyncio.Queue(), asyncio.Event()

    async def worker(command):
        async with case.pg.session() as db:
            await ready.put(True)
            await asyncio.wait_for(start.wait(), WAIT)
            try:
                await move(db, case, command)
                await db.commit()
                return True
            except InventoryMutationError:
                await db.rollback()
                return False

    tasks = [asyncio.create_task(worker(command)) for command in (transfer, reservation)]
    try:
        await asyncio.wait_for(ready.get(), WAIT)
        await asyncio.wait_for(ready.get(), WAIT)
        start.set()
        moved, reserved = await asyncio.wait_for(asyncio.gather(*tasks), WAIT)
    finally:
        start.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert moved != reserved  # Exactly one complete operation; neither partial nor negative.
    if moved:
        after = await assert_truth(case, warehouse="20", vehicle="0")
    else:
        after = await assert_truth(case, warehouse="10", vehicle="10", reserved_vehicle="1")
        release = spec(case, source=case.vehicle_id, destination=case.vehicle_id,
                       quantity="1", reservation="RELEASE")
        async with case.pg.session() as db:
            await move(db, case, release)
            await db.commit()
        async with case.pg.session() as db:
            await move(db, case, transfer)
            await db.commit()
        await assert_truth(case, warehouse="20", vehicle="0")
    emit("reservation_race", transfer_won=moved, reservation_won=reserved, after=after)


async def test_foreign_movement_identity_is_rejected_without_effect(r1case):
    case = r1case
    foreign = case.pg.tenants[1]
    before = await assert_truth(case, warehouse="10", vehicle="10")
    command = spec(case, source=case.vehicle_id, destination=foreign.location_id)
    async with case.pg.session() as db:
        with pytest.raises(InventoryMutationError):
            await move(db, case, command)
        await db.rollback()
    assert await assert_truth(case, warehouse="10", vehicle="10") == before
    emit("foreign_destination_rejected", after=before)
