"""Canonical Product Import column-mapping rules."""
from __future__ import annotations

from domains.simple_products.imports.domain.localization import (
    CANONICAL_IMPORT_FIELDS,
    suggest_import_mapping,
)


_CANONICAL_FIELDS = CANONICAL_IMPORT_FIELDS


def suggest_mapping(
    headers: list[str],
) -> dict[str, str]:
    return suggest_import_mapping(headers)


def mapping_complete(
    mapping: dict[str, str],
) -> bool:
    return bool(
        mapping.get("name")
        and (
            mapping.get("package_price")
            or mapping.get("unit_price")
        )
    )


def validate_mapping(
    headers: list[str],
    mapping: dict[str, str],
) -> dict[str, str]:
    allowed = set(headers)
    cleaned: dict[str, str] = {}
    used: set[str] = set()

    for canonical, header in mapping.items():
        if canonical not in _CANONICAL_FIELDS:
            raise ValueError(
                f"Unknown mapping field: {canonical}"
            )
        if not header:
            continue
        if header not in allowed:
            raise ValueError(
                f"Source column does not exist: {header}"
            )
        if header in used:
            raise ValueError(
                "One source column cannot map to more than one canonical field."
            )
        cleaned[canonical] = header
        used.add(header)

    return cleaned
