from __future__ import annotations

import asyncio
import os
import sys
import time
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

A_CODE = "WKR-HARDEN-V1-A"
B_CODE = "WKR-HARDEN-V1-B"


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


async def cleanup(conn):
    rows = await conn.fetch(
        "SELECT id FROM companies WHERE company_code = ANY($1::text[])",
        [A_CODE, B_CODE],
    )
    ids = [int(r["id"]) for r in rows]
    if not ids:
        return
    await conn.execute(
        "DELETE FROM system_settings WHERE company_id = ANY($1::int[])",
        ids,
    )
    await conn.execute(
        "DELETE FROM companies WHERE id = ANY($1::int[])",
        ids,
    )


async def setup():
    conn = await migration_conn()
    try:
        async with conn.transaction():
            await cleanup(conn)
            now = datetime.now(timezone.utc).replace(tzinfo=None)

            async def create(code: str, label: str):
                cid = int(
                    await conn.fetchval(
                        """
                        INSERT INTO companies
                            (name, company_code, is_active, subscription_status,
                             currency_code, timezone, created_at)
                        VALUES ($1,$2,TRUE,'active','JOD','Asia/Amman',$3)
                        RETURNING id
                        """,
                        f"Hardening {label}",
                        code,
                        now,
                    )
                )
                await conn.execute(
                    """
                    INSERT INTO system_settings
                        (company_id, setting_key, setting_value, description)
                    VALUES ($1,'hardening_probe',$2,'hardening gate')
                    """,
                    cid,
                    label,
                )
                return cid

            a = await create(A_CODE, "A")
            b = await create(B_CODE, "B")
            return a, b
    finally:
        await conn.close()


async def verify_tenant_cleanup(a: int, b: int):
    from sqlalchemy import select, text
    from database import AsyncSessionLocal
    from models import SystemSetting
    from workers.tenant import tenant_session

    async with tenant_session(a) as db:
        value = (
            await db.execute(
                select(SystemSetting.setting_value).where(
                    SystemSetting.company_id == a,
                    SystemSetting.setting_key == "hardening_probe",
                )
            )
        ).scalar_one()
        if value != "A":
            raise AssertionError("TENANT_A_SELF_READ_FAILED")

    async with AsyncSessionLocal() as db:
        current = (
            await db.execute(
                text("SELECT current_setting('app.current_tenant', true)")
            )
        ).scalar_one()
        visible = (
            await db.execute(
                select(SystemSetting.id).where(
                    SystemSetting.company_id.in_([a, b])
                )
            )
        ).scalars().all()

    if current not in ("", None):
        raise AssertionError(
            f"TENANT_CONNECTION_CLEAR_FAILED: current={current!r}"
        )
    if visible:
        raise AssertionError(
            f"NO_TENANT_RLS_FAILED: visible={visible}"
        )

    print("TENANT_CONNECTION_CLEAR_RUNTIME=OK")


async def verify_ws_send_timeout():
    from ws_manager import ConnectionManager, WS_SEND_TIMEOUT_SECONDS

    class SlowSocket:
        async def send_json(self, message):
            await asyncio.sleep(WS_SEND_TIMEOUT_SECONDS + 5)

    mgr = ConnectionManager()
    sock = SlowSocket()
    mgr.active_connections[1] = [sock]

    started = time.monotonic()
    await mgr.broadcast({"event": "TEST"}, company_id=1)
    elapsed = time.monotonic() - started

    if elapsed > WS_SEND_TIMEOUT_SECONDS + 1.5:
        raise AssertionError(
            f"WS_SEND_TIMEOUT_FAILED: elapsed={elapsed:.2f}s"
        )
    if 1 in mgr.active_connections:
        raise AssertionError("WS_SLOW_CONNECTION_NOT_REMOVED")

    print("WEBSOCKET_SLOW_CLIENT_TIMEOUT_RUNTIME=OK")


def verify_static():
    main = (BACKEND / "main.py").read_text(encoding="utf-8")
    relay = (
        BACKEND / "realtime" / "worker_event_relay.py"
    ).read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    if "limiter.enabled = False" in main:
        raise AssertionError("RATE_LIMITER_STILL_DISABLED")
    if "from realtime.worker_event_relay import worker_event_relay" not in main:
        raise AssertionError("REALTIME_IMPORT_NOT_UPDATED")
    if 'conn.execute("SELECT 1")' not in relay:
        raise AssertionError("RELAY_HEARTBEAT_MISSING")
    if "BROADCAST_TIMEOUT_SECONDS" not in relay:
        raise AssertionError("RELAY_BROADCAST_TIMEOUT_MISSING")
    if (ROOT / ".patch_backups").exists():
        raise AssertionError("ROOT_PATCH_BACKUPS_STILL_EXIST")
    if (BACKEND / ".patch_backups").exists():
        raise AssertionError("BACKEND_PATCH_BACKUPS_STILL_EXIST")
    if "**/.patch_backups/" not in gitignore:
        raise AssertionError("PATCH_BACKUPS_NOT_GITIGNORED")

    print("WORKERS_HARDENING_V1_STATIC=OK")


async def run():
    verify_static()
    try:
        a, b = await setup()
        print(f"HARDENING_FIXTURE=OK A={a} B={b}")
        await verify_tenant_cleanup(a, b)
        await verify_ws_send_timeout()
        print("WORKERS_PRODUCTION_HARDENING_GATE_V1=PASS")
    finally:
        conn = await migration_conn()
        try:
            async with conn.transaction():
                await cleanup(conn)
            print("HARDENING_GATE_CLEANUP=OK")
        finally:
            await conn.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()
        )
    asyncio.run(run())
