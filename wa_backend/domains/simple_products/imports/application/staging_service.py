"""Product Import source staging orchestration."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from domains.simple_products.imports.application.state_machine import (
    transition_job,
)
from domains.simple_products.imports.domain import (
    ProductImportTerminalError,
)
from domains.simple_products.imports.domain.mapping import (
    mapping_complete,
)
from domains.simple_products.imports.infrastructure.parsers import (
    MAX_IMPORT_ROWS,
)
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    delete_job_rows,
    insert_staged_rows,
    load_job,
    open_tenant_session,
)


STAGE_BATCH = 1_000


async def stage_source(
    *,
    company_id: int,
    job_id: UUID,
    headers: list[str],
    rows: list[dict[str, Any]],
    suggestions: dict[str, str],
) -> None:
    if len(rows) > MAX_IMPORT_ROWS:
        raise ProductImportTerminalError(
            f"The import exceeds the {MAX_IMPORT_ROWS:,}-row safety limit."
        )

    token, db = await open_tenant_session(
        company_id
    )
    try:
        await delete_job_rows(
            db,
            company_id=company_id,
            job_id=job_id,
        )
        await insert_staged_rows(
            db,
            company_id=company_id,
            job_id=job_id,
            rows=rows,
            batch_size=STAGE_BATCH,
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

        mapping = dict(
            job.column_mapping
            or suggestions
            or {}
        )
        target = (
            "VALIDATING"
            if mapping_complete(mapping)
            else "NEEDS_MAPPING"
        )

        transition_job(
            job,
            target,
            detected_headers=headers,
            suggested_mapping=suggestions,
            column_mapping=mapping,
            total_rows=len(rows),
            processed_rows=0,
            valid_rows=0,
            failed_rows=0,
            source_payload=None,
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
