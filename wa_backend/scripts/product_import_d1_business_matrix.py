"""D1 repeated real Sale/Inbound/Route Launch A/B while a real import runs."""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import selectors
import subprocess
import sys
import time
from datetime import date,timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import psycopg
from fastapi import FastAPI,Depends
from sqlalchemy import select,text

ROOT=pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
if os.getenv("WANASAH_D1_DISPOSABLE_CHILD")!="1" or (
    "127.0.0.1:55445/d1_mix" not in os.getenv("DATABASE_URL","")
):
    raise RuntimeError("D1 matrix must run only in disposable localhost DB")

from api import dispatch as dispatch_router, driver as driver_router
from api.dependencies import get_current_driver
from api.warehouse import inbound as inbound_router
from context import tenant_context
from database import AsyncSessionLocal,engine,get_db
from models import Driver,Zone,Vehicle,InventoryLocation,Shop,Visit
from scripts import product_import_d1_real_business_child as d1
from scripts.product_import_business_integrity_gate import _assert_business_evidence

COUNT=int(os.getenv("WANASAH_D1_MATRIX_SAMPLES","12"))
if COUNT<8 or COUNT>30:raise RuntimeError("D1 matrix sample size out of bound")


async def seed_business_variants(ident):
    """All 2*COUNT shops/visits and route drivers belong to temporary tenant2."""
    token=tenant_context.set(2)
    try:
        async with AsyncSessionLocal() as db:
            base_visit=await db.scalar(select(Visit).where(
                Visit.company_id==2,Visit.id==ident["visit_id"]
            ))
            if base_visit is None:raise RuntimeError("Base visit absent")
            base_shop=await db.scalar(select(Shop).where(
                Shop.company_id==2,Shop.id==base_visit.shop_id
            ))
            if base_shop is None:raise RuntimeError("Base shop absent")
            visits=[ident["visit_id"]]
            routes=[{
                "driver_id":ident["driver_id"],
                "zone_id":ident["zone_id"],
                "vehicle_id":ident["vehicle_id"],
            }]
            for k in range(2*COUNT):
                suffix=uuid4().hex[:9]
                shop=Shop(
                    company_id=2,
                    name="D1 Matrix Shop "+suffix,
                    zone_id=base_shop.zone_id,
                    current_balance=Decimal("0"),
                    max_debt_limit=Decimal("1000"),
                    tax_jurisdiction_id=base_shop.tax_jurisdiction_id,
                    is_active=True,
                )
                driver=Driver(
                    company_id=2,
                    username="D1-MAT-"+suffix,
                    password_hash="TEST_ONLY_NO_LOGIN",
                    full_name="D1 Matrix Driver",
                    is_admin=False,is_active=True,
                    can_allow_debt=False,max_debt_limit=Decimal("0"),
                )
                zone=Zone(company_id=2,name="D1 Mat Zone "+suffix,is_active=True)
                vehicle=Vehicle(
                    company_id=2,
                    plate_number="D1M"+suffix[:8],
                    maintenance_status="Active",is_active=True,
                )
                db.add_all([shop,driver,zone,vehicle])
                await db.flush()
                visit=Visit(
                    id=2_100_000_000+k,
                    company_id=2,shop_id=shop.id,
                    driver_id=ident["actor_id"],
                    operational_date=date.today(),
                    status="Pending",outcome="Pending",
                )
                location=InventoryLocation(
                    company_id=2,
                    name="D1 Mat Vehicle "+suffix,
                    code="D1M-"+suffix,
                    location_type="VEHICLE",
                    vehicle_id=vehicle.id,
                    is_active=True,is_system_managed=False,
                )
                db.add_all([visit,location])
                await db.flush()
                visits.append(int(visit.id))
                routes.append({
                    "driver_id":int(driver.id),
                    "zone_id":int(zone.id),
                    "vehicle_id":int(vehicle.id),
                })
            await db.commit()
            return visits,routes
    finally:
        tenant_context.reset(token)


def percentile(values, p):
    vals=sorted(values)
    return round(vals[max(0,min(len(vals)-1,int((len(vals)-1)*p)))],3)


def build_real_asgi_client()->httpx.AsyncClient:
    """Keep real FastAPI request validation/handler/commit, stub only test login."""
    app=FastAPI()
    app.include_router(dispatch_router.router)
    app.include_router(driver_router.router)
    app.include_router(inbound_router.router)

    async def tenant_db():
        token=tenant_context.set(2)
        try:
            async with AsyncSessionLocal() as db:
                yield db
        finally:
            tenant_context.reset(token)

    async def synthetic_actor(db=Depends(get_db)):
        actor=await db.scalar(select(Driver).where(
            Driver.company_id==2,Driver.id==1,
            Driver.is_admin.is_(True),Driver.is_active.is_(True),
        ))
        if actor is None:raise RuntimeError("D1 synthetic actor missing")
        return actor

    app.dependency_overrides[get_db]=tenant_db
    app.dependency_overrides[get_current_driver]=synthetic_actor
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://d1-isolated.test",
        timeout=httpx.Timeout(20.0),
    )


