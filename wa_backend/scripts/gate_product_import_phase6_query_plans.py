from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
from dotenv import load_dotenv
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
sys.path.insert(
    0,
    str(BACKEND),
)
load_dotenv(
    BACKEND / ".env"
)


TARGET_ROWS = 50_000
NOISE_JOBS = 0

checks = 0
failures: list[str] = []


def check(
    condition: bool,
    label: str,
    detail: str = "",
) -> None:
    global checks
    checks += 1
    prefix = (
        "[PASS]"
        if condition
        else "[FAIL]"
    )
    suffix = (
        f" — {detail}"
        if detail
        else ""
    )
    print(
        f"{prefix} {label}{suffix}"
    )
    if not condition:
        failures.append(label)


def owner_dsn() -> str:
    raw = (
        os.getenv(
            "DATABASE_URL_MIGRATION"
        )
        or os.getenv(
            "DATABASE_URL"
        )
    )
    if not raw:
        raise RuntimeError(
            "Database URL is required."
        )
    return (
        make_url(raw)
        .set(
            drivername="postgresql"
        )
        .render_as_string(
            hide_password=False
        )
    )


def walk_plan(
    node: dict,
):
    yield node
    for child in (
        node.get(
            "Plans"
        )
        or []
    ):
        yield from walk_plan(
            child
        )


def explain(
    conn,
    sql: str,
    params: tuple,
) -> dict:
    row = conn.execute(
        "EXPLAIN "
        "(ANALYZE, BUFFERS, FORMAT JSON) "
        + sql,
        params,
    ).fetchone()
    return row[0][0][
        "Plan"
    ]


def plan_evidence(
    plan: dict,
) -> tuple[
    list[str],
    list[str],
]:
    indexes: list[str] = []
    seq_relations: list[str] = []
    for node in walk_plan(
        plan
    ):
        index_name = node.get(
            "Index Name"
        )
        if index_name:
            indexes.append(
                str(index_name)
            )
        if (
            node.get(
                "Node Type"
            )
            == "Seq Scan"
        ):
            relation = node.get(
                "Relation Name"
            )
            if relation:
                seq_relations.append(
                    str(relation)
                )
    return (
        indexes,
        seq_relations,
    )


