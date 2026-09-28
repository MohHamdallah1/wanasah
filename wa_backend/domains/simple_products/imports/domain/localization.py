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

IMPORT_TRACKING_DEFAULT_SENTINEL = "__DEFAULT__"

_TRACKING_CODES = {
    "NONE",
    "OPTIONAL",
    "REQUIRED",
}
_TRACKING_IMPORT_VALUES = (
    _TRACKING_CODES
    | {
        IMPORT_TRACKING_DEFAULT_SENTINEL,
    }
)


@dataclass(frozen=True)
class ImportTemplateCopy:
    sheet_name: str
    headers: Mapping[
        str,
        str,
    ]
    required_note: str
    family_note: str
    default_note: str
    validation_error: str
    validation_title: str
    barcode_validation_title: str
    barcode_validation_error: str
    package_note: str
    units_note: str
    package_price_note: str
    unit_price_note: str
    unit_barcode_note: str
    package_barcode_note: str
    package_validation_title: str
    units_validation_title: str
    price_validation_title: str


@dataclass(frozen=True)
class ImportLocalePack:
    locale: str
    rtl: bool
    template: ImportTemplateCopy
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
    rtl=False,
    template=ImportTemplateCopy(
        sheet_name="Products",
        headers={
            "name": "Name",
            "family": "Family",
            "package_uom": "Outer Package Type",
            "units_per_package": "Base Units per Outer Package",
            "package_price": "Outer Package Price",
            "unit_price": "Unit Price",
            "unit_barcode": "Unit Barcode",
            "package_barcode": "Outer Package Barcode",
            "lot_control_mode": "Lot Tracking",
            "expiry_control_mode": "Expiry Tracking",
        },
        required_note="Required.",
        family_note="Optional product family.",
        default_note=(
            "Leave blank, or choose Use default, to use the "
            "tracking default shown in Wanasah when you upload "
            "this file. Choose another value only for exceptions."
        ),
        validation_error=(
            "Choose a value from the list, or leave the cell blank."
        ),
        validation_title="Product tracking",
        barcode_validation_title="Barcode text",
        barcode_validation_error=(
            "Enter the complete barcode as text. "
            "Do not use numbers, formulas, or scientific notation."
        ),
        package_note=(
            "Required: choose No outer package, or choose the actual outer "
            "package type used for this product."
        ),
        units_note=(
            "Required when an outer package is selected. Enter how many base "
            "units it contains, from 2 to 1,000,000. Example: "
            "1 carton = 24 base units. Leave blank only when "
            "No outer package is selected."
        ),
        package_price_note=(
            "Optional. Use only for a real outer package. Enter a positive "
            "number. Leave blank when No outer package is selected."
        ),
        unit_price_note=(
            "Enter a positive number when provided. At least one of "
            "Package Price or Unit Price must be supplied per product."
        ),
        unit_barcode_note=(
            "Optional. Keep the complete unit barcode as text, "
            "especially when it starts with zero."
        ),
        package_barcode_note=(
            "Optional and valid only for a real outer package. Keep the "
            "complete barcode as text."
        ),
        package_validation_title="Package type",
        units_validation_title="Units per package",
        price_validation_title="Price",
    ),
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
            "outer package type",
            "outer package",
            "package uom",
        ),
        "units_per_package": (
            "base units per outer package",
            "units per outer package",
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
            "outer package price",
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
            "outer package barcode",
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
        "use default":
            IMPORT_TRACKING_DEFAULT_SENTINEL,
        "default":
            IMPORT_TRACKING_DEFAULT_SENTINEL,
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
        "no outer package": "NONE",
        "no package": "NONE",
        "unit only": "NONE",
        "none": "NONE",
    },
)


