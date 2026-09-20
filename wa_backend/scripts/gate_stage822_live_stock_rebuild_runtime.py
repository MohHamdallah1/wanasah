from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts import gate_stage821_live_stock_projector_runtime as fixture
from domains.live_stock_projection.service import (
    LiveStockProjectionError,
    assert_live_stock_projection_ready,
    mark_live_stock_projection_degraded,
    rebuild_live_stock_company,
    rebuild_live_stock_warehouse,
    reconcile_live_stock_company,
    remove_live_stock_warehouse_projection,
)


RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(
        f"[{'PASS' if ok else 'FAIL'}] {name}"
        + (f" — {detail}" if detail else "")
    )


async def projection_health(
    company_id: int,
    warehouse_id: int,
) -> tuple[str | None, str | None, int, int, int]:
    async with fixture.SessionApp() as app:
        await app.begin()
        await fixture.set_tenant(app, company_id)
        row = (
            await app.execute(
                text(
                    """
                    SELECT
                        c.projection_state AS company_state,
                        w.projection_state AS warehouse_state,
                        w.projected_row_count,
                        w.alert_count,
                        w.nonactive_visible_count
                    FROM inventory_live_stock_company_summaries c
                    LEFT JOIN inventory_live_stock_warehouse_summaries w
                      ON w.company_id=c.company_id
                     AND w.warehouse_location_id=:warehouse_id
                    WHERE c.company_id=:company_id
                    """
                ),
                {
                    "company_id": company_id,
                    "warehouse_id": warehouse_id,
                },
            )
        ).mappings().one()
        await app.rollback()
    return (
        row["company_state"],
        row["warehouse_state"],
        int(row["projected_row_count"] or 0),
        int(row["alert_count"] or 0),
        int(row["nonactive_visible_count"] or 0),
    )


async def projection_name(
    company_id: int,
    warehouse_id: int,
    variant_id: int,
) -> str | None:
    async with fixture.SessionApp() as app:
        await app.begin()
        await fixture.set_tenant(app, company_id)
        value = (
            await app.execute(
                text(
                    """
                    SELECT variant_name
                    FROM inventory_live_stock_projection
                    WHERE company_id=:company_id
                      AND warehouse_location_id=:warehouse_id
                      AND product_variant_id=:variant_id
                    """
                ),
                {
                    "company_id": company_id,
                    "warehouse_id": warehouse_id,
                    "variant_id": variant_id,
                },
            )
        ).scalar_one_or_none()
        await app.rollback()
    return None if value is None else str(value)


async def create_empty_warehouse(company_id: int, source_warehouse_id: int) -> int:
    async with fixture.SessionSU() as su:
        await su.begin()
        branch_id = int(
            (
                await su.execute(
                    text(
                        """
                        SELECT branch_id
                        FROM inventory_locations
                        WHERE company_id=:company_id
                          AND id=:warehouse_id
                        """
                    ),
                    {
                        "company_id": company_id,
                        "warehouse_id": source_warehouse_id,
                    },
                )
            ).scalar_one()
        )
        warehouse_id = int(
            (
                await su.execute(
                    text(
                        """
                        INSERT INTO inventory_locations
                            (company_id, branch_id, name, code,
                             location_type, vehicle_id, system_role,
                             is_system_managed, version, is_active,
                             created_at, updated_at)
                        VALUES
                            (:company_id, :branch_id, :name, :code,
                             'WAREHOUSE', NULL, NULL, false, 1, true,
                             NOW(), NOW())
                        RETURNING id
                        """
                    ),
                    {
                        "company_id": company_id,
                        "branch_id": branch_id,
                        "name": "Stage822 Empty Warehouse",
                        "code": f"S822-{uuid4().hex[:10]}",
                    },
                )
            ).scalar_one()
        )
        await su.commit()
    return warehouse_id


async def count_projection_rows(company_id: int, warehouse_id: int) -> tuple[int, int]:
    async with fixture.SessionApp() as app:
        await app.begin()
        await fixture.set_tenant(app, company_id)
        rows = int(
            (
                await app.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM inventory_live_stock_projection
                        WHERE company_id=:company_id
                          AND warehouse_location_id=:warehouse_id
                        """
                    ),
                    {
                        "company_id": company_id,
                        "warehouse_id": warehouse_id,
                    },
                )
            ).scalar_one()
        )
        summaries = int(
            (
                await app.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM inventory_live_stock_warehouse_summaries
                        WHERE company_id=:company_id
                          AND warehouse_location_id=:warehouse_id
                        """
                    ),
                    {
                        "company_id": company_id,
                        "warehouse_id": warehouse_id,
                    },
                )
            ).scalar_one()
        )
        await app.rollback()
    return rows, summaries


