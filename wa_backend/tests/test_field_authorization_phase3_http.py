"""Actual mounted HTTP + restricted PostgreSQL capability AND scope acceptance."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from domains.authorization.capabilities import FIELD_ASSIGNABLE_PERMISSIONS
from models import (
    Visit, Shop, Zone, Vehicle, InventoryLocation, DispatchRoute, WorkSession,
    InventoryTransferHeader,
)
from tests.field_authorization_phase3_fixture import (
    gate, auth, call, denied, evidence, set_codes, new_transfers,
)
from tests.field_authorization_phase3_matrix import CASES, request_case

pytestmark=pytest.mark.asyncio


@pytest.mark.parametrize("case",CASES,ids=lambda c:c["name"])
async def test_same_token_immediate_revoke_denies_every_business_route_without_effect(gate,case):
    g=gate
    endpoint=f"/representatives/{g.field.context.representative_id}/field-roles"
    response=await call(g,"POST",endpoint+f"/{g.default_role}/revoke",
        {"request_id":str(uuid4())},token=g.owner_token)
    assert response.status_code==200,response.text
    try:
        before=await evidence(g)
        method,path,body=request_case(g,case)
        denied(await call(g,method,path,body))
        assert await evidence(g)==before
        # Authentication is still possible; it cannot opportunistically restore the grant.
        refresh=await call(g,"POST","/refresh",{"refresh_token":g.login["refresh_token"]})
        assert refresh.status_code==200,refresh.text
        g.login=refresh.json()
        after_refresh=await evidence(g)
        denied(await call(g,method,path,body,token=g.login.get("access_token",g.login.get("token"))))
        assert await evidence(g)==after_refresh
    finally:
        response=await call(g,"POST",endpoint,{"role_id":g.default_role,"request_id":str(uuid4())},
                            token=g.owner_token)
        assert response.status_code==200,response.text


MISSING=[(case,code) for case in CASES for code in case["codes"]]


@pytest.mark.parametrize("case,missing",MISSING,ids=[c["name"]+"-"+p for c,p in MISSING])
async def test_each_required_capability_is_independently_necessary(gate,case,missing):
    g=gate
    await set_codes(g,FIELD_ASSIGNABLE_PERMISSIONS-{missing})
    try:
        before=await evidence(g)
        method,path,body=request_case(g,case)
        denied(await call(g,method,path,body))
        assert await evidence(g)==before
    finally:
        await set_codes(g,FIELD_ASSIGNABLE_PERMISSIONS)


@pytest.mark.parametrize("token_name",["bo_token","owner_token"])
@pytest.mark.parametrize("case",CASES,ids=lambda c:c["name"])
async def test_backoffice_tokens_cannot_enter_field_channel(gate,case,token_name):
    # GET visit detail is intentionally shared: its existing BO authorization remains.
    if case["name"]=="get_visit_details":
        response=await call(gate,"GET",f"/visits/{gate.visit}",token=getattr(gate,token_name))
        assert response.status_code==200,response.text
        return
    before=await evidence(gate)
    method,path,body=request_case(gate,case)
    denied(await call(gate,method,path,body,token=getattr(gate,token_name)),401,None)
    assert await evidence(gate)==before


@pytest.mark.parametrize("path",["/inventory/access/me","/representatives","/dispatch/init",
                                  "/pricing/policy","/admin/sessions/today"])
async def test_field_token_has_no_backoffice_access_even_with_dual_split_grants(gate,path):
    before=await evidence(gate)
    response=await call(gate,"GET",path)
    assert response.status_code in (401,403),response.text
    assert await evidence(gate)==before


@pytest.mark.parametrize("name",["get_visit_details","get_visit_commercial_state","preview_visit_invoice",
                                 "resolve_visit_return","update_visit","get_visit_invoice",
                                 "accept","reject","batch_mixed","reconcile_driver_end_of_day"])
async def test_foreign_company_has_no_object_access_or_mutation(gate,name):
    case=next(c for c in CASES if c["name"]==name)
    before=(await evidence(gate),await evidence(gate.foreign))
    method,path,body=request_case(gate,case)
    response=await call(gate,method,path,body,token=gate.foreign_token)
    assert response.status_code in (403,404),response.text
    assert (await evidence(gate),await evidence(gate.foreign))==before


async def test_wrong_visit_and_transfer_receiver_fail_closed(gate):
    g=gate
    for method,path,body in [
        ("GET",f"/visits/{g.visit}",None),
        ("GET",f"/visits/{g.visit}/commercial-state",None),
        ("PUT",f"/visits/{g.visit}",{"request_id":str(uuid4()),"outcome":"NoSale","notes":"Synthetic"}),
        ("PUT",f"/driver/transfers/{g.transfers[0]}/respond",{"response":"accepted"}),
        ("PUT","/driver/transfers/batch_respond",{"transfers":[
            {"transfer_id":g.transfers[0],"status":"accepted"}]}),
    ]:
        before=await evidence(g)
        response=await call(g,method,path,body,token=g.other_token)
        assert response.status_code in (403,404),response.text
        assert await evidence(g)==before


async def test_wrong_route_zone_preserves_assignment_guard(gate):
    g=gate
    async with AsyncSession(g.admin) as db:
        shop=await db.get(Shop,await db.scalar(select(Visit.shop_id).where(Visit.id==g.visit)))
        original=shop.zone_id
        zone=Zone(company_id=g.tenant,name="Unassigned "+uuid4().hex)
        db.add(zone)
        await db.flush()
        shop.zone_id=zone.id
        await db.commit()
        try:
            before=await evidence(g)
            denied(await call(g,"GET",f"/visits/{g.visit}/commercial-state"),
                   403,"FIELD_VISIT_OUTSIDE_ASSIGNMENT")
            response=await call(g,"PUT",f"/visits/{g.visit}",
                {"request_id":str(uuid4()),"outcome":"NoSale","notes":"Synthetic"})
            assert response.status_code==403,response.text
            assert await evidence(g)==before
        finally:
            shop.zone_id=original
            await db.commit()


async def test_wrong_vehicle_and_atomic_batch_scope_denial(gate):
    g=gate
    async with AsyncSession(g.admin,expire_on_commit=False) as db:
        vehicle=Vehicle(company_id=g.tenant,plate_number="P3-"+uuid4().hex[:10],
                        maintenance_status="Active",is_active=True)
        db.add(vehicle)
        await db.flush()
        location=InventoryLocation(company_id=g.tenant,code="P3-"+uuid4().hex[:16],
            name="Other vehicle",location_type="VEHICLE",vehicle_id=vehicle.id,
            is_active=True,is_system_managed=False)
        db.add(location)
        await db.commit()
    ids=await new_transfers(g,destination=location.id)
    for path,body in [
        (f"/driver/transfers/{ids[0]}/respond",{"response":"accepted"}),
        ("/driver/transfers/batch_respond",{"transfers":[
            {"transfer_id":g.transfers[0],"status":"accepted"},
            {"transfer_id":ids[0],"status":"accepted"}]}),
    ]:
        before=await evidence(g)
        response=await call(g,"PUT",path,body)
        assert response.status_code==403,response.text
        assert await evidence(g)==before
    async with AsyncSession(g.admin) as db:
        own=await db.get(InventoryLocation,g.location)
        own.is_active=False
        await db.commit()
        try:
            before=await evidence(g)
            response=await call(g,"GET","/driver/custody")
            assert response.status_code in (403,404,409),response.text
            assert await evidence(g)==before
        finally:
            own.is_active=True
            await db.commit()
    # Close the deliberately wrong-destination fixture via the real rejection
    # path; otherwise later composite reads correctly reject its pending evidence.
    for transfer in ids:
        response=await call(g,"PUT",f"/driver/transfers/{transfer}/respond",
                           {"response":"rejected","reason":"Synthetic wrong destination"})
        assert response.status_code==200,response.text


async def test_default_grants_real_visit_invoice_returns_custody_shop_and_replay(gate):
    g=gate
    for path in ("/driver/sessions/active","/driver/dashboard","/driver/visits",
                 f"/visits/{g.visit}",f"/visits/{g.visit}/commercial-state",
                 "/product_variants","/driver/custody","/driver/transfers/pending"):
        response=await call(g,"GET",path)
        assert response.status_code==200,(path,response.text)
    preview=await call(g,"POST",f"/visits/{g.visit}/invoice-preview",
        {"cart_items":[{"product_variant_id":g.variant["id"],"packs_quantity":10}]})
    assert preview.status_code==200,preview.text
    assert Decimal(preview.json()["invoice"]["totals"]["final_amount"])==Decimal("50")
    command={"request_id":str(uuid4()),"outcome":"Sale","cash_collected":"50",
             "cart_items":[{"product_variant_id":g.variant["id"],"packs_quantity":10}]}
    posted=await call(g,"PUT",f"/visits/{g.visit}",command)
    assert posted.status_code==200,posted.text
    frozen=await call(g,"GET",f"/visits/{g.visit}/invoice")
    assert frozen.status_code==200,frozen.text
    assert frozen.json()["invoice"]["totals"]==posted.json()["invoice"]["totals"]
    before=await evidence(g)
    assert (await call(g,"PUT",f"/visits/{g.visit}",command)).json()==posted.json()
    assert await evidence(g)==before
    async with AsyncSession(g.admin,expire_on_commit=False) as db:
        source=await db.get(Visit,g.visit)
        target=Visit(id=1700000000+uuid4().int%300000000,company_id=g.tenant,shop_id=source.shop_id,
            driver_id=g.field.driver.id,operational_date=source.operational_date,status="Pending",outcome="Pending")
        db.add(target)
        await db.commit()
    returns=[]
    for reason in ("Damaged","Expired","Factory_Defect"):
        request={"product_variant_id":g.variant["id"],"packs_quantity":1,"return_type":reason}
        response=await call(g,"POST",f"/visits/{target.id}/return-resolution",request)
        assert response.status_code==200,response.text
        assert response.json()["status"]=="RESOLVED"
        assert "batch_id" not in response.json()
        returns.append({**request,"resolution_token":response.json()["resolution_token"]})
    command={"request_id":str(uuid4()),"outcome":"NoSale","returns":returns}
    response=await call(g,"PUT",f"/visits/{target.id}",command)
    assert response.status_code==200,response.text
    before=await evidence(g)
    assert (await call(g,"PUT",f"/visits/{target.id}",command)).json()==response.json()
    assert await evidence(g)==before
    custody=await call(g,"GET","/driver/custody")
    assert custody.status_code==200,custody.text
    assert sum(Decimal(i["quantity"]) for i in custody.json()["items"])==Decimal("3")
    command={"request_id":str(uuid4()),"name":"New field shop","phone_number":uuid4().hex[:15]}
    created=await call(g,"POST","/shops",command)
    assert created.status_code==201,created.text
    before=await evidence(g)
    assert (await call(g,"POST","/shops",command)).json()==created.json()
    assert await evidence(g)==before


@pytest.mark.parametrize("decisions",[
    ["accepted","accepted"],["rejected","rejected"],["accepted","rejected"],
])
async def test_real_transfer_batches_authorize_minimal_decisions_and_exact_replay(gate,decisions):
    g=gate
    ids=await new_transfers(g)
    needed={"transfer.receive" if d=="accepted" else "transfer.reject" for d in decisions}
    await set_codes(g,needed)
    try:
        body={"transfers":[{"transfer_id":i,"status":d,"reason":"Synthetic"} for i,d in zip(ids,decisions)]}
        response=await call(g,"PUT","/driver/transfers/batch_respond",body)
        assert response.status_code==200,response.text
        async with g.admin.connect() as db:
            statuses=(await db.execute(text(
                "SELECT status FROM inventory_transfer_headers WHERE id=ANY(:ids) ORDER BY id"),{"ids":ids})).scalars().all()
            assert statuses==["POSTED" if d=="accepted" else "REJECTED" for d in decisions]
        before=await evidence(g)
        assert (await call(g,"PUT","/driver/transfers/batch_respond",body)).json()==response.json()
        assert await evidence(g)==before
    finally:
        await set_codes(g,FIELD_ASSIGNABLE_PERMISSIONS)


@pytest.mark.parametrize("decision",["accepted","rejected"])
async def test_real_single_transfer_minimal_permission_and_exact_replay(gate,decision):
    g=gate
    ids=await new_transfers(g,count=1)
    await set_codes(g,{"transfer.receive" if decision=="accepted" else "transfer.reject"})
    try:
        path=f"/driver/transfers/{ids[0]}/respond"
        body={"response":decision,"reason":"Synthetic"}
        response=await call(g,"PUT",path,body)
        assert response.status_code==200,response.text
        before=await evidence(g)
        assert (await call(g,"PUT",path,body)).json()==response.json()
        assert await evidence(g)==before
    finally:
        await set_codes(g,FIELD_ASSIGNABLE_PERMISSIONS)


async def test_transfer_batch_preserves_100_limit_and_attributed_validation(gate):
    g=gate
    before=await evidence(g)
    response=await call(g,"PUT","/driver/transfers/batch_respond",{"transfers":[
        {"transfer_id":i,"status":"accepted"} for i in range(1,102)]})
    denied(response,413,"FIELD_TRANSFER_BATCH_TOO_LARGE")
    response=await call(g,"PUT","/driver/transfers/batch_respond",{"transfers":[
        {"transfer_id":g.transfers[0],"status":"rejected"}]})
    denied(response,422,"FIELD_TRANSFER_REJECTION_REASON_REQUIRED")
    assert response.json()["error"]["context"]=={"transfer_id":g.transfers[0]}
    assert await evidence(g)==before


async def test_default_session_start_break_end_reconcile_own_assignment(gate):
    from domains.pricing.context import lock_route_commercial_context
    g=gate
    async with AsyncSession(g.admin,expire_on_commit=False) as db:
        zone=Zone(company_id=g.tenant,name="P3 session "+uuid4().hex)
        vehicle=Vehicle(company_id=g.tenant,plate_number="P3S"+uuid4().hex[:9],
                        maintenance_status="Active",is_active=True)
        db.add_all([zone,vehicle])
        await db.flush()
        db.add(InventoryLocation(company_id=g.tenant,code="P3S"+uuid4().hex[:15],
            name="Session vehicle",location_type="VEHICLE",vehicle_id=vehicle.id,is_active=True,
            is_system_managed=False))
        route=DispatchRoute(company_id=g.tenant,zone_id=zone.id,vehicle_id=vehicle.id,
            driver_id=g.other.driver.id,source_location_id=g.warehouse_id,status="waiting")
        db.add(route)
        await db.flush()
        await lock_route_commercial_context(db,company_id=g.tenant,dispatch_route_id=route.id)
        route.status="active"
        await db.commit()
    response=await call(g,"POST","/driver/sessions/start",{},token=g.other_token)
    assert response.status_code==201,response.text
    active=await call(g,"GET","/driver/sessions/active",token=g.other_token)
    assert active.status_code==200,active.text
    session=active.json()["session_id"]
    for action in ("start","end"):
        response=await call(g,"PUT","/driver/sessions/break",{"action":action},token=g.other_token)
        assert response.status_code==200,response.text
    response=await call(g,"PUT","/driver/sessions/end",token=g.other_token)
    assert response.status_code==200,response.text
    response=await call(g,"POST",f"/driver/session/{session}/reconcile",{"counts":[]},token=g.other_token)
    assert response.status_code==200,response.text
    before=await evidence(g)
    replay=await call(g,"POST",f"/driver/session/{session}/reconcile",{"counts":[]},token=g.other_token)
    assert replay.status_code==200,replay.text
    assert replay.json()["already_reconciled"]
    assert await evidence(g)==before
