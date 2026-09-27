"""Thin Product Import application orchestrator.

Phase 2 keeps the current execution semantics and delegates specialized work to
the state machine, staging, validation and execution services.
"""
from __future__ import annotations

import hashlib
from uuid import UUID

from domains.simple_products.imports.application.execution_service import (
    execute_import,
)
from domains.simple_products.imports.application.source_store import (
    SourceStore,
)
from domains.simple_products.imports.application.staging_service import (
    stage_source,
)
from domains.simple_products.imports.application.state_machine import (
    JobStatus,
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
    open_source,
)
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    load_job,
    mark_job_source_cleared,
    open_tenant_session,
)


async def _load_job_context(
    *,
    company_id: int,
    job_id: UUID,
) -> tuple[
    bytes | None,
    UUID | None,
    int,
    str,
    bool,
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
            (
                UUID(
                    str(
                        job.source_id
                    )
                )
                if job.source_id
                is not None
                else None
            ),
            int(
                job.file_size
            ),
            str(
                job.source_sha256
            ),
            (
                job.source_payload_cleared_at
                is not None
            ),
            str(
                job.file_name
            ),
            str(
                job.status
            ),
        )
    finally:
        await close_tenant_session(
            token,
            db,
        )


async def _mark_source_cleaned(
    *,
    company_id: int,
    job_id: UUID,
) -> None:
    token, db = await open_tenant_session(
        company_id
    )
    try:
        await mark_job_source_cleared(
            db,
            company_id=company_id,
            job_id=job_id,
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


async def _cleanup_staged_source(
    *,
    source_store: SourceStore,
    company_id: int,
    job_id: UUID,
    source_id: UUID | None,
    already_cleared: bool,
) -> None:
    if (
        source_id is None
        or already_cleared
    ):
        return

    await source_store.delete_source_bytes(
        company_id=company_id,
        source_id=source_id,
    )
    await _mark_source_cleaned(
        company_id=company_id,
        job_id=job_id,
    )


def _verify_legacy_payload(
    payload: bytes,
    *,
    expected_size: int,
    expected_sha256: str,
) -> None:
    if (
        len(
            payload
        )
        != int(
            expected_size
        )
        or hashlib.sha256(
            payload
        ).hexdigest()
        != str(
            expected_sha256
        ).lower()
    ):
        raise ProductImportTerminalError(
            "Legacy Product Import source hash verification failed."
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
        has_source = (
            job.source_payload
            is not None
            or (
                job.source_id
                is not None
                and job.source_payload_cleared_at
                is None
            )
        )
        return (
            str(
                job.status
            ),
            bool(
                has_source
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
    source_store: SourceStore,
) -> None:
    (
        legacy_payload,
        source_id,
        source_size,
        source_sha256,
        source_cleared,
        file_name,
        status,
    ) = await _load_job_context(
        company_id=company_id,
        job_id=job_id,
    )

    if status in {
        JobStatus.COMPLETED.value,
        JobStatus.COMPLETED_WITH_ERRORS.value,
        JobStatus.VALIDATION_FAILED.value,
        JobStatus.FAILED.value,
        JobStatus.NEEDS_MAPPING.value,
    }:
        return

    if status in {
        JobStatus.QUEUED.value,
        JobStatus.PARSING.value,
    }:
        if source_id is not None:
            payload = (
                await source_store.read_verified_bytes(
                    company_id=
                        company_id,
                    source_id=
                        source_id,
                    expected_size=
                        source_size,
                    expected_sha256=
                        source_sha256,
                )
            )
        elif legacy_payload is not None:
            _verify_legacy_payload(
                legacy_payload,
                expected_size=
                    source_size,
                expected_sha256=
                    source_sha256,
            )
            payload = legacy_payload
        else:
            raise ProductImportTerminalError(
                "Import state is inconsistent and has no retained source."
            )

        await set_job_status(
            company_id=company_id,
            job_id=job_id,
            target=JobStatus.PARSING,
            started_at=
                utc_naive_now(),
            error_summary={},
        )
        with open_source(
            file_name,
            payload,
        ) as source:
            suggestions = suggest_mapping(
                source.headers
            )
            await stage_source(
                company_id=company_id,
                job_id=job_id,
                headers=source.headers,
                rows=source.rows,
                suggestions=suggestions,
            )

        await _cleanup_staged_source(
            source_store=
                source_store,
            company_id=
                company_id,
            job_id=
                job_id,
            source_id=
                source_id,
            already_cleared=
                source_cleared,
        )
        source_cleared = True

    (
        status,
        has_source,
    ) = await _load_runtime_state(
        company_id=company_id,
        job_id=job_id,
    )

    if (
        source_id is not None
        and not source_cleared
        and status
        not in {
            JobStatus.QUEUED.value,
            JobStatus.PARSING.value,
            JobStatus.FAILED.value,
        }
    ):
        await _cleanup_staged_source(
            source_store=
                source_store,
            company_id=
                company_id,
            job_id=
                job_id,
            source_id=
                source_id,
            already_cleared=False,
        )
        source_cleared = True
        has_source = False

    if status == JobStatus.NEEDS_MAPPING.value:
        return

    if (
        status
        in {JobStatus.QUEUED.value, JobStatus.PARSING.value}
        and not has_source
    ):
        raise ProductImportTerminalError(
            "Import state is inconsistent and cannot be resumed safely."
        )

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
