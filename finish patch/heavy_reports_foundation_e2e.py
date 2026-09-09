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

COMPANY_A_CODE = "WKR-REPORT-E2E-A"
COMPANY_B_CODE = "WKR-REPORT-E2E-B"


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
    company_ids = [int(row["id"]) for row in rows]
    if not company_ids:
        return

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


async def setup():
    conn = await connect_migration()
    try:
        async with conn.transaction():
            await cleanup(conn)
            now = datetime.now(timezone.utc).replace(tzinfo=None)

            async def make_company(code: str, label: str, sessions: int):
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
                        f"Report E2E {label}",
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
                        f"report_e2e_driver_{label}",
                        f"Report E2E Driver {label}",
                        now,
                    )
                )

                session_ids = []
                for index in range(sessions):
                    sid = int(
                        await conn.fetchval(
                            """
                            INSERT INTO work_sessions
                                (company_id, driver_id, start_time, end_time,
                                 session_date, is_authorized_to_sell, is_settled)
                            VALUES
                                ($1, $2, $3, $4, $5, FALSE, FALSE)
                            RETURNING id
                            """,
                            company_id,
                            driver_id,
                            now - timedelta(days=index + 2),
                            now - timedelta(days=index + 2, hours=-1),
                            (now - timedelta(days=index + 2)).date(),
                        )
                    )
                    session_ids.append(sid)

                return company_id, driver_id, session_ids

            company_a, driver_a, sessions_a = await make_company(
                COMPANY_A_CODE, "A", 2
            )
            company_b, driver_b, sessions_b = await make_company(
                COMPANY_B_CODE, "B", 3
            )

        return {
            "company_a": company_a,
            "company_b": company_b,
            "driver_a": driver_a,
            "driver_b": driver_b,
            "sessions_a": sessions_a,
            "sessions_b": sessions_b,
        }
    finally:
        await conn.close()


async def snapshot_business_state(info: dict):
    conn = await connect_migration()
    try:
        rows = await conn.fetch(
            """
            SELECT company_id, id, end_time, is_settled, is_authorized_to_sell
            FROM work_sessions
            WHERE company_id = ANY($1::int[])
            ORDER BY company_id, id
            """,
            [info["company_a"], info["company_b"]],
        )
        return [
            (
                int(row["company_id"]),
                int(row["id"]),
                row["end_time"],
                bool(row["is_settled"]),
                bool(row["is_authorized_to_sell"]),
            )
            for row in rows
        ]
    finally:
        await conn.close()


async def job_row(job_id: int):
    conn = await connect_migration()
    try:
        return await conn.fetchrow(
            """
            SELECT id, queue_name, task_name, status, args
            FROM worker_queue.procrastinate_jobs
            WHERE id=$1
            """,
            int(job_id),
        )
    finally:
        await conn.close()


async def verify_db_read_only_guard(company_id: int):
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
            message = str(original).lower()
            if sqlstate == "25006" or "read-only transaction" in message:
                blocked = True
            else:
                raise
        finally:
            await db.rollback()

    if not blocked:
        raise AssertionError(
            "REPORT_READ_ONLY_GUARD_FAILED: PostgreSQL allowed business UPDATE."
        )


async def verify_rls(info: dict):
    conn = await connect_app()
    try:
        await conn.execute(
            "SELECT set_config('app.current_tenant', $1, false)",
            str(info["company_a"]),
        )

        cross_read = int(
            await conn.fetchval(
                "SELECT count(*) FROM work_sessions WHERE company_id=$1",
                info["company_b"],
            )
        )
        if cross_read != 0:
            raise AssertionError(
                f"REPORT_RLS_CROSS_READ_FAILED: visible={cross_read}"
            )

        update_status = await conn.execute(
            """
            UPDATE work_sessions
            SET is_authorized_to_sell = is_authorized_to_sell
            WHERE company_id=$1
            """,
            info["company_b"],
        )
        if update_status != "UPDATE 0":
            raise AssertionError(
                f"REPORT_RLS_CROSS_UPDATE_FAILED: {update_status}"
            )

        insert_blocked = False
        try:
            await conn.execute(
                """
                INSERT INTO work_sessions
                    (company_id, driver_id, start_time, session_date,
                     is_authorized_to_sell, is_settled)
                VALUES ($1, $2, $3, $4, FALSE, FALSE)
                """,
                info["company_b"],
                info["driver_b"],
                datetime.now(timezone.utc).replace(tzinfo=None),
                datetime.now(timezone.utc).date(),
            )
        except Exception as exc:
            sqlstate = getattr(exc, "sqlstate", None)
            if sqlstate == "42501" or "row-level security" in str(exc).lower():
                insert_blocked = True
            else:
                raise

        if not insert_blocked:
            raise AssertionError("REPORT_RLS_CROSS_INSERT_FAILED")
    finally:
        await conn.close()


