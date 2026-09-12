from __future__ import annotations

from pathlib import Path
import ast
import re
import shutil
from datetime import datetime

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "wa_backend"
TASK_FILE = BACKEND / "workers" / "tasks" / "reports.py"
APP_FILE = BACKEND / "workers" / "app.py"
README_FILE = BACKEND / "workers" / "README.md"

TASK_CONTENT = '# HEAVY_REPORTS_FOUNDATION_V1\nfrom __future__ import annotations\n\nfrom datetime import datetime, timezone\n\nfrom sqlalchemy import func, select, text\n\nfrom models import (\n    InventoryMovement,\n    InventoryTransferHeader,\n    Visit,\n    WorkSession,\n)\nfrom workers.app import REPORTS_QUEUE, app\nfrom workers.tenant import tenant_session\n\n\ndef _utc_now_iso() -> str:\n    return datetime.now(timezone.utc).isoformat()\n\n\n@app.task(\n    name="wanasah.report_foundation_probe",\n    queue=REPORTS_QUEUE,\n)\nasync def report_foundation_probe(\n    company_id: int,\n) -> dict:\n    """\n    Infrastructure-only report probe.\n\n    Business data is strictly read-only. The PostgreSQL transaction itself is\n    switched to READ ONLY before report queries, so an accidental future write\n    in this task fails at the database layer.\n    """\n    company_id = int(company_id)\n    if company_id <= 0:\n        raise ValueError("company_id must be a positive integer.")\n\n    async with tenant_session(company_id) as db:\n        await db.execute(text("SET TRANSACTION READ ONLY"))\n\n        session_count = int(\n            (\n                await db.execute(\n                    select(func.count(WorkSession.id)).where(\n                        WorkSession.company_id == company_id\n                    )\n                )\n            ).scalar_one()\n            or 0\n        )\n        visit_count = int(\n            (\n                await db.execute(\n                    select(func.count(Visit.id)).where(\n                        Visit.company_id == company_id\n                    )\n                )\n            ).scalar_one()\n            or 0\n        )\n        transfer_count = int(\n            (\n                await db.execute(\n                    select(func.count(InventoryTransferHeader.id)).where(\n                        InventoryTransferHeader.company_id == company_id\n                    )\n                )\n            ).scalar_one()\n            or 0\n        )\n        movement_count = int(\n            (\n                await db.execute(\n                    select(func.count(InventoryMovement.id)).where(\n                        InventoryMovement.company_id == company_id\n                    )\n                )\n            ).scalar_one()\n            or 0\n        )\n\n        await db.rollback()\n\n        return {\n            "report": "FOUNDATION_PROBE",\n            "company_id": company_id,\n            "generated_at_utc": _utc_now_iso(),\n            "counts": {\n                "work_sessions": session_count,\n                "visits": visit_count,\n                "inventory_transfers": transfer_count,\n                "inventory_movements": movement_count,\n            },\n        }\n'
README_BLOCK = '\n\n## Heavy Reports Foundation (V1)\n\n### Queue isolation\n\n- `maintenance`: operational monitors and integrity scans.\n- `notifications`: notification work.\n- `reports`: heavy/read-only reporting only.\n- Every business/report job must carry an explicit `company_id`.\n- Report tasks must enter through `tenant_session(company_id)`.\n- Report business queries must remain read-only. V1 additionally uses PostgreSQL\n  `SET TRANSACTION READ ONLY` inside report transactions.\n\n### Official root commands\n\nRun these from the repository root.\n\nPowerShell environment for each new terminal:\n\n```powershell\n$env:PYTHONPATH = "$PWD\\wa_backend"\n```\n\nOperational worker:\n\n```powershell\npython -m procrastinate -v --app=workers.app.app worker -q maintenance,notifications -c 4\n```\n\nHeavy reports worker:\n\n```powershell\npython -m procrastinate -v --app=workers.app.app worker -q reports -c 1\n```\n\nHealth check:\n\n```powershell\npython -m procrastinate --app=workers.app.app healthchecks\n```\n\n`reports` starts at concurrency `1` deliberately so heavy reads cannot saturate\nPostgreSQL alongside operational jobs. Increase it only after measured production\nload proves the database has headroom.\n\nThe API process, operational worker, and reports worker are separate processes.\nThey may initially run on the same server; physical host separation is not required.\n'


