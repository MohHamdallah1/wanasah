"""Version-stable HTTP contracts for Product Import.

These models describe the existing /simple-products import payloads. They do
not own mapping/business validation; application/domain services do.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
