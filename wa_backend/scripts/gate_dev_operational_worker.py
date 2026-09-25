from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "wa_backend" / "scripts" / "run_dev_operational_worker.ps1"
RUNBOOK = ROOT / "docs" / "operations" / "DEVELOPMENT_WORKERS.md"
WORKER_APP = ROOT / "wa_backend" / "workers" / "app.py"
LIVE_STOCK_TASKS = ROOT / "wa_backend" / "workers" / "tasks" / "live_stock.py"

checks = 0
failures: list[str] = []


def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(label)


script = SCRIPT.read_text(encoding="utf-8")
runbook = RUNBOOK.read_text(encoding="utf-8")
worker_app = WORKER_APP.read_text(encoding="utf-8")
live_stock_tasks = LIVE_STOCK_TASKS.read_text(encoding="utf-8")

canonical_app = "--app=workers.app.app"
canonical_queues = "-q maintenance,notifications"

check(
    canonical_app in script
    and canonical_queues in script,
    "operational worker launcher uses the canonical app and queues",
)
check(
    "venv\\Scripts\\python.exe" in script
    and "Activate.ps1" not in script,
    "launcher uses the repository backend virtual environment directly",
)
check(
    "product_import_queue.app" not in script
    and "-q reports" not in script,
    "operational launcher does not mix independent worker roles",
)
check(
    "MAINTENANCE_QUEUE = \"maintenance\"" in worker_app
    and "NOTIFICATIONS_QUEUE = \"notifications\"" in worker_app
    and '"workers.tasks.live_stock"' in worker_app
    and '"workers.tasks.maintenance"' in worker_app,
    "worker app still owns the operational queues and periodic task imports",
)
check(
    '@app.periodic(cron="2,17,32,47 * * * *")' in live_stock_tasks
    and "queue=MAINTENANCE_QUEUE" in live_stock_tasks,
    "Live Stock transition maintenance remains periodic on maintenance queue",
)
check(
    ".\\wa_backend\\scripts\\run_dev_operational_worker.ps1" in runbook
    and "maintenance,notifications" in runbook
    and "product_import_queue.app" in runbook,
    "development runbook documents required and optional worker roles",
)
check(
    "Tenant-specific jobs" in runbook
    and "never bypasses tenant RLS" in runbook,
    "development runbook preserves the tenant isolation contract",
)

print(f"CHECKS={checks}")
print(f"FAILURES={len(failures)}")
for failure in failures:
    print(f"FAILED_CHECK={failure}")

if failures:
    print("DEV_OPERATIONAL_WORKER_GATE=FAIL")
    sys.exit(1)

print("DEV_OPERATIONAL_WORKER_GATE=PASS")
