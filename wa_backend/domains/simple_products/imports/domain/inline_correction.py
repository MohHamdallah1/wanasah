"""Transport-neutral bounds and cell patch semantics for inline correction."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from domains.simple_products.imports.domain.localization import CANONICAL_IMPORT_FIELDS
from domains.simple_products.imports.domain.source_semantics import SOURCE_CELL_META_KEY
from domains.simple_products.imports.domain.retention import DEFAULT_PRODUCT_IMPORT_RETENTION

MAX_INLINE_CORRECTION_ROWS = 100
MAX_INLINE_CORRECTION_BYTES = 256 * 1024
MAX_INLINE_ROW_VALUES_BYTES = 64 * 1024

_CORRECTABLE_STATUSES = frozenset({"VALIDATION_FAILED", "COMPLETED_WITH_ERRORS"})


class InlineCorrectionError(ValueError):
    """Deterministic safe conflict; remains compatible with file correction."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def correction_field_mapping(
    mapping: dict[str, Any],
    detected_headers: list[str],
) -> dict[str, str]:
    """Expose only mapped canonical cells, never arbitrary source/metadata keys."""
    headers = set(detected_headers)
    return {
        field: mapping[field]
        for field in CANONICAL_IMPORT_FIELDS
        if isinstance(mapping.get(field), str)
        and mapping[field] in headers
        and mapping[field] != SOURCE_CELL_META_KEY
    }


def correction_details_expired(
    *, finished_at: datetime | None, compacted_at: Any,
) -> bool:
    if compacted_at is not None:
        return True
    if finished_at is None:
        return False
    if finished_at.tzinfo is not None:
        finished_at = finished_at.astimezone(timezone.utc).replace(tzinfo=None)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return finished_at <= now - DEFAULT_PRODUCT_IMPORT_RETENTION.full_row_detail


def correction_unavailable_reason(
    *, status: str, details_expired: bool, fields: dict[str, str], values_available: bool,
) -> str | None:
    if details_expired:
        return "ROW_DETAILS_EXPIRED"
    if status not in _CORRECTABLE_STATUSES:
        return "JOB_NOT_CORRECTABLE"
    if not fields:
        return "MAPPING_UNAVAILABLE"
    if not values_available:
        return "ROW_VALUES_TOO_LARGE"
    return None


def correction_cell_patch(
    *, values: dict[str, str | None], fields: dict[str, str],
) -> dict[str, str | None]:
    """Translate literal edited cells only; business validation stays in the worker."""
    if not values or any(field not in fields for field in values):
        raise InlineCorrectionError("PRODUCT_IMPORT_CORRECTION_FIELD_INVALID")
    if any(value is not None and not isinstance(value, str) for value in values.values()):
        raise InlineCorrectionError("PRODUCT_IMPORT_CORRECTION_ROWS_INVALID")
    return {fields[field]: value for field, value in values.items()}
