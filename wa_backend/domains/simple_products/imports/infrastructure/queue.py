"""PostgreSQL-backed queue for asynchronous product imports."""
from __future__ import annotations

import logging
from typing import Any, BinaryIO
from uuid import UUID, uuid4

import psycopg
from procrastinate import App, PsycopgConnector, RetryStrategy
from psycopg.types.json import Jsonb
from domains.simple_products.imports.application.state_machine import (
    JobStatus,
    assert_job_transition,
)
from domains.simple_products.imports.domain.admission import (
    DEFAULT_PRODUCT_IMPORT_ADMISSION_POLICY,
    ProductImportAdmissionDenied,
)
from domains.simple_products.imports.infrastructure.admission_repository import (
    check_import_admission_before_persist,
    record_admission_rejection,
    reserve_source_capacity_after_persist,
)
from domains.simple_products.imports.infrastructure.postgres_source_store import (
    POSTGRES_PRODUCT_IMPORT_SOURCE_STORE,
)
from domains.simple_products.imports.infrastructure.runtime_monitor import (
    register_product_import_worker,
)
from domains.product_tracking import normalize_tracking_mode
from workers.recovery import recover_safe_stalled_jobs


from domains.simple_products.imports.infrastructure.queue_dsn import (
    product_import_psycopg_dsn,
)


DSN = product_import_psycopg_dsn()
logger = logging.getLogger(
    "wanasah_logger"
)
PRODUCT_IMPORT_HEARTBEAT_SECONDS = 10.0
PRODUCT_IMPORT_STALLED_TIMEOUT_SECONDS = 30.0
PRODUCT_IMPORT_STALLED_ALLOWLIST = frozenset(
    {
        "wanasah.process_product_import",
        "wanasah.recover_stalled_product_imports",
        "wanasah.cleanup_product_import_retention",
        "wanasah.schedule_product_import_retention",
        "wanasah.monitor_product_import_capacity",
        "wanasah.schedule_product_import_capacity_monitor",
        "wanasah.product_import_worker_heartbeat",
    }
)

