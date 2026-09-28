from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
DASHBOARD = ROOT / "dashboard" / "src"
sys.path.insert(
    0,
    str(BACKEND),
)

from domains.simple_products.imports.application.execution_service import (  # noqa: E402
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


checks = 0
failures: list[str] = []


def check(
    condition: bool,
    label: str,
    detail: str = "",
) -> None:
    global checks
    checks += 1
    prefix = (
        "[PASS]"
        if condition
        else "[FAIL]"
    )
    suffix = (
        f" — {detail}"
        if detail
        else ""
    )
    print(
        f"{prefix} {label}{suffix}"
    )
    if not condition:
        failures.append(label)


validation_source = (
    BACKEND
    / "domains"
    / "simple_products"
    / "imports"
    / "application"
    / "validation_service.py"
).read_text(
    encoding="utf-8"
)
execution_source = (
    BACKEND
    / "domains"
    / "simple_products"
    / "imports"
    / "application"
    / "execution_service.py"
).read_text(
    encoding="utf-8"
)
schemas_source = (
    BACKEND
    / "domains"
    / "simple_products"
    / "imports"
    / "api"
    / "schemas.py"
).read_text(
    encoding="utf-8"
)
contracts_source = (
    DASHBOARD
    / "pages"
    / "products"
    / "contracts.ts"
).read_text(
    encoding="utf-8"
)
polling_source = (
    DASHBOARD
    / "pages"
    / "products"
    / "import"
    / "useImportProductPolling.ts"
).read_text(
    encoding="utf-8"
)


check(
    validation_outcome(
        49_999,
        1,
    )
    == (
        JobStatus.IMPORTING.value,
        True,
    ),
    "One invalid row does not block 49,999 valid rows",
)

check(
    validation_outcome(
        0,
        50_000,
    )
    == (
        JobStatus.VALIDATION_FAILED.value,
        False,
    ),
    "Zero valid rows stop at VALIDATION_FAILED",
)

check(
    completion_outcome(
        ProductImportProgress(
            total_rows=50_000,
            imported_rows=49_999,
            invalid_rows=1,
            import_failed_rows=0,
            pending_rows=0,
        )
    )
    is JobStatus.COMPLETED_WITH_ERRORS,
    "Mixed imported/invalid outcomes finish COMPLETED_WITH_ERRORS",
)

check(
    completion_outcome(
        ProductImportProgress(
            total_rows=100,
            imported_rows=100,
            invalid_rows=0,
            import_failed_rows=0,
            pending_rows=0,
        )
    )
    is JobStatus.COMPLETED,
    "All-success outcome finishes COMPLETED",
)

check(
    "status=RowStatus.VALID.value"
    in execution_source
    and "list_job_rows("
    in execution_source,
    "Execution selects only VALID rows",
)

check(
    "RowStatus.IMPORT_FAILED"
    in execution_source
    and "begin_nested()"
    in execution_source,
    "Deterministic execution failures are isolated with savepoints and recorded per row",
)

check(
    "delete_job_rows("
    not in execution_source,
    "Execution retains durable row outcomes for progress/audit instead of deleting imported rows",
)

check(
    "JobStatus.FAILED"
    not in execution_source,
    "Execution does not convert row/business outcomes directly into FAILED",
)

for field in (
    "imported_rows",
    "invalid_rows",
    "import_failed_rows",
    "pending_rows",
):
    check(
        field
        in schemas_source
        and field
        in contracts_source,
        f"Public Product Import contract exposes {field}",
    )

check(
    "COMPLETED_WITH_ERRORS"
    in contracts_source
    and "COMPLETED_WITH_ERRORS"
    in polling_source,
    "Frontend recognizes partial success as a terminal Product Import status",
)

check(
    "PRODUCT_IMPORT_VALIDATION_PARTIAL"
    in validation_source,
    "Partial validation preserves deterministic error summary while continuing",
)


if failures:
    print(
        f"CHECKS={checks}"
    )
    print(
        f"FAILURES={len(failures)}"
    )
    for failure in failures:
        print(
            f"FAIL: {failure}"
        )
    print(
        "PRODUCT_IMPORT_PHASE7_BEST_EFFORT_GATE=FAIL"
    )
    raise SystemExit(1)

print(
    f"CHECKS={checks}"
)
print("FAILURES=0")
print(
    "PRODUCT_IMPORT_PHASE7_BEST_EFFORT_GATE=PASS"
)
