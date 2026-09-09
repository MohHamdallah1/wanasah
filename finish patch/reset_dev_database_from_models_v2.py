from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import inspect, text

ROOT = Path.cwd()
BACKEND = ROOT / "wa_backend"

if not BACKEND.is_dir():
    raise SystemExit("ERROR: شغّل السكربت من جذر مشروع wanasah.")

if os.getenv("WANASAH_DEV_RESET") != "YES":
    raise SystemExit(
        "REFUSED: هذا السكربت يحذف كل جداول قاعدة البيانات الحالية.\n"
        "للتأكيد على أنها قاعدة تطوير فقط، شغّل أولاً:\n"
        '$env:WANASAH_DEV_RESET="YES"'
    )

sys.path.insert(0, str(BACKEND))

from database import engine
from models import Base


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _get_objects(sync_conn):
    inspector = inspect(sync_conn)
    tables = inspector.get_table_names()
    views = inspector.get_view_names()
    try:
        materialized_views = inspector.get_materialized_view_names()
    except Exception:
        materialized_views = []
    return tables, views, materialized_views


async def main() -> None:
    if engine.dialect.name != "postgresql":
        raise SystemExit("POSTGRESQL_REQUIRED_FOR_DEV_RESET")

    async with engine.begin() as conn:
        db_name = (
            await conn.execute(text("SELECT current_database()"))
        ).scalar_one()
        schema_name = (
            await conn.execute(text("SELECT current_schema()"))
        ).scalar_one()

        print(f"DATABASE={db_name}")
        print(f"SCHEMA={schema_name}")

        tables, views, materialized_views = await conn.run_sync(_get_objects)

        # Drop views first because they may depend on tables.
        for view in materialized_views:
            await conn.execute(
                text(f"DROP MATERIALIZED VIEW IF EXISTS {_quote_ident(view)} CASCADE")
            )

        for view in views:
            await conn.execute(
                text(f"DROP VIEW IF EXISTS {_quote_ident(view)} CASCADE")
            )

        # Drop application tables only.
        # alembic_version may be owned by a different DB role; it is migration metadata,
        # not application data, and will be reconciled later when we create the official baseline.
        skipped = []
        for table in tables:
            if table == "alembic_version":
                skipped.append(table)
                continue
            await conn.execute(
                text(f"DROP TABLE IF EXISTS {_quote_ident(table)} CASCADE")
            )

    # Recreate the exact current model schema in a fresh transaction.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Verify that every model table now exists.
    async with engine.connect() as conn:
        def verify(sync_conn):
            inspector = inspect(sync_conn)
            actual = set(inspector.get_table_names())
            expected = set(Base.metadata.tables.keys())
            missing = sorted(expected - actual)
            return missing, len(actual), len(expected)

        missing, actual_count, model_count = await conn.run_sync(verify)

    if missing:
        raise RuntimeError(
            "RESET_INCOMPLETE: missing model tables: " + ", ".join(missing)
        )

    print("WANASAH_DEV_DATABASE_RESET_OK")
    print(f"MODEL_TABLES={model_count}")
    print(f"DB_TABLES={actual_count}")
    print("Legacy application tables: REMOVED")
    print("Current models schema: CREATED")
    print("alembic_version: PRESERVED (will be reconciled at official baseline stage)")


async def _run() -> None:
    try:
        await main()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
