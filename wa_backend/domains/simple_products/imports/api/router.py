"""HTTP transport adapter for Product Import.

This router preserves the existing /simple-products import URLs while keeping
Product Import transport concerns inside the owning capability module.
"""
from __future__ import annotations

import base64
import logging
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from domains.product_tracking import ProductTrackingError
from domains.simple_products.imports.api.schemas import (
    ImportActionResponse,
    ImportCorrectionDownloadResponse,
    ImportCorrectionUploadResponse,
    ImportCreateResponse,
    ImportErrorsResponse,
    ImportMappingRequest,
    ImportStatusResponse,
    ImportTemplateResponse,
    ImportWorkerReadinessResponse,
)
from domains.simple_products.imports.application.api_service import (
    apply_correction,
    cancel_import,
    create_import,
    download_correction,
    ensure_import_job_access,
    read_import_errors,
    read_import_status,
    retry_import,
    set_import_mapping,
)
from domains.simple_products.imports.application.audit_service import (
    get_import_lineage,
)
from domains.simple_products.imports.domain import (
    ProductImportTerminalError,
)
from domains.simple_products.imports.domain.admission import (
    ProductImportAdmissionDenied,
)
from domains.simple_products.imports.domain.errors import (
    user_safe_error_message,
)
from domains.simple_products.imports.infrastructure.content_security import (
    validate_source_content,
)
from domains.simple_products.imports.infrastructure.realtime_manager import (
    product_import_connection_manager,
)
from domains.simple_products.imports.infrastructure.runtime_monitor import (
    read_product_import_runtime_metrics,
)
from domains.simple_products.imports.infrastructure.template import (
    build_product_import_template,
)
from domains.simple_products.imports.infrastructure.upload_stream import (
    ProductImportUploadTooLarge,
    spool_upload_bounded,
)
from inventory_access import InventoryAccess
from models import Driver, ProductImportJob
from realtime.auth import (
    WebSocketAuthError,
    authenticate_websocket_user,
)
from realtime.ws_security import (
    receive_websocket_bearer,
    drain_authenticated_websocket,
)
from workers.tenant import tenant_session


router = APIRouter(
    prefix="/simple-products",
    tags=["Simple Products"],
)

MAX_IMPORT_FILE_BYTES = 8 * 1024 * 1024
_ALLOWED_IMPORT_SUFFIXES = {".csv", ".xlsx"}


logger = logging.getLogger(
    "wanasah_logger"
)


def _correlation_id(
    request: Request,
) -> str:
    return str(
        getattr(
            request.state,
            "request_id",
            "unknown",
        )
        or "unknown"
    )


def _error_context(
    request: Request,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        **dict(
            context
            or {}
        ),
        "correlation_id":
            _correlation_id(
                request
            ),
    }


def _log_api_exception(
    request: Request,
    exc: BaseException,
    *,
    code: str,
    job_id: UUID | None = None,
) -> None:
    logger.error(
        "PRODUCT_IMPORT_API_FAILURE "
        "correlation_id=%s code=%s job_id=%s",
        _correlation_id(
            request
        ),
        str(
            code
        ),
        (
            str(
                job_id
            )
            if job_id
            is not None
            else "-"
        ),
        exc_info=(
            type(
                exc
            ),
            exc,
            exc.__traceback__,
        ),
    )


def _raise_terminal_http(
    request: Request,
    exc: ProductImportTerminalError,
    *,
    job_id: UUID | None = None,
    status_code: int | None = None,
    code: str | None = None,
) -> None:
    resolved_code = str(
        code
        or exc.code
    )
    resolved_status = (
        int(
            status_code
        )
        if status_code
        is not None
        else (
            404
            if resolved_code
            == "PRODUCT_IMPORT_NOT_FOUND"
            else 409
            if resolved_code
            in {
                "PRODUCT_IMPORT_CORRECTION_UNAVAILABLE",
                "PRODUCT_IMPORT_NOT_CANCELLABLE",
            }
            else 422
        )
    )
    _log_api_exception(
        request,
        exc,
        code=resolved_code,
        job_id=job_id,
    )
    raise HTTPException(
        resolved_status,
        detail={
            "code":
                resolved_code,
            "message":
                (
                    user_safe_error_message(
                        resolved_code
                    )
                    if code
                    is not None
                    else exc.user_message
                ),
            "context":
                _error_context(
                    request,
                    exc.context,
                ),
        },
    ) from exc


