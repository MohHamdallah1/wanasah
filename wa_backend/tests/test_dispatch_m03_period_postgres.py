"""M03 real FIELD Bearer + isolated PostgreSQL 16/tenant/custody/context gate.

Requires a disposable unique "m03_941_*" migrated DB, distinct restricted
runtime vs privileged migration roles. No production/shared DB operations.
M02's operational POSTPONE/RESUME is separately gated after its merge.
"""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from context import tenant_context
from main import app
from models import (
    DispatchRoute, InventoryBalance, InventoryMovement, RouteCommercialContext,
    Visit, WorkSession, Vehicle, InventoryLocation, Zone, utc_now,
)
from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from tests.field_authorization_phase3_fixture import (
    PASSWORD, seed_business, new_transfers,
)

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_DISPATCH_M03_PG_GATE") != "1",
        reason="Explicit disposable M03 PG16 genuine Bearer gate only",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]


def _check_url(value):
    url = make_url(value)
    assert url.database.startswith("m03_941_")
    assert url.host in ("127.0.0.1", "localhost")
    assert url.drivername == "postgresql+asyncpg"
    return url


@pytest_asyncio.fixture(loop_scope="module")
async def gate():
    runtime = _check_url(os.environ["DATABASE_URL"])
    admin_url = _check_url(os.environ["DATABASE_URL_MIGRATION"])
    assert runtime.database == admin_url.database
    assert runtime.port == admin_url.port and runtime.username != admin_url.username
    admin = create_async_engine(
        os.environ["DATABASE_URL_MIGRATION"], poolclass=NullPool,
    )
    @event.listens_for(admin.sync_engine, "begin")
    def _admin_tenant(connection):
        connection.execute(
            text("SELECT set_config('app.current_tenant', :id, true)"),
            {"id": str(tenant_context.get() or "")},
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://m03-real-verify",
    ) as client:
        g = await seed_business(admin)
        foreign = await seed_business(admin)
        g.client = client
        async def login(company, username):
            r = await client.post("/driver/login", json={
                "company_code": company, "username": username,
                "password": PASSWORD,
            })
            assert r.status_code == 200, r.text
            return r.json()["token"]
        g.token = await login(g.company_code, g.field_name)
        g.other_token = await login(g.company_code, g.other_name)
        g.foreign_token = await login(foreign.company_code, foreign.field_name)
        g.foreign = foreign
        g.transfers = await new_transfers(g)
        from database import engine as runtime_engine
        async with runtime_engine.connect() as conn:
            flags = (
                await conn.execute(text(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname=current_user"
                ))
            ).one()
            assert tuple(flags) == (False, False)
            for table in ("dispatch_route_execution_periods", "vehicle_custody_epochs", "visits"):
                rls = (await conn.execute(text(
                    "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                    "WHERE oid=to_regclass(:name)"
                ), {"name": table})).one()
                assert tuple(rls) == (True, True)
        yield g
    await admin.dispose()


async def _set_period(g):
    """Seed M02's documented ACTIVE period shape, not a fake HTTP transition."""
    token = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin, expire_on_commit=False) as db:
            route = await db.scalar(
                select(DispatchRoute).where(
                    DispatchRoute.company_id == g.tenant,
                    DispatchRoute.id == g.route,
                ).with_for_update()
            )
            context_id = await db.scalar(
                select(RouteCommercialContext.id).where(
                    RouteCommercialContext.company_id == g.tenant,
                    RouteCommercialContext.dispatch_route_id == g.route,
                )
            )
            assert context_id is not None
            route.assignment_context_revision = 2
            ep = VehicleCustodyEpoch(
                company_id=g.tenant,
                vehicle_id=g.vehicle,
                vehicle_location_id=g.location,
                custodian_kind="FIELD_REPRESENTATIVE",
                custodian_principal_id=g.field.context.principal_id,
                field_representative_id=g.field.context.representative_id,
                related_session_id=g.session,
                accepted_by_principal_id=g.owner.context.principal_id,
                state="ACCEPTED",
                context_revision=1,
                started_at=utc_now(),
                request_id=str(uuid4()),
                payload_hash="a"*64,
            )
            db.add(ep)
            await db.flush()
            p = DispatchRouteExecutionPeriod(
                company_id=g.tenant,
                route_id=g.route,
                driver_id=g.field.driver.id,
                field_representative_id=g.field.context.representative_id,
                work_session_id=g.session,
                vehicle_id=g.vehicle,
                vehicle_location_id=g.location,
                commercial_context_id=context_id,
                state="ACTIVE",
                context_revision=2,
                started_at=utc_now(),
                started_by_principal_id=g.owner.context.principal_id,
                request_id=str(uuid4()),
                payload_hash="b"*64,
            )
            db.add(p)
            await db.flush()
            response = (p.id, ep.id, context_id)
            await db.commit()
            return response
    finally:
        tenant_context.reset(token)


