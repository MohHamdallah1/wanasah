"""Locale-aware aliases for product import parsing.

This module is deliberately free of database and business workflow code.
Adding a new import language should require adding an ImportLocalePack here,
not changing product_import_worker.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


CANONICAL_IMPORT_FIELDS = (
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
)

_TRACKING_CODES = {
    "NONE",
    "OPTIONAL",
    "REQUIRED",
}


@dataclass(frozen=True)
class ImportLocalePack:
    locale: str
    header_aliases: Mapping[
        str,
        tuple[str, ...],
    ]
    tracking_value_aliases: Mapping[
        str,
        str,
    ]
    package_value_aliases: Mapping[
        str,
        str,
    ]


@dataclass(frozen=True)
class ImportAliasRegistry:
    header_to_field: Mapping[str, str]
    tracking_to_code: Mapping[str, str]
    package_to_code: Mapping[str, str]


def normalize_import_token(
    value: Any,
) -> str:
    normalized = (
        str(value or "")
        .strip()
        .lower()
        .replace("_", " ")
        .replace("-", " ")
    )
    return re.sub(r"\s+", " ", normalized)


EN_IMPORT_LOCALE = ImportLocalePack(
    locale="en",
    header_aliases={
        "name": (
            "name",
            "product name",
            "product",
            "item",
            "item name",
        ),
        "family": (
            "family",
            "product family",
            "group",
        ),
        "package_uom": (
            "package",
            "package type",
            "outer package",
            "package uom",
        ),
        "units_per_package": (
            "units per package",
            "units/package",
            "pieces per package",
            "units per carton",
            "units/carton",
            "pieces per carton",
            "pcs per carton",
            "pack per carton",
            "packs per carton",
        ),
        "package_price": (
            "package price",
            "outer price",
            "carton price",
            "case price",
        ),
        "unit_price": (
            "unit price",
            "piece price",
            "each price",
        ),
        "unit_barcode": (
            "unit barcode",
            "piece barcode",
            "each barcode",
        ),
        "package_barcode": (
            "package barcode",
            "outer barcode",
            "carton barcode",
            "case barcode",
        ),
        "lot_control_mode": (
            "lot control",
            "lot tracking",
            "batch tracking",
            "lot control mode",
            "batch control mode",
        ),
        "expiry_control_mode": (
            "expiry control",
            "expiry tracking",
            "expiration tracking",
            "expiry control mode",
            "expiration control mode",
        ),
    },
    tracking_value_aliases={
        "none": "NONE",
        "no": "NONE",
        "without": "NONE",
        "optional": "OPTIONAL",
        "required": "REQUIRED",
        "mandatory": "REQUIRED",
    },
    package_value_aliases={
        "carton": "CARTON",
        "case": "CASE",
        "box": "CASE",
        "pack": "PACK",
        "packet": "PACK",
        "bag": "BAG",
        "sack": "SACK",
        "tray": "TRAY",
        "crate": "CRATE",
        "bundle": "BUNDLE",
        "pallet": "PALLET",
        "none": "NONE",
        "no package": "NONE",
        "unit only": "NONE",
    },
)


AR_IMPORT_LOCALE = ImportLocalePack(
    locale="ar",
    header_aliases={
        "name": (
            "اسم المنتج",
            "المنتج",
            "اسم الصنف",
            "الصنف",
        ),
        "family": (
            "العائلة",
            "عائلة",
            "عائلة المنتج",
        ),
        "package_uom": (
            "نوع العبوة",
            "العبوة",
            "وحدة العبوة",
        ),
        "units_per_package": (
            "عدد الوحدات في العبوة",
            "عدد الحبات في العبوة",
            "عدد الحبات في الكرتونة",
            "الحبات بالكرتونة",
            "حبة بالكرتونة",
            "عدد القطع في الكرتونة",
        ),
        "package_price": (
            "سعر العبوة",
            "سعر الكرتونة",
            "سعر كرتونة",
        ),
        "unit_price": (
            "سعر الوحدة",
            "سعر الحبة",
            "سعر القطعة",
        ),
        "unit_barcode": (
            "باركود الوحدة",
            "باركود الحبة",
            "باركود القطعة",
            "باركود",
        ),
        "package_barcode": (
            "باركود العبوة",
            "باركود الكرتونة",
        ),
        "lot_control_mode": (
            "تتبع الدفعة",
            "تتبع الدفعات",
            "تتبع التشغيلة",
            "نمط تتبع الدفعة",
        ),
        "expiry_control_mode": (
            "تتبع الصلاحية",
            "تتبع تاريخ الصلاحية",
            "نمط تتبع الصلاحية",
        ),
    },
    tracking_value_aliases={
        "بدون": "NONE",
        "لا": "NONE",
        "اختياري": "OPTIONAL",
        "إلزامي": "REQUIRED",
        "الزامي": "REQUIRED",
    },
    package_value_aliases={
        "كرتونة": "CARTON",
        "صندوق": "CASE",
        "باكيت": "PACK",
        "كيس": "BAG",
        "شوال": "SACK",
        "صينية": "TRAY",
        "قفص": "CRATE",
        "حزمة": "BUNDLE",
        "طبلية": "PALLET",
        "بدون": "NONE",
        "بدون عبوة": "NONE",
        "لا يوجد": "NONE",
    },
)


IMPORT_LOCALE_PACKS = (
    EN_IMPORT_LOCALE,
    AR_IMPORT_LOCALE,
)


def build_import_alias_registry(
    packs: Iterable[ImportLocalePack],
) -> ImportAliasRegistry:
    locales: set[str] = set()
    header_to_field: dict[str, str] = {}
    tracking_to_code: dict[str, str] = {}
    package_to_code: dict[str, str] = {}

    # Canonical IDs are always valid language-neutral
    # aliases, independent of locale packs.
    for field in CANONICAL_IMPORT_FIELDS:
        header_to_field[
            normalize_import_token(field)
        ] = field

    for pack in packs:
        locale = pack.locale.strip()
        if not locale:
            raise ValueError(
                "Import locale pack must have a locale.",
            )
        if locale in locales:
            raise ValueError(
                f"Duplicate import locale pack: {locale}",
            )
        locales.add(locale)

        unknown_fields = (
            set(pack.header_aliases)
            - set(CANONICAL_IMPORT_FIELDS)
        )
        if unknown_fields:
            raise ValueError(
                "Unknown canonical import fields "
                f"in locale {locale}: "
                f"{sorted(unknown_fields)}",
            )

        for field, aliases in (
            pack.header_aliases.items()
        ):
            for alias in aliases:
                normalized = (
                    normalize_import_token(
                        alias,
                    )
                )
                if not normalized:
                    raise ValueError(
                        "Import header alias cannot "
                        f"be empty ({locale}/{field}).",
                    )
                existing = (
                    header_to_field.get(
                        normalized,
                    )
                )
                if (
                    existing is not None
                    and existing != field
                ):
                    raise ValueError(
                        "Ambiguous import header alias "
                        f"{alias!r}: {existing} vs "
                        f"{field}",
                    )
                header_to_field[
                    normalized
                ] = field

        for alias, code in (
            pack.tracking_value_aliases.items()
        ):
            normalized = (
                normalize_import_token(alias)
            )
            if code not in _TRACKING_CODES:
                raise ValueError(
                    "Unknown tracking code "
                    f"{code!r} in locale {locale}.",
                )
            existing = tracking_to_code.get(
                normalized,
            )
            if (
                existing is not None
                and existing != code
            ):
                raise ValueError(
                    "Ambiguous tracking value alias "
                    f"{alias!r}: {existing} vs "
                    f"{code}",
                )
            tracking_to_code[
                normalized
            ] = code

        for alias, code in (
            pack.package_value_aliases.items()
        ):
            normalized = (
                normalize_import_token(alias)
            )
            canonical = code.strip().upper()
            if not canonical:
                raise ValueError(
                    "Package alias code cannot be "
                    f"empty ({locale}/{alias}).",
                )
            existing = package_to_code.get(
                normalized,
            )
            if (
                existing is not None
                and existing != canonical
            ):
                raise ValueError(
                    "Ambiguous package value alias "
                    f"{alias!r}: {existing} vs "
                    f"{canonical}",
                )
            package_to_code[
                normalized
            ] = canonical

    return ImportAliasRegistry(
        header_to_field=header_to_field,
        tracking_to_code=tracking_to_code,
        package_to_code=package_to_code,
    )


IMPORT_ALIAS_REGISTRY = (
    build_import_alias_registry(
        IMPORT_LOCALE_PACKS,
    )
)


def suggest_import_mapping(
    headers: list[str],
    *,
    registry: ImportAliasRegistry = (
        IMPORT_ALIAS_REGISTRY
    ),
) -> dict[str, str]:
    by_field: dict[str, list[str]] = {}

    for header in headers:
        canonical = (
            registry.header_to_field.get(
                normalize_import_token(header),
            )
        )
        if canonical is None:
            continue
        by_field.setdefault(
            canonical,
            [],
        ).append(header)

    # Multiple source columns matching the same
    # canonical field are deliberately not guessed.
    return {
        field: by_field[field][0]
        for field in CANONICAL_IMPORT_FIELDS
        if len(by_field.get(field, ())) == 1
    }


def canonical_tracking_value(
    raw_value: Any,
    *,
    registry: ImportAliasRegistry = (
        IMPORT_ALIAS_REGISTRY
    ),
) -> str:
    raw = str(raw_value).strip()
    return registry.tracking_to_code.get(
        normalize_import_token(raw),
        raw,
    )


def canonical_package_value(
    raw_value: Any,
    *,
    registry: ImportAliasRegistry = (
        IMPORT_ALIAS_REGISTRY
    ),
) -> str:
    raw = str(raw_value).strip()
    return registry.package_to_code.get(
        normalize_import_token(raw),
        raw.upper(),
    )
