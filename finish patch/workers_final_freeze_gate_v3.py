from __future__ import annotations

import asyncio
import ast
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "wa_backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

load_dotenv(BACKEND / ".env", override=True)

APP_URL = os.getenv("DATABASE_URL")
MIGRATION_URL = os.getenv("DATABASE_URL_MIGRATION")

A_CODE = "WKR-FREEZE-V3-A"
B_CODE = "WKR-FREEZE-V3-B"
AUDIT_TRIGGER = "trg_system_audit_logs_append_only"


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


async def set_audit_trigger(conn, enabled: bool) -> None:
    action = "ENABLE" if enabled else "DISABLE"
    await conn.execute(
        f"ALTER TABLE public.system_audit_logs "
        f"{action} TRIGGER {AUDIT_TRIGGER}"
    )


async def cleanup(conn) -> None:
    rows = await conn.fetch(
        """
        SELECT id FROM companies
        WHERE company_code = ANY($1::text[])
        """,
        [A_CODE, B_CODE],
    )
    ids = [int(row["id"]) for row in rows]
    if not ids:
        return

    exists = await conn.fetchval(
        """
        SELECT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgrelid='public.system_audit_logs'::regclass
              AND tgname=$1
              AND NOT tgisinternal
        )
        """,
        AUDIT_TRIGGER,
    )
    if not exists:
        raise AssertionError("AUDIT_TRIGGER_MISSING_DURING_CLEANUP")

    await set_audit_trigger(conn, False)
    try:
        await conn.execute(
            "DELETE FROM system_audit_logs WHERE company_id=ANY($1::int[])",
            ids,
        )
    finally:
        await set_audit_trigger(conn, True)

    await conn.execute(
        "DELETE FROM system_settings WHERE company_id=ANY($1::int[])",
        ids,
    )
    await conn.execute(
        "DELETE FROM companies WHERE id=ANY($1::int[])",
        ids,
    )


