from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from domains.simple_products.imports.domain import (
    AR_IMPORT_LOCALE,
    CANONICAL_IMPORT_FIELDS,
    EN_IMPORT_LOCALE,
    IMPORT_TRACKING_DEFAULT_SENTINEL,
    ImportLocalePack,
    WANASAH_TEMPLATE_MARKER,
    WANASAH_TEMPLATE_META_SHEET,
)


MAX_TEMPLATE_ROWS = 50_000
_TRACKING_FIELDS = (
    "lot_control_mode",
    "expiry_control_mode",
)
_BARCODE_FIELDS = (
    "unit_barcode",
    "package_barcode",
)


def _locale_pack(locale: str) -> ImportLocalePack:
    return (
        EN_IMPORT_LOCALE
        if str(locale).lower().startswith("en")
        else AR_IMPORT_LOCALE
    )


def _preferred_tracking_label(
    pack: ImportLocalePack,
    canonical: str,
) -> str:
    for label, code in (
        pack.tracking_value_aliases.items()
    ):
        if code == canonical:
            return label
    raise ValueError(
        f"Missing tracking label for {canonical!r} "
        f"in locale {pack.locale!r}."
    )


def _template_copy(
    locale: str,
) -> dict[str, str]:
    if locale == "en":
        return {
            "sheet": "Products",
            "default_note": (
                "Leave blank, or choose Use default, to use the "
                "tracking default shown in Wanasah when you upload "
                "this file. Choose another value only for exceptions."
            ),
            "validation_error": (
                "Choose a value from the list, or leave the cell blank."
            ),
            "validation_title": "Product tracking",
            "barcode_validation_title": "Barcode text",
            "barcode_validation_error": (
                "Enter the complete barcode as text. "
                "Do not use numbers, formulas, or scientific notation."
            ),
        }
    return {
        "sheet": "المنتجات",
        "default_note": (
            "اترك الخانة فارغة، أو اختر «استخدام الافتراضي»، "
            "ليستخدم المنتج إعداد التتبع الافتراضي الظاهر في وناسة "
            "وقت رفع الملف. اختر قيمة أخرى فقط للاستثناءات."
        ),
        "validation_error": (
            "اختر قيمة من القائمة، أو اترك الخانة فارغة."
        ),
        "validation_title": "تتبع المنتج",
        "barcode_validation_title": "الباركود كنص",
        "barcode_validation_error": (
            "أدخل الباركود كاملاً كنص. لا تستخدم رقماً أو معادلة أو صيغة علمية."
        ),
    }


def build_product_import_template(
    *,
    locale: str,
) -> bytes:
    pack = _locale_pack(locale)
    copy = _template_copy(pack.locale)

    headers = [
        pack.header_aliases[field][0]
        for field in CANONICAL_IMPORT_FIELDS
    ]
    tracking_values = [
        _preferred_tracking_label(
            pack,
            IMPORT_TRACKING_DEFAULT_SENTINEL,
        ),
        _preferred_tracking_label(
            pack,
            "NONE",
        ),
        _preferred_tracking_label(
            pack,
            "OPTIONAL",
        ),
        _preferred_tracking_label(
            pack,
            "REQUIRED",
        ),
    ]

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = copy["sheet"]
    sheet.freeze_panes = "A2"
    sheet.sheet_view.rightToLeft = (
        pack.locale == "ar"
    )

    header_fill = PatternFill(
        fill_type="solid",
        fgColor="0F172A",
    )
    header_font = Font(
        bold=True,
        color="FFFFFF",
    )
    for column_index, header in enumerate(
        headers,
        start=1,
    ):
        cell = sheet.cell(
            row=1,
            column=column_index,
            value=header,
        )
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(
            horizontal="center",
            vertical="center",
        )

    sheet.auto_filter.ref = (
        f"A1:J{MAX_TEMPLATE_ROWS + 1}"
    )
    sheet.row_dimensions[1].height = 24

    widths = (
        28,
        22,
        18,
        22,
        18,
        18,
        22,
        22,
        22,
        22,
    )
    for index, width in enumerate(
        widths,
        start=1,
    ):
        sheet.column_dimensions[
            chr(64 + index)
        ].width = width

    for field in _BARCODE_FIELDS:
        column_index = (
            CANONICAL_IMPORT_FIELDS.index(
                field
            )
            + 1
        )
        column_letter = chr(
            64 + column_index
        )
        sheet.column_dimensions[
            column_letter
        ].number_format = "@"

        barcode_validation = DataValidation(
            type="custom",
            formula1=(
                f'=OR({column_letter}2="",'
                f'ISTEXT({column_letter}2))'
            ),
            allow_blank=True,
        )
        barcode_validation.errorTitle = (
            copy[
                "barcode_validation_title"
            ]
        )
        barcode_validation.error = copy[
            "barcode_validation_error"
        ]
        barcode_validation.showErrorMessage = True
        sheet.add_data_validation(
            barcode_validation
        )
        barcode_validation.add(
            f"{column_letter}2:"
            f"{column_letter}{MAX_TEMPLATE_ROWS + 1}"
        )

    meta_sheet = workbook.create_sheet(
        WANASAH_TEMPLATE_META_SHEET
    )
    meta_sheet["A1"] = (
        WANASAH_TEMPLATE_MARKER
    )
    meta_sheet["A2"] = sheet.title
    meta_sheet.sheet_state = (
        "veryHidden"
    )

    list_sheet = workbook.create_sheet(
        "_wanasah_lists"
    )
    for row_index, value in enumerate(
        tracking_values,
        start=1,
    ):
        list_sheet.cell(
            row=row_index,
            column=1,
            value=value,
        )
    list_sheet.sheet_state = "hidden"

    formula = (
        "='_wanasah_lists'!$A$1:$A$4"
    )
    for field in _TRACKING_FIELDS:
        column_index = (
            CANONICAL_IMPORT_FIELDS.index(
                field
            )
            + 1
        )
        column_letter = chr(
            64 + column_index
        )
        validation = DataValidation(
            type="list",
            formula1=formula,
            allow_blank=True,
        )
        validation.errorTitle = (
            copy[
                "validation_title"
            ]
        )
        validation.error = copy[
            "validation_error"
        ]
        validation.promptTitle = (
            copy[
                "validation_title"
            ]
        )
        validation.prompt = copy[
            "default_note"
        ]
        validation.showErrorMessage = True
        validation.showInputMessage = True

        sheet.add_data_validation(
            validation
        )
        validation.add(
            f"{column_letter}2:"
            f"{column_letter}{MAX_TEMPLATE_ROWS + 1}"
        )

        sheet.cell(
            row=1,
            column=column_index,
        ).comment = Comment(
            copy["default_note"],
            "Wanasah",
        )

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
