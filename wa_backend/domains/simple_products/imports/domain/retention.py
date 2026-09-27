"""Product Import retention policy.

Upload bytes are short-lived source material. Full row JSON is retained longer
for support/correction, while compact lineage metadata remains available for
audit without keeping heavy source payloads indefinitely.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


TERMINAL_IMPORT_JOB_STATUSES = (
    "VALIDATION_FAILED",
    "COMPLETED",
    "COMPLETED_WITH_ERRORS",
    "FAILED",
)


@dataclass(frozen=True, slots=True)
class ProductImportRetentionPolicy:
    upload_bytes: timedelta = timedelta(
        days=7
    )
    full_row_detail: timedelta = timedelta(
        days=30
    )
    compact_lineage: timedelta = timedelta(
        days=365
    )
    batch_size: int = 1_000
    max_batches_per_run: int = 10

    def __post_init__(
        self,
    ) -> None:
        if not (
            timedelta(0)
            < self.upload_bytes
            < self.full_row_detail
            < self.compact_lineage
        ):
            raise ValueError(
                "Product Import retention windows must be positive and strictly increasing."
            )
        if (
            isinstance(
                self.batch_size,
                bool,
            )
            or not isinstance(
                self.batch_size,
                int,
            )
            or self.batch_size <= 0
            or self.batch_size > 5_000
        ):
            raise ValueError(
                "Product Import retention batch_size must be between 1 and 5000."
            )
        if (
            isinstance(
                self.max_batches_per_run,
                bool,
            )
            or not isinstance(
                self.max_batches_per_run,
                int,
            )
            or self.max_batches_per_run
            <= 0
            or self.max_batches_per_run
            > 100
        ):
            raise ValueError(
                "Product Import retention max_batches_per_run must be between 1 and 100."
            )


DEFAULT_PRODUCT_IMPORT_RETENTION = (
    ProductImportRetentionPolicy()
)
