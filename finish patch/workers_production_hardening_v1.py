
from __future__ import annotations

from pathlib import Path
import ast
import shutil

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "wa_backend"

GITIGNORE = ROOT / ".gitignore"
MAIN = BACKEND / "main.py"
TENANT = BACKEND / "workers" / "tenant.py"
WS_MANAGER = BACKEND / "ws_manager.py"
OLD_RELAY = BACKEND / "worker_event_relay.py"
REALTIME_DIR = BACKEND / "realtime"
NEW_RELAY = REALTIME_DIR / "worker_event_relay.py"


def fail(msg: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {msg}")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"ALREADY_PATCHED={path.relative_to(ROOT)}:{label}")
        return
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected 1 match in {path.relative_to(ROOT)}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"PATCHED={path.relative_to(ROOT)}:{label}")


def cleanup_patch_backups() -> None:
    removed = 0
    for path in [ROOT / ".patch_backups", BACKEND / ".patch_backups"]:
        if path.exists():
            shutil.rmtree(path)
            removed += 1
            print(f"REMOVED={path.relative_to(ROOT)}")
    if removed == 0:
        print("PATCH_BACKUPS_ALREADY_ABSENT=OK")

    gi = GITIGNORE.read_text(encoding="utf-8")
    marker = "**/.patch_backups/"
    if marker not in gi:
        GITIGNORE.write_text(
            gi.rstrip()
            + "\n\n# Surgical patch backups are temporary only\n**/.patch_backups/\n",
            encoding="utf-8",
        )
        print("PATCHED=.gitignore:patch_backups")
    else:
        print("ALREADY_PATCHED=.gitignore:patch_backups")


def organize_relay() -> None:
    REALTIME_DIR.mkdir(parents=True, exist_ok=True)
    init_file = REALTIME_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text(
            "# Realtime infrastructure for API-process event delivery.\n",
            encoding="utf-8",
        )
        print("CREATED=wa_backend/realtime/__init__.py")

    if OLD_RELAY.exists() and not NEW_RELAY.exists():
        shutil.move(str(OLD_RELAY), str(NEW_RELAY))
        print(
            "MOVED=wa_backend/worker_event_relay.py"
            "->wa_backend/realtime/worker_event_relay.py"
        )
    elif OLD_RELAY.exists() and NEW_RELAY.exists():
        fail("Both old and new worker_event_relay.py exist; refusing ambiguous move.")
    elif NEW_RELAY.exists():
        print("RELAY_ALREADY_ORGANIZED=OK")
    else:
        fail("worker_event_relay.py not found.")

    replace_once(
        MAIN,
        "from worker_event_relay import worker_event_relay\n",
        "from realtime.worker_event_relay import worker_event_relay\n",
        "relay_import",
    )


def enable_rate_limiter() -> None:
    text = MAIN.read_text(encoding="utf-8")
    old = '''# +++ TEMPORARY (Stage 9 Testing): rate limiter disabled for isolation/load testing +++
#احذف السطر بس تخلص الاختبار
limiter.enabled = False
'''
    if old in text:
        MAIN.write_text(text.replace(old, "", 1), encoding="utf-8")
        print("PATCHED=wa_backend/main.py:rate_limiter_enabled")
    elif "limiter.enabled = False" in text:
        fail("Found limiter.enabled = False in an unexpected form.")
    else:
        print("RATE_LIMITER_ALREADY_ENABLED=OK")


