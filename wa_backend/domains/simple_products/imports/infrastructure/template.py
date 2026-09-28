from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from domains.simple_products.imports.domain import (
    CANONICAL_IMPORT_FIELDS,
    IMPORT_TRACKING_DEFAULT_SENTINEL,
    ImportLocalePack,
    WANASAH_TEMPLATE_MARKER,
    WANASAH_TEMPLATE_META_SHEET,
    resolve_import_locale_pack,
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
_PACKAGE_CODES = (
    "CARTON",
    "CASE",
    "PACK",
    "BAG",
    "SACK",
    "TRAY",
    "CRATE",
    "BUNDLE",
    "PALLET",
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


def _preferred_package_label(
    pack: ImportLocalePack,
    canonical: str,
) -> str:
    for label, code in (
        pack.package_value_aliases.items()
    ):
        if code == canonical:
            return label
    raise ValueError(
        f"Missing package label for {canonical!r} "
        f"in locale {pack.locale!r}."
    )


def build_product_import_template(
    *,
    locale: str,
) -> bytes:
    pack = resolve_import_locale_pack(
        locale
    )
    copy = pack.template

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
    package_values = [
        _preferred_package_label(
            pack,
            code,
        )
        for code in _PACKAGE_CODES
    ]

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = copy.sheet_name
    sheet.freeze_panes = "A2"
    sheet.sheet_view.rightToLeft = (
        pack.rtl
    )

    header_fill = PatternFill(
        fill_type="solid",
        fgColor="475569",
    )
    header_font = Font(
        bold=True,
        color="FFFFFF",
        size=11,
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
            wrap_text=True,
        )

    sheet.auto_filter.ref = (
        f"A1:J{MAX_TEMPLATE_ROWS + 1}"
    )
    sheet.row_dimensions[1].height = 30

    widths = (
        30,
        20,
        16,
        18,
        14,
        14,
        20,
        20,
        16,
        16,
    )
    for index, width in enumerate(
        widths,
        start=1,
    ):
        sheet.column_dimensions[
            chr(64 + index)
        ].width = width

    package_column = "C"
    units_column = "D"
    package_price_column = "E"
    unit_price_column = "F"
    package_barcode_column = "H"

    package_validation = DataValidation(
        type="list",
        formula1="='_wanasah_lists'!$B$1:$B$9",
        allow_blank=True,
    )
    package_validation.errorTitle = copy[
        "package_validation_title"
    ]
    package_validation.error = copy[
        "validation_error"
    ]
    package_validation.promptTitle = copy[
        "package_validation_title"
    ]
    package_validation.prompt = copy[
        "package_note"
    ]
    package_validation.showErrorMessage = True
    package_validation.showInputMessage = True
    sheet.add_data_validation(
        package_validation
    )
    package_validation.add(
        f"{package_column}2:"
        f"{package_column}{MAX_TEMPLATE_ROWS + 1}"
    )

    units_validation = DataValidation(
        type="custom",
        formula1=(
            '=IF(C2="",D2="",'
            'AND(ISNUMBER(D2),D2=INT(D2),'
            'D2>=2,D2<=1000000))'
        ),
        allow_blank=False,
    )
    units_validation.errorTitle = copy[
        "units_validation_title"
    ]
    units_validation.error = copy[
        "units_note"
    ]
    units_validation.promptTitle = copy[
        "units_validation_title"
    ]
    units_validation.prompt = copy[
        "units_note"
    ]
    units_validation.showErrorMessage = True
    units_validation.showInputMessage = True
    sheet.add_data_validation(
        units_validation
    )
    units_validation.add(
        f"{units_column}2:"
        f"{units_column}{MAX_TEMPLATE_ROWS + 1}"
    )

    package_price_validation = DataValidation(
        type="custom",
        formula1=(
            '=OR(E2="",AND(C2<>"",'
            'ISNUMBER(E2),E2>0))'
        ),
        allow_blank=True,
    )
    package_price_validation.errorTitle = copy[
        "price_validation_title"
    ]
    package_price_validation.error = copy[
        "package_price_note"
    ]
    package_price_validation.promptTitle = copy[
        "price_validation_title"
    ]
    package_price_validation.prompt = copy[
        "package_price_note"
    ]
    package_price_validation.showErrorMessage = True
    package_price_validation.showInputMessage = True
    sheet.add_data_validation(
        package_price_validation
    )
    package_price_validation.add(
        f"{package_price_column}2:"
        f"{package_price_column}{MAX_TEMPLATE_ROWS + 1}"
    )

    unit_price_validation = DataValidation(
        type="custom",
        formula1=(
            '=OR(F2="",AND(ISNUMBER(F2),F2>0))'
        ),
        allow_blank=True,
    )
    unit_price_validation.errorTitle = copy[
        "price_validation_title"
    ]
    unit_price_validation.error = copy[
        "unit_price_note"
    ]
    unit_price_validation.promptTitle = copy[
        "price_validation_title"
    ]
    unit_price_validation.prompt = copy[
        "unit_price_note"
    ]
    unit_price_validation.showErrorMessage = True
    unit_price_validation.showInputMessage = True
    sheet.add_data_validation(
        unit_price_validation
    )
    unit_price_validation.add(
        f"{unit_price_column}2:"
        f"{unit_price_column}{MAX_TEMPLATE_ROWS + 1}"
    )

    sheet.column_dimensions[
        units_column
    ].number_format = "0"
    sheet.column_dimensions[
        package_price_column
    ].number_format = "0.000"
    sheet.column_dimensions[
        unit_price_column
    ].number_format = "0.000"

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

        barcode_formula = (
            (
                f'=OR({column_letter}2="",'
                f'AND(C2<>"",ISTEXT({column_letter}2)))'
            )
            if column_letter
            == package_barcode_column
            else (
                f'=OR({column_letter}2="",'
                f'ISTEXT({column_letter}2))'
            )
        )
        barcode_validation = DataValidation(
            type="custom",
            formula1=barcode_formula,
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
    for row_index, value in enumerate(
        package_values,
        start=1,
    ):
        list_sheet.cell(
            row=row_index,
            column=2,
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
            copy.default_note,
            "Wanasah",
        )

    header_notes = {
        "name":
            copy.required_note,
        "family":
            copy.family_note,
        "package_uom":
            copy.package_note,
        "units_per_package":
            copy.units_note,
        "package_price":
            copy.package_price_note,
        "unit_price":
            copy.unit_price_note,
        "unit_barcode":
            copy.unit_barcode_note,
        "package_barcode":
            copy.package_barcode_note,
        "lot_control_mode":
            copy.default_note,
        "expiry_control_mode":
            copy.default_note,
    }
    for field, note in (
        header_notes.items()
    ):
        column_index = (
            CANONICAL_IMPORT_FIELDS.index(
                field
            )
            + 1
        )
        sheet.cell(
            row=1,
            column=column_index,
        ).comment = Comment(
            note,
            "Wanasah",
        )

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