def verify_static() -> None:
    paths = {
        "main": BACKEND / "main.py",
        "tenant": BACKEND / "workers" / "tenant.py",
        "settings": BACKEND / "workers" / "settings.py",
        "events": BACKEND / "workers" / "events.py",
        "handshake": BACKEND / "workers" / "tasks" / "handshake.py",
        "session": BACKEND / "workers" / "tasks" / "session_monitor.py",
        "integrity": BACKEND / "workers" / "tasks" / "integrity.py",
        "reports": BACKEND / "workers" / "tasks" / "reports.py",
        "maintenance": BACKEND / "workers" / "tasks" / "maintenance.py",
        "ws": BACKEND / "ws_manager.py",
        "relay": BACKEND / "realtime" / "worker_event_relay.py",
        "auth": BACKEND / "realtime" / "auth.py",
        "db_manager": BACKEND / "db_manager.py",
        "readme": BACKEND / "workers" / "README.md",
    }
    for path in paths.values():
        if not path.exists():
            raise AssertionError(
                f"FREEZE_V3_MISSING_FILE: {path.relative_to(ROOT)}"
            )
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    text = {
        name: path.read_text(encoding="utf-8")
        for name, path in paths.items()
    }

    checks = {
        "rate_limiter_on": "limiter.enabled = False" not in text["main"],
        "ws_authoritative_auth": (
            "authenticate_websocket_admin(token)" in text["main"]
        ),
        "ws_tenant_limit": (
            "MAX_WS_CONNECTIONS_PER_TENANT" in text["ws"]
        ),
        "relay_heartbeat": 'conn.execute("SELECT 1")' in text["relay"],
        "relay_timeout": "BROADCAST_TIMEOUT_SECONDS" in text["relay"],
        "tenant_checkout_exit_cleanup": (
            "_clear_tenant_or_invalidate" in text["tenant"]
        ),
        "tenant_advisory_lock": (
            "pg_advisory_xact_lock" in text["tenant"]
        ),
        "settings_failsafe": (
            "_default_handshake_settings" in text["settings"]
            and "_default_session_settings" in text["settings"]
            and "Invalid integrity monitor settings" in text["settings"]
        ),
        "batched_notify": (
            "_EVENT_BATCH_SIZE = 200" in text["events"]
            and "jsonb_array_elements_text" in text["events"]
        ),
        "handshake_starvation_filter": (
            "warning_audit_exists" in text["handshake"]
            and "critical_audit_exists" in text["handshake"]
        ),
        "session_starvation_filter": (
            "warning_audit_exists" in text["session"]
            and "critical_audit_exists" in text["session"]
        ),
        "scheduler": (
            '@app.periodic(cron="*/5 * * * *")' in text["handshake"]
            and '@app.periodic(cron="*/15 * * * *")' in text["session"]
            and '@app.periodic(cron="7 * * * *")' in text["integrity"]
        ),
        "stalled_recovery": (
            "STALLED_RETRY_ALLOWLIST" in text["maintenance"]
        ),
        "retention": "max_hours=720" in text["maintenance"],
        "reports_read_only": (
            'text("SET TRANSACTION READ ONLY")' in text["reports"]
        ),
        "db_manager_current": (
            "MainWarehouse(" not in text["db_manager"]
            and "WarehouseLedger(" not in text["db_manager"]
            and "interval_days=7" in text["db_manager"]
        ),
        "runbook": "Production Runbook" in text["readme"],
        "no_patch_backups": (
            not (ROOT / ".patch_backups").exists()
            and not (BACKEND / ".patch_backups").exists()
        ),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise AssertionError(f"FREEZE_V3_STATIC_FAILED: {failed}")

    for monitor_name in ["handshake", "session"]:
        monitor = text[monitor_name]
        if re.search(r"\.status\s*=(?!=)", monitor):
            raise AssertionError(
                f"FREEZE_V3_WORKFLOW_STATUS_WRITE: {monitor_name}"
            )
        if re.search(r"\.end_time\s*=(?!=)", monitor):
            raise AssertionError(
                f"FREEZE_V3_SESSION_END_WRITE: {monitor_name}"
            )
        if "apply_inventory_movements" in monitor:
            raise AssertionError(
                f"FREEZE_V3_INVENTORY_MUTATION: {monitor_name}"
            )

    print("FREEZE_V3_STATIC_CONTRACTS=OK")
    print("FREEZE_V3_NO_WORKFLOW_MUTATION=OK")


def verify_procrastinate_health() -> None:
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
        raise AssertionError(
            "FREEZE_V3_PROCRASTINATE_HEALTH_FAILED:\n"
            + output[-4000:]
        )

    for marker in [
        "App configuration: OK",
        "DB connection: OK",
        "Found procrastinate_jobs table: OK",
    ]:
        if marker not in output:
            raise AssertionError(
                f"FREEZE_V3_HEALTH_MARKER_MISSING: {marker}"
            )

    print("FREEZE_V3_PROCRASTINATE_HEALTH=OK")


async def setup_fixture() -> tuple[int, int]:
    conn = await migration_conn()
    try:
        async with conn.transaction():
            await cleanup(conn)
            now = datetime.now(timezone.utc).replace(tzinfo=None)

            async def create(code: str, label: str) -> int:
                cid = int(
                    await conn.fetchval(
                        """
                        INSERT INTO companies
                            (name, company_code, is_active,
                             subscription_status, currency_code,
                             timezone, created_at)
                        VALUES
                            ($1, $2, TRUE, 'active',
                             'JOD', 'Asia/Amman', $3)
                        RETURNING id
                        """,
                        f"Freeze V3 {label}",
                        code,
                        now,
                    )
                )
                await conn.execute(
                    """
                    INSERT INTO system_settings
                        (company_id, setting_key, setting_value, description)
                    VALUES
                        ($1, 'freeze_v3_probe', $2, 'freeze v3')
                    """,
                    cid,
                    label,
                )
                return cid

            return await create(A_CODE, "A"), await create(B_CODE, "B")
    finally:
        await conn.close()


async def verify_role_and_schema_rls() -> None:
    conn = await app_conn()
    try:
        role = await conn.fetchrow(
            """
            SELECT rolname, rolsuper, rolbypassrls
            FROM pg_roles
            WHERE rolname=current_user
            """
        )
        if role is None:
            raise AssertionError("FREEZE_V3_APP_ROLE_NOT_FOUND")
        if bool(role["rolsuper"]) or bool(role["rolbypassrls"]):
            raise AssertionError(
                f"FREEZE_V3_APP_ROLE_TOO_POWERFUL: {dict(role)}"
            )
        print(f"FREEZE_V3_APP_ROLE=OK role={role['rolname']}")
    finally:
        await conn.close()

    conn = await migration_conn()
    try:
        tenant_tables = [
            str(r["table_name"])
            for r in await conn.fetch(
                """
                SELECT DISTINCT table_name
                FROM information_schema.columns
                WHERE table_schema='public'
                  AND column_name='company_id'
                ORDER BY table_name
                """
            )
        ]
        rows = await conn.fetch(
            """
            SELECT
                c.relname,
                c.relrowsecurity,
                c.relforcerowsecurity,
                (
                    SELECT count(*)
                    FROM pg_policies p
                    WHERE p.schemaname='public'
                      AND p.tablename=c.relname
                ) AS policy_count
            FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public'
              AND c.relkind='r'
              AND c.relname=ANY($1::text[])
            """,
            tenant_tables,
        )
        by_name = {str(r["relname"]): r for r in rows}
        failures = []
        for table in tenant_tables:
            row = by_name.get(table)
            if (
                row is None
                or not bool(row["relrowsecurity"])
                or not bool(row["relforcerowsecurity"])
                or int(row["policy_count"] or 0) < 1
            ):
                failures.append(table)

        if failures:
            raise AssertionError(
                f"FREEZE_V3_SCHEMA_RLS_FAILED: {failures}"
            )

        print(
            "FREEZE_V3_SCHEMA_RLS_FORCE_POLICY=OK "
            f"tenant_tables={len(tenant_tables)}"
        )
    finally:
        await conn.close()


async def verify_cross_tenant_and_pool(a: int, b: int) -> None:
    conn = await app_conn()
    try:
        await conn.execute(
            "SELECT set_config('app.current_tenant', $1, false)",
            str(a),
        )
        visible_b = int(
            await conn.fetchval(
                """
                SELECT count(*) FROM system_settings
                WHERE company_id=$1
                """,
                b,
            )
        )
        if visible_b != 0:
            raise AssertionError("FREEZE_V3_CROSS_TENANT_READ_FAILED")

        update = await conn.execute(
            """
            UPDATE system_settings
            SET setting_value=setting_value
            WHERE company_id=$1
            """,
            b,
        )
        if update != "UPDATE 0":
            raise AssertionError(
                f"FREEZE_V3_CROSS_TENANT_UPDATE_FAILED: {update}"
            )

        blocked = False
        try:
            await conn.execute(
                """
                INSERT INTO system_settings
                    (company_id, setting_key, setting_value, description)
                VALUES
                    ($1, 'freeze_v3_spoof', 'x', 'must fail')
                """,
                b,
            )
        except Exception as exc:
            if (
                getattr(exc, "sqlstate", None) == "42501"
                or "row-level security" in str(exc).lower()
            ):
                blocked = True
            else:
                raise
        if not blocked:
            raise AssertionError("FREEZE_V3_CROSS_TENANT_INSERT_FAILED")
    finally:
        await conn.close()

    from sqlalchemy import func, select, text
    from context import tenant_context
    from database import AsyncSessionLocal
    from models import SystemSetting

    token = tenant_context.set(a)
    try:
        async with AsyncSessionLocal() as db:
            own = int(
                (
                    await db.execute(
                        select(func.count(SystemSetting.id)).where(
                            SystemSetting.company_id == a
                        )
                    )
                ).scalar_one()
            )
            if own != 1:
                raise AssertionError(
                    f"FREEZE_V3_SELF_TENANT_READ_FAILED: {own}"
                )
    finally:
        tenant_context.reset(token)

    async with AsyncSessionLocal() as db:
        visible = int(
            (
                await db.execute(
                    select(func.count(SystemSetting.id)).where(
                        SystemSetting.company_id.in_([a, b])
                    )
                )
            ).scalar_one()
        )
        current = (
            await db.execute(
                text("SELECT current_setting('app.current_tenant', true)")
            )
        ).scalar_one()

    if visible != 0 or current not in ("", None):
        raise AssertionError(
            "FREEZE_V3_POOL_RESIDUE_FAILED: "
            f"visible={visible} current={current!r}"
        )

    print("FREEZE_V3_HOSTILE_RLS_READ_UPDATE_INSERT=OK")
    print("FREEZE_V3_POOL_TENANT_RESIDUE=OK")


async def verify_audit_immutability(a: int) -> None:
    app = await app_conn()
    migration = await migration_conn()
    try:
        await app.execute(
            "SELECT set_config('app.current_tenant', $1, false)",
            str(a),
        )
        audit_id = int(
            await app.fetchval(
                """
                INSERT INTO system_audit_logs
                    (company_id, admin_id, target_id, action_type,
                     old_value, new_value, timestamp)
                VALUES
                    ($1, NULL, 'FreezeV3', 'FREEZE_V3_AUDIT',
                     NULL, 'original', $2)
                RETURNING id
                """,
                a,
                datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )

        for sql, label in [
            (
                """
                UPDATE system_audit_logs
                SET new_value='tampered'
                WHERE id=$1
                """,
                "UPDATE",
            ),
            (
                "DELETE FROM system_audit_logs WHERE id=$1",
                "DELETE",
            ),
        ]:
            blocked = False
            try:
                await app.execute(sql, audit_id)
            except Exception:
                blocked = True
            if not blocked:
                raise AssertionError(
                    f"FREEZE_V3_AUDIT_{label}_NOT_BLOCKED"
                )

        row = await migration.fetchrow(
            """
            SELECT new_value
            FROM system_audit_logs
            WHERE id=$1 AND company_id=$2
            """,
            audit_id,
            a,
        )
        if row is None or str(row["new_value"]) != "original":
            raise AssertionError("FREEZE_V3_AUDIT_TAMPERED")

        trigger_exists = await migration.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_trigger
                WHERE tgrelid='public.system_audit_logs'::regclass
                  AND tgname=$1
                  AND tgenabled <> 'D'
                  AND NOT tgisinternal
            )
            """,
            AUDIT_TRIGGER,
        )
        if not trigger_exists:
            raise AssertionError("FREEZE_V3_AUDIT_TRIGGER_DISABLED")

        print("FREEZE_V3_AUDIT_APPEND_ONLY_RUNTIME=OK")
    finally:
        await app.close()
        await migration.close()


async def run() -> None:
    verify_static()
    verify_procrastinate_health()
    await verify_role_and_schema_rls()

    try:
        a, b = await setup_fixture()
        print(f"FREEZE_V3_FIXTURE=OK A={a} B={b}")
        await verify_cross_tenant_and_pool(a, b)
        await verify_audit_immutability(a)
        print("WORKERS_FINAL_FREEZE_GATE_V3=PASS")
    finally:
        conn = await migration_conn()
        try:
            async with conn.transaction():
                await cleanup(conn)
            print("FREEZE_V3_CLEANUP=OK")
        finally:
            await conn.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()
        )
    asyncio.run(run())