def main() -> None:
    dsn = owner_dsn()
    marker = (
        "P6PLAN"
        + uuid4().hex[:12]
    )
    target_job = uuid4()
    jobs = [
        target_job,
        *[
            uuid4()
            for _ in range(
                NOISE_JOBS
            )
        ],
    ]

    with psycopg.connect(
        dsn
    ) as conn:
        fixture = conn.execute(
            """
            SELECT
                variants.company_id,
                drivers.id
            FROM product_variants AS variants
            JOIN drivers
              ON drivers.company_id = variants.company_id
             AND drivers.is_active IS TRUE
            ORDER BY variants.id
            LIMIT 1
            """
        ).fetchone()
        if fixture is None:
            raise RuntimeError(
                "Phase 6 plan gate requires one Product variant and active driver."
            )
        (
            company_id,
            driver_id,
        ) = map(
            int,
            fixture,
        )

        try:
            for job_index, job_id in enumerate(
                jobs
            ):
                conn.execute(
                    """
                    INSERT INTO product_import_jobs (
                        id,
                        company_id,
                        request_id,
                        created_by,
                        file_name,
                        content_type,
                        source_payload,
                        source_sha256,
                        file_size,
                        status,
                        detected_headers,
                        suggested_mapping,
                        column_mapping,
                        default_lot_control_mode,
                        default_expiry_control_mode,
                        error_summary,
                        total_rows,
                        processed_rows,
                        valid_rows,
                        failed_rows,
                        version
                    )
                    VALUES (
                        %s,%s,%s,%s,
                        %s,
                        'text/csv',
                        NULL,
                        %s,
                        1,
                        'VALIDATING',
                        '[]'::jsonb,
                        '{}'::jsonb,
                        '{}'::jsonb,
                        'NONE',
                        'NONE',
                        '{}'::jsonb,
                        %s,0,%s,0,1
                    )
                    """,
                    (
                        job_id,
                        company_id,
                        uuid4(),
                        driver_id,
                        f"phase6-plan-{job_index}.csv",
                        uuid4().hex.ljust(
                            64,
                            "0",
                        )[:64],
                        TARGET_ROWS,
                        TARGET_ROWS,
                    ),
                )

                conn.execute(
                    """
                    INSERT INTO product_import_rows (
                        company_id,
                        job_id,
                        row_number,
                        raw_data,
                        normalized_data,
                        status,
                        version
                    )
                    SELECT
                        %s,
                        %s,
                        series + 1,
                        '{}'::jsonb,
                        '{}'::jsonb,
                        'VALID',
                        1
                    FROM generate_series(
                        1,
                        %s
                    ) AS series
                    """,
                    (
                        company_id,
                        job_id,
                        TARGET_ROWS,
                    ),
                )

                conn.execute(
                    """
                    INSERT INTO product_import_row_barcodes (
                        company_id,
                        job_id,
                        row_number,
                        barcode
                    )
                    SELECT
                        %s,
                        %s,
                        series + 1,
                        CASE
                            WHEN %s = 0
                             AND series IN (1, %s)
                            THEN %s
                            ELSE %s
                                 || '_'
                                 || %s::text
                                 || '_'
                                 || series::text
                        END
                    FROM generate_series(
                        1,
                        %s
                    ) AS series
                    """,
                    (
                        company_id,
                        job_id,
                        job_index,
                        TARGET_ROWS,
                        marker + "_DUP",
                        marker,
                        job_index,
                        TARGET_ROWS,
                    ),
                )

            conn.commit()

            # Make the covering-index visibility state production-like so
            # the planner can choose the narrow index-only path instead of a
            # heap scan simply because this benchmark just inserted the rows.
            with psycopg.connect(
                dsn,
                autocommit=True,
            ) as maintenance:
                maintenance.execute(
                    "VACUUM (ANALYZE) product_import_row_barcodes"
                )
                maintenance.execute(
                    "ANALYZE product_barcodes"
                )

            internal_sql = """
                WITH duplicate_barcodes AS (
                    SELECT barcode
                    FROM product_import_row_barcodes
                    WHERE company_id = %s
                      AND job_id = %s
                    GROUP BY barcode
                    HAVING COUNT(*) > 1
                )
                SELECT DISTINCT staged.row_number
                FROM product_import_row_barcodes AS staged
                JOIN duplicate_barcodes AS duplicates
                  ON duplicates.barcode = staged.barcode
                WHERE staged.company_id = %s
                  AND staged.job_id = %s
            """
            internal_plan = explain(
                conn,
                internal_sql,
                (
                    company_id,
                    target_job,
                    company_id,
                    target_job,
                ),
            )
            (
                internal_indexes,
                internal_seq,
            ) = plan_evidence(
                internal_plan
            )

            external_sql = """
                SELECT DISTINCT staged.row_number
                FROM product_import_row_barcodes AS staged
                JOIN LATERAL (
                    SELECT existing.id
                    FROM product_barcodes AS existing
                    WHERE existing.company_id = staged.company_id
                      AND existing.barcode = staged.barcode
                      AND existing.is_active IS TRUE
                    LIMIT 1
                    OFFSET 0
                ) AS conflict
                  ON TRUE
                WHERE staged.company_id = %s
                  AND staged.job_id = %s
            """
            external_plan = explain(
                conn,
                external_sql,
                (
                    company_id,
                    target_job,
                ),
            )
            (
                external_indexes,
                external_seq,
            ) = plan_evidence(
                external_plan
            )

            protected_relations = {
                "product_import_row_barcodes",
                "product_barcodes",
            }
            internal_bad_seq = [
                relation
                for relation
                in internal_seq
                if relation
                in protected_relations
            ]
            external_bad_seq = [
                relation
                for relation
                in external_seq
                if relation
                in protected_relations
            ]

            check(
                "ix_product_import_row_barcode_job_barcode"
                in internal_indexes,
                "50k internal-duplicate plan uses Product Import job+barcode index",
                repr(
                    internal_indexes
                ),
            )
            check(
                not internal_bad_seq,
                "50k internal-duplicate plan has no sequential scan on barcode staging",
                repr(
                    internal_seq
                ),
            )
            check(
                "ix_product_import_row_barcode_job_barcode"
                in external_indexes,
                "50k external-conflict plan uses Product Import job+barcode index",
                repr(
                    external_indexes
                ),
            )
            check(
                "uq_active_product_barcode"
                in external_indexes,
                "50k external-conflict plan uses active Product barcode unique index",
                repr(
                    external_indexes
                ),
            )
            check(
                not external_bad_seq,
                "50k external-conflict plan has no sequential scan on staging or active barcodes",
                repr(
                    external_seq
                ),
            )

            rls = conn.execute(
                """
                SELECT
                    relrowsecurity,
                    relforcerowsecurity
                FROM pg_class
                WHERE oid =
                    'product_import_row_barcodes'::regclass
                """
            ).fetchone()
            check(
                tuple(rls)
                == (
                    True,
                    True,
                ),
                "Product Import barcode staging keeps ENABLE + FORCE RLS",
                repr(
                    rls
                ),
            )

            print(
                "INTERNAL_PLAN_INDEXES="
                + repr(
                    internal_indexes
                )
            )
            print(
                "EXTERNAL_PLAN_INDEXES="
                + repr(
                    external_indexes
                )
            )

        finally:
            conn.rollback()
            conn.execute(
                """
                DELETE FROM product_import_jobs
                WHERE company_id = %s
                  AND id = ANY(%s)
                """,
                (
                    company_id,
                    jobs,
                ),
            )
            conn.commit()

    repository_source = (
        BACKEND
        / "domains"
        / "simple_products"
        / "imports"
        / "infrastructure"
        / "repository.py"
    ).read_text(
        encoding="utf-8"
    )
    validation_source = (
        BACKEND
        / "domains"
        / "simple_products"
        / "imports"
        / "application"
        / "validation_service.py"
    ).read_text(
        encoding="utf-8"
    )

    check(
        "GROUP BY barcode"
        in repository_source
        and "HAVING COUNT(*) > 1"
        in repository_source,
        "Internal duplicate detection is set-based SQL",
    )
    check(
        "JOIN LATERAL"
        in repository_source
        and "product_barcodes"
        in repository_source,
        "External conflict detection is a tenant-scoped SQL join",
    )
    check(
        "find_active_barcodes"
        not in validation_source
        and "barcode_rows"
        not in validation_source,
        "Validation no longer pulls import-wide barcode sets into Python",
    )
    check(
        ".in_("
        not in repository_source[
            repository_source.index(
                "async def rebuild_job_barcode_staging("
            ):
            repository_source.index(
                "async def load_active_actor("
            )
        ],
        "Phase 6 barcode checks contain no giant parameterized IN query",
    )

    if failures:
        print(
            f"CHECKS={checks}"
        )
        print(
            f"FAILURES={len(failures)}"
        )
        for failure in failures:
            print(
                f"FAIL: {failure}"
            )
        print(
            "PRODUCT_IMPORT_PHASE6_QUERY_PLAN_GATE=FAIL"
        )
        raise SystemExit(1)

    print(
        f"CHECKS={checks}"
    )
    print(
        "FAILURES=0"
    )
    print(
        "PRODUCT_IMPORT_PHASE6_QUERY_PLAN_GATE=PASS"
    )


if __name__ == "__main__":
    main()