async def http_sale(client,ident,visit_id):
    payload={
        "request_id":str(uuid4()),"outcome":"Sale",
        "cart_items":[{
            "product_variant_id":ident["variant_id"],
            "quantity":0,"packs_quantity":4,
        }],
        "returns":[],"cash_collected":"20.000",
    }
    response=await client.put(f"/visits/{visit_id}",json=payload)
    if response.status_code!=200:
        raise RuntimeError(
            f"D1 HTTP Sale status={response.status_code} "
            f"detail={response.text[:230]}"
        )
    retry=await client.put(f"/visits/{visit_id}",json=payload)
    if retry.status_code!=200 or retry.json()!=response.json():
        raise RuntimeError("D1 HTTP Sale idempotent replay contract failed")
    return response.json()


async def http_inbound(client,ident):
    uid=uuid4()
    payload={
        "request_id":str(uid),
        "location_id":ident["warehouse_id"],
        "reference_id":"D1-POST-IN-"+uid.hex[:16],
        "items":[{
            "product_variant_id":ident["variant_id"],
            "quantity":"7","uom_id":ident["base_uom_id"],
            "unit_cost":"3.000000",
            "batch_number":"D1-BATCH-"+uid.hex[:15],
            "production_date":str(date.today()-timedelta(days=15)),
            "expiry_date":str(date.today()+timedelta(days=850)),
        }],
    }
    response=await client.post("/warehouse/inbound",json=payload)
    if response.status_code!=201:
        raise RuntimeError(
            f"D1 HTTP Inbound status={response.status_code} "
            f"detail={response.text[:230]}"
        )
    retry=await client.post("/warehouse/inbound",json=payload)
    if retry.status_code!=201 or retry.json()!=response.json():
        raise RuntimeError("D1 HTTP inbound idempotent replay contract failed")
    return response.json()


async def http_route_launch(client,ident,route):
    payload={
        "zone_id":route["zone_id"],
        "driver_id":route["driver_id"],
        "vehicle_id":route["vehicle_id"],
        "source_location_id":ident["warehouse_id"],
        "inventory":{},
    }
    response=await client.post("/dispatch/route",json=payload)
    if response.status_code!=201:
        raise RuntimeError(
            f"D1 HTTP Route Launch status={response.status_code} "
            f"detail={response.text[:230]}"
        )
    result=response.json()
    if not result.get("commercial_context") or not result.get("route_id"):
        raise RuntimeError("D1 Route Launch missing pinned commercial context")
    return result


async def business_measurement(ident,visits,routes,sample_range,
                               *,client,admin=None,job_id=None):
    results={"sale":[],"inbound":[],"route_launch":[]}
    route_ids=[]
    affected_visits=[]
    importing_overlaps=0
    for n in sample_range:
        for op,fn in (
            ("sale", lambda n=n:http_sale(client,ident,visits[n])),
            ("inbound",lambda:http_inbound(client,ident)),
            ("route_launch",lambda n=n:http_route_launch(
                client,ident,routes[n],
            )),
        ):
            if admin is not None:
                before=d1.status(admin,job_id)
                if str(before[0])!="IMPORTING":
                    raise RuntimeError(
                        f"D1 matrix {op} was not in-flight: {before}"
                    )
            start=time.perf_counter()
            output=await asyncio.wait_for(fn(),timeout=25)
            duration=(time.perf_counter()-start)*1000.0
            if admin is not None:
                importing_overlaps+=1
            if duration>5000:
                raise RuntimeError(
                    f"D1 actual {op} exceeded 5s: {duration:.3f}ms"
                )
            results[op].append(duration)
            if op=="sale":affected_visits.append(int(visits[n]))
            if op=="route_launch":route_ids.append(int(output["route_id"]))
    return results,route_ids,affected_visits,importing_overlaps


