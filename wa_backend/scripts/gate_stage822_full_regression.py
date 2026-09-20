from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parent.parent
SCRIPTS = BACKEND / "scripts"


def run_gate(label: str, script: str, *args: str) -> None:
    command = [sys.executable, str(SCRIPTS / script), *args]
    print(f"\n=== {label} ===", flush=True)
    completed = subprocess.run(
        command,
        cwd=BACKEND,
        check=False,
    )
    if completed.returncode != 0:
        print(f"LIVE_STOCK_REGRESSION_FAILED_AT={label}", flush=True)
        raise SystemExit(completed.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Full Stage 8.2.1 + 8.2.2 + read-model regression suite."
    )
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--location-id", type=int, required=True)
    parser.add_argument("--driver-id", type=int)
    args = parser.parse_args()

    if args.company_id <= 0 or args.location_id <= 0:
        raise SystemExit("company-id and location-id must be positive.")

    gates = (
        (
            "stage82_foundation",
            "gate_stage82_live_stock_projection_foundation.py",
            (),
        ),
        (
            "stage821_core",
            "gate_stage821_live_stock_projector_core.py",
            (),
        ),
        (
            "stage821_runtime",
            "gate_stage821_live_stock_projector_runtime.py",
            (),
        ),
        (
            "stage822_core",
            "gate_stage822_live_stock_rebuild_core.py",
            (),
        ),
        (
            "stage822_runtime",
            "gate_stage822_live_stock_rebuild_runtime.py",
            (),
        ),
        (
            "stage823_read_model_core",
            "gate_stage823_live_stock_read_model_core.py",
            (),
        ),
        (
            "stage823_read_model_runtime",
            "gate_stage823_live_stock_read_model.py",
            (),
        ),
        (
            "stage821_stress",
            "gate_stage821_projector_stress.py",
            (
                "--company-id",
                str(args.company_id),
                "--location-id",
                str(args.location_id),
            ),
        ),
        (
            "live_stock_read_scale",
            "gate_live_stock_scale.py",
            tuple(
                [
                    "--company-id",
                    str(args.company_id),
                    "--location-id",
                    str(args.location_id),
                ]
                + (
                    ["--driver-id", str(args.driver_id)]
                    if args.driver_id is not None
                    else []
                )
            ),
        ),
    )

    for label, script, gate_args in gates:
        run_gate(label, script, *gate_args)

    print("\nLIVE_STOCK_FULL_REGRESSION_SUITE=PASS")


if __name__ == "__main__":
    main()