async def _parse_new_import_upload(
    request: Request,
    file: UploadFile,
):
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
        content_type = (
            validate_source_content(
                file_name,
                bounded_upload.stream,
            )
        )
    except ProductImportTerminalError as exc:
        bounded_upload.close()
        _raise_terminal_http(
            request,
            exc,
        )

    return (
        file_name,
        content_type,
        bounded_upload,
    )


async def _parse_correction_upload(
    request: Request,
    *,
    job_id: UUID,
    file: UploadFile,
) -> tuple[str, bytes]:
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
        await file.close()
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

    try:
        payload = await file.read(
            MAX_IMPORT_FILE_BYTES
            + 1
        )
    finally:
        await file.close()

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
        validate_source_content(
            file_name,
            payload,
        )
    except ProductImportTerminalError as exc:
        _raise_terminal_http(
            request,
            exc,
            job_id=job_id,
        )

    return (
        file_name,
        payload,
    )


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


@router.get(
    "/import-template",
    response_model=ImportTemplateResponse,
)
async def get_product_import_template(
    locale: str = Query(
        "ar",
        min_length=2,
        max_length=35,
        pattern=(
            "^[A-Za-z0-9]+"
            "(?:[-_][A-Za-z0-9]+)*$"
        ),
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


@router.get(
    "/import-worker/readiness",
    response_model=ImportWorkerReadinessResponse,
)
async def get_product_import_worker_readiness(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(
        db,
        actor,
    )
    try:
        metrics = (
            await read_product_import_runtime_metrics()
        )
    except Exception as exc:
        _log_api_exception(
            request,
            exc,
            code=
                "PRODUCT_IMPORT_WORKER_HEALTH_UNAVAILABLE",
        )
        raise HTTPException(
            503,
            detail={
                "code":
                    "PRODUCT_IMPORT_WORKER_HEALTH_UNAVAILABLE",
                "message":
                    "Product Import worker readiness could not be determined.",
                "context":
                    _error_context(
                        request
                    ),
            },
        ) from exc

    return {
        "ready":
            bool(
                metrics.ready
            ),
        "status": (
            "READY"
            if metrics.ready
            else "UNAVAILABLE"
        ),
    }


@router.websocket("/imports/{job_id}/ws")
async def product_import_progress_websocket(
    websocket: WebSocket,
    job_id: UUID,
):
    token = await receive_websocket_bearer(websocket)
    if token is None:
        return

    try:
        identity = (
            await authenticate_websocket_user(
                token
            )
        )
        async with tenant_session(
            identity.company_id
        ) as db:
            actor = await db.scalar(
                select(Driver).where(
                    Driver.company_id
                    == int(
                        identity.company_id
                    ),
                    Driver.id
                    == int(
                        identity.driver_id
                    ),
                    Driver.is_active.is_(
                        True
                    ),
                )
            )
            if actor is None:
                raise WebSocketAuthError(
                    "inactive websocket actor"
                )

            await InventoryAccess(
                db,
                actor,
            ).require(
                "catalog.read",
                any_location=True,
            )
            job_exists = await db.scalar(
                select(
                    ProductImportJob.id
                ).where(
                    ProductImportJob.company_id
                    == int(
                        identity.company_id
                    ),
                    ProductImportJob.id
                    == job_id,
                )
            )
            if job_exists is None:
                raise WebSocketAuthError(
                    "product import websocket job scope denied"
                )
    except (
        WebSocketAuthError,
        HTTPException,
    ):
        await websocket.close(
            code=1008
        )
        return

    connected = (
        await product_import_connection_manager.connect(
            websocket,
            company_id=int(
                identity.company_id
            ),
            job_id=job_id,
            already_accepted=True,
        )
    )
    if not connected:
        return

    try:
        await websocket.send_json({"event": "WS_AUTHENTICATED"})
        await drain_authenticated_websocket(
            websocket,
            token_expires_at=identity.token_expires_at,
        )
    finally:
        await product_import_connection_manager.disconnect(
            websocket,
            company_id=int(
                identity.company_id
            ),
            job_id=job_id,
        )


@router.post(
    "/imports",
    status_code=202,
    response_model=ImportCreateResponse,
)
async def create_product_import(
    request: Request,
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
    (
        file_name,
        content_type,
        bounded_upload,
    ) = await _parse_new_import_upload(
        request,
        file,
    )

    try:
        result = await create_import(
            db,
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
            default_lot_control_mode=
                default_lot_control_mode,
            default_expiry_control_mode=
                default_expiry_control_mode,
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
        _log_api_exception(
            request,
            exc,
            code=
                "PRODUCT_IMPORT_REQUEST_CONFLICT",
        )
        raise HTTPException(
            409,
            detail={
                "code":
                    "PRODUCT_IMPORT_REQUEST_CONFLICT",
                "message":
                    user_safe_error_message(
                        "PRODUCT_IMPORT_REQUEST_CONFLICT"
                    ),
                "context":
                    _error_context(
                        request
                    ),
            },
        ) from exc
    except Exception as exc:
        _log_api_exception(
            request,
            exc,
            code=
                "PRODUCT_IMPORT_QUEUE_UNAVAILABLE",
        )
        raise HTTPException(
            503,
            detail={
                "code":
                    "PRODUCT_IMPORT_QUEUE_UNAVAILABLE",
                "message":
                    user_safe_error_message(
                        "PRODUCT_IMPORT_QUEUE_UNAVAILABLE"
                    ),
                "context":
                    _error_context(
                        request
                    ),
            },
        ) from exc
    finally:
        bounded_upload.close()

    return ImportCreateResponse.model_validate(
        result
    )


@router.get(
    "/imports/{job_id}",
    response_model=ImportStatusResponse,
)
async def get_product_import(
    job_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(
        db,
        actor,
        "catalog.read",
    )
    try:
        result = await read_import_status(
            db,
            company_id=int(
                actor.company_id
            ),
            job_id=job_id,
        )
    except ProductImportTerminalError as exc:
        _raise_terminal_http(
            request,
            exc,
            job_id=job_id,
        )

    return ImportStatusResponse.model_validate(
        result
    )


@router.get(
    "/imports/{job_id}/errors",
    response_model=ImportErrorsResponse,
)
async def get_product_import_errors(
    job_id: UUID,
    request: Request,
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
    try:
        result = await read_import_errors(
            db,
            company_id=int(
                actor.company_id
            ),
            job_id=job_id,
            after_row=after_row,
            limit=limit,
        )
    except ProductImportTerminalError as exc:
        _raise_terminal_http(
            request,
            exc,
            job_id=job_id,
        )

    return ImportErrorsResponse.model_validate(
        result
    )


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
    response_model=
        ImportCorrectionDownloadResponse,
)
async def get_product_import_correction(
    job_id: UUID,
    request: Request,
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
    try:
        artifact = await download_correction(
            db,
            company_id=int(
                actor.company_id
            ),
            job_id=job_id,
            file_format=file_format,
        )
    except ProductImportTerminalError as exc:
        if (
            exc.code
            == "PRODUCT_IMPORT_NOT_FOUND"
        ):
            _raise_terminal_http(
                request,
                exc,
                job_id=job_id,
            )
        _raise_terminal_http(
            request,
            exc,
            job_id=job_id,
            status_code=409,
            code=
                "PRODUCT_IMPORT_CORRECTION_UNAVAILABLE",
        )

    return ImportCorrectionDownloadResponse(
        file_name=
            artifact.file_name,
        content_type=
            artifact.content_type,
        content_base64=
            base64.b64encode(
                artifact.payload
            ).decode(
                "ascii"
            ),
        row_count=int(
            artifact.row_count
        ),
    )


@router.post(
    "/imports/{job_id}/correction",
    status_code=202,
    response_model=
        ImportCorrectionUploadResponse,
    response_model_exclude_none=True,
)
async def upload_product_import_correction(
    job_id: UUID,
    request: Request,
    request_id: UUID = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(
        db,
        actor,
    )
    try:
        await ensure_import_job_access(
            db,
            company_id=int(
                actor.company_id
            ),
            job_id=job_id,
        )
    except ProductImportTerminalError as exc:
        _raise_terminal_http(
            request,
            exc,
            job_id=job_id,
        )

    (
        file_name,
        payload,
    ) = await _parse_correction_upload(
        request,
        job_id=job_id,
        file=file,
    )

    try:
        result = await apply_correction(
            db,
            company_id=int(
                actor.company_id
            ),
            actor_id=int(
                actor.id
            ),
            job_id=job_id,
            request_id=request_id,
            file_name=file_name,
            payload=payload,
        )
    except ProductImportTerminalError as exc:
        if (
            exc.code
            == "PRODUCT_IMPORT_NOT_FOUND"
        ):
            _raise_terminal_http(
                request,
                exc,
                job_id=job_id,
            )
        _raise_terminal_http(
            request,
            exc,
            job_id=job_id,
            status_code=422,
            code=
                "PRODUCT_IMPORT_CORRECTION_INVALID",
        )
    except ValueError as exc:
        _log_api_exception(
            request,
            exc,
            code=
                "PRODUCT_IMPORT_CORRECTION_CONFLICT",
            job_id=job_id,
        )
        raise HTTPException(
            409,
            detail={
                "code":
                    "PRODUCT_IMPORT_CORRECTION_CONFLICT",
                "message":
                    "The correction request conflicts with the current import state.",
                "context":
                    _error_context(
                        request
                    ),
            },
        ) from exc
    except Exception as exc:
        _log_api_exception(
            request,
            exc,
            code=
                "PRODUCT_IMPORT_QUEUE_UNAVAILABLE",
            job_id=job_id,
        )
        raise HTTPException(
            503,
            detail={
                "code":
                    "PRODUCT_IMPORT_QUEUE_UNAVAILABLE",
                "message":
                    user_safe_error_message(
                        "PRODUCT_IMPORT_QUEUE_UNAVAILABLE"
                    ),
                "context":
                    _error_context(
                        request
                    ),
            },
        ) from exc

    return ImportCorrectionUploadResponse.model_validate(
        result
    )


@router.put(
    "/imports/{job_id}/mapping",
    status_code=202,
    response_model=ImportActionResponse,
)
async def set_product_import_mapping(
    job_id: UUID,
    payload: ImportMappingRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(
        db,
        actor,
    )
    try:
        result = await set_import_mapping(
            db,
            company_id=int(
                actor.company_id
            ),
            job_id=job_id,
            mapping=payload.mapping,
        )
    except ProductImportTerminalError as exc:
        _raise_terminal_http(
            request,
            exc,
            job_id=job_id,
        )
    except ValueError as exc:
        _log_api_exception(
            request,
            exc,
            code=
                "PRODUCT_IMPORT_MAPPING_CONFLICT",
            job_id=job_id,
        )
        raise HTTPException(
            409,
            detail={
                "code":
                    "PRODUCT_IMPORT_MAPPING_CONFLICT",
                "message":
                    user_safe_error_message(
                        "PRODUCT_IMPORT_MAPPING_CONFLICT"
                    ),
                "context":
                    _error_context(
                        request
                    ),
            },
        ) from exc
    except Exception as exc:
        _log_api_exception(
            request,
            exc,
            code=
                "PRODUCT_IMPORT_QUEUE_UNAVAILABLE",
            job_id=job_id,
        )
        raise HTTPException(
            503,
            detail={
                "code":
                    "PRODUCT_IMPORT_QUEUE_UNAVAILABLE",
                "message":
                    user_safe_error_message(
                        "PRODUCT_IMPORT_QUEUE_UNAVAILABLE"
                    ),
                "context":
                    _error_context(
                        request
                    ),
            },
        ) from exc

    return ImportActionResponse.model_validate(
        result
    )


@router.post(
    "/imports/{job_id}/cancel",
    status_code=202,
    response_model=ImportActionResponse,
)
async def cancel_product_import(
    job_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(
        db,
        actor,
    )
    try:
        result = await cancel_import(
            db,
            company_id=int(
                actor.company_id
            ),
            job_id=job_id,
        )
    except ProductImportTerminalError as exc:
        _raise_terminal_http(
            request,
            exc,
            job_id=job_id,
        )

    return ImportActionResponse.model_validate(
        result
    )


@router.post(
    "/imports/{job_id}/retry",
    status_code=202,
    response_model=ImportActionResponse,
)
async def retry_product_import(
    job_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(
        db,
        actor,
    )
    try:
        result = await retry_import(
            db,
            company_id=int(
                actor.company_id
            ),
            job_id=job_id,
        )
    except ProductImportTerminalError as exc:
        _raise_terminal_http(
            request,
            exc,
            job_id=job_id,
        )
    except ValueError as exc:
        _log_api_exception(
            request,
            exc,
            code=
                "PRODUCT_IMPORT_NOT_RETRYABLE",
            job_id=job_id,
        )
        raise HTTPException(
            409,
            detail={
                "code":
                    "PRODUCT_IMPORT_NOT_RETRYABLE",
                "message":
                    user_safe_error_message(
                        "PRODUCT_IMPORT_NOT_RETRYABLE"
                    ),
                "context":
                    _error_context(
                        request
                    ),
            },
        ) from exc
    except Exception as exc:
        _log_api_exception(
            request,
            exc,
            code=
                "PRODUCT_IMPORT_QUEUE_UNAVAILABLE",
            job_id=job_id,
        )
        raise HTTPException(
            503,
            detail={
                "code":
                    "PRODUCT_IMPORT_QUEUE_UNAVAILABLE",
                "message":
                    user_safe_error_message(
                        "PRODUCT_IMPORT_QUEUE_UNAVAILABLE"
                    ),
                "context":
                    _error_context(
                        request
                    ),
            },
        ) from exc

    return ImportActionResponse.model_validate(
        result
    )
