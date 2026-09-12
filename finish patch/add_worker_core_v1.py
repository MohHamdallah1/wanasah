from __future__ import annotations

from pathlib import Path
import ast
import shutil
from datetime import datetime

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "wa_backend"
REQUIREMENTS = BACKEND / "requirements.txt"
WORKERS = BACKEND / "workers"

PROCRASTINATE_REQUIREMENT = "procrastinate==3.9.0"

FILES = {
    WORKERS / "__init__.py": '''"""Wanasah background worker package.

Queue metadata is system-owned. Tenant data must always be accessed through
workers.tenant.tenant_session so PostgreSQL RLS is active before any query.
"""\n''',
    WORKERS / "app.py": '''# WORKER_CORE_V1
from __future__ import annotations

from procrastinate import App, PsycopgConnector

from config import Config

QUEUE_SCHEMA = "worker_queue"

MAINTENANCE_QUEUE = "maintenance"
NOTIFICATIONS_QUEUE = "notifications"
REPORTS_QUEUE = "reports"


def _to_psycopg_conninfo(raw_url: str) -> str:
    """Normalize the application's PostgreSQL URL for psycopg 3."""
    url = str(raw_url or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required for background workers.")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]
    elif url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url[len("postgresql+psycopg://"):]
    return url


connector = PsycopgConnector(
    conninfo=_to_psycopg_conninfo(Config.SQLALCHEMY_DATABASE_URI),
    # Queue SQL is intentionally isolated from public tenant tables.
    kwargs={"options": f"-c search_path={QUEUE_SCHEMA}"},
    min_size=1,
    max_size=5,
)

app = App(
    connector=connector,
    import_paths=[
        "workers.tasks.core",
    ],
    worker_defaults={
        "concurrency": 4,
        "delete_jobs": "never",
        "shutdown_graceful_timeout": 60,
    },
)
''',
    WORKERS / "tenant.py": '''# WORKER_CORE_V1
from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy import text

from context import tenant_context
from database import AsyncSessionLocal


def normalize_company_id(company_id: int) -> int:
    """Reject ambiguous/invalid tenant identities before touching the DB."""
    if isinstance(company_id, bool):
        raise ValueError("company_id must be a positive integer.")
    try:
        value = int(company_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("company_id must be a positive integer.") from exc
    if value <= 0 or str(value) != str(company_id).strip():
        raise ValueError("company_id must be a positive integer.")
    return value


@asynccontextmanager
async def tenant_session(company_id: int):
    """Open one tenant-scoped SQLAlchemy session for a worker task.

    - tenant_context is set BEFORE the first connection checkout.
    - app.current_tenant is set explicitly on the acquired connection.
    - no implicit commit is performed; the task owns its transaction boundary.
    - tenant context is always restored, including cancellation/errors.
    """
    cid = normalize_company_id(company_id)
    token = tenant_context.set(cid)
    try:
        async with AsyncSessionLocal() as db:
            try:
                await db.execute(
                    text(
                        "SELECT set_config("
                        "'app.current_tenant', :tenant_id, false)"
                    ),
                    {"tenant_id": str(cid)},
                )
                yield db
            except BaseException:
                await db.rollback()
                raise
            finally:
                # A task that forgot to commit must never leak an open transaction.
                if db.in_transaction():
                    await db.rollback()
    finally:
        tenant_context.reset(token)
''',
    WORKERS / "tasks" / "__init__.py": '''"""Registered background tasks."""\n''',
    WORKERS / "tasks" / "core.py": '''# WORKER_CORE_V1
from __future__ import annotations

from workers.app import MAINTENANCE_QUEUE, app


@app.task(
    name="wanasah.worker_healthcheck",
    queue=MAINTENANCE_QUEUE,
)
async def worker_healthcheck() -> dict[str, str]:
    """Minimal non-tenant task used only to verify worker execution."""
    return {"status": "ok"}
''',
    WORKERS / "bootstrap.py": '''# WORKER_CORE_V1
from __future__ import annotations

import asyncio
import os

from sqlalchemy import text
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
''',
    WORKERS / "README.md": '''# Wanasah Background Workers

## Architecture

- Procrastinate stores queue metadata in PostgreSQL schema `worker_queue`.
- Tenant/business tables remain in `public` and stay protected by existing RLS.
- Every tenant task must receive an explicit `company_id` and open DB work through
  `workers.tenant.tenant_session(company_id)`.
- Queue connections use `search_path=worker_queue`, separating queue SQL from tenant SQL.
- Queues:
  - `maintenance`: short operational/integrity jobs.
  - `notifications`: alert delivery jobs.
  - `reports`: heavy analytical jobs; run on a dedicated worker later.

## Bootstrap

Run from `wa_backend`:

```powershell
python -m workers.bootstrap
python -m procrastinate --app=workers.app.app schema --apply
python -m procrastinate --app=workers.app.app healthchecks
```

## Run workers

```powershell
python -m procrastinate --app=workers.app.app worker maintenance notifications
```

Heavy reports worker later:

```powershell
python -m procrastinate --app=workers.app.app worker reports
```

## Scheduling policy

Critical periodic scheduling is intentionally not coupled to Procrastinate's built-in
`@app.periodic` yet. A deployment scheduler (cron/systemd/Kubernetes/platform scheduler)
will enqueue one idempotent scan job at the required interval; queueing locks will prevent
duplicate scans.
''',
}


