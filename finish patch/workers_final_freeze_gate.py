from __future__ import annotations

import asyncio
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

COMPANY_A_CODE = "WKR-FREEZE-GATE-A"
COMPANY_B_CODE = "WKR-FREEZE-GATE-B"


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


async def connect_migration():
    return await asyncpg.connect(normalize_pg_url(MIGRATION_URL))


async def connect_app():
    return await asyncpg.connect(normalize_pg_url(APP_URL))


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.exists():
        raise AssertionError(f"MISSING_REQUIRED_FILE: {rel}")
    return path.read_text(encoding="utf-8")


def verify_worker_source_contracts() -> None:
    app = read("wa_backend/workers/app.py")
    tenant = read("wa_backend/workers/tenant.py")
    database = read("wa_backend/database.py")
    handshake = read("wa_backend/workers/tasks/handshake.py")
    session = read("wa_backend/workers/tasks/session_monitor.py")
    integrity = read("wa_backend/workers/tasks/integrity.py")
    reports = read("wa_backend/workers/tasks/reports.py")
    readme = read("wa_backend/workers/README.md")

    required_imports = [
        '"workers.tasks.core"',
        '"workers.tasks.handshake"',
        '"workers.tasks.session_monitor"',
        '"workers.tasks.integrity"',
        '"workers.tasks.reports"',
    ]
    missing_imports = [x for x in required_imports if x not in app]
    if missing_imports:
        raise AssertionError(f"WORKER_IMPORTS_MISSING: {missing_imports}")

    for queue_name in ["maintenance", "notifications", "reports"]:
        if queue_name not in app:
            raise AssertionError(f"QUEUE_NAME_MISSING: {queue_name}")

    # Tenant context must be set and reset by the worker tenant wrapper.
    if "tenant_context.set" not in tenant or "tenant_context.reset" not in tenant:
        raise AssertionError("TENANT_CONTEXT_SET_RESET_CONTRACT_FAILED")
    if "AsyncSessionLocal" not in tenant:
        raise AssertionError("TENANT_SESSION_FACTORY_CONTRACT_FAILED")

    # DB checkout must actively clear tenant state on no-tenant checkouts.
    if "set_config('app.current_tenant', '', false)" not in database:
        raise AssertionError("DB_CHECKOUT_TENANT_CLEAR_CONTRACT_FAILED")

    # Stale handshake monitor: monitor/alert only.
    forbidden_handshake = [
        "force_cancel_handshake",
        "apply_inventory_movements_batch",
    ]
    for token in forbidden_handshake:
        if token in handshake:
            raise AssertionError(
                f"HANDSHAKE_MONITOR_FORBIDDEN_MUTATION_TOKEN: {token}"
            )
    if re.search(r"\.status\s*=(?!=)", handshake):
        raise AssertionError("HANDSHAKE_MONITOR_STATUS_MUTATION_FOUND")

    # Session monitor: never closes/settles sessions or touches inventory.
    for pattern, label in [
        (r"\.end_time\s*=(?!=)", "SESSION_END_WRITE"),
        (r"\.is_settled\s*=(?!=)", "SESSION_SETTLEMENT_WRITE"),
    ]:
        if re.search(pattern, session):
            raise AssertionError(f"{label}_FOUND")
    if "apply_inventory_movements" in session:
        raise AssertionError("SESSION_MONITOR_INVENTORY_MUTATION_FOUND")

    # Integrity jobs: business data is read-only; only audit/event writes allowed.
    for pattern, label in [
        (r"\bupdate\s*\(", "INTEGRITY_SQL_UPDATE"),
        (r"\bdelete\s*\(", "INTEGRITY_SQL_DELETE"),
        (r"\binsert\s*\(", "INTEGRITY_SQL_INSERT"),
        (r"\.status\s*=(?!=)", "INTEGRITY_STATUS_WRITE"),
        (r"\.end_time\s*=(?!=)", "INTEGRITY_END_WRITE"),
        (r"\.is_settled\s*=(?!=)", "INTEGRITY_SETTLEMENT_WRITE"),
    ]:
        if re.search(pattern, integrity, re.I):
            raise AssertionError(f"{label}_FOUND")
    if "SystemAuditLog(" not in integrity:
        raise AssertionError("INTEGRITY_AUDIT_WRITE_MISSING")

    # Reports: separate queue + tenant session + PostgreSQL read-only transaction.
    for token in [
        "queue=REPORTS_QUEUE",
        "company_id: int",
        "async with tenant_session(company_id)",
        'text("SET TRANSACTION READ ONLY")',
    ]:
        if token not in reports:
            raise AssertionError(f"REPORT_CONTRACT_MISSING: {token}")
    for pattern, label in [
        (r"\bupdate\s*\(", "REPORT_SQL_UPDATE"),
        (r"\bdelete\s*\(", "REPORT_SQL_DELETE"),
        (r"\binsert\s*\(", "REPORT_SQL_INSERT"),
    ]:
        if re.search(pattern, reports, re.I):
            raise AssertionError(f"{label}_FOUND")

    # Frozen runbook commands must exist.
    for command in [
        "worker -q maintenance,notifications -c 4",
        "worker -q reports -c 1",
        "healthchecks",
    ]:
        if command not in readme:
            raise AssertionError(f"RUNBOOK_COMMAND_MISSING: {command}")

    print("WORKERS_SOURCE_CONTRACTS=OK")
    print("WORKERS_NO_UNAPPROVED_WORKFLOW_MUTATION=OK")
    print("WORKERS_ROOT_RUNBOOK=OK")


