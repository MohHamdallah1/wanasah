from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
IMPORTS = BACKEND / "domains" / "simple_products" / "imports"
INFRA = IMPORTS / "infrastructure"

def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")

checks: list[tuple[str, bool]] = []

def check(label: str, condition: bool) -> None:
    checks.append((label, bool(condition)))

migration = read(BACKEND / "alembic" / "versions" / "d31c7a940e62_product_import_schedule_candidates.py")
scheduled = read(INFRA / "scheduled_work.py")
topology = read(INFRA / "queue_topology.py")
capacity = read(INFRA / "capacity_queue.py")
retention = read(INFRA / "retention_queue.py")
worker_cli = read(INFRA / "worker_cli.py")
launcher = read(BACKEND / "scripts" / "run_product_import_worker.ps1")

check(
    "candidate registry has bounded indexed due scheduling",
    "product_import_schedule_candidates" in migration
    and "ix_product_import_schedule_due" in migration
    and "FOR UPDATE SKIP LOCKED" in migration
    and "page_size > 1000" in migration,
)
check(
    "candidate registry is RLS protected and SECURITY DEFINER is constrained",
    "FORCE ROW LEVEL SECURITY" in migration
    and "SECURITY DEFINER SET search_path = pg_catalog, pg_temp" in migration
    and "REVOKE ALL ON FUNCTION public.product_import_schedule_event() FROM PUBLIC" in migration
    and "product_import_claim_schedule(text,timestamptz,integer) FROM PUBLIC" in migration
    and "product_import_finish_schedule(integer,text,bigint,timestamptz) FROM PUBLIC" in migration,
)
check(
    "event generation protects against stale completion",
    "product_import_schedule_generation" in migration
    and "expected_generation" in migration
    and "c.generation = expected_generation" in migration
    and "generation = nextval" in migration,
)
check(
    "scheduler never enumerates Company or tenant eligibility one by one",
    "iter_retention_company_id_pages" not in scheduled
    and "has_scheduled_work" not in scheduled
    and "Company" not in scheduled
    and "product_import_claim_schedule" in scheduled,
)
check(
    "capacity and retention dispatch through isolated maintenance queue",
    "MAINTENANCE_QUEUE" in capacity
    and "defer_due_candidates" in capacity
    and "reconcile_candidate" in capacity
    and "MAINTENANCE_QUEUE" in retention
    and "defer_due_candidates" in retention
    and "reconcile_candidate" in retention,
)
check(
    "execution control and maintenance queues remain explicit",
    'EXECUTION_QUEUE = "product-import"' in topology
    and 'CONTROL_QUEUE = "product-import-control"' in topology
    and 'MAINTENANCE_QUEUE = "product-import-maintenance"' in topology
    and "is_execution_consumer" in topology,
)
check(
    "worker launcher uses one role-scoped canonical entrypoint",
    "worker_cli" in launcher
    and "--role $Role" in launcher
    and "ROLE_QUEUES" in worker_cli
    and "run_worker_async" in worker_cli,
)
failures = [label for label, passed in checks if not passed]
for label, passed in checks:
    print(("[PASS] " if passed else "[FAIL] ") + label)
print(f"CHECKS={len(checks)}")
print(f"FAILURES={len(failures)}")
if failures:
    for label in failures:
        print("FAILED_CHECK=" + label)
    raise SystemExit(1)
print("PRODUCT_IMPORT_D31_EVENT_SCHEDULER_GATE=PASS")
