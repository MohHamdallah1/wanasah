"""Real 5k/10k HTTP→PG→Product Import worker intermediate gate, disposable only.

Uses the already approved Phase19 isolated PG16+API+three-role worker orchestration.
Never connects to existing developer PG; never opens user-supplied XLSX.
"""
from __future__ import annotations

import json
import os
import time
from uuid import uuid4

import psutil
import httpx
import psycopg
from sqlalchemy.engine import make_url

from api.auth import create_access_token
from scripts.product_import_business_integrity_gate import _assert_business_evidence
from scripts.run_product_import_phase19_live_load import build_source
from scripts import product_import_phase19_http_isolated_child as shared

if os.environ.get("WANASAH_P19_HTTP_DISPOSABLE_CHILD") != "1":
    raise RuntimeError("Intermediate gate requires the disposable child marker.")
target = make_url(os.environ.get("DATABASE_URL", ""))
if (
    target.database != "p19_http_synthetic"
    or target.host != "127.0.0.1"
    or int(target.port or 0) != 55446
):
    raise RuntimeError("Medium gate refuses any database except isolated 127.0.0.1:55446.")

ROWS = int(os.environ.get("WANASAH_P19_INTERMEDIATE_ROWS", "5000"))
CASE = os.environ.get("WANASAH_P19_HTTP_CASE", "medium")
if ((CASE == "medium" and ROWS not in (5000, 10000)) or
    (CASE == "final" and ROWS != 50000) or
    CASE not in {"medium", "final"}):
    raise RuntimeError("Only medium 5k/10k or explicit final 50k are permitted.")
