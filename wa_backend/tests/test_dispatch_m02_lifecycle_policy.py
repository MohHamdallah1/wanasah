"""M02 narrow policy/command tests. PG16/HTTP integration is gated on merged M01.

These tests verify executable route lifecycle decision logic, not a fake DB
substitute; only M01 schema integration can prove live resource release.
"""
from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from domains.dispatch.route_execution.lifecycle import (
    RouteLifecycleIntent,
    RouteLifecycleState,
    LifecycleConflict,
    decide_lifecycle,
    lifecycle_request_hash,
)


def intent(action="POSTPONE", **changes):
    base = {
        "action": action,
        "request_id": str(uuid4()),
        "expected_context_revision": 12,
        "expected_period_id": 33 if action != "RESUME" else None,
    }
    if action == "RESUME":
        base.update({
            "target_driver_id": 101,
            "target_vehicle_id": 201,
            "expected_vehicle_custody_revision": 7,
        })
    base.update(changes)
    return RouteLifecycleIntent.model_validate(base)


def state(status="active", **changes):
    base = dict(
        route_id=55, company_id=9, zone_id=8,
        status=status, context_revision=12,
        open_period_id=33 if status in {"active", "waiting"} else None,
        active_driver_id=100 if status in {"active", "waiting"} else None,
        active_vehicle_id=200 if status in {"active", "waiting"} else None,
        work_session_id=71,
        work_session_settled=False,
        target_vehicle_custody_revision=7,
        target_vehicle_custody_accepted=True,
        target_vehicle_custody_matches_target=True,
    )
    base.update(changes)
    return RouteLifecycleState(**base)


@pytest.mark.parametrize("status", ["active", "waiting"])
def test_postpone_keeps_route_and_zone_releases_live_assignment(status):
    result = decide_lifecycle(state(status), intent("POSTPONE"))
    assert result.status == "postponed"
    assert result.zone_reserved is True
    assert result.live_assets_reserved is False
    assert result.end_period_id == 33
    assert result.open_period_driver_id is None
    assert result.open_period_vehicle_id is None
    assert result.next_context_revision == 13
    assert result.inventory_movements == ()


@pytest.mark.parametrize("driver,vehicle", [(100, 200), (101, 201), (100, 201), (101, 200)])
def test_resume_same_or_different_driver_and_vehicle_never_migrates_stock(driver, vehicle):
    result = decide_lifecycle(
        state("postponed"),
        intent("RESUME", target_driver_id=driver, target_vehicle_id=vehicle),
    )
    assert result.status == "active"
    assert result.zone_reserved is True
    assert result.live_assets_reserved is True
    assert result.end_period_id is None
    assert (result.open_period_driver_id, result.open_period_vehicle_id) == (driver, vehicle)
    assert result.inventory_movements == ()


def test_yesterday_postponed_route_can_resume_after_historic_session_settled():
    old_day = state("postponed", work_session_id=71, work_session_settled=True)
    result = decide_lifecycle(old_day, intent("RESUME"))
    assert result.next_context_revision == 13
    assert result.open_period_driver_id == 101


def test_closing_postponed_releases_zone_for_new_route_identity():
    result = decide_lifecycle(state("postponed"), intent("CLOSE", expected_period_id=None))
    assert result.status == "closed"
    assert result.zone_reserved is False
    assert result.live_assets_reserved is False
    assert result.inventory_movements == ()
    assert result.schedule_zone_next is True
    assert result.route_id == 55  # Next schedule creates a DIFFERENT route ID.


@pytest.mark.parametrize("status", ["active", "waiting"])
def test_close_live_route_ends_period_not_vehicle_custody(status):
    result = decide_lifecycle(state(status), intent("CLOSE"))
    assert result.status == "closed"
    assert result.end_period_id == 33
    assert result.inventory_movements == ()


def test_aba_a_to_b_to_a_rejects_stale_period_and_revision_even_same_car():
    initial = state("active", context_revision=12, open_period_id=33)
    pause = decide_lifecycle(initial, intent("POSTPONE"))
    assert pause.next_context_revision == 13
    resumed = decide_lifecycle(
        state("postponed", context_revision=13),
        intent("RESUME", expected_context_revision=13, target_driver_id=101, target_vehicle_id=201),
    )
    assert resumed.next_context_revision == 14
    second_pause = decide_lifecycle(
        state("active", context_revision=14, open_period_id=34,
              active_driver_id=101, active_vehicle_id=201),
        intent("POSTPONE", expected_context_revision=14, expected_period_id=34),
    )
    assert second_pause.next_context_revision == 15
    returned = decide_lifecycle(
        state("postponed", context_revision=15),
        intent("RESUME", expected_context_revision=15, target_driver_id=100, target_vehicle_id=200),
    )
    assert returned.next_context_revision == 16
    with pytest.raises(LifecycleConflict, match="ROUTE_CONTEXT_REVISION_STALE"):
        decide_lifecycle(state("active", context_revision=16, open_period_id=35),
                         intent("POSTPONE", expected_period_id=33))


