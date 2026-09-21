from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.util
import json
import selectors
import sys
from collections import Counter
from pathlib import Path
from typing import Any, get_args, get_origin


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = BACKEND_ROOT / "api" / "warehouse"
MONOLITH_PATH = BACKEND_ROOT / "api" / "warehouse.py"
MANIFEST_PATH = Path(__file__).with_name("warehouse_route_manifest_baseline.json")
EXPECTED_TAG = "Warehouse & Inventory"


def _fail(message: str) -> None:
    print(f"WAREHOUSE_RUNTIME_CUTOVER=FAIL: {message}")
    raise SystemExit(1)


def _response_model_name(model: Any) -> str | None:
    if model is None:
        return None

    origin = get_origin(model)
    if origin is list:
        args = get_args(model)
        if len(args) == 1:
            item = args[0]
            item_name = getattr(item, "__name__", str(item))
            return f"List[{item_name}]"

    name = getattr(model, "__name__", None)
    if isinstance(name, str):
        return name

    return str(model)


def _route_method(route: Any) -> str:
    methods = sorted(
        method
        for method in getattr(route, "methods", set())
        if method not in {"HEAD", "OPTIONS"}
    )
    if len(methods) != 1:
        _fail(
            f"route {getattr(route, 'path', '<unknown>')} "
            f"has unexpected methods={methods}"
        )
    return methods[0]


def _runtime_signature(route: Any) -> dict[str, Any]:
    endpoint = getattr(route, "endpoint", None)
    return {
        "method": _route_method(route),
        "path": getattr(route, "path", None),
        "function": getattr(endpoint, "__name__", None),
        "status_code": (
            str(route.status_code)
            if getattr(route, "status_code", None) is not None
            else None
        ),
        "response_model": _response_model_name(
            getattr(route, "response_model", None)
        ),
        "endpoint_module": getattr(endpoint, "__module__", None),
    }


def _expected_signature(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "method": route["method"],
        "path": route["path"],
        "function": route["function"],
        "status_code": route["status_code"],
        "response_model": route["response_model"],
    }


def _duplicates(routes: list[Any]) -> list[str]:
    counts = Counter(
        (_route_method(route), getattr(route, "path", None))
        for route in routes
    )
    return [
        f"{method} {path}"
        for (method, path), count in counts.items()
        if count > 1
    ]


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        _fail(f"missing manifest: {MANIFEST_PATH}")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    routes = manifest.get("routes")
    if not isinstance(routes, list):
        _fail("manifest routes must be a list")

    expected_count = int(manifest.get("route_count", -1))
    if expected_count != len(routes):
        _fail(
            "manifest route_count mismatch: "
            f"route_count={expected_count}, routes={len(routes)}"
        )
    return manifest


def _verify_cutover_filesystem() -> None:
    if MONOLITH_PATH.exists():
        _fail(f"legacy monolith still exists: {MONOLITH_PATH}")

    package_init = PACKAGE_DIR / "__init__.py"
    if not package_init.is_file():
        _fail(f"warehouse package init missing: {package_init}")


def _verify_import_resolution() -> Any:
    spec = importlib.util.find_spec("api.warehouse")
    if spec is None:
        _fail("importlib cannot resolve api.warehouse")

    expected_init = (PACKAGE_DIR / "__init__.py").resolve()
    origin = Path(spec.origin).resolve() if spec.origin else None
    if origin != expected_init:
        _fail(
            "api.warehouse resolves to unexpected origin: "
            f"expected={expected_init}, actual={origin}"
        )

    if spec.submodule_search_locations is None:
        _fail("api.warehouse resolved as a module, not a package")

    warehouse = importlib.import_module("api.warehouse")
    module_file = Path(warehouse.__file__).resolve()
    if module_file != expected_init:
        _fail(
            "imported api.warehouse has unexpected __file__: "
            f"expected={expected_init}, actual={module_file}"
        )

    router = getattr(warehouse, "router", None)
    if router is None:
        _fail("api.warehouse does not expose router")

    return warehouse


def _verify_package_router(
    warehouse: Any,
    manifest: dict[str, Any],
) -> list[Any]:
    expected = manifest["routes"]
    routes = list(getattr(warehouse.router, "routes", ()))

    if len(routes) != len(expected):
        _fail(
            "package router count mismatch: "
            f"expected={len(expected)}, actual={len(routes)}"
        )

    duplicates = _duplicates(routes)
    if duplicates:
        _fail(
            "package router contains duplicate method+path routes: "
            + ", ".join(duplicates)
        )

    for index, (route, expected_route) in enumerate(
        zip(routes, expected),
        start=1,
    ):
        actual = _runtime_signature(route)
        wanted = _expected_signature(expected_route)

        actual_core = {
            key: actual[key]
            for key in wanted
        }
        if actual_core != wanted:
            _fail(
                f"package runtime route #{index} mismatch: "
                f"expected={wanted}, actual={actual_core}"
            )

        expected_module = (
            f"api.warehouse.{expected_route['expected_module']}"
        )
        if actual["endpoint_module"] != expected_module:
            _fail(
                f"package runtime route #{index} endpoint module mismatch: "
                f"expected={expected_module}, "
                f"actual={actual['endpoint_module']}"
            )

    return routes