def _headers(token, period=None, revision=2, epoch=None):
    result = {"Authorization": f"Bearer {token}"}
    if period is not None:
        result.update({
            "X-Execution-Period-ID": str(period),
            "X-Assignment-Context-Revision": str(revision),
            "X-Vehicle-Custody-Epoch-ID": str(epoch),
        })
    return result


async def _truth(g):
    token = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin) as db:
            visit = await db.scalar(
                select(Visit).where(
                    Visit.company_id == g.tenant,
                    Visit.id == g.visit,
                )
            )
            movements = await db.scalar(select(func.count()).select_from(
                InventoryMovement).where(
                    InventoryMovement.company_id == g.tenant,
                )
            )
            balances = (await db.execute(select(
                InventoryBalance.id, InventoryBalance.on_hand_quantity,
            ).where(
                InventoryBalance.company_id == g.tenant,
            ).order_by(InventoryBalance.id))).all()
            return (
                visit.status,
                visit.work_session_id,
                visit.execution_period_id,
                visit.execution_evidence_state,
                int(movements or 0),
                tuple((int(i), str(q)) for i, q in balances),
            )
    finally:
        tenant_context.reset(token)


async def test_m03_real_bearer_period_proof_stale_and_visit_no_duplication(gate):
    g = gate
    p, e, commercial = await _set_period(g)
    context = await g.client.get(
        "/driver/sessions/execution-context", headers=_headers(g.token),
    )
    assert context.status_code == 200, context.text
    actual = context.json()["execution_context"]
    assert actual["period_id"] == p and actual["custody_epoch_id"] == e
    assert actual["assignment_context_revision"] == 2
    assert actual["commercial_context_id"] == commercial
    assert actual["session_id"] == g.session

    # All FIELD read surfaces must resolve the same canonical execution,
    # not regress to the legacy route-session binding after a switch.
    for path in ("/driver/dashboard", "/product_variants", "/driver/visits"):
        surface = await g.client.get(path, headers=_headers(g.token))
        assert surface.status_code == 200, (path, surface.text)
        if path == "/driver/dashboard":
            assert surface.json()["execution_context"]["period_id"] == p

    foreign = await g.client.get(
        "/driver/sessions/execution-context", headers=_headers(g.foreign_token),
    )
    assert foreign.status_code == 200, foreign.text
    assert foreign.json()["session_id"] != g.session
    assert foreign.json()["execution_context"] is None

    body = {"request_id": str(uuid4()), "outcome": "NoSale", "notes": "M03 exact period"}
    before = await _truth(g)
    for headers in (
        _headers(g.token),
        _headers(g.token, p, 1, e),
        _headers(g.token, p, 2, e+99999),
    ):
        result = await g.client.put(f"/visits/{g.visit}", json=body, headers=headers)
        assert result.status_code == 409, result.text
        assert await _truth(g) == before

    # Real FIELD transfer-reject command releases the pending handshake before
    # the real Visit mutation; no testing-only patch to bypass business guards.
    rejection = await g.client.put(
        "/driver/transfers/batch_respond", json={"transfers": [
            {"transfer_id": t, "status": "rejected", "reason": "M03 acceptance"}
            for t in g.transfers
        ]}, headers=_headers(g.token),
    )
    assert rejection.status_code == 200, rejection.text
    before = await _truth(g)
    headers = _headers(g.token, p, 2, e)
    posted = await g.client.put(f"/visits/{g.visit}", json=body, headers=headers)
    assert posted.status_code == 200, posted.text
    after = await _truth(g)
    assert after[:4] == ("Completed", g.session, p, "VERIFIED")
    assert after[4:] == before[4:], "NoSale must not move stock"
    replay = await g.client.put(f"/visits/{g.visit}", json=body, headers=headers)
    assert replay.status_code == 200, replay.text
    assert replay.json() == posted.json()
    assert await _truth(g) == after
    changed_envelope = await g.client.put(
        f"/visits/{g.visit}", json=body,
        headers=_headers(g.token, p, 3, e),
    )
    assert changed_envelope.status_code in (409, 422), changed_envelope.text
    assert await _truth(g) == after


