from __future__ import annotations

import ast
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


BASELINE_COMMIT = "6f437e7606210bb6328dc97da7f275ee52f5146a"
WAREHOUSE_REPO_PATH = "wa_backend/api/warehouse.py"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
PACKAGE_DIR = BACKEND_ROOT / "api" / "warehouse"
MANIFEST_PATH = Path(__file__).with_name("warehouse_route_manifest_baseline.json")

MODULE_ORDER = (
    "locations",
    "inbound",
    "live_stock",
    "ledger",
    "status",
    "inbound_adjustments",
    "transfer_policy",
    "transfers",
    "stocktake",
)
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _fail(message: str) -> None:
    print(f"WAREHOUSE_ROUTE_MANIFEST=FAIL: {message}")
    raise SystemExit(1)


def _git_show_text(commit: str, repo_path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{commit}:{repo_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    if result.returncode != 0:
        _fail(
            f"cannot read baseline {commit}:{repo_path}: "
            f"{result.stderr.strip()}"
        )
    return result.stdout


def _expr_text(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    return ast.unparse(node)


def _route_decorator(call: ast.AST) -> tuple[str, ast.Call] | None:
    if not isinstance(call, ast.Call):
        return None
    func = call.func
    if (
        not isinstance(func, ast.Attribute)
        or not isinstance(func.value, ast.Name)
        or func.value.id != "router"
        or func.attr not in HTTP_METHODS
    ):
        return None
    return func.attr.upper(), call


def _parse_routes(source: str, module_name: str) -> list[dict[str, Any]]:
    tree = ast.parse(source)
    routes: list[dict[str, Any]] = []

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        decorators: list[tuple[str, ast.Call]] = []
        for decorator in node.decorator_list:
            parsed = _route_decorator(decorator)
            if parsed is not None:
                decorators.append(parsed)

        # Python applies stacked decorators bottom-up. APIRouter therefore
        # registers the bottom decorator first.
        for method, call in reversed(decorators):
            if not call.args:
                _fail(
                    f"{module_name}.{node.name} has a route decorator "
                    "without a positional path"
                )

            path_node = call.args[0]
            if not (
                isinstance(path_node, ast.Constant)
                and isinstance(path_node.value, str)
            ):
                _fail(
                    f"{module_name}.{node.name} has a non-literal route path"
                )

            keyword_map = {
                keyword.arg: keyword.value
                for keyword in call.keywords
                if keyword.arg is not None
            }

            routes.append(
                {
                    "method": method,
                    "path": path_node.value,
                    "function": node.name,
                    "status_code": _expr_text(keyword_map.get("status_code")),
                    "response_model": _expr_text(
                        keyword_map.get("response_model")
                    ),
                    "module": module_name,
                    "source_line": int(call.lineno),
                    # Structural fingerprint of the complete decorator call.
                    # This catches future metadata drift beyond the readable
                    # fields above.
                    "decorator_ast": ast.dump(
                        call,
                        annotate_fields=True,
                        include_attributes=False,
                    ),
                }
            )

    return routes


def _readable_baseline_route(
    route: dict[str, Any],
    *,
    order: int,
) -> dict[str, Any]:
    return {
        "order": order,
        "method": route["method"],
        "path": route["path"],
        "function": route["function"],
        "status_code": route["status_code"],
        "response_model": route["response_model"],
        "baseline_line": route["source_line"],
    }


def _core_signature(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "method": route["method"],
        "path": route["path"],
        "function": route["function"],
        "status_code": route["status_code"],
        "response_model": route["response_model"],
        "decorator_ast": route["decorator_ast"],
    }


def _duplicate_route_keys(
    routes: list[dict[str, Any]],
) -> list[str]:
    counts = Counter(
        (route["method"], route["path"])
        for route in routes
    )
    return [
        f"{method} {path}"
        for (method, path), count in counts.items()
        if count > 1
    ]


def main() -> None:
    if not MANIFEST_PATH.is_file():
        _fail(f"missing baseline manifest: {MANIFEST_PATH}")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    if manifest.get("baseline_commit") != BASELINE_COMMIT:
        _fail("manifest baseline_commit does not match the locked baseline")
    if manifest.get("baseline_path") != WAREHOUSE_REPO_PATH:
        _fail("manifest baseline_path does not match the locked warehouse path")
    if tuple(manifest.get("module_include_order", ())) != MODULE_ORDER:
        _fail("manifest module_include_order changed")

    baseline_source = _git_show_text(
        BASELINE_COMMIT,
        WAREHOUSE_REPO_PATH,
    )
    baseline_routes = _parse_routes(
        baseline_source,
        "warehouse.py",
    )

    expected_count = int(manifest.get("route_count", -1))
    if expected_count != len(baseline_routes):
        _fail(
            "manifest route_count does not match baseline: "
            f"manifest={expected_count}, baseline={len(baseline_routes)}"
        )

    manifest_routes = manifest.get("routes")
    if not isinstance(manifest_routes, list):
        _fail("manifest routes must be a list")
    if len(manifest_routes) != len(baseline_routes):
        _fail(
            "manifest route list count does not match baseline: "
            f"manifest={len(manifest_routes)}, "
            f"baseline={len(baseline_routes)}"
        )

    baseline_readable = [
        _readable_baseline_route(route, order=index)
        for index, route in enumerate(baseline_routes, start=1)
    ]
    manifest_readable = [
        {
            "order": route.get("order"),
            "method": route.get("method"),
            "path": route.get("path"),
            "function": route.get("function"),
            "status_code": route.get("status_code"),
            "response_model": route.get("response_model"),
            "baseline_line": route.get("baseline_line"),
        }
        for route in manifest_routes
    ]

    if manifest_readable != baseline_readable:
        _fail("checked-in readable manifest drifted from locked baseline")

    baseline_duplicates = _duplicate_route_keys(baseline_routes)
    if baseline_duplicates:
        _fail(
            "locked baseline contains duplicate method+path routes: "
            + ", ".join(baseline_duplicates)
        )

    package_routes: list[dict[str, Any]] = []
    for module_name in MODULE_ORDER:
        module_path = PACKAGE_DIR / f"{module_name}.py"
        if not module_path.is_file():
            _fail(f"missing staged warehouse module: {module_path}")
        package_routes.extend(
            _parse_routes(
                module_path.read_text(encoding="utf-8"),
                module_name,
            )
        )

    if len(package_routes) != len(baseline_routes):
        _fail(
            "route count mismatch: "
            f"baseline={len(baseline_routes)}, "
            f"package={len(package_routes)}"
        )

    package_duplicates = _duplicate_route_keys(package_routes)
    if package_duplicates:
        _fail(
            "package contains duplicate method+path routes: "
            + ", ".join(package_duplicates)
        )

    for index, (baseline_route, package_route, manifest_route) in enumerate(
        zip(baseline_routes, package_routes, manifest_routes),
        start=1,
    ):
        if _core_signature(package_route) != _core_signature(baseline_route):
            _fail(
                f"route #{index} differs from baseline: "
                f"baseline={baseline_route['method']} "
                f"{baseline_route['path']} "
                f"({baseline_route['function']}), "
                f"package={package_route['method']} "
                f"{package_route['path']} "
                f"({package_route['function']})"
            )

        expected_module = manifest_route.get("expected_module")
        if package_route["module"] != expected_module:
            _fail(
                f"route #{index} moved to unexpected module: "
                f"expected={expected_module}, "
                f"actual={package_route['module']}"
            )

    print(
        "WAREHOUSE_ROUTE_MANIFEST=PASS "
        f"(baseline={len(baseline_routes)}; "
        f"package={len(package_routes)}; "
        "exact_runtime_order=True; duplicates=0)"
    )


if __name__ == "__main__":
    main()
