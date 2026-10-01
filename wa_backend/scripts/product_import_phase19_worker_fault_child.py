"""Four small real PG/HTTP/Worker fault proofs inside the existing P19 runner."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

import httpx
import psycopg
from sqlalchemy import event, text
from sqlalchemy.engine import make_url

if (os.environ.get("WANASAH_P19_HTTP_DISPOSABLE_CHILD") != "1" or
    os.environ.get("WANASAH_P19_WORKER_FAULT_CONFIRM") != "ISOLATED_SYNTHETIC_ONLY"):
    raise RuntimeError("Worker faults require explicit disposable-only authorization.")
for key in ("DATABASE_URL", "DATABASE_URL_MIGRATION"):
    target = make_url(os.environ.get(key, ""))
    if (target.host != "127.0.0.1" or target.database != "p19_http_synthetic" or
        int(target.port or 0) != 55446):
        raise RuntimeError("Refusing faults outside the disposable P19 database.")

from api.auth import create_access_token
from scripts import product_import_phase19_http_isolated_child as shared
from scripts.product_import_phase19_pg_wire_fault import CommitFaultProxy, PROXY_PORT
from scripts.run_product_import_phase19_live_load import build_source

ADMIN_URL = make_url(os.environ["DATABASE_URL_MIGRATION"]).set(
    drivername="postgresql").render_as_string(hide_password=False)
ROWS = 6
SELECTED = tuple(os.environ.get("WANASAH_P19_WORKER_FAULT_CASES",
    "pre_ping,staging_abort,staging_commit,execution_commit").split(","))
if (not SELECTED or len(set(SELECTED)) != len(SELECTED) or
    not set(SELECTED) <= {"pre_ping", "staging_abort", "staging_commit", "execution_commit"}):
    raise RuntimeError("Unknown or duplicate small fault case.")
MARKER = "PRODUCT_IMPORT_P19_REAL_WORKER_FAULTS=PASS"


def wait_for(probe, label: str, seconds: float = 35):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = probe()
        if result:
            return result
        time.sleep(.05)
    raise RuntimeError("Bounded fault proof did not complete: " + label)


async def pre_ping_probe() -> dict:
    """Use the actual execution process's engine, pool and tenant setup."""
    from database import engine
    from domains.simple_products.imports.infrastructure.repository import (
        open_tenant_session, close_tenant_session,
    )
    pings = []
    invalidations = []
    original = engine.sync_engine.dialect.do_ping

    def ping(connection):
        pings.append(True)
        return original(connection)

    def invalidated(connection, record, exception):
        invalidations.append(type(exception).__name__)

    engine.sync_engine.dialect.do_ping = ping
    event.listen(engine.sync_engine, "invalidate", invalidated)
    try:
        token, db = await open_tenant_session(2)
        try:
            old = int((await db.execute(text("SELECT pg_backend_pid()"))).scalar_one())
        finally:
            await close_tenant_session(token, db)
        # Kill ONLY the returned PID in this disposable process's real pool.
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            killed = admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE pid=%s AND datname='p19_http_synthetic' "
                "AND application_name='p19-fault-execution'", (old,),
            ).fetchone()
            if killed != (True,):
                raise RuntimeError("Owned dead-pool connection was not terminated.")
        token, db = await open_tenant_session(3)
        try:
            new, tenant, foreign = (await db.execute(text(
                "SELECT pg_backend_pid(),current_setting('app.current_tenant'),"
                "(SELECT count(*) FROM products WHERE company_id=2)"
            ))).one()
            if int(new) == old or str(tenant) != "3" or int(foreign) != 0:
                raise RuntimeError("Dead checkout was not replaced with correct tenant context.")
        finally:
            await close_tenant_session(token, db)
        if not pings or not invalidations:
            raise RuntimeError("Actual pre-ping/invalidation was not observed.")
        return {"old_pid": old, "replacement_pid": int(new),
                "ping_calls": len(pings), "invalidations": invalidations,
                "replacement_tenant": str(tenant), "foreign_products": int(foreign)}
    finally:
        engine.sync_engine.dialect.do_ping = original
        event.remove(engine.sync_engine, "invalidate", invalidated)


def worker() -> None:
    # A test-only transport observer surrounds the canonical worker entrypoint.
    # Queue/Psycopg stays direct at 55446; only asyncpg uses the owned proxy.
    from database import engine
    from domains.simple_products.imports.infrastructure import worker_cli

    @event.listens_for(engine.sync_engine, "do_connect")
    def route_owned_engine(dialect, connection_record, args, params):
        params["port"] = PROXY_PORT
        params["ssl"] = False  # disposable localhost cluster only, never production
        params["server_settings"] = {
            **params.get("server_settings", {}),
            "application_name": "p19-fault-execution",
        }

    original_run = worker_cli.run

    async def observed_run(role):
        if role != "execution":
            raise RuntimeError("Fault wrapper is execution-only.")
        if "pre_ping" in SELECTED:
            proof = await pre_ping_probe()
            (shared.LOG_DIR / "pre-ping.json").write_text(json.dumps(proof), encoding="utf-8")
        await original_run(role)

    worker_cli.run = observed_run
    sys.argv = [sys.argv[0], "--role", "execution"]
    worker_cli.main()


