"""Correction artifacts and correction-upload parsing for Product Import."""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from io import BytesIO, StringIO
from typing import Any
from uuid import UUID

from openpyxl import Workbook

from domains.simple_products.imports.application.state_machine import (
    JobStatus,
)
from domains.simple_products.imports.domain import (
    ProductImportTerminalError,
)
from domains.simple_products.imports.infrastructure.parsers import (
    open_source,
)
from domains.simple_products.imports.infrastructure.correction_repository import (
    apply_correction_and_requeue,
)
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    fetch_failed_rows_batch,
    load_job,
    open_tenant_session,
)


CORRECTION_IDENTITY_HEADER = (
    "__wanasah_row_identity"
)
CORRECTION_ROW_NUMBER_HEADER = (
    "__wanasah_original_row"
)
CORRECTION_ERROR_CODE_HEADER = (
    "__wanasah_error_code"
)
CORRECTION_ERROR_MESSAGE_HEADER = (
    "__wanasah_error_message"
)
CORRECTION_META_HEADERS = (
    CORRECTION_IDENTITY_HEADER,
    CORRECTION_ROW_NUMBER_HEADER,
    CORRECTION_ERROR_CODE_HEADER,
    CORRECTION_ERROR_MESSAGE_HEADER,
)
CORRECTION_BATCH_SIZE = 1000


@dataclass(frozen=True, slots=True)
class ProductImportCorrectionArtifact:
    file_name: str
    content_type: str
    payload: bytes
    row_count: int


@dataclass(frozen=True, slots=True)
class ProductImportCorrectionPatch:
    row_identity: UUID
    raw_data: dict[str, Any]


def _artifact_headers(
    source_headers: list[str],
) -> list[str]:
    collisions = (
        set(source_headers)
        & set(
            CORRECTION_META_HEADERS
        )
    )
    if collisions:
        raise ProductImportTerminalError(
            "The original import uses a reserved correction column."
        )
    return [
        *CORRECTION_META_HEADERS,
        *source_headers,
    ]


def _artifact_values(
    row,
    source_headers: list[str],
) -> list[Any]:
    raw = dict(
        row.raw_data
        or {}
    )
    return [
        str(
            row.row_identity
        ),
        int(
            row.row_number
        ),
        (
            str(
                row.error_code
            )
            if row.error_code
            is not None
            else ""
        ),
        (
            str(
                row.error_message
            )
            if row.error_message
            is not None
            else ""
        ),
        *[
            raw.get(
                header
            )
            for header
            in source_headers
        ],
    ]


async def build_correction_artifact(
    *,
    company_id: int,
    job_id: UUID,
    file_format: str,
) -> ProductImportCorrectionArtifact:
    normalized_format = (
        str(
            file_format
        )
        .strip()
        .lower()
    )
    if normalized_format not in {
        "csv",
        "xlsx",
    }:
        raise ProductImportTerminalError(
            "Correction format must be csv or xlsx."
        )

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
                "Product import job was not found."
            )

        if str(
            job.status
        ) not in {
            JobStatus.VALIDATION_FAILED.value,
            JobStatus.COMPLETED_WITH_ERRORS.value,
        }:
            raise ProductImportTerminalError(
                "This import has no correction workflow in its current state."
            )

        source_headers = [
            str(
                header
            )
            for header
            in (
                job.detected_headers
                or []
            )
        ]
        headers = _artifact_headers(
            source_headers
        )

        if normalized_format == "csv":
            stream = StringIO(
                newline=""
            )
            writer = csv.writer(
                stream
            )
            writer.writerow(
                headers
            )
            workbook = None
            sheet = None
        else:
            stream = None
            writer = None
            workbook = Workbook(
                write_only=True
            )
            sheet = workbook.create_sheet(
                "Corrections"
            )
            sheet.append(
                headers
            )

        after_row_number = 0
        row_count = 0
        while True:
            rows = await fetch_failed_rows_batch(
                db,
                company_id=company_id,
                job_id=job_id,
                after_row_number=
                    after_row_number,
                limit=
                    CORRECTION_BATCH_SIZE,
            )
            if not rows:
                break

            for row in rows:
                values = _artifact_values(
                    row,
                    source_headers,
                )
                if writer is not None:
                    writer.writerow(
                        values
                    )
                else:
                    assert sheet is not None
                    sheet.append(
                        values
                    )
                row_count += 1

            after_row_number = int(
                rows[
                    -1
                ].row_number
            )

        if row_count == 0:
            raise ProductImportTerminalError(
                "This import has no failed rows to correct."
            )

        if normalized_format == "csv":
            assert stream is not None
            payload = (
                "\ufeff"
                + stream.getvalue()
            ).encode(
                "utf-8"
            )
            content_type = (
                "text/csv; charset=utf-8"
            )
            file_name = (
                f"product-import-{job_id}-correction.csv"
            )
        else:
            assert workbook is not None
            output = BytesIO()
            workbook.save(
                output
            )
            workbook.close()
            payload = output.getvalue()
            content_type = (
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            )
            file_name = (
                f"product-import-{job_id}-correction.xlsx"
            )

        return ProductImportCorrectionArtifact(
            file_name=file_name,
            content_type=content_type,
            payload=payload,
            row_count=row_count,
        )
    finally:
        await close_tenant_session(
            token,
            db,
        )


