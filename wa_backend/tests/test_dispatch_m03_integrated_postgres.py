"""M03 final real M02-integrated FIELD acceptance (guarded until M02 merged).

Never run on shared databases. No mock router, fake inventory movements or
authorization overrides. M02 POSTPONE/RESUME via real Backoffice Bearer HTTP;
FIELD Visit sales via real Bearer HTTP; physical preload is explicit and
complete BEFORE the route switch window.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from context import tenant_context
from models import (
    DispatchRoute, InventoryBalance, InventoryLocation, InventoryMovement,
    ProductLocation, RouteCommercialContext, SessionInventorySnapshot,
    Shop, Vehicle, Visit, WorkSession, Zone, Company, utc_now,
)
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
from product_lifecycle import DEFAULT_PRODUCT_LOCATION_FLAGS
from domains.identity.models import FieldRepresentative
from domains.identity.migration.models import IdentityLegacyDriverMap
from services import apply_inventory_movements_batch
from tests.test_dispatch_m03_period_postgres import (
    gate, _headers, _set_period,
)
from tests.field_authorization_phase3_fixture import PASSWORD

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_DISPATCH_M03_INTEGRATED_GATE") != "1",
        reason="Requires real M02+M03 Alembic chain and disposable PG16",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]


def _intent(action, revision, *, period=None, driver=None, vehicle=None, custody=None):
    body = {
        "action": action,
        "request_id": str(uuid4()),
        "expected_context_revision": int(revision),
        "expected_period_id": period,
    }
    if action == "RESUME":
        body.update({
            "target_driver_id": driver, "target_vehicle_id": vehicle,
            "expected_vehicle_custody_revision": custody,
        })
    return body


async def _physical(g, location):
    async with AsyncSession(g.admin) as db:
        return int(await db.scalar(select(func.coalesce(func.sum(
            InventoryBalance.on_hand_quantity),0)).where(
            InventoryBalance.company_id==g.tenant,
            InventoryBalance.location_id==location,
            InventoryBalance.product_variant_id==g.variant["id"],
            InventoryBalance.stock_status=="AVAILABLE",
        )) or 0)


async def _move_count(g):
    async with AsyncSession(g.admin) as db:
        return int(await db.scalar(select(func.count()).select_from(InventoryMovement).where(
            InventoryMovement.company_id==g.tenant,
        )) or 0)


async def _prepare_real_b(g):
    """True physical 150 A -> 100 A + 60 B via pre-test logged movements."""
    token=tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin, expire_on_commit=False) as db:
            existing=await db.scalar(select(Visit).where(
                Visit.company_id==g.tenant,Visit.id==g.visit))
            shop_a=await db.scalar(select(Shop).where(
                Shop.company_id==g.tenant,Shop.id==existing.shop_id))
            shop_a.max_debt_limit=Decimal("500000.000")
            representative=await db.scalar(select(FieldRepresentative).where(
                FieldRepresentative.company_id==g.tenant,
                FieldRepresentative.id==g.field.context.representative_id))
            assert representative is not None
            representative.can_allow_debt=True
            representative.max_debt_limit=Decimal("500000.000")
            bridge=await db.get(IdentityLegacyDriverMap,(g.tenant,g.field.driver.id))
            assert bridge is not None and bridge.field_principal_id == g.field.context.principal_id
            # This accepted credit sale must be a FIELD_ONLY representative;
            # the generic fixture intentionally starts as DUAL_SPLIT to test
            # privilege separation in unrelated authorization cases.
            bridge.backoffice_principal_id=None
            bridge.backoffice_user_id=None
            bridge.classification="FIELD_ONLY"
            tag=uuid4().hex[:10]
            zone_b=Zone(company_id=g.tenant,name="M03-B-"+tag,is_active=True)
            car_b=Vehicle(company_id=g.tenant,plate_number="M03B"+tag,
                maintenance_status="Active",is_active=True)
            db.add_all([zone_b,car_b])
            await db.flush()
            loc_b=InventoryLocation(
                company_id=g.tenant,name="M03 real B "+tag,
                code="M03-B-"+tag,location_type="VEHICLE",
                vehicle_id=car_b.id,is_active=True,is_system_managed=False)
            shop_b=Shop(company_id=g.tenant,name="M03 Shop B "+tag,
                zone_id=zone_b.id,max_debt_limit=Decimal("500000.000"),
                tax_jurisdiction_id=shop_a.tax_jurisdiction_id,is_active=True)
            shop_a3=Shop(company_id=g.tenant,name="M03 Shop A3 "+tag,
                zone_id=g.zone,max_debt_limit=Decimal("500000.000"),
                tax_jurisdiction_id=shop_a.tax_jurisdiction_id,is_active=True)
            db.add_all([loc_b,shop_b,shop_a3])
            await db.flush()
            r2=DispatchRoute(
                company_id=g.tenant,zone_id=zone_b.id,
                driver_id=g.field.driver.id,vehicle_id=car_b.id,
                work_session_id=None,
                source_location_id=g.warehouse_id,
                status="postponed",dispatch_date=date.today())
            v2=Visit(
                id=1_815_000_000+int(tag[:5],16),
                company_id=g.tenant,shop_id=shop_b.id,
                driver_id=g.field.driver.id,
                operational_date=date.today(),status="Pending",
                outcome="Pending",sequence=1)
            v3=Visit(
                id=1_817_000_000+int(tag[:5],16),
                company_id=g.tenant,shop_id=shop_a3.id,
                driver_id=g.field.driver.id,
                operational_date=date.today(),status="Pending",
                outcome="Pending",sequence=2)
            flag=ProductLocation(
                company_id=g.tenant,product_variant_id=g.variant["id"],
                location_id=loc_b.id,
                operational_flags=dict(DEFAULT_PRODUCT_LOCATION_FLAGS),
                created_by=g.actor.id)
            db.add_all([r2,v2,v3,flag])
            await db.flush()
            commercial=await db.scalar(select(RouteCommercialContext).where(
                RouteCommercialContext.company_id==g.tenant,
                RouteCommercialContext.dispatch_route_id==g.route))
            assert commercial is not None
            cc=RouteCommercialContext(
                company_id=g.tenant,dispatch_route_id=r2.id,
                pricing_locked_at=commercial.pricing_locked_at,
                price_publication_revision=commercial.price_publication_revision,
                assignment_revision=commercial.assignment_revision,
                offer_ruleset_version=commercial.offer_ruleset_version,
                tax_ruleset_version=commercial.tax_ruleset_version,
                transaction_currency_code=commercial.transaction_currency_code,
                functional_currency_code=commercial.functional_currency_code,
                rounding_policy_version=commercial.rounding_policy_version,
                tenant_policy_revision=commercial.tenant_policy_revision)
            epoch=VehicleCustodyEpoch(
                company_id=g.tenant,
                vehicle_id=car_b.id,vehicle_location_id=loc_b.id,
                custodian_kind="FIELD_REPRESENTATIVE",
                custodian_principal_id=g.field.context.principal_id,
                field_representative_id=g.field.context.representative_id,
                accepted_by_principal_id=g.owner.context.principal_id,
                state="ACCEPTED",context_revision=1,
                started_at=utc_now(),request_id=str(uuid4()),
                payload_hash="e"*64)
            db.add_all([cc,epoch])
            await db.flush()
            b_ids=(r2.id,car_b.id,loc_b.id,v2.id,v3.id,epoch.id)
            await db.commit()

        # A genuinely received 200 units at warehouse, then 150 to A in the
        # existing accepted fixture. Explicit setup movements now make A=100
        # and B=60 BEFORE P1/P2/P3: no stock changes on any M02 transition.
        async with AsyncSession(g.admin,expire_on_commit=False) as db:
            moves=(
                {
                    "product_variant_id":g.variant["id"],"batch_id":g.batch,
                    "quantity":Decimal("50"),"movement_kind":"PHYSICAL",
                    "reference_type":"C2_TEST_VEHICLE_LOAD",
                    "reference_id":"M03-PRE-A-"+uuid4().hex[:10],
                    "idempotency_key":"M03-SETUP-A-"+uuid4().hex[:10],
                    "source_location_id":g.location,
                    "destination_location_id":g.warehouse_id,
                    "source_stock_status":"AVAILABLE",
                    "destination_stock_status":"AVAILABLE",
                    "work_session_id":None,
                },
                {
                    "product_variant_id":g.variant["id"],"batch_id":g.batch,
                    "quantity":Decimal("60"),"movement_kind":"PHYSICAL",
                    "reference_type":"C2_TEST_VEHICLE_LOAD",
                    "reference_id":"M03-PRE-B-"+uuid4().hex[:10],
                    "idempotency_key":"M03-SETUP-B-"+uuid4().hex[:10],
                    "source_location_id":g.warehouse_id,
                    "destination_location_id":b_ids[2],
                    "source_stock_status":"AVAILABLE",
                    "destination_stock_status":"AVAILABLE",
                    "work_session_id":None,
                },
            )
            # Apply serially: the second movement consumes 10 of the physical
            # warehouse stock recovered from A by the first.
            for move in moves:
                await apply_inventory_movements_batch(
                    db,company_id=g.tenant,performed_by=g.actor.id,
                    movements=[move])
            await db.commit()
        return b_ids
    finally:
        tenant_context.reset(token)


async def _current(g):
    r=await g.client.get("/driver/sessions/execution-context",
                         headers=_headers(g.token))
    assert r.status_code==200,r.text
    return r.json()["execution_context"]


async def _sale(g,visit_id,units,proof):
    body={
        "request_id":str(uuid4()),"outcome":"Sale",
        "cash_collected":"1.000","debt_paid":"0",
        "cart_items":[{
            "product_variant_id":g.variant["id"],"packs_quantity":int(units)
        }],
    }
    h=_headers(g.token,proof["period_id"],
        proof["assignment_context_revision"],proof["custody_epoch_id"])
    response=await g.client.put(f"/visits/{visit_id}",json=body,headers=h)
    assert response.status_code==200,response.text
    replay=await g.client.put(f"/visits/{visit_id}",json=body,headers=h)
    assert replay.status_code==200 and replay.json()==response.json()
    return body


async def test_m03_real_s1_r1_a_r2_b_r1_a_signed_sale_and_physical_truth(gate):
    g=gate
    p1,e1,_=await _set_period(g)
    r2,vehicle_b,location_b,v2,v3,e_b=await _prepare_real_b(g)
    assert (await _physical(g,g.location),await _physical(g,location_b))==(100,60)
    admin_login=await g.client.post("/login",json={
        "company_code":g.company_code,"username":g.owner_name,
        "password":PASSWORD,
    })
    assert admin_login.status_code==200,admin_login.text
    owner={"Authorization":"Bearer "+admin_login.json()["token"]}
    reject=await g.client.put("/driver/transfers/batch_respond",json={
        "transfers":[{"transfer_id":t,"status":"rejected",
                      "reason":"M03 integration"} for t in g.transfers]
    },headers=_headers(g.token))
    assert reject.status_code==200,reject.text

    p=await _current(g)
    assert p["period_id"]==p1 and p["route_id"]==g.route and p["session_id"]==g.session
    await _sale(g,g.visit,12,p)
    assert await _physical(g,g.location)==88
    mv=await _move_count(g)

    r1_url=f"/dispatch/route/{g.route}/lifecycle"
    r2_url=f"/dispatch/route/{r2}/lifecycle"
    postponed=await g.client.put(r1_url,json=_intent("POSTPONE",2,period=p1),headers=owner)
    assert postponed.status_code==200,postponed.text
    assert await _move_count(g)==mv
    resumed=await g.client.put(r2_url,json=_intent("RESUME",1,
        driver=g.field.driver.id,vehicle=vehicle_b,custody=1),headers=owner)
    assert resumed.status_code==200,resumed.text
    assert await _move_count(g)==mv
    b=await _current(g)
    assert b["route_id"]==r2 and b["session_id"]==g.session
    assert b["period_id"]!=p1 and b["vehicle_location_id"]==location_b
    assert b["custody_epoch_id"]==e_b
    await _sale(g,v2,7,b)
    assert await _physical(g,location_b)==53
    mv=await _move_count(g)

    postponed_b=await g.client.put(r2_url,json=_intent("POSTPONE",2,
        period=b["period_id"]),headers=owner)
    assert postponed_b.status_code==200,postponed_b.text
    assert await _move_count(g)==mv
    resumed_a=await g.client.put(r1_url,json=_intent("RESUME",3,
        driver=g.field.driver.id,vehicle=g.vehicle,custody=1),headers=owner)
    assert resumed_a.status_code==200,resumed_a.text
    assert await _move_count(g)==mv
    a3=await _current(g)
    assert a3["route_id"]==g.route and a3["session_id"]==g.session
    assert a3["period_id"] not in {p1,b["period_id"]}
    assert a3["assignment_context_revision"]==4

    before=await _move_count(g)
    old=await g.client.put(f"/visits/{v3}",json={
        "request_id":str(uuid4()),"outcome":"Sale",
        "cash_collected":"1","cart_items":[{
            "product_variant_id":g.variant["id"],"packs_quantity":5}],
    },headers=_headers(g.token,p1,2,e1))
    assert old.status_code==409,old.text
    assert await _move_count(g)==before
    await _sale(g,v3,5,a3)
    assert (await _physical(g,g.location),await _physical(g,location_b))==(83,53)

    token=tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin) as db:
            completed=(await db.scalars(select(Visit).where(
                Visit.company_id==g.tenant,
                Visit.id.in_([g.visit,v2,v3]),
            ))).all()
            assert len(completed)==3
            assert {v.status for v in completed}=={"Completed"}
            assert {v.work_session_id for v in completed}=={g.session}
            assert {v.execution_period_id for v in completed}=={
                p1,b["period_id"],a3["period_id"]}
            assert sum(Decimal(v.cash_collected) for v in completed)==Decimal("3.000")
            assert all(v.commercial_context_id is not None for v in completed)
            snapshots=(await db.scalars(select(SessionInventorySnapshot).where(
                SessionInventorySnapshot.company_id==g.tenant,
                SessionInventorySnapshot.work_session_id==g.session,
                SessionInventorySnapshot.product_variant_id==g.variant["id"],
                SessionInventorySnapshot.stock_status=="AVAILABLE",
            ))).all()
            assert len(snapshots)==2
            assert {
                (int(x.location_id),int(x.starting_quantity)) for x in snapshots
            }=={(g.location,100),(location_b,60)}
    finally:
        tenant_context.reset(token)


    # S1 must close its operational route before the financial settlement.
    pause_r1=await g.client.put(r1_url,json=_intent(
        "POSTPONE",4,period=a3["period_id"]),headers=owner)
    assert pause_r1.status_code==200,pause_r1.text
    ending=await g.client.put("/driver/sessions/end",headers=_headers(g.token))
    assert ending.status_code==200,ending.text

    # The M04 financial settlement action is owned by Worker3. This isolated
    # M03 test seeds the exact required *already financially settled* S1 DB
    # precondition, including vehicle-specific sealed snapshots, and verifies
    # the REAL M02 RESUME + M03 FIELD S2 start path, not M04 settlement.
    tenant_token=tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin,expire_on_commit=False) as db:
            s1=await db.scalar(select(WorkSession).where(
                WorkSession.company_id==g.tenant,
                WorkSession.id==g.session).with_for_update())
            assert s1.end_time is not None and s1.is_settled is False
            original_commercial=int(s1.commercial_context_id)
            sealed_at=utc_now()
            for snap in (await db.scalars(select(SessionInventorySnapshot).where(
                SessionInventorySnapshot.company_id==g.tenant,
                SessionInventorySnapshot.work_session_id==g.session,
            ).with_for_update())).all():
                assert int(snap.location_id) in (int(g.location),int(location_b))
                snap.ending_quantity=(
                    Decimal("83") if snap.location_id==g.location else Decimal("53")
                )
                snap.settled_by=g.field.driver.id
                snap.settled_at=sealed_at
            s1.inventory_reconciled_at=sealed_at
            s1.inventory_reconciled_by=g.field.driver.id
            s1.is_settled=True

            # Simulate the next business date with the tenant timezone, not a
            # monkeypatch of auth, DB time, price or lifecycle services. The
            # original S1 identity, posted Visits and commercial ref stay put.
            next_local=datetime.now(timezone.utc).astimezone(
                ZoneInfo("Pacific/Kiritimati")).date()
            assert next_local > s1.session_date, (
                "Day-two PG16 fixture must run when +14 company time is tomorrow"
            )
            tenant_company=await db.scalar(select(Company).where(
                Company.id==g.tenant).with_for_update())
            tenant_company.timezone="Pacific/Kiritimati"
            old_local_date=s1.session_date
            await db.commit()
    finally:
        tenant_context.reset(tenant_token)

    # Already-settled yesterday's historic WorkSession must not fence RESUME.
    resumed_s2=await g.client.put(r1_url,json=_intent(
        "RESUME",5,driver=g.field.driver.id,
        vehicle=g.vehicle,custody=1),headers=owner)
    assert resumed_s2.status_code==200,resumed_s2.text
    planned=await _current(g)
    assert planned is not None
    assert planned["session_id"] is None
    assert planned["route_id"]==g.route
    s2_request=str(uuid4())
    start_headers={**_headers(g.token),"Idempotency-Key":s2_request}
    started=await g.client.post("/driver/sessions/start",headers=start_headers,json={})
    assert started.status_code==201,started.text
    s2_id=started.json()["session_id"]
    assert s2_id!=g.session
    assert started.json()["execution_context"]["period_id"]==planned["period_id"]
    lost_201=await g.client.post("/driver/sessions/start",headers=start_headers,json={})
    assert lost_201.status_code==201 and lost_201.json()==started.json()
    current_s2=await _current(g)
    assert current_s2["session_id"]==s2_id
    assert current_s2["vehicle_location_id"]==g.location

    # Day2 starts financially at zero, yet historical cash and credit remain.
    token=tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin,expire_on_commit=False) as db:
            s1=await db.scalar(select(WorkSession).where(
                WorkSession.company_id==g.tenant,
                WorkSession.id==g.session))
            s2=await db.scalar(select(WorkSession).where(
                WorkSession.company_id==g.tenant,
                WorkSession.id==s2_id))
            assert s1.is_settled is True and s1.session_date==old_local_date
            assert s2.session_date==next_local and s2.is_settled is False
            assert s1.commercial_context_id==original_commercial
            assert s2.commercial_context_id==original_commercial
            assert await db.scalar(select(func.count()).select_from(Visit).where(
                Visit.company_id==g.tenant,
                Visit.work_session_id==s2_id))==0
            old_visits=(await db.scalars(select(Visit).where(
                Visit.company_id==g.tenant,
                Visit.work_session_id==g.session,
                Visit.id.in_([g.visit,v2,v3])))).all()
            assert len(old_visits)==3
            assert sum(Decimal(v.cash_collected) for v in old_visits)==Decimal("3.000")
            old_snaps=(await db.scalars(select(SessionInventorySnapshot).where(
                SessionInventorySnapshot.company_id==g.tenant,
                SessionInventorySnapshot.work_session_id==g.session,
                SessionInventorySnapshot.stock_status=="AVAILABLE"))).all()
            assert {(s.location_id,int(s.ending_quantity)) for s in old_snaps}=={
                (g.location,83),(location_b,53)}
            new_snaps=(await db.scalars(select(SessionInventorySnapshot).where(
                SessionInventorySnapshot.company_id==g.tenant,
                SessionInventorySnapshot.work_session_id==s2_id,
                SessionInventorySnapshot.stock_status=="AVAILABLE"))).all()
            assert {(s.location_id,int(s.starting_quantity)) for s in new_snaps}=={
                (g.location,83)}
    finally:
        tenant_context.reset(token)
    assert (await _physical(g,g.location),await _physical(g,location_b))==(83,53)



async def test_m03_field_day_end_a_b_a_closes_only_signed_period_and_exposes_day2_policy(gate):
    """Real FIELD HTTP End Work, physical A/B truth, no dashboard command for S2.

    The day-two attempts intentionally assert the CURRENT frozen policy rather
    than silently invent a PLANNED period or relax prior-day settlement.
    """
    g = gate
    p1, epoch_a, _ = await _set_period(g)
    r2, car_b, location_b, v2, v3, epoch_b = await _prepare_real_b(g)
    assert (await _physical(g, g.location), await _physical(g, location_b)) == (100, 60)
    owner_login = await g.client.post("/login", json={
        "company_code": g.company_code, "username": g.owner_name,
        "password": PASSWORD,
    })
    assert owner_login.status_code == 200, owner_login.text
    backoffice = {"Authorization": "Bearer " + owner_login.json()["token"]}

    # Genuine pending HANDSHAKE must be rejected/received before End Work.
    blocked = await g.client.put("/driver/sessions/end", headers=_headers(g.token))
    assert blocked.status_code == 400, blocked.text
    reject = await g.client.put("/driver/transfers/batch_respond", json={
        "transfers": [{"transfer_id": t, "status": "rejected",
                       "reason": "M03 end-day verified"} for t in g.transfers],
    }, headers=_headers(g.token))
    assert reject.status_code == 200, reject.text

    token = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin, expire_on_commit=False) as db:
            route = await db.scalar(select(DispatchRoute).where(
                DispatchRoute.company_id == g.tenant, DispatchRoute.id == g.route))
            zone = await db.scalar(select(Zone).where(
                Zone.company_id == g.tenant, Zone.id == g.zone))
            original = (
                route.status, route.driver_id, route.vehicle_id,
                route.zone_id, route.assignment_context_revision,
                zone.start_date, zone.interval_days,
            )
            original_shop = await db.scalar(select(Shop).where(
                Shop.company_id == g.tenant,
                Shop.id == g.visit_shop_id,
            )) if hasattr(g, "visit_shop_id") else None
            if original_shop is None:
                prev = await db.scalar(select(Visit).where(
                    Visit.company_id == g.tenant, Visit.id == g.visit))
                original_shop = await db.scalar(select(Shop).where(
                    Shop.company_id == g.tenant, Shop.id == prev.shop_id))
            # Unvisited Zone A shop must survive End Work and next-day denial.
            remain = Shop(company_id=g.tenant, zone_id=g.zone,
                          name="M03 unfinished " + uuid4().hex[:10],
                          tax_jurisdiction_id=original_shop.tax_jurisdiction_id,
                          max_debt_limit=Decimal("500000"), is_active=True)
            db.add(remain)
            await db.flush()
            pending_id = 1_819_000_000 + int(uuid4().hex[:5], 16)
            db.add(Visit(
                id=pending_id, company_id=g.tenant, shop_id=remain.id,
                driver_id=g.field.driver.id, operational_date=date.today(),
                status="Pending", outcome="Pending", sequence=4,
                work_session_id=g.session,
            ))
            await db.commit()
    finally:
        tenant_context.reset(token)

    first = await _current(g)
    assert first["period_id"] == p1
    await _sale(g, g.visit, 12, first)
    url1, url2 = f"/dispatch/route/{g.route}/lifecycle", f"/dispatch/route/{r2}/lifecycle"
    postpone_a = await g.client.put(url1, json=_intent("POSTPONE", 2, period=p1),
                                  headers=backoffice)
    assert postpone_a.status_code == 200, postpone_a.text
    resume_b = await g.client.put(url2, json=_intent(
        "RESUME", 1, driver=g.field.driver.id, vehicle=car_b, custody=1,
    ), headers=backoffice)
    assert resume_b.status_code == 200, resume_b.text
    proof_b = await _current(g)
    assert proof_b["vehicle_location_id"] == location_b
    assert proof_b["custody_epoch_id"] == epoch_b
    await _sale(g, v2, 7, proof_b)
    postpone_b = await g.client.put(url2, json=_intent(
        "POSTPONE", 2, period=proof_b["period_id"],
    ), headers=backoffice)
    assert postpone_b.status_code == 200, postpone_b.text
    resume_a = await g.client.put(url1, json=_intent(
        "RESUME", 3, driver=g.field.driver.id, vehicle=g.vehicle, custody=1,
    ), headers=backoffice)
    assert resume_a.status_code == 200, resume_a.text
    proof_a = await _current(g)
    assert proof_a["period_id"] not in (p1, proof_b["period_id"])
    assert proof_a["assignment_context_revision"] == 4
    assert proof_a["vehicle_location_id"] == g.location
    await _sale(g, v3, 5, proof_a)
    assert (await _physical(g, g.location), await _physical(g, location_b)) == (83, 53)
    # Compare against A->B->A settled route identity at the precise End
    # boundary, NOT its old revision 2 before the two M02 RESUME commands.
    token = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin) as db:
            last_route = await db.scalar(select(DispatchRoute).where(
                DispatchRoute.company_id == g.tenant, DispatchRoute.id == g.route))
            zone_at_end = await db.scalar(select(Zone).where(
                Zone.company_id == g.tenant, Zone.id == g.zone))
            original = (
                last_route.status, last_route.driver_id, last_route.vehicle_id,
                last_route.zone_id, last_route.assignment_context_revision,
                zone_at_end.start_date, zone_at_end.interval_days,
            )
            assert original[:5] == ("active", g.field.driver.id, g.vehicle, g.zone, 4)
    finally:
        tenant_context.reset(token)
    before_end_moves = await _move_count(g)

    # End Work performs NO dashboard POSTPONE/CLOSE/WAITING command.
    end = await g.client.put("/driver/sessions/end", headers=_headers(g.token))
    assert end.status_code == 200, end.text
    assert await _move_count(g) == before_end_moves
    assert (await _physical(g, g.location), await _physical(g, location_b)) == (83, 53)
    again = await g.client.put("/driver/sessions/end", headers=_headers(g.token))
    assert again.status_code == 404, again.text  # existing endpoint replay semantics
    assert await _move_count(g) == before_end_moves

    token = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin, expire_on_commit=False) as db:
            s1 = await db.scalar(select(WorkSession).where(
                WorkSession.company_id == g.tenant, WorkSession.id == g.session))
            assert s1.end_time is not None and not s1.is_settled
            periods = (await db.scalars(select(DispatchRouteExecutionPeriod).where(
                DispatchRouteExecutionPeriod.company_id == g.tenant,
                DispatchRouteExecutionPeriod.work_session_id == g.session,
            ).order_by(DispatchRouteExecutionPeriod.id))).all()
            assert len(periods) == 3
            assert {x.state for x in periods} == {"CLOSED"}
            assert all(x.ended_at is not None for x in periods)
            latest = next(x for x in periods if x.id == proof_a["period_id"])
            assert latest.ended_at == s1.end_time
            assert latest.ended_by_principal_id == g.field.context.principal_id
            assert latest.reason == "WORK_SESSION_ENDED"
            route = await db.scalar(select(DispatchRoute).where(
                DispatchRoute.company_id == g.tenant, DispatchRoute.id == g.route))
            zone = await db.scalar(select(Zone).where(
                Zone.company_id == g.tenant, Zone.id == g.zone))
            assert (route.status, route.driver_id, route.vehicle_id, route.zone_id,
                    route.assignment_context_revision, zone.start_date, zone.interval_days) == original
            visits = (await db.scalars(select(Visit).where(
                Visit.company_id == g.tenant,
                Visit.id.in_([g.visit, v2, v3]),
            ))).all()
            assert len(visits) == 3 and {x.status for x in visits} == {"Completed"}
            assert sum(Decimal(x.cash_collected) for x in visits) == Decimal("3.000")
            assert {x.execution_period_id for x in visits} == {x.id for x in periods}
            unfinished = await db.scalar(select(Visit).where(
                Visit.company_id == g.tenant, Visit.id == pending_id))
            assert unfinished.status == "Pending"
            assert unfinished.work_session_id == g.session
            old_visit_date = unfinished.operational_date
            old_day = s1.session_date
    finally:
        tenant_context.reset(token)

    # Exact old offline envelope must not execute after End Work.
    denied = await g.client.put(f"/visits/{pending_id}", json={
        "request_id": str(uuid4()), "outcome": "NoSale",
        "notes": "Stale offline S1 command after End Work",
    }, headers=_headers(g.token, p1, 2, epoch_a))
    assert denied.status_code in (403, 409), denied.text
    assert await _move_count(g) == before_end_moves

    # Real next business date BEFORE both HTTP Start Work attempts; shift
    # tenant timezone only in this disposable PG16 fixture, never auth logic.
    token = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin, expire_on_commit=False) as db:
            tenant_company = await db.scalar(select(Company).where(
                Company.id == g.tenant).with_for_update())
            tenant_company.timezone = "Pacific/Kiritimati"
            day2 = datetime.now(timezone.utc).astimezone(ZoneInfo("Pacific/Kiritimati")).date()
            assert day2 > old_day
            await db.commit()
    finally:
        tenant_context.reset(token)

    day2_key = str(uuid4())
    day2_headers = {**_headers(g.token), "Idempotency-Key": day2_key}
    pre_settlement = await g.client.post("/driver/sessions/start",
                                        headers=day2_headers, json={})
    assert pre_settlement.status_code == 400, pre_settlement.text
    # This is test-only evidence of *already authorized* S1 settlement, NOT a
    # production settlement bypass or a change to the real finance workflow.
    token = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin, expire_on_commit=False) as db:
            old = await db.scalar(select(WorkSession).where(
                WorkSession.company_id == g.tenant, WorkSession.id == g.session
            ).with_for_update())
            sealed = utc_now()
            old.is_settled = True
            old.inventory_reconciled_at = sealed
            old.inventory_reconciled_by = g.field.driver.id
            for snap in (await db.scalars(select(SessionInventorySnapshot).where(
                SessionInventorySnapshot.company_id == g.tenant,
                SessionInventorySnapshot.work_session_id == g.session,
            ).with_for_update())).all():
                snap.ending_quantity = Decimal("83") if snap.location_id == g.location else Decimal("53")
                snap.settled_at = sealed
                snap.settled_by = g.field.driver.id
            await db.commit()
    finally:
        tenant_context.reset(token)

    # OWNER-APPROVED S2: exact existing FIELD Start Work HTTP, no Backoffice
    # RESUME/POSTPONE/launch, and two simultaneous lost-201 retries. Driver
    # row + idempotency advisory lock must produce ONE session/period.
    s2, s2_race = await asyncio.gather(
        g.client.post("/driver/sessions/start", headers=day2_headers, json={}),
        g.client.post("/driver/sessions/start", headers=day2_headers, json={}),
    )
    assert s2.status_code == 201, s2.text
    assert s2_race.status_code == 201 and s2_race.json() == s2.json(), s2_race.text
    s2_id = s2.json()["session_id"]
    assert s2_id != g.session
    s2_proof = await _current(g)
    assert s2_proof["session_id"] == s2_id
    assert s2_proof["route_id"] == g.route
    assert s2_proof["vehicle_location_id"] == g.location
    assert s2_proof["assignment_context_revision"] == 5
    assert s2_proof["period_id"] not in {p1, proof_b["period_id"], proof_a["period_id"]}
    assert s2.json()["execution_context"]["period_id"] == s2_proof["period_id"]
    assert await _move_count(g) == before_end_moves
    replay = await g.client.post("/driver/sessions/start", headers=day2_headers, json={})
    assert replay.status_code == 201 and replay.json() == s2.json()
    another = await g.client.post(
        "/driver/sessions/start",
        headers={**_headers(g.token), "Idempotency-Key": str(uuid4())},
        json={},
    )
    assert another.status_code == 409, another.text
    assert await _move_count(g) == before_end_moves

    # Same old Pending Visit ID/operation date appears exactly ONCE.
    visits_http = await g.client.get("/driver/visits", headers=_headers(g.token))
    assert visits_http.status_code == 200, visits_http.text
    visits_payload = visits_http.json()["visits"]
    assert [item["visit_id"] for item in visits_payload].count(pending_id) == 1
    dashboard = await g.client.get("/driver/dashboard", headers=_headers(g.token))
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["execution_context"]["session_id"] == s2_id

    # Previous offline S1 envelopes never authorize a day2 command.
    old_replay = await g.client.put(f"/visits/{pending_id}", json={
        "request_id": str(uuid4()), "outcome": "NoSale",
        "notes": "Stale S1 on next-day S2",
    }, headers=_headers(g.token, p1, 2, epoch_a))
    assert old_replay.status_code == 409, old_replay.text
    assert await _move_count(g) == before_end_moves

    token = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin) as db:
            s1_db = await db.scalar(select(WorkSession).where(
                WorkSession.company_id == g.tenant, WorkSession.id == g.session))
            s2_db = await db.scalar(select(WorkSession).where(
                WorkSession.company_id == g.tenant, WorkSession.id == s2_id))
            assert s1_db.end_time is not None and s1_db.is_settled
            assert s2_db.session_date == day2 and s2_db.end_time is None
            assert not s2_db.is_settled and s2_db.inventory_reconciled_at is None
            assert s2_db.commercial_context_id == s1_db.commercial_context_id
            assert await db.scalar(select(func.count()).select_from(WorkSession).where(
                WorkSession.company_id == g.tenant,
                WorkSession.driver_id == g.field.driver.id,
                WorkSession.session_date == day2,
            )) == 1
            assert await db.scalar(select(func.count()).select_from(
                DispatchRouteExecutionPeriod).where(
                DispatchRouteExecutionPeriod.company_id == g.tenant,
                DispatchRouteExecutionPeriod.work_session_id == s2_id,
                DispatchRouteExecutionPeriod.state == "ACTIVE",
            )) == 1
            assert await db.scalar(select(func.count()).select_from(Visit).where(
                Visit.company_id == g.tenant,
                Visit.work_session_id == s2_id,
            )) == 0  # zero sales, money and visits start in new daily session
            leftover = await db.scalar(select(Visit).where(
                Visit.company_id == g.tenant, Visit.id == pending_id))
            assert leftover.status == "Pending"
            assert leftover.operational_date == old_visit_date
            assert leftover.work_session_id == g.session  # no Start Work rewrite
            route = await db.scalar(select(DispatchRoute).where(
                DispatchRoute.company_id == g.tenant, DispatchRoute.id == g.route))
            zone = await db.scalar(select(Zone).where(
                Zone.company_id == g.tenant, Zone.id == g.zone))
            assert (route.status, route.driver_id, route.vehicle_id, route.zone_id,
                    zone.start_date, zone.interval_days) == (
                original[0], original[1], original[2], original[3],
                original[5], original[6],
            )
            assert route.assignment_context_revision == 5
            snapshots = (await db.scalars(select(SessionInventorySnapshot).where(
                SessionInventorySnapshot.company_id == g.tenant,
                SessionInventorySnapshot.work_session_id == s2_id,
                SessionInventorySnapshot.stock_status == "AVAILABLE",
            ))).all()
            assert {(row.location_id, int(row.starting_quantity)) for row in snapshots} == {
                (g.location, 83)
            }
            old_sales = (await db.scalars(select(Visit).where(
                Visit.company_id == g.tenant, Visit.id.in_([g.visit, v2, v3]),
            ))).all()
            assert all(v.work_session_id == g.session for v in old_sales)
            assert sum(Decimal(v.cash_collected) for v in old_sales) == Decimal("3.000")
    finally:
        tenant_context.reset(token)

    # Sales permission is a DISTINCT, existing owner-controlled session
    # authorization, not a route launch/resume; M03 MUST NOT auto-grant it.
    # This first attempted visit must remain blocked until separately approved.
    denied_sale = await g.client.put(
        f"/visits/{pending_id}",
        json={"request_id": str(uuid4()), "outcome": "NoSale",
              "notes": "Must keep session sell permission"},
        headers=_headers(g.token, s2_proof["period_id"], 5, s2_proof["custody_epoch_id"]),
    )
    assert denied_sale.status_code == 403, denied_sale.text
    authorized = await g.client.put(
        f"/admin/sessions/{s2_id}/authorize",
        json={"is_authorized": True},
        headers=backoffice,
    )
    assert authorized.status_code == 200, authorized.text

    # Only a genuine S2 command may finish the ORIGINAL pending Visit ID.
    # Its original day is retained; no duplicate Visit or old posted edit.
    posted = await g.client.put(
        f"/visits/{pending_id}",
        json={"request_id": str(uuid4()), "outcome": "NoSale",
              "notes": "Unfinished same-zone shop visited on S2"},
        headers=_headers(g.token, s2_proof["period_id"], 5, s2_proof["custody_epoch_id"]),
    )
    assert posted.status_code == 200, posted.text
    token = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin) as db:
            done = await db.scalar(select(Visit).where(
                Visit.company_id == g.tenant, Visit.id == pending_id))
            assert done.status == "Completed"
            assert done.operational_date == old_visit_date
            assert done.work_session_id == s2_id
            assert done.execution_period_id == s2_proof["period_id"]
            assert await db.scalar(select(func.count()).select_from(Visit).where(
                Visit.company_id == g.tenant,
                Visit.shop_id == done.shop_id,
                Visit.operational_date == old_visit_date,
            )) == 1
    finally:
        tenant_context.reset(token)
    assert await _move_count(g) == before_end_moves
    assert (await _physical(g, g.location), await _physical(g, location_b)) == (83, 53)
