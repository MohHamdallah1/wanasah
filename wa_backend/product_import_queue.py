"""PostgreSQL-backed queue for asynchronous product imports."""
from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
from procrastinate import App, PsycopgConnector, RetryStrategy
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url

from config import Config


def _psycopg_dsn() -> str:
    url = make_url(Config.SQLALCHEMY_DATABASE_URI)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("Product import worker requires PostgreSQL.")
    return url.set(drivername="postgresql").render_as_string(
        hide_password=False
    )


DSN = _psycopg_dsn()
app = App(connector=PsycopgConnector(conninfo=DSN))


@app.task(
    name="wanasah.process_product_import",
    queue="product-import",
    retry=RetryStrategy(max_attempts=4, wait=3, exponential_wait=2),
    pass_context=True,
)
async def process_product_import(context, company_id: int, job_id: str) -> None:
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
) -> UUID:
    job_id = uuid4()
    async with await psycopg.AsyncConnection.connect(DSN) as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_tenant', %s, true)",
                [str(int(company_id))],
            )
            existing = await conn.execute(
                """
                SELECT id
                FROM product_import_jobs
                WHERE company_id=%s AND request_id=%s
                """,
                [int(company_id), request_id],
            )
            row = await existing.fetchone()
            if row is not None:
                return UUID(str(row[0]))

            await conn.execute(
                """
                INSERT INTO product_import_jobs (
                    id, company_id, request_id, created_by,
                    file_name, content_type, source_payload,
                    source_sha256, file_size, status,
                    detected_headers, suggested_mapping, column_mapping,
                    error_summary, total_rows, processed_rows, valid_rows,
                    failed_rows, version
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,'QUEUED',
                    '[]'::jsonb,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,
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
                ],
            )
            await _defer(
                conn,
                company_id=int(company_id),
                job_id=job_id,
            )
    return job_id


async def requeue_import(
    *,
    company_id: int,
    job_id: UUID,
    mapping: dict[str, str],
) -> None:
    async with await psycopg.AsyncConnection.connect(DSN) as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_tenant', %s, true)",
                [str(int(company_id))],
            )
            result = await conn.execute(
                """
                UPDATE product_import_jobs
                SET column_mapping=%s,
                    status='VALIDATING',
                    error_summary='{}'::jsonb,
                    version=version+1,
                    updated_at=CURRENT_TIMESTAMP
                WHERE company_id=%s
                  AND id=%s
                  AND status='NEEDS_MAPPING'
                """,
                [Jsonb(mapping), int(company_id), job_id],
            )
            if result.rowcount != 1:
                raise ValueError(
                    "Import job is not waiting for column mapping."
                )
            await _defer(
                conn,
                company_id=int(company_id),
                job_id=job_id,
            )


async def retry_failed_import(
    *,
    company_id: int,
    job_id: UUID,
) -> None:
    async with await psycopg.AsyncConnection.connect(DSN) as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_tenant', %s, true)",
                [str(int(company_id))],
            )
            cursor = await conn.execute(
                """
                SELECT error_summary
                FROM product_import_jobs
                WHERE company_id=%s
                  AND id=%s
                  AND status='FAILED'
                FOR UPDATE
                """,
                [int(company_id), job_id],
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError("Import job is not retryable.")
            summary = dict(row[0] or {})
            if summary.get("retryable") is not True:
                raise ValueError("Import job failed with a non-retryable error.")
            resume_status = str(summary.get("resume_status") or "QUEUED")
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
                SET status=%s,
                    error_summary='{}'::jsonb,
                    finished_at=NULL,
                    version=version+1,
                    updated_at=CURRENT_TIMESTAMP
                WHERE company_id=%s
                  AND id=%s
                  AND status='FAILED'
                """,
                [resume_status, int(company_id), job_id],
            )
            if result.rowcount != 1:
                raise ValueError("Import job is not retryable.")
            await _defer(
                conn,
                company_id=int(company_id),
                job_id=job_id,
            )
