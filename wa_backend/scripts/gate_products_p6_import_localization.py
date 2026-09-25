from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from product_import_localization import (  # noqa: E402
    AR_IMPORT_LOCALE,
    CANONICAL_IMPORT_FIELDS,
    EN_IMPORT_LOCALE,
    IMPORT_LOCALE_PACKS,
    ImportLocalePack,
    build_import_alias_registry,
    canonical_package_value,
    canonical_tracking_value,
    suggest_import_mapping,
)
from product_import_worker import (  # noqa: E402
    _package_code,
    _tracking_import_mode,
    suggest_mapping,
)


checks = 0
failures: list[str] = []


def check(
    condition: bool,
    label: str,
    detail: str = "",
) -> None:
    global checks
    checks += 1
    prefix = "[PASS]" if condition else "[FAIL]"
    suffix = f" — {detail}" if detail else ""
    print(f"{prefix} {label}{suffix}")
    if not condition:
        failures.append(label)


def static_checks() -> None:
    worker = (
        BACKEND / "product_import_worker.py"
    ).read_text(encoding="utf-8")
    api = (
        BACKEND / "api/simple_products.py"
    ).read_text(encoding="utf-8")
    localization = (
        BACKEND / "product_import_localization.py"
    ).read_text(encoding="utf-8")
    import_modal = (
        ROOT
        / "dashboard/src/pages/products/import/ImportProductModal.tsx"
    ).read_text(encoding="utf-8")
    import_polling = (
        ROOT
        / "dashboard/src/pages/products/import/useImportProductPolling.ts"
    ).read_text(encoding="utf-8")
    import_downloads = (
        ROOT
        / "dashboard/src/pages/products/import/createImportDownloads.ts"
    ).read_text(encoding="utf-8")
    modal_compact = " ".join(import_modal.split())
    polling_compact = " ".join(import_polling.split())
    translations = (
        ROOT / "dashboard/src/i18n/resources.ts"
    ).read_text(encoding="utf-8")

    check(
        "from product_import_localization import"
        in worker
        and "_ALIASES = {" not in worker
        and "_TRACKING_VALUE_ALIASES" not in worker
        and "_PACKAGE_VALUE_ALIASES" not in worker,
        "worker no longer owns locale aliases",
    )

    check(
        "CANONICAL_IMPORT_FIELDS"
        in api
        and "_CANONICAL_MAPPING_FIELDS = frozenset("
        in api,
        "API and worker share language-neutral canonical fields",
    )

    check(
        "class ImportLocalePack" in localization
        and "IMPORT_LOCALE_PACKS" in localization
        and "build_import_alias_registry" in localization,
        "locale packs are isolated from business workflow code",
    )

    check(
        '"NEEDS_MAPPING"' in modal_compact
        and "status.suggested_mapping" in import_polling
        and "status.column_mapping" in import_polling
        and "status.detected_headers.map" in import_modal,
        "explicit mapping UI remains the authoritative fallback",
    )

    check(
        '"products.fields.name"' in import_downloads
        and '"products.fields.family"' in import_downloads
        and '"products.fields.packageUom"' in import_downloads
        and '"products.fields.lotControlMode"' in import_downloads
        and '"products.fields.expiryControlMode"' in import_downloads
        and 'const downloadTemplate' in import_downloads,
        "downloaded template derives headers from UI translations",
    )

    report_start = import_downloads.index(
        "const downloadErrorReport"
    )
    report_end = import_downloads.index(
        "const downloadTemplate",
        report_start,
    )
    report_source = import_downloads[
        report_start:report_end
    ]
    check(
        "row.code" in report_source
        and "i18n.exists(key)" in report_source
        and "row.message" not in report_source,
        "error report localization is code-driven",
    )

    import_codes = sorted(
        set(
            re.findall(
                r"""["'](IMPORT_[A-Z0-9_]+)["']""",
                worker,
            )
        )
    )
    missing_translations = [
        code
        for code in import_codes
        if (
            translations.count(
                f"{code}:"
            )
            + translations.count(
                f'"{code}"'
            )
        )
        < 2
    ]
    check(
        not missing_translations,
        "all worker import validation codes have Arabic and English UI translations",
        repr(missing_translations),
    )