def _verify_main_app(
    warehouse: Any,
    package_routes: list[Any],
    manifest: dict[str, Any],
) -> Any:
    main = importlib.import_module("main")

    if getattr(main, "warehouse", None) is not warehouse:
        _fail(
            "main.warehouse is not the imported api.warehouse package object"
        )

    app = getattr(main, "app", None)
    if app is None:
        _fail("main.app is missing")

    warehouse_routes = [
        route
        for route in getattr(app, "routes", ())
        if (
            getattr(getattr(route, "endpoint", None), "__module__", "")
            .startswith("api.warehouse.")
        )
    ]

    expected = manifest["routes"]
    if len(warehouse_routes) != len(expected):
        _fail(
            "main app warehouse route count mismatch: "
            f"expected={len(expected)}, actual={len(warehouse_routes)}"
        )

    duplicates = _duplicates(warehouse_routes)
    if duplicates:
        _fail(
            "main app contains duplicate package warehouse routes: "
            + ", ".join(duplicates)
        )

    package_endpoint_ids = [
        id(getattr(route, "endpoint", None))
        for route in package_routes
    ]
    app_endpoint_ids = [
        id(getattr(route, "endpoint", None))
        for route in warehouse_routes
    ]
    if package_endpoint_ids != app_endpoint_ids:
        _fail(
            "main app warehouse endpoint order/identity differs "
            "from api.warehouse.router"
        )

    for index, (route, expected_route) in enumerate(
        zip(warehouse_routes, expected),
        start=1,
    ):
        actual = _runtime_signature(route)
        wanted = _expected_signature(expected_route)
        actual_core = {
            key: actual[key]
            for key in wanted
        }

        if actual_core != wanted:
            _fail(
                f"main runtime route #{index} mismatch: "
                f"expected={wanted}, actual={actual_core}"
            )

        tags = list(getattr(route, "tags", ()) or ())
        if EXPECTED_TAG not in tags:
            _fail(
                f"main runtime route #{index} is missing tag "
                f"{EXPECTED_TAG!r}: tags={tags}"
            )

    return app


async def _verify_lifespan(app: Any) -> None:
    lifespan_context = getattr(app.router, "lifespan_context", None)
    if lifespan_context is None:
        _fail("main.app router has no lifespan_context")

    async with lifespan_context(app):
        print(
            "WAREHOUSE_RUNTIME_LIFESPAN=PASS "
            "(FastAPI lifespan entered successfully)"
        )


def _run_lifespan(app: Any) -> None:
    if sys.platform == "win32":
        # psycopg async connections are incompatible with the default
        # ProactorEventLoop on Windows. Keep this compatibility override
        # isolated to the optional lifespan gate instead of mutating the
        # application's global event-loop policy.
        def _windows_selector_loop() -> asyncio.AbstractEventLoop:
            return asyncio.SelectorEventLoop(selectors.SelectSelector())

        with asyncio.Runner(loop_factory=_windows_selector_loop) as runner:
            runner.run(_verify_lifespan(app))
        return

    asyncio.run(_verify_lifespan(app))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the final warehouse package cutover at runtime. "
            "Use --with-lifespan only when PostgreSQL/queue dependencies "
            "required by main.py startup are available."
        )
    )
    parser.add_argument(
        "--with-lifespan",
        action="store_true",
        help=(
            "Enter main.app lifespan. This warms the DB pool and starts "
            "the worker event relay/queue connector."
        ),
    )
    args = parser.parse_args()

    # Ensure imports resolve from wa_backend even when the gate is launched
    # from another working directory.
    backend_text = str(BACKEND_ROOT)
    if backend_text not in sys.path:
        sys.path.insert(0, backend_text)

    manifest = _load_manifest()
    _verify_cutover_filesystem()
    warehouse = _verify_import_resolution()
    package_routes = _verify_package_router(warehouse, manifest)
    app = _verify_main_app(warehouse, package_routes, manifest)

    print(
        "WAREHOUSE_RUNTIME_CUTOVER=PASS "
        f"(package_origin={Path(warehouse.__file__).resolve()}; "
        f"package_routes={len(package_routes)}; "
        f"main_routes={len(manifest['routes'])}; "
        "exact_runtime_order=True; duplicates=0)"
    )

    if args.with_lifespan:
        _run_lifespan(app)


if __name__ == "__main__":
    main()
