"""D4 child: orphan reconciliation, staging cancellation and hard-crash recovery."""
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
from uuid import NAMESPACE_URL, uuid5

import psycopg
from sqlalchemy.engine import make_url

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if os.getenv("WANASAH_D4_DISPOSABLE_CHILD") != "1":
    raise RuntimeError("D4 child may run only inside disposable runner.")
if "127.0.0.1:55443/d4_recovery" not in os.getenv("DATABASE_URL", ""):
    raise RuntimeError("D4 child refuses non-disposable database.")

from database import engine
from domains.simple_products.imports.application.api_service import create_import
from domains.simple_products.imports.application.cancellation_service import cancel_import_job
from domains.simple_products.imports.infrastructure.queue import (
    app,
    recover_stalled_product_imports,
)
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    open_tenant_session,
)
from scripts.run_product_import_phase19_live_load import build_source

TERMINAL = {
    "COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED",
    "VALIDATION_FAILED", "CANCELLED", "NEEDS_MAPPING",
}


def _dsn(name: str) -> str:
    return make_url(os.environ[name]).set(
        drivername="postgresql"
    ).render_as_string(hide_password=False)


async def _submit(rows: int, label: str) -> tuple[str, int]:
    data, _mapping, _prefix = build_source(rows, label)
    token, db = await open_tenant_session(2)
    try:
        result = await create_import(
            db,
            company_id=2,
            actor_id=1,
            request_id=uuid5(NAMESPACE_URL, "wanasah:d4:" + label),
            file_name=label + ".csv",
            content_type="text/csv",
            source_stream=io.BytesIO(data),
            source_size=len(data),
            source_sha256=hashlib.sha256(data).hexdigest(),
            default_lot_control_mode="NONE",
            default_expiry_control_mode="NONE",
        )
        await db.commit()
        return str(result["job_id"]), rows - (rows // 100)
    finally:
        await close_tenant_session(token, db)


def _start_worker(label: str) -> tuple[subprocess.Popen, object, pathlib.Path]:
    log_path = pathlib.Path(os.environ["WANASAH_D4_LOG_DIR"]) / f"{label}.log"
    handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable, "-m",
            "domains.simple_products.imports.infrastructure.worker_cli",
            "--role", "execution",
        ],
        cwd=ROOT,
        env=os.environ.copy(),
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return process, handle, log_path


def _stop_worker(process: subprocess.Popen, handle) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    handle.close()


def _job(admin: psycopg.Connection, job_id: str):
    return admin.execute(
        """
        SELECT status, processed_rows, failed_rows, total_rows,
               source_payload_cleared_at
        FROM product_import_jobs
        WHERE company_id=2 AND id=%s
        """,
        (job_id,),
    ).fetchone()


def _wait_status(
    admin: psycopg.Connection,
    job_id: str,
    predicate,
    *,
    timeout: float = 120.0,
):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = _job(admin, job_id)
        if last is not None and predicate(last):
            return last
        time.sleep(0.03)
    raise RuntimeError(f"D4 status timeout job={job_id} last={last}")


async def _recover() -> dict[str, int]:
    async with app.open_async():
        return await recover_stalled_product_imports()


def _queue_rows(admin: psycopg.Connection, job_id: str):
    return admin.execute(
        """
        SELECT id,status,lock,queueing_lock,worker_id
        FROM procrastinate_jobs
        WHERE task_name='wanasah.process_product_import'
          AND args->>'job_id'=%s
        ORDER BY id
        """,
        (job_id,),
    ).fetchall()


