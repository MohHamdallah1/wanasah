from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
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

from domains.simple_products.imports.application.execution_service import (  # noqa: E402
    _batch_request_id,
)
from domains.simple_products.imports.application.state_machine import (  # noqa: E402
    ALLOWED_JOB_TRANSITIONS,
    ALLOWED_ROW_TRANSITIONS,
    JobStatus,
    RowStatus,
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


execution_source = (
    BACKEND
    / "domains"
    / "simple_products"
    / "imports"
    / "application"
    / "execution_service.py"
).read_text(
    encoding="utf-8"
)
correction_service_source = (
    BACKEND
    / "domains"
    / "simple_products"
    / "imports"
    / "application"
    / "correction_service.py"
).read_text(
    encoding="utf-8"
)
correction_repo_source = (
    BACKEND
    / "domains"
    / "simple_products"
    / "imports"
    / "infrastructure"
    / "correction_repository.py"
).read_text(
    encoding="utf-8"
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
router_source = (
    BACKEND
    / "domains"
    / "simple_products"
    / "imports"
    / "api"
    / "router.py"
).read_text(
    encoding="utf-8"
)
migration_source = (
    BACKEND
    / "alembic"
    / "versions"
    / "f2a6d8c4b901_stage8_import_row_identity.py"
).read_text(
    encoding="utf-8"
)


with psycopg.connect(
    owner_dsn()
) as conn:
    column = conn.execute(
        """
        SELECT
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'product_import_rows'
          AND column_name = 'row_identity'
        """
    ).fetchone()
    check(
        column is not None
        and column[0] == "NO",
        "Product Import row identity exists and is NOT NULL",
        repr(
            column
        ),
    )
    check(
        column is not None
        and "gen_random_uuid"
        in str(
            column[1]
        ),
        "Product Import row identity has a database default",
        repr(
            column
        ),
    )

    constraint = conn.execute(
        """
        SELECT pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conname =
            'uq_product_import_row_job_identity'
        """
    ).fetchone()
    check(
        constraint is not None
        and all(
            token
            in str(
                constraint[0]
            )
            for token
            in (
                "company_id",
                "job_id",
                "row_identity",
            )
        ),
        "Row identity is unique inside tenant + import job",
        repr(
            constraint
        ),
    )

    trigger = conn.execute(
        """
        SELECT tgname
        FROM pg_trigger
        WHERE tgrelid =
            'product_import_rows'::regclass
          AND NOT tgisinternal
          AND tgname =
            'trg_product_import_row_identity_immutable'
        """
    ).fetchone()
    check(
        trigger is not None,
        "Database trigger enforces immutable Product Import row identity",
        repr(
            trigger
        ),
    )


identity = uuid4()
job_id = uuid4()
first = SimpleNamespace(
    row_identity=identity,
    row_number=2,
)
same_identity = SimpleNamespace(
    row_identity=identity,
    row_number=50_001,
)
check(
    _batch_request_id(
        job_id,
        [
            first
        ],
    )
    == _batch_request_id(
        job_id,
        [
            same_identity
        ],
    ),
    "Execution idempotency key is derived from job + immutable row identity, not row number",
)

check(
    "begin_idempotent_operation("
    in execution_source
    and "complete_idempotent_operation("
    in execution_source
    and "_row_identity("
    in execution_source,
    "Product creation is wrapped by durable operation idempotency using row identity",
)

execute_once_block = execution_source[
    execution_source.index(
        "async def _execute_rows_once("
    ):
    execution_source.index(
        "async def _execute_rows_best_effort("
    )
]
check(
    ".commit("
    not in execute_once_block,
    "Product changes, idempotency result and row outcome remain in one outer transaction",
)

check(
    "status=RowStatus.VALID.value"
    in execution_source
    and "status=RowStatus.IMPORTED.value"
    not in execution_source[
        execution_source.index(
            "rows = await list_job_rows("
        ):
        execution_source.index(
            "if not rows:"
        )
    ],
    "Worker execution selects VALID rows only and never selects IMPORTED rows",
)

check(
    ALLOWED_ROW_TRANSITIONS[
        RowStatus.IMPORTED
    ]
    == frozenset(),
    "IMPORTED rows remain immutable terminal outcomes",
)

check(
    ALLOWED_ROW_TRANSITIONS[
        RowStatus.INVALID
    ]
    == frozenset({
        RowStatus.STAGED,
    })
    and ALLOWED_ROW_TRANSITIONS[
        RowStatus.IMPORT_FAILED
    ]
    == frozenset({
        RowStatus.STAGED,
    }),
    "Only failed row outcomes can return to STAGED for correction",
)

check(
    JobStatus.VALIDATING
    in ALLOWED_JOB_TRANSITIONS[
        JobStatus.VALIDATION_FAILED
    ]
    and JobStatus.VALIDATING
    in ALLOWED_JOB_TRANSITIONS[
        JobStatus.COMPLETED_WITH_ERRORS
    ],
    "Failed/partial jobs can re-enter validation through correction",
)

check(
    "fetch_failed_rows_batch("
    in correction_service_source
    and '"INVALID"'
    in repository_source
    and '"IMPORT_FAILED"'
    in repository_source,
    "Correction artifacts are sourced only from failed rows",
)

check(
    "__wanasah_row_identity"
    in correction_service_source
    and "row_identity"
    in correction_service_source,
    "Correction artifacts carry stable row identity",
)

check(
    "rows.status = 'IMPORTED'"
    in correction_repo_source
    and "Correction cannot modify an already imported row."
    in correction_repo_source,
    "Correction persistence explicitly rejects imported-row mutation",
)

check(
    "operation_idempotency"
    in correction_repo_source
    and "request_id"
    in correction_repo_source
    and "replayed"
    in correction_repo_source,
    "Correction upload itself is durable and idempotent",
)

check(
    "defer_import_on_connection("
    in correction_repo_source
    and "UPDATE product_import_jobs"
    in correction_repo_source,
    "Correction row update, job transition and queue defer share one transaction",
)

check(
    '@router.get(\n    "/imports/{job_id}/correction"'
    in router_source
    and '@router.post(\n    "/imports/{job_id}/correction"'
    in router_source,
    "Correction download/upload API contract is registered",
)

check(
    "gen_random_uuid()"
    in migration_source
    and "row identity is immutable"
    in migration_source.lower(),
    "Owned Phase 8 migration creates and protects row identities",
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
        "PRODUCT_IMPORT_PHASE8_IDEMPOTENCY_CORRECTION_GATE=FAIL"
    )
    raise SystemExit(1)

print(
    f"CHECKS={checks}"
)
print(
    "FAILURES=0"
)
print(
    "PRODUCT_IMPORT_PHASE8_IDEMPOTENCY_CORRECTION_GATE=PASS"
)
