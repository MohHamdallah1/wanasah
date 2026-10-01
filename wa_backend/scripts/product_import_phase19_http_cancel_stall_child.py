"""Real HTTP CANCEL while an actual staging DELETE waits on a PostgreSQL table lock.

Disposable PG16+real Uvicorn+Workers ONLY. No customer or developer DB writes.
The runner owns both the lock and isolated server and always releases them.
"""
from __future__ import annotations

import os
import time
from uuid import uuid4

import httpx
import psycopg
from sqlalchemy.engine import make_url

if os.environ.get("WANASAH_P19_HTTP_DISPOSABLE_CHILD") != "1":
    raise RuntimeError("CANCEL/lock-stall scenario requires a guarded disposable child.")
if os.environ.get("WANASAH_P19_CANCEL_STALL_CONFIRM") != "ISOLATED_LOCK_ONLY":
    raise RuntimeError("Explicit synthetic-only locked-staging cancellation authorization required.")
dsn = make_url(os.environ.get("DATABASE_URL", ""))
admin_dsn = make_url(os.environ.get("DATABASE_URL_MIGRATION", ""))
for target in (dsn, admin_dsn):
    if (target.database != "p19_http_synthetic"
        or target.host != "127.0.0.1"
        or int(target.port or 0) != 55446):
        raise RuntimeError("Refusing staging-stall test outside disposable 55446 DB.")

from api.auth import create_access_token
from scripts import product_import_phase19_http_isolated_child as shared
from scripts.run_product_import_phase19_live_load import build_source

