from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts import gate_stage821_projector_stress as stress


LEVELS = (8, 12, 16, 20, 24, 32, 40, 48, 64)
OPS = 128


async def main(company_id: int, location_id: int) -> None:
    rows = await stress.load_hot_rows(company_id, location_id, 1000)
    if len(rows) < OPS + 10:
        raise RuntimeError("Not enough hot rows for concurrency diagnosis.")

    impact_metadata = await stress.load_balance_impact_metadata(
        company_id,
        [balance_id for _variant_id, balance_id, _qty in rows],
    )
    noise_samples = await stress.load_noise_keys(OPS)
    if len(noise_samples) < OPS:
        raise RuntimeError("Not enough noise-company samples for diagnosis.")

    print(
        "LEVEL | MUT_P95 | MUT_TPS | XT_P95 | XT_TPS | "
        "MUT_ERRORS | XT_ERRORS"
    )

    candidates: list[tuple[int, float, float, float, float]] = []
    try:
        for level in LEVELS:
            mutation_rows = rows[:OPS]
            originals = {
                balance_id: (variant_id, original)
                for variant_id, balance_id, original in mutation_rows
            }
            try:
                mutation, mutation_tps, mutation_errors, _ = (
                    await stress.timed_mutation_pressure(
                        company_id=company_id,
                        location_id=location_id,
                        rows=mutation_rows,
                        impact_metadata=impact_metadata,
                        concurrency=level,
                        operations=OPS,
                    )
                )
            finally:
                await stress.restore_balances(
                    company_id=company_id,
                    location_id=location_id,
                    originals=originals,
                )

            cross, cross_tps, cross_errors = (
                await stress.timed_cross_tenant_refreshes(
                    samples=noise_samples,
                    concurrency=level,
                    operations=OPS,
                )
            )

            print(
                f"{level:>5} | "
                f"{mutation.p95:>7.1f} | "
                f"{mutation_tps:>7.1f} | "
                f"{cross.p95:>6.1f} | "
                f"{cross_tps:>6.1f} | "
                f"{len(mutation_errors):>10} | "
                f"{len(cross_errors):>9}"
            )
            if not mutation_errors and not cross_errors:
                candidates.append(
                    (
                        level,
                        mutation.p95,
                        mutation_tps,
                        cross.p95,
                        cross_tps,
                    )
                )

        strict = [
            row
            for row in candidates
            if row[1] <= 1200.0
            and row[3] <= 900.0
            and row[2] >= 35.0
            and row[4] >= 60.0
        ]
        if strict:
            best = max(
                strict,
                key=lambda row: (min(row[2] / 35.0, row[4] / 60.0), -row[0]),
            )
            print(
                "STRICT_CAP_CANDIDATE="
                f"{best[0]} "
                f"mutation_p95={best[1]:.1f}ms "
                f"mutation_tps={best[2]:.1f}/s "
                f"cross_tenant_p95={best[3]:.1f}ms "
                f"cross_tenant_tps={best[4]:.1f}/s"
            )
        else:
            print("STRICT_CAP_CANDIDATE=NONE")
    finally:
        await stress.engine_app.dispose()
        await stress.engine_su.dispose()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--location-id", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.company_id, args.location_id))
