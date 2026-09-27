"""Source-cell semantics shared by Product Import parsing and normalization."""
from __future__ import annotations

import re
from typing import Any


SOURCE_CELL_META_KEY = (
    "__wanasah_source_cells__"
)
WANASAH_TEMPLATE_META_SHEET = (
    "_wanasah_meta"
)
WANASAH_TEMPLATE_MARKER = (
    "WANASAH_PRODUCT_IMPORT_V1"
)
WANASAH_TEMPLATE_PRODUCT_SHEET_CELL = (
    "A2"
)

_FORMULA_FLAG = "formula"
_CACHED_FLAG = "cached"
_NUMERIC_FLAG = "numeric"
_NUMBER_FORMAT = "number_format"

_SCIENTIFIC_BARCODE_RE = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)[eE][+-]?\d+$"
)


def formula_source_metadata(
    *,
    cached: bool,
) -> dict[str, object]:
    return {
        _FORMULA_FLAG:
            True,
        _CACHED_FLAG:
            bool(
                cached
            ),
    }


def numeric_source_metadata(
    *,
    number_format: str | None,
) -> dict[str, object]:
    return {
        _NUMERIC_FLAG:
            True,
        _NUMBER_FORMAT:
            str(
                number_format
                or ""
            ),
    }


def source_cell_metadata(
    raw: dict[str, Any],
    header: str | None,
) -> dict[str, Any]:
    if not header:
        return {}

    metadata = raw.get(
        SOURCE_CELL_META_KEY
    )
    if not isinstance(
        metadata,
        dict,
    ):
        return {}

    value = metadata.get(
        header
    )
    return (
        dict(
            value
        )
        if isinstance(
            value,
            dict,
        )
        else {}
    )


def is_formula_metadata(
    metadata: dict[str, Any],
) -> bool:
    return (
        metadata.get(
            _FORMULA_FLAG
        )
        is True
    )


def formula_has_cached_value(
    metadata: dict[str, Any],
) -> bool:
    return (
        metadata.get(
            _CACHED_FLAG
        )
        is True
    )


def is_numeric_source_cell(
    metadata: dict[str, Any],
) -> bool:
    return (
        metadata.get(
            _NUMERIC_FLAG
        )
        is True
    )


def looks_like_scientific_barcode(
    value: Any,
) -> bool:
    if not isinstance(
        value,
        str,
    ):
        return False
    return bool(
        _SCIENTIFIC_BARCODE_RE.fullmatch(
            value.strip()
        )
    )
