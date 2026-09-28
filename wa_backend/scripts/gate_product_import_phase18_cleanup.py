from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
IMPORTS = (
    BACKEND
    / "domains"
    / "simple_products"
    / "imports"
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


def read(path: Path) -> str:
    return path.read_text(
        encoding="utf-8"
    )


source_service = read(
    IMPORTS
    / "application"
    / "source_service.py"
)
staging_service = read(
    IMPORTS
    / "application"
    / "staging_service.py"
)
application_init = read(
    IMPORTS
    / "application"
    / "__init__.py"
)
queue = read(
    IMPORTS
    / "infrastructure"
    / "queue.py"
)
router = read(
    IMPORTS
    / "api"
    / "router.py"
)
worker = read(
    IMPORTS
    / "application"
    / "worker.py"
)
architecture = read(
    ROOT
    / "ARCHITECTURE.md"
)
runbook = read(
    IMPORTS
    / "RUNBOOK.md"
)
module_docs = read(
    IMPORTS
    / "README.md"
)
launcher = read(
    BACKEND
    / "scripts"
    / "run_product_import_worker.ps1"
)
plan = read(
    ROOT
    / "PRODUCT_IMPORT_PRODUCTION_HARDENING_PLAN.md"
)

check(
    "legacy inline source execution is removed",
    "legacy_payload"
    not in source_service
    and "job.source_payload"
    not in source_service
    and "source_payload"
    not in staging_service
    and "source_payload,"
    not in queue,
)
check(
    "migration-only application alias is removed",
    "mark_import_runtime_failure"
    not in application_init
    and "record_runtime_failure"
    in application_init,
)

root_business = [
    path.name
    for path in ROOT.glob(
        "product_import_*.py"
    )
]
backend_root_business = [
    path.name
    for path in BACKEND.glob(
        "product_import_*.py"
    )
]
check(
    "no root-level Product Import executable business files remain",
    not root_business
    and not backend_root_business,
)

application_files = sorted(
    (
        IMPORTS
        / "application"
    ).glob(
        "*.py"
    )
)
alternate_orchestrators: list[str] = []
for path in application_files:
    if path.name == "worker.py":
        continue
    text = read(
        path
    )
    if all(
        token in text
        for token in (
            "prepare_import_source(",
            "validate_rows(",
            "execute_import(",
        )
    ):
        alternate_orchestrators.append(
            path.name
        )

check(
    "no Product Import god-worker is hidden under another application filename",
    not alternate_orchestrators
    and (
        worker.count(
            "\n"
        )
        + 1
    )
    <= 230,
)
check(
    "large API adapter does not own Product Import ORM row/business authority",
    "ProductImportRow"
    not in router
    and "CANONICAL_IMPORT_FIELDS"
    not in router
    and "count_job_progress"
    not in router,
)

check(
    "architecture constitution documents final Product Import module and execution semantics",
    "17.5 PRODUCT IMPORT V1 FINAL MODULE BOUNDARY"
    in architecture
    and "SourceStore"
    in architecture
    and "Permission revocation after queueing"
    in architecture,
)
check(
    "canonical runbook documents operations recovery and release verification",
    "Product Import V1 Operational Runbook"
    in runbook
    and "run_product_import_worker.ps1"
    in runbook
    and "Recovery"
    in runbook
    and "Release verification"
    in runbook,
)
check(
    "worker launcher targets the module-local queue app and product-import queue",
    "domains.simple_products.imports.infrastructure.queue.app"
    in launcher
    and "-q product-import"
    in launcher
    and "product_import_queue"
    not in launcher,
)
check(
    "Product Import module documentation describes final authority boundary",
    "Product Import V1"
    in module_docs
    and "does not own Product, Pricing"
    in module_docs
    and "scripts/run_product_import_worker.ps1"
    in module_docs,
)

check(
    "no forbidden ON CONFLICT DO NOTHING exists in Product Import runtime",
    "ON CONFLICT DO NOTHING"
    not in "\n".join(
        read(path)
        for path in IMPORTS.rglob(
            "*.py"
        )
        if "__pycache__"
        not in path.parts
    ).upper(),
)

phase17_start = plan.index(
    "# Phase 17 "
)
phase18_start = plan.index(
    "# Phase 18 "
)
phase17 = plan[
    phase17_start:
    phase18_start
]
phase18 = plan[
    phase18_start:
]
acceptance = plan[
    :phase17_start
]
check(
    "all pre-final acceptance checklist items are closed",
    "- [ ]"
    not in acceptance,
)
check(
    "all Phase 17 items are closed",
    "- [ ]"
    not in phase17,
)
check(
    "all Phase 18 items are closed",
    "- [ ]"
    not in phase18.split(
        "# Explicit decisions locked by this plan",
        1,
    )[0],
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
        "PRODUCT_IMPORT_PHASE18_CLEANUP_GATE=FAIL"
    )
    raise SystemExit(1)

print(
    "PRODUCT_IMPORT_PHASE18_CLEANUP_GATE=PASS"
)
print(
    "Product Import V1 backend is production-hardened"
)
