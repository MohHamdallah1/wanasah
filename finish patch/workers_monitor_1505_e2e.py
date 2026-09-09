from __future__ import annotations

import asyncio
import os
import re
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

COMPANY_CODE = "WKR-MONITOR-1505-E2E"
TOTAL = 1505
PRESEEDED = 1000
EXPECTED_NEW = TOTAL - PRESEEDED
EXPECTED_BATCH_CALLS = 3

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


async def _set_audit_trigger(conn, enabled: bool) -> None:
    exists = await conn.fetchval(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_trigger
            WHERE tgrelid = 'public.system_audit_logs'::regclass
              AND tgname = $1
              AND NOT tgisinternal
        )
        """,
        AUDIT_TRIGGER,
    )
    if not exists:
        raise AssertionError("AUDIT_APPEND_ONLY_TRIGGER_MISSING")

    action = "ENABLE" if enabled else "DISABLE"
    await conn.execute(
        f"ALTER TABLE public.system_audit_logs "
        f"{action} TRIGGER {AUDIT_TRIGGER}"
    )


async def cleanup(conn) -> None:
    company_id = await conn.fetchval(
        "SELECT id FROM companies WHERE company_code=$1",
        COMPANY_CODE,
    )
    if company_id is None:
        return

    cid = int(company_id)

    await _set_audit_trigger(conn, False)
    try:
        await conn.execute(
            "DELETE FROM system_audit_logs WHERE company_id=$1",
            cid,
        )
    finally:
        await _set_audit_trigger(conn, True)

    await conn.execute(
        "DELETE FROM inventory_transfer_lines WHERE company_id=$1",
        cid,
    )
    await conn.execute(
        "DELETE FROM inventory_transfer_headers WHERE company_id=$1",
        cid,
    )
    await conn.execute(
        "DELETE FROM work_sessions WHERE company_id=$1",
        cid,
    )
    await conn.execute(
        "DELETE FROM system_settings WHERE company_id=$1",
        cid,
    )
    await conn.execute(
        "DELETE FROM inventory_locations WHERE company_id=$1",
        cid,
    )
    await conn.execute(
        "DELETE FROM drivers WHERE company_id=$1",
        cid,
    )
    await conn.execute(
        "DELETE FROM companies WHERE id=$1",
        cid,
    )


async def setup_fixture() -> dict:
    conn = await migration_conn()
    try:
        async with conn.transaction():
            await cleanup(conn)
            now = datetime.now(timezone.utc).replace(tzinfo=None)

            company_id = int(
                await conn.fetchval(
                    """
                    INSERT INTO companies
                        (name, company_code, is_active, subscription_status,
                         currency_code, timezone, created_at)
                    VALUES
                        ('Monitor 1505 E2E', $1, TRUE, 'active',
                         'JOD', 'Asia/Amman', $2)
                    RETURNING id
                    """,
                    COMPANY_CODE,
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
                    VALUES
                        ($1, 'monitor_1505_admin', 'x', 'Monitor E2E Admin',
                         TRUE, TRUE, FALSE, 0, $2)
                    RETURNING id
                    """,
                    company_id,
                    now,
                )
            )

            driver_rows = await conn.fetch(
                """
                INSERT INTO drivers
                    (company_id, username, password_hash, full_name,
                     is_active, is_admin, can_allow_debt,
                     max_debt_limit, created_at)
                SELECT
                    $1,
                    'monitor_1505_driver_' || g::text,
                    'x',
                    'Monitor E2E Driver ' || g::text,
                    TRUE,
                    FALSE,
                    FALSE,
                    0,
                    $2
                FROM generate_series(1, $3) AS g
                RETURNING id
                """,
                company_id,
                now,
                TOTAL,
            )
            driver_ids = sorted(int(row["id"]) for row in driver_rows)
            if len(driver_ids) != TOTAL:
                raise AssertionError(
                    f"DRIVER_FIXTURE_COUNT_FAILED: {len(driver_ids)}"
                )

            session_start = now - timedelta(hours=13)
            session_rows = await conn.fetch(
                """
                INSERT INTO work_sessions
                    (company_id, driver_id, start_time, session_date,
                     is_authorized_to_sell, is_settled)
                SELECT
                    $1,
                    t.driver_id,
                    $2,
                    $3,
                    FALSE,
                    FALSE
                FROM unnest($4::int[]) AS t(driver_id)
                RETURNING id, driver_id
                """,
                company_id,
                session_start,
                session_start.date(),
                driver_ids,
            )
            session_by_driver = {
                int(row["driver_id"]): int(row["id"])
                for row in session_rows
            }
            session_ids = sorted(session_by_driver.values())
            if len(session_ids) != TOTAL:
                raise AssertionError(
                    f"SESSION_FIXTURE_COUNT_FAILED: {len(session_ids)}"
                )

            source_location_id = int(
                await conn.fetchval(
                    """
                    INSERT INTO inventory_locations
                        (company_id, name, code, location_type,
                         is_active, created_at, updated_at)
                    VALUES
                        ($1, 'Monitor Source', 'MON1505-SRC',
                         'WAREHOUSE', TRUE, $2, $2)
                    RETURNING id
                    """,
                    company_id,
                    now,
                )
            )
            destination_location_id = int(
                await conn.fetchval(
                    """
                    INSERT INTO inventory_locations
                        (company_id, name, code, location_type,
                         is_active, created_at, updated_at)
                    VALUES
                        ($1, 'Monitor Destination', 'MON1505-DST',
                         'WAREHOUSE', TRUE, $2, $2)
                    RETURNING id
                    """,
                    company_id,
                    now,
                )
            )

            ordered_session_ids = [
                session_by_driver[driver_id]
                for driver_id in driver_ids
            ]
            handshake_created = now - timedelta(hours=5)
            header_rows = await conn.fetch(
                """
                INSERT INTO inventory_transfer_headers
                    (company_id, reference_number,
                     source_location_id, destination_location_id,
                     workflow_type, status, work_session_id,
                     expected_receiver_id, dispatched_by,
                     created_at, updated_at)
                SELECT
                    $1,
                    'MON1505-HS-' || t.ord::text,
                    $2,
                    $3,
                    'HANDSHAKE',
                    'PENDING',
                    t.session_id,
                    t.driver_id,
                    $4,
                    $5,
                    $5
                FROM unnest(
                    $6::int[],
                    $7::int[]
                ) WITH ORDINALITY
                    AS t(session_id, driver_id, ord)
                RETURNING id
                """,
                company_id,
                source_location_id,
                destination_location_id,
                admin_id,
                handshake_created,
                ordered_session_ids,
                driver_ids,
            )
            header_ids = sorted(int(row["id"]) for row in header_rows)
            if len(header_ids) != TOTAL:
                raise AssertionError(
                    f"HANDSHAKE_FIXTURE_COUNT_FAILED: {len(header_ids)}"
                )

            # Intentionally invalid partial overrides. Loader must fail safe.
            await conn.executemany(
                """
                INSERT INTO system_settings
                    (company_id, setting_key, setting_value, description)
                VALUES ($1, $2, $3, 'Monitor E2E invalid partial override')
                """,
                [
                    (company_id, "handshake_auto_cancel_hours", "6"),
                    (company_id, "session_critical_hours", "10"),
                    (company_id, "integrity_alert_repeat_hours", "not-an-int"),
                ],
            )

        return {
            "company_id": company_id,
            "admin_id": admin_id,
            "driver_ids": driver_ids,
            "session_ids": session_ids,
            "header_ids": header_ids,
        }
    finally:
        await conn.close()


