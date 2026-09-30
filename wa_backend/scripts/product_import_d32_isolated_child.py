"""D3.2 child: real queue/import concurrency inside disposable PostgreSQL only."""
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
from statistics import median
from uuid import NAMESPACE_URL, uuid5

import psycopg
from sqlalchemy.engine import make_url

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if os.getenv("WANASAH_D32_DISPOSABLE_CHILD") != "1":
    raise RuntimeError("D3.2 child may run only inside disposable runner.")
if "127.0.0.1:55442/d32_" not in os.getenv("DATABASE_URL", ""):
    raise RuntimeError("D3.2 child refuses non-disposable database.")

from database import engine
from domains.simple_products.imports.application.api_service import create_import
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    open_tenant_session,
)
from scripts.run_product_import_phase19_live_load import build_source

TERMINAL = {
    "COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED",
    "VALIDATION_FAILED", "CANCELLED", "NEEDS_MAPPING",
}
def _psycopg_url(name: str) -> str:
    return make_url(os.environ[name]).set(
        drivername="postgresql"
    ).render_as_string(hide_password=False)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * 0.95)))
    return ordered[index]


async def _submit(company_id: int, actor_id: int, run_id: str, rows: int) -> str:
    data, _mapping, _prefix = build_source(rows, run_id)
    token, db = await open_tenant_session(company_id)
    try:
        result = await create_import(
            db,
            company_id=company_id,
            actor_id=actor_id,
            request_id=uuid5(NAMESPACE_URL, "wanasah:d32:" + run_id),
            file_name=run_id + ".csv",
            content_type="text/csv",
            source_stream=io.BytesIO(data),
            source_size=len(data),
            source_sha256=hashlib.sha256(data).hexdigest(),
            default_lot_control_mode="NONE",
            default_expiry_control_mode="NONE",
        )
        await db.commit()
        return str(result["job_id"])
    finally:
        await close_tenant_session(token, db)