async def run() -> None:
    await fixture.cleanup_test_companies()
    ids = await fixture.seed()
    company_id = int(ids["a"])
    warehouse_id = int(ids["a_wh"])
    variant_id = int(ids["a_variant"])

    try:
        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            initial = await rebuild_live_stock_company(
                app,
                company_id=company_id,
                batch_size=1000,
            )
            await assert_live_stock_projection_ready(
                app,
                company_id=company_id,
                warehouse_location_id=warehouse_id,
            )
            await app.commit()

        record(
            "initial company rebuild materializes sparse truth",
            initial.candidate_keys >= 1 and initial.drifted_keys >= 1,
            (
                f"keys={initial.candidate_keys} "
                f"drift={initial.drifted_keys} "
                f"summary_repairs={initial.summary_repairs}"
            ),
        )
        health = await projection_health(company_id, warehouse_id)
        record(
            "rebuild marks company and warehouse READY",
            health[0] == "READY" and health[1] == "READY",
            f"company={health[0]} warehouse={health[1]}",
        )

        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            clean = await reconcile_live_stock_company(
                app,
                company_id=company_id,
                batch_size=1000,
            )
            await app.commit()

        record(
            "clean reconciliation is idempotent",
            clean.drifted_keys == 0 and clean.summary_repairs == 0,
            (
                f"drift={clean.drifted_keys} "
                f"summary_repairs={clean.summary_repairs}"
            ),
        )

        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            await app.execute(
                text(
                    """
                    UPDATE inventory_live_stock_projection
                    SET variant_name='CORRUPTED-STAGE822'
                    WHERE company_id=:company_id
                      AND warehouse_location_id=:warehouse_id
                      AND product_variant_id=:variant_id
                    """
                ),
                {
                    "company_id": company_id,
                    "warehouse_id": warehouse_id,
                    "variant_id": variant_id,
                },
            )
            await app.execute(
                text(
                    """
                    UPDATE inventory_live_stock_warehouse_summaries
                    SET projected_row_count=projected_row_count + 2
                    WHERE company_id=:company_id
                      AND warehouse_location_id=:warehouse_id
                    """
                ),
                {
                    "company_id": company_id,
                    "warehouse_id": warehouse_id,
                },
            )
            await app.commit()

        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            repaired = await reconcile_live_stock_company(
                app,
                company_id=company_id,
                batch_size=1000,
            )
            await app.commit()

        restored_name = await projection_name(
            company_id,
            warehouse_id,
            variant_id,
        )
        record(
            "reconciliation detects and repairs row drift",
            repaired.drifted_keys >= 1 and restored_name == "A Variant",
            f"drift={repaired.drifted_keys} name={restored_name}",
        )
        record(
            "reconciliation detects and repairs summary drift",
            repaired.summary_repairs >= 1,
            f"summary_repairs={repaired.summary_repairs}",
        )

        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            await mark_live_stock_projection_degraded(
                app,
                company_id=company_id,
                warehouse_location_id=warehouse_id,
            )
            await app.commit()

        rejected = False
        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            try:
                await assert_live_stock_projection_ready(
                    app,
                    company_id=company_id,
                    warehouse_location_id=warehouse_id,
                )
            except LiveStockProjectionError:
                rejected = True
            await app.rollback()
        record("DEGRADED projection is rejected by readiness guard", rejected)

        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            rebuilt = await rebuild_live_stock_warehouse(
                app,
                company_id=company_id,
                warehouse_location_id=warehouse_id,
                batch_size=1000,
            )
            await assert_live_stock_projection_ready(
                app,
                company_id=company_id,
                warehouse_location_id=warehouse_id,
            )
            await app.commit()
        record(
            "warehouse rebuild restores READY after degradation",
            rebuilt.drifted_keys == 0,
            f"drift={rebuilt.drifted_keys}",
        )

        empty_warehouse_id = await create_empty_warehouse(
            company_id,
            warehouse_id,
        )
        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            empty_report = await rebuild_live_stock_warehouse(
                app,
                company_id=company_id,
                warehouse_location_id=empty_warehouse_id,
                batch_size=1000,
            )
            await app.commit()
        record(
            "empty active warehouse can be rebuilt deterministically",
            empty_report.candidate_keys == 0,
            f"keys={empty_report.candidate_keys}",
        )

        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            await app.execute(
                text(
                    """
                    UPDATE inventory_locations
                    SET is_active=false, version=version + 1, updated_at=NOW()
                    WHERE company_id=:company_id AND id=:warehouse_id
                    """
                ),
                {
                    "company_id": company_id,
                    "warehouse_id": empty_warehouse_id,
                },
            )
            removed = await remove_live_stock_warehouse_projection(
                app,
                company_id=company_id,
                warehouse_location_id=empty_warehouse_id,
            )
            await app.commit()
        rows_after_remove, summaries_after_remove = await count_projection_rows(
            company_id,
            empty_warehouse_id,
        )
        record(
            "inactive warehouse projection is removed completely",
            removed == 0
            and rows_after_remove == 0
            and summaries_after_remove == 0,
            (
                f"removed_rows={removed} "
                f"projection_rows={rows_after_remove} "
                f"summaries={summaries_after_remove}"
            ),
        )

        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            await app.execute(
                text(
                    """
                    UPDATE inventory_locations
                    SET is_active=true, version=version + 1, updated_at=NOW()
                    WHERE company_id=:company_id AND id=:warehouse_id
                    """
                ),
                {
                    "company_id": company_id,
                    "warehouse_id": empty_warehouse_id,
                },
            )
            await rebuild_live_stock_warehouse(
                app,
                company_id=company_id,
                warehouse_location_id=empty_warehouse_id,
                batch_size=1000,
            )
            await assert_live_stock_projection_ready(
                app,
                company_id=company_id,
                warehouse_location_id=empty_warehouse_id,
            )
            await app.commit()
        record("reactivated warehouse rebuild returns READY", True)

    finally:
        await fixture.cleanup_test_companies()

    failures = [
        (name, detail)
        for name, ok, detail in RESULTS
        if not ok
    ]
    print(f"CHECKS={len(RESULTS)}")
    print(f"FAILURES={len(failures)}")
    for name, detail in failures:
        print(f"FAIL:{name}" + (f":{detail}" if detail else ""))
    if failures:
        raise SystemExit(1)
    print("STAGE822_LIVE_STOCK_REBUILD_RUNTIME_GATE=PASS")


async def main() -> None:
    try:
        await run()
    finally:
        await fixture.engine_app.dispose()
        await fixture.engine_su.dispose()


if __name__ == "__main__":
    asyncio.run(main())
