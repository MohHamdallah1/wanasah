"""Correction artifacts and correction-upload parsing for Product Import."""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from io import BytesIO, StringIO
from typing import Any
from uuid import UUID

from openpyxl import Workbook

from domains.simple_products.imports.domain.inline_correction import (
    MAX_INLINE_CORRECTION_BYTES, MAX_INLINE_CORRECTION_ROWS, InlineCorrectionError,
    correction_details_expired,
)

from domains.simple_products.imports.application.state_machine import (
    JobStatus,
)
from domains.simple_products.imports.domain import (
    ProductImportTerminalError,
    SOURCE_CELL_META_KEY,
    source_cell_metadata,
)
from domains.simple_products.imports.domain.errors import (
    import_error_field,
    user_safe_row_error_message,
)
from domains.simple_products.imports.domain.localization import (
    resolve_import_locale_pack,
)
from domains.simple_products.imports.infrastructure.parsers import (
    MAX_IMPORT_COLUMNS,
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


# Plain, language-neutral export column names. Stable row identities remain
# mandatory for same-job correction; brand names never appear in new files.
CORRECTION_IDENTITY_HEADER = "row_identity"
CORRECTION_ROW_NUMBER_HEADER = "original_row"
CORRECTION_ERROR_CODE_HEADER = "error_code"
CORRECTION_ERROR_FIELD_HEADER = "error_field"
CORRECTION_ERROR_MESSAGE_HEADER = "error_message"
CORRECTION_META_HEADERS = (
    CORRECTION_IDENTITY_HEADER,
    CORRECTION_ROW_NUMBER_HEADER,
    CORRECTION_ERROR_CODE_HEADER,
    CORRECTION_ERROR_FIELD_HEADER,
    CORRECTION_ERROR_MESSAGE_HEADER,
)
# Compatibility read path for correction files downloaded before this change.
# Never produce these branded headers in new CSV/XLSX exports.
LEGACY_CORRECTION_META_HEADERS = tuple(
    "__wanasah_" + name for name in CORRECTION_META_HEADERS
)
LEGACY_CORRECTION_IDENTITY_HEADER = LEGACY_CORRECTION_META_HEADERS[0]

_FORMULA_PREFIXES = (
    "=",
    "+",
    "-",
    "@",
)


def sanitize_spreadsheet_cell(
    value: Any,
) -> Any:
    """Prevent CSV/XLSX formula execution while preserving ordinary values."""
    if not isinstance(
        value,
        str,
    ):
        return value
    probe = value.lstrip(
        " \t\r\n"
    )
    if (
        probe.startswith(
            _FORMULA_PREFIXES
        )
        or value.startswith(
            (
                "\t",
                "\r",
            )
        )
    ):
        return "'" + value
    return value


def _restore_sanitized_cell(
    value: Any,
) -> Any:
    if (
        isinstance(
            value,
            str,
        )
        and value.startswith(
            "'"
        )
    ):
        candidate = value[
            1:
        ]
        probe = candidate.lstrip(
            " \t\r\n"
        )
        if (
            probe.startswith(
                _FORMULA_PREFIXES
            )
            or candidate.startswith(
                (
                    "\t",
                    "\r",
                )
            )
        ):
            return candidate
    return value

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
        & set((
            *CORRECTION_META_HEADERS,
            *LEGACY_CORRECTION_META_HEADERS,
        ))
    )
    if collisions:
        raise ProductImportTerminalError(
            "The original import uses a reserved correction column."
        )
    safe_source_headers = [
        str(
            sanitize_spreadsheet_cell(
                header
            )
        )
        for header in source_headers
    ]
    output_headers = [
        *CORRECTION_META_HEADERS,
        *safe_source_headers,
    ]
    if (
        len(
            output_headers
        )
        != len(
            set(
                output_headers
            )
        )
    ):
        raise ProductImportTerminalError(
            "Correction headers collide after spreadsheet sanitization."
        )
    return output_headers