AR_IMPORT_LOCALE = ImportLocalePack(
    locale="ar",
    rtl=True,
    template=ImportTemplateCopy(
        sheet_name="المنتجات",
        headers={
            "name": "اسم المنتج",
            "family": "العائلة",
            "package_uom": "نوع العبوة الخارجية",
            "units_per_package": "عدد الوحدات الأساسية داخل العبوة الخارجية",
            "package_price": "سعر العبوة الخارجية",
            "unit_price": "سعر الوحدة",
            "unit_barcode": "باركود الوحدة",
            "package_barcode": "باركود العبوة الخارجية",
            "lot_control_mode": "تتبع الدفعة",
            "expiry_control_mode": "تتبع الصلاحية",
        },
        required_note="مطلوب.",
        family_note="عائلة المنتج اختيارية.",
        default_note=(
            "اترك الخانة فارغة، أو اختر «استخدام الافتراضي»، "
            "ليستخدم المنتج إعداد التتبع الافتراضي الظاهر في وناسة "
            "وقت رفع الملف. اختر قيمة أخرى فقط للاستثناءات."
        ),
        validation_error=(
            "اختر قيمة من القائمة، أو اترك الخانة فارغة."
        ),
        validation_title="تتبع المنتج",
        barcode_validation_title="الباركود كنص",
        barcode_validation_error=(
            "أدخل الباركود كاملاً كنص. لا تستخدم رقماً أو معادلة أو صيغة علمية."
        ),
        package_note=(
            "اختيار إلزامي: اختر «بدون عبوة خارجية» إذا كان المنتج يباع "
            "كوحدة أساسية فقط، أو اختر نوع العبوة الخارجية الفعلي."
        ),
        units_note=(
            "مطلوب عند اختيار عبوة خارجية: أدخل عدد الوحدات الأساسية "
            "داخلها من 2 إلى 1,000,000. مثال: كرتونة فيها 24 وحدة "
            "أساسية = 24. اتركه فارغاً فقط عند اختيار «بدون عبوة خارجية»."
        ),
        package_price_note=(
            "اختياري، ويستخدم فقط لعبوة خارجية فعلية. أدخل رقماً موجباً، "
            "واتركه فارغاً عند اختيار «بدون عبوة خارجية»."
        ),
        unit_price_note=(
            "أدخل رقماً موجباً عند تعبئته. يجب توفير سعر العبوة أو سعر الوحدة "
            "على الأقل لكل منتج."
        ),
        unit_barcode_note=(
            "اختياري. احتفظ بالباركود كاملاً كنص، خصوصاً إذا بدأ بصفر."
        ),
        package_barcode_note=(
            "اختياري ويقبل فقط لعبوة خارجية فعلية. احتفظ بالباركود كاملاً كنص."
        ),
        package_validation_title="نوع العبوة",
        units_validation_title="عدد الوحدات",
        price_validation_title="السعر",
    ),
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
            "نوع العبوة الخارجية",
            "نوع العبوة",
            "العبوة الخارجية",
            "العبوة",
            "وحدة العبوة",
        ),
        "units_per_package": (
            "عدد الوحدات الأساسية داخل العبوة الخارجية",
            "عدد الوحدات داخل العبوة الخارجية",
            "عدد الوحدات في العبوة",
            "عدد الحبات في العبوة",
            "عدد الحبات في الكرتونة",
            "الحبات بالكرتونة",
            "حبة بالكرتونة",
            "عدد القطع في الكرتونة",
        ),
        "package_price": (
            "سعر العبوة الخارجية",
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
            "باركود العبوة الخارجية",
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
        "استخدام الافتراضي":
            IMPORT_TRACKING_DEFAULT_SENTINEL,
        "افتراضي":
            IMPORT_TRACKING_DEFAULT_SENTINEL,
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
        "بدون عبوة خارجية": "NONE",
        "بدون عبوة": "NONE",
        "بدون": "NONE",
        "لا يوجد": "NONE",
    },
)


IMPORT_LOCALE_PACKS = (
    EN_IMPORT_LOCALE,
    AR_IMPORT_LOCALE,
)


def normalize_import_locale_tag(
    value: Any,
) -> str:
    return (
        str(
            value
            or ""
        )
        .strip()
        .replace(
            "_",
            "-",
        )
        .lower()
    )


def build_import_locale_registry(
    packs: Iterable[ImportLocalePack],
) -> dict[str, ImportLocalePack]:
    registry: dict[
        str,
        ImportLocalePack,
    ] = {}
    for pack in packs:
        locale = (
            normalize_import_locale_tag(
                pack.locale
            )
        )
        if not locale:
            raise ValueError(
                "Import locale pack must have a locale."
            )
        if locale in registry:
            raise ValueError(
                f"Duplicate import locale pack: {locale}"
            )

        template_fields = set(
            pack.template.headers
        )
        canonical_fields = set(
            CANONICAL_IMPORT_FIELDS
        )
        if template_fields != canonical_fields:
            raise ValueError(
                "Import template headers must cover exactly "
                f"the canonical fields for locale {locale}: "
                f"missing={sorted(canonical_fields - template_fields)}, "
                f"unknown={sorted(template_fields - canonical_fields)}"
            )

        normalized_headers = [
            normalize_import_token(
                pack.template.headers[
                    field
                ]
            )
            for field in CANONICAL_IMPORT_FIELDS
        ]
        if (
            any(
                not value
                for value in normalized_headers
            )
            or len(
                normalized_headers
            )
            != len(
                set(
                    normalized_headers
                )
            )
        ):
            raise ValueError(
                "Import template display headers must be "
                f"non-empty and unique for locale {locale}."
            )

        if not pack.template.sheet_name.strip():
            raise ValueError(
                f"Import template sheet name is empty for locale {locale}."
            )

        registry[
            locale
        ] = pack
    return registry


IMPORT_LOCALE_REGISTRY = (
    build_import_locale_registry(
        IMPORT_LOCALE_PACKS
    )
)


def resolve_import_locale_pack(
    locale: str | None,
    *,
    fallback_locale: str = "en",
    registry: Mapping[
        str,
        ImportLocalePack,
    ] = IMPORT_LOCALE_REGISTRY,
) -> ImportLocalePack:
    requested = (
        normalize_import_locale_tag(
            locale
        )
    )
    candidates = [
        candidate
        for candidate in (
            requested,
            (
                requested.split(
                    "-",
                    1,
                )[0]
                if requested
                else ""
            ),
        )
        if candidate
    ]
    for candidate in candidates:
        pack = registry.get(
            candidate
        )
        if pack is not None:
            return pack

    fallback = (
        normalize_import_locale_tag(
            fallback_locale
        )
    )
    fallback_candidates = [
        candidate
        for candidate in (
            fallback,
            (
                fallback.split(
                    "-",
                    1,
                )[0]
                if fallback
                else ""
            ),
        )
        if candidate
    ]
    for candidate in fallback_candidates:
        pack = registry.get(
            candidate
        )
        if pack is not None:
            return pack

    raise ValueError(
        "Import locale registry has no usable fallback locale."
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
        locale = normalize_import_locale_tag(
            pack.locale
        )
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
            if code not in _TRACKING_IMPORT_VALUES:
                raise ValueError(
                    "Unknown tracking import value "
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
