from __future__ import annotations

import subprocess
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parent.parent

GATES = (
    "scripts/gate_product_tracking_authority.py",
    "scripts/gate_product_import_tracking.py",
    "scripts/gate_stage7_simple_products.py",
    "scripts/gate_product_tracking_runtime.py",
)


def main() -> int:
    failures: list[str] = []

    for relative_path in GATES:
        gate_path = BACKEND / relative_path
        print()
        print(f"=== RUN {relative_path} ===")
        result = subprocess.run(
            [sys.executable, str(gate_path)],
            cwd=BACKEND,
            check=False,
        )
        if result.returncode != 0:
            failures.append(relative_path)

    print()
    print(f"CHECKS={len(GATES)}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAILED_GATE={failure}")

    if failures:
        print(
            "PRODUCT_TRACKING_PRODUCTION_GATE=FAIL"
        )
        return 1

    print(
        "PRODUCT_TRACKING_PRODUCTION_GATE=PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
