"""M02 orchestration guard tests with fake store ONLY.

These do not claim any PG16/HTTP evidence; M01 persistence and partial-index
migration are required to test actual lifecycle writes under restricted RLS.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

from domains.dispatch.route_execution.lifecycle import RouteLifecycleIntent
from domains.dispatch.route_execution.lifecycle.policy import (
    LifecycleConflict, RouteLifecycleState,
)
from domains.dispatch.route_execution.lifecycle import usecase


@dataclass
class Db:
    flushes: int = 0
    commits: int = 0
    rollbacks: int = 0

    async def flush(self):
        self.flushes += 1

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class Store:
    def __init__(self, state):
        self.state = state
        self.locked = 0
        self.guarded = 0
        self.applied = 0

    async def lock_authorized_state(self, db, *, company_id, route_id, intent):
        self.locked += 1
        assert company_id == self.state.company_id and route_id == self.state.route_id
        return self.state

    async def assert_live_resource_guards(self, db, *, state, decision):
        self.guarded += 1
        assert decision.inventory_movements == ()

    async def persist_transition(self, db, *, state, decision, intent, actor_id):
        self.applied += 1
        assert actor_id == 51 and decision.status == "postponed"
        assert decision.end_period_id == 33


def state(revision=12):
    return RouteLifecycleState(
        company_id=9, route_id=55, zone_id=8, status="active",
        context_revision=revision, open_period_id=33,
        active_driver_id=101, active_vehicle_id=201,
        work_session_id=71, work_session_settled=False,
        target_vehicle_custody_revision=None,
        target_vehicle_custody_accepted=False,
    )


def command(revision=12):
    return RouteLifecycleIntent.model_validate({
        "action": "POSTPONE", "request_id": str(uuid4()),
        "expected_context_revision": revision, "expected_period_id": 33,
    })


@pytest.mark.asyncio
async def test_receipt_and_transition_commit_in_one_transaction(monkeypatch):
    db=Db()
    store=Store(state())
    called=[]
    record=object()
    async def begin(db, **kwargs):
        assert kwargs["company_id"]==9 and kwargs["actor_id"]==51
        assert kwargs["operation"]==usecase.OPERATION
        assert len(kwargs["request_hash"])==64
        return record,None
    def complete(r,response):
        assert r is record
        called.append(("completed",response.copy()))
    async def authorized_route(route_id):
        called.append(("route",route_id))
    async def authorized_vehicle(vehicle_id):
        called.append(("vehicle",vehicle_id))
    monkeypatch.setattr(usecase,"begin_idempotent_operation",begin)
    monkeypatch.setattr(usecase,"complete_idempotent_operation",complete)
    cmd=command()
    response=await usecase.execute_route_lifecycle(
        db,company_id=9,route_id=55,actor_id=51,intent=cmd,store=store,
        authorize_route=authorized_route,authorize_vehicle=authorized_vehicle,
    )
    assert response["state"]=="COMMITTED"
    assert response["status"]=="postponed"
    assert response["context_revision"]==13
    assert response["live_assets_reserved"] is False
    assert response["zone_reserved"] is True
    assert called==[("route",55),("completed",response)]
    assert (store.locked,store.guarded,store.applied)==(1,1,1)
    assert (db.flushes,db.commits,db.rollbacks)==(1,1,0)


@pytest.mark.asyncio
async def test_replay_does_not_reenter_state_mutation_and_rechecks_authority(monkeypatch):
    db=Db()
    store=Store(state())
    cmd=command()
    orig={"request_id":str(cmd.request_id),"route_id":55,"state":"COMMITTED",
          "action":"POSTPONE","status":"postponed","context_revision":13}
    async def begin(*args,**kwargs):return object(),orig
    async def authorize_route(route_id):assert route_id==55
    async def authorize_vehicle(vehicle_id):raise AssertionError("not a RESUME")
    monkeypatch.setattr(usecase,"begin_idempotent_operation",begin)
    result=await usecase.execute_route_lifecycle(
        db,company_id=9,route_id=55,actor_id=51,intent=cmd,store=store,
        authorize_route=authorize_route,authorize_vehicle=authorize_vehicle,
    )
    assert result is orig
    assert db.rollbacks==1 and db.commits==0
    assert store.applied==0 and store.locked==0
    async def denied_route(route_id):raise PermissionError("revoked")
    with pytest.raises(PermissionError):
        await usecase.execute_route_lifecycle(
            db,company_id=9,route_id=55,actor_id=51,intent=cmd,store=store,
            authorize_route=denied_route,authorize_vehicle=authorize_vehicle,
        )
    assert store.applied==0 and db.commits==0


@pytest.mark.asyncio
async def test_stale_epoch_rolls_back_receipt_and_never_persists(monkeypatch):
    db=Db()
    store=Store(state(revision=14))
    async def begin(*args,**kwargs):return object(),None
    async def okay(_):return None
    monkeypatch.setattr(usecase,"begin_idempotent_operation",begin)
    with pytest.raises(LifecycleConflict, match="ROUTE_CONTEXT_REVISION_STALE"):
        await usecase.execute_route_lifecycle(
            db,company_id=9,route_id=55,actor_id=51,
            intent=command(revision=12),store=store,
            authorize_route=okay,authorize_vehicle=okay,
        )
    assert store.locked==1 and store.guarded==0 and store.applied==0
    assert (db.flushes,db.commits,db.rollbacks)==(0,0,1)


@pytest.mark.asyncio
async def test_authority_denial_precedes_even_idempotency_lookup(monkeypatch):
    async def begin(*args,**kwargs):raise AssertionError("denied request reached DB")
    async def deny(_):raise PermissionError("route scope revoked")
    monkeypatch.setattr(usecase,"begin_idempotent_operation",begin)
    with pytest.raises(PermissionError):
        await usecase.execute_route_lifecycle(
            Db(),company_id=9,route_id=55,actor_id=51,
            intent=command(),store=Store(state()),
            authorize_route=deny,authorize_vehicle=deny,
        )

def test_lock_snapshot_fences_assignment_revision_not_inventory_adjustment_revision():
    from types import SimpleNamespace
    from domains.dispatch.route_execution.lifecycle.resource_locks import _snapshot_identity

    def route(*, assignment_revision, adjustment_revision):
        return SimpleNamespace(
            driver_id=21, vehicle_id=42, zone_id=7, work_session_id=9,
            status="postponed",
            assignment_context_revision=assignment_revision,
            adjustment_context_revision=adjustment_revision,
        )

    first = _snapshot_identity(route(assignment_revision=3, adjustment_revision=200))
    assert first == _snapshot_identity(route(assignment_revision=3, adjustment_revision=201))
    assert first != _snapshot_identity(route(assignment_revision=4, adjustment_revision=200))
