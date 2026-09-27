"""Application port for immutable Product Import source storage."""
from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Protocol
from uuid import UUID

from domains.simple_products.imports.domain.errors import (
    ProductImportTerminalError,
)


@dataclass(frozen=True, slots=True)
class ProductImportSourceRef:
    source_id: UUID
    byte_size: int
    sha256: str
    storage_backend: str


class ProductImportSourceIntegrityError(
    ProductImportTerminalError
):
    """Stored source no longer matches its immutable metadata."""


class ProductImportSourceMissingError(
    ProductImportTerminalError
):
    """Expected immutable source bytes are no longer available."""


class SourceStore(Protocol):
    async def read_verified_bytes(
        self,
        *,
        company_id: int,
        source_id: UUID,
        expected_size: int,
        expected_sha256: str,
    ) -> bytes:
        """Read one immutable source after streaming integrity verification."""

    async def delete_source_bytes(
        self,
        *,
        company_id: int,
        source_id: UUID,
    ) -> bool:
        """Delete retained bytes while preserving immutable source metadata."""


class TransactionalSourceStore(
    SourceStore,
    Protocol,
):
    async def persist_stream_on_connection(
        self,
        *,
        connection,
        company_id: int,
        stream: BinaryIO,
        byte_size: int,
        sha256: str,
    ) -> ProductImportSourceRef:
        """Persist one bounded stream inside the caller's database transaction."""