async def verify_settings_fallback(company_id: int) -> None:
    from workers.settings import (
        load_handshake_monitor_settings,
        load_integrity_monitor_settings,
        load_session_monitor_settings,
    )
    from workers.tenant import tenant_session

    async with tenant_session(company_id) as db:
        handshake = await load_handshake_monitor_settings(
            db,
            company_id=company_id,
        )
        session = await load_session_monitor_settings(
            db,
            company_id=company_id,
        )
        integrity = await load_integrity_monitor_settings(
            db,
            company_id=company_id,
        )
        await db.rollback()

    if (
        handshake.warning_hours,
        handshake.critical_hours,
        handshake.auto_cancel_hours,
        handshake.timeout_action,
    ) != (4, 8, 12, "NOTIFY_ONLY"):
        raise AssertionError(
            f"HANDSHAKE_FALLBACK_FAILED: {handshake}"
        )

    if (
        session.warning_hours,
        session.critical_hours,
    ) != (12, 16):
        raise AssertionError(
            f"SESSION_FALLBACK_FAILED: {session}"
        )

    if integrity.repeat_hours != 24:
        raise AssertionError(
            f"INTEGRITY_FALLBACK_FAILED: {integrity}"
        )

    conn = await migration_conn()
    try:
        await conn.execute(
            "DELETE FROM system_settings WHERE company_id=$1",
            company_id,
        )
    finally:
        await conn.close()

    print("E2E_PARTIAL_SETTINGS_FULL_FALLBACK=OK")
    print("E2E_INTEGRITY_SETTINGS_FAILSAFE=OK")


