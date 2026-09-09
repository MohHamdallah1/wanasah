from __future__ import annotations

import asyncio
import ast
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "wa_backend"

APP = BACKEND / "workers" / "app.py"
TENANT = BACKEND / "workers" / "tenant.py"
HANDSHAKE = BACKEND / "workers" / "tasks" / "handshake.py"
SESSION = BACKEND / "workers" / "tasks" / "session_monitor.py"
INTEGRITY = BACKEND / "workers" / "tasks" / "integrity.py"
MAINTENANCE = BACKEND / "workers" / "tasks" / "maintenance.py"
REALTIME_AUTH = BACKEND / "realtime" / "auth.py"
WS_MANAGER = BACKEND / "ws_manager.py"
MAIN = BACKEND / "main.py"
README = BACKEND / "workers" / "README.md"
DB_MANAGER = BACKEND / "db_manager.py"
CONFIG = BACKEND / "config.py"
BOOTSTRAP = BACKEND / "workers" / "bootstrap.py"

AUTH_CONTENT = '''from __future__ import annotations

from dataclasses import dataclass

import jwt
from sqlalchemy import select

from config import Config
from models import Driver, TokenBlacklist
from workers.tenant import normalize_company_id, tenant_session


class WebSocketAuthError(Exception):
    pass


@dataclass(frozen=True)
class WebSocketAdminIdentity:
    company_id: int
    driver_id: int


async def authenticate_websocket_admin(token: str) -> WebSocketAdminIdentity:
    try:
        payload = jwt.decode(
            token,
            Config.SECRET_KEY,
            algorithms=["HS256"],
            options={"require": ["exp"]},
        )
        company_id = normalize_company_id(payload.get("company_id"))
        driver_id = int(payload.get("sub"))
        if driver_id <= 0:
            raise ValueError
    except (jwt.PyJWTError, TypeError, ValueError) as exc:
        raise WebSocketAuthError("invalid websocket token") from exc

    async with tenant_session(company_id) as db:
        blacklisted = (
            await db.execute(
                select(TokenBlacklist.id).where(TokenBlacklist.token == token)
            )
        ).scalar_one_or_none()
        if blacklisted is not None:
            raise WebSocketAuthError("revoked websocket token")

        driver = (
            await db.execute(
                select(Driver).where(
                    Driver.company_id == company_id,
                    Driver.id == driver_id,
                )
            )
        ).scalar_one_or_none()

        if (
            driver is None
            or not bool(driver.is_active)
            or not bool(driver.is_admin)
        ):
            raise WebSocketAuthError("websocket admin authorization failed")

    return WebSocketAdminIdentity(
        company_id=company_id,
        driver_id=driver_id,
    )
'''

MAINTENANCE_CONTENT = '''# WORKER_PRODUCTION_HARDENING_V2
from __future__ import annotations

from procrastinate import builtin_tasks

from workers.app import MAINTENANCE_QUEUE, app


STALLED_RETRY_ALLOWLIST = {
    "wanasah.worker_healthcheck",
    "wanasah.scan_all_stale_handshakes",
    "wanasah.scan_company_stale_handshakes",
    "wanasah.scan_all_stale_sessions",
    "wanasah.scan_company_stale_sessions",
    "wanasah.scan_all_integrity",
    "wanasah.scan_company_integrity",
    "wanasah.report_foundation_probe",
    "wanasah.retry_safe_stalled_jobs",
    "wanasah.cleanup_old_worker_jobs",
}


@app.periodic(cron="*/10 * * * *")
@app.task(
    name="wanasah.retry_safe_stalled_jobs",
    queue=MAINTENANCE_QUEUE,
    queueing_lock="retry-safe-stalled-jobs",
    lock="retry-safe-stalled-jobs",
)
async def retry_safe_stalled_jobs(timestamp: int) -> dict[str, int]:
    stalled_jobs = await app.job_manager.get_stalled_jobs()
    retried = 0
    skipped = 0

    for job in stalled_jobs:
        if job.task_name not in STALLED_RETRY_ALLOWLIST:
            skipped += 1
            continue
        await app.job_manager.retry_job(job)
        retried += 1

    return {
        "stalled_seen": len(stalled_jobs),
        "retried": retried,
        "skipped_not_allowlisted": skipped,
    }


@app.periodic(cron="13 4 * * *")
@app.task(
    name="wanasah.cleanup_old_worker_jobs",
    queue=MAINTENANCE_QUEUE,
    queueing_lock="cleanup-old-worker-jobs",
    lock="cleanup-old-worker-jobs",
    pass_context=True,
)
async def cleanup_old_worker_jobs(context, timestamp: int):
    return await builtin_tasks.remove_old_jobs(
        context,
        max_hours=720,
        remove_failed=True,
        remove_cancelled=True,
        remove_aborted=True,
    )
'''

