from __future__ import annotations

import ast
import asyncio
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import jwt
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "wa_backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

load_dotenv(BACKEND / ".env", override=False)

APP_URL = os.getenv("DATABASE_URL")
MIGRATION_URL = os.getenv("DATABASE_URL_MIGRATION")

A_CODE = "WKR-FINAL-V2-A"
B_CODE = "WKR-FINAL-V2-B"
AUDIT_ACTION = "WORKER_FINAL_V2_DEDUPE"


def normalize_pg_url(raw: str | None) -> str:
    if not raw:
        raise RuntimeError("Required database URL is missing.")
    url = raw.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]
    elif url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url[len("postgresql+psycopg://"):]
    return url


async def migration_conn():
    return await asyncpg.connect(normalize_pg_url(MIGRATION_URL))


async def app_conn():
    return await asyncpg.connect(normalize_pg_url(APP_URL))


async def disable_audit_guard(conn):
    exists = await conn.fetchval(
        "SELECT to_regclass('public.system_audit_logs') IS NOT NULL"
    )
    if exists:
        await conn.execute(
            "ALTER TABLE public.system_audit_logs "
            "DISABLE TRIGGER trg_system_audit_logs_append_only"
        )


async def enable_audit_guard(conn):
    exists = await conn.fetchval(
        "SELECT to_regclass('public.system_audit_logs') IS NOT NULL"
    )
    if exists:
        await conn.execute(
            "ALTER TABLE public.system_audit_logs "
            "ENABLE TRIGGER trg_system_audit_logs_append_only"
        )


async def cleanup(conn, tokens: list[str] | None = None):
    rows = await conn.fetch(
        "SELECT id FROM companies WHERE company_code = ANY($1::text[])",
        [A_CODE, B_CODE],
    )
    ids = [int(row["id"]) for row in rows]

    if tokens:
        await conn.execute(
            "DELETE FROM token_blacklist WHERE token = ANY($1::text[])",
            tokens,
        )

    if not ids:
        return

    await disable_audit_guard(conn)
    try:
        await conn.execute(
            "DELETE FROM system_audit_logs WHERE company_id = ANY($1::int[])",
            ids,
        )
    finally:
        await enable_audit_guard(conn)

    await conn.execute(
        "DELETE FROM work_sessions WHERE company_id = ANY($1::int[])",
        ids,
    )
    await conn.execute(
        "DELETE FROM system_settings WHERE company_id = ANY($1::int[])",
        ids,
    )
    await conn.execute(
        "DELETE FROM drivers WHERE company_id = ANY($1::int[])",
        ids,
    )
    await conn.execute(
        "DELETE FROM companies WHERE id = ANY($1::int[])",
        ids,
    )


async def setup_fixture():
    conn = await migration_conn()
    try:
        async with conn.transaction():
            await cleanup(conn)
            now = datetime.now(timezone.utc).replace(tzinfo=None)

            async def create_company(code: str, label: str):
                cid = int(
                    await conn.fetchval(
                        """
                        INSERT INTO companies
                            (name, company_code, is_active, subscription_status,
                             currency_code, timezone, created_at)
                        VALUES ($1,$2,TRUE,'active','JOD','Asia/Amman',$3)
                        RETURNING id
                        """,
                        f"Final V2 {label}",
                        code,
                        now,
                    )
                )
                admin_id = int(
                    await conn.fetchval(
                        """
                        INSERT INTO drivers
                            (company_id, username, password_hash, full_name,
                             is_active, is_admin, can_allow_debt,
                             max_debt_limit, created_at)
                        VALUES ($1,$2,'x',$3,TRUE,TRUE,FALSE,0,$4)
                        RETURNING id
                        """,
                        cid,
                        f"final_v2_admin_{label}",
                        f"Final V2 Admin {label}",
                        now,
                    )
                )
                user_id = int(
                    await conn.fetchval(
                        """
                        INSERT INTO drivers
                            (company_id, username, password_hash, full_name,
                             is_active, is_admin, can_allow_debt,
                             max_debt_limit, created_at)
                        VALUES ($1,$2,'x',$3,TRUE,FALSE,FALSE,0,$4)
                        RETURNING id
                        """,
                        cid,
                        f"final_v2_user_{label}",
                        f"Final V2 User {label}",
                        now,
                    )
                )
                return cid, admin_id, user_id

            a_cid, a_admin, a_user = await create_company(A_CODE, "A")
            b_cid, b_admin, b_user = await create_company(B_CODE, "B")

        return {
            "a": {"company": a_cid, "admin": a_admin, "user": a_user},
            "b": {"company": b_cid, "admin": b_admin, "user": b_user},
        }
    finally:
        await conn.close()


