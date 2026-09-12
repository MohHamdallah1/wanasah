from __future__ import annotations

from pathlib import Path
import ast
import shutil
from datetime import datetime

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "wa_backend"
TASK_FILE = BACKEND / "workers" / "tasks" / "session_monitor.py"
SETTINGS_FILE = BACKEND / "workers" / "settings.py"
APP_FILE = BACKEND / "workers" / "app.py"
RELAY_FILE = BACKEND / "worker_event_relay.py"
DASHBOARD_FILE = ROOT / "dashboard" / "src" / "pages" / "DispatchBoard.tsx"

SESSION_TASK = '# SESSION_MONITOR_V1\nfrom __future__ import annotations\n\nfrom datetime import datetime, timedelta, timezone\n\nfrom sqlalchemy import select\n\nfrom database import AsyncSessionLocal\nfrom models import Company, Driver, SystemAuditLog, WorkSession\nfrom workers.app import MAINTENANCE_QUEUE, app\nfrom workers.events import emit_worker_event\nfrom workers.settings import load_session_monitor_settings\nfrom workers.tenant import tenant_session\n\nWARNING_AUDIT = "STALE_SESSION_WARNING"\nCRITICAL_AUDIT = "STALE_SESSION_CRITICAL"\n\n\ndef _utc_now() -> datetime:\n    return datetime.now(timezone.utc).replace(tzinfo=None)\n\n\n@app.task(\n    name="wanasah.scan_all_stale_sessions",\n    queue=MAINTENANCE_QUEUE,\n    queueing_lock="stale-session-global-scan",\n    lock="stale-session-global-scan",\n)\nasync def scan_all_stale_sessions() -> dict[str, int]:\n    async with AsyncSessionLocal() as db:\n        company_ids = list(\n            (\n                await db.execute(\n                    select(Company.id).order_by(Company.id.asc())\n                )\n            ).scalars().all()\n        )\n        if db.in_transaction():\n            await db.rollback()\n\n    deferred = 0\n    for company_id in company_ids:\n        await scan_company_stale_sessions.configure(\n            lock=f"stale-session-company:{int(company_id)}",\n        ).defer_async(company_id=int(company_id))\n        deferred += 1\n\n    return {\n        "companies_seen": len(company_ids),\n        "company_jobs_deferred": deferred,\n    }\n\n\n@app.task(\n    name="wanasah.scan_company_stale_sessions",\n    queue=MAINTENANCE_QUEUE,\n)\nasync def scan_company_stale_sessions(\n    company_id: int,\n) -> dict[str, int]:\n    now = _utc_now()\n\n    async with tenant_session(company_id) as db:\n        settings = await load_session_monitor_settings(\n            db,\n            company_id=int(company_id),\n        )\n        warning_cutoff = now - timedelta(\n            hours=settings.warning_hours\n        )\n\n        sessions = (\n            await db.execute(\n                select(WorkSession)\n                .filter(\n                    WorkSession.company_id == int(company_id),\n                    WorkSession.end_time.is_(None),\n                    WorkSession.start_time <= warning_cutoff,\n                )\n                .order_by(\n                    WorkSession.start_time.asc(),\n                    WorkSession.id.asc(),\n                )\n                .limit(1000)\n            )\n        ).scalars().all()\n\n        if not sessions:\n            await db.rollback()\n            return {\n                "company_id": int(company_id),\n                "active_stale": 0,\n                "warnings_created": 0,\n                "critical_created": 0,\n            }\n\n        driver_ids = sorted(\n            {int(session.driver_id) for session in sessions}\n        )\n        driver_rows = (\n            await db.execute(\n                select(Driver.id, Driver.full_name).filter(\n                    Driver.company_id == int(company_id),\n                    Driver.id.in_(driver_ids),\n                )\n            )\n        ).all()\n        driver_map = {\n            int(driver_id): str(full_name)\n            for driver_id, full_name in driver_rows\n        }\n\n        target_ids = [\n            f"WorkSession_{int(session.id)}"\n            for session in sessions\n        ]\n        prior_rows = (\n            await db.execute(\n                select(\n                    SystemAuditLog.target_id,\n                    SystemAuditLog.action_type,\n                ).filter(\n                    SystemAuditLog.company_id == int(company_id),\n                    SystemAuditLog.target_id.in_(target_ids),\n                    SystemAuditLog.action_type.in_(\n                        [WARNING_AUDIT, CRITICAL_AUDIT]\n                    ),\n                )\n            )\n        ).all()\n        prior = {\n            (str(target_id), str(action_type))\n            for target_id, action_type in prior_rows\n        }\n\n        warnings_created = 0\n        critical_created = 0\n\n        for session in sessions:\n            if session.start_time is None:\n                continue\n\n            age_hours = max(\n                0.0,\n                (now - session.start_time).total_seconds() / 3600.0,\n            )\n            target_id = f"WorkSession_{int(session.id)}"\n            driver_name = driver_map.get(\n                int(session.driver_id),\n                "مندوب غير معروف",\n            )\n\n            if age_hours >= settings.critical_hours:\n                action_type = CRITICAL_AUDIT\n                event = "STALE_SESSION_CRITICAL"\n                if (target_id, action_type) in prior:\n                    continue\n                message = (\n                    f"🚨 جلسة {driver_name} ما زالت مفتوحة لأكثر من "\n                    f"{settings.critical_hours} ساعة."\n                )\n                critical_created += 1\n            else:\n                action_type = WARNING_AUDIT\n                event = "STALE_SESSION_WARNING"\n                if (target_id, action_type) in prior:\n                    continue\n                message = (\n                    f"⚠️ جلسة {driver_name} ما زالت مفتوحة لأكثر من "\n                    f"{settings.warning_hours} ساعة."\n                )\n                warnings_created += 1\n\n            db.add(\n                SystemAuditLog(\n                    company_id=int(company_id),\n                    admin_id=None,\n                    target_id=target_id,\n                    action_type=action_type,\n                    old_value="end_time=NULL",\n                    new_value=(\n                        f"age_hours={age_hours:.2f}|"\n                        f"warning={settings.warning_hours}|"\n                        f"critical={settings.critical_hours}|"\n                        "action=NOTIFY_ONLY"\n                    ),\n                )\n            )\n\n            await emit_worker_event(\n                db,\n                company_id=int(company_id),\n                event=event,\n                message=message,\n                data={\n                    "work_session_id": int(session.id),\n                    "driver_id": int(session.driver_id),\n                    "age_hours": round(age_hours, 2),\n                },\n            )\n\n            prior.add((target_id, action_type))\n\n        await db.commit()\n\n        return {\n            "company_id": int(company_id),\n            "active_stale": len(sessions),\n            "warnings_created": warnings_created,\n            "critical_created": critical_created,\n        }\n'
SETTINGS_BLOCK = '\n\n# SESSION_MONITOR_V1\nSESSION_WARNING_KEY = "session_warning_hours"\nSESSION_CRITICAL_KEY = "session_critical_hours"\n\nDEFAULT_SESSION_WARNING_HOURS = 12\nDEFAULT_SESSION_CRITICAL_HOURS = 16\n\n\n@dataclass(frozen=True)\nclass SessionMonitorSettings:\n    warning_hours: int\n    critical_hours: int\n\n\nasync def load_session_monitor_settings(\n    db: AsyncSession,\n    *,\n    company_id: int,\n) -> SessionMonitorSettings:\n    rows = (\n        await db.execute(\n            select(\n                SystemSetting.setting_key,\n                SystemSetting.setting_value,\n            ).filter(\n                SystemSetting.company_id == company_id,\n                SystemSetting.setting_key.in_(\n                    [SESSION_WARNING_KEY, SESSION_CRITICAL_KEY]\n                ),\n            )\n        )\n    ).all()\n    values = {str(key): str(value) for key, value in rows}\n\n    warning = _parse_positive_int(\n        values.get(SESSION_WARNING_KEY),\n        key=SESSION_WARNING_KEY,\n        default=DEFAULT_SESSION_WARNING_HOURS,\n    )\n    critical = _parse_positive_int(\n        values.get(SESSION_CRITICAL_KEY),\n        key=SESSION_CRITICAL_KEY,\n        default=DEFAULT_SESSION_CRITICAL_HOURS,\n    )\n\n    if warning >= critical:\n        raise ValueError(\n            "Session monitor settings must satisfy: warning < critical."\n        )\n\n    return SessionMonitorSettings(\n        warning_hours=warning,\n        critical_hours=critical,\n    )\n'


