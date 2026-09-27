"""Current Product Import state-transition authority.

Phase 2 preserves the existing execution policy. This module centralizes the
currently legal transitions and fails closed on any transition outside that
contract.
"""
from __future__ import annotations

from datetime import datetime, timezone
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


JOB_STATUSES = frozenset({
    "QUEUED",
    "PARSING",
    "NEEDS_MAPPING",
    "VALIDATING",
    "VALIDATION_FAILED",
    "IMPORTING",
    "RETRYING",
    "COMPLETED",
    "FAILED",
})

ROW_STATUSES = frozenset({
    "STAGED",
    "VALID",
    "FAILED",
    "IMPORTED",
})

_ALLOWED_JOB_TRANSITIONS = {
    "QUEUED": {
        "PARSING",
        "FAILED",
    },
    "PARSING": {
        "PARSING",
        "NEEDS_MAPPING",
        "VALIDATING",
        "FAILED",
    },
    "NEEDS_MAPPING": {
        "VALIDATING",
    },
    "VALIDATING": {
        "NEEDS_MAPPING",
        "VALIDATION_FAILED",
        "IMPORTING",
        "FAILED",
    },
    "VALIDATION_FAILED": set(),
    "IMPORTING": {
        "IMPORTING",
        "COMPLETED",
        "FAILED",
    },
    "RETRYING": {
        "QUEUED",
        "PARSING",
        "VALIDATING",
        "IMPORTING",
        "FAILED",
    },
    "COMPLETED": set(),
    "FAILED": {
        "QUEUED",
        "PARSING",
        "VALIDATING",
        "IMPORTING",
    },
}

_ALLOWED_ROW_TRANSITIONS = {
    "STAGED": {
        "VALID",
        "FAILED",
    },
    "VALID": {
        "IMPORTED",
    },
    "FAILED": set(),
    "IMPORTED": set(),
}


class ProductImportStateTransitionError(
    ProductImportTerminalError
):
    """Illegal Product Import state transition."""


def utc_naive_now() -> datetime:
    return datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )


def assert_job_transition(
    current: str,
    target: str,
) -> None:
    current_status = str(current)
    target_status = str(target)

    if (
        current_status
        not in JOB_STATUSES
        or target_status
        not in JOB_STATUSES
        or target_status
        not in _ALLOWED_JOB_TRANSITIONS[
            current_status
        ]
    ):
        raise ProductImportStateTransitionError(
            "Illegal Product Import job transition: "
            f"{current_status} -> {target_status}."
        )


def assert_row_transition(
    current: str,
    target: str,
) -> None:
    current_status = str(current)
    target_status = str(target)

    if (
        current_status
        not in ROW_STATUSES
        or target_status
        not in ROW_STATUSES
        or target_status
        not in _ALLOWED_ROW_TRANSITIONS[
            current_status
        ]
    ):
        raise ProductImportStateTransitionError(
            "Illegal Product Import row transition: "
            f"{current_status} -> {target_status}."
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
    target: str,
    *,
    touch_updated_at: bool = True,
    **values: Any,
) -> None:
    assert_job_transition(
        str(job.status),
        target,
    )
    job.status = str(target)
    touch_job(
        job,
        touch_updated_at=touch_updated_at,
        **values,
    )


def transition_row(
    row: Any,
    target: str,
    **values: Any,
) -> None:
    assert_row_transition(
        str(row.status),
        target,
    )
    row.status = str(target)
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
    target: str,
    **values: Any,
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
            raise ValueError(
                "Product import job not found."
            )

        transition_job(
            job,
            target,
            **values,
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
        summary = runtime_failure_summary(
            message=message,
            final_attempt=final_attempt,
            retryable=retryable,
            resume_status=current_status,
        )

        if final_attempt:
            transition_job(
                job,
                "FAILED",
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
