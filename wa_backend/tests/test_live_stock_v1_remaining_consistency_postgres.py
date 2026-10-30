"""Remaining Live Stock V1 committed-read and disclosure acceptance.

This file intentionally does not re-prove R1's one-statement snapshot.  It
tests the remaining contract BETWEEN independent requests: every response is a
fresh READ COMMITTED observation of its own statement(s), while callers must
not pretend list/summary/batch/source responses share one atomic snapshot.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from api.warehouse import live_stock
from models import UserLocationAccess
from tests.live_stock_r1_support import (
    D,
    assert_truth,
    cursor_kwargs,
    move,
    r1case,
    spec,
)
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_live_stock_v1_safety_sales_policy_postgres import (
    _batch_detail_row,
    _batch_id,
    _company_date,
    _set_company_timezone,
)


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_REMAINING_CONSISTENCY_PG_GATE") != "1",
        reason="Explicit disposable PostgreSQL 16 remaining-consistency gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


def _list_item(case, response):
    return next(
        item
        for item in response["items"]
        if int(item["id"]) == int(case.tenant.variant_id)
    )


def _batch_item(case, response):
    return next(
        item
        for item in response["batches"]
        if int(item["batch_id"]) == int(case.batch_id)
    )


def _source_available(response) -> dict[int, tuple[str, Decimal, Decimal]]:
    result = {}
    for source in response["sources"]:
        available = next(
            (
                status
                for status in source["statuses"]
                if status["stock_status"] == "AVAILABLE"
            ),
            None,
        )
        if available is not None:
            result[int(source["location_id"])] = (
                str(source["location_type"]),
                D(available["on_hand_quantity"]),
                D(available["reserved_quantity"]),
            )
    return result


async def test_independent_requests_observe_real_committed_instants_without_fake_atomicity(
    r1case,
):
    """Interleave a committed move between surfaces and prove the real contract."""
    case = r1case

    # Initial committed truth from the existing R1 fixture is W=10, V=10.
    await assert_truth(case, warehouse="10", vehicle="10")
    async with case.pg.session() as db:
        access = case.tenant.ordinary.access(db)
        old_list = await live_stock.get_warehouse_inventory(
            **cursor_kwargs(case, db)
        )
        old_row = _list_item(case, old_list)
        old_summary = await live_stock.get_warehouse_inventory_summary(
            case.warehouse_id, db, access
        )
        old_detail = await live_stock.get_warehouse_inventory_batches(
            case.tenant.variant_id,
            case.warehouse_id,
            None,
            100,
            db,
            access,
        )
        old_sources = await live_stock.get_batch_stock_sources(
            case.batch_id, db, access
        )

        assert (
            D(old_row["on_hand_quantity"]),
            D(old_row["vehicle_quantity"]),
        ) == (D("10"), D("10"))
        assert D(_batch_item(case, old_detail)["on_hand_quantity"]) == D("10")
        assert _source_available(old_sources) == {
            case.warehouse_id: ("WAREHOUSE", D("10"), D("0")),
            case.vehicle_id: ("VEHICLE", D("10"), D("0")),
        }
        assert int(old_summary["stock_total"]) == 1

        # Commit a real inventory movement in a different transaction while the
        # same reader session remains open. READ COMMITTED means later endpoint
        # calls legitimately see the newer committed instant.
        async with case.pg.session() as writer:
            await move(
                writer,
                case,
                spec(
                    case,
                    source=case.vehicle_id,
                    destination=case.warehouse_id,
                    quantity="5",
                ),
            )
            await writer.commit()

        await assert_truth(case, warehouse="15", vehicle="5")

        # Intentionally do NOT re-read the list yet. These newer responses are
        # allowed to disagree with the old list because they are independent
        # requests/statements; no shared snapshot token is claimed by the API.
        new_summary = await live_stock.get_warehouse_inventory_summary(
            case.warehouse_id, db, access
        )
        new_detail = await live_stock.get_warehouse_inventory_batches(
            case.tenant.variant_id,
            case.warehouse_id,
            None,
            100,
            db,
            access,
        )
        new_sources = await live_stock.get_batch_stock_sources(
            case.batch_id, db, access
        )
        assert int(new_summary["stock_total"]) == 1
        assert D(_batch_item(case, new_detail)["on_hand_quantity"]) == D("15")
        assert _source_available(new_sources) == {
            case.warehouse_id: ("WAREHOUSE", D("15"), D("0")),
            case.vehicle_id: ("VEHICLE", D("5"), D("0")),
        }

        # The already-returned list remains an old observation in caller memory.
        # A fresh list request catches up to the same committed truth.
        assert (
            D(old_row["on_hand_quantity"]),
            D(old_row["vehicle_quantity"]),
        ) == (D("10"), D("10"))
        refreshed_list = await live_stock.get_warehouse_inventory(
            **cursor_kwargs(case, db)
        )
        refreshed_row = _list_item(case, refreshed_list)
        assert (
            D(refreshed_row["on_hand_quantity"]),
            D(refreshed_row["vehicle_quantity"]),
        ) == (D("15"), D("5"))

    print(
        "REMAINING_READ_CONSISTENCY "
        + json.dumps(
            {
                "contract": "independent_committed_instants",
                "before": {"warehouse": "10", "vehicle": "10"},
                "after": {"warehouse": "15", "vehicle": "5"},
                "summary_semantics": "variant-count-not-quantity",
                "cross_request_atomic_snapshot": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )


async def test_restricted_location_vehicle_and_foreign_disclosure_revoke_immediately(
    r1case,
):
    """One persisted access subject never sees revoked, hidden or foreign stock."""
    case = r1case

    # Give the second company one real batch so foreign-batch opacity is tested
    # against an existing object, not a made-up identifier.
    foreign = case.pg.tenants[1]
    foreign_payload = case.pg.request(
        party=1,
        quantity="3",
        cost="7",
        lot="FOREIGN-READ-" + os.urandom(6).hex(),
    )
    async with case.pg.session(1) as foreign_db:
        await case.pg.post(foreign_db, foreign_payload, party=1)
    foreign_snapshot = await case.pg.snapshot(party=1)
    foreign_batch_id = int(foreign_snapshot["batches"][-1][0])

    async with case.pg.session() as db:
        # Keep exactly one capability-access object alive across committed grant
        # revocations. Its decisions must re-read persisted grants.
        access = case.tenant.ordinary.access(db)

        initial_list = await live_stock.get_warehouse_inventory(
            **cursor_kwargs(case, db)
        )
        initial_row = _list_item(case, initial_list)
        assert D(initial_row["vehicle_quantity"]) == D("10")

        initial_sources = await live_stock.get_batch_stock_sources(
            case.batch_id, db, access
        )
        assert set(_source_available(initial_sources)) == {
            case.warehouse_id,
            case.vehicle_id,
        }

        # Foreign company/location and a genuine foreign batch stay opaque.
        with pytest.raises(HTTPException) as foreign_location:
            await live_stock.get_warehouse_inventory(
                **cursor_kwargs(
                    case,
                    db,
                    location_id=foreign.location_id,
                )
            )
        assert foreign_location.value.status_code in {403, 404}
        with pytest.raises(HTTPException) as foreign_batch:
            await live_stock.get_batch_stock_sources(
                foreign_batch_id, db, access
            )
        assert foreign_batch.value.status_code == 404

        # Revoke only Vehicle inventory.read in a separate committed transaction.
        async with case.pg.session() as revoke:
            await revoke.execute(
                delete(UserLocationAccess).where(
                    UserLocationAccess.company_id == case.tenant.company_id,
                    UserLocationAccess.driver_id
                    == case.tenant.ordinary.driver_id,
                    UserLocationAccess.location_id == case.vehicle_id,
                )
            )
            await revoke.commit()

        hidden_list = await live_stock.get_warehouse_inventory(
            **cursor_kwargs(case, db)
        )
        hidden_row = _list_item(case, hidden_list)
        assert (
            D(hidden_row["on_hand_quantity"]),
            D(hidden_row["vehicle_quantity"]),
        ) == (D("10"), D("0"))
        vehicle_filter = await live_stock.get_warehouse_inventory(
            **cursor_kwargs(case, db, has_vehicle=True)
        )
        assert vehicle_filter["items"] == []

        hidden_sources = await live_stock.get_batch_stock_sources(
            case.batch_id, db, access
        )
        assert _source_available(hidden_sources) == {
            case.warehouse_id: ("WAREHOUSE", D("10"), D("0"))
        }
        hidden_detail = await live_stock.get_warehouse_inventory_batches(
            case.tenant.variant_id,
            case.warehouse_id,
            None,
            100,
            db,
            access,
        )
        assert D(_batch_item(case, hidden_detail)["on_hand_quantity"]) == D("10")
        hidden_summary = await live_stock.get_warehouse_inventory_summary(
            case.warehouse_id, db, access
        )
        assert int(hidden_summary["stock_total"]) == 1

        # Revoke the remaining Warehouse scope. Reusing the SAME access object
        # must fail every warehouse surface immediately; batch source becomes
        # opaque because no readable physical source remains.
        async with case.pg.session() as revoke:
            await revoke.execute(
                delete(UserLocationAccess).where(
                    UserLocationAccess.company_id == case.tenant.company_id,
                    UserLocationAccess.driver_id
                    == case.tenant.ordinary.driver_id,
                    UserLocationAccess.location_id == case.warehouse_id,
                )
            )
            await revoke.commit()

        for operation in (
            lambda: live_stock.get_warehouse_inventory(**cursor_kwargs(case, db)),
            lambda: live_stock.get_warehouse_inventory_summary(
                case.warehouse_id, db, access
            ),
            lambda: live_stock.get_warehouse_inventory_batches(
                case.tenant.variant_id,
                case.warehouse_id,
                None,
                100,
                db,
                access,
            ),
        ):
            with pytest.raises(HTTPException) as denied:
                await operation()
            assert denied.value.status_code in {403, 404}

        with pytest.raises(HTTPException) as hidden_batch:
            await live_stock.get_batch_stock_sources(
                case.batch_id, db, access
            )
        # Once every inventory.read grant is revoked, canonical authorization
        # rejects before object lookup. 403 is the exact fail-closed contract;
        # the earlier foreign-batch probe under a valid Warehouse grant remains
        # strict 404 opacity.
        assert hidden_batch.value.status_code == 403

    print(
        "REMAINING_DISCLOSURE "
        + json.dumps(
            {
                "same_subject_revocation": True,
                "vehicle_hidden_after_revoke": True,
                "warehouse_denied_after_revoke": True,
                "foreign_location_opaque": True,
                "foreign_batch_opaque": True,
            },
            sort_keys=True,
        ),
        flush=True,
    )



async def test_company_local_day_overrides_client_process_day_at_expiry_boundary(pg):
    """Backend sellability follows company day, never a browser/process calendar."""
    tenant = pg.tenants[0]
    process_day = date.today()

    # Find two real company timezones that straddle one commercial-date boundary
    # at this exact database instant. At least one side must differ from the
    # runner/browser-like process calendar, which proves client date is irrelevant.
    observed = {}
    for zone in ("Etc/GMT+12", "UTC", "Pacific/Kiritimati"):
        await _set_company_timezone(pg, tenant, zone)
        observed[zone] = await _company_date(pg, tenant)

    pairs = [
        (a, b)
        for a in observed
        for b in observed
        if observed[b] == observed[a] + timedelta(days=1)
    ]
    assert pairs, observed
    zone_before, zone_after = next(
        (
            (a, b)
            for a, b in pairs
            if observed[a] != process_day or observed[b] != process_day
        ),
        pairs[0],
    )
    day_before = observed[zone_before]
    day_after = observed[zone_after]
    assert day_after == day_before + timedelta(days=1)
    assert process_day in {
        day_before - timedelta(days=1),
        day_before,
        day_after,
        day_after + timedelta(days=1),
    }

    await _set_company_timezone(pg, tenant, zone_before)
    batch_number = "LOCAL-DAY-" + os.urandom(6).hex()
    inbound_request = pg.request(
        lot=batch_number,
        quantity="6",
        cost="2",
        production=day_before - timedelta(days=5),
        expiry=day_before,
    )
    async with pg.session() as db:
        assert await pg.post(db, inbound_request) == {"message": "INBOUND_POSTED"}
    batch_id = await _batch_id(pg, tenant, batch_number)

    before = await _batch_detail_row(pg, tenant, batch_id)
    assert before["days_to_expiry"] == 0
    assert D(before["on_hand_quantity"]) == D("6")
    assert D(before["available_for_sale_quantity"]) == D("6")

    # No stock, batch metadata, request payload, or process/browser clock changes.
    # Only the authoritative company timezone crosses the next company-local day.
    await _set_company_timezone(pg, tenant, zone_after)
    assert await _company_date(pg, tenant) == day_after
    after = await _batch_detail_row(pg, tenant, batch_id)
    assert after["days_to_expiry"] == -1
    assert D(after["on_hand_quantity"]) == D("6")
    assert D(after["available_for_sale_quantity"]) == D("0")
    assert D(after["expiry_unavailable_quantity"]) == D("6")

    print(
        "REMAINING_COMPANY_DAY "
        + json.dumps(
            {
                "process_day": process_day.isoformat(),
                "company_day_before": day_before.isoformat(),
                "company_day_after": day_after.isoformat(),
                "company_timezone_before": zone_before,
                "company_timezone_after": zone_after,
                "client_date_authority": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