def fail(message: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {message}")


def backup(path: Path) -> None:
    backup_dir = BACKEND / ".patch_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"{path.name}.before_session_monitor_{stamp}.bak"
    shutil.copy2(path, dest)
    print(f"BACKUP={dest.relative_to(ROOT)}")


def append_once(path: Path, marker: str, block: str) -> None:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        print(f"ALREADY_PATCHED={path.relative_to(ROOT)}")
        return
    backup(path)
    path.write_text(text.rstrip() + "\n" + block, encoding="utf-8")
    print(f"PATCHED={path.relative_to(ROOT)}")


def replace_once(path: Path, old: str, new: str, marker: str) -> None:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        print(f"ALREADY_PATCHED={path.relative_to(ROOT)}")
        return
    count = text.count(old)
    if count != 1:
        fail(
            f"Expected one anchor in {path.relative_to(ROOT)}, found {count}."
        )
    backup(path)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"PATCHED={path.relative_to(ROOT)}")


def main() -> None:
    required = [
        SETTINGS_FILE,
        APP_FILE,
        RELAY_FILE,
        DASHBOARD_FILE,
    ]
    for path in required:
        if not path.exists():
            fail(f"Missing required file: {path.relative_to(ROOT)}")

    if TASK_FILE.exists():
        current = TASK_FILE.read_text(encoding="utf-8")
        if current != SESSION_TASK:
            fail("session_monitor.py already exists with different content.")
        print("UNCHANGED=wa_backend/workers/tasks/session_monitor.py")
    else:
        TASK_FILE.write_text(SESSION_TASK, encoding="utf-8")
        print("CREATED=wa_backend/workers/tasks/session_monitor.py")

    append_once(
        SETTINGS_FILE,
        "# SESSION_MONITOR_V1",
        SETTINGS_BLOCK,
    )

    replace_once(
        APP_FILE,
        '        "workers.tasks.handshake",\n',
        '        "workers.tasks.handshake",\n'
        '        "workers.tasks.session_monitor",\n',
        '"workers.tasks.session_monitor"',
    )

    replace_once(
        RELAY_FILE,
        '        "STALE_HANDSHAKE_CRITICAL",\n',
        '        "STALE_HANDSHAKE_CRITICAL",\n'
        '        "STALE_SESSION_WARNING",\n'
        '        "STALE_SESSION_CRITICAL",\n',
        '"STALE_SESSION_WARNING"',
    )

    dashboard_old = """            if (data.event === "STALE_HANDSHAKE_WARNING" && data.message) {
              toast.warning(data.message);
            } else if (data.event === "STALE_HANDSHAKE_CRITICAL" && data.message) {
              toast.error(data.message);
            }
"""
    dashboard_new = """            if (data.event === "STALE_HANDSHAKE_WARNING" && data.message) {
              toast.warning(data.message);
            } else if (data.event === "STALE_HANDSHAKE_CRITICAL" && data.message) {
              toast.error(data.message);
            } else if (data.event === "STALE_SESSION_WARNING" && data.message) {
              toast.warning(data.message);
            } else if (data.event === "STALE_SESSION_CRITICAL" && data.message) {
              toast.error(data.message);
            }
"""
    replace_once(
        DASHBOARD_FILE,
        dashboard_old,
        dashboard_new,
        'data.event === "STALE_SESSION_WARNING"',
    )

    for path in [
        TASK_FILE,
        SETTINGS_FILE,
        APP_FILE,
        RELAY_FILE,
    ]:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    task_text = TASK_FILE.read_text(encoding="utf-8")
    checks = {
        "TENANT_SESSION": "async with tenant_session(company_id)" in task_text,
        "TENANT_FILTER": "WorkSession.company_id == int(company_id)" in task_text,
        "NO_SESSION_CLOSE": ".end_time =" not in task_text,
        "NO_INVENTORY_MUTATION": "InventoryBalance" not in task_text and "InventoryMovement" not in task_text,
        "DURABLE_AUDIT": "SystemAuditLog(" in task_text,
        "APP_IMPORT": '"workers.tasks.session_monitor"' in APP_FILE.read_text(encoding="utf-8"),
        "RELAY_EVENTS": '"STALE_SESSION_CRITICAL"' in RELAY_FILE.read_text(encoding="utf-8"),
    }
    failed = [k for k, v in checks.items() if not v]
    if failed:
        fail(f"Static verification failed: {failed}")

    print("SESSION_MONITOR_STATIC_VERIFY=OK")
    print("TENANT_ISOLATION_STATIC_VERIFY=OK")
    print("NO_SESSION_MUTATION=OK")
    print("NO_INVENTORY_MUTATION=OK")
    print("SESSION_MONITOR_PATCH_V1=OK")


if __name__ == "__main__":
    main()
