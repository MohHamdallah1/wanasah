"""Small HTTP contention/retention evidence; reuses the disposable P19 runner."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import time
from uuid import uuid4

import httpx
import psycopg
from sqlalchemy.engine import make_url

if (os.environ.get("WANASAH_P19_HTTP_DISPOSABLE_CHILD") != "1" or
    os.environ.get("WANASAH_P19_CONTENTION_CONFIRM") != "ISOLATED_SYNTHETIC_ONLY"):
    raise RuntimeError("Contention evidence requires the guarded disposable runner.")
for key in ("DATABASE_URL", "DATABASE_URL_MIGRATION"):
    target = make_url(os.environ.get(key, ""))
    if (target.host != "127.0.0.1" or target.database != "p19_http_synthetic" or
        int(target.port or 0) != 55446):
        raise RuntimeError("Refusing contention outside disposable P19 PostgreSQL.")
if (os.environ.get("PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS") != "2" or
    os.environ.get("PRODUCT_IMPORT_MAX_ACTIVE_JOBS_PER_TENANT") != "2" or
    os.environ.get("WANASAH_P19_HTTP_API_PORT") != "18046"):
    raise RuntimeError("Expected explicit two-slot/two-active-job synthetic fixture.")

from api.auth import create_access_token
from domains.simple_products.imports.infrastructure.queue import app, product_import_worker_heartbeat
from domains.simple_products.imports.infrastructure.retention_queue import schedule_product_import_retention
from scripts import product_import_phase19_http_isolated_child as shared
from scripts.product_import_business_integrity_gate import _assert_business_evidence
from scripts.run_product_import_phase19_live_load import build_source

ADMIN = make_url(os.environ["DATABASE_URL_MIGRATION"]).set(drivername="postgresql").render_as_string(hide_password=False)
APP = make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql").render_as_string(hide_password=False)
ROWS = 3
BARRIER = 190019
MARKER = "PRODUCT_IMPORT_P19_REAL_CONTENTION=PASS"


def wait_for(probe, label, seconds=25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = probe()
        if result:
            return result
        time.sleep(.05)
    raise RuntimeError("Bounded contention evidence unavailable: " + label)


def queue_snapshot(admin):
    rows = admin.execute("SELECT status,lock,args->>'job_id' FROM procrastinate_jobs "
        "WHERE task_name='wanasah.process_product_import' AND status IN ('todo','doing') "
        "ORDER BY id").fetchall()
    doing = [row for row in rows if row[0] == "doing"]
    locks = [row[1] for row in doing]
    if len(doing) > 2 or len(set(locks)) != len(locks):
        raise RuntimeError("Execution bound/company serialization violated.")
    return rows


def blocked_pair(admin):
    rows = queue_snapshot(admin)
    doing = {row[1] for row in rows if row[0] == "doing"}
    pending = {row[1] for row in rows if row[0] == "todo"}
    waiters = admin.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory' "
        "AND classid=%s AND objid IN (2,3) AND NOT granted", (BARRIER,)).fetchone()[0]
    return (rows if doing == pending == {"product-import:2", "product-import:3"}
            and int(waiters) == 2 and len(rows) == 4 else None)


def upload(client, request_id, payload, name):
    return client.post("/simple-products/imports", data={"request_id": request_id,
        "default_lot_control_mode": "NONE", "default_expiry_control_mode": "NONE"},
        files={"file": (name, payload, "text/csv")})


def retained_source(admin, company, job, payload):
    row = admin.execute("SELECT j.source_id,j.source_sha256,j.file_size,j.source_payload_cleared_at,"
        "s.deleted_at,s.sha256,s.byte_size FROM product_import_jobs j JOIN product_import_sources s "
        "ON s.company_id=j.company_id AND s.id=j.source_id WHERE j.company_id=%s AND j.id=%s",
        (company, job)).fetchone()
    if row is None:
        raise RuntimeError("Missing tenant source reference.")
    chunks = admin.execute("SELECT payload FROM product_import_source_chunks WHERE company_id=%s "
        "AND source_id=%s ORDER BY chunk_index", (company, row[0])).fetchall()
    if (row[3] is not None or row[4] is not None or row[1] != row[5] or
        row[1] != hashlib.sha256(payload).hexdigest() or int(row[2]) != len(payload) or
        int(row[6]) != len(payload) or b"".join(bytes(x[0]) for x in chunks) != payload):
        raise RuntimeError("Retained source bytes/hash/tenant reference mismatch.")
    return str(row[0])


def tenant_reads(admin, jobs):
    # Exercise the actual application role while both execution slots are held.
    with psycopg.connect(APP, autocommit=True) as probe:
        role = probe.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        if role != (False, False):
            raise RuntimeError("RLS probe unexpectedly privileged.")
        for company in (2, 3, 2):
            probe.execute("SELECT set_config('app.current_tenant',%s,false)", (str(company),))
            for table in ("product_import_jobs", "product_import_sources", "product_import_source_chunks"):
                foreign = probe.execute("SELECT count(*) FROM " + table + " WHERE company_id<>%s", (company,)).fetchone()[0]
                own = probe.execute("SELECT count(*) FROM " + table + " WHERE company_id=%s", (company,)).fetchone()[0]
                if foreign != 0 or own != 2:
                    raise RuntimeError("Concurrent tenant source RLS visibility mismatch.")
    for company, client in jobs["clients"].items():
        foreign_job = next(job for tenant, job, _ in jobs["accepted"] if tenant != company)
        shared.require(client.get(f"/simple-products/imports/{foreign_job}"), 404, "concurrent foreign job")


async def defer_control_and_retention():
    async with app.open_async():
        control = await product_import_worker_heartbeat.defer_async()
        maintenance = await schedule_product_import_retention.defer_async()
    return int(control), int(maintenance)


async def defer_retention():
    async with app.open_async():
        return int(await schedule_product_import_retention.defer_async())


def delivered(admin, ids):
    states = admin.execute("SELECT id,status FROM procrastinate_jobs WHERE id=ANY(%s) ORDER BY id", (ids,)).fetchall()
    if any(str(row[1]) in {"failed", "cancelled", "aborted"} for row in states):
        raise RuntimeError("Actual control/maintenance delivery failed.")
    return states if len(states) == len(ids) and all(str(row[1]) == "succeeded" for row in states) else None


def business_snapshot(admin):
    # Compare durable identities/versions, not mutable delivery status timestamps.
    result = {}
    for table, columns in (("products", "id,version"), ("product_variants", "id,version"),
        ("price_book_entries", "id,version,publication_id"), ("domain_audit_events", "id"),
        ("transactional_outbox", "id")):
        result[table] = admin.execute("SELECT company_id," + columns + " FROM " + table +
            " WHERE company_id IN (2,3) ORDER BY company_id,id").fetchall()
    return result


def retention_evidence(admin, accepted, business_before):
    # Age terminal *owned synthetic fixtures only*. Never change status, queue,
    # source bytes, policy, or any developer row. Native trigger updates registry.
    own = [job for company, job, _ in accepted if company == 2]
    foreign = admin.execute("SELECT id,row_identity,raw_data,normalized_data,version,compacted_at "
        "FROM product_import_rows WHERE company_id=3 ORDER BY id").fetchall()
    identity = admin.execute("SELECT id,row_identity,row_number,product_variant_id,status FROM product_import_rows "
        "WHERE company_id=2 AND job_id=%s ORDER BY row_number", (own[0],)).fetchall()
    for job, days in zip(own, (31, 366), strict=True):
        changed = admin.execute("UPDATE product_import_jobs SET finished_at=(CURRENT_TIMESTAMP AT TIME ZONE 'UTC') "
            "- (%s * interval '1 day') WHERE company_id=2 AND id=%s AND status='COMPLETED' "
            "AND source_payload_cleared_at IS NOT NULL", (days, job)).rowcount
        if changed != 1:
            raise RuntimeError("Retention fixture was not a completed source-cleaned job.")
    scheduler = asyncio.run(defer_retention(), loop_factory=asyncio.SelectorEventLoop)
    wait_for(lambda: delivered(admin, [scheduler]), "native retention scheduler")
    def cleanup_done():
        return admin.execute("SELECT id FROM procrastinate_jobs WHERE task_name='wanasah.cleanup_product_import_retention' "
            "AND args->>'company_id'='2' AND status='succeeded' ORDER BY id DESC LIMIT 1").fetchone()
    wait_for(cleanup_done, "real retention Worker")
    rows = admin.execute("SELECT id,row_identity,row_number,product_variant_id,status,raw_data,normalized_data,compacted_at "
        "FROM product_import_rows WHERE company_id=2 AND job_id=%s ORDER BY row_number", (own[0],)).fetchall()
    if (len(rows) != ROWS or [r[:5] for r in rows] != identity or
        any(r[5] != {} or r[6] != {} or r[7] is None for r in rows)):
        raise RuntimeError("Retention compaction damaged row identity or kept expired detail.")
    if admin.execute("SELECT count(*) FROM product_import_rows WHERE company_id=2 AND job_id=%s", (own[1],)).fetchone() != (0,):
        raise RuntimeError("Expired terminal lineage not removed by retention authority.")
    after = admin.execute("SELECT id,row_identity,raw_data,normalized_data,version,compacted_at "
        "FROM product_import_rows WHERE company_id=3 ORDER BY id").fetchall()
    if after != foreign or business_snapshot(admin) != business_before:
        raise RuntimeError("Retention changed foreign detail or durable business identities.")
    candidate = admin.execute("SELECT next_due_at > CURRENT_TIMESTAMP FROM product_import_schedule_candidates "
        "WHERE company_id=2 AND task_kind='retention'").fetchone()
    if candidate != (True,):
        raise RuntimeError("Retention scheduler did not reconcile next bounded deadline.")
    return {"compacted_rows": ROWS, "lineage_rows_deleted": ROWS,
        "foreign_rows_unchanged": len(foreign), "business_snapshot_unchanged": True,
        "source_expiry": "OPEN: sources already cleaned after atomic staging"}


def main():
    processes = []
    clients = {}
    accepted = []
    with psycopg.connect(ADMIN, autocommit=True) as admin:
        admin.execute("SET statement_timeout='10s'")
        try:
            baseline = business_snapshot(admin)
            # Test-only lock on the first physical row. It never changes data or
            # runtime code and is removed with the owned disposable cluster.
            admin.execute("CREATE FUNCTION p19_contention_barrier() RETURNS trigger LANGUAGE plpgsql AS $$ "
                "BEGIN IF NEW.row_number=2 THEN PERFORM pg_advisory_xact_lock(190019,NEW.company_id); "
                "END IF; RETURN NEW; END $$")
            admin.execute("CREATE TRIGGER p19_contention_barrier BEFORE INSERT ON product_import_rows "
                "FOR EACH ROW EXECUTE FUNCTION p19_contention_barrier()")
            for company, actor in ((2, 1), (3, 2)):
                admin.execute("SELECT pg_advisory_lock(%s,%s)", (BARRIER, company))
                token = create_access_token({"sub": str(actor), "is_admin": True}, company, "Admin")
                clients[company] = httpx.Client(base_url=shared.BASE, timeout=40,
                    headers={"Authorization": f"Bearer {token}"})
            processes.append(shared.start("p19-contention-api", "-m", "scripts.product_import_phase19_http_selector_server"))
            for role in ("control", "maintenance", "execution"):
                processes.append(shared.start("p19-contention-" + role, "-m",
                    "domains.simple_products.imports.infrastructure.worker_cli", "--role", role))
            shared.wait_health(clients[2], processes)
            shared.wait_worker(clients[2])
            # Identical request ID/body across tenants must produce independent
            # operations; two simultaneously blocked copies per tenant replay.
            request_id = str(uuid4())
            payload, _, _ = build_source(ROWS, "P19CONCURRENT" + uuid4().hex[:10])
            for company in clients:
                admin.execute("SELECT pg_advisory_lock(%s,hashtext(%s))", (company, request_id))
            with ThreadPoolExecutor(max_workers=4) as pool:
                pending = [(company, pool.submit(upload, client, request_id, payload, "synthetic-shared.csv"))
                    for company, client in clients.items() for _ in range(2)]
                try:
                    wait_for(lambda: admin.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory' "
                        "AND classid IN (2,3) AND NOT granted").fetchone()[0] == 4,
                        "four HTTP uploads overlapping at request locks")
                finally:
                    for company in clients:
                        admin.execute("SELECT pg_advisory_unlock(%s,hashtext(%s))", (company, request_id))
                responses = [(company, shared.require(future.result(), 202, "simultaneous upload"))
                    for company, future in pending]
            for company in clients:
                own = [row for tenant, row in responses if tenant == company]
                if len({row["job_id"] for row in own}) != 1 or sorted(row["replayed"] for row in own) != [False, True]:
                    raise RuntimeError("Simultaneous same-tenant upload was not exactly deduplicated.")
                accepted.append((company, own[0]["job_id"], payload))
            if accepted[0][1] == accepted[1][1]:
                raise RuntimeError("Request identity escaped its tenant scope.")
            print("P19_OVERLAPPING_HTTP_REPLAY=" + json.dumps({"requests": 4, "jobs": 2,
                "replays": 2, "same_request_id_across_tenants": True}), flush=True)
            # Race two further uploads for the one remaining active admission.
            with ThreadPoolExecutor(max_workers=4) as pool:
                more = []
                for company, client in clients.items():
                    for _ in range(2):
                        body, _, _ = build_source(ROWS, "P19CAPACITY" + uuid4().hex[:12])
                        more.append((company, body, pool.submit(upload, client, str(uuid4()), body, "synthetic-extra.csv")))
                denial_count = 0
                for company, body, future in more:
                    response = future.result()
                    if response.status_code == 202:
                        admitted = shared.require(response, 202, "capacity winner")
                        accepted.append((company, admitted["job_id"], body))
                    else:
                        denied = shared.require(response, 429, "capacity loser")
                        if (denied.get("error", {}).get("code") != "PRODUCT_IMPORT_ACTIVE_JOB_LIMIT" or
                            response.headers.get("Retry-After") != "30"):
                            raise RuntimeError("Unexpected admission denial contract.")
                        denial_count += 1
                if denial_count != 2 or len(accepted) != 4:
                    raise RuntimeError("Concurrent uploads raced past tenant admission limit.")
            wait_for(lambda: blocked_pair(admin), "two live Workers with two accepted pending imports")
            sources = [retained_source(admin, company, job, body) for company, job, body in accepted]
            if len(set(sources)) != 4 or admin.execute("SELECT count(*) FROM product_import_rows").fetchone() != (0,):
                raise RuntimeError("Duplicate source or partial atomic staging visible.")
            for company in clients:
                total = sum(len(body) for tenant, _, body in accepted if tenant == company)
                if admin.execute("SELECT live_bytes FROM product_import_tenant_source_capacity WHERE company_id=%s",
                    (company,)).fetchone() != (total,):
                    raise RuntimeError("Admission/source capacity includes rejected or duplicated bytes.")
            if admin.execute("SELECT live_bytes FROM product_import_global_source_capacity WHERE id=1").fetchone() != (
                sum(len(body) for _, _, body in accepted),):
                raise RuntimeError("Cross-tenant global source reservation mismatch.")
            tenant_reads(admin, {"clients": clients, "accepted": accepted})
            control_ids = asyncio.run(defer_control_and_retention(), loop_factory=asyncio.SelectorEventLoop)
            wait_for(lambda: delivered(admin, list(control_ids)), "control/maintenance while execution slots blocked")
            # Require continued blocked work after independent roles finished.
            if not blocked_pair(admin):
                raise RuntimeError("Execution slots no longer held at independent-role observation.")
            for company, job, body in accepted:
                retained_source(admin, company, job, body)
            print("P19_BOUNDED_WORKER_BACKPRESSURE=" + json.dumps({"execution_slots": 2,
                "doing": 2, "todo": 2, "tenant_active_limit_fixture": 2, "admission_rejected": 2,
                "source_references": 4, "partial_rows": 0, "control_and_maintenance_succeeded": True,
                "cross_tenant_http_and_app_role_reads": "PASS"}), flush=True)
            for company in clients:
                admin.execute("SELECT pg_advisory_unlock(%s,%s)", (BARRIER, company))
            peak_doing = 2
            def drained():
                nonlocal peak_doing
                active = queue_snapshot(admin)
                peak_doing = max(peak_doing, sum(row[0] == "doing" for row in active))
                if any(process.poll() is not None for process, _ in processes):
                    raise RuntimeError("Owned Worker exited before completion.")
                return not active
            wait_for(drained, "four real imports complete", seconds=90)
            outcomes = []
            for company, job, _ in accepted:
                row = shared.require(clients[company].get(f"/simple-products/imports/{job}"), 200, "completed import")
                if row["status"] != "COMPLETED" or row["imported_rows"] != ROWS:
                    raise RuntimeError("Unexpected import terminal outcome.")
                evidence = _assert_business_evidence(admin, job, ROWS, company_id=company)
                physical = admin.execute("SELECT row_number,row_identity FROM product_import_rows "
                    "WHERE company_id=%s AND job_id=%s ORDER BY row_number", (company, job)).fetchall()
                if [x[0] for x in physical] != [2,3,4] or len({x[1] for x in physical}) != ROWS:
                    raise RuntimeError("Source row identity/physical number changed under contention.")
                delivery = admin.execute("SELECT status,attempts FROM procrastinate_jobs "
                    "WHERE task_name='wanasah.process_product_import' AND args->>'job_id'=%s", (job,)).fetchall()
                if delivery != [("succeeded", 1)]:
                    raise RuntimeError("Duplicate/retried queue delivery in healthy contention proof.")
                original_source = sources[accepted.index((company, job, _))]
                metadata = admin.execute("SELECT source_id::text,source_sha256,file_size FROM product_import_jobs "
                    "WHERE company_id=%s AND id=%s", (company, job)).fetchone()
                if metadata != (original_source, hashlib.sha256(_).hexdigest(), len(_)):
                    raise RuntimeError("Durable request source metadata changed during execution.")
                if admin.execute("SELECT j.source_payload_cleared_at IS NOT NULL,s.deleted_at IS NOT NULL "
                    "FROM product_import_jobs j JOIN product_import_sources s ON s.company_id=j.company_id "
                    "AND s.id=j.source_id WHERE j.company_id=%s AND j.id=%s", (company, job)).fetchone() != (True, True):
                    raise RuntimeError("Source cleanup not reconciled after atomic staging.")
                with admin.transaction(force_rollback=True):
                    admin.execute("SELECT id FROM product_import_jobs WHERE company_id=%s AND id=%s FOR UPDATE NOWAIT", (company, job))
                    admin.execute("SELECT id FROM product_import_rows WHERE company_id=%s AND job_id=%s FOR UPDATE NOWAIT", (company, job))
                outcomes.append({"company": company, "job_id": job, **evidence, "locks_available": True})
            if admin.execute("SELECT live_bytes FROM product_import_global_source_capacity WHERE id=1").fetchone() != (0,):
                raise RuntimeError("Source capacity not released after all jobs completed.")
            if admin.execute("SELECT company_id,live_bytes FROM product_import_tenant_source_capacity "
                "WHERE company_id IN (2,3) ORDER BY company_id").fetchall() != [(2,0),(3,0)]:
                raise RuntimeError("Tenant source capacity not released.")
            if admin.execute("SELECT count(*) FROM product_import_source_chunks WHERE company_id IN (2,3)").fetchone() != (0,):
                raise RuntimeError("Source chunks retained after successful staging cleanup.")
            before = business_snapshot(admin)
            counts = {table: len(rows) - len(baseline[table]) for table, rows in before.items()}
            if counts != {"products":12,"product_variants":12,"price_book_entries":24,
                "domain_audit_events":12,"transactional_outbox":12}:
                raise RuntimeError("Unexpected extra or missing business records.")
            print("P19_CONCURRENT_TENANT_COMPLETION=" + json.dumps({"jobs":outcomes,
                "totals":counts,"peak_doing_sampled":peak_doing,"source_capacity":0}, sort_keys=True), flush=True)
            result = retention_evidence(admin, accepted, before)
            print("P19_REAL_RETENTION=" + json.dumps(result, sort_keys=True), flush=True)
            print(MARKER, flush=True)
        finally:
            # Release only this observer's barriers BEFORE official cancellation.
            admin.execute("SELECT pg_advisory_unlock_all()")
            active = admin.execute("SELECT company_id,id::text FROM product_import_jobs "
                "WHERE company_id IN (2,3) AND status IN ('QUEUED','PARSING','NEEDS_MAPPING','VALIDATING','IMPORTING','RETRYING')").fetchall()
            for company, job in active:
                if company in clients:
                    response = clients[company].post(f"/simple-products/imports/{job}/cancel")
                    if response.status_code not in (202,409):
                        raise RuntimeError("Official cleanup cancellation failed.")
            wait_for(lambda: not queue_snapshot(admin), "owned imports drained before Worker shutdown", seconds=90)
            for process, handle in reversed(processes):
                shared.stop(process, handle)
            for client in clients.values():
                client.close()


if __name__ == "__main__":
    main()