def source_proof(admin, job: str, payload: bytes) -> dict:
    state = admin.execute(
        "SELECT j.status,j.source_id,j.source_payload_cleared_at,s.sha256,s.byte_size,"
        "s.deleted_at FROM product_import_jobs j JOIN product_import_sources s "
        "ON s.company_id=j.company_id AND s.id=j.source_id WHERE j.company_id=2 AND j.id=%s",
        (job,),
    ).fetchone()
    chunks = admin.execute(
        "SELECT payload FROM product_import_source_chunks WHERE company_id=2 "
        "AND source_id=%s ORDER BY chunk_index", (state[1],),
    ).fetchall()
    retained = b"".join(bytes(item[0]) for item in chunks)
    digest = hashlib.sha256(payload).hexdigest()
    if (state[2] is not None or state[5] is not None or state[3] != digest or
        int(state[4]) != len(payload) or retained != payload):
        raise RuntimeError("SourceStore bytes/reference/hash lost before retry.")
    return {"status": str(state[0]), "source_id": str(state[1]),
            "bytes": len(retained), "sha256": digest, "chunks": len(chunks)}


def row_identity(admin, job):
    return admin.execute(
        "SELECT row_number,row_identity,raw_data FROM product_import_rows "
        "WHERE company_id=2 AND job_id=%s ORDER BY row_number", (job,),
    ).fetchall()


def business_snapshot(admin, job):
    identities = admin.execute(
        "SELECT r.row_identity,r.product_variant_id,v.version,p.id,p.version "
        "FROM product_import_rows r JOIN product_variants v "
        "ON v.company_id=r.company_id AND v.id=r.product_variant_id "
        "JOIN products p ON p.company_id=v.company_id AND p.id=v.product_id "
        "WHERE r.company_id=2 AND r.job_id=%s ORDER BY r.row_number", (job,),
    ).fetchall()
    ids = [int(row[1]) for row in identities]
    return {
        "identity": identities,
        "prices": admin.execute("SELECT id,product_variant_id,publication_id,version "
            "FROM price_book_entries WHERE company_id=2 AND product_variant_id=ANY(%s) "
            "ORDER BY id", (ids,)).fetchall(),
        "audit": admin.execute("SELECT id,entity_id FROM domain_audit_events "
            "WHERE company_id=2 AND entity_type='ProductVariant' AND entity_id=ANY(%s) "
            "ORDER BY id", ([str(i) for i in ids],)).fetchall(),
        "outbox": admin.execute("SELECT id,aggregate_id FROM transactional_outbox "
            "WHERE company_id=2 AND aggregate_type='ProductVariant' AND aggregate_id=ANY(%s) "
            "ORDER BY id", ([str(i) for i in ids],)).fetchall(),
    }


def totals(admin):
    return {table: int(admin.execute(
        "SELECT count(*) FROM " + table + " WHERE company_id=2").fetchone()[0])
        for table in ("products", "product_variants", "price_book_entries",
                      "domain_audit_events", "transactional_outbox")}


def unlocked(admin, job) -> None:
    # Test-only probe: acquire scoped job and all six row locks, then rollback.
    with admin.transaction(force_rollback=True):
        admin.execute("SELECT id FROM product_import_jobs WHERE company_id=2 AND id=%s "
                      "FOR UPDATE NOWAIT", (job,)).fetchall()
        admin.execute("SELECT id FROM product_import_rows WHERE company_id=2 AND job_id=%s "
                      "FOR UPDATE NOWAIT", (job,)).fetchall()


