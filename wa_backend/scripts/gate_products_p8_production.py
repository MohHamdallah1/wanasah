from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "wa_backend"
DASHBOARD = REPO_ROOT / "dashboard"

BACKEND_GATES = (
    "scripts/gate_error_contract_runtime.py",
    "scripts/gate_stage73_product_ux_i18n_network.py",
    "scripts/gate_products_read_contract_p2.py",
    "scripts/gate_products_search_families_p4.py",
    "scripts/gate_products_p5_uom_safety.py",
    "scripts/gate_products_p6_import_localization.py",
    "scripts/gate_product_tracking_production.py",
    "scripts/gate_stage3_lifecycle.py",
    "scripts/gate_products_p8_performance.py",
    "scripts/gate_products_p8_price_publication_scale.py",
    "scripts/gate_products_p8_isolation.py",
    "scripts/gate_products_p8_concurrency_idempotency.py",
    "scripts/gate_products_p8_existing_products.py",
)


def run_step(
    *,
    label: str,
    command: list[str],
    cwd: Path,
) -> bool:
    print()
    print("=" * 72)
    print(f"RUN {label}")
    print("=" * 72)
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
    )
    ok = result.returncode == 0
    print(
        f"{label}="
        + ("PASS" if ok else "FAIL")
        + f" returncode={result.returncode}"
    )
    return ok


def main() -> int:
    failures: list[str] = []

    npm = shutil.which("npm")
    if npm is None:
        print("DASHBOARD_TOOLCHAIN=FAIL npm_not_found")
        failures.append("dashboard:npm")
    else:
        frontend_steps = (
            (
                "dashboard:typescript",
                [
                    npm,
                    "exec",
                    "tsc",
                    "--",
                    "--noEmit",
                ],
            ),
            (
                "dashboard:tests",
                [npm, "test"],
            ),
            (
                "dashboard:lint",
                [
                    npm,
                    "run",
                    "lint",
                    "--",
                    "--max-warnings=0",
                ],
            ),
            (
                "dashboard:build",
                [npm, "run", "build"],
            ),
        )
        for label, command in frontend_steps:
            if not run_step(
                label=label,
                command=command,
                cwd=DASHBOARD,
            ):
                failures.append(label)

    for relative_path in BACKEND_GATES:
        label = "backend:" + relative_path.removeprefix(
            "scripts/"
        ).removesuffix(".py")
        if not run_step(
            label=label,
            command=[
                sys.executable,
                "-W",
                "error::DeprecationWarning",
                str(
                    BACKEND
                    / relative_path
                ),
            ],
            cwd=BACKEND,
        ):
            failures.append(label)

    total = (
        4
        + len(BACKEND_GATES)
    )
    print()
    print("=" * 72)
    print("P8 PRODUCTION GATE SUMMARY")
    print("=" * 72)
    print(f"CHECKS={total}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(
            f"FAILED_GATE={failure}"
        )

    if failures:
        print(
            "PRODUCTS_P8_PRODUCTION_GATE=FAIL"
        )
        return 1

    print(
        "PRODUCTS_P8_PRODUCTION_GATE=PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
