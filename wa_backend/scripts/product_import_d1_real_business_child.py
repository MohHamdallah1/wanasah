"""D1 real committed Sale/Inbound/Route Launch during in-flight Product Import.

This child ONLY runs inside the private 127.0.0.1:55445/d1_mix cluster.
It calls actual business handlers with real sessions, invariants and commits.
No business mocks, no developer source writes. The runner disposes all test data.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import pathlib
import selectors
import subprocess
import sys
import time
from datetime import date,timedelta
from decimal import Decimal
from uuid import uuid4,uuid5,NAMESPACE_URL

import psycopg
from sqlalchemy import select,text
from sqlalchemy.engine import make_url

ROOT=pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
if str(ROOT/"tests") not in sys.path:sys.path.insert(0,str(ROOT/"tests"))
if os.getenv("WANASAH_D1_DISPOSABLE_CHILD")!="1":
    raise RuntimeError("D1 only inside guarded disposable runner")
if "127.0.0.1:55445/d1_mix" not in os.getenv("DATABASE_URL",""):
    raise RuntimeError("D1 wrong database; refusing business writes")

from api.dispatch import dispatch_route
from api.driver import update_visit
from api.warehouse.inbound import warehouse_inbound
from context import tenant_context
from database import AsyncSessionLocal,engine
from domains.simple_products.imports.application.api_service import create_import
from domains.simple_products.imports.infrastructure.repository import (
    open_tenant_session,close_tenant_session
)
from models import Driver,Zone,Vehicle,InventoryLocation
from schemas import DispatchRouteRequest,UpgradedInboundRequest,VisitUpdateRequest
from scripts.run_product_import_phase19_live_load import build_source
from scripts.product_import_business_integrity_gate import _assert_business_evidence
from test_costed_driver_sale_correction_real_c2_db import (
    RealDriverSaleCorrectionC2DatabaseTests
)
from test_costed_driver_customer_return_c2_db import RealCustomerReturnC2DatabaseTests

ROWS=int(os.environ.get("WANASAH_D1_IMPORT_ROWS","3000"))
TERMINAL={"COMPLETED","COMPLETED_WITH_ERRORS","FAILED","CANCELLED","VALIDATION_FAILED"}

def dsn(name):
    return make_url(os.environ[name]).set(
        drivername="postgresql"
    ).render_as_string(hide_password=False)

async def setup_committed_business():
    """Reuse the independently audited real-sale fixture, but COMMIT only in temp PG."""
    token=tenant_context.set(2)
    async with AsyncSessionLocal() as db:
        fixture=RealDriverSaleCorrectionC2DatabaseTests(
            methodName="test_fifo_real_priced_sale_and_authorized_return_correction"
        )
        fixture.tenant=2
        fixture.db=db
        fixture.actor=await db.scalar(select(Driver).where(
            Driver.company_id==2,Driver.is_admin.is_(True),
            Driver.is_active.is_(True)
        ))
        if fixture.actor is None:raise RuntimeError("D1 missing test admin")
        fixture.warehouse_id=await db.scalar(text(
            "SELECT id FROM inventory_locations WHERE company_id=2 "
            "AND location_type='WAREHOUSE' AND is_active=true"
        ))
        fixture.variant=(await db.execute(text(
            "SELECT id,base_uom_id,packs_per_carton FROM product_variants "
            "WHERE company_id=2 AND lifecycle_status='ACTIVE' "
            "AND operational_hold='NONE' AND expiry_control_mode='REQUIRED' "
            "LIMIT 1"
        ))).mappings().one()
        async def d1_compatible_commercial_context(visit_id):
            # The C2-only fixture intentionally installs an offer-exclusive
            # company default; Product Import correctly rejects that policy.
            # Before the fixture's FIRST COMMIT, stage a valid default book
            # assignment compatible with Simple Products. Never alter the
            # production pricing/business rules to appease test data.
            context_id = await fixture._create_real_commercial_context(visit_id)
            from models import PriceBookAssignment
            assignment = await db.scalar(
                select(PriceBookAssignment).where(
                    PriceBookAssignment.company_id == 2,
                    PriceBookAssignment.scope_type == "COMPANY_DEFAULT",
                    PriceBookAssignment.scope_id.is_(None),
                )
            )
            if assignment is None:
                raise RuntimeError("D1 fixture company default assignment missing")
            assignment.allow_offers = True
            await db.flush()
            return context_id

        visit_id,vehicle_location_id,batch_id=(
            await RealCustomerReturnC2DatabaseTests._create_business_fixture(
                fixture,"FIFO",
                commercial_context_factory=d1_compatible_commercial_context,
                second_purchase_price="4",
            )
        )
        # This second driver/vehicle/zone is exclusively for real POST /dispatch/route.
        suffix=uuid4().hex[:8]
        driver=Driver(
            company_id=2, username="D1-DR-"+suffix,
            password_hash=fixture.actor.password_hash,
            full_name="D1 temporary route driver",
            is_admin=False,is_active=True,
            can_allow_debt=False,max_debt_limit=Decimal("0"),
        )
        zone=Zone(company_id=2,name="D1-LAUNCH-"+suffix,is_active=True)
        vehicle=Vehicle(
            company_id=2,plate_number="D1-"+suffix,
            maintenance_status="Active",is_active=True
        )
        db.add_all((driver,zone,vehicle))
        await db.flush()
        location=InventoryLocation(
            company_id=2,name="D1 Temp Vehicle "+suffix,
            code="D1-VH-"+suffix,
            location_type="VEHICLE",vehicle_id=vehicle.id,
            is_active=True,is_system_managed=False,
        )
        db.add(location)
        await db.commit()
        result={
            "actor_id":int(fixture.actor.id),
            "visit_id":int(visit_id),
            "warehouse_id":int(fixture.warehouse_id),
            "variant_id":int(fixture.variant["id"]),
            "base_uom_id":int(fixture.variant["base_uom_id"]),
            "batch_id":int(batch_id),
            "driver_id":int(driver.id),
            "vehicle_id":int(vehicle.id),
            "zone_id":int(zone.id),
        }
    tenant_context.reset(token)
    return result

async def submit_import():
    data,_map,_prefix=build_source(ROWS,"D1-MIXED-COMMITTED")
    token,db=await open_tenant_session(2)
    try:
        result=await create_import(
            db,company_id=2,actor_id=1,
            request_id=uuid5(NAMESPACE_URL,"D1-real-mixed-permanent-"+str(ROWS)),
            file_name="d1-mixed.csv",content_type="text/csv",
            source_stream=io.BytesIO(data),source_size=len(data),
            source_sha256=hashlib.sha256(data).hexdigest(),
            default_lot_control_mode="NONE",
            default_expiry_control_mode="NONE",
        )
        await db.commit()
        return str(result["job_id"])
    finally:
        await close_tenant_session(token,db)

def status(admin,job_id):
    result=admin.execute(
        "SELECT status,processed_rows,failed_rows,total_rows "
        "FROM product_import_jobs WHERE company_id=2 AND id=%s",
        (job_id,)
    ).fetchone()
    return result

def wait_for(admin,job_id,predicate,timeout=90):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        row=status(admin,job_id)
        if row and predicate(row):return row
        time.sleep(0.03)
    raise RuntimeError("D1 wait timeout "+str(status(admin,job_id)))

async def invoke_business(fn):
    token=tenant_context.set(2)
    try:
        async with AsyncSessionLocal() as db:
            actor=await db.scalar(select(Driver).where(
                Driver.company_id==2,Driver.id==1
            ))
            if actor is None:raise RuntimeError("D1 admin not found")
            return await fn(db,actor)
    finally:
        tenant_context.reset(token)

async def real_sale(ident):
    async def call(db,actor):
        payload=VisitUpdateRequest(
            request_id=uuid4(),outcome="Sale",
            cart_items=[{
                "product_variant_id":ident["variant_id"],
                "quantity":0,"packs_quantity":4,
            }],
            returns=[],cash_collected="20.000",
        )
        posted=await update_visit(
            visit_id=ident["visit_id"],payload=payload,
            db=db,current_driver=actor
        )
        if posted["message"]!="Visit updated successfully":
            raise RuntimeError("D1 real Sale did not commit")
        replay=await update_visit(
            visit_id=ident["visit_id"],payload=payload,
            db=db,current_driver=actor
        )
        if replay!=posted:raise RuntimeError("D1 Sale idempotency mismatch")
        return posted
    return await invoke_business(call)

async def real_inbound(ident):
    async def call(db,actor):
        uuid=uuid4()
        req=UpgradedInboundRequest(
            request_id=uuid,location_id=ident["warehouse_id"],
            reference_id="D1-POST-IN-"+uuid.hex[:16],
            items=[{
                "product_variant_id":ident["variant_id"],
                "quantity":"7","uom_id":ident["base_uom_id"],
                "unit_cost":"3.000000",
                "batch_number":"D1-BATCH-"+uuid.hex[:15],
                "production_date":date.today()-timedelta(days=15),
                "expiry_date":date.today()+timedelta(days=850),
            }],
        )
        posted=await warehouse_inbound(
            payload=req,db=db,current_admin=actor
        )
        if posted["message"]!="INBOUND_POSTED":
            raise RuntimeError("D1 real inbound failed")
        again=await warehouse_inbound(
            payload=req,db=db,current_admin=actor
        )
        if again!=posted:raise RuntimeError("D1 inbound idempotency mismatch")
        return posted
    return await invoke_business(call)

async def real_route_launch(ident):
    async def call(db,actor):
        payload=DispatchRouteRequest(
            zone_id=ident["zone_id"],
            driver_id=ident["driver_id"],
            vehicle_id=ident["vehicle_id"],
            source_location_id=ident["warehouse_id"],
            inventory={},
        )
        created=await dispatch_route(
            payload=payload,db=db,current_admin=actor
        )
        if created["message"]!="تم إطلاق خط السير بنجاح":
            raise RuntimeError("D1 real route launch failed")
        if not created.get("commercial_context"):
            raise RuntimeError("D1 route commercial context missing")
        return created
    return await invoke_business(call)

async def main():
    ident=await setup_committed_business()
    admin=psycopg.connect(dsn("DATABASE_URL_MIGRATION"),autocommit=True)
    worker=None
    handle=None
    try:
        # Baseline business calls before any import: real sales/stock/route
        # preconditions are validated in setup; ordinary short reads provide a
        # same-process DB timing reference without consuming the one-shot visit.
        reference=[]
        for _ in range(24):
            t=time.perf_counter()
            await invoke_business(lambda db,actor:db.scalar(text(
                "SELECT count(*) FROM product_variants WHERE company_id=2 "
                "AND lifecycle_status='ACTIVE'"
            )))
            reference.append((time.perf_counter()-t)*1000)

        job_id=await submit_import()
        log=pathlib.Path(os.environ["WANASAH_D1_LOG_DIR"])/"d1_worker.log"
        handle=log.open("w",encoding="utf-8")
        worker=subprocess.Popen([
            sys.executable,"-m",
            "domains.simple_products.imports.infrastructure.worker_cli",
            "--role","execution",
        ],cwd=ROOT,env=os.environ.copy(),
        stdout=handle,stderr=subprocess.STDOUT,text=True)
        if os.getenv("WANASAH_D1_DIAGNOSTIC_ONLY") == "1":
            finished = await asyncio.to_thread(
                wait_for, admin, job_id,
                lambda row: str(row[0]) in TERMINAL, 160,
            )
            error_rows = admin.execute(
                "SELECT status,coalesce(error_code,'') AS code,"
                "left(coalesce(error_message,''),220),count(*) "
                "FROM product_import_rows WHERE company_id=2 AND job_id=%s "
                "GROUP BY 1,2,3 ORDER BY count(*) DESC LIMIT 12",
                (job_id,),
            ).fetchall()
            print("D1_IMPORT_DIAGNOSTIC="+json.dumps({
                "job":list(map(str,finished)),
                "row_errors":[list(map(str,row)) for row in error_rows],
            },separators=(",",":")),flush=True)
            return
        await asyncio.to_thread(
            wait_for,admin,job_id,
            lambda row:str(row[0])=="IMPORTING",90
        )
        results={}
        samples={}
        for name,fn in (
            ("sale",real_sale),
            ("inbound",real_inbound),
            ("route_launch",real_route_launch),
        ):
            before=status(admin,job_id)
            if str(before[0])!="IMPORTING":
                raise RuntimeError("D1 "+name+" did not overlap active import: "+str(before))
            started=time.perf_counter()
            result=await asyncio.wait_for(fn(ident),timeout=25)
            elapsed_ms=(time.perf_counter()-started)*1000
            after=status(admin,job_id)
            results[name]={"latency_ms":round(elapsed_ms,3),
                "import_processed_before":int(before[1] or 0),
                "import_processed_after":int(after[1] or 0),
                "status_after":str(after[0])}
            if name=="route_launch":
                results[name]["route_id"]=int(result["route_id"])
                results[name]["context"]=result["commercial_context"]
            if elapsed_ms>15000:
                raise RuntimeError("D1 "+name+" exceeded bounded business latency")
        final=await asyncio.to_thread(
            wait_for,admin,job_id,
            lambda row:str(row[0]) in TERMINAL,160
        )
        if str(final[0])!="COMPLETED_WITH_ERRORS":
            raise RuntimeError("D1 import result: "+str(final))
        expected=ROWS-(ROWS//100)
        if int(final[1])!=expected:
            error_rows = admin.execute(
                "SELECT status,coalesce(error_code,'') AS code,"
                "left(coalesce(error_message,''),220),count(*) "
                "FROM product_import_rows WHERE company_id=2 AND job_id=%s "
                "GROUP BY 1,2,3 ORDER BY count(*) DESC LIMIT 12",
                (job_id,),
            ).fetchall()
            print("D1_BUSINESS_OPS="+json.dumps(results,separators=(",",":")),
                  flush=True)
            print("D1_IMPORT_ERRORS="+json.dumps(
                [list(map(str,row)) for row in error_rows],
                separators=(",",":")),flush=True)
            raise RuntimeError("D1 import mismatch: "+str(final))
        import_evidence=_assert_business_evidence(admin,job_id,expected)

        # Persisted business evidence: SALE/COGS, Inbound/stock, immutable
        # route pricing authority remain correct after catalog revisions.
        sale=admin.execute(
            "SELECT status,final_amount_due,financial_evidence_version "
            "FROM visits WHERE company_id=2 AND id=%s",
            (ident["visit_id"],)
        ).fetchone()
        if (str(sale[0]),Decimal(sale[1]),int(sale[2]))!=(
            "Completed",Decimal("20"),4
        ):
            raise RuntimeError("D1 Sale financial evidence changed: "+str(sale))
        stock=admin.execute(
            "SELECT count(*) FROM inventory_cost_events e "
            "JOIN inventory_movements m ON m.id=e.inventory_movement_id "
            "AND m.company_id=e.company_id "
            "WHERE e.company_id=2 AND m.reference_type='VISIT_ITEM_OUT' "
            "AND m.reference_id=%s",
            (str(ident["visit_id"]),)
        ).fetchone()[0]
        if int(stock)!=1:
            raise RuntimeError("D1 Sale COGS not exactly once")
        inbound=admin.execute(
            "SELECT count(*) FROM inventory_movements "
            "WHERE company_id=2 AND reference_type='INBOUND_SUPPLIER' "
            "AND reference_id LIKE 'D1-POST-IN-%'"
        ).fetchone()[0]
        if int(inbound)!=1:
            raise RuntimeError("D1 inbound movement not exactly once: "+str(inbound))
        context=admin.execute(
            "SELECT count(*) FROM route_commercial_contexts "
            "WHERE company_id=2 AND dispatch_route_id=%s",
            (results["route_launch"]["route_id"],)
        ).fetchone()[0]
        if int(context)!=1:
            raise RuntimeError("D1 launched route context not immutable/unique")
        negatives=admin.execute(
            "SELECT count(*) FROM inventory_balances "
            "WHERE company_id=2 AND on_hand_quantity<0"
        ).fetchone()[0]
        if int(negatives)!=0:
            raise RuntimeError("D1 negative inventory balance")
        rows=admin.execute(
            "SELECT count(*) FROM procrastinate_jobs "
            "WHERE task_name='wanasah.process_product_import' "
            "AND args->>'job_id'=%s AND status IN ('todo','doing')",
            (job_id,)
        ).fetchone()[0]
        if rows:raise RuntimeError("D1 import has dangling active delivery")
        results["baseline_read_p95_ms"]=round(sorted(reference)[22],3)
        results["import_evidence"]=import_evidence
        results["invoice_cogs_events"]=int(stock)
        results["supplier_inbound_movements"]=int(inbound)
        results["route_context_rows"]=int(context)
        results["negative_balances"]=int(negatives)
        results["actual_imported"]=int(final[1])
        print("D1_REAL_BUSINESS_RESULT="+json.dumps(results,
            ensure_ascii=True,separators=(",",":")),flush=True)
        print("PRODUCT_IMPORT_D1_MIXED_BUSINESS=PASS",flush=True)
    finally:
        if worker is not None and worker.poll() is None:
            worker.terminate()
            try:worker.wait(timeout=12)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
        if handle is not None:handle.close()
        admin.close()
        await engine.dispose()


if __name__=="__main__":
    if sys.platform=="win32":
        asyncio.run(main(),loop_factory=lambda:
            asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:asyncio.run(main())
