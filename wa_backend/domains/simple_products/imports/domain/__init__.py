"""Public domain contract for Product Import.

Only stable, domain-level import concepts are re-exported here. Callers should
import these names from domains.simple_products.imports.domain instead of
reaching into internal module files. The domain layer is a leaf: it must not
depend on application, infrastructure or API layers.
"""

from .errors import ProductImportTerminalError
from .source_semantics import (
    SOURCE_CELL_META_KEY,
    WANASAH_TEMPLATE_MARKER,
    WANASAH_TEMPLATE_META_SHEET,
    WANASAH_TEMPLATE_PRODUCT_SHEET_CELL,
    formula_has_cached_value,
    formula_source_metadata,
    is_formula_metadata,
    is_numeric_source_cell,
    looks_like_scientific_barcode,
    numeric_source_metadata,
    source_cell_metadata,
)
from .spreadsheet_dates import (
    normalize_spreadsheet_date,
)
from .localization import (
    AR_IMPORT_LOCALE,
    CANONICAL_IMPORT_FIELDS,
    EN_IMPORT_LOCALE,
    IMPORT_ALIAS_REGISTRY,
    IMPORT_LOCALE_PACKS,
    IMPORT_TRACKING_DEFAULT_SENTINEL,
    ImportAliasRegistry,
    ImportLocalePack,
    build_import_alias_registry,
    canonical_package_value,
    canonical_tracking_value,
    normalize_import_token,
    suggest_import_mapping,
)

__all__ = (
    "ProductImportTerminalError",
    "SOURCE_CELL_META_KEY",
    "WANASAH_TEMPLATE_MARKER",
    "WANASAH_TEMPLATE_META_SHEET",
    "WANASAH_TEMPLATE_PRODUCT_SHEET_CELL",
    "formula_has_cached_value",
    "formula_source_metadata",
    "is_formula_metadata",
    "is_numeric_source_cell",
    "looks_like_scientific_barcode",
    "numeric_source_metadata",
    "source_cell_metadata",
    "normalize_spreadsheet_date",
    "AR_IMPORT_LOCALE",
    "CANONICAL_IMPORT_FIELDS",
    "EN_IMPORT_LOCALE",
    "IMPORT_ALIAS_REGISTRY",
    "IMPORT_LOCALE_PACKS",
    "IMPORT_TRACKING_DEFAULT_SENTINEL",
    "ImportAliasRegistry",
    "ImportLocalePack",
    "build_import_alias_registry",
    "canonical_package_value",
    "canonical_tracking_value",
    "normalize_import_token",
    "suggest_import_mapping",
)