def fail(message: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {message}")


def backup(path: Path) -> None:
    backup_dir = BACKEND / ".patch_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"{path.name}.before_reports_foundation_{stamp}.bak"
    shutil.copy2(path, dest)
    print(f"BACKUP={dest.relative_to(ROOT)}")


def patch_app_import() -> None:
    text_value = APP_FILE.read_text(encoding="utf-8")
    if '"workers.tasks.reports"' in text_value:
        print("ALREADY_PATCHED=wa_backend/workers/app.py")
        return

    anchor = '        "workers.tasks.integrity",\n'
    if text_value.count(anchor) != 1:
        fail("Expected exactly one integrity import anchor in workers/app.py")

    backup(APP_FILE)
    text_value = text_value.replace(
        anchor,
        anchor + '        "workers.tasks.reports",\n',
        1,
    )
    APP_FILE.write_text(text_value, encoding="utf-8")
    print("PATCHED=wa_backend/workers/app.py")


def patch_readme() -> None:
    text_value = README_FILE.read_text(encoding="utf-8")
    if "## Heavy Reports Foundation (V1)" in text_value:
        print("ALREADY_PATCHED=wa_backend/workers/README.md")
        return
    backup(README_FILE)
    README_FILE.write_text(
        text_value.rstrip() + "\n\n" + README_BLOCK,
        encoding="utf-8",
    )
    print("PATCHED=wa_backend/workers/README.md")


def verify() -> None:
    for path in [TASK_FILE, APP_FILE]:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    task = TASK_FILE.read_text(encoding="utf-8")
    app_text = APP_FILE.read_text(encoding="utf-8")
    readme = README_FILE.read_text(encoding="utf-8")

    checks = {
        "REPORTS_QUEUE_EXISTS": "REPORTS_QUEUE" in app_text,
        "TASK_IMPORTED": '"workers.tasks.reports"' in app_text,
        "TASK_QUEUE_REPORTS": "queue=REPORTS_QUEUE" in task,
        "EXPLICIT_COMPANY_ID": "company_id: int" in task,
        "TENANT_SESSION": "async with tenant_session(company_id)" in task,
        "READ_ONLY_TX": 'text("SET TRANSACTION READ ONLY")' in task,
        "TENANT_FILTER_SESSION": "WorkSession.company_id == company_id" in task,
        "TENANT_FILTER_VISIT": "Visit.company_id == company_id" in task,
        "TENANT_FILTER_TRANSFER": "InventoryTransferHeader.company_id == company_id" in task,
        "TENANT_FILTER_MOVEMENT": "InventoryMovement.company_id == company_id" in task,
        "NO_SQL_UPDATE": re.search(r"\bupdate\s*\(", task, re.I) is None,
        "NO_SQL_DELETE": re.search(r"\bdelete\s*\(", task, re.I) is None,
        "NO_SQL_INSERT": re.search(r"\binsert\s*\(", task, re.I) is None,
        "NO_ORM_STATUS_WRITE": re.search(r"\.status\s*=(?!=)", task) is None,
        "NO_SESSION_END_WRITE": re.search(r"\.end_time\s*=(?!=)", task) is None,
        "ROOT_OPERATIONAL_COMMAND": "worker -q maintenance,notifications -c 4" in readme,
        "ROOT_REPORTS_COMMAND": "worker -q reports -c 1" in readme,
    }

    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        fail(f"Static verification failed: {failed}")

    print("HEAVY_REPORTS_STATIC_VERIFY=OK")
    print("REPORTS_QUEUE_ISOLATION_STATIC_VERIFY=OK")
    print("REPORTS_TENANT_ISOLATION_STATIC_VERIFY=OK")
    print("REPORTS_READ_ONLY_STATIC_VERIFY=OK")
    print("WORKER_RUNBOOK_COMMANDS_FROZEN=OK")
    print("HEAVY_REPORTS_FOUNDATION_PATCH_V1=OK")


def main() -> None:
    for path in [APP_FILE, README_FILE]:
        if not path.exists():
            fail(f"Missing required file: {path.relative_to(ROOT)}")

    if TASK_FILE.exists():
        current = TASK_FILE.read_text(encoding="utf-8")
        if current != TASK_CONTENT:
            fail("workers/tasks/reports.py already exists with different content.")
        print("UNCHANGED=wa_backend/workers/tasks/reports.py")
    else:
        TASK_FILE.write_text(TASK_CONTENT, encoding="utf-8")
        print("CREATED=wa_backend/workers/tasks/reports.py")

    patch_app_import()
    patch_readme()
    verify()


if __name__ == "__main__":
    main()
