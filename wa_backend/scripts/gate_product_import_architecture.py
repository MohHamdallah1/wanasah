from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
IMPORTS = (
    BACKEND
    / "domains"
    / "simple_products"
    / "imports"
)
INFRASTRUCTURE = IMPORTS / "infrastructure"
APPLICATION_WORKER = (
    IMPORTS
    / "application"
    / "worker.py"
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


def python_files(
    directory: Path,
) -> list[Path]:
    return sorted(
        path
        for path in directory.rglob(
            "*.py"
        )
        if "__pycache__"
        not in path.parts
    )


root_business_files = sorted(
    path.name
    for path in BACKEND.glob(
        "product_import_*.py"
    )
)
check(
    not root_business_files,
    "No Product Import business files remain loose in backend root",
    ", ".join(root_business_files),
)

repo_root_business_files = sorted(
    path.name
    for path in ROOT.glob(
        "product_import_*.py"
    )
)
check(
    not repo_root_business_files,
    "No Product Import executable business files remain in repository root",
    ", ".join(
        repo_root_business_files
    ),
)


forbidden_infrastructure_symbols = {
    "SimpleProductSpec",
    "create_products_and_prices",
    "resolve_price_pair",
    "update_prices",
    "current_prices",
    "publish_prices",
    "create_family",
    "rename_family",
    "delete_family",
}

forbidden_infrastructure_modules = {
    "domains.pricing.core",
    "domains.simple_products.service",
}

authority_violations: list[str] = []
for path in python_files(
    INFRASTRUCTURE
):
    tree = ast.parse(
        path.read_text(
            encoding="utf-8"
        ),
        filename=str(path),
    )
    for node in ast.walk(tree):
        if isinstance(
            node,
            ast.ImportFrom,
        ):
            module = (
                node.module or ""
            )
            imported = {
                alias.name
                for alias in node.names
            }
            if (
                module
                in forbidden_infrastructure_modules
            ):
                authority_violations.append(
                    f"{path.name}: imports {module}"
                )
            overlap = (
                imported
                & forbidden_infrastructure_symbols
            )
            if overlap:
                authority_violations.append(
                    f"{path.name}: imports "
                    + ", ".join(
                        sorted(overlap)
                    )
                )

        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ) and (
            node.name
            in forbidden_infrastructure_symbols
        ):
            authority_violations.append(
                f"{path.name}: defines {node.name}"
            )

check(
    not authority_violations,
    "Product Import infrastructure does not own Product/Pricing business authority",
    "; ".join(
        authority_violations
    ),
)


application_source = (
    APPLICATION_WORKER.read_text(
        encoding="utf-8"
    )
)
check(
    "from sqlalchemy" not in application_source
    and "from models import" not in application_source,
    "Product Import application worker reaches persistence through repository boundary",
)

repository_source = (
    INFRASTRUCTURE
    / "repository.py"
).read_text(
    encoding="utf-8"
)
check(
    "ProductImportJob" in repository_source
    and "ProductImportRow"
    in repository_source
    and "open_tenant_session"
    in repository_source,
    "Import repository owns job/row persistence and tenant-scoped session boundary",
)


required_phase2_services = (
    IMPORTS
    / "application"
    / "state_machine.py",
    IMPORTS
    / "application"
    / "staging_service.py",
    IMPORTS
    / "application"
    / "validation_service.py",
    IMPORTS
    / "application"
    / "execution_service.py",
    IMPORTS
    / "domain"
    / "normalization.py",
    IMPORTS
    / "domain"
    / "errors.py",
    INFRASTRUCTURE
    / "parsers.py",
    INFRASTRUCTURE
    / "repository.py",
)
missing_services = [
    str(
        path.relative_to(
            BACKEND
        )
    )
    for path in required_phase2_services
    if not path.is_file()
]
check(
    not missing_services,
    "Product Import responsibilities remain split into dedicated Phase 2 services",
    ", ".join(
        missing_services
    ),
)


worker_lines = (
    application_source.count("\n")
    + 1
)
check(
    worker_lines <= 230,
    "Product Import worker stays a thin orchestrator",
    f"lines={worker_lines}, limit=230",
)

worker_tree = ast.parse(
    application_source,
    filename=str(
        APPLICATION_WORKER
    ),
)
worker_functions = [
    node
    for node in worker_tree.body
    if isinstance(
        node,
        (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
        ),
    )
]
oversized_worker_functions = [
    (
        node.name,
        (
            int(
                node.end_lineno
                or node.lineno
            )
            - int(node.lineno)
            + 1
        ),
    )
    for node in worker_functions
    if (
        int(
            node.end_lineno
            or node.lineno
        )
        - int(node.lineno)
        + 1
    )
    > 120
]
check(
    not oversized_worker_functions,
    "Product Import worker has no oversized orchestration function",
    ", ".join(
        f"{name}={size}"
        for name, size
        in oversized_worker_functions
    ),
)

worker_forbidden_tokens = {
    "InventoryAccess(",
    "SimpleProductSpec(",
    "create_products_and_prices(",
    "normalize_raw_row(",
    "find_active_barcodes(",
    "list_job_rows(",
    "ProductImportRow",
    "transition_row(",
}
worker_responsibility_leaks = sorted(
    token
    for token
    in worker_forbidden_tokens
    if token in application_source
)
check(
    not worker_responsibility_leaks,
    "Thin Product Import worker does not absorb validation/execution/persistence responsibilities",
    ", ".join(
        worker_responsibility_leaks
    ),
)


application_files = python_files(
    IMPORTS / "application"
)
alternate_orchestrators: list[str] = []
for path in application_files:
    if path == APPLICATION_WORKER:
        continue
    source_text = path.read_text(
        encoding="utf-8"
    )
    if all(
        token in source_text
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
    not alternate_orchestrators,
    "No Product Import god-worker was recreated under another application filename",
    ", ".join(
        alternate_orchestrators
    ),
)

source_service_source = (
    IMPORTS
    / "application"
    / "source_service.py"
).read_text(
    encoding="utf-8"
)
application_init_source = (
    IMPORTS
    / "application"
    / "__init__.py"
).read_text(
    encoding="utf-8"
)
check(
    "legacy_payload"
    not in source_service_source
    and "job.source_payload\n"
    not in source_service_source
    and "job.source_payload is not None"
    not in source_service_source,
    "Runtime source execution has no legacy inline-payload fallback",
)
check(
    "mark_import_runtime_failure"
    not in application_init_source,
    "Migration-era Product Import application alias is removed",
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
        "PRODUCT_IMPORT_ARCHITECTURE_GATE=FAIL"
    )
    raise SystemExit(1)

print(
    f"CHECKS={checks}"
)
print("FAILURES=0")
print(
    "PRODUCT_IMPORT_ARCHITECTURE_GATE=PASS"
)
