"""M04 independent rules; these tests do not claim PG16/HTTP acceptance."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from domains.representative_settlement_multi_vehicle.contracts import (
    BalanceEvidence, CountLine, CustodyRejected, EpochEvidence, PeriodEvidence,
    VehicleCountCommand, VehicleSnapshot,
)
from domains.representative_settlement_multi_vehicle.policy import (
    command_hash, line_key, resolve_responsibilities, snapshot_token, validate_count,
)

NOW = datetime(2026, 11, 12, 8)


def scenario():
    def period(i, vehicle, revision):
        return PeriodEvidence(i, 1, 71, 103, 213, vehicle, vehicle + 100,
                              revision, "CLOSED", NOW + timedelta(hours=i),
                              NOW + timedelta(hours=i, minutes=50), True)
    def epoch(i, vehicle):
        return EpochEvidence(i, 1, 71, 213, vehicle, vehicle + 100, i,
                             "ACCEPTED", NOW + timedelta(hours=i),
                             NOW + timedelta(hours=i + 1), 391, True)
    return (period(1, 10, 1), period(2, 20, 1), period(3, 10, 2)), (
        epoch(1, 10), epoch(2, 20), epoch(3, 10),
    )


def vehicles(periods=None, epochs=None):
    ps, es = scenario()
    return resolve_responsibilities(company_id=1, session_id=71, driver_id=103,
                                    periods=ps if periods is None else periods,
                                    epochs=es if epochs is None else epochs)


def snapshot():
    a = vehicles()[0]
    return VehicleSnapshot(1, 71, a, 3, 3, 812, (
        BalanceEvidence(12, 19, "AVAILABLE", Decimal("83"), Decimal(0), 3, Decimal(".001")),
        BalanceEvidence(12, 19, "DAMAGED", Decimal("2.125"), Decimal(0), 3, Decimal(".001")),
    ))


def command(s=None, **changes):
    s = s or snapshot()
    return VehicleCountCommand(**{
        "request_id": uuid4(), "mode": "COUNT_IN_PLACE",
        "snapshot_token": snapshot_token(s), "receiver_confirms_count": True,
        "items": [CountLine(line_key=line_key(s, r), actual_quantity=str(r.quantity)) for r in s.rows],
        **changes,
    })


def test_aba_resolves_distinct_vehicle_and_all_responsibility_epochs():
    a, b = vehicles()
    assert a.vehicle_id == 10 and a.period_ids == (1, 3) and a.epoch_ids == (1, 3)
    assert b.vehicle_id == 20 and b.period_ids == (2,) and b.epoch_ids == (2,)


def test_pre_session_signed_custody_is_resolved_only_from_exact_period_identity_and_interval():
    ps, es = scenario()
    unbound = tuple(replace(e, session_id=None) for e in es)
    assert vehicles(ps, unbound) == vehicles()
    with pytest.raises(CustodyRejected):
        vehicles(ps, (*unbound, replace(unbound[0], id=10, vehicle_id=30, location_id=130)))


@pytest.mark.parametrize("change", [
    {"company_id": 2}, {"session_id": 72}, {"driver_id": 104},
    {"representative_id": 214}, {"state": "HISTORICAL"}, {"canonical": False},
    {"location_id": 120}, {"ended_at": None},
])
def test_inconsistent_period_never_falls_back_to_last_route(change):
    ps, es = scenario()
    with pytest.raises(CustodyRejected):
        vehicles((replace(ps[0], **change), *ps[1:]), es)


@pytest.mark.parametrize("change", [
    {"company_id": 2}, {"session_id": 72}, {"representative_id": 214},
    {"state": "NEEDS_REVIEW"}, {"canonical": False}, {"accepted_by": None},
])
def test_missing_unsigned_or_foreign_custody_fails_closed(change):
    ps, es = scenario()
    with pytest.raises(CustodyRejected):
        vehicles(ps, (replace(es[0], **change), *es[1:]))


def test_ambiguous_overlapping_epoch_fails_closed():
    ps, es = scenario()
    with pytest.raises(CustodyRejected, match="AMBIGUOUS"):
        vehicles(ps, (*es, replace(es[0], id=4)))


def test_no_canonical_period_never_guesses_vehicle():
    with pytest.raises(CustodyRejected, match="REVIEW_REQUIRED"):
        vehicles(())


def test_exact_match_accepts_every_status_without_any_movement_instruction():
    s = snapshot()
    assert tuple(validate_count(s, command(s)).values()) == (Decimal(83), Decimal("2.125"))
    assert command(s).destination_location_id is None


@pytest.mark.parametrize("change", [
    {"movement_watermark": 813}, {"latest_epoch_revision": 5}, {"latest_epoch_id": 5},
    {"session_id": 72}, {"company_id": 2},
])
def test_stale_and_aba_snapshot_cannot_be_sealed(change):
    s = snapshot()
    with pytest.raises(CustodyRejected, match="SNAPSHOT_STALE"):
        validate_count(replace(s, **change), command(s))


def test_equal_balance_after_out_and_back_is_still_stale():
    s = snapshot()
    assert snapshot_token(s) != snapshot_token(replace(s, movement_watermark=820))


def test_one_vehicle_count_never_seals_another():
    s = snapshot()
    b = replace(s, responsibility=vehicles()[1])
    with pytest.raises(CustodyRejected, match="SNAPSHOT_STALE"):
        validate_count(b, command(s))
    assert line_key(s, s.rows[0]) != line_key(b, b.rows[0])


@pytest.mark.parametrize("quantity", ["-1", "NaN", "Infinity", "1.0001"])
def test_invalid_physical_quantity_rejected(quantity):
    s = snapshot()
    cmd = command(s)
    cmd.items[0].actual_quantity = quantity
    with pytest.raises(CustodyRejected, match="INVALID_PHYSICAL_QUANTITY"):
        validate_count(s, cmd)


def test_partial_or_foreign_lines_cannot_be_counted():
    s = snapshot()
    with pytest.raises(CustodyRejected, match="INCOMPLETE_OR_STALE"):
        validate_count(s, command(s, items=[command(s).items[0]]))


@pytest.mark.parametrize("change", [
    {"destination_location_id": 400}, {"receiver_confirms_handoff": True},
    {"receiver_confirms_count": False}, {"mode": "PHYSICAL_HANDOFF"},
    {"unexpected_field": True},
])
def test_modes_and_receiver_signature_cannot_be_confused(change):
    with pytest.raises(ValidationError):
        command(**change)


def test_physical_handoff_requires_actual_receiver_confirmation():
    cmd = command(mode="PHYSICAL_HANDOFF", destination_location_id=400, receiver_confirms_handoff=True)
    assert cmd.mode == "PHYSICAL_HANDOFF"


def test_request_hash_is_order_independent_but_rejects_changed_quantities_or_mode():
    cmd = command()
    assert command_hash(71, 10, cmd) == command_hash(71, 10, cmd.model_copy(update={"items": cmd.items[::-1]}))
    changed = cmd.model_copy(deep=True)
    changed.items[0].actual_quantity = "82"
    assert command_hash(71, 10, cmd) != command_hash(71, 10, changed)
    assert command_hash(71, 10, cmd) != command_hash(71, 20, cmd)


def test_reserved_quantity_and_duplicate_stock_buckets_fail_closed():
    s = snapshot()
    for rows in ((replace(s.rows[0], reserved=Decimal(1)),), (s.rows[0], s.rows[0])):
        with pytest.raises(CustodyRejected):
            snapshot_token(replace(s, rows=rows))
