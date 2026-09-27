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
