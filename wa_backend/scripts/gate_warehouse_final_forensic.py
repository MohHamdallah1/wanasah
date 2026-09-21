from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
WAREHOUSE_PACKAGE = BACKEND_ROOT / "api" / "warehouse"
LEGACY_MONOLITH = BACKEND_ROOT / "api" / "warehouse.py"

EXPECTED_PACKAGE_FILES = {
    "__init__.py",
    "_shared.py",
    "locations.py",
    "inbound.py",
    "live_stock.py",
    "ledger.py",
    "status.py",
    "inbound_adjustments.py",
    "transfer_policy.py",
    "transfers.py",
    "stocktake.py",
}

# These files intentionally name the historical monolith because they compare
# the split against a locked pre-cutover baseline. No runtime code may do so.
HISTORICAL_MONOLITH_REFERENCE_ALLOWLIST = {
    "scripts/gate_live_stock_phase11.py",
    "scripts/gate_warehouse_route_manifest.py",
    "scripts/gate_warehouse_split_integrity.py",
}


def fail(message: str) -> None:
    print(f"WAREHOUSE_FINAL_FORENSIC=FAIL: {message}")
    raise SystemExit(1)


def relative_backend(path: Path) -> str:
    return path.relative_to(BACKEND_ROOT).as_posix()


def verify_package_shape() -> None:
    if LEGACY_MONOLITH.exists():
        fail(f"legacy monolith exists: {LEGACY_MONOLITH}")

    if not WAREHOUSE_PACKAGE.is_dir():
        fail(f"warehouse package missing: {WAREHOUSE_PACKAGE}")

    actual = {
        path.name
        for path in WAREHOUSE_PACKAGE.iterdir()
        if path.is_file() and path.suffix == ".py"
    }
    if actual != EXPECTED_PACKAGE_FILES:
        missing = sorted(EXPECTED_PACKAGE_FILES - actual)
        unexpected = sorted(actual - EXPECTED_PACKAGE_FILES)
        fail(
            "warehouse package file set drifted: "
            f"missing={missing}, unexpected={unexpected}"
        )


def verify_python_sources() -> None:
    stale_imports: list[str] = []
    syntax_errors: list[str] = []
    historical_refs: list[str] = []

    legacy_repo_path = "/".join(("wa_backend", "api", "warehouse.py"))

    for path in sorted(BACKEND_ROOT.rglob("*.py")):
        rel = relative_backend(path)
        source = path.read_text(encoding="utf-8")

        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            syntax_errors.append(
                f"{rel}:{exc.lineno}:{exc.offset}:{exc.msg}"
            )
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "api.warehouse":
                imported = ",".join(alias.name for alias in node.names)
                stale_imports.append(
                    f"{rel}:{node.lineno}:from api.warehouse import {imported}"
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "api.warehouse":
                        rendered = (
                            f" as {alias.asname}" if alias.asname else ""
                        )
                        stale_imports.append(
                            f"{rel}:{node.lineno}:import api.warehouse{rendered}"
                        )

        if legacy_repo_path in source:
            historical_refs.append(rel)

    if syntax_errors:
        fail("Python syntax errors: " + " | ".join(syntax_errors))

    if stale_imports:
        fail(
            "stale exact api.warehouse imports remain: "
            + " | ".join(stale_imports)
        )

    unexpected_refs = sorted(
        set(historical_refs) - HISTORICAL_MONOLITH_REFERENCE_ALLOWLIST
    )
    missing_refs = sorted(
        HISTORICAL_MONOLITH_REFERENCE_ALLOWLIST - set(historical_refs)
    )
    if unexpected_refs or missing_refs:
        fail(
            "historical monolith reference set drifted: "
            f"unexpected={unexpected_refs}, missing={missing_refs}"
        )


def run_gate(script_name: str, *extra_args: str) -> None:
    script = BACKEND_ROOT / "scripts" / script_name
    if not script.is_file():
        fail(f"required gate missing: {script}")

    completed = subprocess.run(
        [sys.executable, str(script), *extra_args],
        cwd=BACKEND_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr)
    if completed.returncode != 0:
        fail(
            f"{script_name} failed with exit code {completed.returncode}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Final forensic gate for the warehouse.py -> api/warehouse package "
            "cutover. It verifies package shape, scans the backend for stale "
            "monolith imports/references, and reruns the locked split gates."
        )
    )
    parser.add_argument(
        "--with-lifespan",
        action="store_true",
        help="Also enter the FastAPI lifespan through the runtime cutover gate.",
    )
    args = parser.parse_args()

    verify_package_shape()
    verify_python_sources()

    run_gate("gate_warehouse_split_integrity.py")
    run_gate("gate_warehouse_route_manifest.py")
    run_gate(
        "gate_warehouse_runtime_cutover.py",
        *(("--with-lifespan",) if args.with_lifespan else ()),
    )

    print(
        "WAREHOUSE_FINAL_FORENSIC=PASS "
        "(package_files=11; stale_imports=0; "
        "historical_refs=3; split_gates=3)"
    )


if __name__ == "__main__":
    main()
