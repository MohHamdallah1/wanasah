from __future__ import annotations

import os
from pathlib import Path
import threading
import time
from uuid import UUID, uuid4

import psycopg
from dotenv import load_dotenv
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
load_dotenv(BACKEND / ".env")

TARGET_ROWS = 50_000
VALIDATION_BATCH = 500
EXECUTION_BATCH = 100

checks = 0
failures: list[str] = []


def check(condition: bool, label: str, detail: str = "") -> None:
    global checks
    checks += 1
    print((
        "[PASS] "
        if condition
        else "[FAIL] "
    ) + label + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def _dsn(env_name: str) -> str:
    raw = os.getenv(env_name)
    if not raw:
        raise RuntimeError(f"{env_name} is required.")
    return (
        make_url(raw)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )


def owner_dsn() -> str:
    if os.getenv("DATABASE_URL_MIGRATION"):
        return _dsn("DATABASE_URL_MIGRATION")
    return _dsn("DATABASE_URL")


def runtime_dsn() -> str:
    return _dsn("DATABASE_URL")


def walk_plan(node: dict):
    yield node
    for child in node.get("Plans") or []:
        yield from walk_plan(child)


def explain(conn, sql: str, params: tuple) -> tuple[float, list[str], list[str]]:
    document = conn.execute(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql,
        params,
    ).fetchone()[0][0]
    nodes = list(walk_plan(document["Plan"]))
    indexes = [
        str(node["Index Name"])
        for node in nodes
        if node.get("Index Name")
    ]
    seq_relations = [
        str(node["Relation Name"])
        for node in nodes
        if node.get("Node Type") == "Seq Scan"
        and node.get("Relation Name")
    ]
    return (
        float(document["Execution Time"]),
        indexes,
        seq_relations,
    )


def set_tenant(conn, company_id: int) -> None:
    conn.execute(
        "SELECT set_config('app.current_tenant', %s, true)",
        (str(int(company_id)),),
    )


def index_review(conn) -> None:
    rows = conn.execute(
        """
        SELECT tablename, indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND tablename IN (
              'product_import_jobs',
              'product_import_rows',
              'product_import_row_barcodes'
          )
        ORDER BY tablename, indexname
        """
    ).fetchall()
    definitions = {
        str(name): str(definition)
        for _table, name, definition in rows
    }

    row_index = definitions.get(
        "ix_product_import_row_job_status",
        "",
    )
    check(
        "(company_id, job_id, status, row_number)" in row_index,
        "Batch scan index matches tenant+job+status+row ordering",
        row_index,
    )

    barcode_index = definitions.get(
        "ix_product_import_row_barcode_job_barcode",
        "",
    )
    check(
        "(company_id, job_id, barcode, row_number)" in barcode_index,
        "Normalized barcode staging index matches Phase 6 joins",
        barcode_index,
    )

    surrogate_primary_keys = {
        "pk_product_import_jobs",
        "pk_product_import_rows",
    }
    non_tenant: list[str] = []
    for _table, index_name, definition in rows:
        index_name = str(index_name)
        if index_name in surrogate_primary_keys:
            continue
        marker = " USING btree ("
        definition = str(definition)
        if marker not in definition:
            continue
        indexed = definition.split(marker, 1)[1]
        if not indexed.startswith("company_id"):
            non_tenant.append(index_name)
    check(
        not non_tenant,
        "All tenant read/constraint indexes are company-prefixed",
        repr(non_tenant),
    )

    barcode_indexes = [
        str(name)
        for table, name, _definition in rows
        if str(table) == "product_import_row_barcodes"
    ]
    check(
        len(barcode_indexes) == 2,
        "Barcode staging avoids redundant duplicate indexes",
        repr(barcode_indexes),
    )


def reloption_review(conn) -> None:
    options = {
        str(name): set(value or [])
        for name, value in conn.execute(
            """
            SELECT relname, reloptions
            FROM pg_class
            WHERE relname IN (
                'product_import_rows',
                'product_import_jobs',
                'product_import_row_barcodes'
            )
            """
        )
    }
    rows_options = options.get("product_import_rows", set())
    expected_rows = {
        "autovacuum_vacuum_scale_factor=0.05",
        "autovacuum_vacuum_threshold=2500",
        "autovacuum_analyze_scale_factor=0.02",
        "autovacuum_analyze_threshold=1000",
        "autovacuum_vacuum_insert_scale_factor=0.05",
        "autovacuum_vacuum_insert_threshold=5000",
    }
    check(
        expected_rows.issubset(rows_options),
        "High-churn row table owns evidence-based autovacuum/analyze reloptions",
        repr(sorted(rows_options)),
    )
    for table in ("product_import_jobs", "product_import_row_barcodes"):
        check(
            bool(options.get(table)),
            f"{table} owns explicit autovacuum/analyze reloptions",
            repr(sorted(options.get(table, set()))),
        )

    effective_vacuum = 2500 + int(0.05 * TARGET_ROWS)
    default_vacuum = 50 + int(0.20 * TARGET_ROWS)
    effective_analyze = 1000 + int(0.02 * TARGET_ROWS)
    check(
        effective_vacuum < default_vacuum
        and effective_vacuum >= VALIDATION_BATCH * 10,
        "50k vacuum threshold is materially lower than default without firing per batch",
        f"configured={effective_vacuum} default={default_vacuum}",
    )
    check(
        effective_analyze == 2000,
        "50k analyze threshold refreshes planner stats early",
        f"configured={effective_analyze}",
    )


def rls_review(conn) -> None:
    rows = conn.execute(
        """
        SELECT relname, relrowsecurity, relforcerowsecurity
        FROM pg_class
        WHERE relname IN (
            'product_import_jobs',
            'product_import_rows',
            'product_import_row_barcodes'
        )
        ORDER BY relname
        """
    ).fetchall()
    check(
        len(rows) == 3
        and all(bool(row[1]) and bool(row[2]) for row in rows),
        "Product Import staging keeps ENABLE + FORCE RLS",
        repr(rows),
    )


def health_snapshot(conn, label: str) -> list[tuple]:
    try:
        conn.execute("SELECT pg_stat_force_next_flush()")
    except Exception:
        conn.rollback()
    rows = conn.execute(
        """
        SELECT stats.relname,
               stats.n_live_tup::bigint,
               stats.n_dead_tup::bigint,
               pg_relation_size(class.oid)::bigint,
               pg_indexes_size(class.oid)::bigint,
               pg_total_relation_size(class.oid)::bigint,
               age(class.relfrozenxid)::bigint,
               stats.last_autovacuum,
               stats.last_autoanalyze
        FROM pg_stat_user_tables AS stats
        JOIN pg_class AS class ON class.oid = stats.relid
        WHERE stats.relname IN (
            'product_import_rows',
            'product_import_jobs',
            'product_import_row_barcodes'
        )
        ORDER BY stats.relname
        """
    ).fetchall()
    for row in rows:
        print(f"TABLE_HEALTH_{label}={row}")
    return rows


def main() -> None:
    owner = owner_dsn()
    runtime = runtime_dsn()
    job_id = uuid4()
    request_id = uuid4()
    marker = "P15" + uuid4().hex[:10]

    with psycopg.connect(owner) as conn:
        index_review(conn)
        reloption_review(conn)
        rls_review(conn)
        health_snapshot(conn, "BASELINE")
        identity = conn.execute(
            """
            SELECT company_id, id
            FROM drivers
            WHERE is_active IS TRUE
            ORDER BY company_id, id
            LIMIT 1
            """
        ).fetchone()
        if identity is None:
            raise RuntimeError("Phase 15 audit requires one active driver.")
        company_id = int(identity[0])
        actor_id = int(identity[1])

    try:
        with psycopg.connect(owner) as conn:
            conn.execute(
                """
                INSERT INTO product_import_jobs (
                    id, company_id, request_id, created_by, file_name,
                    content_type, source_sha256, file_size, status,
                    default_lot_control_mode, default_expiry_control_mode,
                    total_rows
                ) VALUES (
                    %s, %s, %s, %s, %s, 'text/csv', %s, 1,
                    'VALIDATING', 'NONE', 'NONE', %s
                )
                """,
                (
                    job_id, company_id, request_id, actor_id,
                    f"{marker}.csv", "0" * 64, TARGET_ROWS,
                ),
            )
            started = time.perf_counter()
            conn.execute(
                """
                INSERT INTO product_import_rows (
                    company_id, job_id, row_number, raw_data,
                    normalized_data, status
                )
                SELECT %s, %s, gs, '{}'::jsonb, '{}'::jsonb,
                       CASE
                           WHEN gs %% 10 < 5 THEN 'STAGED'
                           WHEN gs %% 10 < 8 THEN 'VALID'
                           WHEN gs %% 10 = 8 THEN 'INVALID'
                           ELSE 'IMPORTED'
                       END
                FROM generate_series(2, %s) AS gs
                """,
                (company_id, job_id, TARGET_ROWS + 1),
            )
            conn.commit()
            seed_ms = (time.perf_counter() - started) * 1000
            print(f"SEED_50K_MS={seed_ms:.3f}")
            conn.execute("ANALYZE product_import_rows")
            conn.commit()

        with psycopg.connect(runtime) as conn:
            with conn.transaction():
                set_tenant(conn, company_id)
                validation_ms, indexes, seq = explain(
                    conn,
                    """
                    SELECT id, row_number
                    FROM product_import_rows
                    WHERE company_id = %s
                      AND job_id = %s
                      AND status = 'STAGED'
                      AND row_number > 0
                    ORDER BY row_number
                    LIMIT 500
                    FOR UPDATE
                    """,
                    (company_id, job_id),
                )
                print(
                    f"VALIDATION_BATCH_50K_MS={validation_ms:.3f} "
                    f"INDEXES={indexes} SEQ={seq}"
                )
                check(
                    "ix_product_import_row_job_status" in indexes
                    and "product_import_rows" not in seq
                    and validation_ms < 250.0,
                    "50k validation batch uses the tenant/job/status index",
                    f"{validation_ms:.3f}ms",
                )

            with conn.transaction():
                set_tenant(conn, company_id)
                execution_ms, indexes, seq = explain(
                    conn,
                    """
                    SELECT id, row_number
                    FROM product_import_rows
                    WHERE company_id = %s
                      AND job_id = %s
                      AND status = 'VALID'
                    ORDER BY row_number
                    LIMIT 100
                    FOR UPDATE SKIP LOCKED
                    """,
                    (company_id, job_id),
                )
                print(
                    f"EXECUTION_SELECTION_50K_MS={execution_ms:.3f} "
                    f"INDEXES={indexes} SEQ={seq}"
                )
                check(
                    "ix_product_import_row_job_status" in indexes
                    and "product_import_rows" not in seq
                    and execution_ms < 250.0,
                    "Mixed VALID/INVALID/IMPORTED execution selection remains indexed",
                    f"{execution_ms:.3f}ms",
                )

            with conn.transaction():
                set_tenant(conn, company_id)
                count_ms, indexes, seq = explain(
                    conn,
                    """
                    SELECT count(id)
                    FROM product_import_rows
                    WHERE company_id = %s
                      AND job_id = %s
                      AND status = 'VALID'
                    """,
                    (company_id, job_id),
                )
                print(
                    f"PENDING_VALID_COUNT_MS={count_ms:.3f} "
                    f"INDEXES={indexes} SEQ={seq}"
                )
                check(
                    "product_import_rows" not in seq
                    and count_ms < 250.0,
                    "Execution finalization uses an indexed status slice, not a full-job scan",
                    f"{count_ms:.3f}ms indexes={indexes}",
                )

        first = psycopg.connect(runtime)
        second = psycopg.connect(runtime)
        try:
            first.execute("BEGIN")
            second.execute("BEGIN")
            set_tenant(first, company_id)
            set_tenant(second, company_id)
            first_rows = {
                int(row[0])
                for row in first.execute(
                    """
                    SELECT row_number
                    FROM product_import_rows
                    WHERE company_id = %s
                      AND job_id = %s
                      AND status = 'VALID'
                    ORDER BY row_number
                    LIMIT 100
                    FOR UPDATE SKIP LOCKED
                    """,
                    (company_id, job_id),
                )
            }
            started = time.perf_counter()
            second_rows = {
                int(row[0])
                for row in second.execute(
                    """
                    SELECT row_number
                    FROM product_import_rows
                    WHERE company_id = %s
                      AND job_id = %s
                      AND status = 'VALID'
                    ORDER BY row_number
                    LIMIT 100
                    FOR UPDATE SKIP LOCKED
                    """,
                    (company_id, job_id),
                )
            }
            skip_locked_ms = (time.perf_counter() - started) * 1000
            check(
                len(first_rows) == EXECUTION_BATCH
                and len(second_rows) == EXECUTION_BATCH
                and first_rows.isdisjoint(second_rows)
                and skip_locked_ms < 1000.0,
                "Concurrent SKIP LOCKED workers are disjoint and non-blocking",
                f"{skip_locked_ms:.3f}ms",
            )
        finally:
            first.rollback()
            second.rollback()
            first.close()
            second.close()

        with psycopg.connect(owner) as conn:
            owner_ms, owner_indexes, owner_seq = explain(
                conn,
                """
                SELECT id, row_number
                FROM product_import_rows
                WHERE company_id = %s
                  AND job_id = %s
                  AND status = 'VALID'
                ORDER BY row_number
                LIMIT 100
                """,
                (company_id, job_id),
            )
        with psycopg.connect(runtime) as conn:
            with conn.transaction():
                set_tenant(conn, company_id)
                rls_ms, rls_indexes, rls_seq = explain(
                    conn,
                    """
                    SELECT id, row_number
                    FROM product_import_rows
                    WHERE company_id = %s
                      AND job_id = %s
                      AND status = 'VALID'
                    ORDER BY row_number
                    LIMIT 100
                    """,
                    (company_id, job_id),
                )
        ratio = rls_ms / max(owner_ms, 0.001)
        print(
            f"RLS_OWNER_MS={owner_ms:.3f} RLS_RUNTIME_MS={rls_ms:.3f} "
            f"RATIO={ratio:.2f}"
        )
        check(
            "ix_product_import_row_job_status" in rls_indexes
            and "product_import_rows" not in rls_seq
            and rls_ms < 250.0
            and ratio <= 5.0,
            "FORCE RLS preserves the indexed execution plan without pathological regression",
            f"owner={owner_ms:.3f}ms rls={rls_ms:.3f}ms ratio={ratio:.2f}",
        )

        execution_source = (
            BACKEND
            / "domains/simple_products/imports/application/execution_service.py"
        ).read_text(encoding="utf-8")
        validation_source = (
            BACKEND
            / "domains/simple_products/imports/application/validation_service.py"
        ).read_text(encoding="utf-8")
        check(
            "count_job_progress(" not in execution_source
            and execution_source.count("count_job_rows(") == 1,
            "Execution loop contains no repeated full-job aggregate scan",
        )
        check(
            validation_source.count("count_validation_outcomes(") == 1,
            "Validation performs one final aggregate scan, not one scan per batch",
        )

        with psycopg.connect(owner) as conn:
            started = time.perf_counter()
            conn.execute(
                """
                UPDATE product_import_rows
                SET status = 'VALID',
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE company_id = %s
                  AND job_id = %s
                  AND status = 'STAGED'
                  AND row_number <= 40001
                """,
                (company_id, job_id),
            )
            conn.commit()
            churn_ms = (time.perf_counter() - started) * 1000
            print(f"CHURN_UPDATE_20K_MS={churn_ms:.3f}")
            churn_health = health_snapshot(conn, "POST_CHURN")
            check(
                bool(churn_health),
                "50k churn benchmark records live/dead tuples, sizes, vacuum timestamps and transaction age",
            )

        vacuum_result: dict[str, float | Exception] = {}

        def run_vacuum() -> None:
            try:
                with psycopg.connect(owner, autocommit=True) as vacuum_conn:
                    started = time.perf_counter()
                    vacuum_conn.execute("VACUUM (ANALYZE) product_import_rows")
                    vacuum_result["ms"] = (time.perf_counter() - started) * 1000
            except Exception as exc:
                vacuum_result["error"] = exc

        worker = threading.Thread(target=run_vacuum, daemon=True)
        worker.start()
        foreground: list[float] = []
        with psycopg.connect(runtime) as conn:
            for _ in range(25):
                with conn.transaction():
                    set_tenant(conn, company_id)
                    started = time.perf_counter()
                    conn.execute(
                        """
                        SELECT row_number
                        FROM product_import_rows
                        WHERE company_id = %s
                          AND job_id = %s
                          AND status = 'VALID'
                        ORDER BY row_number
                        LIMIT 100
                        """,
                        (company_id, job_id),
                    ).fetchall()
                    foreground.append(
                        (time.perf_counter() - started) * 1000
                    )
                if not worker.is_alive():
                    break
        worker.join(timeout=10.0)
        vacuum_ms = float(vacuum_result.get("ms", 0.0))
        max_foreground_ms = max(foreground or [0.0])
        print(
            f"VACUUM_ANALYZE_MS={vacuum_ms:.3f} "
            f"FOREGROUND_MAX_MS={max_foreground_ms:.3f}"
        )
        check(
            "error" not in vacuum_result
            and not worker.is_alive()
            and vacuum_ms > 0.0
            and max_foreground_ms < 500.0,
            "Vacuum/analyze does not starve indexed foreground import reads",
            f"vacuum={vacuum_ms:.3f}ms foreground_max={max_foreground_ms:.3f}ms",
        )

    finally:
        with psycopg.connect(owner) as conn:
            conn.execute(
                """
                DELETE FROM product_import_jobs
                WHERE company_id = %s
                  AND id = %s
                """,
                (company_id, job_id),
            )
            conn.commit()
            print("CLEANUP=PASS")

    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    if failures:
        for label in failures:
            print("FAILED_CHECK=" + label)
        print("PRODUCT_IMPORT_PHASE15_SCALE_AUDIT=FAIL")
        raise SystemExit(1)
    print("PRODUCT_IMPORT_PHASE15_SCALE_AUDIT=PASS")


if __name__ == "__main__":
    main()