def complete(client, admin, job, processes):
    result = shared.wait_job(client, job, valid_states={"COMPLETED"}, seconds=90)
    if int(result["imported_rows"]) != ROWS:
        raise RuntimeError("Incorrect real imported counter after retry.")
    deliveries = wait_for(lambda: admin.execute(
        "SELECT attempts,status FROM procrastinate_jobs "
        "WHERE task_name='wanasah.process_product_import' AND args->>'job_id'=%s "
        "AND status NOT IN ('todo','doing')", (job,),
    ).fetchall(), "queue retry completion")
    if len(deliveries) != 1 or int(deliveries[0][0]) < 2 or str(deliveries[0][1]) != "succeeded":
        raise RuntimeError("No actual failed attempt plus successful queue retry.")
    if admin.execute("SELECT count(*) FROM procrastinate_jobs WHERE "
        "task_name='wanasah.process_product_import' AND args->>'job_id'=%s "
        "AND status IN ('todo','doing')", (job,)).fetchone()[0]:
        raise RuntimeError("Active queue delivery retained.")
    evidence = shared.verify_job(admin, job, ROWS)
    if admin.execute("SELECT source_payload_cleared_at IS NOT NULL FROM "
        "product_import_jobs WHERE company_id=2 AND id=%s", (job,)).fetchone() != (True,):
        raise RuntimeError("SourceStore cleanup not marked after durable staging.")
    unlocked(admin, job)
    if any(process.poll() is not None for process, _ in processes):
        raise RuntimeError("Owned worker exited during retry.")
    return {"evidence": evidence, "queue_attempts": int(deliveries[0][0]),
            "queue_status": str(deliveries[0][1]), "job_and_row_locks_available": True}


def run_case(client, admin, proxy, processes, case):
    before_totals = totals(admin)
    proxy.arm(case)
    if case == "staging_abort":
        admin.execute("UPDATE p19_fault_control SET enabled=true")
    payload, _, _ = build_source(ROWS, "P19FAULT" + uuid4().hex[:12])
    started = time.monotonic()
    admitted = shared.require(client.post("/simple-products/imports", data={
        "request_id": str(uuid4()), "default_lot_control_mode": "NONE",
        "default_expiry_control_mode": "NONE",
    }, files={"file": ("synthetic-fault.csv", payload, "text/csv")}), 202, case)
    job = admitted["job_id"]
    boundary = proxy.wait_observed()
    pid = int(boundary["backend_pid"])
    if not pid:
        raise RuntimeError("Fault target has no real backend PID.")
    snapshot = None
    if case == "staging_abort":
        wait_for(lambda: admin.execute(
            "SELECT 1 FROM pg_stat_activity WHERE pid=%s AND "
            "datname=current_database() AND application_name='p19-fault-execution' "
            "AND wait_event='PgSleep' AND query LIKE 'INSERT INTO product_import_rows%%'",
            (pid,),
        ).fetchone(), "real staging INSERT sleep")
        retained_before = source_proof(admin, job, payload)
        proxy.release()
        # Enqueue this probe BEFORE the queue retries (3s). A TCP EOF need
        # not interrupt PostgreSQL's active computation; the bounded single
        # 8s sleep finishes, then its uncommitted transaction rolls back.
        admin.execute("SET statement_timeout='20s'")
        admin.execute("SELECT pg_advisory_lock(19190,1)")
        admin.execute("SET statement_timeout=0")
        wait_for(lambda: not admin.execute(
            "SELECT 1 FROM pg_stat_activity WHERE pid=%s", (pid,),
        ).fetchone(), "disconnected staging backend release")
        # Keep the released lock while proving source retention/zero staging.
        # The real queued retry cannot pass the same trigger until we release.
        try:
            retained = source_proof(admin, job, payload)
            if retained["source_id"] != retained_before["source_id"] or row_identity(admin, job):
                raise RuntimeError("Abort lost source identity or committed partial staging.")
            admin.execute("UPDATE p19_fault_control SET enabled=false")
        finally:
            admin.execute("SELECT pg_advisory_unlock(19190,1)")
        identity = None
    else:
        if not boundary["server_commit_seen"] or boundary["command_complete_forwarded"]:
            raise RuntimeError("COMMIT ACK was not truly lost on the wire.")
        durable = admin.execute("SELECT status,processed_rows FROM product_import_jobs "
                                "WHERE company_id=2 AND id=%s", (job,)).fetchone()
        expected = "VALIDATING" if case == "staging_commit" else "IMPORTING"
        if str(durable[0]) != expected:
            raise RuntimeError("Unexpected durable state at lost-COMMIT boundary.")
        identity = row_identity(admin, job)
        if len(identity) != ROWS:
            raise RuntimeError("COMMIT did not preserve the entire staged identity set.")
        unlocked(admin, job)
        if case == "staging_commit":
            retained = source_proof(admin, job, payload)
        else:
            retained = {"cleared_after_staging": True}
            shared.verify_job(admin, job, ROWS)
            snapshot = business_snapshot(admin, job)
            committed_totals = totals(admin)
        proxy.release()
    final = complete(client, admin, job, processes)
    if identity is not None and identity != row_identity(admin, job):
        raise RuntimeError("Retry replaced durable original rows/cells/identities.")
    after_totals = totals(admin)
    if (after_totals["products"] - before_totals["products"] != ROWS or
        after_totals["product_variants"] - before_totals["product_variants"] != ROWS):
        raise RuntimeError("Orphan or duplicate Product/Variant beyond row links.")
    if snapshot is not None and (
        snapshot != business_snapshot(admin, job) or committed_totals != after_totals
    ):
        raise RuntimeError("Lost execution ACK replay duplicated/mutated business evidence.")
    evidence = {"case": case, "job_id": job, "wire": boundary,
                "source": retained, **final,
                "table_delta": {k: after_totals[k] - before_totals[k] for k in after_totals},
                "admission_to_recovered_seconds": round(time.monotonic() - started, 3),
                "durable_row_identity_unchanged": identity is not None}
    print("P19_WORKER_FAULT_RESULT=" + json.dumps(evidence, default=str), flush=True)
    return evidence


