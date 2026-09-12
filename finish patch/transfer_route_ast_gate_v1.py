from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WAREHOUSE = ROOT / "wa_backend" / "api" / "warehouse.py"

TARGET_PATHS = {
    "/warehouse/unified/transfer/locations",
    "/warehouse/unified/transfer/source-inventory",
    "/warehouse/unified/transfer/override-options",
    "/warehouse/unified/transfers",
    "/warehouse/unified/transfers/{transfer_id}",
    "/warehouse/unified/transfer/dispatch",
    "/warehouse/unified/transfer/receive",
    "/warehouse/unified/transfer/{header_id}/cancel",
    "/warehouse/unified/transfer/{header_id}/reject",
}

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def fail(message: str) -> None:
    raise SystemExit(f"TRANSFER_ROUTE_AST_GATE=FAIL\n{message}")


if not WAREHOUSE.exists():
    fail(f"MISSING_FILE={WAREHOUSE.relative_to(ROOT)}")

source = WAREHOUSE.read_text(encoding="utf-8")

try:
    tree = ast.parse(source, filename=str(WAREHOUSE))
except SyntaxError as exc:
    fail(f"PYTHON_SYNTAX_ERROR={exc}")

routes: dict[str, list[tuple[str, str, int]]] = defaultdict(list)

for node in ast.walk(tree):
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue

    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue

        func = decorator.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "router"
            and func.attr in HTTP_METHODS
        ):
            continue

        if not decorator.args:
            continue

        path_arg = decorator.args[0]
        if not (
            isinstance(path_arg, ast.Constant)
            and isinstance(path_arg.value, str)
        ):
            continue

        routes[path_arg.value].append(
            (func.attr.upper(), node.name, decorator.lineno)
        )

failed = False

for path in sorted(TARGET_PATHS):
    matches = routes.get(path, [])
    if not matches:
        print(f"ROUTE_MISSING={path}")
        failed = True
        continue

    method_groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for method, function_name, line_no in matches:
        method_groups[method].append((function_name, line_no))

    for method, entries in sorted(method_groups.items()):
        detail = ", ".join(
            f"{function_name}@L{line_no}"
            for function_name, line_no in entries
        )
        print(f"ROUTE_FOUND={method} {path} -> {detail}")

        if len(entries) > 1:
            print(
                f"ROUTE_DUPLICATE={method} {path} count={len(entries)}"
            )
            failed = True

if failed:
    fail("One or more transfer routes are missing or duplicated.")

print("TRANSFER_ROUTE_AST_GATE=PASS")
