"""Product Import source-capacity metrics backed by durable counters."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import psycopg

from domains.simple_products.imports.infrastructure.queue_dsn import (
    product_import_psycopg_dsn,
)


@dataclass(frozen=True, slots=True)
class ProductImportCapacityMetrics:
    company_id: int
    live_source_bytes: int
    high_water_source_bytes: int
    oldest_live_source_age_seconds: int
    quota_rejections_last_hour: int
    active_jobs: int
    oldest_active_job_age_seconds: int
    oldest_queued_job_age_seconds: int

    def as_dict(
        self,
    ) -> dict[str, int]:
        return asdict(
            self
        )


async def read_global_source_capacity_metrics(
) -> dict[str, int]:
    async with await psycopg.AsyncConnection.connect(
        product_import_psycopg_dsn()
    ) as connection:
        cursor = await connection.execute(
            """
            SELECT
                live_bytes,
                high_water_bytes
            FROM product_import_global_source_capacity
            WHERE id = 1
            """
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError(
                "Product Import global capacity counter is missing."
            )
        return {
            "live_source_bytes":
                int(
                    row[
                        0
                    ]
                    or 0
                ),
            "high_water_source_bytes":
                int(
                    row[
                        1
                    ]
                    or 0
                ),
        }


async def read_tenant_source_capacity_metrics(
    *,
    company_id: int,
) -> ProductImportCapacityMetrics:
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
                    live_bytes,
                    high_water_bytes
                FROM product_import_tenant_source_capacity
                WHERE company_id = %s
                """,
                [
                    int(
                        company_id
                    )
                ],
            )
            row = await cursor.fetchone()
            (
                live_bytes,
                high_water_bytes,
            ) = (
                (
                    int(
                        row[
                            0
                        ]
                        or 0
                    ),
                    int(
                        row[
                            1
                        ]
                        or 0
                    ),
                )
                if row is not None
                else (
                    0,
                    0,
                )
            )

            cursor = await connection.execute(
                """
                SELECT
                    COALESCE(
                        EXTRACT(
                            EPOCH FROM (
                                CURRENT_TIMESTAMP
                                - min(created_at)
                            )
                        ),
                        0
                    )::bigint
                FROM product_import_sources
                WHERE company_id = %s
                  AND deleted_at IS NULL
                """,
                [
                    int(
                        company_id
                    )
                ],
            )
            oldest_age = int(
                (
                    await cursor.fetchone()
                )[
                    0
                ]
                or 0
            )

            cursor = await connection.execute(
                """
                SELECT count(*)::bigint
                FROM product_import_admission_rejections
                WHERE company_id = %s
                  AND created_at >= (
                      CURRENT_TIMESTAMP
                      - INTERVAL '1 hour'
                  )
                """,
                [
                    int(
                        company_id
                    )
                ],
            )
            rejection_count = int(
                (
                    await cursor.fetchone()
                )[
                    0
                ]
                or 0
            )

            cursor = await connection.execute(
                """
                SELECT
                    count(*) FILTER (
                        WHERE status IN (
                            'QUEUED',
                            'PARSING',
                            'NEEDS_MAPPING',
                            'VALIDATING',
                            'IMPORTING',
                            'RETRYING'
                        )
                    )::bigint,
                    COALESCE(
                        EXTRACT(
                            EPOCH FROM (
                                CURRENT_TIMESTAMP
                                - (
                                    min(updated_at) FILTER (
                                        WHERE status IN (
                                            'PARSING',
                                            'VALIDATING',
                                            'IMPORTING',
                                            'RETRYING'
                                        )
                                    )
                                )
                            )
                        ),
                        0
                    )::bigint,
                    COALESCE(
                        EXTRACT(
                            EPOCH FROM (
                                CURRENT_TIMESTAMP
                                - (
                                    min(created_at) FILTER (
                                        WHERE status = 'QUEUED'
                                    )
                                )
                            )
                        ),
                        0
                    )::bigint
                FROM product_import_jobs
                WHERE company_id = %s
                """,
                [
                    int(
                        company_id
                    )
                ],
            )
            runtime_row = (
                await cursor.fetchone()
            )
            active_jobs = int(
                runtime_row[
                    0
                ]
                or 0
            )
            oldest_active_job_age = int(
                runtime_row[
                    1
                ]
                or 0
            )
            oldest_queued_job_age = int(
                runtime_row[
                    2
                ]
                or 0
            )

            return ProductImportCapacityMetrics(
                company_id=int(
                    company_id
                ),
                live_source_bytes=
                    live_bytes,
                high_water_source_bytes=
                    high_water_bytes,
                oldest_live_source_age_seconds=
                    oldest_age,
                quota_rejections_last_hour=
                    rejection_count,
                active_jobs=
                    active_jobs,
                oldest_active_job_age_seconds=
                    oldest_active_job_age,
                oldest_queued_job_age_seconds=
                    oldest_queued_job_age,
            )
