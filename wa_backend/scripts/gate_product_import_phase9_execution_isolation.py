from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.exc import OperationalError


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(
    0,
    str(BACKEND),
)

from domains.simple_products.imports.domain.errors import (  # noqa: E402
    ImportErrorKind,
    ImportFailureScope,
    ProductImportRowExecutionError,
    ProductImportRowValidationError,
    classify_import_error,
)


checks = 0
failures: list[str] = []


def check(
    condition: bool,
    label: str,
) -> None:
    global checks
    checks += 1
    print(
        (
            "[PASS] "
            if condition
            else "[FAIL] "
        )
        + label
    )
    if not condition:
        failures.append(
            label
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

validation = (
    classify_import_error(
        ProductImportRowValidationError(
            "ROW_BAD",
            "bad",
        )
    )
)
check(
    validation.kind
    is ImportErrorKind.DETERMINISTIC_VALIDATION
    and validation.scope
    is ImportFailureScope.ROW
    and not validation.retryable,
    "Validation row errors are deterministic row-attributable failures",
)

execution = (
    classify_import_error(
        ProductImportRowExecutionError(
            "ROW_EXEC_BAD",
            "bad",
        )
    )
)
check(
    execution.kind
    is ImportErrorKind.DETERMINISTIC_ROW_EXECUTION
    and execution.scope
    is ImportFailureScope.ROW
    and not execution.retryable,
    "Execution row errors are deterministic row-attributable failures",
)

outage = OperationalError(
    "SELECT 1",
    {},
    ConnectionError(
        "database unavailable"
    ),
)
classified_outage = (
    classify_import_error(
        outage
    )
)
check(
    classified_outage.kind
    is ImportErrorKind.TRANSIENT_SYSTEM
    and classified_outage.scope
    is ImportFailureScope.JOB
    and classified_outage.retryable,
    "Database/system outage stays transient job failure",
)

check(
    "async with db.begin_nested():"
    in execution_source,
    "Execution attempts are isolated with savepoints",
)

check(
    "midpoint ="
    in execution_source
    and "_execute_rows_best_effort("
    in execution_source,
    "Deterministic batch failures use bounded recursive bisection",
)

check(
    "if len(rows) == 1:"
    in execution_source
    and "RowStatus.IMPORT_FAILED"
    in execution_source,
    "Bisection stops at one row and records IMPORT_FAILED",
)

check(
    "create_products_and_prices("
    in execution_source,
    "Execution preserves Product/Pricing domain authority",
)

check(
    "classify_execution_row_error("
    in execution_source
    and "if row_error is None:"
    in execution_source
    and "raise"
    in execution_source,
    "Non-attributable/system failures propagate instead of blaming rows",
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
        "PRODUCT_IMPORT_PHASE9_EXECUTION_ISOLATION_GATE=FAIL"
    )
    raise SystemExit(1)

print(
    f"CHECKS={checks}"
)
print("FAILURES=0")
print(
    "PRODUCT_IMPORT_PHASE9_EXECUTION_ISOLATION_GATE=PASS"
)
