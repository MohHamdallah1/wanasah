from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
WORKERS = BACKEND / "workers"
TASKS = WORKERS / "tasks"
OPS = ROOT / "ops" / "development"

checks = 0
failures: list[str] = []


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(label)


app = read(WORKERS / "app.py")
tenant = read(WORKERS / "tenant.py")
scheduling = read(WORKERS / "scheduling.py")
recovery = read(WORKERS / "recovery.py")
recover_cli = read(WORKERS / "recover_cli.py")
maintenance = read(TASKS / "maintenance.py")
handshake = read(TASKS / "handshake.py")
sessions = read(TASKS / "session_monitor.py")
integrity = read(TASKS / "integrity.py")
live_stock = read(TASKS / "live_stock.py")
reports = read(TASKS / "reports.py")
product_import = read(BACKEND / "product_import_queue.py")
dev_runbook = read(ROOT / "docs" / "operations" / "DEVELOPMENT_WORKERS.md")

operational_launcher = read(OPS / "run_operational_worker.ps1")
reports_launcher = read(OPS / "run_reports_worker.ps1")
product_launcher = read(OPS / "run_product_import_worker.ps1")

check(
    not (BACKEND / "scripts" / "run_dev_operational_worker.ps1").exists()
    and (OPS / "run_operational_worker.ps1").is_file()
    and (OPS / "run_reports_worker.ps1").is_file()
    and (OPS / "run_product_import_worker.ps1").is_file(),
    "permanent worker launchers live under ops/development, not test scripts",
)

check(
    "tenant_context.set(cid)" in tenant
    and "'app.current_tenant', :tenant_id" in tenant
    and "_clear_tenant_or_invalidate" in tenant
    and "tenant_context.reset(token)" in tenant,
    "tenant worker sessions establish and clear tenant context fail-closed",
)

check(
    "pg_advisory_xact_lock(" in tenant
    and "hashtext(:namespace), :company_id" in tenant,
    "company worker serialization uses transaction advisory locks",
)

check(
    "COMPANY_SCAN_PAGE = 1000" in scheduling
    and "Company.is_active.is_(True)" in scheduling
    and "Company.id > after_company_id" in scheduling
    and ".limit(page_size)" in scheduling,
    "global tenant discovery is bounded, keyset-paginated, and active-only",
)

check(
    "status = ANY(%(statuses)s::procrastinate_job_status[])" in scheduling
    and 'statuses=["todo", "doing"]' in scheduling
    and "await task.configure(lock=lock_name).defer_async" in scheduling
    and "queueing_lock=lock_name" not in scheduling,
    "company child scheduling prevents active duplicate backlog without retry-hostile queueing locks",
)

for source, label in (
    (handshake, "stale-handshake"),
    (sessions, "stale-session"),
    (integrity, "integrity"),
    (live_stock, "Live Stock"),
):
    check(
        "iter_active_company_id_pages" in source
        and "defer_unique_company_jobs" in source
        and "company_jobs_skipped_duplicate" in source,
        f"{label} global scan uses shared bounded tenant scheduling",
    )

check(
    "WORKER_HEARTBEAT_SECONDS = 10.0" in app
    and "STALLED_WORKER_TIMEOUT_SECONDS = 30.0" in app
    and '"update_heartbeat_interval": WORKER_HEARTBEAT_SECONDS' in app
    and '"stalled_worker_timeout": STALLED_WORKER_TIMEOUT_SECONDS' in app,
    "operational worker heartbeat and stalled timeout are explicit",
)

check(
    "prune_stalled_workers(" in recovery
    and "get_stalled_jobs(" in recovery
    and "task_name not in allowlist" in recovery
    and "superseded_by_queued" in recovery
    and "failed_not_allowlisted" in recovery
    and "failed_lock_conflict" in recovery
    and "finish_job_by_id_async" in recovery
    and "retry_job(job)" in recovery,
    "stalled recovery is allowlisted and handles queued-successor collisions",
)

check(
    '@app.periodic(cron="*/10 * * * *")' in maintenance
    and "recover_safe_stalled_jobs(" in maintenance
    and "STALLED_RETRY_ALLOWLIST" in maintenance,
    "operational stalled recovery remains periodic and allowlisted",
)

check(
    '@app.periodic(cron="2,17,32,47 * * * *")' in live_stock
    and "mark_live_stock_projection_degraded" in live_stock
    and 'state == "DEGRADED"' in live_stock
    and "reconcile_live_stock_company" in live_stock,
    "Live Stock maintenance remains scheduled, fail-closed, and recoverable",
)

check(
    "SET TRANSACTION READ ONLY" in reports
    and "tenant_session(company_id)" in reports
    and '"wanasah.report_foundation_probe"' in reports
    and '"wanasah.recover_stalled_reports"' in reports
    and '@app.periodic(cron="*/10 * * * *")' in reports
    and "recover_safe_stalled_jobs(" in reports,
    "report worker is tenant-scoped, read-only, and independently recoverable",
)

check(
    "RetryStrategy(" in product_import
    and "max_attempts=4" in product_import
    and '@app.periodic(cron="*/5 * * * *")' in product_import
    and "recover_safe_stalled_jobs(" in product_import
    and '"options": "-c search_path=public"' in product_import,
    "product import has exception retry, crash recovery, and explicit atomic queue schema",
)

check(
    '"operational"' in recover_cli
    and '"reports"' in recover_cli
    and '"product-import"' in recover_cli
    and "recover_safe_stalled_jobs(" in recover_cli,
    "startup recovery CLI covers every current worker role",
)

check(
    "-m workers.recover_cli operational" in operational_launcher
    and "--app=workers.app.app worker -q maintenance,notifications" in operational_launcher,
    "operational launcher recovers before starting maintenance/notifications",
)

check(
    "-m workers.recover_cli reports" in reports_launcher
    and "--app=workers.app.app worker -q reports" in reports_launcher,
    "reports launcher recovers before starting reports",
)

check(
    "-m workers.recover_cli product-import" in product_launcher
    and "--app=product_import_queue.app worker -q product-import" in product_launcher,
    "product-import launcher recovers before starting its separate worker app",
)

check(
    "There are currently no registered notification-delivery tasks" in dev_runbook
    and "run_reports_worker.ps1" in dev_runbook
    and "run_product_import_worker.ps1" in dev_runbook
    and "Do not also run the equivalent long Procrastinate command manually" in dev_runbook,
    "runbook states current queue topology and launcher authority explicitly",
)

print(f"CHECKS={checks}")
print(f"FAILURES={len(failures)}")
for failure in failures:
    print(f"FAILED_CHECK={failure}")

if failures:
    print("WORKER_FOUNDATION_STATIC_GATE=FAIL")
    sys.exit(1)

print("WORKER_FOUNDATION_STATIC_GATE=PASS")
