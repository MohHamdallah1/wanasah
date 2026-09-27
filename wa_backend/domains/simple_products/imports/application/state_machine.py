"""Canonical Product Import state-transition authority.

Phase 3 centralized the vocabulary and legal transitions. Phase 7 activates
COMPLETED_WITH_ERRORS and IMPORT_FAILED for best-effort outcomes while this
module remains the fail-closed transition authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from domains.simple_products.imports.domain.errors import (
    ProductImportTerminalError,
    runtime_failure_summary,
)
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    load_job,
    open_tenant_session,
)


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    PARSING = "PARSING"
    NEEDS_MAPPING = "NEEDS_MAPPING"
    VALIDATING = "VALIDATING"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    IMPORTING = "IMPORTING"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    FAILED = "FAILED"


class RowStatus(str, Enum):
    STAGED = "STAGED"
    VALID = "VALID"
    INVALID = "INVALID"
    IMPORT_FAILED = "IMPORT_FAILED"
    IMPORTED = "IMPORTED"


JOB_STATUSES = frozenset(
    status.value
    for status in JobStatus
)
ROW_STATUSES = frozenset(
    status.value
    for status in RowStatus
)


ALLOWED_JOB_TRANSITIONS: dict[
    JobStatus,
    frozenset[JobStatus],
] = {
    JobStatus.QUEUED: frozenset({
        JobStatus.PARSING,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }),
    JobStatus.PARSING: frozenset({
        JobStatus.PARSING,
        JobStatus.NEEDS_MAPPING,
        JobStatus.VALIDATING,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }),
    JobStatus.NEEDS_MAPPING: frozenset({
        JobStatus.VALIDATING,
        JobStatus.CANCELLED,
    }),
    JobStatus.VALIDATING: frozenset({
        JobStatus.NEEDS_MAPPING,
        JobStatus.VALIDATION_FAILED,
        JobStatus.IMPORTING,
        JobStatus.COMPLETED_WITH_ERRORS,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }),
    JobStatus.VALIDATION_FAILED:
        frozenset({
            JobStatus.VALIDATING,
        }),
    JobStatus.IMPORTING: frozenset({
        JobStatus.IMPORTING,
        JobStatus.COMPLETED,
        JobStatus.COMPLETED_WITH_ERRORS,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }),
    JobStatus.RETRYING: frozenset({
        JobStatus.QUEUED,
        JobStatus.PARSING,
        JobStatus.VALIDATING,
        JobStatus.IMPORTING,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }),
    JobStatus.CANCELLED: frozenset(),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.COMPLETED_WITH_ERRORS:
        frozenset({
            JobStatus.VALIDATING,
        }),
    JobStatus.FAILED: frozenset({
        JobStatus.QUEUED,
        JobStatus.PARSING,
        JobStatus.VALIDATING,
        JobStatus.IMPORTING,
    }),
}


ALLOWED_ROW_TRANSITIONS: dict[
    RowStatus,
    frozenset[RowStatus],
] = {
    RowStatus.STAGED: frozenset({
        RowStatus.VALID,
        RowStatus.INVALID,
    }),
    RowStatus.VALID: frozenset({
        RowStatus.IMPORTED,
        RowStatus.IMPORT_FAILED,
    }),
    RowStatus.INVALID: frozenset({
        RowStatus.STAGED,
    }),
    RowStatus.IMPORT_FAILED:
        frozenset({
            RowStatus.STAGED,
        }),
    RowStatus.IMPORTED: frozenset(),
}


class ProductImportStateTransitionError(
    ProductImportTerminalError
):
    """Illegal Product Import state transition."""


def _job_status(
    value: JobStatus | str,
) -> JobStatus:
    if isinstance(
        value,
        JobStatus,
    ):
        return value
    try:
        return JobStatus(
            str(value)
        )
    except ValueError as exc:
        raise ProductImportStateTransitionError(
            "Unknown Product Import job state: "
            f"{value!r}."
        ) from exc


def _row_status(
    value: RowStatus | str,
) -> RowStatus:
    if isinstance(
        value,
        RowStatus,
    ):
        return value
    try:
        return RowStatus(
            str(value)
        )
    except ValueError as exc:
        raise ProductImportStateTransitionError(
            "Unknown Product Import row state: "
            f"{value!r}."
        ) from exc


def assert_job_transition(
    current: JobStatus | str,
    target: JobStatus | str,
) -> None:
    current_status = _job_status(
        current
    )
    target_status = _job_status(
        target
    )
    if (
        target_status
        not in ALLOWED_JOB_TRANSITIONS[
            current_status
        ]
    ):
        raise ProductImportStateTransitionError(
            "Illegal Product Import job transition: "
            f"{current_status.value} -> "
            f"{target_status.value}."
        )


def assert_row_transition(
    current: RowStatus | str,
    target: RowStatus | str,
) -> None:
    current_status = _row_status(
        current
    )
    target_status = _row_status(
        target
    )
    if (
        target_status
        not in ALLOWED_ROW_TRANSITIONS[
            current_status
        ]
    ):
        raise ProductImportStateTransitionError(
            "Illegal Product Import row transition: "
            f"{current_status.value} -> "
            f"{target_status.value}."
        )


def utc_naive_now() -> datetime:
    return datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )


def touch_job(
    job: Any,
    *,
    touch_updated_at: bool = True,
    **values: Any,
) -> None:
    for key, value in values.items():
        setattr(
            job,
            key,
            value,
        )
    job.version += 1
    if touch_updated_at:
        job.updated_at = utc_naive_now()


def transition_job(
    job: Any,
    target: JobStatus | str,
    *,
    touch_updated_at: bool = True,
    **values: Any,
) -> None:
    target_status = _job_status(
        target
    )
    assert_job_transition(
        str(job.status),
        target_status,
    )
    job.status = target_status.value
    touch_job(
        job,
        touch_updated_at=touch_updated_at,
        **values,
    )


def transition_row(
    row: Any,
    target: RowStatus | str,
    **values: Any,
) -> None:
    target_status = _row_status(
        target
    )
    assert_row_transition(
        str(row.status),
        target_status,
    )
    row.status = target_status.value
    for key, value in values.items():
        setattr(
            row,
            key,
            value,
        )
    row.version += 1


async def set_job_status(
    *,
    company_id: int,
    job_id: UUID,
    target: JobStatus | str,
    **values: Any,
) -> str:
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
            raise ValueError(
                "Product import job not found."
            )

        if (
            str(job.status)
            == JobStatus.CANCELLED.value
            and _job_status(target)
            != JobStatus.CANCELLED
        ):
            await db.rollback()
            return JobStatus.CANCELLED.value

        transition_job(
            job,
            target,
            **values,
        )
        await db.commit()
        return str(job.status)
    except Exception:
        await db.rollback()
        raise
    finally:
        await close_tenant_session(
            token,
            db,
        )


async def record_runtime_failure(
    *,
    company_id: int,
    job_id: UUID,
    message: str,
    final_attempt: bool,
    retryable: bool,
) -> None:
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
            return

        current_status = str(
            job.status
        )
        if (
            current_status
            == JobStatus.CANCELLED.value
        ):
            await db.rollback()
            return

        summary = runtime_failure_summary(
            message=message,
            final_attempt=final_attempt,
            retryable=retryable,
            resume_status=current_status,
        )

        if final_attempt:
            transition_job(
                job,
                JobStatus.FAILED,
                error_summary=summary,
                finished_at=utc_naive_now(),
            )
        else:
            touch_job(
                job,
                error_summary=summary,
            )

        await db.commit()
    except Exception:
        await db.rollback()
    finally:
        await close_tenant_session(
            token,
            db,
        )
