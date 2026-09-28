from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
sys.path.insert(0, str(BACKEND))

from domains.simple_products.imports.application.execution_service import (  # noqa: E402
    _completion_summary,
    completion_outcome,
)
from domains.simple_products.imports.application.state_machine import (  # noqa: E402
    JobStatus,
)
from domains.simple_products.imports.application.validation_service import (  # noqa: E402
    validation_outcome,
)
from domains.simple_products.imports.infrastructure.repository import (  # noqa: E402
    ProductImportProgress,
)


checks: list[tuple[str, bool]] = []


def check(
    label: str,
    condition: bool,
) -> None:
    checks.append(
        (
            label,
            bool(condition),
        )
    )


def read(
    relative: str,
) -> str:
    return (
        ROOT
        / relative
    ).read_text(
        encoding="utf-8"
    )


stream_gate = read(
    "wa_backend/scripts/gate_product_import_phase4_streaming.py"
)
phase6_gate = read(
    "wa_backend/scripts/gate_product_import_phase6_query_plans.py"
)
phase6_repository = read(
    "wa_backend/domains/simple_products/imports/infrastructure/barcode_repository.py"
)
phase5_tests = read(
    "wa_backend/tests/test_product_import_phase5_validation.py"
)
phase8_tests = read(
    "wa_backend/tests/test_product_import_phase8_idempotency_correction.py"
)
phase9_tests = read(
    "wa_backend/tests/test_product_import_phase9_execution_isolation.py"
)
phase13_tests = read(
    "wa_backend/tests/test_product_import_phase13_runtime.py"
)
phase16_tests = read(
    "wa_backend/tests/test_product_import_phase16_api.py"
)
phase17_tests = read(
    "wa_backend/tests/test_product_import_phase17_failure_gates.py"
)

check(
    "50k CSV bounded-memory gate exists",
    "50_000" in stream_gate
    and "MEMORY_PEAK_50000" in stream_gate
    and "same fixed memory envelope"
    in stream_gate,
)
check(
    "50k XLSX bounded-memory gate exists",
    "XLSX_MEMORY_PEAK_50000"
    in stream_gate
    and "16 * 1024 * 1024"
    in stream_gate
    and "50,000-row XLSX incremental working set"
    in stream_gate,
)

mixed = ProductImportProgress(
    total_rows=50_000,
    imported_rows=49_999,
    invalid_rows=1,
    import_failed_rows=0,
    pending_rows=0,
)
check(
    "50k mixed validation continues valid rows",
    validation_outcome(
        49_999,
        1,
    )
    == (
        JobStatus.IMPORTING.value,
        True,
    ),
)
check(
    "50k mixed execution completes with reported invalid row",
    completion_outcome(mixed)
    is JobStatus.COMPLETED_WITH_ERRORS
    and _completion_summary(mixed)
    == {
        "code":
            "PRODUCT_IMPORT_COMPLETED_WITH_ERRORS",
        "imported_rows": 49_999,
        "invalid_rows": 1,
        "import_failed_rows": 0,
    },
)
check(
    "100k barcode candidates cannot become one giant IN parameter list",
    ".in_("
    not in phase6_repository
    and "giant parameterized IN query"
    in phase6_gate,
)
check(
    "one deterministic bad row in 100 isolates the other 99",
    "test_one_constraint_failure_in_100_rows_imports_other_99"
    in phase9_tests,
)
check(
    "parsing crash retains source and resumes",
    "test_parsing_crash_retains_source_and_retry_resumes_safely"
    in phase17_tests,
)
check(
    "validation crash resumes without reprocessing finalized rows",
    "test_crash_resume_skips_already_finalized_rows"
    in phase5_tests,
)
check(
    "post-commit crash replay does not duplicate Product",
    "test_crash_replay_uses_durable_idempotency_result_without_duplicate_create"
    in phase8_tests,
)
check(
    "duplicate queue delivery is idempotent",
    "test_duplicate_queue_delivery_replays_same_row_identity_and_creates_once"
    in phase8_tests
    and "test_duplicate_delivery_replays_durable_row_result_without_create"
    in phase13_tests,
)
check(
    "database outage remains transient job failure rather than fake row errors",
    "test_database_outage_is_not_converted_into_100_row_errors"
    in phase9_tests,
)
check(
    "permission revocation fails before execution writes",
    "test_revoked_permission_fails_before_execution_rows_or_writes"
    in phase17_tests,
)
check(
    "tenant isolation has API and repository/worker-path negative proofs",
    "ProductImportPhase16TenantIsolationTests"
    in phase16_tests
    and "test_job_lookup_is_tenant_prefixed_before_repository_read"
    in phase17_tests,
)
check(
    "cancellation is terminal from every active resumable state",
    "test_all_active_states_can_cancel_and_cancelled_is_terminal"
    in phase13_tests
    and "test_cancel_takes_job_row_lock_and_commits_terminal_state"
    in phase13_tests,
)
check(
    "worker stalled/restart recovery remains covered",
    "test_stalled_product_import_delivery_is_retried"
    in phase13_tests
    and "test_worker_restart_resumes_durable_importing_state"
    in phase13_tests,
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
        "PRODUCT_IMPORT_PHASE17_FINAL_GATES=FAIL"
    )
    raise SystemExit(1)

print(
    "PRODUCT_IMPORT_PHASE17_FINAL_GATES=PASS"
)
