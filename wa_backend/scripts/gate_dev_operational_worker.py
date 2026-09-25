from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
OPERATIONAL_SCRIPT = ROOT / "ops" / "development" / "run_operational_worker.ps1"
REPORTS_SCRIPT = ROOT / "ops" / "development" / "run_reports_worker.ps1"
PRODUCT_IMPORT_SCRIPT = ROOT / "ops" / "development" / "run_product_import_worker.ps1"
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


operational_script = OPERATIONAL_SCRIPT.read_text(encoding="utf-8")
reports_script = REPORTS_SCRIPT.read_text(encoding="utf-8")
product_import_script = PRODUCT_IMPORT_SCRIPT.read_text(encoding="utf-8")
runbook = RUNBOOK.read_text(encoding="utf-8")
worker_app = WORKER_APP.read_text(encoding="utf-8")
live_stock_tasks = LIVE_STOCK_TASKS.read_text(encoding="utf-8")

canonical_app = "--app=workers.app.app"
canonical_queues = "-q maintenance,notifications"

check(
    canonical_app in operational_script
    and canonical_queues in operational_script
    and "-m workers.recover_cli operational" in operational_script,
    "operational worker launcher uses the canonical app and queues",
)
check(
    "venv\\Scripts\\python.exe" in operational_script
    and "Activate.ps1" not in operational_script,
    "launcher uses the repository backend virtual environment directly",
)
check(
    "product_import_queue.app" not in operational_script
    and "-q reports" not in operational_script,
    "operational launcher does not mix independent worker roles",
)
check(
    "--app=workers.app.app worker -q reports" in reports_script
    and "-m workers.recover_cli reports" in reports_script
    and "maintenance,notifications" not in reports_script,
    "reports launcher is isolated and performs report startup recovery",
)

check(
    "--app=product_import_queue.app worker -q product-import"
    in product_import_script
    and "-m workers.recover_cli product-import" in product_import_script
    and "--app=workers.app.app" not in product_import_script,
    "product-import launcher is isolated and performs import startup recovery",
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
    ".\\ops\\development\\run_operational_worker.ps1" in runbook
    and ".\\ops\\development\\run_reports_worker.ps1" in runbook
    and ".\\ops\\development\\run_product_import_worker.ps1" in runbook
    and "maintenance,notifications" in runbook
    and "product_import_queue.app" in runbook,
    "development runbook documents required and optional worker roles",
)
check(
    "tenant_session(company_id)" in runbook
    and "app.current_tenant" in runbook
    and "RLS and explicit company/location predicates remain authoritative"
    in runbook,
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