README_CONTENT = r'''# Wanasah Background Workers — Production Runbook

## Architecture

- Queue metadata lives in PostgreSQL schema `worker_queue`.
- Tenant business tables remain in `public` with PostgreSQL RLS + FORCE RLS.
- Every tenant task carries an explicit `company_id`.
- Tenant database access must go through `workers.tenant.tenant_session(company_id)`.
- `maintenance`: operational monitors and integrity jobs.
- `notifications`: notification delivery.
- `reports`: heavy read-only reporting.

## Production safety contracts

- Workers monitor/alert/report by default. They do not close work sessions, settle custody,
  mutate inventory, cancel business operations, or alter workflow unless explicitly approved.
- Stalled-job automatic retry is allowlisted to known safe/idempotent worker tasks only.
- Report transactions use PostgreSQL `READ ONLY`.
- SystemAuditLog is append-only at PostgreSQL level.
- Same-company monitor scans acquire PostgreSQL transaction advisory locks.

## Periodic scheduling

- stale handshake scan: every 5 minutes
- stale work-session scan: every 15 minutes
- integrity scan: hourly at minute 7
- safe stalled-job recovery: every 10 minutes
- worker-history retention cleanup: daily at 04:13

Scheduling is handled by Procrastinate workers and PostgreSQL. At least one worker must run
for periodic jobs to be deferred.

## Root commands

PowerShell development shell:

```powershell
$env:PYTHONPATH = "$PWD\wa_backend"
```

Bootstrap / health:

```powershell
python -m workers.bootstrap
python -m procrastinate --app=workers.app.app schema --apply
python -m procrastinate --app=workers.app.app healthchecks
```

Operational worker:

```powershell
python -m procrastinate -v --app=workers.app.app worker -q maintenance,notifications -c 4
```

Reports worker:

```powershell
python -m procrastinate -v --app=workers.app.app worker -q reports -c 1
```

## Deployment

Run API, operational worker, and reports worker as separate supervised processes.
Production workers should run on a Unix-like host/container. Windows is for development.
Keep `delete_jobs=never`; scheduled retention removes finished jobs older than 30 days.

## Final Alembic baseline

The baseline must explicitly preserve:
- RLS + FORCE RLS policies
- SystemAuditLog append-only trigger and runtime-role privilege revocations
- worker_queue Procrastinate schema/migrations
'''