async def seed_prior_alerts(info: dict) -> None:
    conn = await migration_conn()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        await conn.executemany(
            """
            INSERT INTO system_audit_logs
                (company_id, admin_id, target_id, action_type,
                 old_value, new_value, timestamp)
            VALUES ($1, NULL, $2, $3, NULL, 'preseeded', $4)
            """,
            [
                (
                    info["company_id"],
                    f"WorkSession_{session_id}",
                    "STALE_SESSION_WARNING",
                    now,
                )
                for session_id in info["session_ids"][:PRESEEDED]
            ],
        )
        await conn.executemany(
            """
            INSERT INTO system_audit_logs
                (company_id, admin_id, target_id, action_type,
                 old_value, new_value, timestamp)
            VALUES ($1, NULL, $2, $3, NULL, 'preseeded', $4)
            """,
            [
                (
                    info["company_id"],
                    f"Transfer_{header_id}",
                    "STALE_HANDSHAKE_WARNING",
                    now,
                )
                for header_id in info["header_ids"][:PRESEEDED]
            ],
        )
    finally:
        await conn.close()

    print(
        "E2E_PRESEEDED_OLDEST_ALERTS=OK "
        f"session={PRESEEDED} handshake={PRESEEDED}"
    )


async def count_audits(company_id: int, action_type: str) -> int:
    conn = await migration_conn()
    try:
        return int(
            await conn.fetchval(
                """
                SELECT count(*)
                FROM system_audit_logs
                WHERE company_id=$1 AND action_type=$2
                """,
                company_id,
                action_type,
            )
        )
    finally:
        await conn.close()


async def run_task_with_notify_counter(task, *, company_id: int):
    from sqlalchemy import event
    from database import engine

    counter = {"count": 0}

    def before_cursor_execute(
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        if "pg_notify" in statement.lower():
            counter["count"] += 1

    event.listen(
        engine.sync_engine,
        "before_cursor_execute",
        before_cursor_execute,
    )
    try:
        result = await task(company_id=company_id)
    finally:
        event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            before_cursor_execute,
        )

    return result, counter["count"]


async def verify_session_starvation(info: dict) -> None:
    from workers.tasks.session_monitor import scan_company_stale_sessions

    result, notify_calls = await run_task_with_notify_counter(
        scan_company_stale_sessions,
        company_id=info["company_id"],
    )

    if result["warnings_created"] != EXPECTED_NEW:
        raise AssertionError(
            "SESSION_STARVATION_NOT_FIXED: "
            f"expected={EXPECTED_NEW} result={result}"
        )
    if result["critical_created"] != 0:
        raise AssertionError(
            f"SESSION_UNEXPECTED_CRITICAL: {result}"
        )
    if notify_calls != EXPECTED_BATCH_CALLS:
        raise AssertionError(
            "SESSION_BATCH_NOTIFY_FAILED: "
            f"expected_calls={EXPECTED_BATCH_CALLS} got={notify_calls}"
        )

    total = await count_audits(
        info["company_id"],
        "STALE_SESSION_WARNING",
    )
    if total != TOTAL:
        raise AssertionError(
            f"SESSION_AUDIT_COVERAGE_FAILED: expected={TOTAL} got={total}"
        )

    second, second_notify = await run_task_with_notify_counter(
        scan_company_stale_sessions,
        company_id=info["company_id"],
    )
    if (
        second["warnings_created"] != 0
        or second["critical_created"] != 0
        or second_notify != 0
    ):
        raise AssertionError(
            f"SESSION_SECOND_PASS_NOT_EMPTY: {second} notify={second_notify}"
        )

    print(
        "E2E_SESSION_1505_STARVATION=OK "
        f"preseeded={PRESEEDED} discovered={EXPECTED_NEW}"
    )
    print(
        "E2E_SESSION_BATCH_NOTIFY=OK "
        f"events={EXPECTED_NEW} db_calls={notify_calls}"
    )