def verify_cli_healthchecks() -> None:
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
            "PROCRASTINATE_HEALTHCHECK_FAILED:\n" + output[-4000:]
        )

    required = [
        "App configuration: OK",
        "DB connection: OK",
        "Found procrastinate_jobs table: OK",
    ]
    missing = [line for line in required if line not in output]
    if missing:
        raise AssertionError(
            f"PROCRASTINATE_HEALTHCHECK_OUTPUT_INCOMPLETE: {missing}\n{output}"
        )

    print("PROCRASTINATE_HEALTHCHECKS=OK")


async def cleanup(conn) -> None:
    rows = await conn.fetch(
        """
        SELECT id
        FROM companies
        WHERE company_code = ANY($1::text[])
        """,
        [COMPANY_A_CODE, COMPANY_B_CODE],
    )
    company_ids = [int(row["id"]) for row in rows]
    if not company_ids:
        return

    await conn.execute(
        "DELETE FROM system_settings WHERE company_id = ANY($1::int[])",
        company_ids,
    )
    await conn.execute(
        "DELETE FROM work_sessions WHERE company_id = ANY($1::int[])",
        company_ids,
    )
    await conn.execute(
        "DELETE FROM drivers WHERE company_id = ANY($1::int[])",
        company_ids,
    )
    await conn.execute(
        "DELETE FROM companies WHERE id = ANY($1::int[])",
        company_ids,
    )


async def setup_fixture() -> dict:
    conn = await connect_migration()
    try:
        async with conn.transaction():
            await cleanup(conn)
            now = datetime.now(timezone.utc).replace(tzinfo=None)

            async def create_company(code: str, label: str):
                company_id = int(
                    await conn.fetchval(
                        """
                        INSERT INTO companies
                            (name, company_code, is_active, subscription_status,
                             currency_code, timezone, created_at)
                        VALUES
                            ($1, $2, TRUE, 'active', 'JOD', 'Asia/Amman', $3)
                        RETURNING id
                        """,
                        f"Worker Freeze Gate {label}",
                        code,
                        now,
                    )
                )
                driver_id = int(
                    await conn.fetchval(
                        """
                        INSERT INTO drivers
                            (company_id, username, password_hash, full_name,
                             is_active, is_admin, can_allow_debt,
                             max_debt_limit, created_at)
                        VALUES
                            ($1, $2, 'x', $3, TRUE, FALSE, FALSE, 0, $4)
                        RETURNING id
                        """,
                        company_id,
                        f"freeze_gate_{label}",
                        f"Freeze Gate {label}",
                        now,
                    )
                )
                session_id = int(
                    await conn.fetchval(
                        """
                        INSERT INTO work_sessions
                            (company_id, driver_id, start_time, session_date,
                             is_authorized_to_sell, is_settled)
                        VALUES
                            ($1, $2, $3, $4, FALSE, FALSE)
                        RETURNING id
                        """,
                        company_id,
                        driver_id,
                        now,
                        now.date(),
                    )
                )
                setting_id = int(
                    await conn.fetchval(
                        """
                        INSERT INTO system_settings
                            (company_id, setting_key, setting_value, description)
                        VALUES
                            ($1, 'freeze_gate_key', $2, 'Worker final freeze gate')
                        RETURNING id
                        """,
                        company_id,
                        label,
                    )
                )
                return {
                    "company_id": company_id,
                    "driver_id": driver_id,
                    "session_id": session_id,
                    "setting_id": setting_id,
                }

            a = await create_company(COMPANY_A_CODE, "A")
            b = await create_company(COMPANY_B_CODE, "B")

        return {"a": a, "b": b}
    finally:
        await conn.close()