ROWS = 5000
TERMINAL = {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED", "VALIDATION_FAILED", "CANCELLED"}


def main() -> None:
    admin_url = admin_dsn.set(drivername="postgresql").render_as_string(hide_password=False)
    admin = psycopg.connect(admin_url, autocommit=True)
    holder = psycopg.connect(admin_url, autocommit=False)
    processes = []
    try:
        companies = [
            int(admin.execute("SELECT count(*) FROM companies WHERE id=%s", (number,)).fetchone()[0])
            for number in (2, 3)
        ]
        if companies != [1, 1]:
            raise RuntimeError("Synthetic tenant fixtures missing.")
        primary = create_access_token({"sub": "1", "is_admin": True}, 2, "Admin")
        foreign = create_access_token({"sub": "2", "is_admin": True}, 3, "Admin")

        processes.append(shared.start(
            "cancel-lock-http-server", "-m",
            "scripts.product_import_phase19_http_selector_server",
        ))
        for role in ("control", "maintenance", "execution"):
            processes.append(shared.start(
                f"cancel-lock-{role}", "-m",
                "domains.simple_products.imports.infrastructure.worker_cli",
                "--role", role,
            ))

        with (
            httpx.Client(base_url=shared.BASE, timeout=40.0,
                         headers={"Authorization": f"Bearer {primary}"}) as client,
            httpx.Client(base_url=shared.BASE, timeout=40.0,
                         headers={"Authorization": f"Bearer {foreign}"}) as other,
        ):
            shared.wait_health(client, processes)
            shared.wait_worker(client)

            # Acquire this test's EXCLUSIVE table lock *before* submitting
            # a new synthetic job, so the Worker must reach an actual
            # PostgreSQL lock wait in the first staging DELETE statement.
            # All transactions and teardown exist only in the owned cluster.
            holder.execute(
                "LOCK TABLE public.product_import_rows IN ACCESS EXCLUSIVE MODE"
            )
            source, _mapping, _prefix = build_source(
                ROWS, "P19-HTTP-LOCKED-CANCEL-" + uuid4().hex[:12]
            )
            response = shared.require(
                client.post(
                    "/simple-products/imports",
                    data={
                        "request_id": str(uuid4()),
                        "default_lot_control_mode": "NONE",
                        "default_expiry_control_mode": "NONE",
                    },
                    files={"file": ("p19-locked-cancel.csv", source, "text/csv")},
                ),
                202,
                "new isolated locked-cancel admission",
            )
            job = str(response["job_id"])
            waiting = False
            saw_parsing = False
            cutoff = time.monotonic() + 75
            while time.monotonic() < cutoff:
                job_state = admin.execute(
                    "SELECT status FROM product_import_jobs "
                    "WHERE company_id=2 AND id=%s", (job,)
                ).fetchone()
                if job_state and str(job_state[0]) == "PARSING":
                    saw_parsing = True
                waiting_workers = admin.execute(
                    "SELECT count(DISTINCT l.pid) FROM pg_locks AS l "
                    "JOIN pg_stat_activity AS a ON a.pid=l.pid "
                    "WHERE l.relation='public.product_import_rows'::regclass "
                    "AND NOT l.granted AND a.datname=current_database()"
                ).fetchone()[0]
                if saw_parsing and int(waiting_workers) > 0:
                    waiting = True
                    break
                time.sleep(0.2)
            if not waiting:
                raise RuntimeError(
                    "No genuine PostgreSQL staging table-lock wait was observed."
                )
            print("P19_HTTP_ACTUAL_STAGING_SQL_LOCK_WAIT=PASS", flush=True)
            # This is a live HTTP route with real auth/permission checks, not
            # a direct call to cancel_import_job().
            cancelled = shared.require(
                client.post(f"/simple-products/imports/{job}/cancel"),
                202,
                "official HTTP cancel during real SQL lock wait",
            )
            if cancelled.get("status") != "CANCELLED":
                raise RuntimeError("HTTP cancel did not durably acknowledge CANCELLED.")
            shared.require(
                other.post(f"/simple-products/imports/{job}/cancel"),
                404,
                "cross-company cancellation must not see foreign job",
            )
            print("P19_OFFICIAL_HTTP_CANCEL_WHILE_STAGING_LOCKED=PASS", flush=True)
            print("P19_FOREIGN_TENANT_CANCEL_DENIED=PASS", flush=True)

            # Let the original Worker see the committed CANCELLED status,
            # rollback its whole staging transaction, and clean SourceStore.
            holder.rollback()
            cutoff = time.monotonic() + 140
            final = None
            while time.monotonic() < cutoff:
                state = admin.execute(
                    "SELECT status, processed_rows, source_payload_cleared_at "
                    "FROM product_import_jobs WHERE company_id=2 AND id=%s",
                    (job,),
                ).fetchone()
                active = admin.execute(
                    "SELECT count(*) FROM procrastinate_jobs "
                    "WHERE task_name='wanasah.process_product_import' "
                    "AND args->>'job_id'=%s AND status IN ('doing','todo')",
                    (job,),
                ).fetchone()[0]
                if (state and str(state[0]) == "CANCELLED"
                    and state[2] is not None and not active):
                    final = state
                    break
                time.sleep(0.4)
            if final is None:
                raise RuntimeError(
                    "Cancelled staging Worker did not release queue/source within bounded window."
                )
            if int(final[1]) != 0:
                raise RuntimeError("Cancelled staging published processed Products.")
            persisted = admin.execute(
                "SELECT count(*),count(product_variant_id) "
                "FROM product_import_rows WHERE company_id=2 AND job_id=%s", (job,)
            ).fetchone()
            if tuple(map(int, persisted)) != (0, 0):
                raise RuntimeError("Cancelled staging transaction retained partial row/variant writes.")
            print("P19_CANCELLED_STAGING_ATOMIC_ROLLBACK=PASS", flush=True)
            print("P19_CANCELLED_SOURCESTORE_CLEAR=PASS", flush=True)
            print("P19_CANCELLED_QUEUE_INACTIVE=PASS", flush=True)
            print("PRODUCT_IMPORT_P19_REAL_HTTP_LOCK_CANCEL=PASS", flush=True)
    finally:
        try:
            holder.rollback()
        finally:
            holder.close()
        for process, handle in reversed(processes):
            shared.stop(process, handle)
        admin.close()


if __name__ == "__main__":
    main()
