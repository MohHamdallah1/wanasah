"""Product Import worker/queue runtime observability."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import os

import psycopg

from domains.simple_products.imports.infrastructure.queue_dsn import (
    product_import_psycopg_dsn,
)


def _positive_env_int(
    name: str,
    default: int,
) -> int:
    try:
        value = int(
            os.getenv(
                name,
                str(
                    default
                ),
            )
        )
    except ValueError as exc:
        raise RuntimeError(
            f"{name} must be a positive integer."
        ) from exc
    if value <= 0:
        raise RuntimeError(
            f"{name} must be a positive integer."
        )
    return value


WORKER_HEALTH_TIMEOUT_SECONDS = _positive_env_int(
    "PRODUCT_IMPORT_WORKER_HEALTH_TIMEOUT_SECONDS",
    30,
)
WORKER_SLOTS_PER_PROCESS = _positive_env_int(
    "PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS",
    1,
)
QUEUE_AGE_ALERT_SECONDS = _positive_env_int(
    "PRODUCT_IMPORT_QUEUE_AGE_ALERT_SECONDS",
    120,
)
STUCK_STAGE_ALERT_SECONDS = _positive_env_int(
    "PRODUCT_IMPORT_STUCK_STAGE_SECONDS",
    900,
)


@dataclass(frozen=True, slots=True)
class ProductImportRuntimeMetrics:
    healthy_worker_processes: int
    configured_worker_slots: int
    running_jobs: int
    queued_jobs: int
    available_worker_slots: int
    oldest_queue_age_seconds: int

    @property
    def ready(
        self,
    ) -> bool:
        return (
            self.healthy_worker_processes
            > 0
        )

    def as_dict(
        self,
    ) -> dict[str, int]:
        return asdict(
            self
        )


async def register_product_import_worker(
    worker_id: int,
) -> None:
    """Bind one live Procrastinate worker to the Product Import queue."""
    resolved_worker_id = int(
        worker_id
    )
    if resolved_worker_id <= 0:
        raise ValueError(
            "worker_id must be positive."
        )

    async with await psycopg.AsyncConnection.connect(
        product_import_psycopg_dsn()
    ) as connection:
        await connection.execute(
            """
            INSERT INTO product_import_worker_registry (
                worker_id,
                last_seen_at
            )
            VALUES (
                %s,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (worker_id)
            DO UPDATE
            SET last_seen_at = CURRENT_TIMESTAMP
            """,
            [
                resolved_worker_id
            ],
        )
        await connection.commit()


async def read_product_import_runtime_metrics(
) -> ProductImportRuntimeMetrics:
    """Read global queue metrics without exposing them to tenant payloads."""
    async with await psycopg.AsyncConnection.connect(
        product_import_psycopg_dsn()
    ) as connection:
        cursor = await connection.execute(
            """
            SELECT count(*)::bigint
            FROM product_import_worker_registry AS registry
            JOIN procrastinate_workers AS workers
              ON workers.id = registry.worker_id
            WHERE workers.last_heartbeat >= (
                CURRENT_TIMESTAMP
                - (%s * INTERVAL '1 second')
            )
            """,
            [
                int(
                    WORKER_HEALTH_TIMEOUT_SECONDS
                )
            ],
        )
        healthy_workers = int(
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
                    WHERE jobs.status = 'todo'
                )::bigint,
                count(*) FILTER (
                    WHERE jobs.status = 'doing'
                )::bigint,
                COALESCE(
                    GREATEST(
                        EXTRACT(
                            EPOCH FROM (
                                CURRENT_TIMESTAMP
                                - (
                                    min(
                                        COALESCE(
                                            jobs.scheduled_at,
                                            first_defer.enqueued_at,
                                            CURRENT_TIMESTAMP
                                        )
                                    ) FILTER (
                                        WHERE jobs.status = 'todo'
                                    )
                                )
                            )
                        ),
                        0
                    ),
                    0
                )::bigint
            FROM procrastinate_jobs AS jobs
            LEFT JOIN LATERAL (
                SELECT min(events.at) AS enqueued_at
                FROM procrastinate_events AS events
                WHERE events.job_id = jobs.id
                  AND events.type IN ('deferred', 'deferred_for_retry', 'retried')
            ) AS first_defer ON TRUE
            WHERE jobs.queue_name = 'product-import'
              AND jobs.task_name = 'wanasah.process_product_import'
              AND jobs.status IN ('todo','doing')
            """
        )
        row = await cursor.fetchone()
        queued_jobs = int(
            row[
                0
            ]
            or 0
        )
        running_jobs = int(
            row[
                1
            ]
            or 0
        )
        oldest_queue_age = int(
            row[
                2
            ]
            or 0
        )

    configured_slots = (
        healthy_workers
        * int(
            WORKER_SLOTS_PER_PROCESS
        )
    )
    return ProductImportRuntimeMetrics(
        healthy_worker_processes=
            healthy_workers,
        configured_worker_slots=
            configured_slots,
        running_jobs=
            running_jobs,
        queued_jobs=
            queued_jobs,
        available_worker_slots=
            max(
                configured_slots
                - running_jobs,
                0,
            ),
        oldest_queue_age_seconds=
            oldest_queue_age,
    )
