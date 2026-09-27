"""Bounded, resumable Product Import validation orchestration.

Rows are classified and committed in fixed-size transactions so a worker
restart resumes from rows that are still STAGED instead of reclassifying durable
outcomes. Phase 7 continues to execution whenever at least one row is valid;
zero-valid jobs stop at VALIDATION_FAILED.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from domains.product_tracking import (
    ProductTrackingError,
)
from domains.simple_products.imports.application.state_machine import (
    JobStatus,
    RowStatus,
    touch_job,
    transition_job,
    transition_row,
    utc_naive_now,
)
from domains.simple_products.imports.domain import (
    ProductImportTerminalError,
)
from domains.simple_products.imports.domain.errors import (
    ProductImportRowValidationError,
    classify_import_error,
    user_safe_error_message,
)
from domains.simple_products.imports.domain.mapping import (
    mapping_complete,
    validate_mapping,
)
from domains.simple_products.imports.domain.normalization import (
    normalize_raw_row,
)
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    count_job_rows,
    count_validation_outcomes,
    fetch_validation_batch,
    invalidate_external_barcode_conflicts,
    invalidate_internal_duplicate_barcodes,
    load_job,
    rebuild_job_barcode_staging,
    open_tenant_session,
)
from domains.simple_products.service import (
    SimpleProductError,
)


VALIDATION_BATCH_SIZE = 500


def classify_row_error(
    exc: Exception,
) -> ProductImportRowValidationError:
    if isinstance(
        exc,
        (
            ProductTrackingError,
            SimpleProductError,
        ),
    ):
        return ProductImportRowValidationError(
            exc.code,
            exc.message,
        )

    classification = (
        classify_import_error(
            exc
        )
    )
    if classification.row_failure:
        return ProductImportRowValidationError(
            classification.code
            or "IMPORT_ROW_INVALID",
            classification.message
            or user_safe_error_message(
                classification.code
                or "IMPORT_ROW_INVALID"
            ),
        )

    raise exc


def validation_outcome(
    valid_count: int,
    invalid_count: int,
    *,
    imported_count: int = 0,
    import_failed_count: int = 0,
) -> tuple[str, bool]:
    if int(valid_count) > 0:
        return (
            JobStatus.IMPORTING.value,
            True,
        )

    if int(imported_count) > 0:
        return (
            JobStatus.COMPLETED_WITH_ERRORS.value,
            False,
        )

    return (
        JobStatus.VALIDATION_FAILED.value,
        False,
    )


def collect_row_validation(
    rows: list[Any],
    *,
    mapping: dict[str, str],
    default_lot_control_mode: str,
    default_expiry_control_mode: str,
) -> tuple[
    dict[int, dict[str, Any]],
    dict[int, tuple[str, str]],
]:
    if (
        len(rows)
        > VALIDATION_BATCH_SIZE
    ):
        raise ValueError(
            "Validation batch exceeds the bounded validation limit."
        )

    normalized: dict[
        int,
        dict[str, Any],
    ] = {}
    errors: dict[
        int,
        tuple[str, str],
    ] = {}
    for row in rows:
        try:
            data = normalize_raw_row(
                dict(
                    row.raw_data
                    or {}
                ),
                mapping,
                default_lot_control_mode=
                    default_lot_control_mode,
                default_expiry_control_mode=
                    default_expiry_control_mode,
            )
            row_id = int(row.id)
            normalized[
                row_id
            ] = data

        except Exception as exc:
            classified = (
                classify_row_error(
                    exc
                )
            )
            errors[int(row.id)] = (
                classified.code,
                classified.message,
            )

    return (
        normalized,
        errors,
    )


async def _validate_batch(
    db,
    *,
    company_id: int,
    rows: list[Any],
    mapping: dict[str, str],
    default_lot_control_mode: str,
    default_expiry_control_mode: str,
) -> tuple[int, int]:
    (
        normalized,
        errors,
    ) = collect_row_validation(
        rows,
        mapping=mapping,
        default_lot_control_mode=
            default_lot_control_mode,
        default_expiry_control_mode=
            default_expiry_control_mode,
    )

    valid_count = 0
    failed_count = 0

    for row in rows:
        row_id = int(row.id)
        normalized_data = (
            normalized.get(
                row_id,
                {},
            )
        )
        if row_id in errors:
            (
                error_code,
                error_message,
            ) = errors[row_id]
            transition_row(
                row,
                RowStatus.INVALID,
                normalized_data=
                    normalized_data,
                error_code=error_code,
                error_message=
                    error_message,
            )
            failed_count += 1
        else:
            transition_row(
                row,
                RowStatus.VALID,
                normalized_data=
                    normalized_data,
                error_code=None,
                error_message=None,
            )
            valid_count += 1

    return (
        valid_count,
        failed_count,
    )


async def _validation_contract(
    *,
    company_id: int,
    job_id: UUID,
) -> tuple[
    dict[str, str],
    str,
    str,
] | None:
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
        ):
            await db.rollback()
            return None
        if (
            str(job.status)
            != JobStatus.VALIDATING.value
        ):
            raise ProductImportTerminalError(
                "Product import validation can only run from VALIDATING state."
            )

        try:
            mapping = validate_mapping(
                list(
                    job.detected_headers
                    or []
                ),
                dict(
                    job.column_mapping
                    or {}
                ),
            )
        except ValueError as exc:
            raise ProductImportTerminalError(
                str(exc)
            ) from exc

        if not mapping_complete(mapping):
            transition_job(
                job,
                JobStatus.NEEDS_MAPPING,
            )
            await db.commit()
            return None

        default_lot_control_mode = str(
            job.default_lot_control_mode
        )
        default_expiry_control_mode = str(
            job.default_expiry_control_mode
        )

        (
            valid_count,
            invalid_count,
            _staged_count,
        ) = await count_validation_outcomes(
            db,
            company_id=company_id,
            job_id=job_id,
        )
        imported_count = await count_job_rows(
            db,
            company_id=company_id,
            job_id=job_id,
            status=RowStatus.IMPORTED.value,
        )
        import_failed_count = await count_job_rows(
            db,
            company_id=company_id,
            job_id=job_id,
            status=RowStatus.IMPORT_FAILED.value,
        )
        durable_valid_count = (
            valid_count
            + imported_count
            + import_failed_count
        )

        if (
            int(job.valid_rows)
            != durable_valid_count
            or int(job.failed_rows)
            != invalid_count
            or int(job.processed_rows)
            != imported_count
        ):
            touch_job(
                job,
                valid_rows=
                    durable_valid_count,
                failed_rows=
                    invalid_count,
                processed_rows=
                    imported_count,
            )
            await db.commit()

        return (
            mapping,
            default_lot_control_mode,
            default_expiry_control_mode,
        )
    except Exception:
        await db.rollback()
        raise
    finally:
        await close_tenant_session(
            token,
            db,
        )


async def validate_rows(
    *,
    company_id: int,
    job_id: UUID,
) -> bool:
    contract = await _validation_contract(
        company_id=company_id,
        job_id=job_id,
    )
    if contract is None:
        return False

    (
        mapping,
        default_lot_control_mode,
        default_expiry_control_mode,
    ) = contract

    after_row_number = 0

    while True:
        token, db = await open_tenant_session(
            company_id
        )
        reset_cursor = False
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
            ):
                await db.rollback()
                return False
            if (
                str(job.status)
                != JobStatus.VALIDATING.value
            ):
                raise ProductImportTerminalError(
                    "Product import validation state changed unexpectedly."
                )

            rows = await fetch_validation_batch(
                db,
                company_id=company_id,
                job_id=job_id,
                after_row_number=
                    after_row_number,
                limit=
                    VALIDATION_BATCH_SIZE,
            )

            if not rows:
                (
                    valid_count,
                    invalid_count,
                    staged_count,
                ) = await count_validation_outcomes(
                    db,
                    company_id=company_id,
                    job_id=job_id,
                )

                if staged_count > 0:
                    if (
                        after_row_number
                        > 0
                    ):
                        reset_cursor = True
                        await db.rollback()
                    else:
                        raise ProductImportTerminalError(
                            "Validation checkpoint is inconsistent: staged rows remain unreachable."
                        )
                else:
                    await rebuild_job_barcode_staging(
                        db,
                        company_id=company_id,
                        job_id=job_id,
                    )
                    await invalidate_internal_duplicate_barcodes(
                        db,
                        company_id=company_id,
                        job_id=job_id,
                    )
                    await invalidate_external_barcode_conflicts(
                        db,
                        company_id=company_id,
                        job_id=job_id,
                    )
                    (
                        valid_count,
                        invalid_count,
                        staged_count,
                    ) = await count_validation_outcomes(
                        db,
                        company_id=company_id,
                        job_id=job_id,
                    )
                    if staged_count != 0:
                        raise ProductImportTerminalError(
                            "Validation finalization found staged rows unexpectedly."
                        )

                    imported_count = await count_job_rows(
                        db,
                        company_id=company_id,
                        job_id=job_id,
                        status=RowStatus.IMPORTED.value,
                    )
                    import_failed_count = await count_job_rows(
                        db,
                        company_id=company_id,
                        job_id=job_id,
                        status=RowStatus.IMPORT_FAILED.value,
                    )

                    if (
                        valid_count
                        + invalid_count
                        + imported_count
                        + import_failed_count
                        != int(
                            job.total_rows
                        )
                    ):
                        raise ProductImportTerminalError(
                            "Validation outcome counts do not match the staged import total."
                        )

                    (
                        target,
                        can_execute,
                    ) = validation_outcome(
                        valid_count,
                        invalid_count,
                        imported_count=
                            imported_count,
                        import_failed_count=
                            import_failed_count,
                    )
                    transition_job(
                        job,
                        target,
                        column_mapping=
                            mapping,
                        valid_rows=(
                            valid_count
                            + imported_count
                            + import_failed_count
                        ),
                        failed_rows=
                            invalid_count,
                        processed_rows=
                            imported_count,
                        error_summary=(
                            {
                                "code": (
                                    "PRODUCT_IMPORT_VALIDATION_FAILED"
                                    if target
                                    == JobStatus.VALIDATION_FAILED.value
                                    else "PRODUCT_IMPORT_VALIDATION_PARTIAL"
                                ),
                                "failed_rows":
                                    invalid_count,
                            }
                            if invalid_count
                            or import_failed_count
                            else {}
                        ),
                        finished_at=(
                            utc_naive_now()
                            if target
                            in {
                                JobStatus.VALIDATION_FAILED.value,
                                JobStatus.COMPLETED_WITH_ERRORS.value,
                            }
                            else None
                        ),
                    )
                    await db.commit()
                    return can_execute
            else:
                (
                    valid_delta,
                    failed_delta,
                ) = await _validate_batch(
                    db,
                    company_id=company_id,
                    rows=rows,
                    mapping=mapping,
                    default_lot_control_mode=
                        default_lot_control_mode,
                    default_expiry_control_mode=
                        default_expiry_control_mode,
                )

                touch_job(
                    job,
                    valid_rows=(
                        int(job.valid_rows)
                        + valid_delta
                    ),
                    failed_rows=(
                        int(job.failed_rows)
                        + failed_delta
                    ),
                )

                last_row_number = int(
                    rows[-1].row_number
                )
                await db.commit()
                after_row_number = (
                    last_row_number
                )
        except Exception:
            await db.rollback()
            raise
        finally:
            await close_tenant_session(
                token,
                db,
            )

        if reset_cursor:
            after_row_number = 0