def verify_source_contracts():
    required_files = [
        "wa_backend/realtime/auth.py",
        "wa_backend/realtime/worker_event_relay.py",
        "wa_backend/workers/tasks/maintenance.py",
        "wa_backend/workers/tasks/handshake.py",
        "wa_backend/workers/tasks/session_monitor.py",
        "wa_backend/workers/tasks/integrity.py",
        "wa_backend/workers/tenant.py",
        "wa_backend/workers/README.md",
    ]
    for rel in required_files:
        path = ROOT / rel
        if not path.exists():
            raise AssertionError(f"MISSING_REQUIRED_FILE: {rel}")
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    handshake = (BACKEND / "workers/tasks/handshake.py").read_text(encoding="utf-8")
    session = (BACKEND / "workers/tasks/session_monitor.py").read_text(encoding="utf-8")
    integrity = (BACKEND / "workers/tasks/integrity.py").read_text(encoding="utf-8")
    maintenance = (BACKEND / "workers/tasks/maintenance.py").read_text(encoding="utf-8")
    tenant = (BACKEND / "workers/tenant.py").read_text(encoding="utf-8")
    main = (BACKEND / "main.py").read_text(encoding="utf-8")
    ws = (BACKEND / "ws_manager.py").read_text(encoding="utf-8")

    required = {
        "handshake_schedule": '@app.periodic(cron="*/5 * * * *")' in handshake,
        "session_schedule": '@app.periodic(cron="*/15 * * * *")' in session,
        "integrity_schedule": '@app.periodic(cron="7 * * * *")' in integrity,
        "stalled_recovery": "get_stalled_jobs" in maintenance,
        "stalled_allowlist": "STALLED_RETRY_ALLOWLIST" in maintenance,
        "retention": "max_hours=720" in maintenance,
        "advisory_lock": "pg_advisory_xact_lock" in tenant,
        "ws_authoritative_auth": "authenticate_websocket_admin(token)" in main,
        "ws_tenant_limit": "MAX_WS_CONNECTIONS_PER_TENANT" in ws,
        "rate_limiter": "limiter.enabled = False" not in main,
    }
    failed = [k for k, v in required.items() if not v]
    if failed:
        raise AssertionError(f"SOURCE_CONTRACT_FAILURES: {failed}")

    print("FINAL_V2_SOURCE_CONTRACTS=OK")


def verify_db_manager_constructor_compatibility():
    import models

    path = BACKEND / "db_manager.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    model_classes = {}
    for name, value in vars(models).items():
        if isinstance(value, type) and hasattr(value, "__mapper__"):
            model_classes[name] = value

    failures = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name):
            continue
        name = node.func.id
        model_cls = model_classes.get(name)
        if model_cls is None:
            continue
        allowed = set(model_cls.__mapper__.attrs.keys())
        for keyword in node.keywords:
            if keyword.arg is not None and keyword.arg not in allowed:
                failures.append(f"{name}.{keyword.arg}")

    if failures:
        raise AssertionError(
            "DB_MANAGER_STALE_MODEL_ARGUMENTS: " + ", ".join(sorted(set(failures)))
        )

    source = path.read_text(encoding="utf-8")
    if "MainWarehouse(" in source or "WarehouseLedger(" in source:
        raise AssertionError("DB_MANAGER_LEGACY_INVENTORY_REFERENCE_FOUND")

    print("DB_MANAGER_MODEL_CONSTRUCTOR_COMPATIBILITY=OK")