def main() -> None:
    admin = psycopg.connect(ADMIN_URL, autocommit=True)
    processes = []
    proxy = CommitFaultProxy()
    cases = []
    primary = create_access_token({"sub": "1", "is_admin": True}, 2, "Admin")
    try:
        # Disposable-only trigger makes the actual INSERT observable before
        # cutting its owned TCP transport. Production deadlines stay unchanged.
        admin.execute("CREATE TABLE p19_fault_control(enabled boolean NOT NULL)")
        admin.execute("INSERT INTO p19_fault_control VALUES(false)")
        admin.execute("""
            CREATE FUNCTION p19_fault_insert() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              PERFORM pg_advisory_xact_lock(19190,1);
              IF NEW.row_number=2 AND (SELECT enabled FROM p19_fault_control) THEN PERFORM pg_sleep(8); END IF;
              RETURN NEW;
            END $$;
            CREATE TRIGGER p19_fault_insert BEFORE INSERT ON product_import_rows
              FOR EACH ROW WHEN (NEW.company_id=2) EXECUTE FUNCTION p19_fault_insert();
            GRANT SELECT ON p19_fault_control TO wanasah_app;
        """)
        processes.append(shared.start("fault-http", "-m",
            "scripts.product_import_phase19_http_selector_server"))
        for role in ("control", "maintenance"):
            processes.append(shared.start("fault-" + role, "-m",
                "domains.simple_products.imports.infrastructure.worker_cli", "--role", role))
        processes.append(shared.start("fault-execution", "-m",
            "scripts.product_import_phase19_worker_fault_child", "--worker"))
        with httpx.Client(base_url=shared.BASE, timeout=40,
                          headers={"Authorization": f"Bearer {primary}"}) as client:
            shared.wait_health(client, processes)
            shared.wait_worker(client)
            if "pre_ping" in SELECTED:
                probe = json.loads((shared.LOG_DIR / "pre-ping.json").read_text(encoding="utf-8"))
                print("P19_REAL_POOL_PRE_PING=" + json.dumps(probe), flush=True)
            for case in (case for case in SELECTED if case != "pre_ping"):
                cases.append(run_case(client, admin, proxy, processes, case))
        print(MARKER, flush=True)
    except Exception as exc:
        print("P19_FAULT_GATE_FAILURE_CLASS=" + type(exc).__name__, flush=True)
        for process, _ in processes:
            log = shared.LOG_DIR / (process.p19_label + ".log")
            if log.exists():
                classes = []
                for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                    head = line.strip().split(":", 1)[0]
                    if (head.endswith(("Error", "Exception")) and
                        all(c.isalnum() or c in "._" for c in head)):
                        classes.append(head[-120:])
                print("P19_COMPONENT_ERROR_CLASSES=" + process.p19_label + ":" +
                      json.dumps(classes[-6:]), flush=True)
        raise
    finally:
        # No active import is force-killed. Attempt the official cancellation
        # route for owned unfinished jobs on failure, then await queue drain.
        if len(cases) != len([case for case in SELECTED if case != "pre_ping"]):
            with httpx.Client(base_url=shared.BASE, timeout=10,
                              headers={"Authorization": f"Bearer {primary}"}) as client:
                active = admin.execute("SELECT id FROM product_import_jobs "
                    "WHERE company_id=2 AND status IN ('QUEUED','PARSING','VALIDATING','IMPORTING')"
                ).fetchall()
                for (job,) in active:
                    response = client.post(f"/simple-products/imports/{job}/cancel")
                    if response.status_code != 202:
                        raise RuntimeError("Owned-job official failure cleanup could not cancel.")
                proxy.release() if proxy.target is not None else None
                wait_for(lambda: admin.execute("SELECT count(*) FROM procrastinate_jobs "
                    "WHERE task_name='wanasah.process_product_import' AND status IN ('doing','todo')"
                ).fetchone()[0] == 0, "official cancel drain", seconds=70)
        for process, handle in reversed(processes):
            shared.stop(process, handle)
        proxy.close()
        admin.close()


if __name__ == "__main__":
    if "--worker" in sys.argv:
        worker()
    else:
        main()
