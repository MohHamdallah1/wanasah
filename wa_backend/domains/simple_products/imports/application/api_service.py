"""Application facade for Product Import HTTP use cases.

HTTP transport delegates here after authentication/permission and request
parsing. Tenant-scoped lookup and mapping authority live outside the router.
"""
from __future__ import annotations

import json
from typing import BinaryIO, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.product_tracking import resolve_product_tracking_modes
from domains.simple_products.imports.application.cancellation_service import (
    cancel_import_job,
)
from domains.simple_products.imports.application.correction_service import (
    apply_correction_upload,
    apply_correction_cells,
    build_correction_artifact,
)
from domains.simple_products.imports.application.state_machine import RowStatus
from domains.simple_products.imports.domain import (
    CANONICAL_IMPORT_FIELDS,
    ProductImportTerminalError,
)
from domains.simple_products.imports.domain.errors import (
    import_error_field,
    public_error_summary,
    user_safe_row_error_message,
)
from domains.simple_products.imports.infrastructure.queue import (
    enqueue_new_import,
    requeue_import,
    retry_failed_import,
)
from domains.simple_products.imports.infrastructure.repository import (
    ProductImportProgress,
    count_job_progress,
)
from domains.simple_products.imports.domain.inline_correction import (
    MAX_INLINE_CORRECTION_BYTES, MAX_INLINE_CORRECTION_ROWS, InlineCorrectionError,
    correction_details_expired, correction_field_mapping, correction_unavailable_reason,
)
from domains.simple_products.imports.infrastructure.correction_rows_repository import (
    fetch_correction_rows_page,
)
from models import ProductImportJob, ProductImportRow


_CANONICAL_MAPPING_FIELDS = frozenset(CANONICAL_IMPORT_FIELDS)


async def _load_job(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
    for_review: bool = False,
) -> ProductImportJob:
    statement = select(ProductImportJob).where(
        ProductImportJob.company_id == int(company_id), ProductImportJob.id == job_id,
    )
    if for_review:
        statement = statement.with_for_update(read=True)
    job = await db.scalar(statement)
    if job is None:
        raise ProductImportTerminalError(
            "Product import job was not found in tenant scope.",
            code="PRODUCT_IMPORT_NOT_FOUND",
        )
    return job


def validate_import_mapping(
    *,
    detected_headers: list[str],
    mapping: dict[str, str],
) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for raw_field, raw_header in mapping.items():
        field = str(raw_field)
        header = str(raw_header).strip()
        if not header:
            continue
        if field not in _CANONICAL_MAPPING_FIELDS:
            raise ProductImportTerminalError(
                "Unknown canonical mapping field.",
                code="PRODUCT_IMPORT_MAPPING_INVALID",
                user_message="Column mapping is invalid.",
            )
        cleaned[field] = header

    if len(cleaned.values()) != len(set(cleaned.values())):
        raise ProductImportTerminalError(
            "One source column was mapped more than once.",
            code="PRODUCT_IMPORT_MAPPING_INVALID",
            user_message="Column mapping is invalid.",
        )

    headers = {str(value) for value in detected_headers}
    if any(header not in headers for header in cleaned.values()):
        raise ProductImportTerminalError(
            "Mapping references a source header not present in the job.",
            code="PRODUCT_IMPORT_MAPPING_INVALID",
            user_message="Column mapping is invalid.",
        )

    if not cleaned.get("name"):
        raise ProductImportTerminalError(
            "Product name mapping is required.",
            code="PRODUCT_IMPORT_MAPPING_NAME_REQUIRED",
            user_message="Map the product-name column.",
        )
    if not (cleaned.get("package_price") or cleaned.get("unit_price")):
        raise ProductImportTerminalError(
            "Package or unit price mapping is required.",
            code="PRODUCT_IMPORT_MAPPING_PRICE_REQUIRED",
            user_message="Map package_price or unit_price.",
        )
    return cleaned


