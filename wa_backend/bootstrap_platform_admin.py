from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime, timezone
from getpass import getpass
from pathlib import Path

import bcrypt
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

BACKEND_ROOT = Path(__file__).resolve().parent


def _migration_url() -> str:
    raw = os.getenv("DATABASE_URL_MIGRATION")
    if not raw:
        raise RuntimeError(
            "DATABASE_URL_MIGRATION is required. The platform bootstrap never uses the runtime app role."
        )
    if raw.startswith("postgres://"):
        raw = raw.replace("postgres://", "postgresql://", 1)
    if raw.startswith("postgresql://") and "asyncpg" not in raw:
        raw = raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw


def _expected_alembic_head() -> str:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if not head:
        raise RuntimeError("Alembic has no current head revision.")
    return head


def _read_username(cli_value: str | None) -> str:
    value = (cli_value or input("Platform admin username: ")).strip()
    if not value:
        raise RuntimeError("Platform admin username is required.")
    if len(value) > 80:
        raise RuntimeError("Platform admin username must be at most 80 characters.")
    return value


def _read_password() -> str:
    first = getpass("Platform admin password: ")
    second = getpass("Confirm platform admin password: ")
    if first != second:
        raise RuntimeError("Passwords do not match.")
    if len(first) < 12:
        raise RuntimeError("Platform admin password must be at least 12 characters.")
    if len(first.encode("utf-8")) > 72:
        raise RuntimeError("Platform admin password exceeds bcrypt's 72-byte limit.")
    return first


async def _bootstrap(username: str, password: str) -> None:
    engine = create_async_engine(_migration_url(), poolclass=NullPool)
    expected_head = _expected_alembic_head()
    try:
        async with engine.begin() as connection:
            table_exists = await connection.scalar(
                text("SELECT to_regclass('public.platform_admins') IS NOT NULL")
            )
            if not table_exists:
                raise RuntimeError("Database schema is missing. Run `alembic upgrade head` first.")

            current_head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            if current_head != expected_head:
                raise RuntimeError(
                    "Database is not at the current Alembic head. Run `alembic upgrade head` first."
                )

            existing_count = await connection.scalar(text("SELECT count(*) FROM platform_admins"))
            if int(existing_count or 0) != 0:
                raise RuntimeError(
                    "Platform bootstrap is first-account only; a platform admin already exists."
                )

            password_hash = await asyncio.to_thread(
                lambda: bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            )
            created_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await connection.execute(
                text(
                    """
                    INSERT INTO platform_admins
                        (username, password_hash, is_active, created_at)
                    VALUES
                        (:username, :password_hash, true, :created_at)
                    """
                ),
                {
                    "username": username,
                    "password_hash": password_hash,
                    "created_at": created_at,
                },
            )
    finally:
        await engine.dispose()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the one initial platform-owned administrator after Alembic provisioning."
    )
    parser.add_argument("--username", help="Platform admin username. Password is never accepted on CLI.")
    args = parser.parse_args()

    username = _read_username(args.username)
    password = _read_password()
    await _bootstrap(username, password)
    print(f"PLATFORM_ADMIN_BOOTSTRAPPED={username}")


if __name__ == "__main__":
    asyncio.run(main())