async def test_m03_context_reassignment_aba_fail_closed(gate):
    g=gate
    period, epoch, _ = await _set_period(g)
    proof=_headers(g.token,period,2,epoch)
    first=await g.client.get("/driver/sessions/execution-context",headers=proof)
    assert first.status_code==200,first.text
    token=tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin,expire_on_commit=False) as db:
            route=await db.scalar(select(DispatchRoute).where(
                DispatchRoute.company_id==g.tenant,DispatchRoute.id==g.route).with_for_update())
            old=await db.scalar(select(DispatchRouteExecutionPeriod).where(
                DispatchRouteExecutionPeriod.company_id==g.tenant,
                DispatchRouteExecutionPeriod.id==period).with_for_update())
            old.state="CLOSED"
            old.ended_at=utc_now()
            route.assignment_context_revision=3
            await db.commit()
        no_active=await g.client.get("/driver/sessions/execution-context",headers=_headers(g.token))
        assert no_active.status_code==200,no_active.text
        assert no_active.json()["execution_context"] is None
        body={"request_id":str(uuid4()),"outcome":"NoSale","notes":"stale A context"}
        before=await _truth(g)
        denied=await g.client.put(f"/visits/{g.visit}",json=body,headers=proof)
        assert denied.status_code==409,denied.text
        assert await _truth(g)==before
    finally:
        tenant_context.reset(token)