async def verify_pool_residue(info: dict):
    from sqlalchemy import func, select, text
    from context import tenant_context
    from database import AsyncSessionLocal
    from models import WorkSession

    token = tenant_context.set(info["company_a"])
    try:
        async with AsyncSessionLocal() as db:
            count_a = int(
                (
                    await db.execute(
                        select(func.count(WorkSession.id)).where(
                            WorkSession.company_id == info["company_a"]
                        )
                    )
                ).scalar_one()
            )
            if count_a != 2:
                raise AssertionError(
                    f"REPORT_TENANT_A_SELF_READ_FAILED: {count_a}"
                )
    finally:
        tenant_context.reset(token)

    async with AsyncSessionLocal() as db:
        visible = int(
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

    if visible != 0:
        raise AssertionError(
            f"REPORT_POOL_RESIDUE_FAILED: no-tenant visible={visible}"
        )
    if current not in ("", None):
        raise AssertionError(
            f"REPORT_POOL_RESIDUE_FAILED: tenant={current!r}"
        )


async def run():
    conn = await connect_migration()
    try:
        async with conn.transaction():
            await cleanup(conn)
    finally:
        await conn.close()

    info = None
    try:
        info = await setup()
        print(
            "REPORT_E2E_SETUP=OK "
            f"A={info['company_a']} B={info['company_b']}"
        )

        before = await snapshot_business_state(info)

        await verify_db_read_only_guard(info["company_a"])
        print("REPORT_E2E_POSTGRES_READ_ONLY_GUARD=OK")

        from workers.app import app
        from workers.tasks.reports import report_foundation_probe

        async with app.open_async():
            job_id = int(
                await report_foundation_probe.defer_async(
                    company_id=info["company_a"]
                )
            )
            row = await job_row(job_id)
            if row is None:
                raise AssertionError("REPORT_QUEUE_JOB_MISSING")
            if str(row["queue_name"]) != "reports":
                raise AssertionError(
                    f"REPORT_QUEUE_WRONG: {row['queue_name']!r}"
                )
            if str(row["task_name"]) != "wanasah.report_foundation_probe":
                raise AssertionError(
                    f"REPORT_TASK_NAME_WRONG: {row['task_name']!r}"
                )
            print(
                f"REPORT_E2E_REPORT_JOB_DEFERRED=OK job_id={job_id} queue=reports"
            )

            # An operational worker must NOT consume a reports job.
            await app.run_worker_async(
                queues=["maintenance", "notifications"],
                concurrency=1,
                wait=False,
                install_signal_handlers=False,
            )
            row = await job_row(job_id)
            if str(row["status"]) != "todo":
                raise AssertionError(
                    "REPORT_QUEUE_ISOLATION_FAILED: operational worker "
                    f"changed report job to {row['status']!r}"
                )
            print("REPORT_E2E_OPERATIONAL_WORKER_CANNOT_CONSUME_REPORTS=OK")

            # The reports worker consumes exactly the reports queue.
            await app.run_worker_async(
                queues=["reports"],
                concurrency=1,
                wait=False,
                install_signal_handlers=False,
            )

            row = await job_row(job_id)
            if str(row["status"]) != "succeeded":
                raise AssertionError(
                    f"REPORT_JOB_NOT_SUCCEEDED: {row['status']!r}"
                )
            print("REPORT_E2E_REPORTS_WORKER_EXECUTION=OK")

        after = await snapshot_business_state(info)
        if before != after:
            raise AssertionError(
                f"REPORT_WORKFLOW_MUTATION_FAILED: before={before}, after={after}"
            )
        print("REPORT_E2E_NO_BUSINESS_MUTATION=OK")

        await verify_rls(info)
        print("REPORT_E2E_RLS_READ_UPDATE_INSERT=OK")

        await verify_pool_residue(info)
        print("REPORT_E2E_POOL_TENANT_RESIDUE=OK")

        print("HEAVY_REPORTS_FOUNDATION_POSTGRES_E2E=OK")
    finally:
        conn = await connect_migration()
        try:
            async with conn.transaction():
                await cleanup(conn)
            print("REPORT_E2E_CLEANUP=OK")
        finally:
            await conn.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()
        )
    asyncio.run(run())
