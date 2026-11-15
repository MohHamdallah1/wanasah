"""#773 one real signed PG16/Bearer posted-batch correction; no old suite reruns."""
from __future__ import annotations
import os
import asyncio
from context import tenant_context
from datetime import date
from uuid import uuid4
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import engine as runtime_engine
from models import (
    Company, UOM, Product, ProductVariant, InventoryLocation, InventoryLiveStockProjection,
    InventoryBalance, InventoryCostEvent, InventoryCostState, InventoryCostLayer,
    InventoryCostAllocation, InventoryMovement, ProductBatch,
    StocktakeSession,
)
from domains.inventory_batch_metadata.models import BatchMetadataCorrectionEvent
from tests.test_dispatch_m03_period_postgres import gate, _headers
from tests.test_dispatch_c01_c02_custody_postgres import _login_owner, _ledger_signature
from tests.field_authorization_phase3_fixture import PASSWORD
from tests.canonical_actor_fixtures import seed_company_owner_fixture, seed_ordinary_backoffice_fixture
from tests.supplier_fixtures import seed_receipt_supplier

pytestmark=[
    pytest.mark.skipif(
        os.getenv("WANASAH_BATCH773_PG_GATE")!="1",
        reason="Explicit disposable batch773 restricted PG16 only",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]


async def test_posted_single_source_batch_reauth_inventory_cost_and_history(gate):
    g=gate
    assert os.environ["DATABASE_URL"].endswith("/m03_941_b773_v1")
    assert "@127.0.0.1:56673/" in os.environ["DATABASE_URL"]
    manager=await _login_owner(g)
    foreign=await _login_owner(g,g.foreign)
    field_headers=_headers(g.token)
    company=g.tenant
    location=g.warehouse_id

    async with runtime_engine.connect() as conn:
        role= (await conn.execute(text(
            "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ))).one()
        assert tuple(role)==(False,False)
        for tab in ("product_batches","batch_metadata_correction_events",
                    "inventory_movements","inventory_cost_events"):
            rls=(await conn.execute(text(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                "WHERE oid=to_regclass(:tab)"
            ),{"tab":tab})).one()
            assert tuple(rls)==(True,True), (tab,rls)

    async def receipt(lot: str, invoice: str, quantity="8", price="3"):
        body={
            "request_id":str(uuid4()),"supplier_id":g.supplier_id,
            "location_id":location,"reference_id":invoice,
            "items":[{"product_variant_id":g.variant["id"],"quantity":quantity,
                      "uom_id":g.variant["base_uom_id"],"unit_cost":price,
                      "batch_number":lot,"production_date":"2026-01-01",
                      "expiry_date":"2027-06-30"}],
        }
        response=await g.client.post("/warehouse/inbound",headers=manager,json=body)
        assert response.status_code==201,response.text
        async with AsyncSession(g.admin) as db:
            row=await db.scalar(select(ProductBatch).where(
                ProductBatch.company_id==company,ProductBatch.batch_number==lot,
            ))
            assert row is not None
            return row.id

    lot="WRONG-"+uuid4().hex[:10]
    batch=await receipt(lot,"REAL-INV-"+uuid4().hex[:12])
    path=f"/warehouse/batches/{batch}/metadata-correction"
    preview=await g.client.get(path,headers=manager,params={"location_id":location})
    assert preview.status_code==200,preview.text
    state=preview.json()
    assert state["eligible"] is True,state
    assert state["metadata_revision"]==1
    assert state["source_invoice"].startswith("REAL-INV-")
    assert (await g.client.get(path,headers=foreign,params={"location_id":location})).status_code in (403,404)
    assert (await g.client.get(path,headers=field_headers,params={"location_id":location})).status_code in (401,403)

    original_ledger=await _ledger_signature(g)
    async with AsyncSession(g.admin) as db:
        costs_before=(await db.execute(select(
            InventoryCostEvent.id,InventoryCostEvent.method,
            InventoryCostEvent.quantity,InventoryCostEvent.total_cost
        ).where(InventoryCostEvent.company_id==company,
                InventoryCostEvent.batch_id==batch))).all()
        assert len(costs_before)==1 and costs_before[0].method=="FIFO"
        balance_before=(await db.execute(select(
            InventoryBalance.id,InventoryBalance.on_hand_quantity,InventoryBalance.reserved_quantity
        ).where(InventoryBalance.company_id==company,
                InventoryBalance.batch_id==batch))).all()
        assert len(balance_before)==1
        fifo_before=(await db.execute(select(
            InventoryCostLayer.id, InventoryCostLayer.original_quantity,
            InventoryCostLayer.remaining_quantity, InventoryCostLayer.original_value,
            InventoryCostLayer.remaining_value, InventoryCostLayer.version,
        ).where(InventoryCostLayer.company_id==company,
                InventoryCostLayer.batch_id==batch))).all()
        assert len(fifo_before)==1
        allocations_before=(await db.execute(select(
            InventoryCostAllocation.id, InventoryCostAllocation.cost_layer_id,
            InventoryCostAllocation.quantity, InventoryCostAllocation.amount,
        ).where(InventoryCostAllocation.company_id==company,
                InventoryCostAllocation.cost_layer_id==fifo_before[0].id))).all()
    request={
        "request_id":str(uuid4()),"expected_revision":1,"location_id":location,
        "batch_number":"REAL-"+uuid4().hex[:10],
        "production_date":"2026-01-03","expiry_date":"2027-09-03",
        "reason":"Correct printed production lot and real expiry","password":PASSWORD,
    }
    bad_password=await g.client.post(path,headers=manager,json={
        **request,"password":"Bad-Credential-Not-Manager",
    })
    assert bad_password.status_code==403,bad_password.text
    assert (await g.client.get(path,headers=manager,
          params={"location_id":location})).json()["current"]["batch_number"]==lot
    foreign_mutation=await g.client.post(path,headers=foreign,json=request)
    assert foreign_mutation.status_code in (403,404),foreign_mutation.text
    good=await g.client.post(path,headers=manager,json=request)
    assert good.status_code==200,good.text
    updated=good.json()
    assert updated["metadata_revision"]==2 and updated["current"]["batch_number"]==request["batch_number"]
    assert updated["current"]["expiry_date"]==request["expiry_date"]
    assert updated["source_invoice"]==state["source_invoice"]
    assert (await g.client.post(path,headers=manager,json=request)).json()==updated
    assert (await g.client.post(path,headers=manager,json={
        **request,"batch_number":"ALTERED-WITH-SAME-UUID",
    })).status_code==409
    assert (await g.client.post(path,headers=manager,json={
        **request,"request_id":str(uuid4()),
    })).status_code==409

    history=await g.client.get(
        f"/warehouse/batches/{batch}/metadata-corrections/history",
        headers=manager,params={"location_id":location},
    )
    assert history.status_code==200 and len(history.json()["items"])==1,history.text
    event=history.json()["items"][0]
    assert event["before"]["batch_number"]==lot
    assert event["after"]["batch_number"]==request["batch_number"]
    assert event["source_invoice"]==state["source_invoice"]
    assert event["actor_username"] and event["reason"]==request["reason"]
    assert "password" not in history.text.lower()
    assert (await _ledger_signature(g))==original_ledger
    async with AsyncSession(g.admin) as db:
        costs_after=(await db.execute(select(
            InventoryCostEvent.id,InventoryCostEvent.method,
            InventoryCostEvent.quantity,InventoryCostEvent.total_cost
        ).where(InventoryCostEvent.company_id==company,
                InventoryCostEvent.batch_id==batch))).all()
        balance_after=(await db.execute(select(
            InventoryBalance.id,InventoryBalance.on_hand_quantity,InventoryBalance.reserved_quantity
        ).where(InventoryBalance.company_id==company,
                InventoryBalance.batch_id==batch))).all()
        fifo_after=(await db.execute(select(
            InventoryCostLayer.id, InventoryCostLayer.original_quantity,
            InventoryCostLayer.remaining_quantity, InventoryCostLayer.original_value,
            InventoryCostLayer.remaining_value, InventoryCostLayer.version,
        ).where(InventoryCostLayer.company_id==company,
                InventoryCostLayer.batch_id==batch))).all()
        allocations_after=(await db.execute(select(
            InventoryCostAllocation.id, InventoryCostAllocation.cost_layer_id,
            InventoryCostAllocation.quantity, InventoryCostAllocation.amount,
        ).where(InventoryCostAllocation.company_id==company,
                InventoryCostAllocation.cost_layer_id==fifo_before[0].id))).all()
        assert costs_after==costs_before and balance_after==balance_before
        assert fifo_after==fifo_before and allocations_after==allocations_before
        events=(await db.scalars(select(BatchMetadataCorrectionEvent).where(
            BatchMetadataCorrectionEvent.company_id==company,
            BatchMetadataCorrectionEvent.batch_id==batch,
        ))).all()
        assert len(events)==1 and events[0].source_cost_event_id==costs_before[0].id
        assert events[0].request_id==request["request_id"]
        assert events[0].actor_auth_revision>=1

    # Independent explicit whole-stock physical receipt, same original Lot reused
    # under a SECOND supplier invoice; correction must fail closed.
    another="SHARED-"+uuid4().hex[:9]
    shared=await receipt(another,"INV-MULTI-"+uuid4().hex[:8],price="2")
    await receipt(another,"INV-MULTI-"+uuid4().hex[:8],price="7")
    shared_preview=await g.client.get(
        f"/warehouse/batches/{shared}/metadata-correction",
        headers=manager,params={"location_id":location},
    )
    assert shared_preview.status_code==200
    assert not shared_preview.json()["eligible"]
    assert shared_preview.json()["block_code"]=="BATCH_USED_OR_SHARED_RECEIPT"
    # A second batch name, even with differing case, cannot be merged.
    collide="TARGET-"+uuid4().hex[:8]
    await receipt(collide,"INV-COLL-"+uuid4().hex[:10])
    collision=await g.client.post(path,headers=manager,json={
        **request,"request_id":str(uuid4()),"expected_revision":2,
        "batch_number":collide.lower(),
    })
    assert collision.status_code==409,collision.text

    # Reservation on a separate untouched receipt prevents any metadata edit.
    reserved_lot="RESERVED-"+uuid4().hex[:8]
    reserved=await receipt(reserved_lot,"INV-RES-"+uuid4().hex[:8])
    # The signed real inventory engine will be used for the reservation, not a
    # fake edit to reserved_quantity or a forged Stocktake variance.
    from services import apply_inventory_movements_batch
    async with AsyncSession(g.admin,expire_on_commit=False) as db:
        await apply_inventory_movements_batch(db,company_id=company,
            performed_by=g.actor.id,movements=[dict(
                product_variant_id=g.variant["id"],batch_id=reserved,quantity=Decimal("1"),
                movement_kind="RESERVATION",reservation_action="RESERVE",
                reference_type="B773_TEST_RESERVATION",reference_id=str(uuid4()),
                idempotency_key="B773-R-"+uuid4().hex,
                source_location_id=location,destination_location_id=location,
                source_stock_status="AVAILABLE",destination_stock_status="AVAILABLE",
            )])
        await db.commit()
    reserved_preview=await g.client.get(
        f"/warehouse/batches/{reserved}/metadata-correction",
        headers=manager,params={"location_id":location},
    )
    assert not reserved_preview.json()["eligible"]
    assert reserved_preview.json()["block_code"]=="BATCH_USED_OR_SHARED_RECEIPT"

    # Real canonical physical transfer creates immutable downstream movement.
    # Even if remaining stock is positive in the original warehouse, printed
    # carton identity can no longer be safely corrected in place.
    moved_lot="MOVED-"+uuid4().hex[:8]
    moved=await receipt(moved_lot,"INV-MOVE-"+uuid4().hex[:8])
    async with AsyncSession(g.admin,expire_on_commit=False) as db:
        await apply_inventory_movements_batch(db,company_id=company,
            performed_by=g.actor.id,movements=[dict(
                product_variant_id=g.variant["id"],batch_id=moved,quantity=Decimal("1"),
                movement_kind="PHYSICAL",reference_type="B773_TEST_REAL_TRANSFER",
                reference_id=str(uuid4()),idempotency_key="B773-M-"+uuid4().hex,
                source_location_id=location,destination_location_id=g.location,
                source_stock_status="AVAILABLE",destination_stock_status="AVAILABLE",
            )])
        await db.commit()
    moved_view=await g.client.get(
        f"/warehouse/batches/{moved}/metadata-correction",
        headers=manager,params={"location_id":location},
    )
    assert moved_view.status_code==200,moved_view.text
    assert moved_view.json()["block_code"]=="BATCH_USED_OR_SHARED_RECEIPT"

    # Active cycle count is an independent, explicit no-edit gate; not
    # inferred from a missing/zero balance. Seed only a scoped DRAFT test row.
    counting_lot="COUNT-"+uuid4().hex[:8]
    counting=await receipt(counting_lot,"INV-COUNT-"+uuid4().hex[:8])
    async with AsyncSession(g.admin,expire_on_commit=False) as db:
        db.add(StocktakeSession(
            company_id=company,location_id=location,
            reference_number="B773-CYCLE-"+uuid4().hex[:12],
            stocktake_type="CYCLE_COUNT",status="DRAFT",
            scope_product_variant_id=g.variant["id"],scope_batch_id=counting,
            started_by=g.actor.id,
        ))
        await db.commit()
    count_view=await g.client.get(
        f"/warehouse/batches/{counting}/metadata-correction",
        headers=manager,params={"location_id":location},
    )
    assert count_view.status_code==200,count_view.text
    assert count_view.json()["block_code"]=="BATCH_ACTIVE_STOCKTAKE"

    # #773 LEAD: ACTUAL derived sellability from expired date -> correct FEFO
    # on the same genuine original batch, and quarantine must remain unsellable.
    async def projected_sellable():
        async with AsyncSession(g.admin) as db:
            row=await db.scalar(select(InventoryLiveStockProjection).where(
                InventoryLiveStockProjection.company_id==company,
                InventoryLiveStockProjection.warehouse_location_id==location,
                InventoryLiveStockProjection.product_variant_id==g.variant["id"]))
            assert row is not None
            return Decimal(row.warehouse_sellable_on_hand)

    sellable_before=await projected_sellable()
    ledger_before_projection=await _ledger_signature(g)
    expired={
        "request_id":str(uuid4()),"expected_revision":2,"location_id":location,
        "batch_number":request["batch_number"],
        "production_date":"2024-01-01","expiry_date":"2025-06-30",
        "reason":"Original printed expiry verified expired, quarantine pending",
        "password":PASSWORD,
    }
    expired_reply=await g.client.post(path,headers=manager,json=expired)
    assert expired_reply.status_code==200,expired_reply.text
    assert expired_reply.json()["metadata_revision"]==3
    assert await projected_sellable()==sellable_before-Decimal("8")
    rescue={
        **expired,
        "request_id":str(uuid4()),"expected_revision":3,
        "production_date":"2026-01-03","expiry_date":"2027-09-03",
        "reason":"Verified correct manufacturer expiry on unopened stock",
    }
    rescue_reply=await g.client.post(path,headers=manager,json=rescue)
    assert rescue_reply.status_code==200,rescue_reply.text
    assert rescue_reply.json()["metadata_revision"]==4
    assert await projected_sellable()==sellable_before
    quarantined=await g.client.post(
        f"/warehouse/batches/{batch}/disposition",headers=manager,
        json={"request_id":str(uuid4()),"expected_revision":1,
              "disposition":"QUARANTINED",
              "reason":"Lot proof held pending quality manager clearance"},
    )
    assert quarantined.status_code==200,quarantined.text
    held_projection=await projected_sellable()
    assert held_projection==sellable_before-Decimal("8")
    held_correction=await g.client.post(path,headers=manager,json={
        **rescue,"request_id":str(uuid4()),"expected_revision":4,
        "expiry_date":"2028-09-03",
        "reason":"Correct date while original physical Lot stays quarantined",
    })
    assert held_correction.status_code==200,held_correction.text
    assert held_correction.json()["disposition"]=="QUARANTINED"
    assert await projected_sellable()==held_projection
    assert await _ledger_signature(g)==ledger_before_projection

    print("B773_REAL_PG16_MANAGER_CANONICAL_REAUTH_ORIGINAL_COST_FIFO_NO_MOVEMENT_PASS",flush=True)


async def test_batch_773_moving_average_parallel_reauth_revoke_and_append_only(gate):
    """Separate true company choosing moving average BEFORE its first posted receipt.

    Both requests use real signed manager Bearer and different UUIDs, no mocked
    service/DB or test-only cost layer. Financial rows compared byte-for-byte.
    """
    g=gate
    from sqlalchemy.exc import DBAPIError
    name="B773-MA-"+uuid4().hex[:14]
    async with AsyncSession(g.admin,expire_on_commit=False) as db:
        company=Company(name="B773 moving average standalone",company_code=name,timezone="UTC")
        db.add(company)
        await db.flush()
        tenant_token=tenant_context.set(company.id)
        try:
            await db.execute(text("SELECT set_config('app.current_tenant',:id,true)"),{"id":str(company.id)})
            owner=await seed_company_owner_fixture(db,company.id,password=PASSWORD)
            supplier=await seed_receipt_supplier(db,owner.operational_driver)
            each=await db.scalar(select(UOM.id).where(UOM.code=="EACH"))
            assert each is not None
            product=Product(company_id=company.id,code="B773-MA",name="MA physical product")
            warehouse=InventoryLocation(company_id=company.id,code="B773-MA-WH",
                name="MA warehouse",location_type="WAREHOUSE",
                is_active=True,is_system_managed=False)
            db.add_all([product,warehouse])
            await db.flush()
            variant=ProductVariant(company_id=company.id,product_id=product.id,
                sku="MA-"+uuid4().hex[:8],name="MA product by printed batch",
                base_uom_id=each,packs_per_carton=50,
                lot_control_mode="REQUIRED",expiry_control_mode="REQUIRED",
                lifecycle_status="ACTIVE",
                published_at=__import__("models").utc_now())
            db.add(variant)
            await db.flush()
            c_id=int(company.id)
            warehouse_id=int(warehouse.id)
            variant_id=int(variant.id)
            supplier_id=int(supplier)
            owner_name=await db.scalar(select(__import__("domains.identity.models",
                fromlist=["CompanyPrincipal"]).CompanyPrincipal.username).where(
                __import__("domains.identity.models",
                    fromlist=["CompanyPrincipal"]).CompanyPrincipal.id ==
                owner.context.principal_id,
            ))
            owner_principal_id=int(owner.context.principal_id)
            await db.commit()
        finally:
            tenant_context.reset(tenant_token)

    login=await g.client.post("/login",json={
        "company_code":name,"username":owner_name,"password":PASSWORD,
    })
    assert login.status_code==200,login.text
    manager={"Authorization":"Bearer "+login.json()["token"]}
    policy=await g.client.put("/warehouse/costing-policy",headers=manager,json={
        "request_id":str(uuid4()),"method":"MOVING_AVERAGE","expected_version":0,
    })
    assert policy.status_code==200,policy.text
    assert policy.json()["method"]=="MOVING_AVERAGE"
    original_lot="MA-WRONG-"+uuid4().hex[:10]
    invoice="B773-MA-INV-"+uuid4().hex[:12]
    post=await g.client.post("/warehouse/inbound",headers=manager,json={
        "request_id":str(uuid4()),"supplier_id":supplier_id,
        "location_id":warehouse_id,"reference_id":invoice,
        "items":[{
            "product_variant_id":variant_id,"quantity":"11","uom_id":each,
            "unit_cost":"4.625","batch_number":original_lot,
            "production_date":"2026-01-01","expiry_date":"2027-08-31",
        }],
    })
    assert post.status_code==201,post.text
    async with AsyncSession(g.admin) as db:
        batch_id=await db.scalar(select(ProductBatch.id).where(
            ProductBatch.company_id==c_id,
            ProductBatch.product_variant_id==variant_id,
            ProductBatch.batch_number==original_lot,
        ))
        assert batch_id is not None
        actual_cost=await db.scalar(select(InventoryCostEvent).where(
            InventoryCostEvent.company_id==c_id,
            InventoryCostEvent.batch_id==batch_id,
        ))
        assert actual_cost.method=="MOVING_AVERAGE"
        assert actual_cost.event_type=="PURCHASE_IN"
        assert actual_cost.cost_basis=="PURCHASE_ACTUAL"
    current_path=f"/warehouse/batches/{batch_id}/metadata-correction"
    preview=await g.client.get(current_path,headers=manager,
                               params={"location_id":warehouse_id})
    assert preview.status_code==200,preview.text
    assert preview.json()["eligible"] is True
    assert preview.json()["source_invoice"]==invoice

    tables=(
        "inventory_movements","inventory_balances","inventory_cost_events",
        "inventory_cost_states","inventory_cost_layers","inventory_cost_allocations",
        "inventory_cost_policies",
    )
    async def financial_signature():
        async with AsyncSession(g.admin) as db:
            return {
                table:tuple((await db.scalars(text(
                    "SELECT to_jsonb(t)::text FROM "+table+
                    " t WHERE company_id=:c ORDER BY to_jsonb(t)::text"
                ),{"c":c_id})).all())
                for table in tables
            }

    before=await financial_signature()
    assert len(before["inventory_cost_states"])==1
    # One distinct printed identifier per command; both carry the *same*
    # snapshot revision, demonstrating the real advisory/row lock race.
    race=lambda lot:{
        "request_id":str(uuid4()),"expected_revision":1,
        "location_id":warehouse_id,
        "batch_number":lot,
        "production_date":"2026-01-01","expiry_date":"2027-10-31",
        "reason":"Genuine manufacturer printed label verified at receiving",
        "password":PASSWORD,
    }
    first=race("MA-CORRECT-A-"+uuid4().hex[:7])
    second=race("MA-CORRECT-B-"+uuid4().hex[:7])
    go=asyncio.Event()
    async def send(data):
        await go.wait()
        return await g.client.post(current_path,headers=manager,json=data)
    a,b=asyncio.create_task(send(first)),asyncio.create_task(send(second))
    go.set()
    replies=await asyncio.gather(a,b)
    assert sorted(p.status_code for p in replies)==[200,409],[
        (p.status_code,p.text) for p in replies
    ]
    winner=first if replies[0].status_code==200 else second
    persisted=await g.client.get(current_path,headers=manager,
                                 params={"location_id":warehouse_id})
    assert persisted.status_code==200
    assert persisted.json()["metadata_revision"]==2
    assert persisted.json()["current"]["batch_number"]==winner["batch_number"]
    assert await financial_signature()==before

    # Canonical retry of the winning UUID (same payload) cannot double record.
    replay=await g.client.post(current_path,headers=manager,json=winner)
    assert replay.status_code==200 and replay.json()["metadata_revision"]==2
    history=await g.client.get(
        f"/warehouse/batches/{batch_id}/metadata-corrections/history",
        headers=manager,params={"location_id":warehouse_id},
    )
    assert history.status_code==200,history.text
    assert len(history.json()["items"])==1
    assert history.json()["items"][0]["after"]["batch_number"]==winner["batch_number"]
    assert await financial_signature()==before

    # A request for the same company's other warehouse or a FOREIGN warehouse
    # must NEVER get back this batch's source or events.
    mismatched=await g.client.post(current_path,headers=manager,json={
        **race("MA-FOREIGN-LOC-"+uuid4().hex[:7]),
        "expected_revision":2,"location_id":g.warehouse_id,
    })
    assert mismatched.status_code in (403,404,409),mismatched.text
    assert await financial_signature()==before

    # Runtime role is not allowed to UPDATE or DELETE audit events.
    tenant_token=tenant_context.set(c_id)
    try:
        async with AsyncSession(runtime_engine) as db:
            await db.execute(text("SELECT set_config('app.current_tenant',:id,true)"),
                             {"id":str(c_id)})
            event_id=await db.scalar(select(BatchMetadataCorrectionEvent.id).where(
                BatchMetadataCorrectionEvent.company_id==c_id,
                BatchMetadataCorrectionEvent.batch_id==batch_id,
            ))
            assert event_id
            for sql in (
                "UPDATE batch_metadata_correction_events SET reason='TAMPER' WHERE id=:id",
                "DELETE FROM batch_metadata_correction_events WHERE id=:id",
            ):
                with pytest.raises(DBAPIError):
                    async with db.begin_nested():
                        await db.execute(text(sql),{"id":event_id})
            await db.rollback()
        # Migration/admin role has UPDATE privilege but still cannot bypass
        # the DB trigger: a stronger append-only invariant than RLS alone.
        async with AsyncSession(g.admin) as db:
            await db.execute(text("SELECT set_config('app.current_tenant',:id,true)"),
                             {"id":str(c_id)})
            for sql in (
                "UPDATE batch_metadata_correction_events SET reason='TAMPER' WHERE id=:id",
                "DELETE FROM batch_metadata_correction_events WHERE id=:id",
            ):
                with pytest.raises(DBAPIError,match="append-only"):
                    async with db.begin_nested():
                        await db.execute(text(sql),{"id":event_id})
            await db.rollback()
    finally:
        tenant_context.reset(tenant_token)

    # Signed non-owner BACKOFFICE credentials with company batch.disposition
    # but a warehouse-specific inbound.create grant for a DIFFERENT warehouse
    # must be forbidden for the true source location. Exercises real RLS/role
    # joins and the complete HTTP capability chain, not a fake access object.
    from models import Role, Permission, UserRole, UserLocationAccess, role_permissions
    from domains.identity.models import CompanyPrincipal
    token=tenant_context.set(c_id)
    try:
        async with AsyncSession(g.admin,expire_on_commit=False) as db:
            await db.execute(text("SELECT set_config('app.current_tenant',:id,true)"),{"id":str(c_id)})
            limited=await seed_ordinary_backoffice_fixture(db,c_id,password=PASSWORD)
            limited_name=await db.scalar(select(CompanyPrincipal.username).where(
                CompanyPrincipal.company_id==c_id,
                CompanyPrincipal.id==limited.context.principal_id,
            ))
            other_warehouse=InventoryLocation(company_id=c_id,
                code="MA-SECOND-"+uuid4().hex[:8],
                name="Other warehouse cannot edit supplier receipt",
                location_type="WAREHOUSE",is_active=True,is_system_managed=False)
            company_role=Role(company_id=c_id,name="B773 batch only "+uuid4().hex[:7],
                              is_system_role=False)
            location_role=Role(company_id=c_id,name="B773 other inbound "+uuid4().hex[:7],
                               is_system_role=False)
            db.add_all([other_warehouse,company_role,location_role])
            await db.flush()
            rights=(await db.execute(select(Permission.id,Permission.code).where(
                Permission.code.in_(("batch.disposition","inbound.create"))
            ))).all()
            rights_by_code={code:pid for pid,code in rights}
            assert set(rights_by_code)=={"batch.disposition","inbound.create"}
            await db.execute(role_permissions.insert(),[
                {"company_id":c_id,"role_id":company_role.id,
                 "permission_id":rights_by_code["batch.disposition"]},
                {"company_id":c_id,"role_id":location_role.id,
                 "permission_id":rights_by_code["inbound.create"]},
            ])
            db.add(UserRole(company_id=c_id,driver_id=limited.driver_id,role_id=company_role.id))
            db.add(UserLocationAccess(company_id=c_id,driver_id=limited.driver_id,
                location_id=other_warehouse.id,role_id=location_role.id))
            await db.commit()
            other_wh_id=int(other_warehouse.id)
    finally:
        tenant_context.reset(token)
    scoped_login=await g.client.post("/login",json={
        "company_code":name,"username":limited_name,"password":PASSWORD,
    })
    assert scoped_login.status_code==200,scoped_login.text
    limited_auth={"Authorization":"Bearer "+scoped_login.json()["token"]}
    denied_original=await g.client.post(current_path,headers=limited_auth,json={
        **race("MA-SCOPED-"+uuid4().hex[:7]),"expected_revision":2,
    })
    assert denied_original.status_code==403,denied_original.text
    allowed_other_denied_source=await g.client.get(
        current_path,headers=limited_auth,params={"location_id":other_wh_id},
    )
    assert allowed_other_denied_source.status_code==404,allowed_other_denied_source.text
    assert await financial_signature()==before

    # Test disabling a real canonical manager after login; old token and
    # even correct password must not authenticate a new correction.
    from domains.identity.models import CompanyPrincipal
    async with AsyncSession(g.admin,expire_on_commit=False) as db:
        principal=await db.scalar(select(CompanyPrincipal).where(
            CompanyPrincipal.company_id==c_id,
            CompanyPrincipal.id==owner_principal_id,
        ).with_for_update())
        assert principal is not None
        principal.is_active=False
        principal.auth_revision+=1
        await db.commit()
    revoked=await g.client.post(current_path,headers=manager,json={
        **race("MA-REVOKED-"+uuid4().hex[:7]),
        "expected_revision":2,
    })
    assert revoked.status_code in (401,403),revoked.text
    async with AsyncSession(g.admin) as db:
        count=await db.scalar(select(func.count(BatchMetadataCorrectionEvent.id)).where(
            BatchMetadataCorrectionEvent.company_id==c_id,
            BatchMetadataCorrectionEvent.batch_id==batch_id,
        ))
        assert count==1
    assert await financial_signature()==before
    print("B773_MOVING_AVERAGE_REAL_RECEIPT_RACE_REAUTH_REVOKED_APPEND_ONLY_PASS",flush=True)
