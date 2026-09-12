from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

import asyncpg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "wa_backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

load_dotenv(BACKEND / ".env", override=True)

APP_URL = os.getenv("DATABASE_URL")
MIGRATION_URL = os.getenv("DATABASE_URL_MIGRATION")

COMPANY_A_CODE = "WKR-E2E-A"
COMPANY_B_CODE = "WKR-E2E-B"


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


async def get_company_ids(conn):
    rows = await conn.fetch(
        """
        SELECT id, company_code
        FROM companies
        WHERE company_code = ANY($1::text[])
        ORDER BY company_code
        """,
        [COMPANY_A_CODE, COMPANY_B_CODE],
    )
    mapping = {r["company_code"]: r["id"] for r in rows}
    if COMPANY_A_CODE not in mapping or COMPANY_B_CODE not in mapping:
        raise RuntimeError("E2E companies are missing. Run: python worker_handshake_e2e.py setup")
    return mapping[COMPANY_A_CODE], mapping[COMPANY_B_CODE]


async def cleanup_conn(conn):
    rows = await conn.fetch(
        """
        SELECT id
        FROM companies
        WHERE company_code = ANY($1::text[])
        """,
        [COMPANY_A_CODE, COMPANY_B_CODE],
    )
    ids = [r["id"] for r in rows]
    if not ids:
        return

    # Explicit cleanup because system_audit_logs.company_id is RESTRICT.
    await conn.execute("DELETE FROM system_audit_logs WHERE company_id = ANY($1::int[])", ids)
    await conn.execute("DELETE FROM inventory_transfer_headers WHERE company_id = ANY($1::int[])", ids)
    await conn.execute("DELETE FROM work_sessions WHERE company_id = ANY($1::int[])", ids)
    await conn.execute("DELETE FROM inventory_locations WHERE company_id = ANY($1::int[])", ids)
    await conn.execute("DELETE FROM vehicles WHERE company_id = ANY($1::int[])", ids)
    await conn.execute("DELETE FROM system_settings WHERE company_id = ANY($1::int[])", ids)
    await conn.execute("DELETE FROM drivers WHERE company_id = ANY($1::int[])", ids)
    await conn.execute("DELETE FROM companies WHERE id = ANY($1::int[])", ids)