async def main():
    ident=await d1.setup_committed_business()
    visits,routes=await seed_business_variants(ident)
    client=build_real_asgi_client()
    baseline,base_routes,base_visits,_=await business_measurement(
        ident,visits,routes,range(COUNT),client=client
    )
    admin=psycopg.connect(d1.dsn("DATABASE_URL_MIGRATION"),autocommit=True)
    worker=None
    handle=None
    try:
        job_id=await d1.submit_import()
        logfile=pathlib.Path(os.environ["WANASAH_D1_LOG_DIR"])/"d1_matrix_worker.log"
        handle=logfile.open("w",encoding="utf-8")
        worker=subprocess.Popen([
            sys.executable,"-m",
            "domains.simple_products.imports.infrastructure.worker_cli",
            "--role","execution",
        ],cwd=ROOT,env=os.environ.copy(),
        stdout=handle,stderr=subprocess.STDOUT,text=True)
        await asyncio.to_thread(
            d1.wait_for,admin,job_id,
            lambda row:str(row[0])=="IMPORTING",90
        )
        busy,busy_routes,busy_visits,overlaps=await business_measurement(
            ident,visits,routes,range(COUNT,2*COUNT),
            client=client,admin=admin,job_id=job_id
        )
        terminal=await asyncio.to_thread(
            d1.wait_for,admin,job_id,
            lambda row:str(row[0]) in d1.TERMINAL,160
        )
        expected=d1.ROWS-(d1.ROWS//100)
        if str(terminal[0])!="COMPLETED_WITH_ERRORS" or int(terminal[1])!=expected:
            raise RuntimeError("D1 mixed matrix import unexpected: "+str(terminal))
        import_evidence=_assert_business_evidence(admin,job_id,expected)
        summary={
            "transport":"httpx.ASGITransport; auth identity fixture only",
            "samples_per_type_per_phase":COUNT,
            "baseline_p95_ms":{},
            "during_p95_ms":{},
            "during_p50_ms":{},
            "p95_ratio":{},
            "imported":expected,
            "business_ops_during_import":overlaps,
            "import_evidence":import_evidence,
        }
        for kind in baseline:
            b=percentile(baseline[kind],.95)
            c=percentile(busy[kind],.95)
            summary["baseline_p95_ms"][kind]=b
            summary["during_p95_ms"][kind]=c
            summary["during_p50_ms"][kind]=percentile(busy[kind],.50)
            summary["p95_ratio"][kind]=round(c/max(b,.001),3)
            if c>max(3000,b*12):
                raise RuntimeError(f"D1 {kind} interactive p95 unacceptable {c}ms")
        all_visits=base_visits+busy_visits
        all_routes=base_routes+busy_routes
        if len(set(all_visits))!=2*COUNT or len(set(all_routes))!=2*COUNT:
            raise RuntimeError("D1 duplicate operation fixture")
        sales=admin.execute(
            "SELECT count(*) FROM visits WHERE company_id=2 "
            "AND id=ANY(%s) AND status='Completed' "
            "AND final_amount_due=20.000 AND financial_evidence_version=4",
            (all_visits,),
        ).fetchone()[0]
        if int(sales)!=2*COUNT:
            raise RuntimeError(f"D1 persisted sale finance mismatch: {sales}")
        cogs=admin.execute(
            "SELECT count(*) FROM inventory_cost_events e "
            "JOIN inventory_movements m ON m.company_id=e.company_id "
            "AND m.id=e.inventory_movement_id "
            "WHERE e.company_id=2 AND m.reference_type='VISIT_ITEM_OUT' "
            "AND m.reference_id=ANY(%s)",
            ([str(v) for v in all_visits],),
        ).fetchone()[0]
        if int(cogs)!=2*COUNT:
            raise RuntimeError(f"D1 real Sale COGS not exactly once: {cogs}")
        inbound=admin.execute(
            "SELECT count(*) FROM inventory_movements "
            "WHERE company_id=2 AND reference_type='INBOUND_SUPPLIER' "
            "AND reference_id LIKE 'D1-POST-IN-%'"
        ).fetchone()[0]
        if int(inbound)!=2*COUNT:
            raise RuntimeError(f"D1 real inbounds not exactly once: {inbound}")
        contexts=admin.execute(
            "SELECT count(*) FROM route_commercial_contexts "
            "WHERE company_id=2 AND dispatch_route_id=ANY(%s)",
            (all_routes,),
        ).fetchone()[0]
        if int(contexts)!=2*COUNT:
            raise RuntimeError(f"D1 missing/duplicate route context {contexts}")
        old_context=admin.execute(
            "SELECT price_publication_revision "
            "FROM route_commercial_contexts WHERE company_id=2 "
            "AND dispatch_route_id=(SELECT id FROM dispatch_routes "
            "WHERE company_id=2 AND driver_id=1 LIMIT 1)"
        ).fetchone()
        if old_context is None or int(old_context[0])!=1:
            raise RuntimeError("D1 older route price revision was rewritten")
        stock_neg=admin.execute(
            "SELECT count(*) FROM inventory_balances "
            "WHERE company_id=2 AND on_hand_quantity<0"
        ).fetchone()[0]
        if int(stock_neg):
            raise RuntimeError("D1 negative inventory balances")
        summary.update({
            "sales_finance_rows":int(sales),
            "unique_sale_cogs":int(cogs),
            "inbound_movements":int(inbound),
            "route_context_rows":int(contexts),
            "prior_route_price_revision":int(old_context[0]),
            "negative_stock_balances":int(stock_neg),
        })
        print("D1_MATRIX="+json.dumps(summary,separators=(",",":")),
              flush=True)
        print("PRODUCT_IMPORT_D1_BUSINESS_MATRIX=PASS",flush=True)
    finally:
        if worker is not None and worker.poll() is None:
            worker.terminate()
            try:worker.wait(timeout=12)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
        if handle:handle.close()
        admin.close()
        await client.aclose()
        await engine.dispose()


if __name__=="__main__":
    if sys.platform=="win32":
        asyncio.run(main(),loop_factory=lambda:
            asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:
        asyncio.run(main())
