from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
sys.path.insert(
    0,
    str(BACKEND),
)

VALIDATION = (
    BACKEND
    / "domains"
    / "simple_products"
    / "imports"
    / "application"
    / "validation_service.py"
)
REPOSITORY = (
    BACKEND
    / "domains"
    / "simple_products"
    / "imports"
    / "infrastructure"
    / "repository.py"
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
    VALIDATION.read_text(
        encoding="utf-8"
    )
)
repository_source = (
    REPOSITORY.read_text(
        encoding="utf-8"
    )
)


check(
    "VALIDATION_BATCH_SIZE = 500"
    in validation_source,
    "Validation batch size is fixed and explicit",
)

check(
    "fetch_validation_batch("
    in validation_source
    and "list_job_rows("
    not in validation_source,
    "Validation reads staged rows only through the bounded batch repository path",
)

check(
    ".all()" not in validation_source,
    "Validation service has no full ORM .all() materialization",
)

validation_repo_start = (
    repository_source.index(
        "async def fetch_validation_batch("
    )
)
validation_repo_end = (
    repository_source.index(
        "async def count_validation_outcomes(",
        validation_repo_start,
    )
)
validation_repo_block = (
    repository_source[
        validation_repo_start:
        validation_repo_end
    ]
)
check(
    ".limit(" in validation_repo_block
    and ".fetchmany(" in validation_repo_block
    and '== "STAGED"'
    in validation_repo_block
    and "row_number"
    in validation_repo_block,
    "Repository validation read is STAGED-only keyset pagination with bounded fetchmany",
)

check(
    "await db.commit()"
    in validation_source
    and "touch_job("
    in validation_source,
    "Validation persists row outcomes and counters incrementally",
)

check(
    validation_source.count(
        "count_job_statuses("
    )
    == 1
    and "job_has_rows("
    in validation_source
    and "valid_rows="
    in validation_source
    and "failed_rows="
    in validation_source,
    "Validation reconciles durable counters once per lifecycle and uses indexed existence checkpoints",
)

check(
    "after_row_number = 0"
    in validation_source
    and "staged_count > 0"
    in validation_source
    and "reset_cursor"
    in validation_source,
    "Validation has a durable STAGED-status checkpoint and safe cursor recovery",
)

check(
    "barcode_rows"
    not in validation_source
    and "find_active_barcodes"
    not in validation_source,
    "Phase 6 removed Python barcode ownership collections from validation",
)

tree = ast.parse(
    validation_source,
    filename=str(
        VALIDATION
    ),
)
unbounded_comprehensions = []
for node in ast.walk(tree):
    if isinstance(
        node,
        ast.Call,
    ) and isinstance(
        node.func,
        ast.Attribute,
    ) and node.func.attr == "all":
        unbounded_comprehensions.append(
            int(node.lineno)
        )

check(
    not unbounded_comprehensions,
    "AST confirms no validation .all() call can regress",
    repr(
        unbounded_comprehensions
    ),
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
        "PRODUCT_IMPORT_PHASE5_VALIDATION_GATE=FAIL"
    )
    raise SystemExit(1)

print(
    f"CHECKS={checks}"
)
print("FAILURES=0")
print(
    "PRODUCT_IMPORT_PHASE5_VALIDATION_GATE=PASS"
)
