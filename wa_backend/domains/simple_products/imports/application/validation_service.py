"""Product Import validation orchestration.

Phase 2 preserves the current all-or-nothing policy: any invalid row finishes
validation as VALIDATION_FAILED and prevents execution.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from domains.product_tracking import (
    ProductTrackingError,
)
from domains.simple_products.imports.application.state_machine import (
    set_job_status,
    transition_job,
    transition_row,
)
from domains.simple_products.imports.domain import (
    ProductImportTerminalError,
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
    find_active_barcodes,
    list_job_rows,
    load_job,
    open_tenant_session,
)
from domains.simple_products.service import (
    SimpleProductError,
)


def classify_row_error(
    exc: Exception,
) -> tuple[str, str]:
    if isinstance(
        exc,
        ProductTrackingError,
    ):
        return (
            exc.code,
            exc.message,
        )
    if isinstance(
        exc,
        SimpleProductError,
    ):
        return (
            exc.code,
            exc.message,
        )
    return (
        "IMPORT_ROW_INVALID",
        str(exc),
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
    dict[str, list[int]],
]:
    normalized: dict[
        int,
        dict[str, Any],
    ] = {}
    errors: dict[
        int,
        tuple[str, str],
    ] = {}
    barcode_rows: dict[
        str,
        list[int],
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

            row_barcodes = {
                str(barcode)
                for barcode in (
                    data.get(
                        "unit_barcode"
                    ),
                    data.get(
                        "package_barcode"
                    ),
                )
                if barcode
            }
            for barcode in row_barcodes:
                barcode_rows.setdefault(
                    barcode,
                    [],
                ).append(
                    row_id
                )
        except Exception as exc:
            errors[int(row.id)] = (
                classify_row_error(
                    exc
                )
            )

    return (
        normalized,
        errors,
        barcode_rows,
    )


async def validate_rows(
    *,
    company_id: int,
    job_id: UUID,
) -> bool:
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
            await db.rollback()
            await set_job_status(
                company_id=company_id,
                job_id=job_id,
                target="NEEDS_MAPPING",
            )
            return False

        rows = await list_job_rows(
            db,
            company_id=company_id,
            job_id=job_id,
        )

        (
            normalized,
            errors,
            barcode_rows,
        ) = collect_row_validation(
            rows,
            mapping=mapping,
            default_lot_control_mode=str(
                job.default_lot_control_mode
            ),
            default_expiry_control_mode=str(
                job.default_expiry_control_mode
            ),
        )

        for barcode, row_ids in (
            barcode_rows.items()
        ):
            if len(row_ids) > 1:
                for row_id in row_ids:
                    errors[row_id] = (
                        "IMPORT_BARCODE_DUPLICATE",
                        f"Barcode {barcode} appears on more than one import row.",
                    )

        candidates = [
            barcode
            for barcode, row_ids
            in barcode_rows.items()
            if len(row_ids) == 1
        ]
        if candidates:
            existing = (
                await find_active_barcodes(
                    db,
                    company_id=company_id,
                    candidates=candidates,
                )
            )
            for barcode in existing:
                for row_id in barcode_rows.get(
                    str(barcode),
                    [],
                ):
                    errors[
                        row_id
                    ] = (
                        "IMPORT_BARCODE_CONFLICT",
                        f"Barcode {barcode} is already active.",
                    )

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
                    "FAILED",
                    normalized_data=
                        normalized_data,
                    error_code=error_code,
                    error_message=
                        error_message,
                )
            else:
                transition_row(
                    row,
                    "VALID",
                    normalized_data=
                        normalized_data,
                    error_code=None,
                    error_message=None,
                )

        valid_count = sum(
            1
            for row in rows
            if row.status == "VALID"
        )
        failed_count = (
            len(rows)
            - valid_count
        )

        locked = await load_job(
            db,
            company_id=company_id,
            job_id=job_id,
            for_update=True,
        )
        assert locked is not None

        target = (
            "VALIDATION_FAILED"
            if failed_count
            else "IMPORTING"
        )
        transition_job(
            locked,
            target,
            column_mapping=mapping,
            valid_rows=valid_count,
            failed_rows=failed_count,
            processed_rows=0,
            error_summary=(
                {
                    "code":
                        "PRODUCT_IMPORT_VALIDATION_FAILED",
                    "failed_rows":
                        failed_count,
                }
                if failed_count
                else {}
            ),
        )

        await db.commit()
        return failed_count == 0
    except Exception:
        await db.rollback()
        raise
    finally:
        await close_tenant_session(
            token,
            db,
        )