def verify_procrastinate_healthchecks():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "procrastinate",
            "--app=workers.app.app",
            "healthchecks",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise AssertionError("PROCRASTINATE_HEALTHCHECK_FAILED:\n" + output[-4000:])
    for required in [
        "App configuration: OK",
        "DB connection: OK",
        "Found procrastinate_jobs table: OK",
    ]:
        if required not in output:
            raise AssertionError(f"HEALTHCHECK_OUTPUT_MISSING: {required}\n{output}")
    print("PROCRASTINATE_FINAL_HEALTHCHECKS=OK")


async def verify_audit_append_only(info):
    app_user = make_url(normalize_pg_url(APP_URL)).username
    if not app_user:
        raise AssertionError("APP_USER_UNRESOLVED")

    mig = await migration_conn()
    try:
        trigger_enabled = await mig.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_trigger t
                JOIN pg_class c ON c.oid=t.tgrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public'
                  AND c.relname='system_audit_logs'
                  AND t.tgname='trg_system_audit_logs_append_only'
                  AND NOT t.tgisinternal
                  AND t.tgenabled <> 'D'
            )
            """
        )
        if not trigger_enabled:
            raise AssertionError("AUDIT_APPEND_ONLY_TRIGGER_MISSING_OR_DISABLED")

        privileges = await mig.fetchrow(
            """
            SELECT
                has_table_privilege($1, 'public.system_audit_logs', 'SELECT') AS sel,
                has_table_privilege($1, 'public.system_audit_logs', 'INSERT') AS ins,
                has_table_privilege($1, 'public.system_audit_logs', 'UPDATE') AS upd,
                has_table_privilege($1, 'public.system_audit_logs', 'DELETE') AS del,
                has_table_privilege($1, 'public.system_audit_logs', 'TRUNCATE') AS trunc
            """,
            app_user,
        )
        if not bool(privileges["sel"]) or not bool(privileges["ins"]):
            raise AssertionError("AUDIT_REQUIRED_PRIVILEGES_MISSING")
        if bool(privileges["upd"]) or bool(privileges["del"]) or bool(privileges["trunc"]):
            raise AssertionError(f"AUDIT_MUTATION_PRIVILEGES_PRESENT: {dict(privileges)}")
    finally:
        await mig.close()

    conn = await app_conn()
    try:
        await conn.execute(
            "SELECT set_config('app.current_tenant', $1, false)",
            str(info["a"]["company"]),
        )
        audit_id = int(
            await conn.fetchval(
                """
                INSERT INTO system_audit_logs
                    (company_id, admin_id, target_id, action_type,
                     old_value, new_value, timestamp)
                VALUES ($1, NULL, 'FinalV2:Audit', 'FINAL_V2_APPEND_TEST',
                        NULL, 'created', $2)
                RETURNING id
                """,
                info["a"]["company"],
                datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )

        blocked_update = False
        try:
            await conn.execute(
                "UPDATE system_audit_logs SET new_value='tampered' WHERE id=$1",
                audit_id,
            )
        except Exception as exc:
            if getattr(exc, "sqlstate", None) in {"42501", "55000"} or "permission" in str(exc).lower() or "append-only" in str(exc).lower():
                blocked_update = True
            else:
                raise
        if not blocked_update:
            raise AssertionError("AUDIT_UPDATE_WAS_NOT_BLOCKED")

        blocked_delete = False
        try:
            await conn.execute(
                "DELETE FROM system_audit_logs WHERE id=$1",
                audit_id,
            )
        except Exception as exc:
            if getattr(exc, "sqlstate", None) in {"42501", "55000"} or "permission" in str(exc).lower() or "append-only" in str(exc).lower():
                blocked_delete = True
            else:
                raise
        if not blocked_delete:
            raise AssertionError("AUDIT_DELETE_WAS_NOT_BLOCKED")
    finally:
        await conn.close()

    print("SYSTEM_AUDIT_LOG_APPEND_ONLY_RUNTIME=OK")


async def verify_websocket_auth(info, tokens_out):
    from config import Config
    from realtime.auth import WebSocketAuthError, authenticate_websocket_admin

    def make_token(company_id: int, driver_id: int):
        token = jwt.encode(
            {
                "sub": str(driver_id),
                "company_id": int(company_id),
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            Config.SECRET_KEY,
            algorithm="HS256",
        )
        tokens_out.append(token)
        return token

    valid = make_token(info["a"]["company"], info["a"]["admin"])
    identity = await authenticate_websocket_admin(valid)
    if identity.company_id != info["a"]["company"] or identity.driver_id != info["a"]["admin"]:
        raise AssertionError("WS_VALID_ADMIN_IDENTITY_MISMATCH")

    non_admin = make_token(info["a"]["company"], info["a"]["user"])
    try:
        await authenticate_websocket_admin(non_admin)
        raise AssertionError("WS_NON_ADMIN_WAS_ACCEPTED")
    except WebSocketAuthError:
        pass

    cross_spoof = make_token(info["a"]["company"], info["b"]["admin"])
    try:
        await authenticate_websocket_admin(cross_spoof)
        raise AssertionError("WS_CROSS_TENANT_DRIVER_SPOOF_WAS_ACCEPTED")
    except WebSocketAuthError:
        pass

    revoked = make_token(info["a"]["company"], info["a"]["admin"])
    mig = await migration_conn()
    try:
        await mig.execute(
            "INSERT INTO token_blacklist (token, blacklisted_at) VALUES ($1,$2)",
            revoked,
            datetime.now(timezone.utc).replace(tzinfo=None),
        )
    finally:
        await mig.close()

    try:
        await authenticate_websocket_admin(revoked)
        raise AssertionError("WS_REVOKED_TOKEN_WAS_ACCEPTED")
    except WebSocketAuthError:
        pass

    print("WEBSOCKET_AUTHORITATIVE_AUTH_RUNTIME=OK")


async def verify_websocket_resource_isolation():
    from ws_manager import (
        ConnectionManager,
        MAX_WS_CONNECTIONS,
        MAX_WS_CONNECTIONS_PER_TENANT,
    )

    if MAX_WS_CONNECTIONS < 2 * MAX_WS_CONNECTIONS_PER_TENANT:
        raise AssertionError("WS_GLOBAL_LIMIT_CAN_BE_MONOPOLIZED_BY_ONE_TENANT")

    class FakeSocket:
        def __init__(self):
            self.accepted = False
            self.closed = False

        async def accept(self):
            self.accepted = True

        async def close(self, code=1000):
            self.closed = True

        async def send_json(self, message):
            return None

    mgr = ConnectionManager()
    for _ in range(MAX_WS_CONNECTIONS_PER_TENANT):
        sock = FakeSocket()
        if not await mgr.connect(sock, 1001):
            raise AssertionError("WS_TENANT_LIMIT_REJECTED_VALID_SLOT")

    overflow = FakeSocket()
    if await mgr.connect(overflow, 1001):
        raise AssertionError("WS_TENANT_OVERFLOW_WAS_ACCEPTED")
    if not overflow.closed:
        raise AssertionError("WS_TENANT_OVERFLOW_NOT_CLOSED")

    other = FakeSocket()
    if not await mgr.connect(other, 2002):
        raise AssertionError("WS_NOISY_NEIGHBOR_BLOCKED_OTHER_TENANT")

    print("WEBSOCKET_TENANT_AVAILABILITY_ISOLATION_RUNTIME=OK")


async def verify_advisory_dedupe(info):
    from sqlalchemy import select
    from models import SystemAuditLog
    from workers.tenant import acquire_tenant_job_lock, tenant_session

    company_id = info["a"]["company"]

    async def contender(delay: float):
        await asyncio.sleep(delay)
        async with tenant_session(company_id) as db:
            await acquire_tenant_job_lock(
                db,
                namespace="final-v2-dedupe-gate",
                company_id=company_id,
            )
            exists = (
                await db.execute(
                    select(SystemAuditLog.id).where(
                        SystemAuditLog.company_id == company_id,
                        SystemAuditLog.action_type == AUDIT_ACTION,
                        SystemAuditLog.target_id == "FinalV2:Dedupe",
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                db.add(
                    SystemAuditLog(
                        company_id=company_id,
                        admin_id=None,
                        target_id="FinalV2:Dedupe",
                        action_type=AUDIT_ACTION,
                        old_value=None,
                        new_value="created",
                    )
                )
                await asyncio.sleep(0.25)
                await db.commit()
            else:
                await db.rollback()

    await asyncio.gather(contender(0), contender(0))

    mig = await migration_conn()
    try:
        count = int(
            await mig.fetchval(
                """
                SELECT count(*)
                FROM system_audit_logs
                WHERE company_id=$1
                  AND action_type=$2
                  AND target_id='FinalV2:Dedupe'
                """,
                company_id,
                AUDIT_ACTION,
            )
        )
    finally:
        await mig.close()

    if count != 1:
        raise AssertionError(f"ADVISORY_DEDUPE_FAILED: count={count}")

    print("MONITOR_ADVISORY_DEDUPE_RUNTIME=OK")


async def verify_rls_pool(info):
    conn = await app_conn()
    try:
        await conn.execute(
            "SELECT set_config('app.current_tenant', $1, false)",
            str(info["a"]["company"]),
        )
        visible = int(
            await conn.fetchval(
                "SELECT count(*) FROM drivers WHERE company_id=$1",
                info["b"]["company"],
            )
        )
        if visible != 0:
            raise AssertionError("FINAL_V2_CROSS_TENANT_READ_FAILED")
    finally:
        await conn.close()

    from sqlalchemy import func, select, text
    from context import tenant_context
    from database import AsyncSessionLocal
    from models import Driver

    token = tenant_context.set(info["a"]["company"])
    try:
        async with AsyncSessionLocal() as db:
            own = int(
                (
                    await db.execute(
                        select(func.count(Driver.id)).where(
                            Driver.company_id == info["a"]["company"]
                        )
                    )
                ).scalar_one()
            )
            if own < 1:
                raise AssertionError("FINAL_V2_SELF_TENANT_READ_FAILED")
    finally:
        tenant_context.reset(token)

    async with AsyncSessionLocal() as db:
        visible_none = int(
            (
                await db.execute(select(func.count(Driver.id)))
            ).scalar_one()
        )
        current = (
            await db.execute(
                text("SELECT current_setting('app.current_tenant', true)")
            )
        ).scalar_one()

    if visible_none != 0 or current not in ("", None):
        raise AssertionError(
            f"FINAL_V2_POOL_RESIDUE_FAILED visible={visible_none} current={current!r}"
        )

    print("FINAL_V2_RLS_AND_POOL_ISOLATION=OK")


async def run():
    verify_source_contracts()
    verify_db_manager_constructor_compatibility()
    verify_procrastinate_healthchecks()

    tokens = []
    info = None
    try:
        info = await setup_fixture()
        print(
            "FINAL_V2_FIXTURE=OK "
            f"A={info['a']['company']} B={info['b']['company']}"
        )

        await verify_audit_append_only(info)
        await verify_websocket_auth(info, tokens)
        await verify_websocket_resource_isolation()
        await verify_advisory_dedupe(info)
        await verify_rls_pool(info)

        print("WORKERS_FINAL_PRODUCTION_FREEZE_GATE_V2=PASS")
    finally:
        conn = await migration_conn()
        try:
            async with conn.transaction():
                await cleanup(conn, tokens)
            print("FINAL_V2_CLEANUP=OK")
        finally:
            await conn.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()
        )
    asyncio.run(run())
