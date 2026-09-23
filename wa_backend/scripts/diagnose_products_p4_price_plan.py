from __future__ import annotations

import asyncio
import os
from time import perf_counter
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

import audit_products_p4_performance as perf
import gate_products_read_contract_p2 as p2_gate
from models import Driver


DIAGNOSTIC_TIMEOUT = "5s"


async def run_mode(
    app,
    actor: Driver,
    *,
    mode: str,
    runs: int,
) -> tuple[list[float], bool, str]:
    latencies: list[float] = []
    timed_out = False
    error_detail = ""

    nested = await app.begin_nested()
    try:
        await app.execute(
            text(
                f"SET LOCAL plan_cache_mode = '{mode}'"
            )
        )
        await app.execute(
            text(
                "SET LOCAL statement_timeout = "
                f"'{DIAGNOSTIC_TIMEOUT}'"
            )
        )

        kwargs = perf.endpoint_kwargs(
            has_price=True,
            limit=50,
        )

        for index in range(runs):
            started = perf_counter()
            try:
                await perf.call_endpoint(
                    app,
                    actor,
                    kwargs,
                )
            except DBAPIError as exc:
                sqlstate = getattr(
                    exc.orig,
                    "sqlstate",
                    None,
                )
                timed_out = sqlstate == "57014"
                error_detail = (
                    f"{type(exc.orig).__name__}: "
                    f"{exc.orig}"
                )
                if not timed_out:
                    raise
                print(
                    "PRICE_PLAN_DIAGNOSTIC_TIMEOUT "
                    f"mode={mode} "
                    f"run={index + 1}/{runs} "
                    f"sqlstate={sqlstate}"
                )
                break

            elapsed_ms = (
                perf_counter() - started
            ) * 1000.0
            latencies.append(elapsed_ms)
            print(
                "PRICE_PLAN_DIAGNOSTIC "
                f"mode={mode} "
                f"run={index + 1}/{runs} "
                f"latency_ms={elapsed_ms:.3f}"
            )
    finally:
        if nested.is_active:
            await nested.rollback()

    return latencies, timed_out, error_detail


async def main() -> None:
    ids: dict[str, int] = {}
    prefix = "P4PLAN" + uuid4().hex[:8].upper()
    row_count = perf.bounded_env_int(
        "P4_PERF_ROWS",
        perf.DEFAULT_ROWS,
        perf.MIN_ROWS,
        perf.MAX_ROWS,
    )

    print(
        f"PRICE_PLAN_DIAGNOSTIC_ROWS={row_count}"
    )

    try:
        ids = await p2_gate.bootstrap()
        await perf.seed_committed_catalog(
            ids,
            prefix=prefix,
            row_count=row_count,
        )
        company_id = int(ids["company_id"])

        async with p2_gate.SessionApp() as app:
            await app.begin()
            await p2_gate.set_tenant(
                app,
                company_id,
            )

            tenant_ids = (
                await p2_gate.seed_tenant_transaction(
                    app,
                    ids,
                )
            )
            ids.update(tenant_ids)

            pricing_actor = await app.get(
                Driver,
                ids["pricing_driver_id"],
            )
            if pricing_actor is None:
                raise RuntimeError(
                    "Pricing diagnostic actor is not visible."
                )

            await perf.seed_benchmark_prices(
                app,
                company_id=company_id,
                each_uom_id=int(
                    ids["each_uom_id"]
                ),
                prefix=prefix,
            )

            custom_latencies, custom_timeout, custom_error = (
                await run_mode(
                    app,
                    pricing_actor,
                    mode="force_custom_plan",
                    runs=6,
                )
            )
            generic_latencies, generic_timeout, generic_error = (
                await run_mode(
                    app,
                    pricing_actor,
                    mode="force_generic_plan",
                    runs=1,
                )
            )

            await app.rollback()

        print(
            "PRICE_PLAN_DIAGNOSTIC_RESULT "
            f"custom_runs_completed={len(custom_latencies)} "
            f"custom_timeout={custom_timeout} "
            f"custom_max_ms="
            + (
                f"{max(custom_latencies):.3f}"
                if custom_latencies
                else "-"
            )
            + " "
            f"generic_runs_completed={len(generic_latencies)} "
            f"generic_timeout={generic_timeout} "
            f"generic_latency_ms="
            + (
                f"{generic_latencies[0]:.3f}"
                if generic_latencies
                else "-"
            )
        )
        if custom_error:
            print(
                "PRICE_PLAN_CUSTOM_ERROR="
                + custom_error
            )
        if generic_error:
            print(
                "PRICE_PLAN_GENERIC_ERROR="
                + generic_error
            )

    finally:
        cleanup_ok, cleanup_detail = (
            await perf.cleanup_committed_catalog(
                ids,
                prefix=prefix,
            )
        )
        print(
            "PRICE_PLAN_DIAGNOSTIC_CLEANUP="
            + (
                "PASS"
                if cleanup_ok
                else "FAIL"
            )
            + (
                f" detail={cleanup_detail}"
                if cleanup_detail
                else ""
            )
        )
        await p2_gate.engine_app.dispose()
        await p2_gate.engine_su.dispose()


if __name__ == "__main__":
    asyncio.run(main())