async def verify_handshake_starvation(info: dict) -> None:
    from workers.tasks.handshake import scan_company_stale_handshakes

    result, notify_calls = await run_task_with_notify_counter(
        scan_company_stale_handshakes,
        company_id=info["company_id"],
    )

    if result["warnings_created"] != EXPECTED_NEW:
        raise AssertionError(
            "HANDSHAKE_STARVATION_NOT_FIXED: "
            f"expected={EXPECTED_NEW} result={result}"
        )
    if result["critical_created"] != 0:
        raise AssertionError(
            f"HANDSHAKE_UNEXPECTED_CRITICAL: {result}"
        )
    if notify_calls != EXPECTED_BATCH_CALLS:
        raise AssertionError(
            "HANDSHAKE_BATCH_NOTIFY_FAILED: "
            f"expected_calls={EXPECTED_BATCH_CALLS} got={notify_calls}"
        )

    total = await count_audits(
        info["company_id"],
        "STALE_HANDSHAKE_WARNING",
    )
    if total != TOTAL:
        raise AssertionError(
            f"HANDSHAKE_AUDIT_COVERAGE_FAILED: expected={TOTAL} got={total}"
        )

    second, second_notify = await run_task_with_notify_counter(
        scan_company_stale_handshakes,
        company_id=info["company_id"],
    )
    if (
        second["warnings_created"] != 0
        or second["critical_created"] != 0
        or second_notify != 0
    ):
        raise AssertionError(
            f"HANDSHAKE_SECOND_PASS_NOT_EMPTY: "
            f"{second} notify={second_notify}"
        )

    print(
        "E2E_HANDSHAKE_1505_STARVATION=OK "
        f"preseeded={PRESEEDED} discovered={EXPECTED_NEW}"
    )
    print(
        "E2E_HANDSHAKE_BATCH_NOTIFY=OK "
        f"events={EXPECTED_NEW} db_calls={notify_calls}"
    )


def verify_static() -> None:
    settings = (BACKEND / "workers" / "settings.py").read_text(
        encoding="utf-8"
    )
    events = (BACKEND / "workers" / "events.py").read_text(
        encoding="utf-8"
    )
    handshake = (
        BACKEND / "workers" / "tasks" / "handshake.py"
    ).read_text(encoding="utf-8")
    session = (
        BACKEND / "workers" / "tasks" / "session_monitor.py"
    ).read_text(encoding="utf-8")

    checks = {
        "settings_fallback": (
            "_default_handshake_settings" in settings
            and "_default_session_settings" in settings
        ),
        "batch_size": "_EVENT_BATCH_SIZE = 200" in events,
        "batch_sql": "jsonb_array_elements_text" in events,
        "handshake_filter": (
            "warning_audit_exists" in handshake
            and "critical_audit_exists" in handshake
        ),
        "session_filter": (
            "warning_audit_exists" in session
            and "critical_audit_exists" in session
        ),
        "handshake_no_n1": "await emit_worker_event(" not in handshake,
        "session_no_n1": "await emit_worker_event(" not in session,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise AssertionError(
            f"E2E_STATIC_PRECHECK_FAILED: {failed}"
        )

    print("E2E_MONITOR_V3_STATIC=OK")


async def run() -> None:
    verify_static()

    conn = await migration_conn()
    try:
        async with conn.transaction():
            await cleanup(conn)
    finally:
        await conn.close()

    try:
        info = await setup_fixture()
        print(
            "E2E_1505_FIXTURE=OK "
            f"company={info['company_id']} "
            f"sessions={len(info['session_ids'])} "
            f"handshakes={len(info['header_ids'])}"
        )

        await verify_settings_fallback(info["company_id"])
        await seed_prior_alerts(info)
        await verify_session_starvation(info)
        await verify_handshake_starvation(info)

        print("WORKERS_MONITOR_1505_POSTGRES_E2E=PASS")
    finally:
        conn = await migration_conn()
        try:
            async with conn.transaction():
                await cleanup(conn)
            print("E2E_1505_CLEANUP=OK")
        finally:
            await conn.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()
        )
    asyncio.run(run())
