"""D7-L: 1,000 near-simultaneous mixed arrivals, bounded actual ASGI admission.

NO live data: guarded 127.0.0.1:55445/d1_mix disposable clone only.
Test-only identity header substitutes login, not authorization/domain logic.
"""
from __future__ import annotations

import asyncio
from collections import Counter, defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date,timedelta
from decimal import Decimal
import hashlib
import io
import json
import os
import pathlib
import random
import selectors
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import psutil
import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy import select,text

ROOT=pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
if os.getenv("WANASAH_D7_DISPOSABLE_CHILD")!="1" or (
    "127.0.0.1:55445/d1_mix" not in os.getenv("DATABASE_URL","")
):
    raise RuntimeError("D7 refuses any non-disposable DB")
N=int(os.getenv("WANASAH_D7_REQUESTS","100"))
if N not in (100,500,1000):raise RuntimeError("D7 allowed request counts: 100,500,1000")
S=N//100
ADMISSION_LIMIT=int(os.getenv("WANASAH_D7_CLIENT_INFLIGHT","10"))
if ADMISSION_LIMIT<1 or ADMISSION_LIMIT>100 or ADMISSION_LIMIT>N:
    raise RuntimeError("D7 client concurrency must be in 1..min(100,N)")
SLO_READ_P95_MS=3000
SLO_WRITE_P95_MS=5000
SLO_WRITE_P99_MS=10000
SLO_TOTAL_BURST_S=120
SLO_TERMINAL_S=240

from api import dispatch as dispatch_api,driver as driver_api
from api import simple_products as catalog_api
from api.dependencies import get_current_driver
from api.warehouse import inbound as inbound_api
from context import tenant_context
from database import AsyncSessionLocal,engine,get_db
from domains.simple_products.imports.api import router as imports_api
from domains.simple_products.imports.application.api_service import create_import
from domains.simple_products.imports.infrastructure.queue import DEFAULT_PRODUCT_IMPORT_ADMISSION_POLICY
from domains.simple_products.imports.infrastructure.repository import (
    open_tenant_session,close_tenant_session,
)
from models import Driver
from scripts import product_import_d1_real_business_child as d1
from scripts import product_import_d1_business_matrix as matrix
from scripts.run_product_import_phase19_live_load import build_source

COUNTS={
    "catalog":58*S,
    "owned_status":20*S,
    "foreign_status":6*S,
    "sale":3*S,
    "inbound":4*S,
    "route":3*S,
    "import":2*S,
    "import_replay":2*S,
    "sale_replay":S,
    "inbound_replay":S,
}
assert sum(COUNTS.values())==N
WRITES={"sale","inbound","route","import",
        "sale_replay","inbound_replay","import_replay"}
EXPECT={
    "catalog":200,"owned_status":200,"foreign_status":404,
    "sale":200,"inbound":201,"route":201,"import":202,
    "import_replay":202,"sale_replay":200,"inbound_replay":201,
}
TERMINAL={"COMPLETED","COMPLETED_WITH_ERRORS","FAILED",
          "CANCELLED","VALIDATION_FAILED","NEEDS_MAPPING"}


def pct(values,p):
    if not values:return None
    s=sorted(values)
    return round(float(s[min(len(s)-1,max(0,int((len(s)-1)*p)))]),2)


def headers(company_id):
    return {"X-D7-Fixture-Tenant":str(company_id)}


def build_client():
    app=FastAPI()
    for router in (
        catalog_api.router,imports_api,
        dispatch_api.router,driver_api.router,inbound_api.router,
    ):
        app.include_router(router)

    def tenant_of(request):
        value=request.headers.get("x-d7-fixture-tenant")
        if value not in {"2","3"}:raise HTTPException(403,"D7 synthetic identity denied")
        return int(value)

    async def tenant_db(request:Request):
        company=tenant_of(request)
        token=tenant_context.set(company)
        try:
            async with AsyncSessionLocal() as db:
                yield db
        finally:
            tenant_context.reset(token)

    async def actor_fixture(request:Request,db=Depends(get_db)):
        company=tenant_of(request)
        actor_id=1 if company==2 else 2
        actor=await db.scalar(select(Driver).where(
            Driver.company_id==company,Driver.id==actor_id,
            Driver.is_active.is_(True),Driver.is_admin.is_(True),
        ))
        if actor is None:raise HTTPException(403,"Synthetic actor not available")
        return actor

    app.dependency_overrides[get_db]=tenant_db
    app.dependency_overrides[get_current_driver]=actor_fixture
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://d7-local-asgi.test",
        timeout=httpx.Timeout(22.0),
    )