@pytest.mark.parametrize("field,change,code", [
    ("expected_context_revision", 11, "ROUTE_CONTEXT_REVISION_STALE"),
    ("expected_period_id", 34, "ROUTE_PERIOD_STALE"),
])
def test_postpone_cannot_consume_stale_context_or_period(field, change, code):
    with pytest.raises(LifecycleConflict) as caught:
        decide_lifecycle(state(), intent("POSTPONE", **{field: change}))
    assert caught.value.code == code


@pytest.mark.parametrize("changes,code", [
    ({"target_vehicle_custody_revision": None}, "VEHICLE_CUSTODY_UNVERIFIED"),
    ({"target_vehicle_custody_revision": 9}, "VEHICLE_CUSTODY_REVISION_STALE"),
    ({"target_vehicle_custody_accepted": False}, "VEHICLE_CUSTODY_ACCEPTANCE_REQUIRED"),
    ({"target_vehicle_custody_matches_target": False}, "VEHICLE_CUSTODIAN_MISMATCH"),
    ({"zone_active": False}, "ZONE_ARCHIVED"),
    ({"open_period_id": 33}, "ROUTE_ALREADY_HAS_LIVE_PERIOD"),
])
def test_resume_requires_current_epoch_acceptance_and_unreserved_active_zone(changes, code):
    with pytest.raises(LifecycleConflict) as caught:
        decide_lifecycle(state("postponed", **changes), intent("RESUME"))
    assert caught.value.code == code


def test_same_uuid_exact_payload_deterministic_hash_and_changed_body_rejected():
    request_id = str(uuid4())
    first = intent("RESUME", request_id=request_id)
    duplicate = intent("RESUME", request_id=request_id)
    assert lifecycle_request_hash(55, first) == lifecycle_request_hash(55, duplicate)
    assert lifecycle_request_hash(56, first) != lifecycle_request_hash(55, duplicate)
    changed = intent("RESUME", request_id=request_id, target_vehicle_id=203)
    assert lifecycle_request_hash(55, changed) != lifecycle_request_hash(55, first)
    # The UUID is a retry identity, NOT a component of the request fingerprint.
    assert lifecycle_request_hash(55, first) == lifecycle_request_hash(
        55, intent("RESUME", request_id=str(uuid4())),
    )


@pytest.mark.parametrize("payload", [
    {"action": "RESUME", "expected_context_revision": 4, "target_driver_id": 7,
     "target_vehicle_id": 8},  # missing stable UUID AND accepted custody revision
    {"action": "RESUME", "request_id": str(uuid4()), "expected_context_revision": 4,
     "target_driver_id": 7, "expected_vehicle_custody_revision": 1},
    {"action": "POSTPONE", "request_id": str(uuid4()), "expected_context_revision": 4,
     "expected_period_id": 7, "inventory": {}},
    {"action": "CLOSE", "request_id": str(uuid4()), "expected_context_revision": 4,
     "target_vehicle_id": 9},
    {"action": "CLOSE", "request_id": str(uuid4()), "expected_context_revision": 4,
     "expected_vehicle_custody_revision": 3},
    {"action": "POSTPONE", "request_id": str(uuid4()), "expected_context_revision": 4},
])
def test_legacy_or_implicit_inventory_commands_fail_closed(payload):
    with pytest.raises(ValidationError):
        RouteLifecycleIntent.model_validate(payload)


@pytest.mark.parametrize("action,status,code", [
    ("POSTPONE", "postponed", "ROUTE_NOT_LIVE"),
    ("RESUME", "active", "ROUTE_NOT_POSTPONED"),
    ("CLOSE", "closed", "ROUTE_ALREADY_CLOSED"),
])
def test_invalid_status_transitions_fail_closed(action,status,code):
    command=intent(action, expected_period_id=None if action!="POSTPONE" else 33)
    with pytest.raises(LifecycleConflict) as caught:
        decide_lifecycle(state(status), command)
    assert caught.value.code == code


def test_finished_session_rejects_stale_live_mutation_but_allows_reopen_yesterday():
    with pytest.raises(LifecycleConflict, match="SESSION_ALREADY_SETTLED"):
        decide_lifecycle(state(work_session_settled=True), intent("POSTPONE"))
    assert decide_lifecycle(state("postponed", work_session_settled=True),
                            intent("RESUME")).status == "active"