def fail(message: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {message}")


def write_new_exact(path: Path, content: str, label: str) -> None:
    if path.exists():
        current = path.read_text(encoding="utf-8")
        if current == content:
            print(f"UNCHANGED={path.relative_to(ROOT)}:{label}")
            return
        fail(f"{path.relative_to(ROOT)} exists with unexpected content.")
    path.write_text(content, encoding="utf-8")
    print(f"CREATED={path.relative_to(ROOT)}:{label}")


def patch_tenant_lock_helper() -> None:
    text = TENANT.read_text(encoding="utf-8")
    if "async def acquire_tenant_job_lock" in text:
        print("ALREADY_PATCHED=wa_backend/workers/tenant.py:advisory_lock")
        return
    anchor = "@asynccontextmanager\nasync def tenant_session(company_id: int):\n"
    helper = '''async def acquire_tenant_job_lock(
    db,
    *,
    namespace: str,
    company_id: int,
) -> None:
    cid = normalize_company_id(company_id)
    if not namespace or len(namespace) > 80:
        raise ValueError("invalid tenant job lock namespace")
    await db.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtext(:namespace), :company_id)"
        ),
        {"namespace": namespace, "company_id": cid},
    )


@asynccontextmanager
async def tenant_session(company_id: int):
'''
    if text.count(anchor) != 1:
        fail("tenant.py advisory-lock anchor mismatch.")
    TENANT.write_text(text.replace(anchor, helper, 1), encoding="utf-8")
    print("PATCHED=wa_backend/workers/tenant.py:advisory_lock")


def patch_monitor(path: Path, label: str, cron: str, task_name: str, namespace: str) -> None:
    text = path.read_text(encoding="utf-8")

    old_import = "from workers.tenant import tenant_session\n"
    new_import = "from workers.tenant import acquire_tenant_job_lock, tenant_session\n"
    if new_import not in text:
        if text.count(old_import) != 1:
            fail(f"{label} tenant import mismatch.")
        text = text.replace(old_import, new_import, 1)

    task_anchor = f'@app.task(\n    name="{task_name}",'
    periodic = f'@app.periodic(cron="{cron}")'
    if periodic not in text:
        if text.count(task_anchor) != 1:
            fail(f"{label} periodic anchor mismatch.")
        text = text.replace(task_anchor, periodic + "\n" + task_anchor, 1)

    old_sig = {
        "handshake": "async def scan_all_stale_handshakes() -> dict[str, int]:",
        "session": "async def scan_all_stale_sessions() -> dict[str, int]:",
        "integrity": "async def scan_all_integrity() -> dict[str, int]:",
    }[label]
    if old_sig in text:
        text = text.replace(
            old_sig,
            old_sig.replace("()", "(timestamp: int | None = None)"),
            1,
        )

    session_anchor = "    async with tenant_session(company_id) as db:\n"
    lock_marker = f'namespace="{namespace}"'
    if lock_marker not in text:
        if text.count(session_anchor) != 1:
            fail(f"{label} tenant session anchor mismatch.")
        lock_call = f'''        await acquire_tenant_job_lock(
            db,
            namespace="{namespace}",
            company_id=int(company_id),
        )
'''
        text = text.replace(session_anchor, session_anchor + lock_call, 1)

    path.write_text(text, encoding="utf-8")
    print(f"PATCHED={path.relative_to(ROOT)}:{label}_scheduler_dedupe")


def patch_app() -> None:
    text = APP.read_text(encoding="utf-8")
    if '"workers.tasks.maintenance"' in text:
        print("ALREADY_PATCHED=wa_backend/workers/app.py:maintenance")
        return
    anchor = '        "workers.tasks.reports",\n'
    if text.count(anchor) != 1:
        fail("workers/app.py import_paths mismatch.")
    APP.write_text(
        text.replace(anchor, anchor + '        "workers.tasks.maintenance",\n', 1),
        encoding="utf-8",
    )
    print("PATCHED=wa_backend/workers/app.py:maintenance")


def patch_ws_manager() -> None:
    text = WS_MANAGER.read_text(encoding="utf-8")
    if "MAX_WS_CONNECTIONS_PER_TENANT" in text:
        print("ALREADY_PATCHED=wa_backend/ws_manager.py:tenant_limits")
        return

    if "import os\n" not in text:
        text = text.replace("import asyncio\n", "import asyncio\nimport os\n", 1)

    old = "MAX_WS_CONNECTIONS = 50\nWS_SEND_TIMEOUT_SECONDS = 3.0\n"
    new = '''def _positive_env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer.")
    return value


MAX_WS_CONNECTIONS = _positive_env_int("WS_MAX_GLOBAL_CONNECTIONS", 50)
MAX_WS_CONNECTIONS_PER_TENANT = _positive_env_int(
    "WS_MAX_CONNECTIONS_PER_TENANT",
    10,
)
if MAX_WS_CONNECTIONS < (2 * MAX_WS_CONNECTIONS_PER_TENANT):
    raise RuntimeError(
        "WS_MAX_GLOBAL_CONNECTIONS must be at least twice "
        "WS_MAX_CONNECTIONS_PER_TENANT."
    )
WS_SEND_TIMEOUT_SECONDS = 3.0
'''
    if text.count(old) != 1:
        fail("ws_manager.py constants mismatch.")
    text = text.replace(old, new, 1)

    init_old = '''    def __init__(self):
        # +++ عزل الشركات: القاموس يربط كل شركة بقائمة اتصالاتها الخاصة +++
        self.active_connections: dict[int, list[WebSocket]] = {}
'''
    init_new = '''    def __init__(self):
        self.active_connections: dict[int, list[WebSocket]] = {}
        self._connections_lock = asyncio.Lock()
'''
    if text.count(init_old) != 1:
        fail("ws_manager.py init mismatch.")
    text = text.replace(init_old, init_new, 1)

    start = text.index("    async def connect(")
    end = text.index("    def disconnect(", start)
    new_connect = '''    async def connect(self, websocket: WebSocket, company_id: int) -> bool:
        company_id = int(company_id)
        if company_id <= 0:
            await websocket.close(code=1008)
            return False

        async with self._connections_lock:
            tenant_connections = len(
                self.active_connections.get(company_id, [])
            )
            total_connections = sum(
                len(conns) for conns in self.active_connections.values()
            )

            if tenant_connections >= MAX_WS_CONNECTIONS_PER_TENANT:
                logger.warning(
                    "[WS] Tenant connection limit reached for company %s (%s).",
                    company_id,
                    MAX_WS_CONNECTIONS_PER_TENANT,
                )
                await websocket.close(code=1008)
                return False

            if total_connections >= MAX_WS_CONNECTIONS:
                logger.warning(
                    "[WS] Global connection limit reached (%s).",
                    MAX_WS_CONNECTIONS,
                )
                await websocket.close(code=1008)
                return False

            await websocket.accept()
            self.active_connections.setdefault(company_id, []).append(websocket)

        logger.info(
            "[WS] Client connected to Company %s. Tenant=%s Global=%s",
            company_id,
            tenant_connections + 1,
            total_connections + 1,
        )
        return True

'''
    text = text[:start] + new_connect + text[end:]
    WS_MANAGER.write_text(text, encoding="utf-8")
    print("PATCHED=wa_backend/ws_manager.py:tenant_limits")


def patch_main_ws_auth() -> None:
    text = MAIN.read_text(encoding="utf-8")
    auth_import = (
        "from realtime.auth import "
        "WebSocketAuthError, authenticate_websocket_admin\n"
    )
    relay_import = "from realtime.worker_event_relay import worker_event_relay\n"
    if auth_import not in text:
        if text.count(relay_import) != 1:
            fail("main.py relay import mismatch.")
        text = text.replace(relay_import, relay_import + auth_import, 1)

    start = text.index('@app.websocket("/ws/dispatch")')
    end = text.index('\n@app.get("/")', start)
    block = text[start:end]
    if "authenticate_websocket_admin(token)" not in block:
        new_block = '''@app.websocket("/ws/dispatch")
async def websocket_dispatch_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008)
        return

    try:
        identity = await authenticate_websocket_admin(token)
    except WebSocketAuthError:
        await websocket.close(code=1008)
        return

    company_id = identity.company_id
    is_connected = await dispatch_manager.connect(websocket, company_id)
    if not is_connected:
        return

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        dispatch_manager.disconnect(websocket, company_id)
'''
        text = text[:start] + new_block + text[end:]

    MAIN.write_text(text, encoding="utf-8")
    print("PATCHED=wa_backend/main.py:websocket_authoritative_auth")


def patch_env_loading() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    if "from pathlib import Path" not in text:
        text = text.replace("import os\n", "import os\nfrom pathlib import Path\n", 1)
    text = text.replace(
        "load_dotenv(override=True)",
        'load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)',
        1,
    )
    CONFIG.write_text(text, encoding="utf-8")
    print("PATCHED=wa_backend/config.py:dotenv")

    text = BOOTSTRAP.read_text(encoding="utf-8")
    if "from pathlib import Path" not in text:
        text = text.replace("import os\n", "import os\nfrom pathlib import Path\n", 1)
    text = text.replace(
        "load_dotenv(override=True)",
        'load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)',
        1,
    )
    BOOTSTRAP.write_text(text, encoding="utf-8")
    print("PATCHED=wa_backend/workers/bootstrap.py:dotenv")


def patch_db_manager() -> None:
    text = DB_MANAGER.read_text(encoding="utf-8")
    if "from pathlib import Path" not in text:
        text = text.replace("import re\n", "import re\nfrom pathlib import Path\n", 1)
    text = text.replace(
        "load_dotenv()",
        'load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)',
        1,
    )

    old_zone = (
        'zone = Zone(company_id=cid, name=f"منطقة {cid}", '
        'governorate_id=gov.id, sequence_number=1, '
        'schedule_frequency="أسبوعي", visit_day="الأحد")'
    )
    new_zone = (
        'zone = Zone(company_id=cid, name=f"منطقة {cid}", '
        'governorate_id=gov.id, sequence_number=1, '
        'start_date=datetime.now(timezone.utc).date(), interval_days=7)'
    )
    if old_zone in text:
        text = text.replace(old_zone, new_zone, 1)

    text = text.replace(
        '                session.add(MainWarehouse(product_variant_id=var.id, available_quantity_packs=1000, reserved_quantity_packs=0, min_threshold_packs=10))\n',
        '',
    )
    text = text.replace(
        '                session.add(WarehouseLedger(product_variant_id=var.id, quantity_packs=1000, balance_before_packs=0, balance_after_packs=1000, transaction_type="INBOUND_SUPPLIER", admin_id=admin.id, reference_id=f"TEST-INV-{cid}", notes="فاتورة تجريبية"))\n',
        '',
    )

    if "trg_system_audit_logs_append_only" not in text:
        anchor = (
            "        await conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "
            "public GRANT ALL ON SEQUENCES TO \"{app_user}\"'))\n"
        )
        if text.count(anchor) != 1:
            fail("db_manager.py grant anchor mismatch.")
        block = '''        quoted_app_user = '"' + app_user.replace('"', '""') + '"'
        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION public.prevent_system_audit_log_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'system_audit_logs is append-only'
                    USING ERRCODE = '55000';
            END;
            $$;
        """))
        await conn.execute(text(
            "DROP TRIGGER IF EXISTS trg_system_audit_logs_append_only "
            "ON public.system_audit_logs"
        ))
        await conn.execute(text("""
            CREATE TRIGGER trg_system_audit_logs_append_only
            BEFORE UPDATE OR DELETE OR TRUNCATE
            ON public.system_audit_logs
            FOR EACH STATEMENT
            EXECUTE FUNCTION public.prevent_system_audit_log_mutation()
        """))
        await conn.execute(text(
            f"REVOKE UPDATE, DELETE, TRUNCATE ON TABLE "
            f"public.system_audit_logs FROM {quoted_app_user}"
        ))
        await conn.execute(text(
            f"GRANT SELECT, INSERT ON TABLE "
            f"public.system_audit_logs TO {quoted_app_user}"
        ))
'''
        text = text.replace(anchor, anchor + block, 1)

    DB_MANAGER.write_text(text, encoding="utf-8")
    print("PATCHED=wa_backend/db_manager.py:current_models_audit_guard")


def normalize_pg_url(raw: str) -> str:
    url = raw.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]
    elif url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url[len("postgresql+psycopg://"):]
    return url


