"""Product Import immutable source lifecycle orchestration."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from uuid import UUID

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


_SOURCE_FREE_EARLY_EXIT = frozenset({
    JobStatus.COMPLETED.value,
    JobStatus.COMPLETED_WITH_ERRORS.value,
    JobStatus.VALIDATION_FAILED.value,
    JobStatus.FAILED.value,
    JobStatus.NEEDS_MAPPING.value,
})


@dataclass(frozen=True, slots=True)
class ProductImportSourceContext:
    legacy_payload: bytes | None
    source_id: UUID | None
    source_size: int
    source_sha256: str
    source_cleared: bool
    file_name: str
    status: str


async def _load_source_context(
    *,
    company_id: int,
    job_id: UUID,
) -> ProductImportSourceContext:
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

        return ProductImportSourceContext(
            legacy_payload=(
                bytes(
                    job.source_payload
                )
                if job.source_payload
                is not None
                else None
            ),
            source_id=(
                UUID(
                    str(
                        job.source_id
                    )
                )
                if job.source_id
                is not None
                else None
            ),
            source_size=int(
                job.file_size
            ),
            source_sha256=str(
                job.source_sha256
            ),
            source_cleared=(
                job.source_payload_cleared_at
                is not None
            ),
            file_name=str(
                job.file_name
            ),
            status=str(
                job.status
            ),
        )
    finally:
        await close_tenant_session(
            token,
            db,
        )


async def _runtime_state(
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


async def _read_verified_source(
    *,
    source_store: SourceStore,
    company_id: int,
    context: ProductImportSourceContext,
) -> bytes:
    if context.source_id is not None:
        return await source_store.read_verified_bytes(
            company_id=
                company_id,
            source_id=
                context.source_id,
            expected_size=
                context.source_size,
            expected_sha256=
                context.source_sha256,
        )

    if context.legacy_payload is not None:
        _verify_legacy_payload(
            context.legacy_payload,
            expected_size=
                context.source_size,
            expected_sha256=
                context.source_sha256,
        )
        return context.legacy_payload

    raise ProductImportTerminalError(
        "Import state is inconsistent and has no retained source."
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


async def _cleanup_source(
    *,
    source_store: SourceStore,
    company_id: int,
    job_id: UUID,
    source_id: UUID | None,
    already_cleared: bool,
) -> bool:
    if (
        source_id is None
        or already_cleared
    ):
        return bool(
            already_cleared
        )

    await source_store.delete_source_bytes(
        company_id=company_id,
        source_id=source_id,
    )
    await _mark_source_cleaned(
        company_id=company_id,
        job_id=job_id,
    )
    return True


async def prepare_import_source(
    *,
    company_id: int,
    job_id: UUID,
    source_store: SourceStore,
) -> str:
    """Verify/stage/cleanup source bytes and return the durable next job state."""
    context = await _load_source_context(
        company_id=company_id,
        job_id=job_id,
    )
    if (
        context.status
        == JobStatus.CANCELLED.value
    ):
        await _cleanup_source(
            source_store=source_store,
            company_id=company_id,
            job_id=job_id,
            source_id=context.source_id,
            already_cleared=
                context.source_cleared,
        )
        return JobStatus.CANCELLED.value

    if context.status in _SOURCE_FREE_EARLY_EXIT:
        return context.status

    source_cleared = (
        context.source_cleared
    )
    if context.status in {
        JobStatus.QUEUED.value,
        JobStatus.PARSING.value,
    }:
        payload = await _read_verified_source(
            source_store=
                source_store,
            company_id=
                company_id,
            context=context,
        )

        parsing_status = await set_job_status(
            company_id=company_id,
            job_id=job_id,
            target=JobStatus.PARSING,
            started_at=
                utc_naive_now(),
            error_summary={},
        )
        if (
            parsing_status
            == JobStatus.CANCELLED.value
        ):
            await _cleanup_source(
                source_store=source_store,
                company_id=company_id,
                job_id=job_id,
                source_id=context.source_id,
                already_cleared=
                    context.source_cleared,
            )
            return JobStatus.CANCELLED.value

        with open_source(
            context.file_name,
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

        source_cleared = await _cleanup_source(
            source_store=
                source_store,
            company_id=
                company_id,
            job_id=
                job_id,
            source_id=
                context.source_id,
            already_cleared=
                source_cleared,
        )

    (
        status,
        has_source,
    ) = await _runtime_state(
        company_id=company_id,
        job_id=job_id,
    )

    if (
        context.source_id is not None
        and not source_cleared
        and status
        not in {
            JobStatus.QUEUED.value,
            JobStatus.PARSING.value,
            JobStatus.FAILED.value,
        }
    ):
        await _cleanup_source(
            source_store=
                source_store,
            company_id=
                company_id,
            job_id=
                job_id,
            source_id=
                context.source_id,
            already_cleared=False,
        )
        has_source = False

    if (
        status
        in {
            JobStatus.QUEUED.value,
            JobStatus.PARSING.value,
        }
        and not has_source
    ):
        raise ProductImportTerminalError(
            "Import state is inconsistent and cannot be resumed safely."
        )

    return status
