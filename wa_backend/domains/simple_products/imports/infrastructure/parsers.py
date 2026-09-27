"""Bounded CSV/XLSX streaming parsers for Product Import.

The immutable source payload is currently supplied by the existing SourceStore
contract. Phase 4 guarantees that parsing does not materialize Product rows
proportional to source row count: rows are yielded one at a time and consumed
by bounded staging batches.
"""
from __future__ import annotations

import codecs
import csv
import io
import sqlite3
import zipfile
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, ContextManager, Iterator, Protocol

from openpyxl.reader.excel import (
    ExcelReader,
    SHARED_STRINGS,
)
from openpyxl.reader.strings import (
    SHEET_MAIN_NS,
    Text,
    iterparse,
)

from domains.simple_products.imports.domain import (
    ProductImportTerminalError,
    normalize_import_token,
)


MAX_IMPORT_ROWS = 50_000
MAX_IMPORT_COLUMNS = 100
MAX_XLSX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_XLSX_ARCHIVE_ENTRIES = 500
MAX_XLSX_COMPRESSION_RATIO = 200
_CSV_DECODE_CHUNK_BYTES = 64 * 1024
_CSV_SNIFF_BYTES = 8 * 1024


@dataclass(frozen=True, slots=True)
class ParsedRow:
    row_number: int
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ParsedSource:
    headers: list[str]
    rows: Iterator[ParsedRow]


class SourceParser(Protocol):
    def __call__(
        self,
        file_name: str,
        payload: bytes,
    ) -> ContextManager[ParsedSource]:
        ...


class _DiskBackedSharedStrings(
    Sequence[str]
):
    """Bounded-memory shared-string table for read-only XLSX traversal."""

    _INSERT_BATCH = 512

    def __init__(
        self,
    ) -> None:
        # Empty database name asks SQLite for an automatically-cleaned
        # temporary on-disk database. Cache size stays fixed as row count grows.
        self._db = sqlite3.connect(
            ""
        )
        self._db.execute(
            "PRAGMA temp_store=FILE"
        )
        self._db.execute(
            "PRAGMA cache_size=-2048"
        )
        self._db.execute(
            "PRAGMA synchronous=OFF"
        )
        self._db.execute(
            "PRAGMA journal_mode=OFF"
        )
        self._db.execute(
            "CREATE TABLE shared_strings ("
            "idx INTEGER PRIMARY KEY, "
            "value TEXT NOT NULL"
            ")"
        )
        self._length = 0
        self._closed = False

    def load(
        self,
        xml_source,
    ) -> None:
        string_tag = (
            f"{{{SHEET_MAIN_NS}}}si"
        )
        batch: list[
            tuple[int, str]
        ] = []

        events = iterparse(
            xml_source,
            events=(
                "start",
                "end",
            ),
        )
        try:
            _event, root = next(
                events
            )
        except StopIteration:
            return

        for event, node in events:
            if (
                event != "end"
                or node.tag
                != string_tag
            ):
                continue

            value = (
                Text.from_tree(
                    node
                )
                .content
                .replace(
                    "x005F_",
                    "",
                )
            )
            batch.append(
                (
                    self._length,
                    value,
                )
            )
            self._length += 1

            # Clearing both the processed node and the root releases prior
            # sibling elements instead of allowing ElementTree to retain one
            # empty object per shared string.
            node.clear()
            root.clear()

            if (
                len(batch)
                >= self._INSERT_BATCH
            ):
                self._flush(
                    batch
                )

        self._flush(batch)
        self._db.commit()

    def _flush(
        self,
        batch: list[
            tuple[int, str]
        ],
    ) -> None:
        if not batch:
            return
        self._db.executemany(
            "INSERT INTO shared_strings "
            "(idx, value) VALUES (?, ?)",
            batch,
        )
        batch.clear()

    @lru_cache(
        maxsize=512
    )
    def _lookup(
        self,
        index: int,
    ) -> str:
        row = self._db.execute(
            "SELECT value "
            "FROM shared_strings "
            "WHERE idx = ?",
            (
                int(index),
            ),
        ).fetchone()
        if row is None:
            raise IndexError(index)
        return str(row[0])

    def __getitem__(
        self,
        index,
    ) -> str:
        if isinstance(
            index,
            slice,
        ):
            raise TypeError(
                "Shared-string slices are not supported."
            )

        normalized = int(index)
        if normalized < 0:
            normalized += self._length
        if (
            normalized < 0
            or normalized
            >= self._length
        ):
            raise IndexError(index)

        return self._lookup(
            normalized
        )

    def __len__(
        self,
    ) -> int:
        return self._length

    def close(
        self,
    ) -> None:
        if self._closed:
            return
        self._lookup.cache_clear()
        self._db.close()
        self._closed = True


