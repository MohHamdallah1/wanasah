"""Canonical, user-safe Product Import error taxonomy."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


DEFAULT_TERMINAL_ERROR_CODE = (
    "PRODUCT_IMPORT_JOB_INVALID"
)

USER_SAFE_ERROR_MESSAGES: dict[str, str] = {
    "PRODUCT_IMPORT_JOB_INVALID":
        "The import could not be processed in its current state.",
    "PRODUCT_IMPORT_FAILED":
        "The import could not be completed.",
    "PRODUCT_IMPORT_SYSTEM_FAILURE":
        "Import processing failed because of a temporary system problem.",
    "PRODUCT_IMPORT_RETRYING":
        "Import processing was interrupted and will retry safely.",
    "PRODUCT_IMPORT_SOURCE_INVALID":
        "The import file is invalid or unsupported.",
    "PRODUCT_IMPORT_SOURCE_CORRUPT":
        "The import file is damaged or could not be read safely.",
    "PRODUCT_IMPORT_SOURCE_TYPE_MISMATCH":
        "The file content does not match its file type.",
    "PRODUCT_IMPORT_XLSX_UNSAFE":
        "The Excel file was rejected by file-safety checks.",
    "PRODUCT_IMPORT_CORRECTION_INVALID":
        "The correction file is invalid.",
    "PRODUCT_IMPORT_CORRECTION_UNAVAILABLE":
        "A correction file is not available for this import.",
    "PRODUCT_IMPORT_NOT_CANCELLABLE":
        "This import can no longer be cancelled.",
    "PRODUCT_IMPORT_NOT_FOUND":
        "Import job was not found.",
    "PRODUCT_IMPORT_NOT_RETRYABLE":
        "This import cannot be retried in its current state.",
    "PRODUCT_IMPORT_MAPPING_CONFLICT":
        "The import mapping changed and could not be applied.",
    "PRODUCT_IMPORT_REQUEST_CONFLICT":
        "This operation id was already used for different import input.",
    "PRODUCT_IMPORT_QUEUE_UNAVAILABLE":
        "Import processing is temporarily unavailable.",
    "IMPORT_ROW_INVALID":
        "This row contains invalid import data.",
}


def user_safe_error_message(
    code: str,
    *,
    fallback: str | None = None,
) -> str:
    return USER_SAFE_ERROR_MESSAGES.get(
        str(code),
        fallback or "The import could not be processed.",
    )


class ProductImportTerminalError(RuntimeError):
    """Deterministic job failure with a stable public contract.

    str(exc) is internal diagnostic detail. API callers must use code and
    user_message instead.
    """

    def __init__(
        self,
        technical_message: str,
        *,
        code: str = DEFAULT_TERMINAL_ERROR_CODE,
        user_message: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(str(technical_message))
        self.code = str(code)
        self.user_message = (
            str(user_message)
            if user_message is not None
            else user_safe_error_message(self.code)
        )
        self.context = dict(context or {})


class ProductImportRowValidationError(RuntimeError):
    """Deterministic validation failure attributable to one source row."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)


class ProductImportRowExecutionError(RuntimeError):
    """Deterministic execution failure attributable to one validated row."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)


class ImportFailureScope(str, Enum):
    ROW = "ROW"
    JOB = "JOB"


class ImportErrorKind(str, Enum):
    DETERMINISTIC_VALIDATION = "DETERMINISTIC_VALIDATION"
    DETERMINISTIC_ROW_EXECUTION = "DETERMINISTIC_ROW_EXECUTION"
    DETERMINISTIC_JOB = "DETERMINISTIC_JOB"
    TRANSIENT_SYSTEM = "TRANSIENT_SYSTEM"


@dataclass(frozen=True)
class ImportErrorClassification:
    kind: ImportErrorKind
    scope: ImportFailureScope
    retryable: bool
    code: str | None = None
    message: str | None = None

    @property
    def row_failure(self) -> bool:
        return self.scope is ImportFailureScope.ROW


def classify_import_error(exc: BaseException) -> ImportErrorClassification:
    if isinstance(exc, ProductImportRowValidationError):
        return ImportErrorClassification(
            kind=ImportErrorKind.DETERMINISTIC_VALIDATION,
            scope=ImportFailureScope.ROW,
            retryable=False,
            code=exc.code,
            message=exc.message,
        )
    if isinstance(exc, ProductImportRowExecutionError):
        return ImportErrorClassification(
            kind=ImportErrorKind.DETERMINISTIC_ROW_EXECUTION,
            scope=ImportFailureScope.ROW,
            retryable=False,
            code=exc.code,
            message=exc.message,
        )
    if isinstance(exc, ProductImportTerminalError):
        return ImportErrorClassification(
            kind=ImportErrorKind.DETERMINISTIC_JOB,
            scope=ImportFailureScope.JOB,
            retryable=False,
            code=exc.code,
            message=exc.user_message,
        )
    return ImportErrorClassification(
        kind=ImportErrorKind.TRANSIENT_SYSTEM,
        scope=ImportFailureScope.JOB,
        retryable=True,
        code="PRODUCT_IMPORT_SYSTEM_FAILURE",
        message=user_safe_error_message("PRODUCT_IMPORT_SYSTEM_FAILURE"),
    )


def runtime_failure_summary(
    *,
    message: str | None = None,
    final_attempt: bool,
    retryable: bool,
    resume_status: str,
    code: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, object]:
    """Build durable/public failure state without exception text."""
    del message
    resolved_code = (
        str(code)
        if final_attempt and code
        else (
            "PRODUCT_IMPORT_FAILED"
            if final_attempt
            else "PRODUCT_IMPORT_RETRYING"
        )
    )
    summary: dict[str, object] = {
        "code": resolved_code,
        "message": user_safe_error_message(resolved_code),
        "retryable": bool(retryable) if final_attempt else False,
        "resume_status": str(resume_status),
    }
    if correlation_id:
        summary["correlation_id"] = str(correlation_id)
    return summary
