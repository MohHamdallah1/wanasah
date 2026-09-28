from __future__ import annotations

import os
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
NOISE_JOBS = 9
PLAN_TABLE = (
    "phase6_plan_barcodes"
)
PLAN_INDEX = (
    "phase6_plan_job_barcode_idx"
)

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
        node.get("Plans")
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
    marker = (
        "P6PLAN"
        + uuid4().hex[:12]
    )

    with psycopg.connect(
        dsn
    ) as conn:
        company_row = conn.execute(
            """
            SELECT company_id
            FROM product_variants
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()
        if company_row is None:
            raise RuntimeError(
                "Phase 6 plan gate requires one Product variant."
            )
        company_id = int(
            company_row[0]
        )

        actual_index = conn.execute(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename =
                  'product_import_row_barcodes'
              AND indexname =
                  'ix_product_import_row_barcode_job_barcode'
            """
        ).fetchone()
        actual_index_def = (
            str(actual_index[0])
            if actual_index
            else ""
        )
        check(
            bool(actual_index)
            and "(company_id, job_id, barcode, row_number)"
            in actual_index_def,
            "Real staging table owns the required company+job+barcode covering index",
            actual_index_def,
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
            repr(rls),
        )

        policy = conn.execute(
            """
            SELECT
                COALESCE(qual, ''),
                COALESCE(with_check, '')
            FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename =
                  'product_import_row_barcodes'
              AND policyname =
                  'product_import_row_barcodes_company_isolation'
            """
        ).fetchone()
        policy_text = (
            " ".join(
                str(value)
                for value in policy
            )
            if policy
            else ""
        )
        check(
            bool(policy)
            and "app.current_tenant"
            in policy_text
            and "company_id"
            in policy_text,
            "Barcode staging RLS policy is tenant-context scoped",
            policy_text,
        )

        primary_key = conn.execute(
            """
            SELECT pg_get_constraintdef(
                oid
            )
            FROM pg_constraint
            WHERE conrelid =
                'product_import_row_barcodes'::regclass
              AND contype = 'p'
            """
        ).fetchone()
        primary_key_def = (
            str(primary_key[0])
            if primary_key
            else ""
        )
        check(
            "company_id"
            in primary_key_def
            and "job_id"
            in primary_key_def
            and "row_number"
            in primary_key_def
            and "barcode"
            in primary_key_def,
            "Barcode staging key collapses unit/package shared identity within one row",
            primary_key_def,
        )

        # The functional tests exercise the real staging table. This temporary
        # relation is deliberately schema-minimal: it makes the 50k query-plan
        # benchmark repeatable without inserting hundreds of thousands of
        # artificial FK-backed rows into durable application tables.
        conn.execute(
            f"""
            CREATE TEMP TABLE {PLAN_TABLE} (
                company_id INTEGER NOT NULL,
                job_id UUID NOT NULL,
                barcode VARCHAR(128) NOT NULL,
                row_number INTEGER NOT NULL
            )
            """
        )

        for (
            job_index,
            job_id,
        ) in enumerate(jobs):
            conn.execute(
                f"""
                INSERT INTO {PLAN_TABLE} (
                    company_id,
                    job_id,
                    barcode,
                    row_number
                )
                SELECT
                    %s,
                    %s,
                    CASE
                        WHEN %s = 0
                         AND series IN (1, %s)
                        THEN %s
                        ELSE %s
                             || '_'
                             || %s::text
                             || '_'
                             || series::text
                    END,
                    series + 1
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

        conn.execute(
            f"""
            CREATE INDEX {PLAN_INDEX}
            ON {PLAN_TABLE} (
                company_id,
                job_id,
                barcode,
                row_number
            )
            """
        )
        internal_sql = f"""
            WITH barcode_occurrences AS MATERIALIZED (
                SELECT
                    row_number,
                    COUNT(*) OVER (
                        PARTITION BY barcode
                    ) AS occurrences
                FROM {PLAN_TABLE}
                WHERE company_id = %s
                  AND job_id = %s
            )
            SELECT DISTINCT row_number
            FROM barcode_occurrences
            WHERE occurrences > 1
        """
        # This used to take minutes on a real 50k job: staging has no
        # committed rows visible to autovacuum before the validating
        # transaction finishes, and the old self-join picked an N^2 loop.
        # EXPLAIN ANALYZE BEFORE ANALYZE proves correctness under stale
        # cardinality estimates, not merely after the plan is tuned.
        stale_internal_plan = explain(
            conn,
            internal_sql,
            (
                company_id,
                target_job,
            ),
        )
        check(
            any(
                node.get("Node Type") == "WindowAgg"
                for node in walk_plan(stale_internal_plan)
            ),
            "50k internal-duplicate scan stays single-pass before ANALYZE",
        )
        conn.execute(
            f"ANALYZE {PLAN_TABLE}"
        )
        internal_plan = explain(
            conn,
            internal_sql,
            (
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

        external_sql = f"""
            SELECT DISTINCT staged.row_number
            FROM {PLAN_TABLE} AS staged
            JOIN LATERAL (
                SELECT existing.id
                FROM product_barcodes AS existing
                WHERE existing.company_id =
                      staged.company_id
                  AND existing.barcode =
                      staged.barcode
                  AND existing.is_active
                      IS TRUE
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

        protected_internal = [
            relation
            for relation
            in internal_seq
            if relation
            == PLAN_TABLE
        ]
        protected_external = [
            relation
            for relation
            in external_seq
            if relation
            in {
                PLAN_TABLE,
                "product_barcodes",
            }
        ]

        check(
            PLAN_INDEX
            in internal_indexes,
            "50k internal-duplicate plan uses company+job+barcode index",
            repr(
                internal_indexes
            ),
        )
        check(
            not protected_internal,
            "50k internal-duplicate plan has no sequential scan on barcode staging",
            repr(
                internal_seq
            ),
        )
        check(
            PLAN_INDEX
            in external_indexes,
            "50k external-conflict plan uses company+job+barcode index",
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
            not protected_external,
            "50k external-conflict plan has no sequential scan on staging or active barcodes",
            repr(
                external_seq
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

    phase6_repository = (
        repository_source[
            repository_source.index(
                "async def rebuild_job_barcode_staging("
            ):
            repository_source.index(
                "async def load_active_actor("
            )
        ]
    )
    check(
        ".in_("
        not in phase6_repository,
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
    print("FAILURES=0")
    print(
        "PRODUCT_IMPORT_PHASE6_QUERY_PLAN_GATE=PASS"
    )


if __name__ == "__main__":
    main()
