"""Small fail-closed GS1 element-string parser for the approved AIs."""

from dataclasses import dataclass
from datetime import date
import re


GS = "\x1d"
_VARIABLE_AIS = {"10": (1, 20), "21": (1, 20)}


class Gs1ParseError(ValueError):
    pass


@dataclass(frozen=True)
class Gs1Data:
    gtin: str | None = None
    lot: str | None = None
    expiry_date: date | None = None
    serial: str | None = None


def _expiry(raw: str) -> date:
    if not re.fullmatch(r"\d{6}", raw):
        raise Gs1ParseError("GS1 AI 17 يجب أن يكون YYMMDD.")
    year, month, day = 2000 + int(raw[:2]), int(raw[2:4]), int(raw[4:])
    if day == 0:
        raise Gs1ParseError("GS1 AI 17 بيوم 00 غير مدعوم دون سياسة صريحة.")
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise Gs1ParseError("تاريخ GS1 AI 17 غير صالح.") from exc


def parse_gs1(value: str) -> Gs1Data:
    if not isinstance(value, str):
        raise Gs1ParseError("باركود GS1 يجب أن يكون نصاً.")
    raw = value.strip()
    if raw.startswith("]C1"):
        raw = raw[3:]
    raw = raw.replace("<GS>", GS)
    if not raw or len(raw) > 256 or "\x00" in raw:
        raise Gs1ParseError("باركود GS1 فارغ أو يتجاوز الحد الآمن.")

    values: dict[str, str] = {}
    cursor = 0
    while cursor < len(raw):
        if raw[cursor] == GS:
            cursor += 1
            continue
        ai = raw[cursor:cursor + 2]
        cursor += 2
        if ai == "01":
            data = raw[cursor:cursor + 14]
            if len(data) != 14 or not data.isdigit():
                raise Gs1ParseError("GS1 AI 01 يحتاج GTIN من 14 رقماً.")
            cursor += 14
        elif ai == "17":
            data = raw[cursor:cursor + 6]
            if len(data) != 6:
                raise Gs1ParseError("GS1 AI 17 غير مكتمل.")
            cursor += 6
        elif ai in _VARIABLE_AIS:
            minimum, maximum = _VARIABLE_AIS[ai]
            end = raw.find(GS, cursor)
            if end < 0:
                end = len(raw)
            data = raw[cursor:end]
            if not minimum <= len(data) <= maximum:
                raise Gs1ParseError(f"طول GS1 AI {ai} غير صالح.")
            cursor = end
        else:
            raise Gs1ParseError(f"GS1 AI غير مدعوم: {ai or 'فارغ'}.")
        if ai in values:
            raise Gs1ParseError(f"GS1 AI {ai} مكرر.")
        values[ai] = data

    return Gs1Data(
        gtin=values.get("01"),
        lot=values.get("10"),
        expiry_date=_expiry(values["17"]) if "17" in values else None,
        serial=values.get("21"),
    )