class _BoundedExcelReader(
    ExcelReader
):
    """OpenPyXL reader with disk-backed shared strings."""

    def __init__(
        self,
        file_object,
    ) -> None:
        super().__init__(
            file_object,
            read_only=True,
            keep_vba=False,
            data_only=True,
            keep_links=False,
            rich_text=False,
        )
        self._shared_string_store: (
            _DiskBackedSharedStrings
            | None
        ) = None

    def read_strings(
        self,
    ) -> None:
        content_type = (
            self.package.find(
                SHARED_STRINGS
            )
        )
        if content_type is None:
            self.shared_strings = []
            return

        store = (
            _DiskBackedSharedStrings()
        )
        strings_path = (
            content_type.PartName[1:]
        )
        try:
            with self.archive.open(
                strings_path
            ) as source:
                store.load(source)
        except Exception:
            store.close()
            raise

        self._shared_string_store = (
            store
        )
        self.shared_strings = store

    def close_bounded_resources(
        self,
        *,
        close_archive: bool,
    ) -> None:
        if (
            self._shared_string_store
            is not None
        ):
            self._shared_string_store.close()
            self._shared_string_store = None

        if close_archive:
            self.archive.close()


def _load_bounded_workbook(
    file_object,
) -> _BoundedExcelReader:
    reader = _BoundedExcelReader(
        file_object
    )
    try:
        reader.read()
    except Exception:
        reader.close_bounded_resources(
            close_archive=True
        )
        raise
    return reader


def _json_cell(
    value: Any,
) -> str | None:
    if value is None:
        return None
    if isinstance(
        value,
        datetime,
    ):
        return value.isoformat()
    clean = str(value).strip()
    return clean or None


def _header_layout(
    values: list[Any] | tuple[Any, ...],
    *,
    max_columns: int = MAX_IMPORT_COLUMNS,
) -> list[tuple[int, str]]:
    layout = [
        (
            index,
            str(value or "").strip(),
        )
        for index, value in enumerate(values)
        if str(value or "").strip()
    ]
    if not layout:
        raise ProductImportTerminalError(
            "The header row is empty."
        )
    if int(max_columns) <= 0:
        raise ValueError(
            "max_columns must be positive."
        )
    if (
        len(layout)
        > int(max_columns)
    ):
        raise ProductImportTerminalError(
            f"The file has more than {int(max_columns)} columns."
        )

    normalized = [
        normalize_import_token(
            header
        )
        for _, header in layout
    ]
    if (
        len(normalized)
        != len(set(normalized))
    ):
        raise ProductImportTerminalError(
            "The header row contains duplicate columns after normalization."
        )
    return layout


def _row_from_layout(
    values: list[Any] | tuple[Any, ...],
    layout: list[tuple[int, str]],
) -> dict[str, Any]:
    return {
        header: _json_cell(
            values[index]
            if index < len(values)
            else None
        )
        for index, header
        in layout
    }


