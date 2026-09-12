from __future__ import annotations

from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "wa_backend"

TASK_FILE = BACKEND / "workers" / "tasks" / "session_monitor.py"
SETTINGS_FILE = BACKEND / "workers" / "settings.py"
APP_FILE = BACKEND / "workers" / "app.py"
RELAY_FILE = BACKEND / "worker_event_relay.py"
DASHBOARD_FILE = ROOT / "dashboard" / "src" / "pages" / "DispatchBoard.tsx"


def fail(message: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {message}")


def patch_relay() -> None:
    text = RELAY_FILE.read_text(encoding="utf-8")

    needed = [
        '"STALE_SESSION_WARNING"',
        '"STALE_SESSION_CRITICAL"',
    ]
    if all(item in text for item in needed):
        print("ALREADY_PATCHED=wa_backend/worker_event_relay.py")
        return

    start = text.find("_ALLOWED_EVENTS = {")
    if start < 0:
        fail("_ALLOWED_EVENTS set not found in worker_event_relay.py")

    close = text.find("\n}", start)
    if close < 0:
        fail("_ALLOWED_EVENTS closing brace not found in worker_event_relay.py")

    block = text[start:close]
    insertion = ""
    if '"STALE_SESSION_WARNING"' not in block:
        insertion += '    "STALE_SESSION_WARNING",\n'
    if '"STALE_SESSION_CRITICAL"' not in block:
        insertion += '    "STALE_SESSION_CRITICAL",\n'

    text = text[:close] + "\n" + insertion.rstrip("\n") + text[close:]
    RELAY_FILE.write_text(text, encoding="utf-8")
    print("PATCHED=wa_backend/worker_event_relay.py")


def patch_dashboard() -> None:
    text = DASHBOARD_FILE.read_text(encoding="utf-8")

    if (
        'data.event === "STALE_SESSION_WARNING"' in text
        and 'data.event === "STALE_SESSION_CRITICAL"' in text
    ):
        print("ALREADY_PATCHED=dashboard/src/pages/DispatchBoard.tsx")
        return

    pattern = re.compile(
        r'(\} else if \(data\.event === "STALE_HANDSHAKE_CRITICAL" && data\.message\) \{\s*'
        r'toast\.error\(data\.message\);\s*)\}',
        re.MULTILINE,
    )

    match = pattern.search(text)
    if not match:
        fail("Handshake critical toast branch not found in DispatchBoard.tsx")

    replacement = (
        match.group(1)
        + '} else if (data.event === "STALE_SESSION_WARNING" && data.message) {\n'
          '              toast.warning(data.message);\n'
          '            } else if (data.event === "STALE_SESSION_CRITICAL" && data.message) {\n'
          '              toast.error(data.message);\n'
          '            }'
    )

    text = text[:match.start()] + replacement + text[match.end():]
    DASHBOARD_FILE.write_text(text, encoding="utf-8")
    print("PATCHED=dashboard/src/pages/DispatchBoard.tsx")


def verify() -> None:
    required = [
        TASK_FILE,
        SETTINGS_FILE,
        APP_FILE,
        RELAY_FILE,
        DASHBOARD_FILE,
    ]
    for path in required:
        if not path.exists():
            fail(f"Missing required file: {path.relative_to(ROOT)}")

    for path in [TASK_FILE, SETTINGS_FILE, APP_FILE, RELAY_FILE]:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    task = TASK_FILE.read_text(encoding="utf-8")
    settings = SETTINGS_FILE.read_text(encoding="utf-8")
    app = APP_FILE.read_text(encoding="utf-8")
    relay = RELAY_FILE.read_text(encoding="utf-8")
    dash = DASHBOARD_FILE.read_text(encoding="utf-8")

    checks = {
        "TASK_IMPORTED": '"workers.tasks.session_monitor"' in app,
        "SESSION_SETTINGS_PRESENT": "load_session_monitor_settings" in settings,
        "TENANT_SESSION_USED": "async with tenant_session(company_id)" in task,
        "TENANT_FILTER_PRESENT": "WorkSession.company_id == int(company_id)" in task,
        "NO_SESSION_CLOSE": ".end_time =" not in task,
        "NO_SETTLEMENT_MUTATION": ".is_settled =" not in task,
        "NO_INVENTORY_MUTATION": (
            "InventoryBalance" not in task
            and "InventoryMovement" not in task
        ),
        "RELAY_WARNING_ALLOWED": '"STALE_SESSION_WARNING"' in relay,
        "RELAY_CRITICAL_ALLOWED": '"STALE_SESSION_CRITICAL"' in relay,
        "DASH_WARNING_TOAST": 'data.event === "STALE_SESSION_WARNING"' in dash,
        "DASH_CRITICAL_TOAST": 'data.event === "STALE_SESSION_CRITICAL"' in dash,
    }

    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        fail(f"Verification failed: {failed}")

    print("SESSION_MONITOR_INTEGRATION_VERIFY=OK")
    print("NO_WORKFLOW_MUTATION=OK")
    print("TENANT_ISOLATION_STATIC_VERIFY=OK")
    print("SESSION_MONITOR_V1_READY_FOR_FREEZE=OK")


def main() -> None:
    for path in [TASK_FILE, SETTINGS_FILE, APP_FILE, RELAY_FILE, DASHBOARD_FILE]:
        if not path.exists():
            fail(f"Missing required file: {path.relative_to(ROOT)}")

    patch_relay()
    patch_dashboard()
    verify()


if __name__ == "__main__":
    main()
