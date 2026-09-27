"""Safe Product Import cancellation at durable transaction boundaries."""
from __future__ import annotations

from uuid import UUID

from domains.simple_products.imports.application.state_machine import (
    JobStatus,
    transition_job,
    utc_naive_now,
)
from domains.simple_products.imports.domain import (
    ProductImportTerminalError,
)
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    load_job,
    open_tenant_session,
)


_CANCELLABLE_STATUSES = frozenset({
    JobStatus.QUEUED.value,
    JobStatus.PARSING.value,
    JobStatus.NEEDS_MAPPING.value,
    JobStatus.VALIDATING.value,
    JobStatus.IMPORTING.value,
    JobStatus.RETRYING.value,
})


async def cancel_import_job(
    *,
    company_id: int,
    job_id: UUID,
) -> str:
    """Transition one active job to CANCELLED under its row lock.

    Validation/execution hold the same job row lock for each bounded
    transaction. A cancellation request therefore waits for the current batch
    to commit or roll back and becomes visible before the next batch starts.
    Already committed rows remain valid; no in-flight Product/Pricing
    transaction is interrupted.
    """
    token, db = await open_tenant_session(
        company_id
    )
    try:
        job = await load_job(
            db,
            company_id=company_id,
            job_id=job_id,
            for_update=True,
        )
        if job is None:
            raise ProductImportTerminalError(
                "Product import job was not found."
            )

        current = str(
            job.status
        )
        if current == JobStatus.CANCELLED.value:
            await db.rollback()
            return current
        if current not in _CANCELLABLE_STATUSES:
            raise ProductImportTerminalError(
                "Product import job is no longer cancellable."
            )

        transition_job(
            job,
            JobStatus.CANCELLED,
            finished_at=utc_naive_now(),
            error_summary={
                "code": "PRODUCT_IMPORT_CANCELLED",
            },
        )
        await db.commit()
        return JobStatus.CANCELLED.value
    except Exception:
        await db.rollback()
        raise
    finally:
        await close_tenant_session(
            token,
            db,
        )
