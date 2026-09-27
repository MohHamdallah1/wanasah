"""Thin Product Import application orchestrator.

Phase 2 keeps the current execution semantics and delegates specialized work to
the state machine, staging, validation and execution services.
"""
from __future__ import annotations

import asyncio
from uuid import UUID

from domains.simple_products.imports.application.execution_service import (
    execute_import,
)
from domains.simple_products.imports.application.staging_service import (
    stage_source,
)
from domains.simple_products.imports.application.state_machine import (
    set_job_status,
    utc_naive_now,
)
from domains.simple_products.imports.application.validation_service import (
    validate_rows,
)
from domains.simple_products.imports.domain import (
    ProductImportTerminalError,
)
from domains.simple_products.imports.domain.mapping import (
    suggest_mapping,
)
from domains.simple_products.imports.infrastructure.parsers import (
    parse_source,
)
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    load_job,
    open_tenant_session,
)


async def _load_job_context(
    *,
    company_id: int,
    job_id: UUID,
) -> tuple[
    bytes | None,
    str,
    str,
]:
    token, db = await open_tenant_session(
        company_id
    )
    try:
        job = await load_job(
            db,
            company_id=company_id,
            job_id=job_id,
        )
        if job is None:
            raise ValueError(
                "Product import job not found."
            )
        return (
            (
                bytes(
                    job.source_payload
                )
                if job.source_payload
                is not None
                else None
            ),
            str(job.file_name),
            str(job.status),
        )
    finally:
        await close_tenant_session(
            token,
            db,
        )


async def _load_runtime_state(
    *,
    company_id: int,
    job_id: UUID,
) -> tuple[str, bool]:
    token, db = await open_tenant_session(
        company_id
    )
    try:
        job = await load_job(
            db,
            company_id=company_id,
            job_id=job_id,
        )
        if job is None:
            raise ProductImportTerminalError(
                "Product import job not found."
            )
        return (
            str(job.status),
            (
                job.source_payload
                is not None
            ),
        )
    finally:
        await close_tenant_session(
            token,
            db,
        )


async def run_product_import_job(
    *,
    company_id: int,
    job_id: UUID,
) -> None:
    (
        payload,
        file_name,
        status,
    ) = await _load_job_context(
        company_id=company_id,
        job_id=job_id,
    )

    if status in {
        "COMPLETED",
        "VALIDATION_FAILED",
        "FAILED",
        "NEEDS_MAPPING",
    }:
        return

    if payload is not None:
        await set_job_status(
            company_id=company_id,
            job_id=job_id,
            target="PARSING",
            started_at=
                utc_naive_now(),
            error_summary={},
        )
        (
            headers,
            rows,
        ) = await asyncio.to_thread(
            parse_source,
            file_name,
            payload,
        )
        suggestions = suggest_mapping(
            headers
        )
        await stage_source(
            company_id=company_id,
            job_id=job_id,
            headers=headers,
            rows=rows,
            suggestions=suggestions,
        )

    (
        status,
        has_source,
    ) = await _load_runtime_state(
        company_id=company_id,
        job_id=job_id,
    )

    if status == "NEEDS_MAPPING":
        return

    if (
        status
        in {"QUEUED", "PARSING"}
        and not has_source
    ):
        raise ProductImportTerminalError(
            "Import state is inconsistent and cannot be resumed safely."
        )

    if status == "VALIDATING":
        if not await validate_rows(
            company_id=company_id,
            job_id=job_id,
        ):
            return
        status = "IMPORTING"

    if status == "IMPORTING":
        await execute_import(
            company_id=company_id,
            job_id=job_id,
        )
        return

    raise ProductImportTerminalError(
        f"Unsupported import state: {status}"
    )
