"""PostgreSQL-backed queue for asynchronous product imports."""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import psycopg
from procrastinate import App, PsycopgConnector, RetryStrategy
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url

from config import Config
from domains.product_tracking import normalize_tracking_mode
from workers.recovery import recover_safe_stalled_jobs


def _psycopg_dsn() -> str:
    url = make_url(Config.SQLALCHEMY_DATABASE_URI)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError(
            "Product import worker requires PostgreSQL."
        )
    return url.set(
        drivername="postgresql"
    ).render_as_string(
        hide_password=False
    )


DSN = _psycopg_dsn()
PRODUCT_IMPORT_HEARTBEAT_SECONDS = 10.0
PRODUCT_IMPORT_STALLED_TIMEOUT_SECONDS = 30.0
PRODUCT_IMPORT_STALLED_ALLOWLIST = frozenset(
    {
        "wanasah.process_product_import",
        "wanasah.recover_stalled_product_imports",
    }
)

app = App(
    connector=PsycopgConnector(
        conninfo=DSN
    ),
    worker_defaults={
        "delete_jobs": "never",
        "shutdown_graceful_timeout": 60,
        "update_heartbeat_interval": PRODUCT_IMPORT_HEARTBEAT_SECONDS,
        "stalled_worker_timeout": PRODUCT_IMPORT_STALLED_TIMEOUT_SECONDS,
    },
)


@app.periodic(cron="*/5 * * * *")
@app.task(
    name="wanasah.recover_stalled_product_imports",
    queue="product-import",
    queueing_lock="product-import-stalled-recovery",
    lock="product-import-stalled-recovery",
)
async def recover_stalled_product_imports(
    timestamp: int | None = None,
) -> dict[str, int]:
    return await recover_safe_stalled_jobs(
        app,
        allowlist=PRODUCT_IMPORT_STALLED_ALLOWLIST,
        seconds_since_heartbeat=PRODUCT_IMPORT_STALLED_TIMEOUT_SECONDS,
    )


@app.task(
    name="wanasah.process_product_import",
    queue="product-import",
    retry=RetryStrategy(
        max_attempts=4,
        wait=3,
        exponential_wait=2,
    ),
    pass_context=True,
)
async def process_product_import(
    context,
    company_id: int,
    job_id: str,
) -> None:
    from product_import_worker import (
        ProductImportTerminalError,
        mark_import_runtime_failure,
        run_product_import_job,
    )

    job_uuid = UUID(str(job_id))
    try:
        await run_product_import_job(
            company_id=int(company_id),
            job_id=job_uuid,
        )
    except ProductImportTerminalError as exc:
        await mark_import_runtime_failure(
            company_id=int(company_id),
            job_id=job_uuid,
            message=str(exc),
            final_attempt=True,
            retryable=False,
        )
    except Exception as exc:
        final_attempt = (
            context.task.retry.get_retry_decision(
                exception=exc,
                job=context.job,
            )
            is None
        )
        await mark_import_runtime_failure(
            company_id=int(company_id),
            job_id=job_uuid,
            message=str(exc),
            final_attempt=final_attempt,
            retryable=final_attempt,
        )
        raise


async def _defer(
    conn: psycopg.AsyncConnection,
    *,
    company_id: int,
    job_id: UUID,
) -> None:
    await process_product_import.configure(
        connection=conn,
        lock=f"product-import:{int(company_id)}",
    ).defer_async(
        company_id=int(company_id),
        job_id=str(job_id),
    )