def _wait_queue_inactive(
    admin: psycopg.Connection,
    job_id: str,
    *,
    timeout: float = 15.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        active = [
            row for row in _queue_rows(admin, job_id)
            if str(row[1]) in {"todo", "doing"}
        ]
        if not active:
            return
        time.sleep(0.03)
    raise RuntimeError(
        f"D4 queue delivery stayed active after business completion: {active}"
    )


from scripts.product_import_business_integrity_gate import (
    _assert_business_evidence,
)


async def main() -> None:
    admin = psycopg.connect(_dsn("DATABASE_URL_MIGRATION"), autocommit=True)
    try:
        # A. Simulate a durable business job whose queue delivery vanished.
        orphan_id, orphan_expected = await _submit(300, "D4-ORPHAN")
        original_queue = _queue_rows(admin, orphan_id)
        if len(original_queue) != 1:
            raise RuntimeError(f"D4 orphan setup queue mismatch: {original_queue}")
        admin.execute(
            "DELETE FROM procrastinate_jobs "
            "WHERE task_name='wanasah.process_product_import' "
            "AND args->>'job_id'=%s",
            (orphan_id,),
        )
        admin.execute(
            "UPDATE product_import_jobs "
            "SET updated_at=CURRENT_TIMESTAMP - interval '10 minutes' "
            "WHERE company_id=2 AND id=%s",
            (orphan_id,),
        )
        first_recovery = await _recover()
        second_recovery = await _recover()
        all_recovered_queue = _queue_rows(admin, orphan_id)
        recovered_queue = [
            row for row in all_recovered_queue
            if str(row[1]) in {"todo", "doing"}
        ]
        if len(recovered_queue) != 1:
            raise RuntimeError(
                "D4 orphan recovery delivery mismatch: "
                f"active={recovered_queue} all={all_recovered_queue} "
                f"first={first_recovery} second={second_recovery}"
            )
        if recovered_queue[0][3] != f"product-import-job:{orphan_id}":
            raise RuntimeError("D4 orphan recovery missing job-scoped queueing lock.")
        if int(first_recovery.get("orphan_requeued", 0)) < 1:
            raise RuntimeError(f"D4 orphan was not reconciled: {first_recovery}")
        if int(second_recovery.get("orphan_requeued", 0)) != 0:
            raise RuntimeError(f"D4 second recovery duplicated active delivery: {second_recovery}")

        worker, handle, log = _start_worker("orphan-worker")
        try:
            orphan_final = _wait_status(
                admin, orphan_id, lambda row: str(row[0]) in TERMINAL
            )
            _wait_queue_inactive(admin, orphan_id)
        finally:
            _stop_worker(worker, handle)
        if str(orphan_final[0]) != "COMPLETED_WITH_ERRORS":
            raise RuntimeError(f"D4 orphan final status: {orphan_final}")
        if orphan_final[4] is None:
            raise RuntimeError("D4 orphan retained source was not cleaned.")
        orphan_evidence = _assert_business_evidence(
            admin, orphan_id, orphan_expected
        )

        # B. Cancel while the worker is in PARSING/staging path.
        worker, handle, log = _start_worker("cancel-worker")
        try:
            cancel_id, _cancel_expected = await _submit(5000, "D4-CANCEL")
            _wait_status(
                admin, cancel_id, lambda row: str(row[0]) == "PARSING", timeout=45
            )
            cancelled = await cancel_import_job(company_id=2, job_id=__import__("uuid").UUID(cancel_id))
            if cancelled != "CANCELLED":
                raise RuntimeError(f"D4 cancellation returned {cancelled}")
            cancel_final = _wait_status(
                admin,
                cancel_id,
                lambda row: str(row[0]) == "CANCELLED" and row[4] is not None,
                timeout=60,
            )
            _wait_queue_inactive(admin, cancel_id)
        finally:
            _stop_worker(worker, handle)
        linked_after_cancel = int(admin.execute(
            """
            SELECT count(*) FROM product_import_rows
            WHERE company_id=2 AND job_id=%s AND product_variant_id IS NOT NULL
            """,
            (cancel_id,),
        ).fetchone()[0])
        if int(cancel_final[1]) != 0 or linked_after_cancel != 0:
            raise RuntimeError(
                f"D4 staging cancellation leaked business effects "
                f"processed={cancel_final[1]} linked={linked_after_cancel}"
            )

        # C. Hard-kill an execution worker after at least one committed batch.
        crash_id, crash_expected = await _submit(3000, "D4-CRASH")
        worker, handle, log = _start_worker("crash-before")
        try:
            before_crash = _wait_status(
                admin,
                crash_id,
                lambda row: str(row[0]) == "IMPORTING" and int(row[1] or 0) >= 100,
                timeout=90,
            )
            queue_before = [
                row for row in _queue_rows(admin, crash_id)
                if str(row[1]) == "doing"
            ]
            if len(queue_before) != 1 or queue_before[0][4] is None:
                raise RuntimeError(f"D4 crash setup has no doing worker: {queue_before}")
            worker_id = int(queue_before[0][4])
            worker.kill()
            worker.wait(timeout=10)
        finally:
            _stop_worker(worker, handle)

        admin.execute(
            "UPDATE procrastinate_workers "
            "SET last_heartbeat=CURRENT_TIMESTAMP - interval '2 minutes' "
            "WHERE id=%s",
            (worker_id,),
        )
        crash_recovery = await _recover()
        if int(crash_recovery.get("retried", 0)) < 1:
            raise RuntimeError(f"D4 stalled queue job was not retried: {crash_recovery}")

        worker, handle, log = _start_worker("crash-after")
        try:
            crash_final = _wait_status(
                admin, crash_id, lambda row: str(row[0]) in TERMINAL, timeout=150
            )
            _wait_queue_inactive(admin, crash_id)
        finally:
            _stop_worker(worker, handle)
        if str(crash_final[0]) != "COMPLETED_WITH_ERRORS":
            raise RuntimeError(f"D4 crash final status: {crash_final}")
        if int(crash_final[1]) != crash_expected:
            raise RuntimeError(
                f"D4 crash processed mismatch {crash_final[1]} != {crash_expected}"
            )
        if crash_final[4] is None:
            raise RuntimeError("D4 crash source was not cleaned.")
        crash_evidence = _assert_business_evidence(
            admin, crash_id, crash_expected
        )
        active_delivery = int(admin.execute(
            """
            SELECT count(*) FROM procrastinate_jobs
            WHERE task_name='wanasah.process_product_import'
              AND args->>'job_id'=%s AND status IN ('todo','doing')
            """,
            (crash_id,),
        ).fetchone()[0])
        if active_delivery:
            raise RuntimeError("D4 crash recovery left active duplicate delivery.")

        result = {
            "orphan": {
                "first_recovery": first_recovery,
                "second_recovery": second_recovery,
                "evidence": orphan_evidence,
            },
            "cancel": {
                "status": str(cancel_final[0]),
                "processed": int(cancel_final[1]),
                "linked_variants": linked_after_cancel,
            },
            "crash": {
                "processed_before_kill": int(before_crash[1]),
                "recovery": crash_recovery,
                "evidence": crash_evidence,
            },
        }
        print("D4_RESULT=" + json.dumps(result, separators=(",", ":")), flush=True)
        print("PRODUCT_IMPORT_D4_ISOLATED_GATE=PASS", flush=True)
    finally:
        admin.close()
        await engine.dispose()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.run(
            main(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    else:
        asyncio.run(main())
