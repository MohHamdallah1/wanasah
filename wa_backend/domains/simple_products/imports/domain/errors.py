"""Product Import error taxonomy and stable failure summaries."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProductImportTerminalError(RuntimeError):
    """Deterministic import failure that must not be retried automatically."""


class ImportErrorKind(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    TRANSIENT = "TRANSIENT"


@dataclass(frozen=True)
class ImportErrorClassification:
    kind: ImportErrorKind

    @property
    def retryable(self) -> bool:
        return (
            self.kind
            is ImportErrorKind.TRANSIENT
        )


def classify_import_error(
    exc: BaseException,
) -> ImportErrorClassification:
    if isinstance(
        exc,
        ProductImportTerminalError,
    ):
        return ImportErrorClassification(
            ImportErrorKind.DETERMINISTIC
        )
    return ImportErrorClassification(
        ImportErrorKind.TRANSIENT
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
