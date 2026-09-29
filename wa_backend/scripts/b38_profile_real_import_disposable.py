"""B3.8: REAL XLSX parser -> staging -> validation -> execution in ephemeral PG.

This uses the actual Product Import application services and real Excel parser,
normalization, barcode checks, tenant RLS, per-row error handling, pricing,
audit, idempotency and committed database operations. The synthetic job is
seeded directly because HTTP admission/SourceStore and Procrastinate queue
delivery require additional infrastructure: those excluded phases are NOT
claimed tested. The outer launcher copies schema and synthetic tenant ONLY and
destroys the PostgreSQL cluster after finishing.

Mandatory child flags are set only by run_b3_index_growth_gate.py. No customer
records are copied, and no writes to the source velotrack_db are permitted.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import os
import pathlib
import selectors
import sys
from collections import Counter, defaultdict
from time import perf_counter
from uuid import uuid4

from dotenv import load_dotenv

ROOT=pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
if os.environ.get("WANASAH_B38_REAL_IMPORT_GATE")!="1" or os.environ.get("WANASAH_B3_DISPOSABLE_CHILD")!="1":
    raise RuntimeError("B3.8 may ONLY run inside the disposable PG launcher.")
if "127.0.0.1:55441/b3_index_growth" not in os.environ.get("WANASAH_B3_TEMP_DB_URL",""):
    raise RuntimeError("Wrong target: B3.8 refuses a non-local, non-temporary database.")
load_dotenv(os.environ["WANASAH_B3_SOURCE_ENV_FILE"],override=False)
os.environ["DATABASE_URL"]=os.environ["WANASAH_B3_TEMP_DB_URL"]

from openpyxl import Workbook
from sqlalchemy import event,select,text

from context import tenant_context
from database import AsyncSessionLocal,engine
from domains.simple_products.imports.application.execution_service import execute_import
from domains.simple_products.imports.application.staging_service import stage_source
from domains.simple_products.imports.application.validation_service import validate_rows
from domains.simple_products.imports.domain.mapping import suggest_mapping
from domains.simple_products.imports.infrastructure.parsers import open_source
from domains.simple_products.imports.infrastructure.repository import (
    open_tenant_session,close_tenant_session,
)
from models import Driver,ProductBarcode,ProductImportJob,ProductVariant
from domains.simple_products.service import barcode_type
from scripts.run_product_import_phase19_live_load import build_source

ACTOR_COMPANY=2
_ALLOWED_COUNTS=(100,1000,5000)
phase="setup"
sql_counts=defaultdict(Counter)
sql_elapsed=defaultdict(float)
slow_statements=[]
stage_times={}
parser_active_seconds=0.0
scanned_rows=0

def show(name,val):
    print(name+" "+json.dumps(val,default=str,separators=(",",":"),ensure_ascii=False),flush=True)

def before_cursor(_conn,_cursor,statement,_params,context,_many):
    context._b38_start=perf_counter()
    context._b38_type=statement.lstrip().split(" ",1)[0].upper()
def after_cursor(_conn,_cursor,statement,_params,context,_many):
    elapsed=perf_counter()-context._b38_start
    sql_counts[phase][context._b38_type]+=1
    sql_elapsed[phase]+=elapsed
    if elapsed>=0.2:
        # SQL structure only, never actual bind parameters or account data.
        preview=" ".join(statement.split())[:190]
        slow_statements.append({
            "phase":phase,"elapsed_s":round(elapsed,3),
            "sql_type":context._b38_type,
            "sql_fingerprint":hashlib.sha256(
                statement.encode("utf-8")
            ).hexdigest()[:12],
            "statement_preview":preview,
        })

def actual_parser_rows(rows):
    global scanned_rows,parser_active_seconds
    iterator=iter(rows)
    while True:
        tick=perf_counter()
        try:
            item=next(iterator)
        except StopIteration:
            parser_active_seconds+=perf_counter()-tick
            return
        parser_active_seconds+=perf_counter()-tick
        scanned_rows+=1
        yield item

async def current_job(uuid):
    token,db=await open_tenant_session(ACTOR_COMPANY)
    try:
        return (await db.execute(text(
            "SELECT status,total_rows,valid_rows,processed_rows,failed_rows,"
            "source_payload_cleared_at,started_at,finished_at "
            "FROM product_import_jobs WHERE company_id=:c AND id=:job"
        ),{"c":ACTOR_COMPANY,"job":uuid})).mappings().one()
    finally:
        await db.rollback()
        await close_tenant_session(token,db)

async def main():
    global phase
    n=int(os.environ.get("WANASAH_B38_MAX_ROWS","1000"))
    inject_conflicts=os.environ.get("WANASAH_B38_CONFLICT_FIXTURE")=="1"
    if inject_conflicts and os.environ.get("WANASAH_B38_VALIDATION_ONLY")!="1":
        raise RuntimeError("Barcode conflict fixture must stop after validation.")
    if n not in _ALLOWED_COUNTS:
        raise RuntimeError("Only a bounded 100/1000/5000 sample is permitted.")
    token=tenant_context.set(ACTOR_COMPANY)
    event.listen(engine.sync_engine,"before_cursor_execute",before_cursor)
    event.listen(engine.sync_engine,"after_cursor_execute",after_cursor)
    try:
        # Generate the same realistic mixed Product Import fixture used by
        # Phase19, converted to a real XLSX. Expected 1% invalid.
        t0=perf_counter()
        csv_data,mapping,prefix=build_source(n,run_id="B38-"+uuid4().hex[:14])
        rows=list(csv.reader(io.StringIO(csv_data.decode("utf-8-sig"))))
        wb=Workbook(write_only=True)
        ws=wb.create_sheet("Products")
        for row in rows:
            ws.append(row)
        output=io.BytesIO()
        wb.save(output)
        payload=output.getvalue()
        stage_times["generate_xlsx_s"]=perf_counter()-t0
        show("B38_FILE",{"rows":n,"bytes":len(payload),"synthetic":True})

        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT set_config('app.current_tenant','2',false)"))
            assert await db.scalar(text("SELECT current_database()"))=="b3_index_growth"
            actor=await db.scalar(select(Driver).where(
                Driver.company_id==ACTOR_COMPANY,Driver.is_admin.is_(True),
            ))
            if actor is None:
                raise RuntimeError("No synthetic admin fixture")
            existing=await db.scalar(text("SELECT COUNT(*) FROM product_import_jobs WHERE company_id=2"))
            if existing:
                raise RuntimeError("Fixture is not empty (import jobs)")
            initial_variants=await db.scalar(text(
                "SELECT COUNT(*) FROM product_variants WHERE company_id=2"
            ))
            if initial_variants!=1:
                raise RuntimeError("Unexpected initial synthetic products")
            job_id=uuid4()
            # Application service create_import routes through a persistent
            # source store/queue, so this fixture starts directly in PARSING.
            # SourceStore/HTTP/queue latencies remain excluded and visible.
            if inject_conflicts:
                baseline_variant=await db.scalar(select(ProductVariant).where(
                    ProductVariant.company_id==ACTOR_COMPANY,
                ).limit(1))
                if baseline_variant is None:
                    raise RuntimeError("Synthetic conflict SKU fixture missing")
                header=rows[0]
                barcode_col=header.index(mapping["unit_barcode"])
                active=rows[1][barcode_col]
                inactive=rows[2][barcode_col]
                for value,is_active in ((active,True),(inactive,False)):
                    db.add(ProductBarcode(
                        company_id=ACTOR_COMPANY,
                        product_variant_id=baseline_variant.id,
                        uom_id=baseline_variant.base_uom_id,
                        barcode=value,
                        barcode_type=barcode_type(value),
                        is_active=is_active,
                        is_primary=False,
                    ))
                await db.flush()
                show("B38_CONFLICT_FIXTURE_CREATED",{
                    "active_preexisting_barcodes":1,
                    "inactive_preexisting_barcodes":1,
                    "test_only":True,
                })
            job=ProductImportJob(
                id=job_id,request_id=uuid4(),company_id=ACTOR_COMPANY,
                created_by=actor.id,
                file_name="b38-synthetic.xlsx",
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                source_sha256=hashlib.sha256(payload).hexdigest(),
                file_size=len(payload),source_id=None,
                status="PARSING",
                default_lot_control_mode="NONE",
                default_expiry_control_mode="NONE",
                source_payload_cleared_at=None,
            )
            db.add(job)
            await db.commit()

        phase="xlsx_open_and_stage"
        t=perf_counter()
        with open_source("b38-synthetic.xlsx",payload) as source:
            headers=list(source.headers)
            suggestions=suggest_mapping(headers)
            if suggestions.get("name") is None:
                raise RuntimeError("XLSX name mapping missing")
            await stage_source(
                company_id=ACTOR_COMPANY,job_id=job_id,
                headers=headers,rows=actual_parser_rows(source.rows),
                suggestions=suggestions,
            )
        stage_times["xlsx_stage_total_s"]=perf_counter()-t
        stage_times["xlsx_parser_active_s"]=parser_active_seconds
        assert scanned_rows==n,(scanned_rows,n)
        after_stage=await current_job(job_id)
        if after_stage["status"]!="VALIDATING" or after_stage["total_rows"]!=n:
            raise RuntimeError(f"Unexpected staged state: {dict(after_stage)}")
        show("B38_STAGE_COMPLETE",{
            "elapsed_s":round(stage_times["xlsx_stage_total_s"],3),
            "parser_active_s":round(parser_active_seconds,3),
            "sql_elapsed_s":round(sql_elapsed[phase],3),
            "physical_rows":scanned_rows,
        })

        phase="validation"
        t=perf_counter()
        advance=await validate_rows(company_id=ACTOR_COMPANY,job_id=job_id)
        stage_times["validation_s"]=perf_counter()-t
        after_valid=await current_job(job_id)
        show("B38_VALIDATION_COMPLETE",{
            "elapsed_s":round(stage_times["validation_s"],3),
            "advance":advance,
            "status":after_valid["status"],
            "valid":after_valid["valid_rows"],
            "invalid":after_valid["failed_rows"],
        })
        if not advance or after_valid["status"]!="IMPORTING":
            raise RuntimeError("Real validation did not reach IMPORTING")
        if inject_conflicts:
            token2,s2=await open_tenant_session(ACTOR_COMPANY)
            try:
                states=(await s2.execute(text(
                    "SELECT row_number,status,error_code "
                    "FROM product_import_rows "
                    "WHERE company_id=2 AND job_id=:j AND row_number IN (2,3) "
                    "ORDER BY row_number"
                ),{"j":job_id})).all()
                count=await s2.scalar(text(
                    "SELECT COUNT(*) FROM product_import_rows "
                    "WHERE company_id=2 AND job_id=:j AND status='INVALID'"
                ),{"j":job_id})
            finally:
                await s2.rollback()
                await close_tenant_session(token2,s2)
            expected_invalid=n//100+1
            show("B38_CONFLICT_ASSERTION",{
                "rows":[list(v) for v in states],
                "invalid":count,
                "expected_invalid":expected_invalid,
                "success":(
                    len(states)==2
                    and states[0][1:] == ("INVALID","IMPORT_BARCODE_CONFLICT")
                    and states[1][1:] == ("VALID",None)
                    and count==expected_invalid
                ),
            })
            if not (
                len(states)==2
                and states[0][1:] == ("INVALID","IMPORT_BARCODE_CONFLICT")
                and states[1][1:] == ("VALID",None)
                and count==expected_invalid
            ):
                raise RuntimeError("Active/inactive barcode conflict semantics changed")

        # Optional diagnosis: stop safely after REAL 5k XLSX parse, staging
        # and barcode validation, without costlier product/price execution.
        # Only permitted inside the disposable launcher.
        if os.environ.get("WANASAH_B38_VALIDATION_ONLY")=="1":
            show("B38_SLOW_SQL_BY_STAGE",sorted(
                slow_statements,key=lambda q:q["elapsed_s"],reverse=True
            )[:16])
            show("B38_STAGE_TIMINGS",{
                k:round(v,3) for k,v in stage_times.items()
            })
            show("B38_SQL_BY_STAGE",{
                name:{"sql":dict(counts),"total":sum(counts.values()),
                      "db_elapsed_s":round(sql_elapsed[name],3)}
                for name,counts in sql_counts.items()
            })
            print("B38_VALIDATION_ONLY_REAL_XLSX=PASS",flush=True)
            return

        phase="execution"
        t=perf_counter()
        await execute_import(company_id=ACTOR_COMPANY,job_id=job_id)
        stage_times["execution_s"]=perf_counter()-t
        after=await current_job(job_id)
        t=perf_counter()
        check=await current_job(job_id)
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT set_config('app.current_tenant','2',false)"))
            final_variants=await db.scalar(text(
                "SELECT COUNT(*) FROM product_variants WHERE company_id=2"
            ))
            outcomes=(await db.execute(text(
                "SELECT status,COUNT(*) n FROM product_import_rows "
                "WHERE company_id=2 AND job_id=:job GROUP BY status ORDER BY status"
            ),{"job":job_id})).all()
            imported_count=dict(outcomes).get("IMPORTED",0)
            invalid_count=dict(outcomes).get("INVALID",0)
            linked=await db.scalar(text(
                "SELECT COUNT(*) FROM product_import_rows "
                "WHERE company_id=2 AND job_id=:job AND status='IMPORTED' "
                "AND product_variant_id IS NOT NULL"
            ),{"job":job_id})
            published=await db.scalar(text(
                "SELECT COUNT(*) FROM price_book_entries WHERE company_id=2 "
                "AND is_published=TRUE"
            ))
            await db.rollback()
        stage_times["evidence_s"]=perf_counter()-t
        expected_invalid=n//100
        expected_valid=n-expected_invalid
        # The fixture has one EACH price per valid SKU and an additional
        # outer-package price unless source row i has i % 6 == 0. Every
        # hundredth row is deliberately invalid and has no published price.
        expected_published=sum(
            1+int(i % 6 != 0)
            for i in range(1,n+1) if i % 100 != 0
        )
        actual={
            "status":after["status"],
            "rows":after["total_rows"],
            "reported_imported":after["processed_rows"],
            "reported_valid":after["valid_rows"],
            "reported_invalid":after["failed_rows"],
            "db_imported":imported_count,"db_invalid":invalid_count,
            "linked":linked,"variants_added":final_variants-initial_variants,
            "published_prices":published,
            "expected_published_prices":expected_published,
        }
        show("B38_FINAL",actual)
        if (
            after["status"]!="COMPLETED_WITH_ERRORS"
            or after["total_rows"]!=n
            or after["processed_rows"]!=expected_valid
            or invalid_count!=expected_invalid
            or imported_count!=expected_valid
            or final_variants-initial_variants!=expected_valid
            or linked!=expected_valid
            or published!=expected_published
        ):
            raise RuntimeError("Product Import result/lineage did not reconcile")
        show("B38_SLOW_SQL_BY_STAGE",sorted(
            slow_statements,key=lambda q:q["elapsed_s"],reverse=True
        )[:16])
        show("B38_STAGE_TIMINGS",{
            k:round(v,3) for k,v in stage_times.items()
        })
        show("B38_SQL_BY_STAGE",{
            name:{"sql":dict(counts),"total":sum(counts.values()),
                  "db_elapsed_s":round(sql_elapsed[name],3)}
            for name,counts in sql_counts.items()
        })
        print("B38_REAL_XLSX_STAGING_VALIDATION_EXECUTION=PASS",flush=True)
    finally:
        event.remove(engine.sync_engine,"before_cursor_execute",before_cursor)
        event.remove(engine.sync_engine,"after_cursor_execute",after_cursor)
        tenant_context.reset(token)
        await engine.dispose()


if __name__=="__main__":
    if sys.platform=="win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
