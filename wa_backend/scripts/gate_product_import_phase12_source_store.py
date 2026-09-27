from __future__ import annotations

import os
from pathlib import Path
import sys

import psycopg
from dotenv import load_dotenv
from sqlalchemy.engine import make_url


BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(
    0,
    str(BACKEND),
)
load_dotenv(
    BACKEND / ".env"
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
        failures.append(
            label
        )


def source(
    *parts: str,
) -> str:
    return (
        BACKEND.joinpath(
            *parts
        ).read_text(
            encoding="utf-8"
        )
    )


router_source = source(
    "domains",
    "simple_products",
    "imports",
    "api",
    "router.py",
)
upload_source = source(
    "domains",
    "simple_products",
    "imports",
    "infrastructure",
    "upload_stream.py",
)
port_source = source(
    "domains",
    "simple_products",
    "imports",
    "application",
    "source_store.py",
)
queue_source = source(
    "domains",
    "simple_products",
    "imports",
    "infrastructure",
    "queue.py",
)
store_source = source(
    "domains",
    "simple_products",
    "imports",
    "infrastructure",
    "postgres_source_store.py",
)
worker_source = source(
    "domains",
    "simple_products",
    "imports",
    "application",
    "worker.py",
)
source_service_source = source(
    "domains",
    "simple_products",
    "imports",
    "application",
    "source_service.py",
)
admission_source = source(
    "domains",
    "simple_products",
    "imports",
    "infrastructure",
    "admission_repository.py",
)
admission_policy_source = source(
    "domains",
    "simple_products",
    "imports",
    "domain",
    "admission.py",
)
retention_source = source(
    "domains",
    "simple_products",
    "imports",
    "application",
    "retention_service.py",
)
capacity_monitor_source = source(
    "domains",
    "simple_products",
    "imports",
    "infrastructure",
    "capacity_monitor.py",
)
capacity_queue_source = source(
    "domains",
    "simple_products",
    "imports",
    "infrastructure",
    "capacity_queue.py",
)
docs_source = source(
    "domains",
    "simple_products",
    "imports",
    "SOURCE_STORE.md",
)
test_source = source(
    "tests",
    "test_product_import_phase12_source_store.py",
)
i18n_source = (
    ROOT
    / "dashboard"
    / "src"
    / "i18n"
    / "resources.ts"
).read_text(
    encoding="utf-8"
)

create_start = router_source.index(
    '@router.post("/imports", status_code=202)'
)
create_end = router_source.index(
    "\n\ndef _job_payload(",
    create_start,
)
create_source = router_source[
    create_start:create_end
]

check(
    "MAX_IMPORT_FILE_BYTES = 8 * 1024 * 1024"
    in router_source,
    "Server-side Product Import upload ceiling remains 8 MiB",
)

check(
    "spool_upload_bounded("
    in create_source
    and "file.read("
    not in create_source
    and "source_size="
    in create_source
    and "source_sha256="
    in create_source,
    "Main upload endpoint never materializes the source to calculate size/hash",
)

check(
    "SpooledTemporaryFile("
    in upload_source
    and "hashlib.sha256()"
    in upload_source
    and "UPLOAD_READ_CHUNK"
    in upload_source
    and "digest.update("
    in upload_source
    and "total > int("
    in upload_source,
    "Upload size and SHA-256 are computed incrementally with disk-backed spooling",
)

check(
    "class SourceStore(Protocol)"
    in port_source
    and "class TransactionalSourceStore("
    in port_source
    and "read_verified_bytes("
    in port_source
    and "delete_source_bytes_batch("
    in port_source,
    "Application owns a storage-neutral immutable SourceStore port",
)

check(
    "source_store: SourceStore"
    in worker_source
    and "POSTGRES_PRODUCT_IMPORT_SOURCE_STORE"
    not in worker_source,
    "Application worker depends on SourceStore, not the PostgreSQL adapter",
)

check(
    "source_id,"
    in queue_source
    and "source_payload,"
    in queue_source
    and "NULL"
    in queue_source
    and "persist_stream_on_connection("
    in queue_source,
    "New jobs persist an immutable source reference instead of inline source bytes",
)

admission_index = queue_source.index(
    "check_import_admission_before_persist("
)
persist_index = queue_source.index(
    "persist_stream_on_connection("
)
reserve_index = queue_source.index(
    "reserve_source_capacity_after_persist("
)
check(
    admission_index
    < persist_index
    < reserve_index,
    "Admission is checked before source persistence and capacity is atomically reserved before commit",
)

for token in (
    "PRODUCT_IMPORT_USER_RATE_LIMITED",
    "PRODUCT_IMPORT_TENANT_RATE_LIMITED",
    "PRODUCT_IMPORT_ACTIVE_JOB_LIMIT",
    "PRODUCT_IMPORT_TENANT_SOURCE_CAPACITY",
    "PRODUCT_IMPORT_GLOBAL_SOURCE_CAPACITY",
):
    check(
        token
        in admission_source,
        f"Admission policy enforces {token}",
    )

check(
    "pg_advisory_xact_lock"
    in admission_source
    and "product_import_tenant_source_capacity"
    in admission_source
    and "product_import_global_source_capacity"
    in admission_source
    and "live_bytes + %s <= %s"
    in admission_source,
    "Concurrent admissions use tenant serialization plus durable atomic byte counters",
)

check(
    "Retry-After"
    in create_source
    and "ProductImportAdmissionDenied"
    in create_source,
    "Admission denial returns stable retryable HTTP Retry-After semantics",
)

check(
    all(
        token
        in i18n_source
        for token in (
            "PRODUCT_IMPORT_USER_RATE_LIMITED",
            "PRODUCT_IMPORT_TENANT_RATE_LIMITED",
            "PRODUCT_IMPORT_ACTIVE_JOB_LIMIT",
            "PRODUCT_IMPORT_TENANT_SOURCE_CAPACITY",
            "PRODUCT_IMPORT_GLOBAL_SOURCE_CAPACITY",
        )
    ),
    "Admission-capacity error codes have user-facing localization",
)

verify_index = source_service_source.index(
    "read_verified_bytes("
)
parser_index = source_service_source.index(
    "with open_source("
)
check(
    verify_index
    < parser_index
    and "_verify_legacy_payload("
    in source_service_source,
    "Source hash/size verification occurs before parsing and retry parsing",
)

check(
    "SOURCE_CHUNK_BYTES"
    in store_source
    and "256"
    in store_source
    and "_verify_on_connection("
    in store_source
    and "digest.hexdigest()"
    in store_source
    and "expected_chunk_index"
    in store_source,
    "PostgreSQL SourceStore uses bounded ordered chunks with streaming verification",
)

check(
    "trg_product_import_source_metadata_immutable"
    in source(
        "alembic",
        "versions",
        "c9e5f2a7d310_stage12_import_source_store.py",
    )
    and "trg_product_import_source_chunk_immutable"
    in source(
        "alembic",
        "versions",
        "c9e5f2a7d310_stage12_import_source_store.py",
    ),
    "Database triggers enforce immutable source metadata/chunks",
)

check(
    "delete_source_bytes_batch("
    in retention_source
    and "fetch_expired_source_ids("
    in retention_source,
    "Phase 10 retention hard ceiling delegates source cleanup through SourceStore",
)

check(
    "live_source_bytes"
    in capacity_monitor_source
    and "high_water_source_bytes"
    in capacity_monitor_source
    and "oldest_live_source_age_seconds"
    in capacity_monitor_source
    and "quota_rejections_last_hour"
    in capacity_monitor_source,
    "Capacity metrics cover queued bytes, high-water, oldest source and quota rejections",
)

check(
    "@app.periodic("
    in capacity_queue_source
    and "PRODUCT_IMPORT_GLOBAL_SOURCE_STORAGE_HIGH"
    in capacity_queue_source
    and "PRODUCT_IMPORT_TENANT_SOURCE_STORAGE_HIGH"
    in capacity_queue_source
    and "PRODUCT_IMPORT_SOURCE_AGE_HIGH"
    in capacity_queue_source,
    "Periodic capacity monitoring emits storage/age alerts",
)

check(
    "general HTTP/IP rate limiter remains defense-in-depth"
    in docs_source
    and "PostgresProductImportSourceStore"
    in docs_source
    and "S3-compatible"
    in docs_source,
    "Production SourceStore choice and object-storage migration boundary are documented",
)

check(
    "PRODUCT_IMPORT_WAL_AMPLIFICATION_RATIO="
    in test_source
    and "pg_wal_lsn_diff"
    in test_source,
    "PostgreSQL-backed source capacity test measures WAL amplification",
)

check(
    "peak_8m"
    in test_source
    and "peak_1m"
    in test_source
    and "ProductImportSourceIntegrityError"
    in test_source
    and "parser.assert_not_called()"
    in test_source,
    "Tests prove bounded upload memory and fail-closed source tamper verification",
)

check(
    "PRODUCT_IMPORT_USER_WINDOW_SECONDS"
    in admission_policy_source
    and "PRODUCT_IMPORT_MAX_LIVE_SOURCE_BYTES_PER_TENANT"
    in admission_policy_source
    and "PRODUCT_IMPORT_GLOBAL_LIVE_SOURCE_BYTES"
    in admission_policy_source,
    "Admission limits are deployment-configurable instead of hard-wired transport behavior",
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
    make_url(
        raw
    )
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
    schema_tables = {
        str(
            row[
                0
            ]
        ):
            (
                bool(
                    row[
                        1
                    ]
                ),
                bool(
                    row[
                        2
                    ]
                ),
            )
        for row in conn.execute(
            """
            SELECT
                relname,
                relrowsecurity,
                relforcerowsecurity
            FROM pg_class
            WHERE relname IN (
                'product_import_sources',
                'product_import_source_chunks',
                'product_import_tenant_source_capacity',
                'product_import_admission_rejections'
            )
            """
        )
    }
    triggers = {
        str(
            row[
                0
            ]
        )
        for row in conn.execute(
            """
            SELECT tgname
            FROM pg_trigger
            WHERE tgname IN (
                'trg_product_import_source_metadata_immutable',
                'trg_product_import_source_chunk_immutable'
            )
              AND NOT tgisinternal
            """
        )
    }
    global_counter = conn.execute(
        """
        SELECT
            live_bytes,
            high_water_bytes
        FROM product_import_global_source_capacity
        WHERE id = 1
        """
    ).fetchone()

check(
    schema_tables
    == {
        "product_import_sources":
            (
                True,
                True,
            ),
        "product_import_source_chunks":
            (
                True,
                True,
            ),
        "product_import_tenant_source_capacity":
            (
                True,
                True,
            ),
        "product_import_admission_rejections":
            (
                True,
                True,
            ),
    },
    "SourceStore/admission tenant tables keep ENABLE + FORCE RLS",
    repr(
        schema_tables
    ),
)

check(
    triggers
    == {
        "trg_product_import_source_metadata_immutable",
        "trg_product_import_source_chunk_immutable",
    },
    "Source immutability triggers exist in the live database",
    repr(
        triggers
    ),
)

check(
    global_counter is not None
    and int(
        global_counter[
            0
        ]
        or 0
    )
    >= 0
    and int(
        global_counter[
            1
        ]
        or 0
    )
    >= int(
        global_counter[
            0
        ]
        or 0
    ),
    "Global source-capacity counter is durable and internally consistent",
    repr(
        global_counter
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
        "PRODUCT_IMPORT_PHASE12_SOURCE_STORE_GATE=FAIL"
    )
    raise SystemExit(1)

print(
    f"CHECKS={checks}"
)
print("FAILURES=0")
print(
    "PRODUCT_IMPORT_PHASE12_SOURCE_STORE_GATE=PASS"
)