async def _seed_planned_route_for_other_field(g):
    """Genuine DB snapshot of M02 PLANNED assignment before any new session."""
    token=tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin,expire_on_commit=False) as db:
            zone=Zone(company_id=g.tenant,name="M03 pre-session "+uuid4().hex)
            vehicle=Vehicle(
                company_id=g.tenant,plate_number="M03"+uuid4().hex[:10],
                maintenance_status="Active",is_active=True,
            )
            db.add_all([zone,vehicle])
            await db.flush()
            loc=InventoryLocation(
                company_id=g.tenant,name="M03 planned vehicle",
                code="M03"+uuid4().hex[:11],location_type="VEHICLE",
                vehicle_id=vehicle.id,is_active=True,is_system_managed=False,
            )
            db.add(loc)
            await db.flush()
            route=DispatchRoute(
                company_id=g.tenant,zone_id=zone.id,vehicle_id=vehicle.id,
                driver_id=g.other.driver.id,source_location_id=g.warehouse_id,
                status="active",
            )
            db.add(route)
            await db.flush()
            source=await db.scalar(select(RouteCommercialContext).where(
                RouteCommercialContext.company_id==g.tenant,
                RouteCommercialContext.dispatch_route_id==g.route,
            ))
            assert source is not None
            cc=RouteCommercialContext(
                company_id=g.tenant,dispatch_route_id=route.id,
                pricing_locked_at=source.pricing_locked_at,
                price_publication_revision=source.price_publication_revision,
                assignment_revision=source.assignment_revision,
                offer_ruleset_version=source.offer_ruleset_version,
                tax_ruleset_version=source.tax_ruleset_version,
                transaction_currency_code=source.transaction_currency_code,
                functional_currency_code=source.functional_currency_code,
                rounding_policy_version=source.rounding_policy_version,
                tenant_policy_revision=source.tenant_policy_revision,
            )
            db.add(cc)
            await db.flush()
            epoch=VehicleCustodyEpoch(
                company_id=g.tenant,vehicle_id=vehicle.id,
                vehicle_location_id=loc.id,custodian_kind="FIELD_REPRESENTATIVE",
                custodian_principal_id=g.other.context.principal_id,
                field_representative_id=g.other.context.representative_id,
                accepted_by_principal_id=g.owner.context.principal_id,
                state="ACCEPTED",context_revision=1,
                started_at=utc_now(),request_id=str(uuid4()),payload_hash="c"*64,
            )
            db.add(epoch)
            await db.flush()
            planned=DispatchRouteExecutionPeriod(
                company_id=g.tenant,route_id=route.id,
                work_session_id=None,driver_id=g.other.driver.id,
                field_representative_id=g.other.context.representative_id,
                vehicle_id=vehicle.id,vehicle_location_id=loc.id,
                commercial_context_id=cc.id,state="PLANNED",
                context_revision=1,started_at=utc_now(),
                started_by_principal_id=g.owner.context.principal_id,
                request_id=str(uuid4()),payload_hash="d"*64,
            )
            db.add(planned)
            await db.flush()
            result=(planned.id,route.id,loc.id)
            await db.commit()
            return result
    finally:
        tenant_context.reset(token)


async def test_m03_planned_start_real_bearer_lost201_replay_no_second_session(gate):
    g=gate
    planned,route_id,loc_id=await _seed_planned_route_for_other_field(g)
    token=g.other_token
    path="/driver/sessions/start"
    # Missing durable id: fail closed, NOT a partial session or snapshot.
    miss=await g.client.post(path,json={},headers=_headers(token))
    assert miss.status_code==409,miss.text
    task_id=str(uuid4())
    headers={**_headers(token),"Idempotency-Key":task_id}
    started,same=await asyncio.gather(
        g.client.post(path,json={},headers=headers),
        g.client.post(path,json={},headers=headers),
    )
    assert started.status_code==201,started.text
    assert same.status_code==201,same.text
    body=started.json()
    assert body["execution_context"]["period_id"]==planned
    assert body["execution_context"]["vehicle_location_id"]==loc_id
    assert body["execution_context"]["assignment_context_revision"]==1
    assert same.json()==body

    # A third post after the simulated lost 201 is the exact replay.
    replay=await g.client.post(path,json={},headers=headers)
    assert replay.status_code==201,replay.text
    assert replay.json()==body

    token_context=tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin) as db:
            count=await db.scalar(select(func.count()).select_from(WorkSession).where(
                WorkSession.company_id==g.tenant,
                WorkSession.driver_id==g.other.driver.id))
            period=await db.scalar(select(DispatchRouteExecutionPeriod).where(
                DispatchRouteExecutionPeriod.company_id==g.tenant,
                DispatchRouteExecutionPeriod.id==planned))
            route=await db.scalar(select(DispatchRoute).where(
                DispatchRoute.company_id==g.tenant,DispatchRoute.id==route_id))
            assert count==1
            assert period.state=="ACTIVE" and period.work_session_id==body["session_id"]
            assert route.work_session_id is None
            assert period.vehicle_location_id==loc_id
            assert await db.scalar(select(func.count()).select_from(InventoryMovement).where(
                InventoryMovement.company_id==g.tenant,
                InventoryMovement.work_session_id==body["session_id"],
            ))==0
    finally:
        tenant_context.reset(token_context)
