"""Canonical date-only spreadsheet normalization for future import fields.

The current Product Catalog import has no date-valued field. This helper exists
as the single authority future owning contracts must call instead of inventing
ad-hoc Excel serial conversion.
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
import math
from typing import Any

from openpyxl.utils.datetime import (
    CALENDAR_MAC_1904,
    CALENDAR_WINDOWS_1900,
    from_excel,
)


_SUPPORTED_EPOCHS = {
    "1900":
        CALENDAR_WINDOWS_1900,
    "1904":
        CALENDAR_MAC_1904,
}


def normalize_spreadsheet_date(
    value: Any,
    *,
    epoch: str,
) -> date:
    """Normalize one explicit date-only spreadsheet value."""
    epoch_key = str(
        epoch
    ).strip()
    workbook_epoch = (
        _SUPPORTED_EPOCHS.get(
            epoch_key
        )
    )
    if workbook_epoch is None:
        raise ValueError(
            "Spreadsheet date epoch must be '1900' or '1904'."
        )

    if isinstance(
        value,
        datetime,
    ):
        if (
            value.tzinfo
            is not None
            and value.utcoffset()
            is not None
        ):
            raise ValueError(
                "Timezone-aware datetimes are not valid date-only spreadsheet values."
            )
        if value.time() != time():
            raise ValueError(
                "Spreadsheet date-only value contains a time component."
            )
        return value.date()

    if isinstance(
        value,
        date,
    ):
        return value

    if isinstance(
        value,
        bool,
    ):
        raise ValueError(
            "Boolean is not a spreadsheet date."
        )

    if isinstance(
        value,
        (
            int,
            float,
            Decimal,
        ),
    ):
        try:
            serial = Decimal(
                str(
                    value
                )
            )
        except (
            InvalidOperation,
            ValueError,
        ) as exc:
            raise ValueError(
                "Spreadsheet date serial is invalid."
            ) from exc

        if not math.isfinite(
            float(
                serial
            )
        ):
            raise ValueError(
                "Spreadsheet date serial must be finite."
            )

        if serial != serial.to_integral_value():
            raise ValueError(
                "Spreadsheet date-only serial cannot contain a time fraction."
            )

        serial_int = int(
            serial
        )
        if (
            epoch_key == "1900"
            and serial_int == 60
        ):
            raise ValueError(
                "Excel serial day 60 is the non-existent 1900-02-29 compatibility date."
            )

        converted = from_excel(
            serial_int,
            epoch=workbook_epoch,
        )
        if isinstance(
            converted,
            datetime,
        ):
            return converted.date()
        if isinstance(
            converted,
            date,
        ):
            return converted
        raise ValueError(
            "Spreadsheet serial did not resolve to a calendar date."
        )

    if isinstance(
        value,
        str,
    ):
        clean = value.strip()
        try:
            parsed = date.fromisoformat(
                clean
            )
        except ValueError as exc:
            raise ValueError(
                "Spreadsheet date text must use unambiguous ISO YYYY-MM-DD format."
            ) from exc
        if parsed.isoformat() != clean:
            raise ValueError(
                "Spreadsheet date text must use canonical ISO YYYY-MM-DD format."
            )
        return parsed

    raise ValueError(
        "Unsupported spreadsheet date value."
    )
