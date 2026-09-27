"""HTTP transport adapter for Product Import.

This router preserves the existing /simple-products import URLs while keeping
Product Import transport concerns inside the owning capability module.
"""
from __future__ import annotations

import base64
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    field_validator,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from domains.product_tracking import (
    ProductTrackingError,
    resolve_product_tracking_modes,
)
from domains.simple_products.imports.application.audit_service import (
    get_import_lineage,
)
from domains.simple_products.imports.application.correction_service import (
    apply_correction_upload,
    build_correction_artifact,
)
from domains.simple_products.imports.application.state_machine import (
    JobStatus,
    RowStatus,
)
from domains.simple_products.imports.domain.admission import (
    ProductImportAdmissionDenied,
)
from domains.simple_products.imports.domain import (
    CANONICAL_IMPORT_FIELDS,
    ProductImportTerminalError,
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
from domains.simple_products.imports.infrastructure.upload_stream import (
    ProductImportUploadTooLarge,
    spool_upload_bounded,
)
from domains.simple_products.imports.infrastructure.template import (
    build_product_import_template,
)
from inventory_access import InventoryAccess
from models import (
    Driver,
    ProductImportJob,
    ProductImportRow,
)


router = APIRouter(
    prefix="/simple-products",
    tags=["Simple Products"],
)

MAX_IMPORT_FILE_BYTES = 8 * 1024 * 1024
_ALLOWED_IMPORT_SUFFIXES = {".csv", ".xlsx"}
_CANONICAL_MAPPING_FIELDS = frozenset(
    CANONICAL_IMPORT_FIELDS,
)


class StrictImportRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )


class ImportMappingRequest(
    StrictImportRequest
):
    mapping: dict[str, str]

    @field_validator("mapping")
    @classmethod
    def mapping_contract(
        cls,
        value: dict[str, str],
    ) -> dict[str, str]:
        unknown = (
            set(value)
            - _CANONICAL_MAPPING_FIELDS
        )
        if unknown:
            raise ValueError(
                "Unknown import mapping field."
            )
        cleaned = {
            str(key):
                str(header).strip()
            for key, header
            in value.items()
            if str(header).strip()
        }
        if len(
            cleaned.values()
        ) != len(
            set(cleaned.values())
        ):
            raise ValueError(
                "One source column cannot map to multiple fields."
            )
        return cleaned


async def _require(
    db: AsyncSession,
    actor: Driver,
    permission: str,
) -> None:
    await InventoryAccess(
        db,
        actor,
    ).require(
        permission,
        any_location=True,
    )


async def _require_manage(
    db: AsyncSession,
    actor: Driver,
) -> None:
    for permission in (
        "catalog.manage",
        "catalog.publish",
        "pricing.manage",
    ):
        await _require(
            db,
            actor,
            permission,
        )