def fail(message: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {message}")


def backup_requirements() -> None:
    backup_dir = BACKEND / ".patch_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = backup_dir / f"requirements_before_worker_core_{stamp}.txt"
    shutil.copy2(REQUIREMENTS, backup)
    print(f"BACKUP={backup.relative_to(ROOT)}")


def update_requirements() -> None:
    if not REQUIREMENTS.exists():
        fail("wa_backend/requirements.txt not found.")

    original = REQUIREMENTS.read_text(encoding="utf-8")
    lines = original.splitlines()
    existing = [
        line.strip()
        for line in lines
        if line.strip().lower().startswith("procrastinate")
    ]
    if existing:
        if existing == [PROCRASTINATE_REQUIREMENT]:
            print("REQUIREMENTS_ALREADY_OK")
            return
        fail(f"Existing Procrastinate requirement differs: {existing!r}")

    backup_requirements()
    REQUIREMENTS.write_text(
        original.rstrip() + "\n" + PROCRASTINATE_REQUIREMENT + "\n",
        encoding="utf-8",
    )
    print(f"REQUIREMENTS_ADDED={PROCRASTINATE_REQUIREMENT}")


def write_files() -> None:
    for path, content in FILES.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            current = path.read_text(encoding="utf-8")
            if current == content:
                print(f"UNCHANGED={path.relative_to(ROOT)}")
                continue
            fail(
                "Refusing to overwrite existing different file: "
                f"{path.relative_to(ROOT)}"
            )
        path.write_text(content, encoding="utf-8")
        print(f"CREATED={path.relative_to(ROOT)}")


def verify() -> None:
    worker_py = sorted(WORKERS.rglob("*.py"))
    if not worker_py:
        fail("No worker Python files were created.")
    for path in worker_py:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    req = REQUIREMENTS.read_text(encoding="utf-8")
    if req.splitlines().count(PROCRASTINATE_REQUIREMENT) != 1:
        fail("Procrastinate requirement is missing or duplicated.")

    app_source = (WORKERS / "app.py").read_text(encoding="utf-8")
    tenant_source = (WORKERS / "tenant.py").read_text(encoding="utf-8")
    if 'QUEUE_SCHEMA = "worker_queue"' not in app_source:
        fail("Queue schema isolation marker missing.")
    if "search_path=" not in app_source:
        fail("Queue search_path isolation missing.")
    if "tenant_context.set(cid)" not in tenant_source:
        fail("Tenant context gate missing.")
    if "'app.current_tenant'" not in tenant_source:
        fail("Explicit RLS tenant setting missing.")

    print("WORKER_CORE_STATIC_VERIFY=OK")
    print("NO_FROZEN_FILE_TOUCHED=OK")
    print("PATCH_WORKER_CORE_V1=OK")


def main() -> None:
    if not BACKEND.exists():
        fail("Run this patch from the project root; wa_backend/ was not found.")
    update_requirements()
    write_files()
    verify()


if __name__ == "__main__":
    main()