def _artifact_values(
    row,
    source_headers: list[str],
    *,
    locale: str = "en",
) -> list[Any]:
    raw = dict(
        row.raw_data
        or {}
    )
    return [
        sanitize_spreadsheet_cell(
            str(
                row.row_identity
            )
        ),
        int(
            row.row_number
        ),
        sanitize_spreadsheet_cell(
            (
                str(
                    row.error_code
                )
                if row.error_code
                is not None
                else ""
            )
        ),
        sanitize_spreadsheet_cell(
            import_error_field(
                row.error_code
            )
            or ""
        ),
        sanitize_spreadsheet_cell(
            user_safe_row_error_message(
                row.error_code,
                locale=locale,
            )
        ),
        *[
            sanitize_spreadsheet_cell(
                raw.get(
                    header
                )
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
    locale: str = "en",
) -> ProductImportCorrectionArtifact:
    language = resolve_import_locale_pack(locale).locale
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

        if correction_details_expired(finished_at=job.finished_at, compacted_at=None):
            raise ProductImportTerminalError(
                "Correction source details have expired.",
                code="PRODUCT_IMPORT_CORRECTION_DETAILS_EXPIRED",
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
        after_row_number = 0
        row_count = 0
        expired_rows_seen = False
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
                if correction_details_expired(
                    finished_at=job.finished_at, compacted_at=row.compacted_at,
                ):
                    expired_rows_seen = True
                    continue
                if row_count == 0:
                    header_values = [sanitize_spreadsheet_cell(header) for header in headers]
                    if writer is not None:
                        writer.writerow(header_values)
                    else:
                        assert sheet is not None
                        sheet.append(header_values)
                values = _artifact_values(
                    row,
                    source_headers,
                    locale=language,
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
            if expired_rows_seen:
                raise ProductImportTerminalError(
                    "All rejected row details have expired.",
                    code="PRODUCT_IMPORT_CORRECTION_DETAILS_EXPIRED",
                )
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
        max_columns=(
            MAX_IMPORT_COLUMNS
            + len(
                CORRECTION_META_HEADERS
            )
        ),
    ) as source:
        actual_headers = set(
            source.headers
        )
        legacy_headers = set((
            *LEGACY_CORRECTION_META_HEADERS,
            *(str(sanitize_spreadsheet_cell(h)) for h in source_headers),
        ))
        if actual_headers == expected_headers:
            identity_header = CORRECTION_IDENTITY_HEADER
        elif actual_headers == legacy_headers:
            identity_header = LEGACY_CORRECTION_IDENTITY_HEADER
        else:
            raise ProductImportTerminalError(
                "Correction file columns do not match the generated correction artifact."
            )

        for parsed in source.rows:
            raw = dict(
                parsed.raw
            )
            token_text = str(
                raw.get(
                    identity_header,
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

            corrected_raw: dict[str, Any] = {}
            cell_metadata: dict[str, dict[str, Any]] = {}
            for header in source_headers:
                safe_header = str(sanitize_spreadsheet_cell(header))
                corrected_raw[header] = _restore_sanitized_cell(raw.get(safe_header))
                metadata = source_cell_metadata(raw, safe_header)
                if metadata:
                    cell_metadata[header] = metadata
            if cell_metadata:
                corrected_raw[SOURCE_CELL_META_KEY] = cell_metadata
            patches.append(
                ProductImportCorrectionPatch(
                    row_identity=row_identity,
                    raw_data=corrected_raw,
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


async def apply_correction_cells(
    *,
    company_id: int,
    actor_id: int,
    job_id: UUID,
    request_id: UUID,
    expected_job_version: int,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    # Hash caller intent, not mutable stored row data. Replay remains valid after
    # revalidation, execution or retention has changed the job/rows.
    canonical = json.dumps(
        {
            "expected_job_version": expected_job_version,
            "rows": sorted(rows, key=lambda row: str(row["row_identity"])),
        },
        sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        default=str,
    ).encode("utf-8")
    if not rows or len(rows) > MAX_INLINE_CORRECTION_ROWS or len(canonical) > MAX_INLINE_CORRECTION_BYTES:
        raise InlineCorrectionError("PRODUCT_IMPORT_CORRECTION_ROWS_INVALID")
    return await apply_correction_and_requeue(
        company_id=company_id, actor_id=actor_id, job_id=job_id,
        request_id=request_id,
        request_hash=correction_request_hash(
            job_id=job_id, payload=b"inline-correction-v1\0" + canonical,
        ),
        corrections=None, inline_rows=rows, expected_job_version=expected_job_version,
    )
