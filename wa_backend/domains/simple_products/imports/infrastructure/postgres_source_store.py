"""PostgreSQL-chunk adapter for the Product Import SourceStore port."""
from __future__ import annotations

import hashlib
from io import BytesIO
from typing import BinaryIO
from uuid import UUID, uuid4

import psycopg

from domains.simple_products.imports.application.source_store import (
    ProductImportSourceIntegrityError,
    ProductImportSourceMissingError,
    ProductImportSourceRef,
)
from domains.simple_products.imports.infrastructure.queue_dsn import (
    product_import_psycopg_dsn,
)


SOURCE_CHUNK_BYTES = (
    256
    * 1024
)
_STORAGE_BACKEND = (
    "POSTGRES_CHUNKS"
)


class PostgresProductImportSourceStore:
    """Immutable source storage backed by bounded PostgreSQL chunks."""

    async def persist_stream_on_connection(
        self,
        *,
        connection,
        company_id: int,
        stream: BinaryIO,
        byte_size: int,
        sha256: str,
    ) -> ProductImportSourceRef:
        expected_size = int(
            byte_size
        )
        expected_hash = str(
            sha256
        ).lower()
        if expected_size <= 0:
            raise ValueError(
                "Source byte_size must be positive."
            )
        if (
            len(
                expected_hash
            )
            != 64
            or any(
                char
                not in "0123456789abcdef"
                for char
                in expected_hash
            )
        ):
            raise ValueError(
                "Source SHA-256 is invalid."
            )

        source_id = uuid4()
        await connection.execute(
            """
            INSERT INTO product_import_sources (
                id,
                company_id,
                sha256,
                byte_size,
                storage_backend,
                created_at,
                deleted_at
            )
            VALUES (
                %s,%s,%s,%s,%s,
                CURRENT_TIMESTAMP,
                NULL
            )
            """,
            [
                source_id,
                int(
                    company_id
                ),
                expected_hash,
                expected_size,
                _STORAGE_BACKEND,
            ],
        )

        digest = hashlib.sha256()
        persisted_size = 0
        chunk_index = 0
        stream.seek(
            0
        )
        while True:
            chunk = stream.read(
                SOURCE_CHUNK_BYTES
            )
            if not chunk:
                break
            chunk = bytes(
                chunk
            )
            persisted_size += len(
                chunk
            )
            digest.update(
                chunk
            )
            await connection.execute(
                """
                INSERT INTO product_import_source_chunks (
                    company_id,
                    source_id,
                    chunk_index,
                    byte_size,
                    payload,
                    created_at
                )
                VALUES (
                    %s,%s,%s,%s,%s,
                    CURRENT_TIMESTAMP
                )
                """,
                [
                    int(
                        company_id
                    ),
                    source_id,
                    int(
                        chunk_index
                    ),
                    len(
                        chunk
                    ),
                    chunk,
                ],
            )
            chunk_index += 1

        stream.seek(
            0
        )

        actual_hash = (
            digest.hexdigest()
        )
        if (
            persisted_size
            != expected_size
            or actual_hash
            != expected_hash
        ):
            raise ProductImportSourceIntegrityError(
                "Product Import source changed while it was being persisted."
            )

        return ProductImportSourceRef(
            source_id=source_id,
            byte_size=expected_size,
            sha256=expected_hash,
            storage_backend=
                _STORAGE_BACKEND,
        )

    async def _verify_on_connection(
        self,
        connection,
        *,
        company_id: int,
        source_id: UUID,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        cursor = await connection.execute(
            """
            SELECT
                byte_size,
                sha256,
                storage_backend,
                deleted_at
            FROM product_import_sources
            WHERE company_id = %s
              AND id = %s
            """,
            [
                int(
                    company_id
                ),
                source_id,
            ],
        )
        row = await cursor.fetchone()
        if row is None:
            raise ProductImportSourceMissingError(
                "Product Import source metadata was not found."
            )

        (
            stored_size,
            stored_hash,
            storage_backend,
            deleted_at,
        ) = row
        if (
            deleted_at is not None
        ):
            raise ProductImportSourceMissingError(
                "Product Import source bytes have already been cleaned up."
            )
        if (
            str(
                storage_backend
            )
            != _STORAGE_BACKEND
        ):
            raise ProductImportSourceIntegrityError(
                "Product Import source storage backend does not match this adapter."
            )
        if (
            int(
                stored_size
            )
            != int(
                expected_size
            )
            or str(
                stored_hash
            )
            != str(
                expected_sha256
            ).lower()
        ):
            raise ProductImportSourceIntegrityError(
                "Product Import source metadata does not match the job snapshot."
            )

        digest = hashlib.sha256()
        actual_size = 0
        expected_chunk_index = 0

        async with connection.cursor(
            name=(
                "product_import_source_verify_"
                + source_id.hex
            )
        ) as chunks:
            await chunks.execute(
                """
                SELECT
                    chunk_index,
                    byte_size,
                    payload
                FROM product_import_source_chunks
                WHERE company_id = %s
                  AND source_id = %s
                ORDER BY chunk_index ASC
                """,
                [
                    int(
                        company_id
                    ),
                    source_id,
                ],
            )
            async for (
                chunk_index,
                chunk_size,
                payload,
            ) in chunks:
                if (
                    int(
                        chunk_index
                    )
                    != expected_chunk_index
                ):
                    raise ProductImportSourceIntegrityError(
                        "Product Import source chunk sequence is incomplete."
                    )
                chunk = bytes(
                    payload
                )
                if len(
                    chunk
                ) != int(
                    chunk_size
                ):
                    raise ProductImportSourceIntegrityError(
                        "Product Import source chunk size is corrupted."
                    )
                digest.update(
                    chunk
                )
                actual_size += len(
                    chunk
                )
                expected_chunk_index += 1

        if (
            actual_size
            != int(
                expected_size
            )
            or digest.hexdigest()
            != str(
                expected_sha256
            ).lower()
        ):
            raise ProductImportSourceIntegrityError(
                "Product Import source hash verification failed."
            )

    async def read_verified_bytes(
        self,
        *,
        company_id: int,
        source_id: UUID,
        expected_size: int,
        expected_sha256: str,
    ) -> bytes:
        async with await psycopg.AsyncConnection.connect(
            product_import_psycopg_dsn()
        ) as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config("
                    "'app.current_tenant', %s, true)",
                    [
                        str(
                            int(
                                company_id
                            )
                        )
                    ],
                )
                await self._verify_on_connection(
                    connection,
                    company_id=
                        int(
                            company_id
                        ),
                    source_id=
                        source_id,
                    expected_size=
                        int(
                            expected_size
                        ),
                    expected_sha256=
                        str(
                            expected_sha256
                        ),
                )

                output = BytesIO()
                async with connection.cursor(
                    name=(
                        "product_import_source_read_"
                        + source_id.hex
                    )
                ) as chunks:
                    await chunks.execute(
                        """
                        SELECT payload
                        FROM product_import_source_chunks
                        WHERE company_id = %s
                          AND source_id = %s
                        ORDER BY chunk_index ASC
                        """,
                        [
                            int(
                                company_id
                            ),
                            source_id,
                        ],
                    )
                    async for (
                        payload,
                    ) in chunks:
                        output.write(
                            bytes(
                                payload
                            )
                        )
                return output.getvalue()

    async def delete_source_bytes_batch(
        self,
        *,
        company_id: int,
        source_ids: list[UUID],
    ) -> int:
        if not source_ids:
            return 0
        async with await psycopg.AsyncConnection.connect(
            product_import_psycopg_dsn()
        ) as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config("
                    "'app.current_tenant', %s, true)",
                    [
                        str(
                            int(
                                company_id
                            )
                        )
                    ],
                )

                return await self.delete_source_bytes_batch_on_connection(
                    connection=connection, company_id=company_id, source_ids=source_ids,
                )

    async def delete_source_bytes_batch_on_connection(
        self,
        *,
        connection: psycopg.AsyncConnection,
        company_id: int,
        source_ids: list[UUID],
    ) -> int:
        # Caller owns tenant setup, transaction and any necessary job locks.
        if not source_ids:
            return 0
        if len(
            source_ids
        ) > 1_000:
            raise ValueError(
                "Source cleanup batch cannot exceed 1000 sources."
            )

        normalized_ids = [
            UUID(
                str(
                    source_id
                )
            )
            for source_id
            in source_ids
        ]
        if len(
            normalized_ids
        ) != len(
            set(
                normalized_ids
            )
        ):
            raise ValueError(
                "Source cleanup batch contains duplicate source ids."
            )

        cursor = await connection.execute(
            """
            SELECT
                id,
                byte_size
            FROM product_import_sources
            WHERE company_id = %s
              AND id = ANY(%s::uuid[])
              AND deleted_at IS NULL
            ORDER BY id
            FOR UPDATE
            """,
            [
                int(
                    company_id
                ),
                [
                    str(
                        source_id
                    )
                    for source_id
                    in normalized_ids
                ],
            ],
        )
        rows = await cursor.fetchall()
        if not rows:
            return 0

        live_ids = [
            UUID(
                str(
                    source_id
                )
            )
            for (
                source_id,
                _byte_size,
            )
            in rows
        ]
        total_bytes = sum(
            int(
                byte_size
            )
            for (
                _source_id,
                byte_size,
            )
            in rows
        )

        await connection.execute(
            """
            DELETE FROM product_import_source_chunks
            WHERE company_id = %s
              AND source_id = ANY(%s::uuid[])
            """,
            [
                int(
                    company_id
                ),
                [
                    str(
                        source_id
                    )
                    for source_id
                    in live_ids
                ],
            ],
        )
        result = await connection.execute(
            """
            UPDATE product_import_sources
            SET deleted_at = CURRENT_TIMESTAMP
            WHERE company_id = %s
              AND id = ANY(%s::uuid[])
              AND deleted_at IS NULL
            """,
            [
                int(
                    company_id
                ),
                [
                    str(
                        source_id
                    )
                    for source_id
                    in live_ids
                ],
            ],
        )
        cleaned = int(
            result.rowcount
            or 0
        )
        if cleaned != len(
            live_ids
        ):
            raise ProductImportSourceIntegrityError(
                "Product Import source cleanup changed concurrently."
            )

        tenant_counter = await connection.execute(
            """
            UPDATE product_import_tenant_source_capacity
            SET live_bytes =
                    live_bytes - %s,
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE company_id = %s
              AND live_bytes >= %s
            """,
            [
                total_bytes,
                int(
                    company_id
                ),
                total_bytes,
            ],
        )
        global_counter = await connection.execute(
            """
            UPDATE product_import_global_source_capacity
            SET live_bytes =
                    live_bytes - %s,
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE id = 1
              AND live_bytes >= %s
            """,
            [
                total_bytes,
                total_bytes,
            ],
        )
        if (
            int(
                tenant_counter.rowcount
                or 0
            )
            != 1
            or int(
                global_counter.rowcount
                or 0
            )
            != 1
        ):
            raise ProductImportSourceIntegrityError(
                "Product Import source capacity counters are inconsistent."
            )
        return cleaned


    async def delete_source_bytes(
        self,
        *,
        company_id: int,
        source_id: UUID,
    ) -> bool:
        async with await psycopg.AsyncConnection.connect(
            product_import_psycopg_dsn()
        ) as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config("
                    "'app.current_tenant', %s, true)",
                    [
                        str(
                            int(
                                company_id
                            )
                        )
                    ],
                )
                cursor = await connection.execute(
                    """
                    SELECT
                        byte_size,
                        deleted_at
                    FROM product_import_sources
                    WHERE company_id = %s
                      AND id = %s
                    FOR UPDATE
                    """,
                    [
                        int(
                            company_id
                        ),
                        source_id,
                    ],
                )
                row = await cursor.fetchone()
                if row is None:
                    return False

                (
                    source_size,
                    deleted_at,
                ) = row
                if deleted_at is not None:
                    return False

                await connection.execute(
                    """
                    DELETE FROM product_import_source_chunks
                    WHERE company_id = %s
                      AND source_id = %s
                    """,
                    [
                        int(
                            company_id
                        ),
                        source_id,
                    ],
                )
                result = await connection.execute(
                    """
                    UPDATE product_import_sources
                    SET deleted_at = CURRENT_TIMESTAMP
                    WHERE company_id = %s
                      AND id = %s
                      AND deleted_at IS NULL
                    """,
                    [
                        int(
                            company_id
                        ),
                        source_id,
                    ],
                )
                if int(
                    result.rowcount
                    or 0
                ) != 1:
                    return False

                source_size = int(
                    source_size
                )
                tenant_counter = (
                    await connection.execute(
                        """
                        UPDATE product_import_tenant_source_capacity
                        SET live_bytes =
                                live_bytes - %s,
                            updated_at =
                                CURRENT_TIMESTAMP
                        WHERE company_id = %s
                          AND live_bytes >= %s
                        """,
                        [
                            source_size,
                            int(
                                company_id
                            ),
                            source_size,
                        ],
                    )
                )
                global_counter = (
                    await connection.execute(
                        """
                        UPDATE product_import_global_source_capacity
                        SET live_bytes =
                                live_bytes - %s,
                            updated_at =
                                CURRENT_TIMESTAMP
                        WHERE id = 1
                          AND live_bytes >= %s
                        """,
                        [
                            source_size,
                            source_size,
                        ],
                    )
                )
                if (
                    int(
                        tenant_counter.rowcount
                        or 0
                    )
                    != 1
                    or int(
                        global_counter.rowcount
                        or 0
                    )
                    != 1
                ):
                    raise ProductImportSourceIntegrityError(
                        "Product Import source capacity counters are inconsistent."
                    )
                return True


POSTGRES_PRODUCT_IMPORT_SOURCE_STORE = (
    PostgresProductImportSourceStore()
)