@router.get("/import-template")
async def get_product_import_template(
    locale: str = Query(
        "ar",
        pattern="^(ar|en)$",
    ),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(db, actor)

    payload = build_product_import_template(
        locale=locale,
    )
    return {
        "file_name":
            "products-import-template.xlsx",
        "content_type": (
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        "content_base64": base64.b64encode(
            payload
        ).decode("ascii"),
    }


@router.post("/imports", status_code=202)
async def create_product_import(
    request_id: UUID = Form(...),
    default_lot_control_mode: str | None = Form(None),
    default_expiry_control_mode: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(
        db,
        actor,
    )

    file_name = str(
        file.filename
        or ""
    ).strip()
    if (
        not file_name
        or len(
            file_name
        ) > 255
        or "\x00" in file_name
    ):
        await file.close()
        raise HTTPException(
            422,
            detail={
                "code":
                    "PRODUCT_IMPORT_FILE_NAME_INVALID",
                "message":
                    "Invalid file name.",
                "context": {},
            },
        )

    suffix = (
        "."
        + file_name.lower().rsplit(
            ".",
            1,
        )[-1]
        if "." in file_name
        else ""
    )
    if suffix not in _ALLOWED_IMPORT_SUFFIXES:
        await file.close()
        raise HTTPException(
            415,
            detail={
                "code":
                    "PRODUCT_IMPORT_FILE_TYPE_UNSUPPORTED",
                "message":
                    "Upload a CSV or XLSX file.",
                "context": {},
            },
        )

    content_type = str(
        file.content_type
        or "application/octet-stream"
    )
    bounded_upload = None
    try:
        bounded_upload = (
            await spool_upload_bounded(
                file,
                max_bytes=
                    MAX_IMPORT_FILE_BYTES,
            )
        )
    except ProductImportUploadTooLarge as exc:
        raise HTTPException(
            413,
            detail={
                "code":
                    "PRODUCT_IMPORT_FILE_TOO_LARGE",
                "message":
                    "The import file is larger than 8MB.",
                "context": {
                    "max_bytes":
                        MAX_IMPORT_FILE_BYTES,
                },
            },
        ) from exc
    finally:
        await file.close()

    if (
        bounded_upload
        is None
        or int(
            bounded_upload.byte_size
        ) <= 0
    ):
        if bounded_upload is not None:
            bounded_upload.close()
        raise HTTPException(
            422,
            detail={
                "code":
                    "PRODUCT_IMPORT_FILE_EMPTY",
                "message":
                    "The import file is empty.",
                "context": {},
            },
        )

    try:
        tracking_defaults = (
            await resolve_product_tracking_modes(
                db,
                company_id=int(
                    actor.company_id
                ),
                lot_control_mode=
                    default_lot_control_mode,
                expiry_control_mode=
                    default_expiry_control_mode,
            )
        )
        queued = await enqueue_new_import(
            company_id=int(
                actor.company_id
            ),
            actor_id=int(
                actor.id
            ),
            request_id=request_id,
            file_name=file_name,
            content_type=content_type,
            source_stream=
                bounded_upload.stream,
            source_size=
                bounded_upload.byte_size,
            source_sha256=
                bounded_upload.sha256,
            default_lot_control_mode=(
                tracking_defaults.lot_control_mode
            ),
            default_expiry_control_mode=(
                tracking_defaults.expiry_control_mode
            ),
        )
    except ProductTrackingError as exc:
        raise HTTPException(
            exc.status_code,
            detail={
                "code":
                    exc.code,
                "message":
                    exc.message,
                "context":
                    exc.context,
            },
        ) from exc
    except ProductImportAdmissionDenied as exc:
        status_code = (
            503
            if exc.code
            == "PRODUCT_IMPORT_GLOBAL_SOURCE_CAPACITY"
            else 429
        )
        raise HTTPException(
            status_code,
            detail={
                "code":
                    exc.code,
                "message":
                    exc.message,
                "context": {
                    "current":
                        exc.current_value,
                    "limit":
                        exc.limit_value,
                    "retry_after_seconds":
                        exc.retry_after_seconds,
                },
            },
            headers={
                "Retry-After":
                    str(
                        exc.retry_after_seconds
                    ),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            409,
            detail={
                "code":
                    "PRODUCT_IMPORT_REQUEST_CONFLICT",
                "message":
                    str(
                        exc
                    ),
                "context": {},
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            503,
            detail={
                "code":
                    "PRODUCT_IMPORT_QUEUE_UNAVAILABLE",
                "message":
                    "Import could not be queued.",
                "context": {},
            },
        ) from exc
    finally:
        bounded_upload.close()

    return {
        "job_id":
            str(
                queued[
                    "job_id"
                ]
            ),
        "status":
            str(
                queued[
                    "status"
                ]
            ),
        "replayed":
            bool(
                queued[
                    "replayed"
                ]
            ),
        "default_lot_control_mode": (
            tracking_defaults.lot_control_mode
        ),
        "default_expiry_control_mode": (
            tracking_defaults.expiry_control_mode
        ),
        "message":
            "Import accepted for background processing.",
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
        "imported_rows": max(
            int(
                progress.imported_rows
            ),
            int(
                job.processed_rows
            ),
        ),
        "invalid_rows": max(
            int(
                progress.invalid_rows
            ),
            int(
                job.failed_rows
            ),
        ),
        "import_failed_rows": int(
            progress.import_failed_rows
        ),
        "pending_rows": int(
            progress.pending_rows
        ),
        "detected_headers": list(
            job.detected_headers or []
        ),
        "suggested_mapping": dict(
            job.suggested_mapping or {}
        ),
        "column_mapping": dict(
            job.column_mapping or {}
        ),
        "default_lot_control_mode": str(
            job.default_lot_control_mode
        ),
        "default_expiry_control_mode": str(
            job.default_expiry_control_mode
        ),
        "error_summary": dict(
            job.error_summary or {}
        ),
        "created_at": (
            job.created_at.isoformat()
            if job.created_at
            else None
        ),
        "started_at": (
            job.started_at.isoformat()
            if job.started_at
            else None
        ),
        "finished_at": (
            job.finished_at.isoformat()
            if job.finished_at
            else None
        ),
    }


@router.get("/imports/{job_id}")
async def get_product_import(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(
        db,
        actor,
        "catalog.read",
    )
    job = await db.scalar(
        select(ProductImportJob).where(
            ProductImportJob.company_id
            == int(actor.company_id),
            ProductImportJob.id == job_id,
        )
    )
    if job is None:
        raise HTTPException(
            404,
            detail={
                "code": "PRODUCT_IMPORT_NOT_FOUND",
                "message": "Import job was not found.",
                "context": {},
            },
        )

    progress = await count_job_progress(
        db,
        company_id=int(actor.company_id),
        job_id=job_id,
    )

    errors = []
    if (
        progress.invalid_rows > 0
        or progress.import_failed_rows > 0
    ):
        result_rows = await db.execute(
            select(ProductImportRow)
            .where(
                ProductImportRow.company_id
                == int(actor.company_id),
                ProductImportRow.job_id
                == job_id,
                ProductImportRow.status.in_(
                    (
                        RowStatus.INVALID.value,
                        RowStatus.IMPORT_FAILED.value,
                    )
                ),
            )
            .order_by(
                ProductImportRow.row_number.asc()
            )
            .limit(50)
        )
        rows = list(
            result_rows.scalars().fetchmany(
                50
            )
        )
        errors = [
            {
                "row_number": int(
                    row.row_number
                ),
                "code": row.error_code,
                "message": row.error_message,
            }
            for row in rows
        ]

    result = _job_payload(
        job,
        progress,
    )
    result["errors"] = errors
    return result


@router.get("/imports/{job_id}/errors")
async def get_product_import_errors(
    job_id: UUID,
    after_row: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(
        db,
        actor,
        "catalog.read",
    )
    job_exists = await db.scalar(
        select(ProductImportJob.id).where(
            ProductImportJob.company_id == int(actor.company_id),
            ProductImportJob.id == job_id,
        )
    )
    if job_exists is None:
        raise HTTPException(
            404,
            detail={
                "code": "PRODUCT_IMPORT_NOT_FOUND",
                "message": "Import job was not found.",
                "context": {},
            },
        )

    rows = list(
        (
            await db.scalars(
                select(ProductImportRow)
                .where(
                    ProductImportRow.company_id == int(actor.company_id),
                    ProductImportRow.job_id == job_id,
                    ProductImportRow.status.in_(
                        (
                            RowStatus.INVALID.value,
                            RowStatus.IMPORT_FAILED.value,
                        )
                    ),
                    ProductImportRow.row_number > int(after_row),
                )
                .order_by(ProductImportRow.row_number.asc())
                .limit(limit + 1)
            )
        ).all()
    )
    page = rows[:limit]
    has_more = len(rows) > limit
    return {
        "items": [
            {
                "row_number": int(row.row_number),
                "code": row.error_code,
                "message": row.error_message,
            }
            for row in page
        ],
        "next_after_row": (
            int(page[-1].row_number)
            if has_more and page
            else None
        ),
    }


@router.get(
    "/imports/{job_id}/lineage",
)
async def get_product_import_lineage(
    job_id: UUID,
    after_row_number: int = Query(
        0,
        ge=0,
    ),
    limit: int = Query(
        100,
        ge=1,
        le=200,
    ),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(
        db,
        actor,
    )

    lineage = await get_import_lineage(
        company_id=int(
            actor.company_id
        ),
        job_id=job_id,
        after_row_number=
            after_row_number,
        limit=limit,
    )
    if lineage is None:
        raise HTTPException(
            404,
            detail={
                "code":
                    "PRODUCT_IMPORT_NOT_FOUND",
                "message":
                    "Import job was not found.",
                "context": {},
            },
        )
    return lineage


@router.get(
    "/imports/{job_id}/correction",
)
async def get_product_import_correction(
    job_id: UUID,
    file_format: str = Query(
        "xlsx",
        alias="format",
        pattern="^(csv|xlsx)$",
    ),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(
        db,
        actor,
    )

    job_exists = await db.scalar(
        select(
            ProductImportJob.id
        ).where(
            ProductImportJob.company_id
            == int(
                actor.company_id
            ),
            ProductImportJob.id
            == job_id,
        )
    )
    if job_exists is None:
        raise HTTPException(
            404,
            detail={
                "code":
                    "PRODUCT_IMPORT_NOT_FOUND",
                "message":
                    "Import job was not found.",
                "context": {},
            },
        )

    try:
        artifact = (
            await build_correction_artifact(
                company_id=int(
                    actor.company_id
                ),
                job_id=job_id,
                file_format=
                    file_format,
            )
        )
    except ProductImportTerminalError as exc:
        raise HTTPException(
            409,
            detail={
                "code":
                    "PRODUCT_IMPORT_CORRECTION_UNAVAILABLE",
                "message":
                    str(
                        exc
                    ),
                "context": {},
            },
        ) from exc

    return {
        "file_name":
            artifact.file_name,
        "content_type":
            artifact.content_type,
        "content_base64":
            base64.b64encode(
                artifact.payload
            ).decode(
                "ascii"
            ),
        "row_count":
            int(
                artifact.row_count
            ),
    }


@router.post(
    "/imports/{job_id}/correction",
    status_code=202,
)
async def upload_product_import_correction(
    job_id: UUID,
    request_id: UUID = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(
        db,
        actor,
    )

    job_exists = await db.scalar(
        select(
            ProductImportJob.id
        ).where(
            ProductImportJob.company_id
            == int(
                actor.company_id
            ),
            ProductImportJob.id
            == job_id,
        )
    )
    if job_exists is None:
        raise HTTPException(
            404,
            detail={
                "code":
                    "PRODUCT_IMPORT_NOT_FOUND",
                "message":
                    "Import job was not found.",
                "context": {},
            },
        )

    file_name = str(
        file.filename
        or ""
    ).strip()
    suffix = (
        "."
        + file_name.lower().rsplit(
            ".",
            1,
        )[-1]
        if "." in file_name
        else ""
    )
    if suffix not in _ALLOWED_IMPORT_SUFFIXES:
        raise HTTPException(
            422,
            detail={
                "code":
                    "PRODUCT_IMPORT_CORRECTION_FILE_INVALID",
                "message":
                    "Correction file must be CSV or XLSX.",
                "context": {},
            },
        )

    payload = await file.read(
        MAX_IMPORT_FILE_BYTES
        + 1
    )
    if not payload:
        raise HTTPException(
            422,
            detail={
                "code":
                    "PRODUCT_IMPORT_CORRECTION_FILE_EMPTY",
                "message":
                    "Correction file is empty.",
                "context": {},
            },
        )
    if len(
        payload
    ) > MAX_IMPORT_FILE_BYTES:
        raise HTTPException(
            413,
            detail={
                "code":
                    "PRODUCT_IMPORT_FILE_TOO_LARGE",
                "message":
                    "Import file exceeds the 8 MB limit.",
                "context": {},
            },
        )

    try:
        result = (
            await apply_correction_upload(
                company_id=int(
                    actor.company_id
                ),
                actor_id=int(
                    actor.id
                ),
                job_id=job_id,
                request_id=
                    request_id,
                file_name=
                    file_name,
                payload=payload,
            )
        )
    except ProductImportTerminalError as exc:
        raise HTTPException(
            422,
            detail={
                "code":
                    "PRODUCT_IMPORT_CORRECTION_INVALID",
                "message":
                    str(
                        exc
                    ),
                "context": {},
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            409,
            detail={
                "code":
                    "PRODUCT_IMPORT_CORRECTION_CONFLICT",
                "message":
                    str(
                        exc
                    ),
                "context": {},
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            503,
            detail={
                "code":
                    "PRODUCT_IMPORT_QUEUE_UNAVAILABLE",
                "message":
                    "Correction could not be queued.",
                "context": {},
            },
        ) from exc

    return {
        **result,
        "message":
            "Correction accepted for revalidation.",
    }


@router.put(
    "/imports/{job_id}/mapping",
    status_code=202,
)
async def set_product_import_mapping(
    job_id: UUID,
    payload: ImportMappingRequest,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(db, actor)

    job = await db.scalar(
        select(ProductImportJob).where(
            ProductImportJob.company_id
            == int(actor.company_id),
            ProductImportJob.id == job_id,
        )
    )
    if job is None:
        raise HTTPException(
            404,
            detail={
                "code": "PRODUCT_IMPORT_NOT_FOUND",
                "message": "Import job was not found.",
                "context": {},
            },
        )

    headers = set(
        job.detected_headers or []
    )
    for field, header in payload.mapping.items():
        if (
            field not in _CANONICAL_MAPPING_FIELDS
            or header not in headers
        ):
            raise HTTPException(
                422,
                detail={
                    "code": "PRODUCT_IMPORT_MAPPING_INVALID",
                    "message": "Column mapping is invalid.",
                    "context": {},
                },
            )

    if not payload.mapping.get("name"):
        raise HTTPException(
            422,
            detail={
                "code": "PRODUCT_IMPORT_MAPPING_NAME_REQUIRED",
                "message": "Map the product-name column.",
                "context": {},
            },
        )
    if not (
        payload.mapping.get("package_price")
        or payload.mapping.get("unit_price")
    ):
        raise HTTPException(
            422,
            detail={
                "code": "PRODUCT_IMPORT_MAPPING_PRICE_REQUIRED",
                "message": "Map package_price or unit_price.",
                "context": {},
            },
        )

    try:
        status = await requeue_import(
            company_id=int(actor.company_id),
            job_id=job_id,
            mapping=payload.mapping,
        )
    except ValueError as exc:
        raise HTTPException(
            409,
            detail={
                "code": "PRODUCT_IMPORT_MAPPING_CONFLICT",
                "message": str(exc),
                "context": {},
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            503,
            detail={
                "code": "PRODUCT_IMPORT_QUEUE_UNAVAILABLE",
                "message": "Import could not be requeued.",
                "context": {},
            },
        ) from exc

    return {
        "job_id": str(job_id),
        "status": str(status),
        "message": "Column mapping accepted.",
    }


@router.post(
    "/imports/{job_id}/retry",
    status_code=202,
)
async def retry_product_import(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(db, actor)

    job = await db.scalar(
        select(ProductImportJob).where(
            ProductImportJob.company_id
            == int(actor.company_id),
            ProductImportJob.id == job_id,
        )
    )
    if job is None:
        raise HTTPException(
            404,
            detail={
                "code": "PRODUCT_IMPORT_NOT_FOUND",
                "message": "Import job was not found.",
                "context": {},
            },
        )

    try:
        status = await retry_failed_import(
            company_id=int(actor.company_id),
            job_id=job_id,
        )
    except ValueError as exc:
        raise HTTPException(
            409,
            detail={
                "code": "PRODUCT_IMPORT_NOT_RETRYABLE",
                "message": str(exc),
                "context": {},
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            503,
            detail={
                "code": "PRODUCT_IMPORT_QUEUE_UNAVAILABLE",
                "message": "Import could not be retried.",
                "context": {},
            },
        ) from exc

    return {
        "job_id": str(job_id),
        "status": str(status),
        "message": "Import retry accepted.",
    }