async def apply_audit_guard() -> None:
    load_dotenv(BACKEND / ".env", override=False)
    migration_url = os.getenv("DATABASE_URL_MIGRATION", "").strip()
    app_url = os.getenv("DATABASE_URL", "").strip()
    if not migration_url or not app_url:
        fail("DATABASE_URL_MIGRATION/DATABASE_URL missing.")

    app_user = make_url(normalize_pg_url(app_url)).username
    if not app_user:
        fail("Cannot resolve app DB username.")
    quoted = '"' + app_user.replace('"', '""') + '"'

    conn = await asyncpg.connect(normalize_pg_url(migration_url))
    try:
        await conn.execute('''
            CREATE OR REPLACE FUNCTION public.prevent_system_audit_log_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'system_audit_logs is append-only'
                    USING ERRCODE = '55000';
            END;
            $$;
        ''')
        await conn.execute(
            "DROP TRIGGER IF EXISTS trg_system_audit_logs_append_only "
            "ON public.system_audit_logs"
        )
        await conn.execute('''
            CREATE TRIGGER trg_system_audit_logs_append_only
            BEFORE UPDATE OR DELETE OR TRUNCATE
            ON public.system_audit_logs
            FOR EACH STATEMENT
            EXECUTE FUNCTION public.prevent_system_audit_log_mutation()
        ''')
        await conn.execute(
            f"REVOKE UPDATE, DELETE, TRUNCATE ON TABLE "
            f"public.system_audit_logs FROM {quoted}"
        )
        await conn.execute(
            f"GRANT SELECT, INSERT ON TABLE "
            f"public.system_audit_logs TO {quoted}"
        )
    finally:
        await conn.close()

    print("POSTGRES_AUDIT_APPEND_ONLY_GUARD=APPLIED")


