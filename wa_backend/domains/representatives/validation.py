from __future__ import annotations

import unicodedata

from .contracts import RepresentativeError


_USERNAME_SEPARATORS = frozenset("._-")
_ARABIC_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x0870, 0x089F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)


def _is_arabic_letter(char: str) -> bool:
    codepoint = ord(char)
    return unicodedata.category(char).startswith("L") and any(
        start <= codepoint <= end for start, end in _ARABIC_RANGES
    )


def _is_latin_letter(char: str) -> bool:
    return ("A" <= char <= "Z") or ("a" <= char <= "z")


def normalize_representative_username(value: str) -> str:
    if not isinstance(value, str):
        raise RepresentativeError(
            "REPRESENTATIVE_USERNAME_INVALID",
            "Representative username is invalid.",
            status_code=422,
        )
    username = value.strip()
    if not username or len(username) > 80:
        raise RepresentativeError(
            "REPRESENTATIVE_USERNAME_INVALID",
            "Representative username is invalid.",
            status_code=422,
        )

    has_arabic = False
    has_latin = False
    has_letter = False
    for char in username:
        if _is_arabic_letter(char):
            has_arabic = True
            has_letter = True
            continue
        if _is_latin_letter(char):
            has_latin = True
            has_letter = True
            continue
        if "0" <= char <= "9" or char in _USERNAME_SEPARATORS:
            continue
        raise RepresentativeError(
            "REPRESENTATIVE_USERNAME_INVALID",
            "Representative username is invalid.",
            status_code=422,
        )

    if not has_letter or (has_arabic and has_latin):
        raise RepresentativeError(
            "REPRESENTATIVE_USERNAME_INVALID",
            "Representative username is invalid.",
            status_code=422,
        )
    return username


def normalize_representative_phone(value: str | None) -> str:
    if not isinstance(value, str):
        raise RepresentativeError(
            "REPRESENTATIVE_PHONE_REQUIRED",
            "Representative phone number is required.",
            status_code=422,
        )
    phone = value.strip()
    if not phone:
        raise RepresentativeError(
            "REPRESENTATIVE_PHONE_REQUIRED",
            "Representative phone number is required.",
            status_code=422,
        )
    if len(phone) > 20:
        raise RepresentativeError(
            "REPRESENTATIVE_PHONE_INVALID",
            "Representative phone number exceeds the supported length.",
            status_code=422,
        )
    return phone


__all__ = [
    "normalize_representative_phone",
    "normalize_representative_username",
]