def _count_and_yield(
    *,
    row_number: int,
    raw: dict[str, Any],
    accepted_count: int,
) -> tuple[
    ParsedRow | None,
    int,
]:
    if not any(
        value is not None
        for value in raw.values()
    ):
        return None, accepted_count

    next_count = (
        accepted_count + 1
    )
    if (
        next_count
        > MAX_IMPORT_ROWS
    ):
        raise ProductImportTerminalError(
            f"The import exceeds the {MAX_IMPORT_ROWS:,}-row safety limit."
        )
    return (
        ParsedRow(
            row_number=int(
                row_number
            ),
            raw=raw,
        ),
        next_count,
    )


def _detect_csv_encoding(
    payload: bytes,
) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in (
        "utf-8-sig",
        "utf-8",
        "cp1256",
    ):
        decoder = (
            codecs.getincrementaldecoder(
                encoding
            )(
                errors="strict"
            )
        )
        try:
            for offset in range(
                0,
                len(payload),
                _CSV_DECODE_CHUNK_BYTES,
            ):
                decoder.decode(
                    payload[
                        offset:
                        offset
                        + _CSV_DECODE_CHUNK_BYTES
                    ],
                    final=False,
                )
            decoder.decode(
                b"",
                final=True,
            )
            return encoding
        except UnicodeDecodeError as exc:
            last_error = exc

    raise ProductImportTerminalError(
        "CSV encoding is not supported."
    ) from last_error


def _csv_dialect(
    payload: bytes,
    *,
    encoding: str,
) -> csv.Dialect:
    sample = payload[
        :_CSV_SNIFF_BYTES
    ].decode(
        encoding,
        errors="ignore",
    )
    try:
        return csv.Sniffer().sniff(
            sample,
            delimiters=",;\t|",
        )
    except csv.Error:
        return csv.excel


def _iter_csv_rows(
    reader: csv.reader,
    layout: list[tuple[int, str]],
) -> Iterator[ParsedRow]:
    accepted_count = 0

    while True:
        source_row_number = (
            int(reader.line_num)
            + 1
        )
        try:
            values = next(reader)
        except StopIteration:
            break

        raw = _row_from_layout(
            values,
            layout,
        )
        (
            parsed,
            accepted_count,
        ) = _count_and_yield(
            row_number=
                source_row_number,
            raw=raw,
            accepted_count=
                accepted_count,
        )
        if parsed is not None:
            yield parsed

    if accepted_count == 0:
        raise ProductImportTerminalError(
            "The file contains no product rows."
        )


@contextmanager
def _open_csv_source(
    payload: bytes,
    *,
    max_columns: int = MAX_IMPORT_COLUMNS,
) -> Iterator[ParsedSource]:
    encoding = (
        _detect_csv_encoding(
            payload
        )
    )
    dialect = _csv_dialect(
        payload,
        encoding=encoding,
    )

    with io.BytesIO(
        payload
    ) as binary_stream:
        with io.TextIOWrapper(
            binary_stream,
            encoding=encoding,
            newline="",
        ) as text_stream:
            reader = csv.reader(
                text_stream,
                dialect=dialect,
            )
            first = next(
                reader,
                None,
            )
            if first is None:
                raise ProductImportTerminalError(
                    "The file is empty."
                )

            layout = (
                _header_layout(
                    first,
                    max_columns=
                        max_columns,
                )
            )
            headers = [
                header
                for _, header
                in layout
            ]
            yield ParsedSource(
                headers=headers,
                rows=_iter_csv_rows(
                    reader,
                    layout,
                ),
            )


