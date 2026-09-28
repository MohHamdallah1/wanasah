"""Product Import source staging orchestration."""
from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from domains.simple_products.imports.application.state_machine import (
    JobStatus,
    transition_job,
)
from domains.simple_products.imports.domain.mapping import (
    mapping_complete,
)
from domains.simple_products.imports.domain import (
    ProductImportTerminalError,
)
from domains.simple_products.imports.infrastructure.parsers import (
    MAX_IMPORT_ROWS,
    ParsedRow,
)
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    delete_job_rows,
    insert_staged_rows,
    count_job_rows,
    load_job,
    open_tenant_session,
)


# The Windows SelectorEventLoop/asyncpg ORM bulk-insert path can silently
# persist only 937/1000 rows in a single 1000-row execute. A bounded
# 500-row batch is verified lossless on that runtime up to 50,000 rows.
# Keep the in-transaction count check below regardless of batch size.
STAGE_BATCH = 500


async def stage_source(
    *,
    company_id: int,
    job_id: UUID,
    headers: list[str],
    rows: Iterable[ParsedRow],
    suggestions: dict[str, str],
) -> None:
    token, db = await open_tenant_session(
        company_id
    )
    try:
        await delete_job_rows(
            db,
            company_id=company_id,
            job_id=job_id,
        )
        total_rows = await insert_staged_rows(
            db,
            company_id=company_id,
            job_id=job_id,
            rows=rows,
            batch_size=STAGE_BATCH,
            max_rows=MAX_IMPORT_ROWS,
        )

        # Never advance to VALIDATING or release the immutable SourceStore
        # unless every non-empty source row is durably staged. This catches
        # silent short-writes before commit, preserving safe rollback/retry.
        persisted_rows = await count_job_rows(
            db,
            company_id=company_id,
            job_id=job_id,
            status="STAGED",
        )
        if persisted_rows != total_rows:
            raise ProductImportTerminalError(
                "Staging row-count mismatch: parsed "
                f"{total_rows} rows but persisted "
                f"{persisted_rows}; source was not released."
            )

        job = await load_job(
            db,
            company_id=company_id,
            job_id=job_id,
            for_update=True,
        )
        if job is None:
            raise ValueError(
                "Product import job not found."
            )
        if (
            str(job.status)
            == JobStatus.CANCELLED.value
        ):
            # Cancellation may commit while source rows are being parsed.
            # Roll back this whole staging transaction rather than preserving
            # a partially staged source.
            await db.rollback()
            return

        mapping = dict(
            job.column_mapping
            or suggestions
            or {}
        )
        target = (
            JobStatus.VALIDATING
            if mapping_complete(mapping)
            else JobStatus.NEEDS_MAPPING
        )

        transition_job(
            job,
            target,
            detected_headers=headers,
            suggested_mapping=suggestions,
            column_mapping=mapping,
            total_rows=total_rows,
            processed_rows=0,
            valid_rows=0,
            failed_rows=0,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await close_tenant_session(
            token,
            db,
        )