def harden_tenant_session() -> None:
    helper_anchor = '''@asynccontextmanager
async def tenant_session(company_id: int):
'''
    helper = '''async def _clear_tenant_or_invalidate(db) -> None:
    # Defense in depth: clear tenant state before pool return.
    # If clearing fails, invalidate the physical connection.
    try:
        if db.in_transaction():
            await db.rollback()
        await db.execute(
            text("SELECT set_config('app.current_tenant', '', false)")
        )
        await db.commit()
    except BaseException:
        try:
            if db.in_transaction():
                await db.rollback()
        finally:
            await db.invalidate()
        raise


@asynccontextmanager
async def tenant_session(company_id: int):
'''
    text = TENANT.read_text(encoding="utf-8")
    if "async def _clear_tenant_or_invalidate" not in text:
        if text.count(helper_anchor) != 1:
            fail("tenant_session anchor not found exactly once.")
        text = text.replace(helper_anchor, helper, 1)
        TENANT.write_text(text, encoding="utf-8")
        print("PATCHED=wa_backend/workers/tenant.py:clear_helper")
    else:
        print("ALREADY_PATCHED=wa_backend/workers/tenant.py:clear_helper")

    old_finally = '''            finally:
                # A task that forgot to commit must never leak an open transaction.
                if db.in_transaction():
                    await db.rollback()
    finally:
        tenant_context.reset(token)
'''
    new_finally = '''            finally:
                # Never return a tenant-tainted physical connection to the pool.
                await _clear_tenant_or_invalidate(db)
    finally:
        tenant_context.reset(token)
'''
    replace_once(TENANT, old_finally, new_finally, "tenant_exit_cleanup")


def harden_relay() -> None:
    relay = NEW_RELAY.read_text(encoding="utf-8")

    const_old = '''WORKER_EVENT_CHANNEL = "wanasah_worker_events"
_ALLOWED_EVENTS = {
'''
    const_new = '''WORKER_EVENT_CHANNEL = "wanasah_worker_events"
LISTEN_CONNECT_TIMEOUT_SECONDS = 10.0
LISTEN_COMMAND_TIMEOUT_SECONDS = 10.0
LISTEN_HEARTBEAT_SECONDS = 15.0
LISTEN_HEARTBEAT_TIMEOUT_SECONDS = 5.0
BROADCAST_TIMEOUT_SECONDS = 4.0

_ALLOWED_EVENTS = {
'''
    if "LISTEN_HEARTBEAT_TIMEOUT_SECONDS" not in relay:
        if relay.count(const_old) != 1:
            fail("Relay constants anchor not found exactly once.")
        relay = relay.replace(const_old, const_new, 1)

    connect_old = "                conn = await asyncpg.connect(dsn)\n"
    connect_new = '''                conn = await asyncpg.connect(
                    dsn,
                    timeout=LISTEN_CONNECT_TIMEOUT_SECONDS,
                    command_timeout=LISTEN_COMMAND_TIMEOUT_SECONDS,
                )
'''
    if connect_old in relay:
        relay = relay.replace(connect_old, connect_new, 1)

    timeout_old = '''                    except asyncio.TimeoutError:
                        continue
                    await self._dispatch_payload(payload)
'''
    timeout_new = '''                    except asyncio.TimeoutError:
                        try:
                            await asyncio.wait_for(
                                conn.execute("SELECT 1"),
                                timeout=LISTEN_HEARTBEAT_TIMEOUT_SECONDS,
                            )
                        except Exception as exc:
                            raise ConnectionError(
                                "Worker event relay heartbeat failed."
                            ) from exc
                        continue
                    await self._dispatch_payload(payload)
'''
    if "Worker event relay heartbeat failed." not in relay:
        if relay.count(timeout_old) != 1:
            fail("Relay heartbeat anchor not found exactly once.")
        relay = relay.replace(timeout_old, timeout_new, 1)

    broadcast_old = (
        "        await dispatch_manager.broadcast(outbound, company_id=company_id)\n"
    )
    broadcast_new = '''        try:
            await asyncio.wait_for(
                dispatch_manager.broadcast(outbound, company_id=company_id),
                timeout=BROADCAST_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Worker event relay broadcast timed out for company %s; "
                "durable audit remains authoritative.",
                company_id,
            )
'''
    if "broadcast timed out for company" not in relay:
        if relay.count(broadcast_old) != 1:
            fail("Relay broadcast anchor not found exactly once.")
        relay = relay.replace(broadcast_old, broadcast_new, 1)

    NEW_RELAY.write_text(relay, encoding="utf-8")
    print(
        "PATCHED=wa_backend/realtime/worker_event_relay.py:"
        "heartbeat_and_timeout"
    )


