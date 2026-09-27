"""Product Import row normalization.

This module preserves the existing canonical Product normalization behavior.
It delegates Product/Tracking authority to their existing owning domains.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from domains.product_tracking import (
    normalize_tracking_mode,
)
from domains.simple_products.imports.domain.localization import (
    IMPORT_TRACKING_DEFAULT_SENTINEL,
    canonical_package_value,
    canonical_tracking_value,
)
from domains.simple_products.imports.domain.source_semantics import (
    formula_has_cached_value,
    is_formula_metadata,
    is_numeric_source_cell,
    looks_like_scientific_barcode,
    source_cell_metadata,
)
from domains.simple_products.service import (
    SimpleProductError,
    normalize_barcode,
    normalize_package_code,
    resolve_price_pair,
)


def tracking_import_mode(
    raw_value: Any,
    *,
    fallback: str,
    field_name: str,
) -> str:
    if raw_value is None or not str(raw_value).strip():
        return normalize_tracking_mode(
            fallback,
            field_name=field_name,
        )

    canonical = canonical_tracking_value(
        raw_value,
    )
    if (
        canonical
        == IMPORT_TRACKING_DEFAULT_SENTINEL
    ):
        return normalize_tracking_mode(
            fallback,
            field_name=field_name,
        )
    return normalize_tracking_mode(
        canonical,
        field_name=field_name,
    )


def package_code(
    raw_package: Any,
    *,
    has_package_column: bool,
    has_units_column: bool,
) -> str | None:
    if raw_package is not None and str(
        raw_package
    ).strip():
        canonical = canonical_package_value(
            raw_package,
        )
        return normalize_package_code(canonical)

    if has_units_column:
        return "CARTON"

    if not has_package_column:
        return None

    return None


def normalize_raw_row(
    raw: dict[str, Any],
    mapping: dict[str, str],
    *,
    default_lot_control_mode: str,
    default_expiry_control_mode: str,
) -> dict[str, Any]:
    def value(field: str):
        header = mapping.get(
            field
        )
        if not header:
            return None

        current = raw.get(
            header
        )
        metadata = (
            source_cell_metadata(
                raw,
                header,
            )
        )

        if is_formula_metadata(
            metadata
        ):
            if field in {
                "unit_barcode",
                "package_barcode",
            }:
                raise SimpleProductError(
                    "IMPORT_BARCODE_FORMULA_NOT_ALLOWED",
                    "Barcode cells must contain literal text, not formulas.",
                    status_code=422,
                )
            if not formula_has_cached_value(
                metadata
            ):
                raise SimpleProductError(
                    "IMPORT_FORMULA_VALUE_UNAVAILABLE",
                    "The formula cell has no safe cached value. Replace it with a literal value.",
                    status_code=422,
                )

        if field in {
            "unit_barcode",
            "package_barcode",
        }:
            if is_numeric_source_cell(
                metadata
            ):
                raise SimpleProductError(
                    "IMPORT_BARCODE_NUMERIC_UNSAFE",
                    "Barcode cells stored as Excel numbers are unsafe because leading zeros or digits may have been lost. Store the barcode as text.",
                    status_code=422,
                )
            if looks_like_scientific_barcode(
                current
            ):
                raise SimpleProductError(
                    "IMPORT_BARCODE_SCIENTIFIC_NOTATION",
                    "Barcode is written in scientific notation. Store the complete barcode as literal text.",
                    status_code=422,
                )

        return current

    name = str(
        value("name") or ""
    ).strip()
    if not name:
        raise SimpleProductError(
            "IMPORT_NAME_REQUIRED",
            "Product name is required.",
            status_code=422,
        )
    if len(name) > 200:
        raise SimpleProductError(
            "IMPORT_NAME_TOO_LONG",
            "Product name exceeds the supported length.",
            status_code=422,
        )

    has_package_column = bool(
        mapping.get("package_uom")
    )
    has_units_column = bool(
        mapping.get("units_per_package")
    )
    normalized_package_code = package_code(
        value("package_uom"),
        has_package_column=has_package_column,
        has_units_column=has_units_column,
    )

    if normalized_package_code is None:
        units = 1
    else:
        units_raw = str(
            value("units_per_package") or ""
        ).strip()
        if not units_raw:
            raise SimpleProductError(
                "IMPORT_PACKAGING_REQUIRED",
                "units_per_package is required for an outer package.",
                status_code=422,
            )
        try:
            units_decimal = Decimal(
                units_raw
            )
            units = int(units_decimal)
        except Exception as exc:
            raise SimpleProductError(
                "IMPORT_PACKAGING_INVALID",
                "units_per_package is invalid.",
                status_code=422,
            ) from exc

        if (
            units_decimal
            != Decimal(units)
            or units < 2
            or units > 1_000_000
        ):
            raise SimpleProductError(
                "IMPORT_PACKAGING_INVALID",
                "units_per_package must be an integer between 2 and 1,000,000.",
                status_code=422,
            )

    prices = resolve_price_pair(
        units_per_package=units,
        package_uom_code=normalized_package_code,
        package_price=value(
            "package_price"
        ),
        unit_price=value("unit_price"),
    )

    family = str(
        value("family") or ""
    ).strip() or None
    unit_barcode = normalize_barcode(
        value("unit_barcode"),
        "unit_barcode",
    )
    package_barcode = normalize_barcode(
        value("package_barcode"),
        "package_barcode",
    )
    if (
        normalized_package_code is None
        and package_barcode is not None
    ):
        raise SimpleProductError(
            "IMPORT_PACKAGE_BARCODE_WITHOUT_PACKAGE",
            "package_barcode cannot be supplied without an outer package.",
            status_code=422,
        )

    lot_control_mode = tracking_import_mode(
        value("lot_control_mode"),
        fallback=default_lot_control_mode,
        field_name="lot_control_mode",
    )
    expiry_control_mode = tracking_import_mode(
        value("expiry_control_mode"),
        fallback=default_expiry_control_mode,
        field_name="expiry_control_mode",
    )

    return {
        "name": name,
        "family_name": family,
        "package_uom_code":
            normalized_package_code,
        "units_per_package": units,
        "package_price": (
            format(
                prices.package_price,
                "f",
            )
            if prices.package_price
            is not None
            else None
        ),
        "unit_price": format(
            prices.unit_price,
            "f",
        ),
        "unit_barcode": unit_barcode,
        "package_barcode":
            package_barcode,
        "lot_control_mode":
            lot_control_mode,
        "expiry_control_mode":
            expiry_control_mode,
    }
