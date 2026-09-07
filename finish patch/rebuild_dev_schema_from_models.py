from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.engine import make_url


def locate_project() -> tuple[Path, Path]:
    cwd = Path.cwd().resolve()
    here = Path(__file__).resolve().parent

    candidates = [
        cwd,
        here,
        cwd.parent,
        here.parent,
    ]

    for root in candidates:
        backend = root / "wa_backend"
        if backend.is_dir() and (backend / "models.py").is_file():
            return root, backend

        if root.name == "wa_backend" and (root / "models.py").is_file():
            return root.parent, root

    raise SystemExit(
        "ERROR: لم أجد wa_backend/models.py. "
        "ضع السكربت في جذر المشروع أو شغله من جذر المشروع."
    )


ROOT, BACKEND = locate_project()

# Explicit .env discovery — no implicit cwd-dependent lookup.
env_candidates = [
    BACKEND / ".env",
    ROOT / ".env",
]
env_file = next((p for p in env_candidates if p.is_file()), None)
if env_file is None:
    raise SystemExit(
        "ERROR: لم أجد .env في:\n"
        + "\n".join(f"  - {p}" for p in env_candidates)
    )

load_dotenv(env_file, override=True)

migration_url = os.getenv("DATABASE_URL_MIGRATION")
app_url = os.getenv("DATABASE_URL")

if not migration_url:
    raise SystemExit("ERROR: DATABASE_URL_MIGRATION غير موجود في .env.")
if not app_url:
    raise SystemExit("ERROR: DATABASE_URL غير موجود في .env.")

# Hard safety gate: this script is destructive and DEV-only.
if os.getenv("WANASAH_DEV_RESET") != "YES":
    raise SystemExit(
        "REFUSED: هذا السكربت يمسح schema التطوير بالكامل.\n"
        'نفّذ أولاً في PowerShell:\n'
        '$env:WANASAH_DEV_RESET="YES"'
    )

# Require a local PostgreSQL target to prevent accidental remote/prod wipe.
mig_parsed = make_url(migration_url)
host = (mig_parsed.host or "").lower()
if host not in {"localhost", "127.0.0.1", "::1"}:
    raise SystemExit(
        f"REFUSED: DATABASE_URL_MIGRATION يشير إلى host غير محلي: {host!r}. "
        "هذا السكربت مخصص لقاعدة التطوير المحلية فقط."
    )

db_name = mig_parsed.database or ""
if not db_name:
    raise SystemExit("REFUSED: DATABASE_URL_MIGRATION لا يحتوي اسم قاعدة بيانات.")

# Convert sync PostgreSQL URL to asyncpg without changing credentials.
if migration_url.startswith("postgres://"):
    migration_url = migration_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif migration_url.startswith("postgresql://") and "+asyncpg" not in migration_url:
    migration_url = migration_url.replace("postgresql://", "postgresql+asyncpg://", 1)

app_parsed = make_url(app_url)
app_user = app_parsed.username
if not app_user or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$-]*", app_user):
    raise SystemExit("ERROR: تعذر استخراج اسم مستخدم التطبيق بشكل آمن من DATABASE_URL.")

sys.path.insert(0, str(BACKEND))
from models import Base  # noqa: E402


engine = create_async_engine(
    migration_url,
    pool_pre_ping=True,
    echo=False,
)


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def verify_schema(conn) -> tuple[int, int, list[str]]:
    def _verify(sync_conn):
        inspector = inspect(sync_conn)
        db_tables = set(inspector.get_table_names())
        model_tables = set(Base.metadata.tables.keys())
        return len(db_tables), len(model_tables), sorted(model_tables - db_tables)

    return await conn.run_sync(_verify)


async def rebuild() -> None:
    async with engine.begin() as conn:
        current_db = (
            await conn.execute(text("SELECT current_database()"))
        ).scalar_one()
        current_user = (
            await conn.execute(text("SELECT current_user"))
        ).scalar_one()

        print(f"ENV_FILE={env_file}")
        print(f"DATABASE={current_db}")
        print(f"MIGRATION_ROLE={current_user}")
        print(f"APP_ROLE={app_user}")

        if current_db != db_name:
            raise RuntimeError(
                f"Safety mismatch: URL database={db_name}, connected database={current_db}"
            )

        # Rebuild the entire public schema under the migration owner.
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)

        # Deny CREATE on schema to the runtime role; runtime should not own DDL.
        await conn.execute(
            text(f"REVOKE CREATE ON SCHEMA public FROM {qident(app_user)}")
        )
        await conn.execute(
            text(f"GRANT USAGE ON SCHEMA public TO {qident(app_user)}")
        )

        # Apply tenant RLS to every model table that has company_id.
        tenant_tables = [
            table_name
            for table_name, table in Base.metadata.tables.items()
            if "company_id" in table.columns
        ]

        for table_name in tenant_tables:
            qt = qident(table_name)
            await conn.execute(text(f"ALTER TABLE {qt} ENABLE ROW LEVEL SECURITY"))
            await conn.execute(text(f"ALTER TABLE {qt} FORCE ROW LEVEL SECURITY"))
            await conn.execute(
                text(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {qt}")
            )
            await conn.execute(text(
                f"""
                CREATE POLICY tenant_isolation_policy ON {qt}
                FOR ALL
                USING (
                    company_id =
                    NULLIF(current_setting('app.current_tenant', true), '')::integer
                )
                WITH CHECK (
                    company_id =
                    NULLIF(current_setting('app.current_tenant', true), '')::integer
                )
                """
            ))

        # Runtime role: DML only, no DDL ownership.
        await conn.execute(text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE "
            f"ON ALL TABLES IN SCHEMA public TO {qident(app_user)}"
        ))
        await conn.execute(text(
            f"GRANT USAGE, SELECT, UPDATE "
            f"ON ALL SEQUENCES IN SCHEMA public TO {qident(app_user)}"
        ))

        # Future objects created by this migration role inherit the same runtime grants.
        await conn.execute(text(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {qident(app_user)}"
        ))
        await conn.execute(text(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {qident(app_user)}"
        ))

    async with engine.connect() as conn:
        db_count, model_count, missing = await verify_schema(conn)

    if missing:
        raise RuntimeError(
            "REBUILD_INCOMPLETE: missing tables: " + ", ".join(missing)
        )

    print("WANASAH_DEV_SCHEMA_REBUILD_OK")
    print(f"MODEL_TABLES={model_count}")
    print(f"DB_TABLES={db_count}")
    print("RLS=APPLIED_TO_ALL_TENANT_TABLES")
    print("APP_ROLE_DDL=DENIED")
    print("APP_ROLE_DML=GRANTED")
    print("ALEMBIC_STATE=REMOVED_WITH_SCHEMA_RESET")


async def main() -> None:
    try:
        await rebuild()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