async def seed_import(company,label,rows):
    data,_mapping,_prefix=build_source(rows,label)
    actor=1 if company==2 else 2
    token,db=await open_tenant_session(company)
    try:
        job=await create_import(
            db,company_id=company,actor_id=actor,request_id=uuid4(),
            file_name=label+".csv",content_type="text/csv",
            source_stream=io.BytesIO(data),source_size=len(data),
            source_sha256=hashlib.sha256(data).hexdigest(),
            default_lot_control_mode="NONE",default_expiry_control_mode="NONE",
        )
        await db.commit()
        return str(job["job_id"]),rows-rows//100
    finally:
        await close_tenant_session(token,db)


def import_state(admin,job_id):
    return admin.execute(
        "SELECT status,processed_rows,failed_rows FROM product_import_jobs "
        "WHERE id=%s",(job_id,)
    ).fetchone()


async def tenant_rls_proof():
    for owner,foreign in ((2,3),(3,2)):
        token=tenant_context.set(owner)
        try:
            async with AsyncSessionLocal() as db:
                n=await db.scalar(text(
                    "SELECT count(*) FROM product_import_jobs "
                    "WHERE company_id=:foreign"
                ),{"foreign":foreign})
                if int(n or 0)!=0:
                    raise RuntimeError("D7 cross-tenant business job visible through RLS")
        finally:
            tenant_context.reset(token)
    return True


def read_import_evidence(admin,job_id,company,expected):
    record=admin.execute("""
        SELECT status,processed_rows,failed_rows,source_payload_cleared_at
        FROM product_import_jobs WHERE id=%s AND company_id=%s
    """,(job_id,company)).fetchone()
    if record is None or str(record[0]) not in {"COMPLETED","COMPLETED_WITH_ERRORS"}:
        raise RuntimeError("D7 import failed to complete")
    if int(record[1])!=expected or record[3] is None:
        raise RuntimeError("D7 import processed/source mismatch")
    ids=[int(v[0]) for v in admin.execute("""
        SELECT product_variant_id FROM product_import_rows
        WHERE job_id=%s AND company_id=%s AND status='IMPORTED'
        ORDER BY row_number
    """,(job_id,company)).fetchall()]
    if len(ids)!=expected or len(set(ids))!=expected:
        raise RuntimeError("D7 import variant lineage duplicates/loss")
    variant_count=int(admin.execute(
        "SELECT count(*) FROM product_variants WHERE company_id=%s AND id=ANY(%s)",
        (company,ids),
    ).fetchone()[0])
    pricing_count=int(admin.execute("""
        SELECT count(DISTINCT product_variant_id)
        FROM price_book_entries
        WHERE company_id=%s AND product_variant_id=ANY(%s) AND is_published IS TRUE
    """,(company,ids)).fetchone()[0])
    text_ids=[str(i) for i in ids]
    audits=admin.execute("""
        SELECT count(*),count(DISTINCT entity_id) FROM domain_audit_events
        WHERE company_id=%s AND entity_type='ProductVariant'
        AND entity_id=ANY(%s)
    """,(company,text_ids)).fetchone()
    outbox=admin.execute("""
        SELECT count(*),count(DISTINCT aggregate_id) FROM transactional_outbox
        WHERE company_id=%s AND aggregate_type='ProductVariant'
        AND aggregate_id=ANY(%s)
    """,(company,text_ids)).fetchone()
    if variant_count!=expected or pricing_count!=expected or (
        tuple(map(int,audits))!=(expected,expected)
        or tuple(map(int,outbox))!=(expected,expected)
    ):
        raise RuntimeError("D7 imported product/price/audit/outbox counts differ")
    invalid=int(admin.execute("""
        SELECT count(*) FROM product_import_rows
        WHERE company_id=%s AND job_id=%s AND status='INVALID'
    """,(company,job_id)).fetchone()[0])
    if invalid!=int(record[2]):
        raise RuntimeError("D7 invalid source count mismatch")
    return {"company":company,"imported":expected,"invalid":invalid}


