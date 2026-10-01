"""Version-stable HTTP contracts for Product Import.

These models describe the existing /simple-products import payloads. They do
not own mapping/business validation; application/domain services do.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator,
)
from domains.simple_products.imports.domain.inline_correction import MAX_INLINE_CORRECTION_ROWS


class StrictImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImportMappingRequest(StrictImportRequest):
    mapping: dict[str, str]


class ImportErrorItem(BaseModel):
    row_number: int
    code: str | None = None
    field: str | None = None
    message: str


class ImportErrorsResponse(BaseModel):
    items: list[ImportErrorItem] = Field(default_factory=list)
    next_after_row: int | None = None


class ImportTemplateResponse(BaseModel):
    file_name: str
    content_type: str
    content_base64: str


class ImportWorkerReadinessResponse(BaseModel):
    ready: bool
    status: str


class ImportCreateResponse(BaseModel):
    job_id: str
    status: str
    replayed: bool
    default_lot_control_mode: str
    default_expiry_control_mode: str
    message: str


class ImportStatusResponse(BaseModel):
    job_id: str
    status: str
    file_name: str
    total_rows: int
    processed_rows: int
    valid_rows: int
    failed_rows: int
    imported_rows: int
    invalid_rows: int
    import_failed_rows: int
    pending_rows: int
    detected_headers: list[str]
    suggested_mapping: dict[str, str]
    column_mapping: dict[str, str]
    default_lot_control_mode: str
    default_expiry_control_mode: str
    error_summary: dict[str, Any]
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    errors: list[ImportErrorItem] = Field(default_factory=list)


class ImportActionResponse(BaseModel):
    job_id: str
    status: str
    message: str


class ImportCorrectionDownloadResponse(BaseModel):
    file_name: str
    content_type: str
    content_base64: str
    row_count: int


class ImportCorrectionUploadResponse(BaseModel):
    """Stable known correction fields; preserves existing extra metadata."""

    model_config = ConfigDict(extra="allow")

    message: str
    replayed: bool | None = None
    job_id: str | None = None
    status: str | None = None
    corrected_rows: int | None = None


# Inline correction is additive: the existing file/error DTOs stay unchanged.

class ImportCorrectionRowPatch(StrictImportRequest):
    row_identity: UUID
    expected_version: StrictInt = Field(ge=1)
    # Literal text/null mirrors correction-file cells and preserves barcode zeros.
    values: dict[str, StrictStr | None] = Field(min_length=1, max_length=10)


class ImportCorrectionRowsRequest(StrictImportRequest):
    request_id: UUID
    expected_job_version: StrictInt = Field(ge=1)
    rows: list[ImportCorrectionRowPatch] = Field(
        min_length=1, max_length=MAX_INLINE_CORRECTION_ROWS,
    )

    @model_validator(mode="after")
    def unique_rows(self):
        identities = [row.row_identity for row in self.rows]
        if len(identities) != len(set(identities)):
            raise ValueError("Duplicate correction row identities.")
        return self


class ImportCorrectionRow(BaseModel):
    row_identity: UUID
    row_number: int
    version: int
    status: str
    values: dict[str, StrictStr | StrictInt | StrictFloat | StrictBool | None]
    errors: list[ImportErrorItem]
    editable: bool
    unavailable_reason: str | None = None


class ImportCorrectionRowsResponse(BaseModel):
    job_id: UUID
    job_version: int
    status: str
    fields: list[str]
    items: list[ImportCorrectionRow]
    next_after_row: int | None = None


def inline_correction_request_schema() -> dict[str, Any]:
    """Publish the typed body while runtime parsing stays bounded and authorized."""
    schema = ImportCorrectionRowsRequest.model_json_schema()
    definitions = schema.pop("$defs", {})
    schema["properties"]["rows"]["items"] = definitions["ImportCorrectionRowPatch"]
    return schema
