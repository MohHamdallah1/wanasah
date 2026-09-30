"""Static D4 durable recovery contract."""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"

queue = (BACKEND / "domains/simple_products/imports/infrastructure/queue.py").read_text(encoding="utf-8")
reconciler = (BACKEND / "domains/simple_products/imports/infrastructure/recovery_reconciler.py").read_text(encoding="utf-8")
migration = (BACKEND / "alembic/versions/a42c9f17e6b3_product_import_orphan_recovery.py").read_text(encoding="utf-8")
architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")

checks = {
    "job delivery has job-scoped queueing dedupe":
        'queueing_lock=f"product-import-job:{job_id}"' in queue,
    "recovery reconciles business jobs after queue stalled recovery":
        "reconcile_orphaned_import_jobs(" in queue
        and "queue_recovery = await recover_safe_stalled_jobs" in queue,
    "retry bookkeeping uses Procrastinate 3.9 retry_strategy contract":
        "context.task, \"retry_strategy\"" in queue
        and "strategy.get_retry_decision(" in queue,
    "orphan discovery is bounded and indexed":
        "ix_product_import_job_orphan_recovery" in migration
        and "LIMIT p_limit" in migration
        and "p_limit > 500" in migration,
    "orphan discovery excludes live queue delivery":
        "q.status IN ('todo','doing')" in migration
        and "q.args->>'job_id' = j.id::text" in migration,
    "privileged recovery boundary is constrained":
        "SECURITY DEFINER" in migration
        and "SET row_security = off" in migration
        and "REVOKE ALL ON FUNCTION" in migration
        and "GRANT EXECUTE ON FUNCTION" in migration,
    "reconciler preserves company execution serialization":
        'lock=f"product-import:{int(company_id)}"' in reconciler,
    "architecture records reusable durable-work direction":
        "Reusable durable async/import foundation" in architecture
        and "actual second consumer" in architecture
        and "technical delivery semantics only" in architecture,
}
failed = [name for name, passed in checks.items() if not passed]
for name, passed in checks.items():
    print(("[PASS] " if passed else "[FAIL] ") + name)
print(f"CHECKS={len(checks)}")
print(f"FAILURES={len(failed)}")
for name in failed:
    print("FAILED_CHECK=" + name)
if failed:
    raise SystemExit(1)
print("PRODUCT_IMPORT_D4_RECOVERY_STATIC_GATE=PASS")
