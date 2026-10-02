"""Capture a read-only Product Import performance snapshot.

Operator utility used before/after large import runs. It never mutates business
rows. Output intentionally excludes secrets, SQL bind values and file payloads.

Examples:
    python scripts/capture_product_import_perf_snapshot.py --output before.json
    python scripts/capture_product_import_perf_snapshot.py --job-id <uuid> --output after.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
TABLES = (
    "products",
    "product_variants",
    "product_uom_conversions",
    "product_barcodes",
    "price_books",
    "price_book_assignments",
    "price_publications",
    "price_book_entries",
    "product_import_jobs",
    "product_import_rows",
    "operation_idempotency",
)
INDEXES = (
    "ix_product_company_lower_name_id",
    "ix_product_company_name_id",
    "ix_products_company_name_trgm",
    "ix_price_book_entry_company_publication",
    "ix_price_book_entry_resolver",
    "ix_price_publication_resolver",
    "ix_price_book_assignment_resolver",
    "ix_product_import_row_job_status",
)


def _database_url() -> str:
    load_dotenv(BACKEND / ".env", override=False)
    raw = os.getenv("DATABASE_URL_MIGRATION") or os.getenv("DATABASE_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL_MIGRATION or DATABASE_URL is required.")
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://") and "+asyncpg" not in raw:
        raw = raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw


def _git(args: list[str]) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(REPO), *args],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


async def capture(job_id: UUID | None) -> dict:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            alembic = await conn.scalar(text("SELECT version_num FROM alembic_version"))
            db_now = await conn.scalar(text("SELECT CURRENT_TIMESTAMP"))

            job_status = (
                await conn.execute(
                    text(
                        """
                        SELECT status, count(*) AS count
                        FROM product_import_jobs
                        GROUP BY status
                        ORDER BY status
                        """
                    )
                )
            ).mappings().all()

            active_jobs = (
                await conn.execute(
                    text(
                        """
                        SELECT id::text, company_id, file_name, status,
                               total_rows, processed_rows, valid_rows, failed_rows,
                               created_at, started_at, finished_at, updated_at
                        FROM product_import_jobs
                        WHERE status IN (
                            'QUEUED','PARSING','VALIDATING','IMPORTING','RETRYING'
                        )
                        ORDER BY updated_at ASC
                        """
                    )
                )
            ).mappings().all()

            queue_status = (
                await conn.execute(
                    text(
                        """
                        SELECT status, count(*) AS count
                        FROM procrastinate_jobs
                        GROUP BY status
                        ORDER BY status
                        """
                    )
                )
            ).mappings().all()

            workers = (
                await conn.execute(
                    text(
                        """
                        SELECT r.worker_id, r.last_seen_at, w.last_heartbeat,
                               EXTRACT(EPOCH FROM (
                                   CURRENT_TIMESTAMP - r.last_seen_at
                               ))::int AS registry_age_seconds,
                               EXTRACT(EPOCH FROM (
                                   CURRENT_TIMESTAMP - w.last_heartbeat
                               ))::int AS heartbeat_age_seconds
                        FROM product_import_worker_registry AS r
                        JOIN procrastinate_workers AS w ON w.id = r.worker_id
                        ORDER BY r.last_seen_at DESC
                        """
                    )
                )
            ).mappings().all()

            table_rows: dict[str, int] = {}
            table_sizes: dict[str, dict[str, int]] = {}
            for table_name in TABLES:
                row_count = await conn.scalar(
                    text(f'SELECT count(*) FROM public."{table_name}"')
                )
                size = (
                    await conn.execute(
                        text(
                            """
                            SELECT
                                pg_relation_size(CAST(:regclass AS regclass))
                                    AS table_bytes,
                                pg_indexes_size(CAST(:regclass AS regclass))
                                    AS index_bytes,
                                pg_total_relation_size(CAST(:regclass AS regclass))
                                    AS total_bytes
                            """
                        ),
                        {"regclass": f"public.{table_name}"},
                    )
                ).mappings().one()
                table_rows[table_name] = int(row_count or 0)
                table_sizes[table_name] = {
                    key: int(size[key] or 0)
                    for key in ("table_bytes", "index_bytes", "total_bytes")
                }

            indexes = (
                await conn.execute(
                    text(
                        """
                        SELECT rel.relname AS name,
                               tbl.relname AS table_name,
                               idx.indisvalid AS valid,
                               idx.indisready AS ready,
                               idx.indislive AS live,
                               pg_relation_size(rel.oid) AS bytes,
                               pg_get_indexdef(rel.oid) AS definition
                        FROM pg_class AS rel
                        JOIN pg_index AS idx ON idx.indexrelid = rel.oid
                        JOIN pg_class AS tbl ON tbl.oid = idx.indrelid
                        WHERE rel.relname = ANY(CAST(:names AS text[]))
                        ORDER BY rel.relname
                        """
                    ),
                    {"names": list(INDEXES)},
                )
            ).mappings().all()

            job_payload = None
            if job_id is not None:
                job = (
                    await conn.execute(
                        text(
                            """
                            SELECT id::text, company_id, file_name, status,
                                   total_rows, processed_rows, valid_rows, failed_rows,
                                   created_at, started_at, finished_at, updated_at,
                                   error_summary
                            FROM product_import_jobs
                            WHERE id = :job_id
                            """
                        ),
                        {"job_id": job_id},
                    )
                ).mappings().one_or_none()

                row_status = (
                    await conn.execute(
                        text(
                            """
                            SELECT status, count(*) AS count
                            FROM product_import_rows
                            WHERE job_id = :job_id
                            GROUP BY status
                            ORDER BY status
                            """
                        ),
                        {"job_id": job_id},
                    )
                ).mappings().all()
                job_payload = {
                    "job": dict(job) if job is not None else None,
                    "row_status": [dict(row) for row in row_status],
                }

            return {
                "schema": 1,
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "database_timestamp": db_now,
                "git": {
                    "head": _git(["rev-parse", "HEAD"]),
                    "origin_main": _git(["rev-parse", "origin/main"]),
                    "branch": _git(["branch", "--show-current"]),
                },
                "alembic_version": str(alembic),
                "import_job_status": [dict(row) for row in job_status],
                "active_import_jobs": [dict(row) for row in active_jobs],
                "queue_status": [dict(row) for row in queue_status],
                "import_workers": [dict(row) for row in workers],
                "table_rows": table_rows,
                "table_sizes_bytes": table_sizes,
                "indexes": [dict(row) for row in indexes],
                "job_detail": job_payload,
            }
    finally:
        await engine.dispose()


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--job-id", type=UUID)
    args = parser.parse_args()

    payload = asyncio.run(capture(args.job_id))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )
    print(str(args.output))


if __name__ == "__main__":
    main()
