"""Product Import admission policy for bounded source capacity."""
from __future__ import annotations

from dataclasses import dataclass
import os


def _env_int(
    name: str,
    default: int,
) -> int:
    raw = os.getenv(
        name
    )
    value = (
        int(
            raw
        )
        if raw is not None
        else int(
            default
        )
    )
    if value <= 0:
        raise ValueError(
            f"{name} must be positive."
        )
    return value


@dataclass(frozen=True, slots=True)
class ProductImportAdmissionPolicy:
    user_window_seconds: int = 60
    max_uploads_per_user_window: int = 10
    max_uploads_per_tenant_window: int = 50
    max_active_jobs_per_tenant: int = 25
    max_live_source_bytes_per_tenant: int = (
        128
        * 1024
        * 1024
    )
    global_live_source_bytes: int = (
        2
        * 1024
        * 1024
        * 1024
    )
    retry_after_seconds: int = 30
    storage_alert_percent: int = 80
    oldest_source_alert_seconds: int = 300

    @classmethod
    def from_environment(
        cls,
    ) -> "ProductImportAdmissionPolicy":
        return cls(
            user_window_seconds=
                _env_int(
                    "PRODUCT_IMPORT_USER_WINDOW_SECONDS",
                    60,
                ),
            max_uploads_per_user_window=
                _env_int(
                    "PRODUCT_IMPORT_MAX_UPLOADS_PER_USER_WINDOW",
                    10,
                ),
            max_uploads_per_tenant_window=
                _env_int(
                    "PRODUCT_IMPORT_MAX_UPLOADS_PER_TENANT_WINDOW",
                    50,
                ),
            max_active_jobs_per_tenant=
                _env_int(
                    "PRODUCT_IMPORT_MAX_ACTIVE_JOBS_PER_TENANT",
                    25,
                ),
            max_live_source_bytes_per_tenant=
                _env_int(
                    "PRODUCT_IMPORT_MAX_LIVE_SOURCE_BYTES_PER_TENANT",
                    128 * 1024 * 1024,
                ),
            global_live_source_bytes=
                _env_int(
                    "PRODUCT_IMPORT_GLOBAL_LIVE_SOURCE_BYTES",
                    2 * 1024 * 1024 * 1024,
                ),
            retry_after_seconds=
                _env_int(
                    "PRODUCT_IMPORT_ADMISSION_RETRY_AFTER_SECONDS",
                    30,
                ),
            storage_alert_percent=
                _env_int(
                    "PRODUCT_IMPORT_STORAGE_ALERT_PERCENT",
                    80,
                ),
            oldest_source_alert_seconds=
                _env_int(
                    "PRODUCT_IMPORT_OLDEST_SOURCE_ALERT_SECONDS",
                    300,
                ),
        )


class ProductImportAdmissionDenied(
    RuntimeError
):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        current_value: int,
        limit_value: int,
        retry_after_seconds: int,
    ) -> None:
        super().__init__(
            message
        )
        self.code = str(
            code
        )
        self.message = str(
            message
        )
        self.current_value = int(
            current_value
        )
        self.limit_value = int(
            limit_value
        )
        self.retry_after_seconds = int(
            retry_after_seconds
        )


DEFAULT_PRODUCT_IMPORT_ADMISSION_POLICY = (
    ProductImportAdmissionPolicy.from_environment()
)