async def enqueue_new_import(
    *,
    company_id: int,
    actor_id: int,
    request_id: UUID,
    file_name: str,
    content_type: str,
    payload: bytes,
    source_sha256: str,
    default_lot_control_mode: str,
    default_expiry_control_mode: str,
) -> dict[str, Any]:
    """Create or replay one durable import operation.

    The request id is a network retry key. Reusing it with different input is
    rejected instead of silently returning an unrelated previous job.
    """
    job_id = uuid4()
    request_text = str(request_id)
    default_lot_control_mode = normalize_tracking_mode(
        default_lot_control_mode,
        field_name="default_lot_control_mode",
    )
    default_expiry_control_mode = normalize_tracking_mode(
        default_expiry_control_mode,
        field_name="default_expiry_control_mode",
    )

    async with await psycopg.AsyncConnection.connect(
        DSN
    ) as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config("
                "'app.current_tenant', %s, true)",
                [str(int(company_id))],
            )
            await conn.execute(
                "SELECT pg_advisory_xact_lock("
                "%s, hashtext(%s))",
                [
                    int(company_id),
                    request_text,
                ],
            )

            cursor = await conn.execute(
                """
                SELECT
                    id,
                    created_by,
                    file_name,
                    source_sha256,
                    file_size,
                    status,
                    default_lot_control_mode,
                    default_expiry_control_mode
                FROM product_import_jobs
                WHERE company_id = %s
                  AND request_id = %s
                FOR UPDATE
                """,
                [
                    int(company_id),
                    request_id,
                ],
            )
            existing = await cursor.fetchone()
            if existing is not None:
                (
                    existing_id,
                    existing_actor,
                    existing_name,
                    existing_sha,
                    existing_size,
                    existing_status,
                    existing_lot_default,
                    existing_expiry_default,
                ) = existing

                same_request = (
                    int(existing_actor)
                    == int(actor_id)
                    and str(existing_name)
                    == str(file_name)
                    and str(existing_sha)
                    == str(source_sha256)
                    and int(existing_size)
                    == len(payload)
                    and str(existing_lot_default)
                    == default_lot_control_mode
                    and str(existing_expiry_default)
                    == default_expiry_control_mode
                )
                if not same_request:
                    raise ValueError(
                        "request_id was already used for a different product import."
                    )

                return {
                    "job_id": UUID(
                        str(existing_id)
                    ),
                    "status": str(
                        existing_status
                    ),
                    "replayed": True,
                }

            await conn.execute(
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
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,
                    'QUEUED',
                    '[]'::jsonb,
                    '{}'::jsonb,
                    '{}'::jsonb,
                    %s,
                    %s,
                    '{}'::jsonb,
                    0,0,0,0,1
                )
                """,
                [
                    job_id,
                    int(company_id),
                    request_id,
                    int(actor_id),
                    file_name,
                    content_type,
                    payload,
                    source_sha256,
                    len(payload),
                    default_lot_control_mode,
                    default_expiry_control_mode,
                ],
            )
            await _defer(
                conn,
                company_id=int(company_id),
                job_id=job_id,
            )

    return {
        "job_id": job_id,
        "status": "QUEUED",
        "replayed": False,
    }


async def requeue_import(
    *,
    company_id: int,
    job_id: UUID,
    mapping: dict[str, str],
) -> str:
    """Apply mapping once; repeated lost-response retries are state-idempotent."""
    async with await psycopg.AsyncConnection.connect(
        DSN
    ) as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config("
                "'app.current_tenant', %s, true)",
                [str(int(company_id))],
            )
            cursor = await conn.execute(
                """
                SELECT status, column_mapping
                FROM product_import_jobs
                WHERE company_id = %s
                  AND id = %s
                FOR UPDATE
                """,
                [
                    int(company_id),
                    job_id,
                ],
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(
                    "Import job was not found."
                )

            status = str(row[0])
            current_mapping = dict(
                row[1] or {}
            )

            if status == "NEEDS_MAPPING":
                result = await conn.execute(
                    """
                    UPDATE product_import_jobs
                    SET column_mapping = %s,
                        status = 'VALIDATING',
                        error_summary = '{}'::jsonb,
                        version = version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE company_id = %s
                      AND id = %s
                      AND status = 'NEEDS_MAPPING'
                    """,
                    [
                        Jsonb(mapping),
                        int(company_id),
                        job_id,
                    ],
                )
                if result.rowcount != 1:
                    raise ValueError(
                        "Import mapping changed concurrently."
                    )
                await _defer(
                    conn,
                    company_id=int(company_id),
                    job_id=job_id,
                )
                return "VALIDATING"

            replayable_states = {
                "QUEUED",
                "PARSING",
                "VALIDATING",
                "IMPORTING",
                "RETRYING",
                "VALIDATION_FAILED",
                "COMPLETED",
            }
            if (
                status in replayable_states
                and current_mapping == mapping
            ):
                return status

            if (
                status in replayable_states
                and current_mapping != mapping
            ):
                raise ValueError(
                    "Import already advanced with a different column mapping."
                )

            raise ValueError(
                "Import job is not waiting for column mapping."
            )


async def retry_failed_import(
    *,
    company_id: int,
    job_id: UUID,
) -> str:
    """Retry once from FAILED; duplicate client retries only observe current state."""
    async with await psycopg.AsyncConnection.connect(
        DSN
    ) as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config("
                "'app.current_tenant', %s, true)",
                [str(int(company_id))],
            )
            cursor = await conn.execute(
                """
                SELECT status, error_summary
                FROM product_import_jobs
                WHERE company_id = %s
                  AND id = %s
                FOR UPDATE
                """,
                [
                    int(company_id),
                    job_id,
                ],
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(
                    "Import job was not found."
                )

            status = str(row[0])
            summary = dict(
                row[1] or {}
            )

            if status != "FAILED":
                if status in {
                    "QUEUED",
                    "PARSING",
                    "VALIDATING",
                    "IMPORTING",
                    "RETRYING",
                    "COMPLETED",
                }:
                    return status
                raise ValueError(
                    "Import job is not retryable."
                )

            if summary.get(
                "retryable"
            ) is not True:
                raise ValueError(
                    "Import job failed with a non-retryable error."
                )

            resume_status = str(
                summary.get(
                    "resume_status"
                )
                or "QUEUED"
            )
            if resume_status not in {
                "QUEUED",
                "PARSING",
                "VALIDATING",
                "IMPORTING",
            }:
                resume_status = "QUEUED"

            result = await conn.execute(
                """
                UPDATE product_import_jobs
                SET status = %s,
                    error_summary = '{}'::jsonb,
                    finished_at = NULL,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE company_id = %s
                  AND id = %s
                  AND status = 'FAILED'
                """,
                [
                    resume_status,
                    int(company_id),
                    job_id,
                ],
            )
            if result.rowcount != 1:
                raise ValueError(
                    "Import retry changed concurrently."
                )

            await _defer(
                conn,
                company_id=int(company_id),
                job_id=job_id,
            )
            return resume_status