def runtime_checks() -> None:
    # Existing English/Arabic behavior must remain compatible.
    existing_en = suggest_mapping(
        [
            "Product",
            "Unit Price",
            "Lot Tracking",
        ]
    )
    check(
        existing_en == {
            "name": "Product",
            "unit_price": "Unit Price",
            "lot_control_mode": "Lot Tracking",
        },
        "existing English header suggestions are preserved",
        repr(existing_en),
    )

    existing_ar = suggest_mapping(
        [
            "اسم المنتج",
            "سعر الوحدة",
            "تتبع الصلاحية",
        ]
    )
    check(
        existing_ar == {
            "name": "اسم المنتج",
            "unit_price": "سعر الوحدة",
            "expiry_control_mode": "تتبع الصلاحية",
        },
        "existing Arabic header suggestions are preserved",
        repr(existing_ar),
    )

    check(
        _tracking_import_mode(
            "إلزامي",
            fallback="NONE",
            field_name="lot_control_mode",
        )
        == "REQUIRED"
        and _package_code(
            "كرتونة",
            has_package_column=True,
            has_units_column=True,
        )
        == "CARTON",
        "existing localized row values are preserved",
    )

    # Prove extensibility with a third language without touching worker code.
    fr = ImportLocalePack(
        locale="fr",
        header_aliases={
            "name": ("nom du produit",),
            "family": ("famille",),
            "unit_price": ("prix unitaire",),
            "lot_control_mode": ("suivi du lot",),
        },
        tracking_value_aliases={
            "aucun": "NONE",
            "facultatif": "OPTIONAL",
            "obligatoire": "REQUIRED",
        },
        package_value_aliases={
            "caisse": "CASE",
        },
    )
    registry = build_import_alias_registry(
        (*IMPORT_LOCALE_PACKS, fr)
    )

    french = suggest_import_mapping(
        [
            "Nom du produit",
            "Prix unitaire",
            "Suivi du lot",
        ],
        registry=registry,
    )
    check(
        french == {
            "name": "Nom du produit",
            "unit_price": "Prix unitaire",
            "lot_control_mode": "Suivi du lot",
        },
        "third-language pack adds header detection without worker changes",
        repr(french),
    )

    check(
        canonical_tracking_value(
            "obligatoire",
            registry=registry,
        )
        == "REQUIRED"
        and canonical_package_value(
            "caisse",
            registry=registry,
        )
        == "CASE",
        "third-language value aliases normalize to canonical codes",
    )

    unknown = suggest_import_mapping(
        [
            "Nom du produit",
            "Mystery Header",
        ],
        registry=registry,
    )
    check(
        unknown == {
            "name": "Nom du produit",
        },
        "unknown-language headers remain unmapped instead of guessed",
        repr(unknown),
    )

    duplicate = suggest_import_mapping(
        [
            "Product",
            "Product Name",
        ],
        registry=registry,
    )
    check(
        "name" not in duplicate,
        "multiple matching source columns do not produce an unsafe guess",
        repr(duplicate),
    )

    collision_pack = ImportLocalePack(
        locale="collision",
        header_aliases={
            "family": ("product",),
        },
        tracking_value_aliases={},
        package_value_aliases={},
    )
    collision_blocked = False
    try:
        build_import_alias_registry(
            (
                EN_IMPORT_LOCALE,
                AR_IMPORT_LOCALE,
                collision_pack,
            )
        )
    except ValueError:
        collision_blocked = True

    check(
        collision_blocked,
        "cross-field alias collisions fail closed",
    )

    check(
        tuple(CANONICAL_IMPORT_FIELDS)
        == (
            "name",
            "family",
            "package_uom",
            "units_per_package",
            "package_price",
            "unit_price",
            "unit_barcode",
            "package_barcode",
            "lot_control_mode",
            "expiry_control_mode",
        ),
        "canonical field IDs remain language-neutral and stable",
    )


def main() -> int:
    try:
        static_checks()
        runtime_checks()
    except Exception as exc:
        check(
            False,
            "P6 localization gate completed without unexpected exception",
            repr(exc),
        )

    print()
    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL: {failure}")

    if failures:
        print(
            "PRODUCTS_P6_IMPORT_LOCALIZATION_GATE=FAIL"
        )
        return 1

    print(
        "PRODUCTS_P6_IMPORT_LOCALIZATION_GATE=PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