async def _enqueue(
    long_rows: int,
    short_rows: int,
    label: str,
) -> list[tuple[int, str, int, str]]:
    a1 = await _submit(2, 1, label + "-A1-LONG", long_rows)
    a2 = await _submit(2, 1, label + "-A2-LONG", long_rows)
    b1 = await _submit(3, 2, label + "-B1-SHORT", short_rows)
    return [
        (2, a1, long_rows - (long_rows // 100), "A1"),
        (2, a2, long_rows - (long_rows // 100), "A2"),
        (3, b1, short_rows - (short_rows // 100), "B1"),
    ]
def _probe_latency(conn: psycopg.Connection, samples: int) -> list[float]:
    values: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        conn.execute(
            "SELECT id, sku FROM product_variants "
            "WHERE company_id=2 ORDER BY id LIMIT 20"
        ).fetchall()
        values.append((time.perf_counter() - started) * 1000.0)
    return values


def _snapshot(admin: psycopg.Connection, job_ids: list[str]) -> dict:
    queue = admin.execute(
        """
        SELECT status, lock, args->>'job_id'
        FROM procrastinate_jobs
        WHERE task_name='wanasah.process_product_import'
          AND args->>'job_id' = ANY(%s)
          AND status IN ('todo','doing')
        ORDER BY id
        """,
        (job_ids,),
    ).fetchall()
    statuses = admin.execute(
        """
        SELECT id::text, company_id, status, processed_rows, failed_rows
        FROM product_import_jobs
        WHERE id::text = ANY(%s)
        ORDER BY created_at
        """,
        (job_ids,),
    ).fetchall()
    connections = admin.execute(
        "SELECT count(*) FROM pg_stat_activity WHERE usename='wanasah_app'"
    ).fetchone()[0]
    return {
        "queue": queue,
        "jobs": statuses,
        "connections": int(connections),
    }


def _wal_bytes(admin: psycopg.Connection) -> int:
    return int(admin.execute("SELECT wal_bytes FROM pg_stat_wal").fetchone()[0])
async def main() -> None:
    long_rows = int(os.environ.get("WANASAH_D32_LONG_ROWS", "1000"))
    short_rows = int(os.environ.get("WANASAH_D32_SHORT_ROWS", "100"))
    slots = int(os.environ["PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS"])
    label = f"D32-S{slots}-{int(time.time())}"
    jobs = await _enqueue(long_rows, short_rows, label)
    ids = [job_id for _company, job_id, _expected, _label in jobs]
    expected_by_job = {
        job_id: expected
        for _company, job_id, expected, _label in jobs
    }
    label_by_job = {
        job_id: job_label
        for _company, job_id, _expected, job_label in jobs
    }

    app_dsn = _psycopg_url("DATABASE_URL")
    admin_dsn = _psycopg_url("DATABASE_URL_MIGRATION")
    probe = psycopg.connect(app_dsn, autocommit=True)
    admin = psycopg.connect(admin_dsn, autocommit=True)
    probe.execute("SELECT set_config('app.current_tenant','2',false)")
    baseline = _probe_latency(probe, 25)
    wal_before = _wal_bytes(admin)

    log_base = pathlib.Path(os.environ["WANASAH_D32_WORKER_LOG"])
    workers: dict[str, subprocess.Popen] = {}
    worker_logs = {}
    for role in ("control", "maintenance", "execution"):
        role_log = log_base.with_name(log_base.stem + f"-{role}.log")
        handle = role_log.open("w", encoding="utf-8")
        worker_logs[role] = (role_log, handle)
        workers[role] = subprocess.Popen(
            [
                sys.executable, "-m",
                "domains.simple_products.imports.infrastructure.worker_cli",
                "--role", role,
            ],
            cwd=ROOT,
            env=os.environ.copy(),
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
        )

    started = time.perf_counter()
    during: list[float] = []
    max_connections = 0
    max_doing = 0
    cross_company_overlap = False
    same_company_double = False
    second_a_waited_while_b_ran = False
    terminal_offsets: dict[str, float] = {}
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            snap = _snapshot(admin, ids)
            max_connections = max(max_connections, snap["connections"])
            doing = [row for row in snap["queue"] if row[0] == "doing"]
            todo = [row for row in snap["queue"] if row[0] == "todo"]
            max_doing = max(max_doing, len(doing))
            doing_locks = [str(row[1]) for row in doing]
            if doing_locks.count("product-import:2") > 1:
                same_company_double = True
            if "product-import:2" in doing_locks and "product-import:3" in doing_locks:
                cross_company_overlap = True
                if any(str(row[1]) == "product-import:2" for row in todo):
                    second_a_waited_while_b_ran = True

            tick = time.perf_counter()
            probe.execute(
                "SELECT id, sku FROM product_variants "
                "WHERE company_id=2 ORDER BY id LIMIT 20"
            ).fetchall()
            during.append((time.perf_counter() - tick) * 1000.0)

            terminal = {
                str(row[0]): str(row[2])
                for row in snap["jobs"]
                if str(row[2]) in TERMINAL
            }
            now_offset = time.perf_counter() - started
            for terminal_job_id in terminal:
                terminal_offsets.setdefault(terminal_job_id, now_offset)
            if len(terminal) == len(ids):
                break
            for role, worker in workers.items():
                if worker.poll() is not None:
                    raise RuntimeError(
                        "D3.2 worker exited before jobs became terminal; "
                        f"role={role} log={worker_logs[role][0]}"
                    )
            time.sleep(0.05)
        else:
            raise RuntimeError("D3.2 jobs exceeded 180-second gate.")
    finally:
        elapsed = time.perf_counter() - started
        for worker in workers.values():
            if worker.poll() is None:
                worker.terminate()
        for worker in workers.values():
            if worker.poll() is None:
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=5)
        for _role_log, handle in worker_logs.values():
            handle.close()
    final = _snapshot(admin, ids)
    wal_after = _wal_bytes(admin)
    outcomes = {
        str(row[0]): {
            "company_id": int(row[1]),
            "status": str(row[2]),
            "processed": int(row[3] or 0),
            "failed": int(row[4] or 0),
        }
        for row in final["jobs"]
    }
    for job_id, outcome in outcomes.items():
        if outcome["status"] != "COMPLETED_WITH_ERRORS":
            raise RuntimeError(f"Unexpected D3.2 outcome {job_id}: {outcome}")
        if outcome["processed"] != expected_by_job[job_id]:
            raise RuntimeError(f"Unexpected imported count {job_id}: {outcome}")

    if same_company_double:
        raise RuntimeError("Same-company Product Imports executed concurrently.")
    if slots >= 2 and not cross_company_overlap:
        raise RuntimeError("Two-slot worker never overlapped independent companies.")
    if slots >= 2 and not second_a_waited_while_b_ran:
        raise RuntimeError("Same-company lock/fairness proof was not observed.")
    short_job_id = next(
        job_id for job_id, label_name in label_by_job.items()
        if label_name == "B1"
    )
    second_long_job_id = next(
        job_id for job_id, label_name in label_by_job.items()
        if label_name == "A2"
    )
    short_finished_before_second_long = (
        terminal_offsets[short_job_id] < terminal_offsets[second_long_job_id]
    )
    if slots >= 2 and not short_finished_before_second_long:
        raise RuntimeError(
            "Short independent-tenant import was starved behind same-tenant work."
        )
    if max_connections > int(os.environ["PRODUCT_IMPORT_DB_CONNECTION_BUDGET"]):
        raise RuntimeError(
            f"Observed app connections exceeded Product Import budget: {max_connections}"
        )

    result = {
        "slots": slots,
        "long_rows": long_rows,
        "short_rows": short_rows,
        "jobs": len(ids),
        "elapsed_s": round(elapsed, 3),
        "max_doing": max_doing,
        "cross_company_overlap": cross_company_overlap,
        "same_company_double": same_company_double,
        "same_company_waited_while_other_company_ran": second_a_waited_while_b_ran,
        "short_finished_before_second_long": short_finished_before_second_long,
        "terminal_offsets_s": {
            label_by_job[job_id]: round(offset, 3)
            for job_id, offset in terminal_offsets.items()
        },
        "max_app_connections": max_connections,
        "baseline_p50_ms": round(median(baseline), 3),
        "baseline_p95_ms": round(_p95(baseline), 3),
        "during_p50_ms": round(median(during), 3),
        "during_p95_ms": round(_p95(during), 3),
        "during_max_ms": round(max(during or [0.0]), 3),
        "wal_delta_bytes": max(0, wal_after - wal_before),
        "imported_by_job": {
            label_by_job[job_id]: expected_by_job[job_id]
            for job_id in ids
        },
    }
    print("D32_RESULT=" + json.dumps(result, separators=(",", ":")), flush=True)
    probe.close()
    admin.close()
    await engine.dispose()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.run(main(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:
        asyncio.run(main())
