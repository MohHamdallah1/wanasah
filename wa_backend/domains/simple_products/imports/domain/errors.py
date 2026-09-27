"""Canonical Product Import error taxonomy."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProductImportTerminalError(RuntimeError):
    """Deterministic job-level failure that must not be retried automatically."""


class ProductImportRowValidationError(
    RuntimeError
):
    """Deterministic validation failure attributable to one source row."""

    def __init__(
        self,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)


class ProductImportRowExecutionError(
    RuntimeError
):
    """Deterministic execution failure attributable to one validated row."""

    def __init__(
        self,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)


class ImportFailureScope(str, Enum):
    ROW = "ROW"
    JOB = "JOB"


class ImportErrorKind(str, Enum):
    DETERMINISTIC_VALIDATION = (
        "DETERMINISTIC_VALIDATION"
    )
    DETERMINISTIC_ROW_EXECUTION = (
        "DETERMINISTIC_ROW_EXECUTION"
    )
    DETERMINISTIC_JOB = (
        "DETERMINISTIC_JOB"
    )
    TRANSIENT_SYSTEM = (
        "TRANSIENT_SYSTEM"
    )


@dataclass(frozen=True)
class ImportErrorClassification:
    kind: ImportErrorKind
    scope: ImportFailureScope
    retryable: bool
    code: str | None = None
    message: str | None = None

    @property
    def row_failure(self) -> bool:
        return (
            self.scope
            is ImportFailureScope.ROW
        )


def classify_import_error(
    exc: BaseException,
) -> ImportErrorClassification:
    if isinstance(
        exc,
        ProductImportRowValidationError,
    ):
        return ImportErrorClassification(
            kind=ImportErrorKind.DETERMINISTIC_VALIDATION,
            scope=ImportFailureScope.ROW,
            retryable=False,
            code=exc.code,
            message=exc.message,
        )
    if isinstance(
        exc,
        ProductImportRowExecutionError,
    ):
        return ImportErrorClassification(
            kind=ImportErrorKind.DETERMINISTIC_ROW_EXECUTION,
            scope=ImportFailureScope.ROW,
            retryable=False,
            code=exc.code,
            message=exc.message,
        )
    if isinstance(
        exc,
        ProductImportTerminalError,
    ):
        return ImportErrorClassification(
            kind=ImportErrorKind.DETERMINISTIC_JOB,
            scope=ImportFailureScope.JOB,
            retryable=False,
        )
    return ImportErrorClassification(
        kind=ImportErrorKind.TRANSIENT_SYSTEM,
        scope=ImportFailureScope.JOB,
        retryable=True,
    )


def runtime_failure_summary(
    *,
    message: str,
    final_attempt: bool,
    retryable: bool,
    resume_status: str,
) -> dict[str, object]:
    return {
        "code": (
            "PRODUCT_IMPORT_FAILED"
            if final_attempt
            else "PRODUCT_IMPORT_RETRYING"
        ),
        "technical": str(
            message
        )[:500],
        "retryable": (
            bool(retryable)
            if final_attempt
            else False
        ),
        "resume_status":
            str(resume_status),
    }