async def verify_app_role_security() -> None:
    conn = await connect_app()
    try:
        row = await conn.fetchrow(
            """
            SELECT r.rolname, r.rolsuper, r.rolbypassrls
            FROM pg_roles r
            WHERE r.rolname = current_user
            """
        )
        if row is None:
            raise AssertionError("APP_ROLE_NOT_FOUND")
        if bool(row["rolsuper"]):
            raise AssertionError("APP_ROLE_MUST_NOT_BE_SUPERUSER")
        if bool(row["rolbypassrls"]):
            raise AssertionError("APP_ROLE_MUST_NOT_HAVE_BYPASSRLS")

        print(f"APP_ROLE_SECURITY=OK role={row['rolname']}")
    finally:
        await conn.close()


async def verify_schema_wide_rls() -> None:
    conn = await connect_migration()
    try:
        tenant_tables = [
            str(row["table_name"])
            for row in await conn.fetch(
                """
                SELECT DISTINCT table_name
                FROM information_schema.columns
                WHERE table_schema='public'
                  AND column_name='company_id'
                ORDER BY table_name
                """
            )
        ]
        if not tenant_tables:
            raise AssertionError("NO_TENANT_TABLES_DISCOVERED")

        rows = await conn.fetch(
            """
            SELECT
                c.relname AS table_name,
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
              AND c.relname = ANY($1::text[])
            ORDER BY c.relname
            """,
            tenant_tables,
        )

        by_table = {str(row["table_name"]): row for row in rows}
        failures = []
        for table in tenant_tables:
            row = by_table.get(table)
            if row is None:
                failures.append(f"{table}:metadata_missing")
                continue
            if not bool(row["relrowsecurity"]):
                failures.append(f"{table}:RLS_disabled")
            if not bool(row["relforcerowsecurity"]):
                failures.append(f"{table}:FORCE_RLS_disabled")
            if int(row["policy_count"] or 0) < 1:
                failures.append(f"{table}:policy_missing")

        if failures:
            raise AssertionError(
                "SCHEMA_WIDE_RLS_FAILED:\n" + "\n".join(failures)
            )

        print(
            f"SCHEMA_WIDE_RLS_FORCE_POLICY=OK tenant_tables={len(tenant_tables)}"
        )
    finally:
        await conn.close()


async def verify_hostile_cross_tenant(info: dict) -> None:
    conn = await connect_app()
    try:
        a = info["a"]
        b = info["b"]

        await conn.execute(
            "SELECT set_config('app.current_tenant', $1, false)",
            str(a["company_id"]),
        )

        # Cross-tenant reads on two representative tenant-owned tables.
        visible_b_sessions = int(
            await conn.fetchval(
                "SELECT count(*) FROM work_sessions WHERE id=$1",
                b["session_id"],
            )
        )
        visible_b_settings = int(
            await conn.fetchval(
                "SELECT count(*) FROM system_settings WHERE id=$1",
                b["setting_id"],
            )
        )
        if visible_b_sessions != 0 or visible_b_settings != 0:
            raise AssertionError(
                "HOSTILE_CROSS_TENANT_READ_FAILED: "
                f"sessions={visible_b_sessions}, settings={visible_b_settings}"
            )

        update_status = await conn.execute(
            """
            UPDATE work_sessions
            SET is_authorized_to_sell = TRUE
            WHERE id=$1
            """,
            b["session_id"],
        )
        if update_status != "UPDATE 0":
            raise AssertionError(
                f"HOSTILE_CROSS_TENANT_UPDATE_FAILED: {update_status}"
            )

        insert_blocked = False
        try:
            await conn.execute(
                """
                INSERT INTO system_settings
                    (company_id, setting_key, setting_value, description)
                VALUES
                    ($1, 'freeze_gate_spoof', 'x', 'must be blocked')
                """,
                b["company_id"],
            )
        except Exception as exc:
            sqlstate = getattr(exc, "sqlstate", None)
            if sqlstate == "42501" or "row-level security" in str(exc).lower():
                insert_blocked = True
            else:
                raise
        if not insert_blocked:
            raise AssertionError("HOSTILE_CROSS_TENANT_INSERT_FAILED")

        await conn.execute(
            "SELECT set_config('app.current_tenant', $1, false)",
            str(b["company_id"]),
        )
        reverse_visible = int(
            await conn.fetchval(
                "SELECT count(*) FROM work_sessions WHERE id=$1",
                a["session_id"],
            )
        )
        if reverse_visible != 0:
            raise AssertionError("HOSTILE_REVERSE_CROSS_TENANT_READ_FAILED")

        print("HOSTILE_RLS_READ_UPDATE_INSERT_BIDIRECTIONAL=OK")
    finally:
        await conn.close()