async def setup():
    conn = await connect_migration()
    try:
        async with conn.transaction():
            await cleanup_conn(conn)

            now = datetime.now(timezone.utc).replace(tzinfo=None)

            company_a = await conn.fetchval(
                """
                INSERT INTO companies
                    (name, company_code, is_active, subscription_status,
                     currency_code, timezone, created_at)
                VALUES
                    ('Worker E2E A', $1, TRUE, 'active', 'JOD', 'Asia/Amman', $2)
                RETURNING id
                """,
                COMPANY_A_CODE,
                now,
            )
            company_b = await conn.fetchval(
                """
                INSERT INTO companies
                    (name, company_code, is_active, subscription_status,
                     currency_code, timezone, created_at)
                VALUES
                    ('Worker E2E B', $1, TRUE, 'active', 'JOD', 'Asia/Amman', $2)
                RETURNING id
                """,
                COMPANY_B_CODE,
                now,
            )

            async def seed_company(company_id: int, label: str, age_hours: int):
                dispatcher_id = await conn.fetchval(
                    """
                    INSERT INTO drivers
                        (company_id, username, password_hash, full_name,
                         is_active, is_admin, can_allow_debt, max_debt_limit, created_at)
                    VALUES
                        ($1, $2, 'x', $3, TRUE, TRUE, FALSE, 0, $4)
                    RETURNING id
                    """,
                    company_id,
                    f"e2e_admin_{label}",
                    f"E2E Admin {label}",
                    now,
                )
                receiver_id = await conn.fetchval(
                    """
                    INSERT INTO drivers
                        (company_id, username, password_hash, full_name,
                         is_active, is_admin, can_allow_debt, max_debt_limit, created_at)
                    VALUES
                        ($1, $2, 'x', $3, TRUE, FALSE, FALSE, 0, $4)
                    RETURNING id
                    """,
                    company_id,
                    f"e2e_driver_{label}",
                    f"E2E Driver {label}",
                    now,
                )
                vehicle_id = await conn.fetchval(
                    """
                    INSERT INTO vehicles
                        (company_id, plate_number, vehicle_type, current_mileage,
                         maintenance_status, is_active)
                    VALUES
                        ($1, $2, 'E2E', 0, 'Active', TRUE)
                    RETURNING id
                    """,
                    company_id,
                    f"E2E-{label}",
                )
                source_id = await conn.fetchval(
                    """
                    INSERT INTO inventory_locations
                        (company_id, name, code, location_type, vehicle_id,
                         is_active, created_at, updated_at)
                    VALUES
                        ($1, 'E2E Warehouse', $2, 'WAREHOUSE', NULL, TRUE, $3, $3)
                    RETURNING id
                    """,
                    company_id,
                    f"E2E-WH-{label}",
                    now,
                )
                dest_id = await conn.fetchval(
                    """
                    INSERT INTO inventory_locations
                        (company_id, name, code, location_type, vehicle_id,
                         is_active, created_at, updated_at)
                    VALUES
                        ($1, 'E2E Vehicle', $2, 'VEHICLE', $3, TRUE, $4, $4)
                    RETURNING id
                    """,
                    company_id,
                    f"E2E-VEH-{label}",
                    vehicle_id,
                    now,
                )
                session_id = await conn.fetchval(
                    """
                    INSERT INTO work_sessions
                        (company_id, driver_id, start_time, session_date,
                         is_authorized_to_sell, is_settled)
                    VALUES
                        ($1, $2, $3, $4, TRUE, FALSE)
                    RETURNING id
                    """,
                    company_id,
                    receiver_id,
                    now - timedelta(hours=10),
                    (now - timedelta(hours=10)).date(),
                )

                settings = [
                    ("handshake_warning_hours", "4"),
                    ("handshake_critical_hours", "8"),
                    ("handshake_auto_cancel_hours", "12"),
                    ("handshake_timeout_action", "NOTIFY_ONLY"),
                ]
                for key, value in settings:
                    await conn.execute(
                        """
                        INSERT INTO system_settings
                            (company_id, setting_key, setting_value, description)
                        VALUES ($1, $2, $3, 'Worker E2E')
                        """,
                        company_id,
                        key,
                        value,
                    )

                header_id = await conn.fetchval(
                    """
                    INSERT INTO inventory_transfer_headers
                        (company_id, reference_number, source_location_id,
                         destination_location_id, workflow_type, status,
                         work_session_id, expected_receiver_id, dispatched_by,
                         created_at, updated_at)
                    VALUES
                        ($1, $2, $3, $4, 'HANDSHAKE', 'PENDING',
                         $5, $6, $7, $8, $8)
                    RETURNING id
                    """,
                    company_id,
                    f"E2E-HS-{label}",
                    source_id,
                    dest_id,
                    session_id,
                    receiver_id,
                    dispatcher_id,
                    now - timedelta(hours=age_hours),
                )
                return header_id

            header_a = await seed_company(company_a, "A", 5)  # Warning
            header_b = await seed_company(company_b, "B", 9)  # Critical

        print("HANDSHAKE_E2E_SETUP=OK")
        print(f"COMPANY_A={company_a} HEADER_A={header_a} AGE=5h")
        print(f"COMPANY_B={company_b} HEADER_B={header_b} AGE=9h")
    finally:
        await conn.close()


async def audit_counts(conn, company_id: int):
    rows = await conn.fetch(
        """
        SELECT action_type, count(*) AS c
        FROM system_audit_logs
        WHERE company_id = $1
          AND action_type IN ('STALE_HANDSHAKE_WARNING', 'STALE_HANDSHAKE_CRITICAL')
        GROUP BY action_type
        """,
        company_id,
    )
    d = {r["action_type"]: r["c"] for r in rows}
    return (
        int(d.get("STALE_HANDSHAKE_WARNING", 0)),
        int(d.get("STALE_HANDSHAKE_CRITICAL", 0)),
    )


async def verify_rls(company_a: int, company_b: int):
    migration = await connect_migration()
    app = await connect_app()
    try:
        header_a = await migration.fetchval(
            "SELECT id FROM inventory_transfer_headers WHERE company_id=$1", company_a
        )
        header_b = await migration.fetchval(
            "SELECT id FROM inventory_transfer_headers WHERE company_id=$1", company_b
        )

        await app.execute("SELECT set_config('app.current_tenant', $1, false)", str(company_a))
        a_sees_b = await app.fetchval(
            "SELECT count(*) FROM inventory_transfer_headers WHERE id=$1", header_b
        )

        await app.execute("SELECT set_config('app.current_tenant', $1, false)", str(company_b))
        b_sees_a = await app.fetchval(
            "SELECT count(*) FROM inventory_transfer_headers WHERE id=$1", header_a
        )

        if a_sees_b != 0 or b_sees_a != 0:
            raise AssertionError(
                f"RLS FAILURE: A_sees_B={a_sees_b}, B_sees_A={b_sees_a}"
            )
        print("HANDSHAKE_E2E_RLS_CROSS_TENANT=OK")
    finally:
        await app.close()
        await migration.close()


