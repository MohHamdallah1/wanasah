from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from domains.sales_calculation.core import normalize_currency_code


EVIDENCE_SCHEMA_VERSION = 2


class SalesEvidenceError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        context: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.status_code = int(status_code)
        self.context = dict(context or {})

    def as_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "context": self.context,
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def currency_code(value: str, field_name: str) -> str:
    try:
        return normalize_currency_code(value)
    except Exception as exc:
        raise SalesEvidenceError(
            "SALES_EVIDENCE_CURRENCY_INVALID",
            f"{field_name} is invalid.",
            status_code=422,
            context={"field": field_name},
        ) from exc


def json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise SalesEvidenceError(
                "SALES_EVIDENCE_DATETIME_INVALID",
                "Evidence datetime must include a UTC offset.",
                status_code=422,
            )
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {
            str(key): json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise SalesEvidenceError(
        "SALES_EVIDENCE_JSON_INVALID",
        "Evidence contains a value that cannot be serialized deterministically.",
        status_code=422,
        context={"type": type(value).__name__},
    )