app = App(
    connector=PsycopgConnector(
        conninfo=DSN,
        # Product-import queue rows intentionally share the public-schema
        # transaction that creates/updates product_import_jobs.
        kwargs={"options": "-c search_path=public"},
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


@app.periodic(
    cron="* * * * *"
)
@app.task(
    name="wanasah.product_import_worker_heartbeat",
    queue="product-import",
    pass_context=True,
)
async def product_import_worker_heartbeat(
    context,
    timestamp: int | None = None,
) -> dict[str, int]:
    worker_id = getattr(
        context.job,
        "worker_id",
        None,
    )
    if worker_id is None:
        return {
            "registered": 0,
        }

    await register_product_import_worker(
        int(
            worker_id
        )
    )
    return {
        "registered": 1,
        "worker_id":
            int(
                worker_id
            ),
    }


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
    from domains.simple_products.imports.application import (
        mark_import_runtime_failure,
        run_product_import_job,
    )
    from domains.simple_products.imports.domain.errors import (
        classify_import_error,
    )

    job_uuid = UUID(str(job_id))
    worker_id = getattr(
        context.job,
        "worker_id",
        None,
    )
    if worker_id is not None:
        await register_product_import_worker(
            int(
                worker_id
            )
        )

    try:
        await run_product_import_job(
            company_id=int(company_id),
            job_id=job_uuid,
            source_store=
                POSTGRES_PRODUCT_IMPORT_SOURCE_STORE,
        )
    except Exception as exc:
        classification = (
            classify_import_error(
                exc
            )
        )
        correlation_id = (
            "product-import:"
            + str(
                job_uuid
            )
        )
        logger.exception(
            "PRODUCT_IMPORT_WORKER_FAILURE "
            "correlation_id=%s company_id=%s job_id=%s kind=%s code=%s",
            correlation_id,
            int(
                company_id
            ),
            str(
                job_uuid
            ),
            classification.kind.value,
            classification.code,
        )

        if not classification.retryable:
            await mark_import_runtime_failure(
                company_id=int(company_id),
                job_id=job_uuid,
                final_attempt=True,
                retryable=False,
                code=
                    classification.code,
                correlation_id=
                    correlation_id,
            )
            return

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
            final_attempt=final_attempt,
            retryable=final_attempt,
            code=(
                classification.code
                if final_attempt
                else None
            ),
            correlation_id=
                correlation_id,
        )
        raise


async def defer_import_on_connection(
    conn: psycopg.AsyncConnection,
    *,
    company_id: int,
    job_id: UUID,
) -> None:
    # Deliberately retain company serialization. Product Import executes through
    # create_products_and_prices, which owns a shared company-default
    # PriceBook/assignment and publishes against its version. Parallel imports
    # inside one company can race that Pricing aggregate. Cross-company imports
    # remain concurrent because this lock is tenant-scoped.
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
    source_stream: BinaryIO,
    source_size: int,
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

    try:
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
                        == int(source_size)
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

                await check_import_admission_before_persist(
                    conn,
                    company_id=int(
                        company_id
                    ),
                    actor_id=int(
                        actor_id
                    ),
                    incoming_bytes=int(
                        source_size
                    ),
                    policy=
                        DEFAULT_PRODUCT_IMPORT_ADMISSION_POLICY,
                )

                source_ref = (
                    await POSTGRES_PRODUCT_IMPORT_SOURCE_STORE.persist_stream_on_connection(
                        connection=conn,
                        company_id=int(
                            company_id
                        ),
                        stream=source_stream,
                        byte_size=int(
                            source_size
                        ),
                        sha256=
                            source_sha256,
                    )
                )
                await reserve_source_capacity_after_persist(
                    conn,
                    company_id=int(
                        company_id
                    ),
                    incoming_bytes=int(
                        source_size
                    ),
                    policy=
                        DEFAULT_PRODUCT_IMPORT_ADMISSION_POLICY,
                )

                await conn.execute(
                    """
                    INSERT INTO product_import_jobs (
                        id,
                        company_id,
                        request_id,
                        created_by,
                        file_name,
                        content_type,
                        source_id,
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
                        %s,%s,%s,%s,%s,%s,%s,NULL,%s,%s,
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
                        source_ref.source_id,
                        source_sha256,
                        int(
                            source_size
                        ),
                        default_lot_control_mode,
                        default_expiry_control_mode,
                    ],
                )
                await defer_import_on_connection(
                    conn,
                    company_id=int(company_id),
                    job_id=job_id,
                )

    except ProductImportAdmissionDenied as exc:
        await record_admission_rejection(
            company_id=int(
                company_id
            ),
            actor_id=int(
                actor_id
            ),
            denial=exc,
        )
        raise

    return {
        "job_id": job_id,
        "status": JobStatus.QUEUED.value,
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

            if status == JobStatus.NEEDS_MAPPING.value:
                assert_job_transition(
                    status,
                    JobStatus.VALIDATING,
                )
                result = await conn.execute(
                    """
                    UPDATE product_import_jobs
                    SET column_mapping = %s,
                        status = %s,
                        error_summary = '{}'::jsonb,
                        version = version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE company_id = %s
                      AND id = %s
                      AND status = %s
                    """,
                    [
                        Jsonb(mapping),
                        JobStatus.VALIDATING.value,
                        int(company_id),
                        job_id,
                        JobStatus.NEEDS_MAPPING.value,
                    ],
                )
                if result.rowcount != 1:
                    raise ValueError(
                        "Import mapping changed concurrently."
                    )
                await defer_import_on_connection(
                    conn,
                    company_id=int(company_id),
                    job_id=job_id,
                )
                return JobStatus.VALIDATING.value

            replayable_states = {
                JobStatus.QUEUED.value,
                JobStatus.PARSING.value,
                JobStatus.VALIDATING.value,
                JobStatus.IMPORTING.value,
                JobStatus.RETRYING.value,
                JobStatus.VALIDATION_FAILED.value,
                JobStatus.COMPLETED.value,
                JobStatus.COMPLETED_WITH_ERRORS.value,
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

            if status != JobStatus.FAILED.value:
                if status in {
                    JobStatus.QUEUED.value,
                    JobStatus.PARSING.value,
                    JobStatus.VALIDATING.value,
                    JobStatus.IMPORTING.value,
                    JobStatus.RETRYING.value,
                    JobStatus.COMPLETED.value,
                    JobStatus.COMPLETED_WITH_ERRORS.value,
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
                or JobStatus.QUEUED.value
            )
            if resume_status not in {
                JobStatus.QUEUED.value,
                JobStatus.PARSING.value,
                JobStatus.VALIDATING.value,
                JobStatus.IMPORTING.value,
            }:
                resume_status = JobStatus.QUEUED.value

            assert_job_transition(
                status,
                resume_status,
            )

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
                  AND status = %s
                """,
                [
                    resume_status,
                    int(company_id),
                    job_id,
                    JobStatus.FAILED.value,
                ],
            )
            if result.rowcount != 1:
                raise ValueError(
                    "Import retry changed concurrently."
                )

            await defer_import_on_connection(
                conn,
                company_id=int(company_id),
                job_id=job_id,
            )
            return resume_status

# Import after the queue app/tasks exist so retention jobs share the same
# product-import worker without folding retention orchestration into this module.
from domains.simple_products.imports.infrastructure import retention_queue as _retention_queue  # noqa: E402,F401
from domains.simple_products.imports.infrastructure import capacity_queue as _capacity_queue  # noqa: E402,F401
