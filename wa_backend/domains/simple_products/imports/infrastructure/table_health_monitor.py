"""PostgreSQL table-health telemetry for Product Import staging."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import psycopg

from domains.simple_products.imports.infrastructure.queue_dsn import (
    product_import_psycopg_dsn,
)


PRODUCT_IMPORT_HEALTH_TABLES = (
    "product_import_rows",
    "product_import_jobs",
    "product_import_row_barcodes",
)
DEAD_TUPLE_ALERT_PERCENT = 20.0
AUTOVACUUM_LAG_ALERT_SECONDS = 6 * 60 * 60
TRANSACTION_AGE_ALERT = 50_000_000


@dataclass(frozen=True, slots=True)
class ProductImportTableHealth:
    table_name: str
    live_tuples: int
    dead_tuples: int
    dead_tuple_percent: float
    table_bytes: int
    index_bytes: int
    total_bytes: int
    transaction_age: int
    autovacuum_lag_seconds: int
    autoanalyze_lag_seconds: int
    active_vacuum_seconds: int
    autovacuum_count: int
    autoanalyze_count: int
    reloptions: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


async def read_product_import_table_health(
) -> list[ProductImportTableHealth]:
    async with await psycopg.AsyncConnection.connect(
        product_import_psycopg_dsn()
    ) as connection:
        cursor = await connection.execute(
            """
            SELECT
                stats.relname,
                stats.n_live_tup::bigint,
                stats.n_dead_tup::bigint,
                CASE
                    WHEN stats.n_live_tup + stats.n_dead_tup = 0
                    THEN 0::double precision
                    ELSE (
                        100.0 * stats.n_dead_tup
                        / (stats.n_live_tup + stats.n_dead_tup)
                    )::double precision
                END AS dead_tuple_percent,
                pg_relation_size(class.oid)::bigint AS table_bytes,
                pg_indexes_size(class.oid)::bigint AS index_bytes,
                pg_total_relation_size(class.oid)::bigint AS total_bytes,
                age(class.relfrozenxid)::bigint AS transaction_age,
                CASE
                    WHEN stats.last_autovacuum IS NULL THEN -1
                    ELSE EXTRACT(
                        EPOCH FROM (CURRENT_TIMESTAMP - stats.last_autovacuum)
                    )::bigint
                END AS autovacuum_lag_seconds,
                CASE
                    WHEN stats.last_autoanalyze IS NULL THEN -1
                    ELSE EXTRACT(
                        EPOCH FROM (CURRENT_TIMESTAMP - stats.last_autoanalyze)
                    )::bigint
                END AS autoanalyze_lag_seconds,
                COALESCE(vacuum.active_seconds, 0)::bigint
                    AS active_vacuum_seconds,
                stats.autovacuum_count::bigint,
                stats.autoanalyze_count::bigint,
                COALESCE(class.reloptions, ARRAY[]::text[]) AS reloptions
            FROM pg_stat_user_tables AS stats
            JOIN pg_class AS class
              ON class.oid = stats.relid
            LEFT JOIN LATERAL (
                SELECT max(
                    EXTRACT(EPOCH FROM (clock_timestamp() - activity.query_start))
                )::bigint AS active_seconds
                FROM pg_stat_progress_vacuum AS progress
                JOIN pg_stat_activity AS activity
                  ON activity.pid = progress.pid
                WHERE progress.relid = class.oid
            ) AS vacuum ON TRUE
            WHERE stats.schemaname = 'public'
              AND stats.relname = ANY(%s::text[])
            ORDER BY stats.relname
            """,
            [
                list(PRODUCT_IMPORT_HEALTH_TABLES)
            ],
        )
        rows = await cursor.fetchall()

    return [
        ProductImportTableHealth(
            table_name=str(row[0]),
            live_tuples=int(row[1] or 0),
            dead_tuples=int(row[2] or 0),
            dead_tuple_percent=float(row[3] or 0.0),
            table_bytes=int(row[4] or 0),
            index_bytes=int(row[5] or 0),
            total_bytes=int(row[6] or 0),
            transaction_age=int(row[7] or 0),
            autovacuum_lag_seconds=int(row[8] or 0),
            autoanalyze_lag_seconds=int(row[9] or 0),
            active_vacuum_seconds=int(row[10] or 0),
            autovacuum_count=int(row[11] or 0),
            autoanalyze_count=int(row[12] or 0),
            reloptions=tuple(str(value) for value in (row[13] or ())),
        )
        for row in rows
    ]
