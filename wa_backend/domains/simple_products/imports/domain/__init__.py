"""Public domain contract for Product Import.

Only stable, domain-level import concepts are re-exported here. Callers should
import these names from domains.simple_products.imports.domain instead of
reaching into internal module files. The domain layer is a leaf: it must not
depend on application, infrastructure or API layers.
"""

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
