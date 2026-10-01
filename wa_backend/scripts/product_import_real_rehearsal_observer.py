"""Read-only measurements for an owner-operated, real-dashboard Product Import.

Never starts an import, changes product rows, resets pg_stat counters, executes
EXPLAIN ANALYZE, VACUUM or DDL, or reads Excel/product/source payload bytes.
Uses the already configured application PostgreSQL role and tenant RLS.
The operator supplies the real database name and authorized company/job IDs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from domains.simple_products.imports.infrastructure.queue_dsn import (
    product_import_psycopg_dsn,
)


WATCH_TERMINAL = frozenset({
    "COMPLETED", "COMPLETED_WITH_ERRORS", "VALIDATION_FAILED", "FAILED", "CANCELLED",
})
RELATIONS = (
    "product_import_jobs",
    "product_import_rows",
    "product_import_row_barcodes",
    "product_import_sources",
    "product_import_source_chunks",
    "product_import_tenant_source_capacity",
    "product_import_global_source_capacity",
    "products",
    "product_variants",
    "product_barcodes",
    "product_uom_conversions",
    "price_book_entries",
    "price_publications",
    "operation_idempotency",
    "domain_audit_events",
    "transactional_outbox",
    "procrastinate_jobs",
    "procrastinate_events",
)


def _encode(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"),
        default=lambda x: x.isoformat() if isinstance(x, datetime) else str(x),
    )


def _connect(expected_database: str):
    if not expected_database or any(x in expected_database for x in "\r\n"):
        raise ValueError("--expected-db must be the exact approved database name.")
    conn = psycopg.connect(
        product_import_psycopg_dsn(), autocommit=True, row_factory=dict_row,
        connect_timeout=5, application_name="product-import-read-only-observer",
    )
    try:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            actual = conn.execute("SELECT current_database() AS name").fetchone()["name"]
            if actual != expected_database:
                raise RuntimeError(
                    f"Database mismatch: expected {expected_database!r}, got {actual!r}. "
                    "No import data was queried."
                )
            role = conn.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ).fetchone()
            if role is None or role["rolsuper"] or role["rolbypassrls"]:
                raise RuntimeError(
                    "Observer refuses a superuser/BYPASSRLS connection; "
                    "use the real tenant-scoped application role."
                )
        return conn
    except BaseException:
        conn.close()
        raise


def _job(conn, company_id: int, job_id: UUID):
    return conn.execute(
        """SELECT id, status, total_rows, valid_rows, processed_rows, failed_rows,
                  created_at, started_at, finished_at,
                  (source_payload_cleared_at IS NOT NULL) AS source_cleared,
                  version
           FROM product_import_jobs
           WHERE company_id=%s AND id=%s""",
        (company_id, job_id),
    ).fetchone()


def _queue(conn):
    rows = conn.execute(
        """SELECT queue_name, status, count(*)::bigint AS count
           FROM procrastinate_jobs
           WHERE queue_name IN ('product-import','product-import-control',
                                'product-import-maintenance')
             AND status IN ('todo','doing')
           GROUP BY queue_name,status
           ORDER BY queue_name,status"""
    ).fetchall()
    return [dict(row) for row in rows]


def _activity(conn):
    return [
        dict(row) for row in conn.execute(
            """SELECT COALESCE(state,'unknown') AS state,
                      COALESCE(wait_event_type,'none') AS wait_type,
                      count(*)::bigint AS sessions
               FROM pg_stat_activity
               WHERE datname = current_database() AND backend_type = 'client backend'
               GROUP BY state, wait_event_type
               ORDER BY sessions DESC, state"""
        ).fetchall()
    ]


def _processes():
    """Only aggregate selected Python role PIDs; do NOT print command lines."""
    try:
        import psutil
    except ImportError:
        return {"available": False, "reason": "psutil unavailable"}
    found = []
    for process in psutil.process_iter(["pid", "cmdline", "memory_info", "cpu_times"]):
        try:
            argv = process.info.get("cmdline") or []
            command = " ".join(str(x).lower() for x in argv)
            if "domains.simple_products.imports.infrastructure.worker_cli" in command:
                role = "import-worker"
            elif "uvicorn" in command and "main:app" in command:
                role = "api-uvicorn"
            else:
                continue
            memory = process.info.get("memory_info")
            cpu = process.info.get("cpu_times")
            found.append({
                "pid": int(process.pid),
                "role": role,
                "rss_bytes": int(memory.rss) if memory else None,
                "cpu_seconds_since_process_start": (
                    round(float(cpu.user + cpu.system), 3) if cpu else None
                ),
            })
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue
    return {
        "available": True,
        "matching_processes": found,
        "note": "Only matched PID RSS/CPU, not an automatic complete subprocess-tree or system-wide peak.",
    }


def _scoped_sample(conn, *, company_id: int, job_id: UUID | None, include_os: bool):
    # Fresh READ ONLY transaction on each sample. No locks retained between polls.
    with conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '15000ms'")
        conn.execute("SELECT set_config('app.current_tenant', %s, true)", (str(company_id),))
        job = _job(conn, company_id, job_id) if job_id is not None else None
        sample = {
            "observed_utc": datetime.now(timezone.utc),
            "company_id": company_id,
            "job_id": str(job_id) if job_id else None,
            "job": dict(job) if job is not None else None,
            "queue": _queue(conn),
            "database_client_activity": _activity(conn),
        }
    if include_os:
        sample["matched_os_processes"] = _processes()
    return sample


def _storage_snapshot(conn, *, company_id: int, job_id: UUID | None):
    with conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '30000ms'")
        conn.execute("SELECT set_config('app.current_tenant', %s, true)", (str(company_id),))
        table_rows = conn.execute(
            """SELECT relname,
                      pg_relation_size(relid)::bigint AS table_bytes,
                      pg_indexes_size(relid)::bigint AS indexes_bytes,
                      pg_total_relation_size(relid)::bigint AS total_bytes,
                      n_live_tup::bigint AS estimated_live_tuples,
                      n_dead_tup::bigint AS estimated_dead_tuples,
                      n_tup_ins::bigint AS cumulative_inserted_tuples,
                      n_tup_upd::bigint AS cumulative_updated_tuples,
                      n_tup_del::bigint AS cumulative_deleted_tuples,
                      autovacuum_count::bigint, autoanalyze_count::bigint,
                      last_autovacuum, last_autoanalyze
               FROM pg_stat_user_tables
               WHERE schemaname='public' AND relname=ANY(%s::text[])
               ORDER BY relname""",
            (list(RELATIONS),),
        ).fetchall()
        index_rows = conn.execute(
            """SELECT s.relname AS table_name, i.indexrelname AS index_name,
                      pg_relation_size(i.indexrelid)::bigint AS index_bytes,
                      i.idx_scan::bigint AS cumulative_scans,
                      i.idx_tup_read::bigint AS cumulative_tuples_read,
                      i.idx_tup_fetch::bigint AS cumulative_tuples_fetched
               FROM pg_stat_user_indexes AS i
               JOIN pg_class AS s ON s.oid=i.relid
               WHERE i.schemaname='public' AND s.relname=ANY(%s::text[])
               ORDER BY table_name,index_name""",
            (list(RELATIONS),),
        ).fetchall()
        pg_database = conn.execute(
            """SELECT xact_commit, xact_rollback, blks_read, blks_hit,
                      tup_inserted, tup_updated, tup_deleted,
                      temp_bytes, deadlocks, conflicts
               FROM pg_stat_database
               WHERE datname=current_database()"""
        ).fetchone()
        wal = conn.execute("SELECT wal_bytes FROM pg_stat_wal").fetchone()
        source_capacity = conn.execute(
            """SELECT live_bytes, high_water_bytes
               FROM product_import_tenant_source_capacity WHERE company_id=%s""",
            (company_id,),
        ).fetchone()
        global_capacity = conn.execute(
            """SELECT live_bytes, high_water_bytes
               FROM product_import_global_source_capacity WHERE id=1"""
        ).fetchone()
        sample = {
            "observed_utc": datetime.now(timezone.utc),
            "database": conn.execute("SELECT current_database() AS database").fetchone()["database"],
            "company_id": company_id,
            "job_id": str(job_id) if job_id else None,
            "table_metrics": {row["relname"]: dict(row) for row in table_rows},
            "index_metrics": {row["index_name"]: dict(row) for row in index_rows},
            "missing_expected_tables": sorted(set(RELATIONS) - {row["relname"] for row in table_rows}),
            "database_global_counters": dict(pg_database),
            "cluster_global_wal_bytes": int(wal["wal_bytes"]) if wal else None,
            "company_source_capacity": dict(source_capacity) if source_capacity else None,
            "global_source_capacity": dict(global_capacity) if global_capacity else None,
        }
        if job_id:
            job = _job(conn, company_id, job_id)
            sample["job"] = dict(job) if job is not None else None
            if job is not None and str(job["status"]) in WATCH_TERMINAL:
                # One exact job-scoped reconciliation, never once per watch poll.
                rows = conn.execute(
                    """SELECT count(*)::bigint AS staged_rows,
                              count(*) FILTER (WHERE status='IMPORTED')::bigint AS imported_rows,
                              count(*) FILTER (WHERE status='INVALID')::bigint AS invalid_rows,
                              count(*) FILTER (WHERE status='IMPORT_FAILED')::bigint AS import_failed_rows,
                              count(DISTINCT product_variant_id)
                                FILTER (WHERE status='IMPORTED')::bigint AS distinct_imported_variants,
                              count(*) FILTER (WHERE status IN ('STAGED','VALID'))::bigint AS pending_rows
                       FROM product_import_rows
                       WHERE company_id=%s AND job_id=%s""",
                    (company_id, job_id),
                ).fetchone()
                sample["job_row_reconciliation"] = dict(rows)
                # Scoped Price/Audit/Outbox proof for this job's imported variants.
                sample["job_business_reconciliation"] = dict(conn.execute(
                    """WITH linked AS MATERIALIZED (
                         SELECT DISTINCT product_variant_id AS id
                         FROM product_import_rows
                         WHERE company_id=%s AND job_id=%s
                           AND status='IMPORTED' AND product_variant_id IS NOT NULL
                       )
                       SELECT
                         (SELECT count(*) FROM linked)::bigint AS linked_variants,
                         (SELECT count(*) FROM product_variants v JOIN linked l ON v.id=l.id
                           WHERE v.company_id=%s)::bigint AS existing_variants,
                         (SELECT count(DISTINCT e.product_variant_id)
                           FROM price_book_entries e JOIN linked l ON e.product_variant_id=l.id
                           WHERE e.company_id=%s)::bigint AS variants_with_price,
                         (SELECT count(DISTINCT a.entity_id)
                           FROM domain_audit_events a JOIN linked l ON a.entity_id=l.id::text
                           WHERE a.company_id=%s AND a.entity_type='ProductVariant'
                         )::bigint AS distinct_audited_variants,
                         (SELECT count(DISTINCT o.aggregate_id)
                           FROM transactional_outbox o JOIN linked l ON o.aggregate_id=l.id::text
                           WHERE o.company_id=%s AND o.aggregate_type='ProductVariant'
                         )::bigint AS distinct_outbox_variants""",
                    (company_id, job_id, company_id, company_id, company_id, company_id),
                ).fetchone())
        return sample


def _write_new(path: Path, payload: object):
    if not path.parent.is_dir():
        raise RuntimeError("Output directory does not exist. Create it explicitly.")
    with path.open("x", encoding="utf-8") as stream:
        stream.write(_encode(payload) + "\n")


def _difference(before: object, after: object):
    if isinstance(before, int) and isinstance(after, int):
        return after - before
    return None


def _compare(before: dict, after: dict):
    if before.get("database") != after.get("database") or before.get("company_id") != after.get("company_id"):
        raise RuntimeError("Cannot compare snapshots from different database/company identities.")
    tables = {}
    for name in sorted(set(before["table_metrics"]) | set(after["table_metrics"])):
        a = before["table_metrics"].get(name) or {}
        z = after["table_metrics"].get(name) or {}
        tables[name] = {
            key + "_delta": _difference(a.get(key), z.get(key))
            for key in (
                "table_bytes", "indexes_bytes", "total_bytes",
                "estimated_live_tuples", "estimated_dead_tuples",
                "cumulative_inserted_tuples", "cumulative_updated_tuples",
                "cumulative_deleted_tuples",
            )
        }
    indexes = {}
    for name in sorted(set(before["index_metrics"]) | set(after["index_metrics"])):
        a = before["index_metrics"].get(name) or {}
        z = after["index_metrics"].get(name) or {}
        indexes[name] = {
            "table_name": z.get("table_name") or a.get("table_name"),
            "index_bytes_delta": _difference(a.get("index_bytes"), z.get("index_bytes")),
            "cumulative_scans_delta": _difference(a.get("cumulative_scans"), z.get("cumulative_scans")),
        }
    return {
        "database": before["database"],
        "company_id": before["company_id"],
        "start_utc": before["observed_utc"],
        "finish_utc": after["observed_utc"],
        "table_deltas": tables,
        "index_deltas": indexes,
        "database_global_counter_deltas": {
            key: _difference(before["database_global_counters"].get(key),
                             after["database_global_counters"].get(key))
            for key in before["database_global_counters"]
        },
        "cluster_global_wal_bytes_delta": _difference(
            before.get("cluster_global_wal_bytes"), after.get("cluster_global_wal_bytes")
        ),
        "warnings": [
            "SQL/PostgreSQL global counters include OTHER companies and processes; no reset performed.",
            "n_dead_tup/n_live_tup are estimates, not physical row counts.",
            "Growing index bytes is NOT in itself index bloat; use vacuum/index diagnostics if growth is abnormal.",
            "No 50k performance SLO is inferred from one dashboard run; compare job's actual status times.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("snapshot", "watch", "compare"))
    parser.add_argument("--company-id", type=int)
    parser.add_argument("--job-id")
    parser.add_argument("--expected-db")
    parser.add_argument("--out")
    parser.add_argument("--before")
    parser.add_argument("--after")
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--max-samples", type=int, default=600)
    parser.add_argument("--os-processes", action="store_true")
    args = parser.parse_args()

    if args.mode == "compare":
        if not args.before or not args.after or not args.out:
            parser.error("compare requires --before, --after and --out.")
        with open(args.before, encoding="utf-8") as fh:
            before = json.load(fh)
        with open(args.after, encoding="utf-8") as fh:
            after = json.load(fh)
        result = _compare(before, after)
        _write_new(Path(args.out), result)
        print(_encode({"comparison_saved": args.out, "database": result["database"]}))
        return

    if (
        args.company_id is None or args.company_id <= 0
        or not args.expected_db or not args.out
        or not args.expected_db.strip()
    ):
        parser.error("snapshot/watch require approved --company-id, --expected-db, --out.")
    if args.job_id is not None:
        args.job_id = UUID(args.job_id)
    if args.mode == "watch" and args.job_id is None:
        parser.error("watch requires explicit HTTP-assigned --job-id; never guess tenant jobs.")
    if not 5 <= args.seconds <= 60 or not 1 <= args.max_samples <= 720:
        parser.error("--seconds must be 5..60, --max-samples 1..720.")
    if not Path(args.out).parent.is_dir() or Path(args.out).exists():
        raise RuntimeError("Output path already exists or directory does not exist; refusing overwrite.")

    with _connect(args.expected_db) as conn:
        if args.mode == "snapshot":
            result = _storage_snapshot(conn, company_id=args.company_id, job_id=args.job_id)
            if args.os_processes:
                result["matched_os_processes"] = _processes()
            _write_new(Path(args.out), result)
            print(_encode({
                "snapshot_saved": args.out,
                "database": result["database"],
                "company_id": result["company_id"],
                "job_status": (result.get("job") or {}).get("status"),
                "job_reconciliation": result.get("job_row_reconciliation"),
                "business_reconciliation": result.get("job_business_reconciliation"),
            }))
            return

        with Path(args.out).open("x", encoding="utf-8") as stream:
            for n in range(args.max_samples):
                sample = _scoped_sample(
                    conn, company_id=args.company_id,
                    job_id=args.job_id, include_os=args.os_processes,
                )
                if sample["job"] is None:
                    if n:
                        raise RuntimeError("The watched tenant job disappeared; refusing to switch jobs.")
                    raise RuntimeError("No such job in the approved company; use the real HTTP 202 job ID.")
                stream.write(_encode(sample) + "\n")
                stream.flush()
                job = sample["job"]
                print(_encode({
                    "at": sample["observed_utc"], "status": job["status"],
                    "processed": job["processed_rows"], "valid": job["valid_rows"],
                    "failed": job["failed_rows"], "total": job["total_rows"],
                    "queue": sample["queue"],
                }), flush=True)
                if job["status"] in WATCH_TERMINAL:
                    print("IMPORT_WATCH_TERMINAL=YES", flush=True)
                    return
                if n + 1 < args.max_samples:
                    time.sleep(args.seconds)
        raise RuntimeError("Watch sample ceiling reached: operation did not reach a terminal state.")


if __name__ == "__main__":
    main()
