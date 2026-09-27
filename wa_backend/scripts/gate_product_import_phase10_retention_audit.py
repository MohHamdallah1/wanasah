from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from sqlalchemy.engine import make_url


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(
    0,
    str(BACKEND),
)
load_dotenv(
    BACKEND / ".env"
)

from domains.simple_products.imports.domain.retention import (  # noqa: E402
    DEFAULT_PRODUCT_IMPORT_RETENTION,
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


def source(
    *parts: str,
) -> str:
    return BACKEND.joinpath(
        *parts
    ).read_text(
        encoding="utf-8"
    )


policy = (
    DEFAULT_PRODUCT_IMPORT_RETENTION
)
check(
    policy.upload_bytes
    == timedelta(
        days=7
    )
    and policy.full_row_detail
    == timedelta(
        days=30
    )
    and policy.compact_lineage
    == timedelta(
        days=365
    ),
    "Retention windows are explicit: upload bytes 7d, full row detail 30d, compact lineage 365d",
)
check(
    0
    < policy.batch_size
    <= 5_000
    and policy.max_batches_per_run
    > 0,
    "Retention work is bounded by batch size and per-run batch ceiling",
)

retention_repo = source(
    "domains",
    "simple_products",
    "imports",
    "infrastructure",
    "retention_repository.py",
)
retention_service = source(
    "domains",
    "simple_products",
    "imports",
    "application",
    "retention_service.py",
)
retention_queue = source(
    "domains",
    "simple_products",
    "imports",
    "infrastructure",
    "retention_queue.py",
)
audit_service = source(
    "domains",
    "simple_products",
    "imports",
    "application",
    "audit_service.py",
)
router_source = source(
    "domains",
    "simple_products",
    "imports",
    "api",
    "router.py",
)
staging_source = source(
    "domains",
    "simple_products",
    "imports",
    "application",
    "staging_service.py",
)
execution_source = source(
    "domains",
    "simple_products",
    "imports",
    "application",
    "execution_service.py",
)

check(
    "source_payload=None"
    in staging_source
    and "source_payload_cleared_at="
    in staging_source,
    "Successful staging clears upload bytes early and records cleanup time",
)

check(
    "delete_job_rows("
    not in execution_source,
    "Successful execution does not delete durable row lineage",
)

for required in (
    "company_id = :company_id",
    "finished_at <= :cutoff",
    "LIMIT :batch_limit",
    "FOR UPDATE",
    "SKIP LOCKED",
):
    check(
        required
        in retention_repo,
        f"Cleanup SQL enforces {required}",
    )

check(
    "source_sha256"
    not in retention_repo,
    "Cleanup never mutates immutable source hash",
)

check(
    "row_identity"
    not in retention_repo
    and "product_variant_id"
    not in retention_repo
    and "error_code"
    not in retention_repo,
    "Compaction does not overwrite row identity, Product linkage, or error code",
)

check(
    "raw_data = '{}'::jsonb"
    in retention_repo
    and "normalized_data = '{}'::jsonb"
    in retention_repo
    and "compacted_at = CURRENT_TIMESTAMP"
    in retention_repo,
    "Compaction removes heavy row JSON while marking the lineage record",
)

check(
    "open_tenant_session("
    in retention_service,
    "Cleanup execution always opens explicit tenant context",
)

check(
    "payloads_cleared"
    in retention_service
    and "rows_compacted"
    in retention_service
    and "lineage_rows_deleted"
    in retention_service
    and "batch_limit_reached"
    in retention_service,
    "Cleanup exposes bounded-work observability counters",
)

check(
    "@app.periodic("
    in retention_queue
    and "cleanup_product_import_retention"
    in retention_queue
    and "schedule_product_import_retention"
    in retention_queue,
    "Retention cleanup is registered as periodic background work",
)

check(
    "open_tenant_session("
    in audit_service
    and '"/imports/{job_id}/lineage"'
    in router_source
    and "_require_manage("
    in router_source[
        router_source.index(
            '"/imports/{job_id}/lineage"'
        ):
        router_source.index(
            '"/imports/{job_id}/correction"'
        )
    ],
    "Audit lineage path is authorized and tenant-scoped",
)

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
dsn = (
    make_url(raw)
    .set(
        drivername="postgresql"
    )
    .render_as_string(
        hide_password=False
    )
)
with psycopg.connect(
    dsn
) as conn:
    job_columns = {
        str(
            row[
                0
            ]
        )
        for row in conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'product_import_jobs'
              AND column_name IN (
                  'source_payload',
                  'source_payload_cleared_at',
                  'source_sha256',
                  'finished_at'
              )
            """
        )
    }
    row_columns = {
        str(
            row[
                0
            ]
        )
        for row in conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'product_import_rows'
              AND column_name IN (
                  'row_identity',
                  'row_number',
                  'product_variant_id',
                  'status',
                  'error_code',
                  'compacted_at'
              )
            """
        )
    }
    index = conn.execute(
        """
        SELECT indexdef
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND tablename = 'product_import_jobs'
          AND indexname =
              'ix_product_import_job_retention'
        """
    ).fetchone()

check(
    job_columns
    == {
        "source_payload",
        "source_payload_cleared_at",
        "source_sha256",
        "finished_at",
    },
    "Job schema carries source-retention and immutable hash lineage",
    repr(
        job_columns
    ),
)
check(
    row_columns
    == {
        "row_identity",
        "row_number",
        "product_variant_id",
        "status",
        "error_code",
        "compacted_at",
    },
    "Row schema preserves compact audit lineage metadata",
    repr(
        row_columns
    ),
)
check(
    index is not None
    and "company_id"
    in str(
        index[
            0
        ]
    )
    and "finished_at"
    in str(
        index[
            0
        ]
    ),
    "Retention cleanup owns a company+finished_at supporting index",
    repr(
        index
    ),
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
        "PRODUCT_IMPORT_PHASE10_RETENTION_AUDIT_GATE=FAIL"
    )
    raise SystemExit(1)

print(
    f"CHECKS={checks}"
)
print("FAILURES=0")
print(
    "PRODUCT_IMPORT_PHASE10_RETENTION_AUDIT_GATE=PASS"
)
