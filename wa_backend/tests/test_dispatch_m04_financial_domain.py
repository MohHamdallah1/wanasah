"""All-vehicle coverage and immutable signed-successor financial release rules.

Pure rule tests: no PG/HTTP/financial-posting acceptance claim.
"""
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace as NS

import pytest

from domains.representative_settlement_multi_vehicle.contracts import CustodyRejected
from domains.representative_settlement_multi_vehicle.financial_readiness import (
    require_complete_coverage, require_unchanged_or_signed_successor,
)
from tests.test_dispatch_m04_domain import NOW, vehicles


def receipt(vehicle, receipt_id):
    return NS(id=receipt_id, vehicle_id=vehicle.vehicle_id,
              vehicle_location_id=vehicle.location_id, context_digest=vehicle.context_digest,
              signed_by_principal_id=391, signed_at=NOW + timedelta(hours=4),
              mode="COUNT_IN_PLACE", latest_epoch_id=3, latest_epoch_revision=3,
              final_movement_watermark=812,
              context_manifest={"period_ids": list(vehicle.period_ids),
                                "epoch_ids": list(vehicle.epoch_ids)})


def test_all_vehicles_and_each_epoch_are_required_once():
    a, b = vehicles()
    ca, cb = receipt(a, 101), receipt(b, 102)
    links = {101: {1, 3}, 102: {2}}
    assert set(require_complete_coverage((a, b), (ca, cb), links)) == {110, 120}
    for checkpoints, altered_links in (((ca,), links), ((ca, ca), links),
                                       ((ca, cb), {101: {1}, 102: {2}})):
        with pytest.raises(CustodyRejected):
            require_complete_coverage((a, b), checkpoints, altered_links)


@pytest.mark.parametrize("change", [
    {"signed_by_principal_id": None}, {"signed_at": None}, {"context_digest": "stale"},
    {"vehicle_id": 20}, {"mode": "GENERIC_POSTED"}, {"context_manifest": {}},
])
def test_arbitrary_posted_unsigned_or_wrong_vehicle_is_not_financial_evidence(change):
    a, b = vehicles()
    ca, cb = receipt(a, 101), receipt(b, 102)
    ca.__dict__.update(change)
    with pytest.raises(CustodyRejected):
        require_complete_coverage((a, b), (ca, cb), {101: {1, 3}, 102: {2}})


def epoch(identifier=3, revision=3, **changes):
    return NS(**{
        "id": identifier, "context_revision": revision, "vehicle_location_id": 110,
        "started_at": NOW + timedelta(hours=3), "ended_at": NOW + timedelta(hours=5),
        "state": "ACCEPTED", "accepted_by_principal_id": 391,
        "request_id": "signed-stable-request", "payload_hash": "a" * 64, **changes,
    })


def test_same_custody_requires_exact_movement_watermark_even_if_balance_returns_to_same():
    a = vehicles()[0]
    checkpoint = receipt(a, 101)
    assert require_unchanged_or_signed_successor(
        vehicle=a, checkpoint=checkpoint, epochs=[epoch()], current_watermark=812) is None
    with pytest.raises(CustodyRejected, match="INVENTORY_STALE"):
        require_unchanged_or_signed_successor(
            vehicle=a, checkpoint=checkpoint, epochs=[epoch()], current_watermark=814)


def test_legitimate_signed_later_takeover_does_not_charge_later_stock_to_old_session():
    a = vehicles()[0]
    checkpoint = receipt(a, 101)
    first = epoch()
    second = epoch(4, 4, started_at=first.ended_at, ended_at=None)
    assert require_unchanged_or_signed_successor(
        vehicle=a, checkpoint=checkpoint, epochs=[first, second],
        current_watermark=900) == second.started_at


@pytest.mark.parametrize("change", [
    {"state": "NEEDS_REVIEW"}, {"accepted_by_principal_id": None},
    {"vehicle_location_id": 120}, {"request_id": None}, {"payload_hash": None},
    {"context_revision": 5}, {"started_at": NOW + timedelta(hours=6)},
])
def test_successor_cannot_erase_old_custody_without_contiguous_signed_acceptance(change):
    a = vehicles()[0]
    checkpoint = receipt(a, 101)
    first = epoch()
    successor = epoch(4, 4, started_at=first.ended_at, ended_at=None)
    successor.__dict__.update(change)
    with pytest.raises(CustodyRejected):
        require_unchanged_or_signed_successor(
            vehicle=a, checkpoint=checkpoint, epochs=[first, successor], current_watermark=900)


def test_closing_an_epoch_does_not_rewrite_signed_immutable_context():
    from domains.representative_settlement_multi_vehicle.policy import resolve_responsibilities
    from tests.test_dispatch_m04_domain import scenario
    periods, epochs = scenario()
    opened = (*epochs[:2], replace(epochs[2], ended_at=None))
    args = dict(company_id=1, session_id=71, driver_id=103, periods=periods)
    assert resolve_responsibilities(**args, epochs=opened) == resolve_responsibilities(**args, epochs=epochs)