async def verify_warning():
    conn = await connect_migration()
    try:
        a, b = await get_company_ids(conn)
        a_counts = await audit_counts(conn, a)
        b_counts = await audit_counts(conn, b)

        if a_counts != (1, 0):
            raise AssertionError(f"Company A expected warning=1 critical=0, got {a_counts}")
        if b_counts != (0, 1):
            raise AssertionError(f"Company B expected warning=0 critical=1, got {b_counts}")

        print("HANDSHAKE_E2E_WARNING_CRITICAL=OK")
    finally:
        await conn.close()

    await verify_rls(a, b)


async def escalate():
    conn = await connect_migration()
    try:
        a, _ = await get_company_ids(conn)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        await conn.execute(
            """
            UPDATE inventory_transfer_headers
            SET created_at=$1, updated_at=$1
            WHERE company_id=$2 AND reference_number='E2E-HS-A'
            """,
            now - timedelta(hours=9),
            a,
        )
        print("HANDSHAKE_E2E_ESCALATE_A_TO_9H=OK")
    finally:
        await conn.close()


async def verify_critical():
    conn = await connect_migration()
    try:
        a, b = await get_company_ids(conn)
        a_counts = await audit_counts(conn, a)
        b_counts = await audit_counts(conn, b)

        if a_counts != (1, 1):
            raise AssertionError(f"Company A expected warning=1 critical=1, got {a_counts}")
        if b_counts != (0, 1):
            raise AssertionError(f"Company B expected warning=0 critical=1, got {b_counts}")

        print("HANDSHAKE_E2E_ESCALATION=OK")
    finally:
        await conn.close()


async def verify_no_duplicates():
    conn = await connect_migration()
    try:
        a, b = await get_company_ids(conn)
        a_counts = await audit_counts(conn, a)
        b_counts = await audit_counts(conn, b)

        if a_counts != (1, 1) or b_counts != (0, 1):
            raise AssertionError(
                f"Duplicate audit detected: A={a_counts}, B={b_counts}"
            )
        print("HANDSHAKE_E2E_NO_DUPLICATE_ALERTS=OK")
        print("HANDSHAKE_STALE_MONITOR_POSTGRES_E2E=OK")
    finally:
        await conn.close()


async def cleanup():
    conn = await connect_migration()
    try:
        async with conn.transaction():
            await cleanup_conn(conn)
        print("HANDSHAKE_E2E_CLEANUP=OK")
    finally:
        await conn.close()


async def defer_company(company_id: int):
    from workers.app import app
    from workers.tasks.handshake import scan_company_stale_handshakes

    async with app.open_async():
        job = await scan_company_stale_handshakes.defer_async(
            company_id=int(company_id)
        )
    print(
        f"HANDSHAKE_E2E_DEFER_COMPANY=OK "
        f"company_id={int(company_id)} job_id={job}"
    )


async def defer_all():
    from workers.app import app
    from workers.tasks.handshake import scan_all_stale_handshakes

    async with app.open_async():
        job = await scan_all_stale_handshakes.defer_async()
    print(f"HANDSHAKE_E2E_DEFER_ALL=OK job_id={job}")


COMMANDS = {
    "setup": setup,
    "verify-warning": verify_warning,
    "escalate": escalate,
    "verify-critical": verify_critical,
    "verify-no-duplicates": verify_no_duplicates,
    "cleanup": cleanup,
    "defer-all": defer_all,
}


async def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "defer-company":
        if len(sys.argv) != 3:
            raise SystemExit(
                "Usage: python worker_handshake_e2e.py "
                "defer-company <company_id>"
            )
        await defer_company(int(sys.argv[2]))
        return

    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        print("Usage:")
        for command in COMMANDS:
            print(f"  python worker_handshake_e2e.py {command}")
        print("  python worker_handshake_e2e.py defer-company <company_id>")
        raise SystemExit(2)

    await COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()
        )

    asyncio.run(main())