def verify_static() -> None:
    for path in [
        APP, TENANT, HANDSHAKE, SESSION, INTEGRITY, MAINTENANCE,
        REALTIME_AUTH, WS_MANAGER, MAIN, DB_MANAGER, CONFIG, BOOTSTRAP,
    ]:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    checks = {
        "maintenance_import": '"workers.tasks.maintenance"' in APP.read_text(encoding="utf-8"),
        "handshake_periodic": '@app.periodic(cron="*/5 * * * *")' in HANDSHAKE.read_text(encoding="utf-8"),
        "session_periodic": '@app.periodic(cron="*/15 * * * *")' in SESSION.read_text(encoding="utf-8"),
        "integrity_periodic": '@app.periodic(cron="7 * * * *")' in INTEGRITY.read_text(encoding="utf-8"),
        "advisory_lock": "pg_advisory_xact_lock" in TENANT.read_text(encoding="utf-8"),
        "stalled_allowlist": "STALLED_RETRY_ALLOWLIST" in MAINTENANCE.read_text(encoding="utf-8"),
        "retention": "max_hours=720" in MAINTENANCE.read_text(encoding="utf-8"),
        "ws_auth": "authenticate_websocket_admin(token)" in MAIN.read_text(encoding="utf-8"),
        "ws_tenant_limit": "MAX_WS_CONNECTIONS_PER_TENANT" in WS_MANAGER.read_text(encoding="utf-8"),
        "no_mainwarehouse": "MainWarehouse(" not in DB_MANAGER.read_text(encoding="utf-8"),
        "no_warehouseledger": "WarehouseLedger(" not in DB_MANAGER.read_text(encoding="utf-8"),
        "zone_current": "interval_days=7" in DB_MANAGER.read_text(encoding="utf-8"),
        "audit_trigger": "trg_system_audit_logs_append_only" in DB_MANAGER.read_text(encoding="utf-8"),
    }
    failed = [k for k, v in checks.items() if not v]
    if failed:
        fail(f"Static verification failed: {failed}")

    print("WEBSOCKET_DB_AUTH_HARDENING=OK")
    print("WEBSOCKET_TENANT_RESOURCE_ISOLATION=OK")
    print("PERIODIC_SCHEDULER_HARDENING=OK")
    print("STALLED_JOB_SAFE_RECOVERY=OK")
    print("WORKER_RETENTION_POLICY=OK")
    print("MONITOR_DEDUPE_CONCURRENCY_LOCK=OK")
    print("AUDIT_APPEND_ONLY_STATIC=OK")
    print("DB_MANAGER_CURRENT_MODELS_STATIC=OK")
    print("WORKER_RUNBOOK_FINALIZED=OK")
    print("WORKERS_PRODUCTION_HARDENING_V2=OK")


