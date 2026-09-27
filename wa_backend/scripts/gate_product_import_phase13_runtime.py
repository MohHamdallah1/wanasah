from __future__ import annotations

from pathlib import Path


ROOT = Path(
    __file__
).resolve().parents[1]
REPO = ROOT.parent


def read(
    relative: str,
) -> str:
    return (
        REPO
        / relative
    ).read_text(
        encoding="utf-8"
    )


checks: list[
    tuple[
        str,
        bool,
    ]
] = []


def check(
    label: str,
    condition: bool,
) -> None:
    checks.append(
        (
            label,
            bool(
                condition
            ),
        )
    )


queue = read(
    "wa_backend/domains/simple_products/imports/infrastructure/queue.py"
)
runtime = read(
    "wa_backend/domains/simple_products/imports/infrastructure/runtime_monitor.py"
)
capacity = read(
    "wa_backend/domains/simple_products/imports/infrastructure/capacity_queue.py"
)
admission = read(
    "wa_backend/domains/simple_products/imports/domain/admission.py"
)
manager = read(
    "wa_backend/domains/simple_products/imports/infrastructure/realtime_manager.py"
)
relay = read(
    "wa_backend/domains/simple_products/imports/infrastructure/realtime_relay.py"
)
router = read(
    "wa_backend/domains/simple_products/imports/api/router.py"
)
migration = read(
    "wa_backend/alembic/versions/d1f4a8c6e2b9_stage13_import_runtime.py"
)
cancellation = read(
    "wa_backend/domains/simple_products/imports/application/cancellation_service.py"
)
execution = read(
    "wa_backend/domains/simple_products/imports/application/execution_service.py"
)
validation = read(
    "wa_backend/domains/simple_products/imports/application/validation_service.py"
)
frontend = read(
    "dashboard/src/pages/products/import/useImportProductPolling.ts"
)
decision = read(
    "wa_backend/domains/simple_products/imports/PHASE13_RUNTIME.md"
)
tests = read(
    "wa_backend/tests/test_product_import_phase13_runtime.py"
)

check(
    "company serialization retained and documented",
    'lock=f"product-import:{int(company_id)}"' in queue
    and "shared company-default" in decision,
)
check(
    "per-tenant active import backpressure remains authoritative",
    "PRODUCT_IMPORT_MAX_ACTIVE_JOBS_PER_TENANT" in admission
    and "max_active_jobs_per_tenant" in admission,
)
check(
    "durable coarse progress notify exists",
    "trg_product_import_progress_notify" in migration
    and "AFTER INSERT OR UPDATE OF" in migration
    and "PRODUCT_IMPORT_PROGRESS" in migration,
)
check(
    "dedicated exact-job realtime channel exists",
    '@router.websocket("/imports/{job_id}/ws")' in router
    and "product_import_connection_manager.connect" in router
    and "ProductImportJob.company_id" in router,
)
check(
    "realtime relay is bounded and coalesced",
    "MAX_EVENT_BUFFER = 1000" in relay
    and "COALESCE_SECONDS = 0.25" in relay
    and "latest" in relay,
)
check(
    "adaptive polling is fallback only and visibility-aware",
    "productImportBackoffDelay" in frontend
    and "realtimeOpen" in frontend
    and "visibilitychange" in frontend
    and "setInterval" not in frontend,
)
check(
    "browser observes only exact active job",
    "isProductImportProgressEvent" in frontend
    and "/simple-products/imports/" in frontend
    and "every active" not in frontend.lower(),
)
check(
    "global worker capacity metrics exist",
    "healthy_worker_processes" in runtime
    and "configured_worker_slots" in runtime
    and "available_worker_slots" in runtime,
)
check(
    "queue age and oldest job monitoring exist",
    "oldest_queue_age_seconds" in runtime
    and "oldest_active_job_age_seconds" in read(
        "wa_backend/domains/simple_products/imports/infrastructure/capacity_monitor.py"
    ),
)
check(
    "worker readiness signal exists without global tenant leakage",
    '@router.get("/import-worker/readiness")' in router
    and '"ready"' in router
    and '"queued_jobs"' not in router[
        router.index('@router.get("/import-worker/readiness")'):
        router.index('@router.websocket("/imports/{job_id}/ws")')
    ],
)
check(
    "stuck stage alert exists",
    "PRODUCT_IMPORT_STUCK_STAGE" in capacity
    and "STUCK_STAGE_ALERT_SECONDS" in capacity,
)
check(
    "explicit cancellation state and endpoint exist",
    "JobStatus.CANCELLED" in cancellation
    and '"/imports/{job_id}/cancel"' in router
    and "'CANCELLED'" in migration,
)
check(
    "cancellation uses transaction boundary lock",
    "for_update=True" in cancellation
    and "for_update=True" in execution
    and "for_update=True" in validation,
)
check(
    "duplicate delivery stalled recovery and restart tests exist",
    "Phase13DuplicateDeliveryTests" in tests
    and "test_stalled_product_import_delivery_is_retried" in tests
    and "test_worker_restart_resumes_durable_importing_state" in tests,
)
check(
    "connection reconnect and backpressure tests exist",
    "test_connection_broadcast_is_exact_job_scoped" in tests
    and "test_connection_backpressure_fails_closed" in tests
    and "productImportBackoffDelay" in read(
        "dashboard/src/test/products-import-phase13-realtime.test.ts"
    ),
)

failures = [
    label
    for label, passed
    in checks
    if not passed
]
for label, passed in checks:
    print(
        (
            "[PASS] "
            if passed
            else "[FAIL] "
        )
        + label
    )

print(
    f"CHECKS={len(checks)}"
)
print(
    f"FAILURES={len(failures)}"
)
if failures:
    for label in failures:
        print(
            "FAILED_CHECK="
            + label
        )
    print(
        "PRODUCT_IMPORT_PHASE13_RUNTIME_GATE=FAIL"
    )
    raise SystemExit(
        1
    )

print(
    "PRODUCT_IMPORT_PHASE13_RUNTIME_GATE=PASS"
)