END_STATES = {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED", "VALIDATION_FAILED", "CANCELLED"}


def measure_one(client: httpx.Client, admin: psycopg.Connection, processes) -> None:
    label = f"P19-INTERMEDIATE-{ROWS}-{uuid4().hex[:12]}"
    payload, _mapping, barcode_prefix = build_source(ROWS, label)
    if not payload or len(payload) > 8 * 1024 * 1024:
        raise RuntimeError("Intermediate fixture violates ingress file limit.")
    collisions = admin.execute(
        "SELECT count(*) FROM product_barcodes WHERE company_id=2 AND barcode LIKE %s",
        (barcode_prefix + "%",),
    ).fetchone()[0]
    if int(collisions):
        raise RuntimeError("Synthetic within-run barcode namespace already exists.")

    start = time.perf_counter()
    created = shared.require(
        client.post(
            "/simple-products/imports",
            data={
                "request_id": str(uuid4()),
                "default_lot_control_mode": "NONE",
                "default_expiry_control_mode": "NONE",
            },
            files={"file": (label + ".csv", payload, "text/csv")},
        ),
        202,
        "intermediate real HTTP admission",
    )
    job_id = str(created["job_id"])
    admit_s = time.perf_counter() - start
    phase_first: dict[str, float] = {}
    phases: list[str] = []
    peak_rss_mb: dict[str, float] = {}
    peak_cpu_pct: dict[str, float] = {}
    max_db_clients = 0
    max_db_lock_edges = 0
    last_sample = 0.0
    monitors = {}
    for proc, _ in processes:
        try:
            monitor = psutil.Process(proc.pid)
            monitor.cpu_percent(interval=None)
            monitors[proc.p19_label] = monitor
        except psutil.Error:
            pass
    latest = None
    deadline = time.monotonic() + (660 if ROWS == 5000 else 1020 if ROWS == 10000 else 3600)
    while time.monotonic() < deadline:
        now = time.perf_counter()
        if now - last_sample > 5.0:
            last_sample = now
            for label, proc in monitors.items():
                try:
                    peak_rss_mb[label] = max(
                        peak_rss_mb.get(label, 0.0),
                        round(proc.memory_info().rss / (1024 ** 2), 2),
                    )
                    peak_cpu_pct[label] = max(
                        peak_cpu_pct.get(label, 0.0),
                        round(proc.cpu_percent(interval=None), 2),
                    )
                except psutil.Error:
                    pass
            current_clients, locked = admin.execute(
                "SELECT count(*), coalesce(sum(cardinality(pg_blocking_pids(pid))),0) "
                "FROM pg_stat_activity WHERE datname=current_database() "
                "AND backend_type='client backend'",
            ).fetchone()
            max_db_clients = max(max_db_clients, int(current_clients))
            max_db_lock_edges = max(max_db_lock_edges, int(locked))
        response = shared.require(
            client.get(f"/simple-products/imports/{job_id}"),
            200,
            "intermediate authorized status",
        )
        latest = str(response["status"])
        if latest not in phase_first:
            phase_first[latest] = round(time.perf_counter() - start, 3)
            phases.append(latest)
        if latest in END_STATES:
            break
        time.sleep(0.75)
    else:
        raise TimeoutError(
            f"Intermediate queue job timed out without a terminal state; "
            f"last_status={latest}; no source was resubmitted."
        )
    final_s = time.perf_counter() - start
    if latest != "COMPLETED_WITH_ERRORS":
        raise RuntimeError(f"Intermediate job did not end as expected: {latest}")

    expected = ROWS - ROWS // 100
    result = _assert_business_evidence(admin, job_id, expected)
    if result["invalid"] != ROWS // 100 or result["import_failed"] != 0:
        raise RuntimeError("Intermediate invalid/import-failed counts mismatch.")
    snapshot = admin.execute(
        "SELECT total_rows,processed_rows,failed_rows,source_payload_cleared_at "
        "FROM product_import_jobs WHERE company_id=2 AND id=%s",
        (job_id,),
    ).fetchone()
    if (int(snapshot[0]), int(snapshot[1]), int(snapshot[2])) != (
        ROWS, expected, ROWS // 100,
    ):
        raise RuntimeError("Business-job counters differ from source row reconciliation.")
    if snapshot[3] is None:
        raise RuntimeError("SourceStore cleanup did not complete.")

    line = admin.execute(
        "SELECT count(*),count(DISTINCT row_number),min(row_number),max(row_number) "
        "FROM product_import_rows WHERE company_id=2 AND job_id=%s",
        (job_id,),
    ).fetchone()
    # The accepted synthetic CSV intentionally inserts one physically empty
    # line after each 10,000th data row except the final record. These are
    # skipped as products but MUST advance physical source row numbering.
    expected_last_physical = 1 + ROWS + ((ROWS - 1) // 10_000)
    if tuple(map(int, line)) != (ROWS, ROWS, 2, expected_last_physical):
        raise RuntimeError("Physical source-row identity or staging count mismatch.")
    active = admin.execute(
        "SELECT count(*) FROM procrastinate_jobs WHERE task_name='wanasah.process_product_import' "
        "AND args->>'job_id'=%s AND status IN ('todo','doing')",
        (job_id,),
    ).fetchone()[0]
    if active:
        raise RuntimeError("Intermediate run left an active queue delivery.")

    print("P19_INTERMEDIATE_RESULT=" + json.dumps({
        "case": CASE,
        "peak_rss_mib_per_role": peak_rss_mb,
        "peak_cpu_pct_per_role_sample": peak_cpu_pct,
        "max_db_client_connections": max_db_clients,
        "max_pg_lock_wait_edges": max_db_lock_edges,
        "rows": ROWS,
        "source_bytes": len(payload),
        "admission_seconds": round(admit_s, 3),
        "end_to_end_seconds": round(final_s, 3),
        "phase_first_seen_seconds": phase_first,
        "phase_order_observed": phases,
        "imported": result["imported"],
        "invalid": result["invalid"],
        "import_failed": result["import_failed"],
        "price_variants": result["price_variants"],
        "audit": result["audit"],
        "outbox": result["outbox"],
        "physical_source_rows": int(line[0]),
        "last_physical_row": int(line[3]),
        "retained_source_cleared": True,
        "queue_active_after": int(active),
    }, separators=(",", ":")), flush=True)
    print(f"P19_REAL_QUEUE_{ROWS}_SYNTHETIC=PASS", flush=True)


def main() -> None:
    admin_url = make_url(os.environ["DATABASE_URL_MIGRATION"])
    if (admin_url.database != "p19_http_synthetic"
        or admin_url.host != "127.0.0.1"
        or int(admin_url.port or 0) != 55446):
        raise RuntimeError("Refusing unisolated admin DB target.")
    admin = psycopg.connect(
        admin_url.set(drivername="postgresql").render_as_string(hide_password=False),
        autocommit=True,
    )
    processes = []
    try:
        companies = [
            admin.execute("SELECT count(*) FROM companies WHERE id=%s", (number,)).fetchone()[0]
            for number in (2, 3)
        ]
        if companies != [1, 1]:
            raise RuntimeError("Synthetic company fixtures missing.")
        token = create_access_token({"sub": "1", "is_admin": True}, 2, "Admin")
        processes.append(shared.start(
            "medium-http-server", "-m",
            "scripts.product_import_phase19_http_selector_server",
        ))
        for role in ("control", "maintenance", "execution"):
            processes.append(shared.start(
                f"medium-{role}", "-m",
                "domains.simple_products.imports.infrastructure.worker_cli",
                "--role", role,
            ))
        with httpx.Client(
            base_url=shared.BASE, timeout=40.0,
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            shared.wait_health(client, processes)
            shared.wait_worker(client)
            measure_one(client, admin, processes)
    finally:
        for process, handle in reversed(processes):
            shared.stop(process, handle)
        admin.close()


if __name__ == "__main__":
    main()
