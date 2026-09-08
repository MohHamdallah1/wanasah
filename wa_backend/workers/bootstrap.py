# WORKER_CORE_V1
from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv(override=True)
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

QUEUE_SCHEMA = "worker_queue"


def _to_asyncpg_url(raw_url: str) -> str:
    url = str(raw_url or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL_MIGRATION is required.")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    elif url.startswith("postgresql+psycopg://"):
        url = "postgresql+asyncpg://" + url[len("postgresql+psycopg://"):]
    return url


def _app_username() -> str:
    raw = os.getenv("DATABASE_URL", "").strip()
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql+asyncpg://"):
        raw = "postgresql://" + raw[len("postgresql+asyncpg://"):]
    elif raw.startswith("postgresql+psycopg://"):
        raw = "postgresql://" + raw[len("postgresql+psycopg://"):]
    username = make_url(raw).username if raw else None
    if not username:
        raise RuntimeError("Cannot resolve app DB username from DATABASE_URL.")
    return username


async def bootstrap() -> None:
    migration_url = _to_asyncpg_url(os.getenv("DATABASE_URL_MIGRATION", ""))
    app_user = _app_username()
    quoted_user = '"' + app_user.replace('"', '""') + '"'

    engine = create_async_engine(migration_url, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(f'CREATE SCHEMA IF NOT EXISTS "{QUEUE_SCHEMA}"')
            )
            await conn.execute(
                text(f'ALTER SCHEMA "{QUEUE_SCHEMA}" OWNER TO {quoted_user}')
            )
            await conn.execute(
                text(
                    f'GRANT USAGE, CREATE ON SCHEMA "{QUEUE_SCHEMA}" '
                    f'TO {quoted_user}'
                )
            )
    finally:
        await engine.dispose()

    print(f"WORKER_QUEUE_SCHEMA_READY={QUEUE_SCHEMA}")
    print(f"WORKER_QUEUE_OWNER={app_user}")


if __name__ == "__main__":
    asyncio.run(bootstrap())