def _validate_xlsx_archive(
    payload: bytes,
) -> None:
    try:
        with io.BytesIO(
            payload
        ) as archive_stream:
            with zipfile.ZipFile(
                archive_stream
            ) as archive:
                infos = (
                    archive.infolist()
                )
                if not infos:
                    raise ProductImportTerminalError(
                        "The Excel file is empty or invalid."
                    )
                if (
                    len(infos)
                    > MAX_XLSX_ARCHIVE_ENTRIES
                ):
                    raise ProductImportTerminalError(
                        "The Excel archive has an abnormal number of internal entries."
                    )

                total = 0
                for info in infos:
                    total += int(
                        info.file_size
                    )
                    if (
                        total
                        > MAX_XLSX_UNCOMPRESSED_BYTES
                    ):
                        raise ProductImportTerminalError(
                            "The uncompressed Excel content exceeds the safety limit."
                        )
                    if (
                        info.compress_size
                        > 0
                        and info.file_size
                        > 1_000_000
                        and (
                            info.file_size
                            / info.compress_size
                        )
                        > MAX_XLSX_COMPRESSION_RATIO
                    ):
                        raise ProductImportTerminalError(
                            "The Excel file was rejected because of an abnormal compression ratio."
                        )
                    if (
                        info.filename
                        .lower()
                        .endswith(
                            "vbaproject.bin"
                        )
                    ):
                        raise ProductImportTerminalError(
                            "Macro-enabled Excel files are not supported."
                        )
    except zipfile.BadZipFile as exc:
        raise ProductImportTerminalError(
            "The Excel file is invalid or corrupted."
        ) from exc


def _iter_xlsx_rows(
    iterator: Iterator[
        tuple[Any, ...]
    ],
    layout: list[tuple[int, str]],
) -> Iterator[ParsedRow]:
    accepted_count = 0
    for (
        row_number,
        values,
    ) in enumerate(
        iterator,
        start=2,
    ):
        raw = _row_from_layout(
            values,
            layout,
        )
        (
            parsed,
            accepted_count,
        ) = _count_and_yield(
            row_number=row_number,
            raw=raw,
            accepted_count=
                accepted_count,
        )
        if parsed is not None:
            yield parsed

    if accepted_count == 0:
        raise ProductImportTerminalError(
            "The file contains no product rows."
        )


@contextmanager
def _open_xlsx_source(
    payload: bytes,
    *,
    max_columns: int = MAX_IMPORT_COLUMNS,
) -> Iterator[ParsedSource]:
    # Security inspection must finish before OpenPyXL traverses the workbook.
    _validate_xlsx_archive(
        payload
    )

    with io.BytesIO(
        payload
    ) as workbook_stream:
        try:
            reader = (
                _load_bounded_workbook(
                    workbook_stream
                )
            )
            workbook = reader.wb
        except Exception as exc:
            raise ProductImportTerminalError(
                "The Excel file could not be opened."
            ) from exc

        try:
            sheet = workbook.active
            iterator = sheet.iter_rows(
                values_only=True
            )
            first = next(
                iterator,
                None,
            )
            if first is None:
                raise ProductImportTerminalError(
                    "The file is empty."
                )

            layout = (
                _header_layout(
                    first,
                    max_columns=
                        max_columns,
                )
            )
            headers = [
                header
                for _, header
                in layout
            ]
            yield ParsedSource(
                headers=headers,
                rows=_iter_xlsx_rows(
                    iterator,
                    layout,
                ),
            )
        finally:
            try:
                workbook.close()
            finally:
                reader.close_bounded_resources(
                    close_archive=False
                )


@contextmanager
def open_source(
    file_name: str,
    payload: bytes,
    *,
    max_columns: int = MAX_IMPORT_COLUMNS,
) -> Iterator[ParsedSource]:
    suffix = (
        file_name
        .lower()
        .rsplit(
            ".",
            1,
        )[-1]
        if "." in file_name
        else ""
    )

    if suffix == "csv":
        with _open_csv_source(
            payload,
            max_columns=
                max_columns,
        ) as source:
            yield source
        return

    if suffix == "xlsx":
        with _open_xlsx_source(
            payload,
            max_columns=
                max_columns,
        ) as source:
            yield source
        return

    raise ProductImportTerminalError(
        "Only CSV and XLSX files are supported."
    )