def parse_correction_payload(
    *,
    file_name: str,
    payload: bytes,
    source_headers: list[str],
) -> list[ProductImportCorrectionPatch]:
    expected_headers = set(
        _artifact_headers(
            source_headers
        )
    )
    patches: list[
        ProductImportCorrectionPatch
    ] = []
    seen: set[UUID] = set()

    with open_source(
        file_name,
        payload,
    ) as source:
        actual_headers = set(
            source.headers
        )
        if actual_headers != expected_headers:
            raise ProductImportTerminalError(
                "Correction file columns do not match the generated correction artifact."
            )

        for parsed in source.rows:
            raw = dict(
                parsed.raw
            )
            token_text = str(
                raw.get(
                    CORRECTION_IDENTITY_HEADER,
                    "",
                )
                or ""
            ).strip()
            try:
                row_identity = UUID(
                    token_text
                )
            except ValueError as exc:
                raise ProductImportTerminalError(
                    "Correction file contains an invalid row identity."
                ) from exc

            if row_identity in seen:
                raise ProductImportTerminalError(
                    "Correction file contains a duplicate row identity."
                )
            seen.add(
                row_identity
            )

            patches.append(
                ProductImportCorrectionPatch(
                    row_identity=
                        row_identity,
                    raw_data={
                        header:
                            raw.get(
                                header
                            )
                        for header
                        in source_headers
                    },
                )
            )

    if not patches:
        raise ProductImportTerminalError(
            "Correction file contains no rows."
        )

    return patches


def correction_request_hash(
    *,
    job_id: UUID,
    payload: bytes,
) -> str:
    digest = hashlib.sha256()
    digest.update(
        str(
            job_id
        ).encode(
            "ascii"
        )
    )
    digest.update(
        b"\0"
    )
    digest.update(
        payload
    )
    return digest.hexdigest()


async def apply_correction_upload(
    *,
    company_id: int,
    actor_id: int,
    job_id: UUID,
    request_id: UUID,
    file_name: str,
    payload: bytes,
) -> dict[str, object]:
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
                "Product import job was not found."
            )
        source_headers = [
            str(
                header
            )
            for header
            in (
                job.detected_headers
                or []
            )
        ]
    finally:
        await close_tenant_session(
            token,
            db,
        )

    patches = parse_correction_payload(
        file_name=file_name,
        payload=payload,
        source_headers=
            source_headers,
    )
    request_hash = (
        correction_request_hash(
            job_id=job_id,
            payload=payload,
        )
    )

    result = await apply_correction_and_requeue(
        company_id=company_id,
        actor_id=actor_id,
        job_id=job_id,
        request_id=request_id,
        request_hash=request_hash,
        corrections=[
            {
                "row_identity":
                    patch.row_identity,
                "raw_data":
                    patch.raw_data,
            }
            for patch
            in patches
        ],
    )
    return dict(
        result
    )
