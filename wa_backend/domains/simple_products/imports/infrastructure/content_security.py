"""File-content authority for Product Import uploads.

Client MIME is never trusted. The filename selects the supported contract;
content signatures and archive structure must independently match it.
"""
from __future__ import annotations

import io
import zipfile
from typing import BinaryIO

from domains.simple_products.imports.domain import (
    ProductImportTerminalError,
)


MAX_XLSX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_XLSX_ARCHIVE_ENTRIES = 500
MAX_XLSX_COMPRESSION_RATIO = 200
_CSV_INSPECTION_BYTES = 64 * 1024
_ZIP_SIGNATURES = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
)
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_REQUIRED_XLSX_MEMBERS = frozenset({
    "[content_types].xml",
    "xl/workbook.xml",
})


def _terminal(
    technical: str,
    *,
    code: str,
    user_message: str,
) -> ProductImportTerminalError:
    return ProductImportTerminalError(
        technical,
        code=code,
        user_message=user_message,
    )


def _validate_xlsx_archive(
    archive: zipfile.ZipFile,
) -> None:
    infos = archive.infolist()
    if not infos:
        raise _terminal(
            "XLSX archive contains no entries.",
            code="PRODUCT_IMPORT_SOURCE_CORRUPT",
            user_message="The Excel file is empty or damaged.",
        )
    if len(infos) > MAX_XLSX_ARCHIVE_ENTRIES:
        raise _terminal(
            "XLSX archive entry count exceeds safety limit.",
            code="PRODUCT_IMPORT_XLSX_UNSAFE",
            user_message="The Excel file was rejected by file-safety checks.",
        )

    names = {
        info.filename.replace("\\", "/").lower()
        for info in infos
    }
    if not _REQUIRED_XLSX_MEMBERS.issubset(names):
        raise _terminal(
            "ZIP payload is not an XLSX workbook.",
            code="PRODUCT_IMPORT_SOURCE_TYPE_MISMATCH",
            user_message="The file content does not match an XLSX workbook.",
        )

    total_uncompressed = 0
    for info in infos:
        normalized_name = (
            info.filename
            .replace("\\", "/")
            .lower()
        )
        total_uncompressed += int(info.file_size)
        if total_uncompressed > MAX_XLSX_UNCOMPRESSED_BYTES:
            raise _terminal(
                "XLSX uncompressed content exceeds safety limit.",
                code="PRODUCT_IMPORT_XLSX_UNSAFE",
                user_message="The Excel file was rejected by file-safety checks.",
            )
        if (
            info.compress_size > 0
            and info.file_size > 1_000_000
            and (info.file_size / info.compress_size)
            > MAX_XLSX_COMPRESSION_RATIO
        ):
            raise _terminal(
                "XLSX compression ratio exceeds safety limit.",
                code="PRODUCT_IMPORT_XLSX_UNSAFE",
                user_message="The Excel file was rejected by file-safety checks.",
            )
        if normalized_name.endswith("vbaproject.bin"):
            raise _terminal(
                "Macro payload detected in XLSX archive.",
                code="PRODUCT_IMPORT_XLSX_UNSAFE",
                user_message="Macro-enabled Excel files are not supported.",
            )


def _validate_csv_prefix(
    prefix: bytes,
) -> None:
    if prefix.startswith(_ZIP_SIGNATURES) or prefix.startswith(_OLE_SIGNATURE):
        raise _terminal(
            "Binary spreadsheet payload was supplied as CSV.",
            code="PRODUCT_IMPORT_SOURCE_TYPE_MISMATCH",
            user_message="The file content does not match a CSV file.",
        )
    if b"\x00" in prefix:
        raise _terminal(
            "CSV prefix contains NUL bytes.",
            code="PRODUCT_IMPORT_SOURCE_TYPE_MISMATCH",
            user_message="The file content does not match a supported CSV file.",
        )
    forbidden_controls = sum(
        1
        for byte in prefix
        if byte < 32
        and byte not in (9, 10, 13)
    )
    if prefix and forbidden_controls > max(2, len(prefix) // 100):
        raise _terminal(
            "CSV prefix contains abnormal binary control bytes.",
            code="PRODUCT_IMPORT_SOURCE_TYPE_MISMATCH",
            user_message="The file content does not match a supported CSV file.",
        )


def validate_source_content(
    file_name: str,
    source: bytes | BinaryIO,
) -> str:
    """Validate content independently from client MIME and return canonical MIME."""
    suffix = (
        str(file_name).lower().rsplit(".", 1)[-1]
        if "." in str(file_name)
        else ""
    )
    if suffix not in {"csv", "xlsx"}:
        raise _terminal(
            "Unsupported Product Import filename suffix.",
            code="PRODUCT_IMPORT_SOURCE_INVALID",
            user_message="Upload a CSV or XLSX file.",
        )

    owns_stream = isinstance(source, (bytes, bytearray, memoryview))
    stream: BinaryIO = (
        io.BytesIO(bytes(source))
        if owns_stream
        else source
    )
    original_position = stream.tell()
    try:
        stream.seek(0)
        if suffix == "csv":
            prefix = stream.read(_CSV_INSPECTION_BYTES)
            _validate_csv_prefix(prefix)
            return "text/csv; charset=utf-8"

        try:
            with zipfile.ZipFile(stream) as archive:
                _validate_xlsx_archive(archive)
        except zipfile.BadZipFile as exc:
            raise _terminal(
                "XLSX payload is not a valid ZIP archive.",
                code="PRODUCT_IMPORT_SOURCE_TYPE_MISMATCH",
                user_message="The file content does not match an XLSX workbook.",
            ) from exc
        return (
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )
    finally:
        if not owns_stream:
            stream.seek(original_position)
        else:
            stream.close()