async def verify_pool_residue(info: dict) -> None:
    from sqlalchemy import func, select, text
    from context import tenant_context
    from database import AsyncSessionLocal
    from models import WorkSession

    a_company = info["a"]["company_id"]

    token = tenant_context.set(a_company)
    try:
        async with AsyncSessionLocal() as db:
            own = int(
                (
                    await db.execute(
                        select(func.count(WorkSession.id)).where(
                            WorkSession.company_id == a_company
                        )
                    )
                ).scalar_one()
            )
            if own != 1:
                raise AssertionError(
                    f"POOL_SELF_TENANT_READ_FAILED: expected=1 got={own}"
                )
    finally:
        tenant_context.reset(token)

    async with AsyncSessionLocal() as db:
        no_tenant_visible = int(
            (
                await db.execute(
                    select(func.count(WorkSession.id))
                )
            ).scalar_one()
        )
        current = (
            await db.execute(
                text("SELECT current_setting('app.current_tenant', true)")
            )
        ).scalar_one()

    if no_tenant_visible != 0:
        raise AssertionError(
            f"POOL_TENANT_RESIDUE_ROWS_VISIBLE: {no_tenant_visible}"
        )
    if current not in ("", None):
        raise AssertionError(
            f"POOL_TENANT_RESIDUE_SETTING_PRESENT: {current!r}"
        )

    print("CONNECTION_POOL_TENANT_RESIDUE=OK")


async def verify_reports_read_only_db_guard(company_id: int) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from workers.tenant import tenant_session

    blocked = False
    async with tenant_session(company_id) as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        try:
            await db.execute(
                text(
                    """
                    UPDATE work_sessions
                    SET is_authorized_to_sell = NOT is_authorized_to_sell
                    WHERE company_id = :company_id
                    """
                ),
                {"company_id": int(company_id)},
            )
        except DBAPIError as exc:
            original = getattr(exc, "orig", exc)
            sqlstate = getattr(original, "sqlstate", None)
            if sqlstate == "25006" or "read-only transaction" in str(original).lower():
                blocked = True
            else:
                raise
        finally:
            await db.rollback()

    if not blocked:
        raise AssertionError("REPORTS_READ_ONLY_DB_GUARD_FAILED")

    print("REPORTS_POSTGRES_READ_ONLY_GUARD=OK")


async def async_gate() -> None:
    await verify_app_role_security()
    await verify_schema_wide_rls()

    info = None
    try:
        info = await setup_fixture()
        print(
            "WORKERS_FREEZE_FIXTURE=OK "
            f"A={info['a']['company_id']} B={info['b']['company_id']}"
        )

        await verify_hostile_cross_tenant(info)
        await verify_pool_residue(info)
        await verify_reports_read_only_db_guard(info["a"]["company_id"])

        print("WORKERS_FINAL_POSTGRES_ISOLATION_GATE=OK")
    finally:
        conn = await connect_migration()
        try:
            async with conn.transaction():
                await cleanup(conn)
            print("WORKERS_FREEZE_GATE_CLEANUP=OK")
        finally:
            await conn.close()


def main() -> None:
    verify_worker_source_contracts()
    verify_cli_healthchecks()
    asyncio.run(async_gate())
    print("WORKERS_FINAL_FREEZE_GATE=PASS")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()
        )
    main()
