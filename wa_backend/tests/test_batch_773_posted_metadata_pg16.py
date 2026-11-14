"""#773 one real signed PG16/Bearer posted-batch correction; no old suite reruns."""
from __future__ import annotations
import os
from datetime import date
from uuid import uuid4
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import engine as runtime_engine
from models import (
    InventoryBalance, InventoryCostEvent, InventoryCostLayer, InventoryCostAllocation,
    InventoryMovement, ProductBatch,
    SystemAuditLog, StocktakeSession, InventoryLock,
)
from domains.inventory_batch_metadata.models import BatchMetadataCorrectionEvent
from tests.test_dispatch_m03_period_postgres import gate, _headers
from tests.test_dispatch_c01_c02_custody_postgres import _login_owner, _ledger_signature
from tests.field_authorization_phase3_fixture import PASSWORD

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

    print("B773_REAL_PG16_MANAGER_CANONICAL_REAUTH_ORIGINAL_COST_FIFO_NO_MOVEMENT_PASS",flush=True)