def main() -> None:
    for path in [
        APP, TENANT, HANDSHAKE, SESSION, INTEGRITY, WS_MANAGER,
        MAIN, README, DB_MANAGER, CONFIG, BOOTSTRAP,
    ]:
        if not path.exists():
            fail(f"Missing required file: {path.relative_to(ROOT)}")

    if not (BACKEND / "realtime" / "worker_event_relay.py").exists():
        fail("Patch 1 relay organization is missing.")
    if "limiter.enabled = False" in MAIN.read_text(encoding="utf-8"):
        fail("Patch 1 rate limiter hardening is missing.")

    write_new_exact(REALTIME_AUTH, AUTH_CONTENT, "websocket_auth")
    write_new_exact(MAINTENANCE, MAINTENANCE_CONTENT, "maintenance_tasks")
    patch_tenant_lock_helper()

    patch_monitor(
        HANDSHAKE, "handshake", "*/5 * * * *",
        "wanasah.scan_all_stale_handshakes", "stale-handshake-monitor",
    )
    patch_monitor(
        SESSION, "session", "*/15 * * * *",
        "wanasah.scan_all_stale_sessions", "stale-session-monitor",
    )
    patch_monitor(
        INTEGRITY, "integrity", "7 * * * *",
        "wanasah.scan_all_integrity", "integrity-monitor",
    )

    patch_app()
    patch_ws_manager()
    patch_main_ws_auth()
    patch_env_loading()
    patch_db_manager()

    README.write_text(README_CONTENT, encoding="utf-8")
    print("PATCHED=wa_backend/workers/README.md:final_runbook")

    asyncio.run(apply_audit_guard())
    verify_static()


if __name__ == "__main__":
    main()