async def main():
    if psutil.virtual_memory().available < 700*1024*1024:
        raise RuntimeError("D7 workstation RAM below safe private-cluster limit")
    ident=await d1.setup_committed_business()
    visits,routes=await matrix.seed_business_variants(ident)
    client=build_client()
    admin=psycopg.connect(d1.dsn("DATABASE_URL_MIGRATION"),autocommit=True)
    workers={}
    handles={}
    jobs=[]
    data_by_import={}
    try:
        # Before starting workers, establish a real, deterministic FIFO
        # cross-tenant contention order, plus exact import-status targets.
        for company,label,count in (
            (2,"D7-BASE-2A-LONG",1200),
            (2,"D7-BASE-2B-LONG",800),
            (3,"D7-BASE-3A-SHORT",100),
        ):
            jid,valid=await seed_import(company,label,count)
            jobs.append((company,jid,valid,label))
        base_status={2:jobs[0][1],3:jobs[2][1]}
        catalog_baseline=[]
        for i in range(20):
            began=time.perf_counter()
            rsp=await client.get("/simple-products?limit=10",headers=headers(2 if i%2==0 else 3))
            if rsp.status_code!=200:
                raise RuntimeError("D7 preflight catalog failed "+str(rsp.status_code))
            catalog_baseline.append((time.perf_counter()-began)*1000)

        # Seed distinct one-shot authoritative business identities. Visit/
        # route ids are not shared between writes, preventing fixture races
        # that would masquerade as application lock contention.
        if len(visits)<31 or len(routes)<31:
            raise RuntimeError("D7 business seed under-provisioned")
        sale_payloads={}
        inbound_payloads={}
        route_payloads={}
        for i in range(COUNTS["sale"]):
            sale_payloads[i]={
                "request_id":str(uuid4()),"outcome":"Sale",
                "cart_items":[{
                    "product_variant_id":ident["variant_id"],
                    "quantity":0,"packs_quantity":4,
                }],
                "returns":[],"cash_collected":"20.000",
            }
        for i in range(COUNTS["inbound"]):
            rid=uuid4()
            inbound_payloads[i]={
                "request_id":str(rid),
                "location_id":ident["warehouse_id"],
                "reference_id":"D7-IN-"+rid.hex[:16],
                "items":[{
                    "product_variant_id":ident["variant_id"],
                    "quantity":"7","uom_id":ident["base_uom_id"],
                    "unit_cost":"3.000000",
                    "batch_number":"D7-IN-LOT-"+rid.hex[:14],
                    "production_date":str(date.today()-timedelta(days=15)),
                    "expiry_date":str(date.today()+timedelta(days=850)),
                }],
            }
        for i in range(COUNTS["route"]):
            route=routes[i+1]
            route_payloads[i]={
                **route,"source_location_id":ident["warehouse_id"],
                "inventory":{},
            }
        for i in range(COUNTS["import"]):
            company=2 if i%2==0 else 3
            label=f"D7-UP-{company}-{i}-{uuid4().hex[:7]}"
            rows=75 if i%2 else 100
            payload,_mapping,_prefix=build_source(rows,label)
            data_by_import[i]=(company,str(uuid4()),label,payload,rows-rows//100)

        records={}
        completion={}
        route_results={}
        record_errors=[]
        policy_denied_unique=[]
        # A rejected original can legitimately be admitted on its replay
        # when the unchanged rolling quota window expires mid-burst.
        replay_first_admitted={}
        specs=[]
        # Data requests are actual HTTP GETs, not fake health/probe counters.
        for i in range(COUNTS["catalog"]):
            tenant=2 if i%2==0 else 3
            specs.append(("catalog",tenant,i,None))
        for i in range(COUNTS["owned_status"]):
            tenant=2 if i%2==0 else 3
            specs.append(("owned_status",tenant,i,base_status[tenant]))
        for i in range(COUNTS["foreign_status"]):
            tenant=2 if i%2==0 else 3
            specs.append(("foreign_status",tenant,i,base_status[3 if tenant==2 else 2]))
        for kind,count in (
            ("sale",COUNTS["sale"]),("inbound",COUNTS["inbound"]),
            ("route",COUNTS["route"]),("import",COUNTS["import"]),
        ):
            for i in range(count):
                company=2 if kind!="import" else data_by_import[i][0]
                specs.append((kind,company,i,None))
        for kind,count in (
            ("sale_replay",COUNTS["sale_replay"]),
            ("inbound_replay",COUNTS["inbound_replay"]),
            ("import_replay",COUNTS["import_replay"]),
        ):
            for i in range(count):
                company=2 if kind!="import_replay" else data_by_import[i][0]
                specs.append((kind,company,i,None))
        if len(specs)!=N:raise RuntimeError("D7 wrong burst composition")
        random.Random(7931).shuffle(specs)

        async def request(kind,company,index,foreign_id):
            hdr=headers(company)
            if kind=="catalog":
                return await client.get("/simple-products?limit=10",headers=hdr)
            if kind in ("owned_status","foreign_status"):
                return await client.get(
                    "/simple-products/imports/"+str(foreign_id),headers=hdr,
                )
            if kind in ("sale","sale_replay"):
                return await client.put(
                    "/visits/"+str(visits[index+1]),
                    headers=hdr,json=sale_payloads[index],
                )
            if kind in ("inbound","inbound_replay"):
                return await client.post(
                    "/warehouse/inbound",headers=hdr,json=inbound_payloads[index],
                )
            if kind=="route":
                return await client.post(
                    "/dispatch/route",headers=hdr,json=route_payloads[index],
                )
            if kind in ("import","import_replay"):
                _,rid,label,blob,_valid=data_by_import[index]
                return await client.post(
                    "/simple-products/imports",headers=hdr,
                    data={
                        "request_id":rid,
                        "default_lot_control_mode":"NONE",
                        "default_expiry_control_mode":"NONE",
                    },
                    files={"file":(label+".csv",blob,"text/csv")},
                )
            raise RuntimeError("Unknown D7 workload category")

        barrier=asyncio.Event()
        sem=asyncio.Semaphore(ADMISSION_LIMIT)
        first_finished={
            (kind,i):asyncio.Event()
            for kind in ("sale","inbound","import")
            for i in range(COUNTS[kind])
        }
        pending=0
        admitted=0
        max_admitted=0
        begin_wall=None

        async def run_one(spec):
            nonlocal admitted,max_admitted,pending
            kind,company,index,foreign_id=spec
            await barrier.wait()
            released=begin_wall
            origin=kind.removesuffix("_replay")
            if kind.endswith("_replay"):
                await first_finished[(origin,index)].wait()
            queued=time.perf_counter()
            async with sem:
                admitted+=1
                max_admitted=max(max_admitted,admitted)
                started=time.perf_counter()
                try:
                    response=await asyncio.wait_for(
                        request(kind,company,index,foreign_id),timeout=22
                    )
                    code=int(response.status_code)
                    if code!=EXPECT[kind] and not (
                        kind in {"import","import_replay"} and code==429
                    ):
                        raise RuntimeError(
                            f"HTTP {kind} tenant={company} code={code}"
                        )
                    result=response.json()
                    if code==429:
                        reason=result.get("detail",{})
                        retry_after=response.headers.get("retry-after")
                        if (
                            not isinstance(reason,dict)
                            or reason.get("code")!="PRODUCT_IMPORT_USER_RATE_LIMITED"
                            or not retry_after
                            or int(retry_after)<=0
                        ):
                            raise RuntimeError(
                                "D7 returned unrecognized/non-retryable 429"
                            )
                    if kind=="owned_status":
                        if str(result.get("job_id"))!=foreign_id:
                            raise RuntimeError("D7 own status wrong job")
                    if kind=="foreign_status":
                        # Never expose even a job state for other tenants.
                        if str(foreign_id) in response.text:
                            raise RuntimeError("D7 foreign job identifier leaked")
                    if kind=="route":
                        if not result.get("route_id") or not result.get("commercial_context"):
                            raise RuntimeError("D7 Route Launch missing immutable context")
                        route_results[index]=result
                    if kind in ("sale","sale_replay","inbound","inbound_replay"):
                        if kind.endswith("_replay") and result!=completion[(origin,index)]:
                            raise RuntimeError("D7 idempotent business replay changed")
                    if kind=="import":
                        if code==429:
                            policy_denied_unique.append((company,index))
                        else:
                            if result.get("replayed") or not result.get("job_id"):
                                raise RuntimeError("D7 fresh import should not replay")
                            company_id=data_by_import[index][0]
                            valid=data_by_import[index][4]
                            jobs.append((company_id,str(result["job_id"]),valid,
                                         data_by_import[index][2]))
                    if kind=="import_replay":
                        original=completion[("import",index)]
                        if original.get("detail",{}).get("code")=="PRODUCT_IMPORT_USER_RATE_LIMITED":
                            if code==202:
                                # No business job was ever created by the
                                # original 429. This is the FIRST legitimate
                                # admission, not an idempotent replay.
                                if result.get("replayed") or not result.get("job_id"):
                                    raise RuntimeError("D7 first admission after 429 not fresh")
                                if (company,index) in replay_first_admitted:
                                    raise RuntimeError("D7 admission recorded twice")
                                replay_first_admitted[(company,index)]=str(result["job_id"])
                                _tenant,_rid,_label,_source,valid=data_by_import[index]
                                jobs.append((company,str(result["job_id"]),valid,_label))
                            elif code!=429:
                                raise RuntimeError("D7 denied replay returned unexpected status")
                        elif (
                            code!=202 or not result.get("replayed")
                            or str(result.get("job_id"))!=str(original["job_id"])
                        ):
                            raise RuntimeError("D7 replay created a new job")
                    if kind in ("sale","inbound","import"):
                        completion[(kind,index)]=result
                    records.setdefault(kind,[]).append({
                        "company":company,"status":code,
                        "service_ms":(time.perf_counter()-started)*1000,
                        "wait_ms":(started-queued)*1000,
                        "arrival_ms":(time.perf_counter()-released)*1000,
                    })
                except Exception as exc:
                    record_errors.append({
                        "kind":kind,"company":company,
                        "error_type":type(exc).__name__,
                        "detail":str(exc)[:170],
                    })
                finally:
                    admitted-=1
                    if kind in ("sale","inbound","import"):
                        first_finished[(kind,index)].set()

        # Start all three genuine role-isolated workers.
        for role in ("control","maintenance","execution"):
            logfile=pathlib.Path(os.environ["WANASAH_D1_LOG_DIR"])/("d7-"+role+".log")
            handle=logfile.open("w",encoding="utf-8")
            handles[role]=handle
            workers[role]=subprocess.Popen([
                sys.executable,"-m",
                "domains.simple_products.imports.infrastructure.worker_cli",
                "--role",role,
            ],cwd=ROOT,env=os.environ.copy(),stdout=handle,
                stderr=subprocess.STDOUT,text=True)
        await asyncio.to_thread(
            d1.wait_for,admin,jobs[0][1],
            lambda r:str(r[0])=="IMPORTING",90,
        )
        await tenant_rls_proof()
        stop_monitor=asyncio.Event()
        max_app_conns=0
        max_total_conns=0
        max_import_doing=0
        oldest_observed_queue_age_seconds=0.0
        min_memory_available_bytes=psutil.virtual_memory().available
        sampled_cpu_percent=[]
        cross_overlap=False
        same_company_double=False
        terminal_offsets={}
        blocked_samples=0
        blocked_observations=Counter()
        longest_blocked_active_query_ms=0.0
        sample_count=0
        start_import=time.perf_counter()
        wal_before=int(admin.execute("SELECT wal_bytes FROM pg_stat_wal").fetchone()[0])

        async def monitor():
            nonlocal max_app_conns,max_total_conns,max_import_doing
            nonlocal oldest_observed_queue_age_seconds,min_memory_available_bytes
            nonlocal cross_overlap,same_company_double,blocked_samples,sample_count
            nonlocal longest_blocked_active_query_ms
            while not stop_monitor.is_set():
                activity=admin.execute("""
                    SELECT count(*),count(*) FILTER (WHERE usename='wanasah_app'),
                           count(*) FILTER (
                             WHERE cardinality(pg_blocking_pids(pid))>0
                           )
                    FROM pg_stat_activity WHERE datname=current_database()
                """).fetchone()
                max_total_conns=max(max_total_conns,int(activity[0]))
                max_app_conns=max(max_app_conns,int(activity[1]))
                blocked_samples+=int(activity[2])
                if int(activity[2])>0:
                    # Attribution only: no raw SQL, user data or credentials
                    # leave the private DB. query_start age includes CPU and
                    # admission time: do NOT present it as lock-wait duration.
                    for wait_type,wait_name,lock_type,relation,age_ms in admin.execute("""
                        SELECT
                            COALESCE(a.wait_event_type,'unknown'),
                            COALESCE(a.wait_event,'unknown'),
                            COALESCE(l.locktype,'unknown'),
                            COALESCE(l.relation::regclass::text,'unresolved'),
                            GREATEST(0,EXTRACT(EPOCH FROM
                              clock_timestamp()-a.query_start)*1000)
                        FROM pg_stat_activity a
                        LEFT JOIN LATERAL (
                            SELECT locktype,relation
                            FROM pg_locks WHERE pid=a.pid AND granted=false
                            ORDER BY locktype LIMIT 1
                        ) l ON TRUE
                        WHERE a.datname=current_database()
                          AND cardinality(pg_blocking_pids(a.pid))>0
                        LIMIT 20
                    """):
                        label="/".join(map(str,(
                            wait_type,wait_name,lock_type,relation
                        )))
                        blocked_observations[label]+=1
                        longest_blocked_active_query_ms=max(
                            longest_blocked_active_query_ms,float(age_ms or 0)
                        )
                ids=[jid for _c,jid,_n,_label in jobs]
                queue_rows=admin.execute("""
                    SELECT status,lock,
                        CASE WHEN status='todo'
                        THEN GREATEST(0,EXTRACT(EPOCH FROM
                            clock_timestamp()-scheduled_at))
                        ELSE 0 END AS queue_age_seconds
                    FROM procrastinate_jobs
                    WHERE task_name='wanasah.process_product_import'
                      AND args->>'job_id'=ANY(%s)
                      AND status IN ('todo','doing')
                """,(ids,)).fetchall()
                busy=[
                    str(lock) for status,lock,_age in queue_rows
                    if str(status)=="doing"
                ]
                oldest_observed_queue_age_seconds=max(
                    oldest_observed_queue_age_seconds,
                    max(
                        (float(age or 0) for _status,_lock,age in queue_rows),
                        default=0.0,
                    ),
                )
                max_import_doing=max(max_import_doing,len(busy))
                if busy.count("product-import:2")>1 or busy.count("product-import:3")>1:
                    same_company_double=True
                if "product-import:2" in busy and "product-import:3" in busy:
                    cross_overlap=True
                snapshots=admin.execute("""
                    SELECT id::text,status FROM product_import_jobs
                    WHERE id::text=ANY(%s)
                """,(ids,)).fetchall()
                for jid,status in snapshots:
                    if str(status) in TERMINAL:
                        terminal_offsets.setdefault(jid,time.perf_counter()-start_import)
                min_memory_available_bytes=min(
                    min_memory_available_bytes,
                    psutil.virtual_memory().available,
                )
                sampled_cpu_percent.append(psutil.cpu_percent(interval=None))
                sample_count+=1
                await asyncio.sleep(.12)

        watch=asyncio.create_task(monitor())
        begin_wall=time.perf_counter()
        tasks=[asyncio.create_task(run_one(spec)) for spec in specs]
        barrier.set()
        try:
            await asyncio.wait_for(asyncio.gather(*tasks),timeout=SLO_TOTAL_BURST_S)
            burst_seconds=time.perf_counter()-begin_wall
            if record_errors:
                raise RuntimeError("D7 HTTP errors="+json.dumps(record_errors[:8]))
            if sum(map(len,records.values()))!=N:
                raise RuntimeError("D7 unaccounted burst requests")
            # Quotas use a real rolling window. If 1,000 requests and
            # quota retries cross the 60-second boundary, a previously
            # rejected request can legitimately become admitted IN the
            # measured burst. Never assert a fixed denial count based only
            # on number of arrivals; assert the actual rolling invariant.
            rejected_attempts=sum(
                row["status"]==429
                for kind in ("import","import_replay")
                for row in records.get(kind,[])
            )
            denial_rows=int(admin.execute("""
                SELECT count(*) FROM product_import_admission_rejections
                WHERE company_id IN (2,3)
                  AND code='PRODUCT_IMPORT_USER_RATE_LIMITED'
            """).fetchone()[0])
            if denial_rows!=rejected_attempts:
                raise RuntimeError(
                    "D7 durable admission denial telemetry mismatch "
                    +str(denial_rows)+" != "+str(rejected_attempts)
                )
            for company,index in policy_denied_unique:
                request_id=data_by_import[index][1]
                existing=admin.execute("""
                    SELECT id::text FROM product_import_jobs
                    WHERE company_id=%s AND request_id=%s
                """,(company,request_id)).fetchall()
                expected=[replay_first_admitted[(company,index)]] if (
                    company,index
                ) in replay_first_admitted else []
                if [jid for (jid,) in existing]!=expected:
                    raise RuntimeError(
                        "D7 denied upload wrote an unexpected business job"
                    )

            # Delayed retries are beyond the 1,000 measured arrivals.
            # Request ID + source bytes never change. Replayed after first
            # admission must return the same job, never create a second.
            retry_attempts=0
            admitted_during_initial_replay=len(replay_first_admitted)
            recovered_from_limit=len(replay_first_admitted)
            for company,index in policy_denied_unique:
                if (company,index) in replay_first_admitted:
                    continue
                delayed_deadline=time.monotonic()+135
                while time.monotonic()<delayed_deadline:
                    retry_attempts+=1
                    attempt=await asyncio.wait_for(
                        request("import",company,index,None),timeout=22
                    )
                    if attempt.status_code==202:
                        payload=attempt.json()
                        if payload.get("replayed") or not payload.get("job_id"):
                            raise RuntimeError("D7 delayed first admission not fresh")
                        _,_key,label,_blob,valid=data_by_import[index]
                        jobs.append((company,str(payload["job_id"]),valid,label))
                        recovered_from_limit+=1
                        replay_first_admitted[(company,index)]=str(payload["job_id"])
                        break
                    if (
                        attempt.status_code!=429
                        or attempt.json().get("detail",{}).get("code")
                        !="PRODUCT_IMPORT_USER_RATE_LIMITED"
                    ):
                        raise RuntimeError("D7 delayed admission unexpected error")
                    pause=int(attempt.headers.get("retry-after","0"))
                    if pause<=0:raise RuntimeError("D7 429 missing Retry-After")
                    await asyncio.sleep(min(pause,30))
                else:
                    raise RuntimeError("D7 delayed admission failed after retry")
            if recovered_from_limit!=len(policy_denied_unique):
                raise RuntimeError("D7 admission recovery did not account for every denial")
            # Every newly admitted request must now be a stable replay.
            for company,index in policy_denied_unique:
                attempt=await asyncio.wait_for(
                    request("import_replay",company,index,None),timeout=22
                )
                evidence=attempt.json()
                if (
                    attempt.status_code!=202 or not evidence.get("replayed")
                    or str(evidence.get("job_id"))
                    !=replay_first_admitted[(company,index)]
                ):
                    raise RuntimeError("D7 admitted request replay produced a duplicate job")
            if len(jobs)!=len({job_id for _c,job_id,_valid,_lbl in jobs}):
                raise RuntimeError("D7 duplicate Product Import job identity")
            policy=DEFAULT_PRODUCT_IMPORT_ADMISSION_POLICY
            if (
                policy.max_uploads_per_user_window!=10
                or policy.user_window_seconds!=60
            ):
                raise RuntimeError("D7 reviewed 10/60s policy unexpectedly modified")
            admitted=admin.execute("""
                SELECT company_id,created_by,created_at,id::text
                FROM product_import_jobs
                WHERE company_id IN (2,3)
                ORDER BY company_id,created_by,created_at,id
            """).fetchall()
            by_actor=defaultdict(deque)
            max_rolling_admissions=0
            for tenant,actor,created_at,jid in admitted:
                history=by_actor[(int(tenant),int(actor))]
                while history and (
                    created_at-history[0]
                ).total_seconds()>policy.user_window_seconds:
                    history.popleft()
                history.append(created_at)
                max_rolling_admissions=max(max_rolling_admissions,len(history))
                if len(history)>policy.max_uploads_per_user_window:
                    raise RuntimeError("D7 Product Import rolling quota violated")
            deadline=time.monotonic()+SLO_TERMINAL_S
            while time.monotonic()<deadline:
                ids=[jid for _c,jid,_v,_label in jobs]
                rows=admin.execute("""
                    SELECT id::text,status FROM product_import_jobs
                    WHERE id::text=ANY(%s)
                """,(ids,)).fetchall()
                if len(rows)==len(ids) and all(str(row[1]) in TERMINAL for row in rows):
                    break
                for role,p in workers.items():
                    if p.poll() is not None:
                        raise RuntimeError("D7 "+role+" worker exited prematurely")
                await asyncio.sleep(.15)
            else:
                raise RuntimeError("D7 import terminal timeout")
            await asyncio.sleep(.15)
        finally:
            stop_monitor.set()
            await watch
        wal_delta=int(admin.execute("SELECT wal_bytes FROM pg_stat_wal").fetchone()[0])-wal_before
        if max_admitted>ADMISSION_LIMIT:
            raise RuntimeError("D7 client admission bound violated")
        if max_app_conns>28 or max_total_conns>60 or max_import_doing>2:
            raise RuntimeError("D7 reviewed DB/worker budget exceeded")
        if not cross_overlap or same_company_double:
            raise RuntimeError("D7 tenant worker fairness/serialization violated")
        if not (
            terminal_offsets.get(jobs[2][1],float("inf"))
            <terminal_offsets.get(jobs[1][1],-1)
        ):
            raise RuntimeError("D7 independent short job was starved behind long same-tenant job")

        per_kind={}
        for kind,values in records.items():
            service=[v["service_ms"] for v in values]
            queue=[v["wait_ms"] for v in values]
            arrival=[v["arrival_ms"] for v in values]
            summary={
                "requests":len(values),
                "service_p50_ms":pct(service,.50),
                "service_p95_ms":pct(service,.95),
                "service_p99_ms":pct(service,.99),
                "client_queue_wait_p50_ms":pct(queue,.50),
                "client_queue_wait_p95_ms":pct(queue,.95),
                "client_queue_wait_p99_ms":pct(queue,.99),
                "arrival_to_result_p95_ms":pct(arrival,.95),
                "arrival_to_result_p99_ms":pct(arrival,.99),
            }
            per_kind[kind]=summary
            if summary["service_p95_ms"]>(
                SLO_WRITE_P95_MS if kind in WRITES else SLO_READ_P95_MS
            ):
                raise RuntimeError("D7 "+kind+" p95 service SLO breached "+str(summary))
            if kind in WRITES and summary["service_p99_ms"]>SLO_WRITE_P99_MS:
                raise RuntimeError("D7 "+kind+" p99 write service SLO breached")
        if burst_seconds>SLO_TOTAL_BURST_S:
            raise RuntimeError("D7 bounded burst wall SLO breached")
        # The classifier is a separate pg_stat_activity snapshot from the
        # top-level blocker counter; new blockers may appear between both
        # reads. Keep both as observations, never demand atomically equal counts.

        # Verify authentic committed business and ledger effects, separately
        # from returned HTTP responses (no successful-ACK-only shortcuts).
        imported=[read_import_evidence(admin,jid,company,valid)
                  for company,jid,valid,_label in jobs]
        sales_visit_ids=[int(visits[i+1]) for i in range(COUNTS["sale"])]
        sales=int(admin.execute("""
            SELECT count(*) FROM visits
            WHERE company_id=2 AND id=ANY(%s) AND status='Completed'
              AND final_amount_due=20.000 AND financial_evidence_version=4
        """,(sales_visit_ids,)).fetchone()[0])
        cogs=int(admin.execute("""
            SELECT count(*) FROM inventory_cost_events e
            JOIN inventory_movements m ON m.id=e.inventory_movement_id
             AND m.company_id=e.company_id
            WHERE e.company_id=2 AND m.reference_type='VISIT_ITEM_OUT'
              AND m.reference_id=ANY(%s)
        """,([str(i) for i in sales_visit_ids],)).fetchone()[0])
        inbounds=int(admin.execute("""
            SELECT count(*) FROM inventory_movements
            WHERE company_id=2 AND reference_type='INBOUND_SUPPLIER'
              AND reference_id LIKE 'D7-IN-%'
        """).fetchone()[0])
        # Routes are not replayed. IDs are read from actual HTTP responses.
        route_ids=[
            int(route_results[i]["route_id"])
            for i in range(COUNTS["route"])
        ]
        contexts=int(admin.execute("""
            SELECT count(*) FROM route_commercial_contexts
            WHERE company_id=2 AND dispatch_route_id=ANY(%s)
        """,(route_ids,)).fetchone()[0])
        neg=int(admin.execute("""
            SELECT count(*) FROM inventory_balances
            WHERE company_id=2 AND on_hand_quantity<0
        """).fetchone()[0])
        if (
            sales!=COUNTS["sale"] or cogs!=COUNTS["sale"]
            or inbounds!=COUNTS["inbound"]
            or contexts!=COUNTS["route"] or neg
        ):
            raise RuntimeError("D7 true financial/COGS/inbound/route stock evidence mismatch")
        if not await tenant_rls_proof():
            raise RuntimeError("D7 RLS proof failed")
        live_delivery=int(admin.execute("""
            SELECT count(*) FROM procrastinate_jobs
            WHERE task_name='wanasah.process_product_import'
              AND args->>'job_id'=ANY(%s)
              AND status IN ('todo','doing')
        """,([jid for _c,jid,_valid,_label in jobs],)).fetchone()[0])
        if live_delivery:
            raise RuntimeError("D7 queue has dangling active deliveries")

        report={
            "source":"disposable PG16; HTTPX ASGITransport 1 web process;"
                     f" actor-identity fixture only; {ADMISSION_LIMIT}-slot client admission",
            "arrivals_released":N,
            "completed_expected_http":sum(map(len,records.values())),
            "burst_wall_seconds":round(burst_seconds,3),
            "max_inflight_http":max_admitted,
            "configured_http_admission":ADMISSION_LIMIT,
            "baseline_catalog_p95_ms":pct(catalog_baseline,.95),
            "by_category":per_kind,
            "import_jobs":len(jobs),
            "unique_imports_rate_denied_initially":len(policy_denied_unique),
            "initial_durable_429_telemetry_rows":denial_rows,
            "initial_http_429_attempts":rejected_attempts,
            "replay_first_admitted_after_429":admitted_during_initial_replay,
            "rolling_60s_max_admissions_per_actor":max_rolling_admissions,
            "retry_after_http_attempts":retry_attempts,
            "eventual_new_imports_admitted_after_window":recovered_from_limit,
            "imported":sum(row["imported"] for row in imported),
            "invalid":sum(row["invalid"] for row in imported),
            "cross_company_queue_overlap":cross_overlap,
            "same_company_double":same_company_double,
            "independent_short_before_same_tenant_long":True,
            "peak_app_db_connections":max_app_conns,
            "peak_total_db_connections":max_total_conns,
            "max_import_tasks_doing":max_import_doing,
            "longest_observed_import_queue_age_seconds":round(
                oldest_observed_queue_age_seconds,2
            ),
            "import_terminal_latency_since_monitor_p95_seconds":pct(
                list(terminal_offsets.values()),.95
            ),
            "local_physical_cpu_cores":psutil.cpu_count(logical=False),
            "local_logical_cpu_cores":psutil.cpu_count(logical=True),
            "local_total_ram_gib":round(
                psutil.virtual_memory().total/(1024**3),2
            ),
            "min_available_ram_gib":round(
                min_memory_available_bytes/(1024**3),2
            ),
            "sampled_machine_cpu_p95_percent":pct(sampled_cpu_percent,.95),
            "sampled_db_blocker_edges":blocked_samples,
            "sampled_db_blocker_breakdown":dict(
                blocked_observations.most_common(12)
            ),
            "max_blocked_query_active_age_ms":round(
                longest_blocked_active_query_ms,2
            ),
            "db_samples":sample_count,
            "wal_bytes_delta_cluster":wal_delta,
            "sales_committed":sales,
            "cogs_exact_once":cogs,
            "inbound_committed":inbounds,
            "route_contexts":contexts,
            "negative_balances":neg,
            "http_foreign_tenant_denials":len(records["foreign_status"]),
            "rls_foreign_tenant_denials":2,
            "caveat":(
                "D7-L local ASGI burst admitted "
                + str(ADMISSION_LIMIT)
                + " active client calls; NOT 1000 active TCP clients "
                "or production-like staging. Sampled blocked-query age "
                "includes request execution time, not lock-wait duration."
            ),
        }
        print("D7_RESULT="+json.dumps(report,separators=(",",":")),flush=True)
        print("PRODUCT_IMPORT_D7_LOCAL_BURST=PASS",flush=True)
    finally:
        for proc in workers.values():
            if proc.poll() is None:proc.terminate()
        for proc in workers.values():
            if proc.poll() is None:
                try:proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
        for handle in handles.values():handle.close()
        admin.close()
        await client.aclose()
        await engine.dispose()


if __name__=="__main__":
    if sys.platform=="win32":
        asyncio.run(main(),loop_factory=lambda:
            asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:asyncio.run(main())
