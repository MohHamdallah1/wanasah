"""Ephemeral, disk-backed parser handoff; SourceStore remains recovery authority."""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from typing import BinaryIO

from domains.simple_products.imports.domain import ProductImportTerminalError
from domains.simple_products.imports.domain.errors import (
    ProductImportStagingStorageError,
)
from domains.simple_products.imports.infrastructure.parsers import (
    MAX_XLSX_UNCOMPRESSED_BYTES,
    ParsedRow,
)


STAGING_WRITE_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class StagingDiskBudget:
    directory: str
    byte_limit: int
    reserve_bytes: int

    @classmethod
    def from_temp_volume(cls, concurrent_spools: int) -> StagingDiskBudget:
        directory = tempfile.gettempdir()
        # The approved topology has one execution process with two slots.
        # Honor larger configured slot counts without assuming a single spool.
        slots = max(2, concurrent_spools)
        # Two XLSX readers per slot, each with a 64 MiB uncompressed-source
        # ceiling: 256 MiB of working headroom for the default two slots.
        # This is operational headroom, not a bound on SQLite amplification.
        reserve_bytes = slots * 2 * MAX_XLSX_UNCOMPRESSED_BYTES
        free_bytes = shutil.disk_usage(directory).free
        byte_limit = (free_bytes - reserve_bytes) // slots
        if byte_limit <= 0:
            raise ProductImportStagingStorageError(
                "The staging volume has no space above its working reserve.",
                context={"free_bytes": free_bytes, "reserve_bytes": reserve_bytes},
            )
        return cls(directory, byte_limit, reserve_bytes)

    def write_chunk(self, stream: BinaryIO, chunk: bytearray) -> None:
        # Flush every bounded chunk so the next disk check (including another
        # import's check) observes these writes, not a Python output buffer.
        free_bytes = shutil.disk_usage(self.directory).free
        if free_bytes < self.reserve_bytes + len(chunk):
            raise ProductImportStagingStorageError(
                "Writing a staging chunk would consume the disk reserve.",
                context={"free_bytes": free_bytes, "reserve_bytes": self.reserve_bytes},
            )
        written = stream.write(chunk)
        if written != len(chunk):
            raise ProductImportStagingStorageError(
                "The staging spool write was incomplete."
            )
        stream.flush()
        chunk.clear()


@dataclass(slots=True)
class BufferedStageRows:
    stream: BinaryIO
    total_rows: int
    byte_size: int = 0
    byte_limit: int = 0

    def __iter__(self) -> Iterator[ParsedRow]:
        self.stream.seek(0)
        for record in self.stream:
            row_number, raw = json.loads(record)
            yield ParsedRow(row_number=row_number, raw=raw)

    def close(self) -> None:
        self.stream.close()


async def spool_stage_rows(
    rows: Iterable[ParsedRow],
    *,
    max_rows: int,
    yield_every: int,
    concurrent_spools: int = 2,
) -> BufferedStageRows:
    """Finish parsing without borrowing a tenant database connection.

    Store physical row numbers and raw cell metadata verbatim in private JSONL.
    Only one record and a 64 KiB write chunk are materialized at a time.
    The byte limit is a share of actual free disk above parser headroom, not
    an arbitrary source/row-size limit; see ../STAGING_BUFFER.md.
    This file is never a durable checkpoint: every retry must verify and parse
    the immutable SourceStore again. The caller closes it after the single
    atomic staging transaction.
    """
    if max_rows <= 0 or yield_every <= 0 or concurrent_spools <= 0:
        raise ValueError("Staging row and concurrency limits must be positive.")

    stream = None
    total_rows = 0
    byte_size = 0
    chunk = bytearray()
    try:
        budget = StagingDiskBudget.from_temp_volume(concurrent_spools)
        stream = tempfile.TemporaryFile(mode="w+b", dir=budget.directory)
        for parsed in rows:
            total_rows += 1
            if total_rows > max_rows:
                raise ProductImportTerminalError(
                    f"The import exceeds the {max_rows:,}-row safety limit."
                )
            record = (json.dumps(
                [int(parsed.row_number), dict(parsed.raw)],
                ensure_ascii=False,
                separators=(",", ":"),
            ) + "\n").encode("utf-8", errors="backslashreplace")
            # Arabic is direct UTF-8 (2 bytes rather than 6-byte \uXXXX).
            # backslashreplace escapes only isolated surrogates, retaining
            # the previous JSON round trip without writing invalid UTF-8.
            next_size = byte_size + len(record)
            if next_size > budget.byte_limit:
                raise ProductImportStagingStorageError(
                    "The staging spool exceeds its share of free disk.",
                    context={
                        "byte_limit": budget.byte_limit,
                        "required_bytes": next_size,
                    },
                )
            # Split even a large individual row into bounded disk writes.
            with memoryview(record) as record_bytes:
                offset = 0
                while offset < len(record_bytes):
                    take = min(
                        STAGING_WRITE_CHUNK_BYTES - len(chunk),
                        len(record_bytes) - offset,
                    )
                    chunk.extend(record_bytes[offset:offset + take])
                    offset += take
                    if len(chunk) == STAGING_WRITE_CHUNK_BYTES:
                        budget.write_chunk(stream, chunk)
            byte_size = next_size
            if total_rows % yield_every == 0:
                # Keep queue heartbeats and cancellation requests runnable
                # without adding a task, database poll or delivery checkpoint.
                await asyncio.sleep(0)

        if total_rows == 0:
            raise ProductImportTerminalError("The file contains no product rows.")
        if chunk:
            budget.write_chunk(stream, chunk)
        stream.seek(0)
        await asyncio.sleep(0)
        return BufferedStageRows(
            stream=stream, total_rows=total_rows,
            byte_size=byte_size, byte_limit=budget.byte_limit,
        )
    except OSError as exc:
        if stream is not None:
            # A failed buffered flush can fail again on close. Preserve the
            # resource error while close still releases the underlying file.
            with suppress(OSError):
                stream.close()
        raise ProductImportStagingStorageError(
            "Temporary staging storage could not be accessed or written."
        ) from exc
    except BaseException:
        # Includes cooperative task cancellation; no source bytes are released.
        if stream is not None:
            with suppress(OSError):
                stream.close()
        raise