def harden_websocket_sends() -> None:
    text = WS_MANAGER.read_text(encoding="utf-8")
    if "WS_SEND_TIMEOUT_SECONDS" not in text:
        anchor = "MAX_WS_CONNECTIONS = 50\n"
        replacement = "MAX_WS_CONNECTIONS = 50\nWS_SEND_TIMEOUT_SECONDS = 3.0\n"
        if text.count(anchor) != 1:
            fail("WS constants anchor not found exactly once.")
        text = text.replace(anchor, replacement, 1)

    old = '''        results = await asyncio.gather(
            *[connection.send_json(message) for connection in connections],
            return_exceptions=True
        )
'''
    new = '''        results = await asyncio.gather(
            *[
                asyncio.wait_for(
                    connection.send_json(message),
                    timeout=WS_SEND_TIMEOUT_SECONDS,
                )
                for connection in connections
            ],
            return_exceptions=True,
        )
'''
    if "timeout=WS_SEND_TIMEOUT_SECONDS" not in text:
        if text.count(old) != 1:
            fail("WS broadcast gather anchor not found exactly once.")
        text = text.replace(old, new, 1)

    WS_MANAGER.write_text(text, encoding="utf-8")
    print("PATCHED=wa_backend/ws_manager.py:bounded_send_timeout")


def verify() -> None:
    for path in [MAIN, TENANT, WS_MANAGER, NEW_RELAY]:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    checks = {
        "NO_ROOT_PATCH_BACKUPS": not (ROOT / ".patch_backups").exists(),
        "NO_BACKEND_PATCH_BACKUPS": not (BACKEND / ".patch_backups").exists(),
        "PATCH_BACKUPS_GITIGNORED": (
            "**/.patch_backups/" in GITIGNORE.read_text(encoding="utf-8")
        ),
        "RELAY_ORGANIZED": NEW_RELAY.exists() and not OLD_RELAY.exists(),
        "MAIN_IMPORT_RELAY": (
            "from realtime.worker_event_relay import worker_event_relay"
            in MAIN.read_text(encoding="utf-8")
        ),
        "RATE_LIMITER_ENABLED": (
            "limiter.enabled = False" not in MAIN.read_text(encoding="utf-8")
        ),
        "TENANT_CLEAR_ON_EXIT": (
            "_clear_tenant_or_invalidate"
            in TENANT.read_text(encoding="utf-8")
        ),
        "TENANT_INVALIDATE_FAIL_CLOSED": (
            "await db.invalidate()" in TENANT.read_text(encoding="utf-8")
        ),
        "RELAY_HEARTBEAT": (
            'conn.execute("SELECT 1")'
            in NEW_RELAY.read_text(encoding="utf-8")
        ),
        "RELAY_BROADCAST_TIMEOUT": (
            "BROADCAST_TIMEOUT_SECONDS"
            in NEW_RELAY.read_text(encoding="utf-8")
        ),
        "WS_SEND_TIMEOUT": (
            "WS_SEND_TIMEOUT_SECONDS"
            in WS_MANAGER.read_text(encoding="utf-8")
        ),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        fail(f"Static verification failed: {failed}")

    print("PATCH_BACKUPS_CLEANUP=OK")
    print("REALTIME_MODULE_ORGANIZATION=OK")
    print("RATE_LIMITER_PRODUCTION_GUARD=OK")
    print("TENANT_CONNECTION_CLEANUP_HARDENING=OK")
    print("RELAY_HEARTBEAT_HARDENING=OK")
    print("WEBSOCKET_SEND_TIMEOUT_HARDENING=OK")
    print("WORKERS_PRODUCTION_HARDENING_V1=OK")


def main() -> None:
    for path in [GITIGNORE, MAIN, TENANT, WS_MANAGER]:
        if not path.exists():
            fail(f"Missing required file: {path.relative_to(ROOT)}")

    cleanup_patch_backups()
    organize_relay()
    enable_rate_limiter()
    harden_tenant_session()
    harden_relay()
    harden_websocket_sends()
    verify()


if __name__ == "__main__":
    main()