async def create_import(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    request_id: UUID,
    file_name: str,
    content_type: str,
    source_stream: BinaryIO,
    source_size: int,
    source_sha256: str,
    default_lot_control_mode: str | None,
    default_expiry_control_mode: str | None,
) -> dict[str, Any]:
    tracking_defaults = await resolve_product_tracking_modes(
        db,
        company_id=int(company_id),
        lot_control_mode=default_lot_control_mode,
        expiry_control_mode=default_expiry_control_mode,
    )
    queued = await enqueue_new_import(
        company_id=int(company_id),
        actor_id=int(actor_id),
        request_id=request_id,
        file_name=file_name,
        content_type=content_type,
        source_stream=source_stream,
        source_size=int(source_size),
        source_sha256=str(source_sha256),
        default_lot_control_mode=tracking_defaults.lot_control_mode,
        default_expiry_control_mode=tracking_defaults.expiry_control_mode,
    )
    return {
        "job_id": str(queued["job_id"]),
        "status": str(queued["status"]),
        "replayed": bool(queued["replayed"]),
        "default_lot_control_mode": tracking_defaults.lot_control_mode,
        "default_expiry_control_mode": tracking_defaults.expiry_control_mode,
        "message": "Import accepted for background processing.",
    }


def _job_payload(
    job: ProductImportJob,
    progress: ProductImportProgress,
) -> dict[str, Any]:
    return {
        "job_id": str(job.id),
        "status": str(job.status),
        "file_name": str(job.file_name),
        "total_rows": int(job.total_rows),
        "processed_rows": int(job.processed_rows),
        "valid_rows": int(job.valid_rows),
        "failed_rows": int(job.failed_rows),
        "imported_rows": max(int(progress.imported_rows), int(job.processed_rows)),
        "invalid_rows": max(int(progress.invalid_rows), int(job.failed_rows)),
        "import_failed_rows": int(progress.import_failed_rows),
        "pending_rows": int(progress.pending_rows),
        "detected_headers": list(job.detected_headers or []),
        "suggested_mapping": dict(job.suggested_mapping or {}),
        "column_mapping": dict(job.column_mapping or {}),
        "default_lot_control_mode": str(job.default_lot_control_mode),
        "default_expiry_control_mode": str(job.default_expiry_control_mode),
        "error_summary": public_error_summary(job.error_summary),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def _error_item(row: ProductImportRow) -> dict[str, Any]:
    return {
        "row_number": int(row.row_number),
        "code": row.error_code,
        "field": import_error_field(row.error_code),
        "message": user_safe_row_error_message(row.error_code),
    }


async def ensure_import_job_access(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
) -> None:
    await _load_job(
        db,
        company_id=company_id,
        job_id=job_id,
    )


async def read_import_status(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
) -> dict[str, Any]:
    job = await _load_job(db, company_id=company_id, job_id=job_id)
    progress = await count_job_progress(
        db,
        company_id=int(company_id),
        job_id=job_id,
    )
    errors: list[dict[str, Any]] = []
    if progress.invalid_rows > 0 or progress.import_failed_rows > 0:
        result = await db.execute(
            select(ProductImportRow)
            .where(
                ProductImportRow.company_id == int(company_id),
                ProductImportRow.job_id == job_id,
                ProductImportRow.status.in_(
                    (RowStatus.INVALID.value, RowStatus.IMPORT_FAILED.value)
                ),
            )
            .order_by(ProductImportRow.row_number.asc())
            .limit(50)
        )
        rows = list(result.scalars().fetchmany(50))
        errors = [_error_item(row) for row in rows]
    payload = _job_payload(job, progress)
    payload["errors"] = errors
    return payload


async def read_import_errors(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
    after_row: int,
    limit: int,
) -> dict[str, Any]:
    await _load_job(db, company_id=company_id, job_id=job_id)
    rows = list(
        (
            await db.scalars(
                select(ProductImportRow)
                .where(
                    ProductImportRow.company_id == int(company_id),
                    ProductImportRow.job_id == job_id,
                    ProductImportRow.status.in_(
                        (RowStatus.INVALID.value, RowStatus.IMPORT_FAILED.value)
                    ),
                    ProductImportRow.row_number > int(after_row),
                )
                .order_by(ProductImportRow.row_number.asc())
                .limit(int(limit) + 1)
            )
        ).all()
    )
    page = rows[: int(limit)]
    has_more = len(rows) > int(limit)
    return {
        "items": [_error_item(row) for row in page],
        "next_after_row": (
            int(page[-1].row_number) if has_more and page else None
        ),
    }


async def download_correction(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
    file_format: str,
    locale: str = "en",
):
    await _load_job(db, company_id=company_id, job_id=job_id)
    return await build_correction_artifact(
        company_id=int(company_id),
        job_id=job_id,
        file_format=str(file_format),
        locale=locale,
    )


async def apply_correction(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    job_id: UUID,
    request_id: UUID,
    file_name: str,
    payload: bytes,
) -> dict[str, Any]:
    await _load_job(db, company_id=company_id, job_id=job_id)
    result = await apply_correction_upload(
        company_id=int(company_id),
        actor_id=int(actor_id),
        job_id=job_id,
        request_id=request_id,
        file_name=str(file_name),
        payload=payload,
    )
    return {
        **dict(result),
        "message": "Correction accepted for revalidation.",
    }


async def set_import_mapping(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
    mapping: dict[str, str],
) -> dict[str, str]:
    job = await _load_job(db, company_id=company_id, job_id=job_id)
    cleaned = validate_import_mapping(
        detected_headers=list(job.detected_headers or []),
        mapping=mapping,
    )
    status = await requeue_import(
        company_id=int(company_id),
        job_id=job_id,
        mapping=cleaned,
    )
    return {
        "job_id": str(job_id),
        "status": str(status),
        "message": "Column mapping accepted.",
    }


async def cancel_import(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
) -> dict[str, str]:
    await _load_job(db, company_id=company_id, job_id=job_id)
    status = await cancel_import_job(
        company_id=int(company_id),
        job_id=job_id,
    )
    return {
        "job_id": str(job_id),
        "status": str(status),
        "message": "Import cancellation accepted.",
    }


async def retry_import(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
) -> dict[str, str]:
    await _load_job(db, company_id=company_id, job_id=job_id)
    status = await retry_failed_import(
        company_id=int(company_id),
        job_id=job_id,
    )
    return {
        "job_id": str(job_id),
        "status": str(status),
        "message": "Import retry accepted.",
    }


async def read_correction_rows(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
    after_row: int,
    limit: int,
    expected_job_version: int | None = None,
) -> dict[str, Any]:
    if not 1 <= limit <= MAX_INLINE_CORRECTION_ROWS or after_row < 0:
        raise InlineCorrectionError("PRODUCT_IMPORT_CORRECTION_ROWS_INVALID")
    # A short shared job lock gives this page one stable mapping/state/version.
    job = await _load_job(db, company_id=company_id, job_id=job_id, for_review=True)
    if expected_job_version is not None and int(job.version) != expected_job_version:
        raise InlineCorrectionError("PRODUCT_IMPORT_CORRECTION_STALE_JOB")
    fields = correction_field_mapping(
        dict(job.column_mapping or {}), list(job.detected_headers or []),
    )
    rows = await fetch_correction_rows_page(
        db, company_id=company_id, job_id=job_id,
        fields=fields, after_row=after_row, limit=limit,
    )
    payload: dict[str, Any] = {
        "job_id": str(job_id), "job_version": int(job.version),
        "status": str(job.status), "fields": list(fields),
        "items": [], "next_after_row": None,
    }
    used_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + 64
    for row in rows[:limit]:
        details_expired = correction_details_expired(
            finished_at=job.finished_at, compacted_at=row.compacted_at,
        )
        reason = correction_unavailable_reason(
            status=str(job.status), details_expired=details_expired,
            fields=fields, values_available=row.values is not None,
        )
        item = {
            "row_identity": str(row.row_identity), "row_number": int(row.row_number),
            "version": int(row.version), "status": str(row.status),
            "values": {} if details_expired else dict(row.values or {}),
            "errors": [_error_item(row)], "editable": reason is None,
            "unavailable_reason": reason,
        }
        item_bytes = len(json.dumps(item, ensure_ascii=False, allow_nan=False).encode("utf-8")) + 2
        if used_bytes + item_bytes > MAX_INLINE_CORRECTION_BYTES:
            payload["next_after_row"] = int(payload["items"][-1]["row_number"])
            break
        payload["items"].append(item)
        used_bytes += item_bytes
    else:
        if len(rows) > limit:
            payload["next_after_row"] = int(payload["items"][-1]["row_number"])
    return payload


async def apply_inline_correction(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    job_id: UUID,
    request_id: UUID,
    expected_job_version: int,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    # Lookup checks ownership only: do not pre-check mutable status before replay.
    await _load_job(db, company_id=company_id, job_id=job_id)
    result = await apply_correction_cells(
        company_id=company_id, actor_id=actor_id, job_id=job_id,
        request_id=request_id, expected_job_version=expected_job_version, rows=rows,
    )
    return {**result, "message": "Correction accepted for revalidation."}
