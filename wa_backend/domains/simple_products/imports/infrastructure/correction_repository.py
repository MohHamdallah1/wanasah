"""Atomic persistence adapter for Product Import correction uploads."""
from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from domains.simple_products.imports.application.state_machine import (
    JobStatus,
    assert_job_transition,
)
from domains.simple_products.imports.infrastructure.queue import (
    DSN,
    defer_import_on_connection,
)


_CORRECTION_OPERATION = (
    "PRODUCT_IMPORT_CORRECTION"
)


async def _set_tenant(
    conn: psycopg.AsyncConnection,
    company_id: int,
) -> None:
    await conn.execute(
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


async def _begin_correction_idempotency(
    conn: psycopg.AsyncConnection,
    *,
    company_id: int,
    actor_id: int,
    request_id: UUID,
    request_hash: str,
) -> dict[str, Any] | None:
    request_text = str(
        UUID(
            str(
                request_id
            )
        )
    )
    canonical_hash = (
        str(
            request_hash
        )
        .strip()
        .lower()
    )
    if (
        len(
            canonical_hash
        )
        != 64
        or any(
            ch
            not in "0123456789abcdef"
            for ch
            in canonical_hash
        )
    ):
        raise ValueError(
            "Correction request hash is invalid."
        )

    await conn.execute(
        "SELECT pg_advisory_xact_lock("
        "%s, hashtext(%s))",
        [
            int(
                company_id
            ),
            (
                "op-idempotency:"
                f"{_CORRECTION_OPERATION}:"
                f"{request_text}"
            ),
        ],
    )

    cursor = await conn.execute(
        """
        SELECT
            created_by,
            request_hash,
            response_json,
            completed_at
        FROM operation_idempotency
        WHERE company_id = %s
          AND operation = %s
          AND request_id = %s
        FOR UPDATE
        """,
        [
            int(
                company_id
            ),
            _CORRECTION_OPERATION,
            request_text,
        ],
    )
    existing = await cursor.fetchone()
    if existing is not None:
        (
            existing_actor,
            existing_hash,
            response_json,
            completed_at,
        ) = existing
        if int(
            existing_actor
        ) != int(
            actor_id
        ):
            raise ValueError(
                "Correction request_id belongs to another actor."
            )
        if str(
            existing_hash
        ) != canonical_hash:
            raise ValueError(
                "Correction request_id was reused with different content."
            )
        if (
            completed_at
            is None
            or not isinstance(
                response_json,
                dict,
            )
        ):
            raise RuntimeError(
                "Correction idempotency record is incomplete."
            )

        replay = dict(
            response_json
        )
        replay[
            "replayed"
        ] = True
        return replay

    await conn.execute(
        """
        INSERT INTO operation_idempotency (
            company_id,
            operation,
            request_id,
            request_hash,
            created_by,
            response_json,
            created_at,
            completed_at
        )
        VALUES (
            %s,%s,%s,%s,%s,
            NULL,CURRENT_TIMESTAMP,NULL
        )
        """,
        [
            int(
                company_id
            ),
            _CORRECTION_OPERATION,
            request_text,
            canonical_hash,
            int(
                actor_id
            ),
        ],
    )
    return None


async def _load_correctable_job_status(
    conn: psycopg.AsyncConnection,
    *,
    company_id: int,
    job_id: UUID,
) -> str:
    cursor = await conn.execute(
        """
        SELECT status
        FROM product_import_jobs
        WHERE company_id = %s
          AND id = %s
        FOR UPDATE
        """,
        [
            int(
                company_id
            ),
            job_id,
        ],
    )
    row = await cursor.fetchone()
    if row is None:
        raise ValueError(
            "Import job was not found."
        )

    status = str(
        row[
            0
        ]
    )
    if status not in {
        JobStatus.VALIDATION_FAILED.value,
        JobStatus.COMPLETED_WITH_ERRORS.value,
    }:
        raise ValueError(
            "Import job is not awaiting failed-row correction."
        )

    assert_job_transition(
        status,
        JobStatus.VALIDATING.value,
    )
    return status


async def _stage_corrections(
    conn: psycopg.AsyncConnection,
    *,
    corrections: list[
        dict[str, Any]
    ],
) -> list[UUID]:
    identities = [
        UUID(
            str(
                item[
                    "row_identity"
                ]
            )
        )
        for item in corrections
    ]
    if len(
        identities
    ) != len(
        set(
            identities
        )
    ):
        raise ValueError(
            "Correction contains duplicate row identities."
        )

    await conn.execute(
        """
        CREATE TEMP TABLE
            product_import_correction_input (
                row_identity uuid PRIMARY KEY,
                raw_data jsonb NOT NULL
            )
        ON COMMIT DROP
        """
    )
    async with conn.cursor() as cursor:
        await cursor.executemany(
            """
            INSERT INTO product_import_correction_input (
                row_identity,
                raw_data
            )
            VALUES (%s, %s)
            """,
            [
                (
                    identity,
                    Jsonb(
                        dict(
                            correction[
                                "raw_data"
                            ]
                        )
                    ),
                )
                for (
                    identity,
                    correction,
                )
                in zip(
                    identities,
                    corrections,
                    strict=True,
                )
            ],
        )

    return identities


async def _assert_correction_targets(
    conn: psycopg.AsyncConnection,
    *,
    company_id: int,
    job_id: UUID,
) -> None:
    cursor = await conn.execute(
        """
        SELECT
            count(*) FILTER (
                WHERE rows.id IS NULL
            ) AS unknown_count,
            count(*) FILTER (
                WHERE rows.status = 'IMPORTED'
            ) AS imported_count,
            count(*) FILTER (
                WHERE rows.id IS NOT NULL
                  AND rows.status NOT IN (
                    'INVALID',
                    'IMPORT_FAILED'
                  )
            ) AS ineligible_count
        FROM product_import_correction_input AS correction
        LEFT JOIN product_import_rows AS rows
          ON rows.company_id = %s
         AND rows.job_id = %s
         AND rows.row_identity = correction.row_identity
        """,
        [
            int(
                company_id
            ),
            job_id,
        ],
    )
    (
        unknown_count,
        imported_count,
        ineligible_count,
    ) = await cursor.fetchone()

    if int(
        unknown_count
        or 0
    ):
        raise ValueError(
            "Correction contains a row identity that does not belong to this import."
        )
    if int(
        imported_count
        or 0
    ):
        raise ValueError(
            "Correction cannot modify an already imported row."
        )
    if int(
        ineligible_count
        or 0
    ):
        raise ValueError(
            "Correction can update only failed Product Import rows."
        )


async def _apply_correction_rows(
    conn: psycopg.AsyncConnection,
    *,
    company_id: int,
    job_id: UUID,
    expected_count: int,
) -> None:
    result = await conn.execute(
        """
        UPDATE product_import_rows AS rows
        SET raw_data = correction.raw_data,
            normalized_data = '{}'::jsonb,
            status = 'STAGED',
            error_code = NULL,
            error_message = NULL,
            product_variant_id = NULL,
            version = rows.version + 1,
            updated_at = CURRENT_TIMESTAMP
        FROM product_import_correction_input AS correction
        WHERE rows.company_id = %s
          AND rows.job_id = %s
          AND rows.row_identity = correction.row_identity
          AND rows.status IN (
              'INVALID',
              'IMPORT_FAILED'
          )
        """,
        [
            int(
                company_id
            ),
            job_id,
        ],
    )
    if int(
        result.rowcount
        or 0
    ) != int(
        expected_count
    ):
        raise ValueError(
            "Correction rows changed concurrently."
        )


async def _complete_correction_idempotency(
    conn: psycopg.AsyncConnection,
    *,
    company_id: int,
    request_id: UUID,
    response: dict[str, Any],
) -> None:
    result = await conn.execute(
        """
        UPDATE operation_idempotency
        SET response_json = %s,
            completed_at = CURRENT_TIMESTAMP
        WHERE company_id = %s
          AND operation = %s
          AND request_id = %s
          AND response_json IS NULL
          AND completed_at IS NULL
        """,
        [
            Jsonb(
                response
            ),
            int(
                company_id
            ),
            _CORRECTION_OPERATION,
            str(
                request_id
            ),
        ],
    )
    if int(
        result.rowcount
        or 0
    ) != 1:
        raise RuntimeError(
            "Correction idempotency completion failed."
        )


async def apply_correction_and_requeue(
    *,
    company_id: int,
    actor_id: int,
    job_id: UUID,
    request_id: UUID,
    request_hash: str,
    corrections: list[
        dict[str, Any]
    ],
) -> dict[str, Any]:
    """Update only failed rows and queue the same durable import atomically."""
    if not corrections:
        raise ValueError(
            "Correction file contains no rows."
        )

    async with await psycopg.AsyncConnection.connect(
        DSN
    ) as conn:
        async with conn.transaction():
            await _set_tenant(
                conn,
                company_id,
            )

            replay = (
                await _begin_correction_idempotency(
                    conn,
                    company_id=
                        company_id,
                    actor_id=
                        actor_id,
                    request_id=
                        request_id,
                    request_hash=
                        request_hash,
                )
            )
            if replay is not None:
                return replay

            previous_status = (
                await _load_correctable_job_status(
                    conn,
                    company_id=
                        company_id,
                    job_id=
                        job_id,
                )
            )
            identities = (
                await _stage_corrections(
                    conn,
                    corrections=
                        corrections,
                )
            )
            await _assert_correction_targets(
                conn,
                company_id=
                    company_id,
                job_id=
                    job_id,
            )
            await _apply_correction_rows(
                conn,
                company_id=
                    company_id,
                job_id=
                    job_id,
                expected_count=
                    len(
                        identities
                    ),
            )

            result = await conn.execute(
                """
                UPDATE product_import_jobs
                SET status = %s,
                    error_summary = '{}'::jsonb,
                    finished_at = NULL,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE company_id = %s
                  AND id = %s
                  AND status = %s
                """,
                [
                    JobStatus.VALIDATING.value,
                    int(
                        company_id
                    ),
                    job_id,
                    previous_status,
                ],
            )
            if int(
                result.rowcount
                or 0
            ) != 1:
                raise ValueError(
                    "Import correction state changed concurrently."
                )

            await defer_import_on_connection(
                conn,
                company_id=
                    company_id,
                job_id=
                    job_id,
            )

            response = {
                "job_id":
                    str(
                        job_id
                    ),
                "status":
                    JobStatus.VALIDATING.value,
                "corrected_rows":
                    len(
                        identities
                    ),
                "replayed":
                    False,
            }
            await _complete_correction_idempotency(
                conn,
                company_id=
                    company_id,
                request_id=
                    request_id,
                response=
                    response,
            )
            return response
