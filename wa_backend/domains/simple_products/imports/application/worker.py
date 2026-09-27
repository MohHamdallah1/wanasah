"""Thin Product Import application orchestrator."""
from __future__ import annotations

from uuid import UUID

from domains.simple_products.imports.application.execution_service import (
    execute_import,
)
from domains.simple_products.imports.application.source_service import (
    prepare_import_source,
)
from domains.simple_products.imports.application.source_store import (
    SourceStore,
)
from domains.simple_products.imports.application.state_machine import (
    JobStatus,
)
from domains.simple_products.imports.application.validation_service import (
    validate_rows,
)
from domains.simple_products.imports.domain import (
    ProductImportTerminalError,
)


async def run_product_import_job(
    *,
    company_id: int,
    job_id: UUID,
    source_store: SourceStore,
) -> None:
    status = await prepare_import_source(
        company_id=company_id,
        job_id=job_id,
        source_store=source_store,
    )

    if status in {
        JobStatus.COMPLETED.value,
        JobStatus.COMPLETED_WITH_ERRORS.value,
        JobStatus.VALIDATION_FAILED.value,
        JobStatus.FAILED.value,
        JobStatus.NEEDS_MAPPING.value,
    }:
        return

    if status == JobStatus.VALIDATING.value:
        if not await validate_rows(
            company_id=company_id,
            job_id=job_id,
        ):
            return
        status = JobStatus.IMPORTING.value

    if status == JobStatus.IMPORTING.value:
        await execute_import(
            company_id=company_id,
            job_id=job_id,
        )
        return

    raise ProductImportTerminalError(
        f"Unsupported import state: {status}"
    )
