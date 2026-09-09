from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
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

COMPANY_A_CODE = "WKR-SESSION-E2E-A"
COMPANY_B_CODE = "WKR-SESSION-E2E-B"


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


async def cleanup(conn):
    rows = await conn.fetch(
        """
        SELECT id
        FROM companies
        WHERE company_code = ANY($1::text[])
        """,
        [COMPANY_A_CODE, COMPANY_B_CODE],
    )
    ids = [int(r["id"]) for r in rows]
    if not ids:
        return

    await conn.execute(
        "DELETE FROM system_audit_logs WHERE company_id = ANY($1::int[])",
        ids,
    )
    await conn.execute(
        "DELETE FROM system_settings WHERE company_id = ANY($1::int[])",
        ids,
    )
    await conn.execute(
        "DELETE FROM work_sessions WHERE company_id = ANY($1::int[])",
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


async def setup():
    conn = await connect_migration()
    try:
        async with conn.transaction():
            await cleanup(conn)

            now = datetime.now(timezone.utc).replace(tzinfo=None)

            async def make_company(code: str, label: str):
                company_id = await conn.fetchval(
                    """
                    INSERT INTO companies
                        (name, company_code, is_active, subscription_status,
                         currency_code, timezone, created_at)
                    VALUES
                        ($1, $2, TRUE, 'active', 'JOD', 'Asia/Amman', $3)
                    RETURNING id
                    """,
                    f"Session E2E {label}",
                    code,
                    now,
                )

                driver_id = await conn.fetchval(
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
                    f"session_e2e_driver_{label}",
                    f"Session E2E Driver {label}",
                    now,
                )

                spoof_driver_id = await conn.fetchval(
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
                    f"session_e2e_spoof_{label}",
                    f"Session E2E Spoof {label}",
                    now,
                )

                for key, value in [
                    ("session_warning_hours", "12"),
                    ("session_critical_hours", "16"),
                ]:
                    await conn.execute(
                        """
                        INSERT INTO system_settings
                            (company_id, setting_key, setting_value, description)
                        VALUES ($1, $2, $3, 'Session Monitor E2E')
                        """,
                        company_id,
                        key,
                        value,
                    )

                return int(company_id), int(driver_id), int(spoof_driver_id)

            company_a, driver_a, spoof_a = await make_company(
                COMPANY_A_CODE, "A"
            )
            company_b, driver_b, spoof_b = await make_company(
                COMPANY_B_CODE, "B"
            )

            session_a = await conn.fetchval(
                """
                INSERT INTO work_sessions
                    (company_id, driver_id, start_time, session_date,
                     is_authorized_to_sell, is_settled)
                VALUES ($1, $2, $3, $4, TRUE, FALSE)
                RETURNING id
                """,
                company_a,
                driver_a,
                now - timedelta(hours=13),
                (now - timedelta(hours=13)).date(),
            )

            session_b = await conn.fetchval(
                """
                INSERT INTO work_sessions
                    (company_id, driver_id, start_time, session_date,
                     is_authorized_to_sell, is_settled)
                VALUES ($1, $2, $3, $4, TRUE, FALSE)
                RETURNING id
                """,
                company_b,
                driver_b,
                now - timedelta(hours=17),
                (now - timedelta(hours=17)).date(),
            )

        return {
            "company_a": company_a,
            "company_b": company_b,
            "driver_a": driver_a,
            "driver_b": driver_b,
            "spoof_b": spoof_b,
            "session_a": int(session_a),
            "session_b": int(session_b),
        }
    finally:
        await conn.close()


async def audit_counts(company_id: int):
    conn = await connect_migration()
    try:
        rows = await conn.fetch(
            """
            SELECT action_type, count(*) AS c
            FROM system_audit_logs
            WHERE company_id = $1
              AND action_type IN (
                'STALE_SESSION_WARNING',
                'STALE_SESSION_CRITICAL'
              )
            GROUP BY action_type
            """,
            company_id,
        )
        data = {r["action_type"]: int(r["c"]) for r in rows}
        return (
            data.get("STALE_SESSION_WARNING", 0),
            data.get("STALE_SESSION_CRITICAL", 0),
        )
    finally:
        await conn.close()


async def wait_for_counts(company_id: int, expected: tuple[int, int]):
    for _ in range(60):
        counts = await audit_counts(company_id)
        if counts == expected:
            return
        await asyncio.sleep(0.25)
    raise AssertionError(
        f"Worker result not observed for company {company_id}; "
        f"expected={expected}, got={await audit_counts(company_id)}. "
        "Confirm the worker process is running."
    )


async def defer_company(company_id: int):
    from workers.app import app
    from workers.tasks.session_monitor import scan_company_stale_sessions

    async with app.open_async():
        job_id = await scan_company_stale_sessions.defer_async(
            company_id=int(company_id)
        )
    return int(job_id)


async def verify_rls_and_writes(info: dict):
    conn = await connect_app()
    try:
        await conn.execute(
            "SELECT set_config('app.current_tenant', $1, false)",
            str(info["company_a"]),
        )

        cross_read = await conn.fetchval(
            "SELECT count(*) FROM work_sessions WHERE id=$1",
            info["session_b"],
        )
        if int(cross_read) != 0:
            raise AssertionError(
                f"CROSS_TENANT_READ_FAILED: A saw B session ({cross_read})."
            )

        update_status = await conn.execute(
            """
            UPDATE work_sessions
            SET is_authorized_to_sell = is_authorized_to_sell
            WHERE id=$1
            """,
            info["session_b"],
        )
        if update_status != "UPDATE 0":
            raise AssertionError(
                f"CROSS_TENANT_UPDATE_FAILED: status={update_status}"
            )

        insert_blocked_by_rls = False
        try:
            await conn.execute(
                """
                INSERT INTO work_sessions
                    (company_id, driver_id, start_time, session_date,
                     is_authorized_to_sell, is_settled)
                VALUES ($1, $2, $3, $4, FALSE, FALSE)
                """,
                info["company_b"],
                info["spoof_b"],
                datetime.now(timezone.utc).replace(tzinfo=None),
                datetime.now(timezone.utc).date(),
            )
        except Exception as exc:
            sqlstate = getattr(exc, "sqlstate", None)
            text = str(exc).lower()
            if sqlstate == "42501" or "row-level security" in text:
                insert_blocked_by_rls = True
            else:
                raise AssertionError(
                    f"Cross-tenant INSERT failed for an unverified reason: {exc}"
                ) from exc

        if not insert_blocked_by_rls:
            raise AssertionError(
                "CROSS_TENANT_INSERT_FAILED: tenant A inserted a tenant B row."
            )

        await conn.execute(
            "SELECT set_config('app.current_tenant', $1, false)",
            str(info["company_b"]),
        )
        reverse_read = await conn.fetchval(
            "SELECT count(*) FROM work_sessions WHERE id=$1",
            info["session_a"],
        )
        if int(reverse_read) != 0:
            raise AssertionError(
                f"CROSS_TENANT_REVERSE_READ_FAILED: B saw A ({reverse_read})."
            )
    finally:
        await conn.close()


async def verify_pool_residue(info: dict):
    from sqlalchemy import func, select
    from context import tenant_context
    from database import AsyncSessionLocal
    from models import WorkSession

    token = tenant_context.set(info["company_a"])
    try:
        async with AsyncSessionLocal() as db:
            visible_a = int(
                (
                    await db.execute(
                        select(func.count(WorkSession.id)).filter(
                            WorkSession.company_id == info["company_a"]
                        )
                    )
                ).scalar_one()
            )
            if visible_a < 1:
                raise AssertionError("Tenant A context could not see its own session.")
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
        current_tenant = (
            await db.execute(
                __import__("sqlalchemy").text(
                    "SELECT current_setting('app.current_tenant', true)"
                )
            )
        ).scalar_one()

    if no_tenant_visible != 0:
        raise AssertionError(
            f"POOL_RESIDUE_FAILED: no-tenant checkout saw {no_tenant_visible} rows."
        )
    if current_tenant not in ("", None):
        raise AssertionError(
            f"POOL_RESIDUE_FAILED: current tenant remained {current_tenant!r}."
        )


async def run():
    info = None
    migration = await connect_migration()
    try:
        await cleanup(migration)
    finally:
        await migration.close()

    try:
        info = await setup()
        print(
            "SESSION_E2E_SETUP=OK "
            f"A={info['company_a']} B={info['company_b']}"
        )

        job_a = await defer_company(info["company_a"])
        print(f"SESSION_E2E_JOB_A_DEFERRED=OK job_id={job_a}")
        await wait_for_counts(info["company_a"], (1, 0))

        # Critical isolation assertion: running A's job must not create B's alert.
        b_before = await audit_counts(info["company_b"])
        if b_before != (0, 0):
            raise AssertionError(
                f"TENANT_JOB_SPOOF/CROSS_SCAN_FAILED: B changed during A job: {b_before}"
            )
        print("SESSION_E2E_TENANT_JOB_ISOLATION=OK")

        job_b = await defer_company(info["company_b"])
        print(f"SESSION_E2E_JOB_B_DEFERRED=OK job_id={job_b}")
        await wait_for_counts(info["company_b"], (0, 1))

        # Repeat both jobs: durable audit must prevent duplicate alerts.
        await defer_company(info["company_a"])
        await defer_company(info["company_b"])
        await asyncio.sleep(1.0)

        if await audit_counts(info["company_a"]) != (1, 0):
            raise AssertionError("SESSION_E2E_DUPLICATE_AUDIT_A_FAILED")
        if await audit_counts(info["company_b"]) != (0, 1):
            raise AssertionError("SESSION_E2E_DUPLICATE_AUDIT_B_FAILED")
        print("SESSION_E2E_NO_DUPLICATE_ALERTS=OK")

        await verify_rls_and_writes(info)
        print("SESSION_E2E_RLS_READ_UPDATE_INSERT=OK")

        await verify_pool_residue(info)
        print("SESSION_E2E_POOL_TENANT_RESIDUE=OK")

        print("SESSION_MONITOR_POSTGRES_E2E=OK")
    finally:
        conn = await connect_migration()
        try:
            async with conn.transaction():
                await cleanup(conn)
            print("SESSION_E2E_CLEANUP=OK")
        finally:
            await conn.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()
        )
    asyncio.run(run())
