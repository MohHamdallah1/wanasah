"""One small real PG/HTTP/maintenance-Worker Retention-versus-Retry acceptance."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
from io import BytesIO, StringIO
import json
import os
import time
from uuid import UUID, uuid4

import httpx
import psycopg
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

if (os.environ.get("WANASAH_P19_HTTP_DISPOSABLE_CHILD") != "1" or
    os.environ.get("WANASAH_P19_RETENTION_RETRY_CONFIRM") != "ISOLATED_SYNTHETIC_ONLY"):
    raise RuntimeError("Retention/Retry requires the explicitly guarded disposable runner.")
for key in ("DATABASE_URL", "DATABASE_URL_MIGRATION"):
    target = make_url(os.environ.get(key, ""))
    if (target.host != "127.0.0.1" or target.database != "p19_http_synthetic" or
        int(target.port or 0) != 55446):
        raise RuntimeError("Refusing retention writes outside disposable P19 PostgreSQL.")

from api.auth import create_access_token
from database import engine
from domains.simple_products.imports.application.source_service import prepare_import_source
from domains.simple_products.imports.application.execution_service import execute_import
from domains.simple_products.imports.application.state_machine import record_runtime_failure
from domains.simple_products.imports.application.validation_service import validate_rows
from domains.simple_products.imports.infrastructure.admission_repository import (
    check_import_admission_before_persist, reserve_source_capacity_after_persist,
)
from domains.simple_products.imports.domain.admission import DEFAULT_PRODUCT_IMPORT_ADMISSION_POLICY
from domains.simple_products.imports.infrastructure.postgres_source_store import POSTGRES_PRODUCT_IMPORT_SOURCE_STORE as STORE
from domains.simple_products.imports.infrastructure.queue import app
from domains.simple_products.imports.infrastructure.retention_queue import cleanup_product_import_retention
from scripts import product_import_phase19_http_isolated_child as shared
from scripts.run_product_import_phase19_live_load import build_source

ADMIN = make_url(os.environ["DATABASE_URL_MIGRATION"]).set(drivername="postgresql").render_as_string(hide_password=False)
LOCK = 190071
MARKER = "PRODUCT_IMPORT_P19_RETENTION_RETRY_ATOMIC=PASS"
CASE = os.environ.get("WANASAH_P19_RETENTION_RETRY_CASE", "all")
if CASE not in {"all", "correction", "checkpoint"}:
    raise RuntimeError("Unknown focused Retention/Retry case.")


def run(coro):
    async def wrapped():
        try:
            return await coro
        finally:
            await engine.dispose()
    return asyncio.run(wrapped(), loop_factory=asyncio.SelectorEventLoop)


def wait_for(probe, label, seconds=25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = probe()
        if result:
            return result
        time.sleep(.05)
    raise RuntimeError("Bounded acceptance did not complete: " + label)


async def seed(company, actor, *, staged=False, rejected=False, failed=True):
    # Source/job intake is a synthetic fixture. Actual preparation, validation
    # and runtime-failure authority establish subsequent durable states.
    job = uuid4()
    payload, mapping, _ = build_source(2 if rejected else 1, "P19RET" + job.hex[:12])
    if rejected:
        raw = list(csv.DictReader(StringIO(payload.decode("utf-8-sig"))))
        for item in raw:
            item[mapping["name"]] = ""
        stream = StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(raw[0]))
        writer.writeheader()
        writer.writerows(raw)
        payload = stream.getvalue().encode("utf-8-sig")
    digest = hashlib.sha256(payload).hexdigest()
    async with await psycopg.AsyncConnection.connect(shared.url.set(drivername="postgresql").render_as_string(hide_password=False)) as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.current_tenant',%s,true)", (str(company),))
            await check_import_admission_before_persist(conn, company_id=company, actor_id=actor,
                incoming_bytes=len(payload), policy=DEFAULT_PRODUCT_IMPORT_ADMISSION_POLICY)
            ref = await STORE.persist_stream_on_connection(connection=conn, company_id=company,
                stream=BytesIO(payload), byte_size=len(payload), sha256=digest)
            await reserve_source_capacity_after_persist(conn, company_id=company,
                incoming_bytes=len(payload), policy=DEFAULT_PRODUCT_IMPORT_ADMISSION_POLICY)
            await conn.execute("INSERT INTO product_import_jobs(id,company_id,request_id,created_by,"
                "file_name,content_type,source_id,source_sha256,file_size,status,detected_headers,"
                "suggested_mapping,column_mapping,default_lot_control_mode,default_expiry_control_mode,"
                "error_summary,total_rows,processed_rows,valid_rows,failed_rows,version) "
                "VALUES (%s,%s,%s,%s,'synthetic-retention.csv','text/csv',%s,%s,%s,'QUEUED',"
                "'[]','{}','{}','NONE','NONE','{}',0,0,0,0,1)",
                (job, company, uuid4(), actor, ref.source_id, digest, len(payload)))
    if staged or rejected:
        status = await prepare_import_source(company_id=company, job_id=job, source_store=STORE)
        if status != "VALIDATING":
            raise RuntimeError("Real preparation did not atomically stage the synthetic fixture.")
    if rejected:
        if await validate_rows(company_id=company, job_id=job):
            raise RuntimeError("Missing-name fixture was not actually rejected by validation authority.")
    elif failed:
        await record_runtime_failure(company_id=company, job_id=job,
            final_attempt=True, retryable=True, code="PRODUCT_IMPORT_SYSTEM_FAILURE",
            correlation_id="p19-retention-fixture")
    return str(job), str(ref.source_id), payload


async def defer_cleanup():
    async with app.open_async():
        return int(await cleanup_product_import_retention.configure(
            lock="product-import-retention:2", queueing_lock="product-import-retention:2",
        ).defer_async(company_id=2))


def delivered(admin, delivery):
    row = admin.execute("SELECT status,attempts FROM procrastinate_jobs WHERE id=%s", (delivery,)).fetchone()
    if row and row[0] in ("failed","aborted","cancelled"):
        raise RuntimeError("Real maintenance delivery failed.")
    return row if row == ("succeeded",1) else None


def source_snapshot(admin, company, fixture):
    job, source, _ = fixture
    state = admin.execute("SELECT j.status,j.source_payload_cleared_at,s.deleted_at,j.version "
        "FROM product_import_jobs j JOIN product_import_sources s ON s.company_id=j.company_id "
        "AND s.id=j.source_id WHERE j.company_id=%s AND j.id=%s", (company,job)).fetchone()
    chunks = admin.execute("SELECT payload FROM product_import_source_chunks WHERE company_id=%s "
        "AND source_id=%s ORDER BY chunk_index", (company,source)).fetchall()
    return state, b"".join(bytes(row[0]) for row in chunks)


def capacity(admin):
    return admin.execute("SELECT company_id,live_bytes FROM product_import_tenant_source_capacity "
        "WHERE company_id IN (2,3) ORDER BY company_id").fetchall(), admin.execute(
        "SELECT live_bytes FROM product_import_global_source_capacity WHERE id=1").fetchone()[0]


def retry(client, job):
    return client.post(f"/simple-products/imports/{job}/retry")


def gone(response, code):
    body = shared.require(response, 410, "expired/unavailable Retry")
    error = body.get("error", {})
    if (error.get("code") != code or not error.get("context", {}).get("correlation_id") or
        not error.get("message") or "SQL" in str(error.get("message"))):
        raise RuntimeError("Missing stable safe Retry error/correlation contract.")
    return error.get("context", {}).get("reason")


def rows_snapshot(admin, job):
    return admin.execute("SELECT row_identity,row_number,raw_data,normalized_data,status,version,compacted_at "
        "FROM product_import_rows WHERE company_id=2 AND job_id=%s ORDER BY row_number", (job,)).fetchall()


def business(admin):
    return {table:admin.execute("SELECT " + ("id,version" if table in
        ("products","product_variants","price_book_entries") else "id") + " FROM " + table + " ORDER BY id").fetchall()
        for table in ("products","product_variants","price_book_entries","domain_audit_events","transactional_outbox")}



def completed_checkpoint_regression(admin, client, processes):
    # This regression alone runs one synthetic product through the existing
    # authorities. No execution Worker or original developer DB is used.
    pending = run(seed(2, 1, staged=True))
    admin.execute("UPDATE product_import_jobs SET finished_at=(clock_timestamp() AT TIME ZONE 'UTC') "
        "- interval '31 days' WHERE id=%s", (pending[0],))
    gone(retry(client, pending[0]), "PRODUCT_IMPORT_RETRY_DETAILS_EXPIRED")
    checkpoint = run(seed(2, 1, staged=True, failed=False))
    if not run(validate_rows(company_id=2, job_id=UUID(checkpoint[0]))):
        raise RuntimeError("Synthetic checkpoint row was not validated by existing authority.")
    # Real PostgreSQL fails finalization AFTER the separate product/row commit.
    admin.execute(f"CREATE FUNCTION p19_finalization_failure() RETURNS trigger LANGUAGE plpgsql AS $$ "
        f"BEGIN IF NEW.id='{checkpoint[0]}'::uuid AND NEW.status='COMPLETED' THEN "
        "RAISE EXCEPTION 'synthetic finalization conflict' USING ERRCODE='40001'; "
        "END IF; RETURN NEW; END $$")
    admin.execute("CREATE TRIGGER p19_finalization_failure BEFORE UPDATE ON product_import_jobs "
        "FOR EACH ROW EXECUTE FUNCTION p19_finalization_failure()")
    try:
        run(execute_import(company_id=2, job_id=UUID(checkpoint[0])))
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) != "40001":
            raise
    else:
        raise RuntimeError("Expected real finalization serialization failure did not occur.")
    admin.execute("DROP TRIGGER p19_finalization_failure ON product_import_jobs")
    run(record_runtime_failure(company_id=2, job_id=UUID(checkpoint[0]), final_attempt=True,
        retryable=True, code="PRODUCT_IMPORT_SYSTEM_FAILURE", correlation_id="p19-checkpoint"))
    saved = business(admin)
    if admin.execute("SELECT status,product_variant_id FROM product_import_rows WHERE job_id=%s",
            (checkpoint[0],)).fetchall()[0][0] != "IMPORTED":
        raise RuntimeError("Finalization fixture did not actually save the product first.")
    admin.execute("UPDATE product_import_jobs SET finished_at=(clock_timestamp() AT TIME ZONE 'UTC') "
        "- interval '31 days' WHERE id=%s AND status='FAILED'", (checkpoint[0],))
    cleanup = run(defer_cleanup())
    processes.append(shared.start("p19-checkpoint-maintenance", "-m",
        "domains.simple_products.imports.infrastructure.worker_cli", "--role", "maintenance"))
    wait_for(lambda: delivered(admin, cleanup), "actual checkpoint compaction")
    if admin.execute("SELECT compacted_at IS NOT NULL AND raw_data='{}'::jsonb "
            "AND normalized_data='{}'::jsonb FROM product_import_rows WHERE job_id=%s",
            (checkpoint[0],)).fetchone() != (True,):
        raise RuntimeError("Real retention did not compact the durable imported row.")
    first = shared.require(retry(client, checkpoint[0]), 202, "compacted imported checkpoint retry")
    replay = shared.require(retry(client, checkpoint[0]), 202, "checkpoint retry replay")
    if replay != first:
        raise RuntimeError("Checkpoint retry replay changed its accepted state.")
    retained_capacity = capacity(admin)
    run(execute_import(company_id=2, job_id=UUID(checkpoint[0])))
    if admin.execute("SELECT status,processed_rows,total_rows FROM product_import_jobs WHERE id=%s",
            (checkpoint[0],)).fetchone() != ("COMPLETED", 1, 1):
        raise RuntimeError("Compacted checkpoint could not safely finalize.")
    if business(admin) != saved or capacity(admin) != retained_capacity:
        raise RuntimeError("Checkpoint finalization repeated business writes or capacity changes.")
    print("P19_RETRY_COMPACTED_CHECKPOINT=" + json.dumps({"products_imported":1,
        "pending_expired_details_rejected":True, "compacted_checkpoint_completed":True,
        "product_variant_price_audit_outbox_unchanged":True, "capacity_unchanged":True,
        "same_retry_replay":True}), flush=True)
    print("PRODUCT_IMPORT_P19_RETENTION_CHECKPOINT=PASS", flush=True)


def main():
    processes = []
    client = None
    with psycopg.connect(ADMIN, autocommit=True) as admin:
        admin.execute("SET statement_timeout='10s'")
        try:
            before_business = business(admin)
            deadlocks = admin.execute("SELECT deadlocks FROM pg_stat_database WHERE datname=current_database()").fetchone()[0]
            token = create_access_token({"sub":"1","is_admin":True},2,"Admin")
            client = httpx.Client(base_url=shared.BASE,timeout=40,headers={"Authorization":f"Bearer {token}"})
            processes.append(shared.start("p19-retention-api","-m","scripts.product_import_phase19_http_selector_server"))
            shared.wait_health(client,processes)
            if CASE == "checkpoint":
                completed_checkpoint_regression(admin, client, processes)
                return
            if CASE == "all":
                expired = run(seed(2,1))
                foreign = run(seed(3,2))
                fresh = run(seed(2,1))
                staged = run(seed(2,1,staged=True))
                old_details = run(seed(2,1,staged=True))
                for fixture, days in ((expired,8),(foreign,8),(fresh,6),(staged,8),(old_details,31)):
                    admin.execute("UPDATE product_import_jobs SET finished_at=(clock_timestamp() AT TIME ZONE 'UTC') "
                        "- (%s * interval '1 day') WHERE id=%s AND status='FAILED'", (days,fixture[0]))
                before_source = source_snapshot(admin,2,expired)
                before_foreign = source_snapshot(admin,3,foreign)
                before_capacity = capacity(admin)
                if gone(retry(client,expired[0]),"PRODUCT_IMPORT_RETRY_SOURCE_UNAVAILABLE") != "RETENTION_EXPIRED":
                    raise RuntimeError("Expired but retained source was accepted for parse retry.")
                gone(retry(client,old_details[0]),"PRODUCT_IMPORT_RETRY_DETAILS_EXPIRED")
                if source_snapshot(admin,2,expired) != before_source or capacity(admin) != before_capacity:
                    raise RuntimeError("Rejected Retry mutated data/capacity.")
                shared.require(client.get(f"/simple-products/imports/{foreign[0]}"),404,"foreign ownership")
                print("P19_EXPIRED_RETAINED_RETRY=PASS",flush=True)
                # Pause BEFORE job marking, after real source deletion and both
                # counter decrements in the SAME maintenance transaction.
                admin.execute(f"CREATE FUNCTION p19_retention_mark_barrier() RETURNS trigger LANGUAGE plpgsql AS $$ "
                    f"BEGIN IF NEW.id='{expired[0]}'::uuid THEN PERFORM pg_advisory_xact_lock({LOCK},1); "
                    "END IF; RETURN NEW; END $$")
                admin.execute("CREATE TRIGGER p19_retention_mark_barrier BEFORE UPDATE OF source_payload_cleared_at "
                    "ON product_import_jobs FOR EACH ROW WHEN (OLD.source_payload_cleared_at IS NULL "
                    "AND NEW.source_payload_cleared_at IS NOT NULL) EXECUTE FUNCTION p19_retention_mark_barrier()")
                admin.execute("SELECT pg_advisory_lock(%s,1)",(LOCK,))
                delivery = run(defer_cleanup())
                processes.append(shared.start("p19-retention-maintenance","-m",
                    "domains.simple_products.imports.infrastructure.worker_cli","--role","maintenance"))
                holder = wait_for(lambda: admin.execute("SELECT pid FROM pg_locks WHERE locktype='advisory' "
                    "AND classid=%s AND objid=1 AND NOT granted",(LOCK,)).fetchone(),"real retention marker barrier")
                if source_snapshot(admin,2,expired) != before_source or capacity(admin) != before_capacity:
                    raise RuntimeError("Source/counters became visible before the locked job marker commit.")
                with ThreadPoolExecutor(max_workers=1) as pool:
                    waiting_retry = pool.submit(retry,client,expired[0])
                    wait_for(lambda: admin.execute("SELECT pid FROM pg_stat_activity WHERE datname=current_database() "
                        "AND usename='wanasah_app' AND %s=ANY(pg_blocking_pids(pid)) "
                        "AND query LIKE '%%SELECT status, error_summary%%'",(holder[0],)).fetchone(),
                        "HTTP Retry blocked on retention's job lock")
                    if waiting_retry.done():
                        raise RuntimeError("Retry escaped the retention job lock.")
                    admin.execute("SELECT pg_advisory_unlock(%s,1)",(LOCK,))
                    if gone(waiting_retry.result(),"PRODUCT_IMPORT_RETRY_SOURCE_UNAVAILABLE") != "SOURCE_UNAVAILABLE":
                        raise RuntimeError("Post-commit Retry did not reject the deleted source.")
                wait_for(lambda: delivered(admin,delivery),"actual maintenance commit")
                after_source, body = source_snapshot(admin,2,expired)
                if after_source[0] != "FAILED" or after_source[1] is None or after_source[2] is None or body:
                    raise RuntimeError("Atomic source cleanup state incomplete.")
                expected_capacity = ([(2,len(fresh[2])),(3,len(foreign[2]))],len(fresh[2])+len(foreign[2]))
                if capacity(admin) != expected_capacity or source_snapshot(admin,3,foreign) != before_foreign:
                    raise RuntimeError("Capacity decrement or foreign source isolation failed.")
                again = run(defer_cleanup())
                wait_for(lambda: delivered(admin,again),"idempotent retention repeat")
                if capacity(admin) != expected_capacity:
                    raise RuntimeError("Repeated cleanup decremented capacity twice.")
                with admin.transaction(force_rollback=True):
                    admin.execute("SELECT id FROM product_import_jobs WHERE id=%s FOR UPDATE NOWAIT",(expired[0],))
                    admin.execute("SELECT id FROM product_import_sources WHERE id=%s FOR UPDATE NOWAIT",(expired[1],))
                    admin.execute("SELECT company_id FROM product_import_tenant_source_capacity WHERE company_id=2 FOR UPDATE NOWAIT")
                    admin.execute("SELECT id FROM product_import_global_source_capacity WHERE id=1 FOR UPDATE NOWAIT")
                print("P19_RETENTION_RETRY_ATOMIC="+json.dumps({"retention_delivery":delivery,
                    "retry_waited_for_job_lock":True,"uncommitted_changes_invisible":True,
                    "removed_bytes":len(expired[2]),"capacity_after":expected_capacity,
                    "foreign_source_unchanged":True,"repeat_no_double_decrement":True,"locks_available":True}),flush=True)
                # Essential regression: fresh parse and staged/source-free resume.
                for fixture, expected in ((fresh,"QUEUED"),(staged,"VALIDATING")):
                    first = shared.require(retry(client,fixture[0]),202,"available Retry")
                    version = admin.execute("SELECT version FROM product_import_jobs WHERE id=%s",(fixture[0],)).fetchone()[0]
                    repeated = shared.require(retry(client,fixture[0]),202,"state-idempotent Retry")
                    count = admin.execute("SELECT count(*) FROM procrastinate_jobs WHERE task_name='wanasah.process_product_import' "
                        "AND args->>'job_id'=%s",(fixture[0],)).fetchone()[0]
                    if (first["status"] != expected or repeated["status"] != expected or count != 1 or
                        admin.execute("SELECT version FROM product_import_jobs WHERE id=%s",(fixture[0],)).fetchone()[0] != version):
                        raise RuntimeError("Retry replay duplicated dispatch or refused source-free staged resume.")
                if source_snapshot(admin,2,fresh)[1] != fresh[2]:
                    raise RuntimeError("Available retry lost original source.")
                print("P19_RETRY_AVAILABLE_AND_STAGED_REPLAY=PASS",flush=True)
            else:
                processes.append(shared.start("p19-retention-maintenance","-m",
                    "domains.simple_products.imports.infrastructure.worker_cli","--role","maintenance"))
            # Actual Correction obtains its job lock just BEFORE 30 days and
            # pauses on row 2. Another rejected row remains otherwise unlocked.
            correction = run(seed(2,1,rejected=True))
            expected_capacity = capacity(admin)
            admin.execute("UPDATE product_import_jobs SET finished_at=(clock_timestamp() AT TIME ZONE 'UTC') "
                "- interval '30 days' + interval '8 seconds' WHERE id=%s",(correction[0],))
            original_rows = rows_snapshot(admin,correction[0])
            view = shared.require(client.get(f"/simple-products/imports/{correction[0]}/correction/rows"),200,"correction projection")
            item = view["items"][0]
            command = {"request_id":str(uuid4()),"expected_job_version":view["job_version"],
                "rows":[{"row_identity":item["row_identity"],"expected_version":item["version"],
                         "values":{"name":"Synthetic corrected row"}}]}
            admin.execute(f"CREATE FUNCTION p19_correction_barrier() RETURNS trigger LANGUAGE plpgsql AS $$ "
                f"BEGIN IF NEW.job_id='{correction[0]}'::uuid AND NEW.row_number=2 AND NEW.status='STAGED' "
                f"THEN PERFORM pg_advisory_xact_lock({LOCK},2); END IF; RETURN NEW; END $$")
            admin.execute("CREATE TRIGGER p19_correction_barrier BEFORE UPDATE ON product_import_rows "
                "FOR EACH ROW EXECUTE FUNCTION p19_correction_barrier()")
            admin.execute("SELECT pg_advisory_lock(%s,2)",(LOCK,))
            target = f"/simple-products/imports/{correction[0]}/correction/rows"
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(client.post,target,json=command)
                wait_for(lambda: admin.execute("SELECT pid FROM pg_locks WHERE locktype='advisory' "
                    "AND classid=%s AND objid=2 AND NOT granted",(LOCK,)).fetchone(),"actual Correction row barrier")
                wait_for(lambda: admin.execute("SELECT finished_at <= (clock_timestamp() AT TIME ZONE 'UTC') "
                    "- interval '30 days' FROM product_import_jobs WHERE id=%s",(correction[0],)).fetchone()[0],
                    "real expiry boundary crossed",seconds=12)
                cleanup = run(defer_cleanup())
                wait_for(lambda: delivered(admin,cleanup),"retention skips Correction's locked job")
                if rows_snapshot(admin,correction[0]) != original_rows:
                    raise RuntimeError("Retention erased an unrelated rejected row during Correction.")
                admin.execute("SELECT pg_advisory_unlock(%s,2)",(LOCK,))
                first = shared.require(pending.result(),202,"Correction acquired before expiry")
            replay = shared.require(client.post(target,json=command),202,"Correction durable replay after expiry")
            expected_replay = dict(first, replayed=True)
            if first.get("replayed") is not False or replay != expected_replay:
                raise RuntimeError("Correction idempotency changed at retention boundary.")
            after = rows_snapshot(admin,correction[0])
            if len(after) != 2 or after[1] != original_rows[1] or after[0][6] is not None:
                raise RuntimeError("Correction/retention damaged unedited lineage or row details.")
            cleanup = run(defer_cleanup())
            wait_for(lambda: delivered(admin,cleanup),"retention rechecks active Correction state")
            if rows_snapshot(admin,correction[0]) != after:
                raise RuntimeError("Retention selected a stale terminal Correction job.")
            if business(admin) != before_business or capacity(admin) != expected_capacity:
                raise RuntimeError("Product/Variant/Price/Audit/Outbox or live capacity changed.")
            if admin.execute("SELECT deadlocks FROM pg_stat_database WHERE datname=current_database()").fetchone()[0] != deadlocks:
                raise RuntimeError("PostgreSQL recorded a lock-order deadlock.")
            print("P19_CORRECTION_RETENTION_BOUNDARY="+json.dumps({"untouched_rejected_rows":1,
                "retention_skipped_locked_job":True,"active_state_rechecked":True,"same_request_replay":True,
                "business_snapshot_unchanged":True,"deadlocks_delta":0}),flush=True)
            print(MARKER if CASE == "all" else "PRODUCT_IMPORT_P19_RETENTION_CORRECTION=PASS",flush=True)
        finally:
            admin.execute("SELECT pg_advisory_unlock_all()")
            # Only maintenance is running. Never stop a Worker during an actual
            # delivery; cancel owned pending imports through the official API.
            if client is not None:
                active = admin.execute("SELECT id::text FROM product_import_jobs WHERE company_id=2 "
                    "AND status IN ('QUEUED','PARSING','VALIDATING','IMPORTING','RETRYING')").fetchall()
                for (job,) in active:
                    response = client.post(f"/simple-products/imports/{job}/cancel")
                    if response.status_code not in (202,409):
                        raise RuntimeError("Official cancellation of owned fixture failed.")
            wait_for(lambda: admin.execute("SELECT count(*) FROM procrastinate_jobs WHERE queue_name='product-import-maintenance' "
                "AND status IN ('doing','todo')").fetchone()[0] == 0,"owned maintenance deliveries drained",seconds=60)
            for process,handle in reversed(processes):
                shared.stop(process,handle)
            if client is not None:
                client.close()


if __name__ == "__main__":
    main()
