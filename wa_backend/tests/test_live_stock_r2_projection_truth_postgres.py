"""R2 Live Stock projection truth acceptance on disposable PostgreSQL 16.

This gate proves that persisted READY summaries are not sufficient when the
sparse projection disagrees with authoritative InventoryBalance truth.
"""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import pytest
from sqlalchemy import text

from domains.live_stock_projection.service import (
    LiveStockProjectionError,
    apply_live_stock_balance_impacts,
    assert_live_stock_projection_ready,
    rebuild_live_stock_company,
    rebuild_live_stock_warehouse,
    refresh_live_stock_keys,
)
from scripts import gate_stage821_live_stock_projector_runtime as fixture


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_R2_PG_GATE") != "1",
        reason="Explicit disposable R2 PostgreSQL gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _prepare_exact_ten() -> dict[str, int]:
    await fixture.cleanup_test_companies()
    ids = await fixture.seed()
    company_id = int(ids["a"])
    warehouse_id = int(ids["a_wh"])
    balance_id = int(ids["a_bal1"])

    async with fixture.SessionSU() as su:
        await su.begin()
        await su.execute(
            text(
                """
                DELETE FROM inventory_stock_policies
                WHERE company_id=:company_id
                  AND location_id=:warehouse_id
                """
            ),
            {
                "company_id": company_id,
                "warehouse_id": warehouse_id,
            },
        )
        await su.execute(
            text(
                """
                DELETE FROM inventory_balances
                WHERE company_id=:company_id
                  AND location_id=:warehouse_id
                  AND id<>:balance_id
                """
            ),
            {
                "company_id": company_id,
                "warehouse_id": warehouse_id,
                "balance_id": balance_id,
            },
        )
        await su.execute(
            text(
                """
                UPDATE inventory_balances
                SET on_hand_quantity=10,
                    reserved_quantity=0,
                    last_updated=NOW()
                WHERE company_id=:company_id
                  AND id=:balance_id
                """
            ),
            {
                "company_id": company_id,
                "balance_id": balance_id,
            },
        )
        await su.commit()

    async with fixture.SessionApp() as app:
        await app.begin()
        await fixture.set_tenant(app, company_id)
        await rebuild_live_stock_company(
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
    return ids


async def _truth_and_projection(
    ids: dict[str, int],
) -> tuple[Decimal, Decimal, str, str]:
    company_id = int(ids["a"])
    warehouse_id = int(ids["a_wh"])
    variant_id = int(ids["a_variant"])
    async with fixture.SessionApp() as app:
        await app.begin()
        await fixture.set_tenant(app, company_id)
        row = (
            await app.execute(
                text(
                    """
                    SELECT
                        COALESCE((
                            SELECT SUM(on_hand_quantity)
                            FROM inventory_balances
                            WHERE company_id=:company_id
                              AND location_id=:warehouse_id
                              AND product_variant_id=:variant_id
                              AND stock_status='AVAILABLE'
                        ), 0) AS truth_on_hand,
                        COALESCE((
                            SELECT warehouse_on_hand
                            FROM inventory_live_stock_projection
                            WHERE company_id=:company_id
                              AND warehouse_location_id=:warehouse_id
                              AND product_variant_id=:variant_id
                        ), 0) AS projected_on_hand,
                        (
                            SELECT projection_state
                            FROM inventory_live_stock_company_summaries
                            WHERE company_id=:company_id
                        ) AS company_state,
                        (
                            SELECT projection_state
                            FROM inventory_live_stock_warehouse_summaries
                            WHERE company_id=:company_id
                              AND warehouse_location_id=:warehouse_id
                        ) AS warehouse_state
                    """
                ),
                {
                    "company_id": company_id,
                    "warehouse_id": warehouse_id,
                    "variant_id": variant_id,
                },
            )
        ).one()
        await app.rollback()
    return (
        Decimal(row.truth_on_hand),
        Decimal(row.projected_on_hand),
        str(row.company_state),
        str(row.warehouse_state),
    )


async def _assert_ready_rejected(ids: dict[str, int]) -> None:
    company_id = int(ids["a"])
    warehouse_id = int(ids["a_wh"])
    async with fixture.SessionApp() as app:
        await app.begin()
        await fixture.set_tenant(app, company_id)
        with pytest.raises(LiveStockProjectionError):
            await assert_live_stock_projection_ready(
                app,
                company_id=company_id,
                warehouse_location_id=warehouse_id,
            )
        await app.rollback()


@pytest.mark.asyncio
async def test_r2_missing_projection_rejects_false_ready_zero() -> None:
    ids = await _prepare_exact_ten()
    try:
        company_id = int(ids["a"])
        warehouse_id = int(ids["a_wh"])
        variant_id = int(ids["a_variant"])
        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            await app.execute(
                text(
                    """
                    DELETE FROM inventory_live_stock_projection
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
            await app.commit()

        truth, projected, company_state, warehouse_state = (
            await _truth_and_projection(ids)
        )
        assert truth == Decimal("10")
        assert projected == Decimal("0")
        assert company_state == "READY"
        assert warehouse_state == "DEGRADED"
        await _assert_ready_rejected(ids)
    finally:
        await fixture.cleanup_test_companies()


@pytest.mark.asyncio
async def test_r2_stale_projection_rejects_false_ready() -> None:
    ids = await _prepare_exact_ten()
    try:
        company_id = int(ids["a"])
        warehouse_id = int(ids["a_wh"])
        variant_id = int(ids["a_variant"])
        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            await app.execute(
                text(
                    """
                    UPDATE inventory_live_stock_projection
                    SET warehouse_on_hand=9,
                        warehouse_sellable_on_hand=9,
                        revision=revision + 1,
                        updated_at=NOW()
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
            await app.commit()

        truth, projected, company_state, warehouse_state = (
            await _truth_and_projection(ids)
        )
        assert truth == Decimal("10")
        assert projected == Decimal("9")
        assert company_state == "READY"
        assert warehouse_state == "DEGRADED"
        await _assert_ready_rejected(ids)
    finally:
        await fixture.cleanup_test_companies()


@pytest.mark.asyncio
async def test_r2_rebuild_recovers_missing_projection_without_false_ready() -> None:
    ids = await _prepare_exact_ten()
    try:
        company_id = int(ids["a"])
        warehouse_id = int(ids["a_wh"])
        variant_id = int(ids["a_variant"])
        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            await app.execute(
                text(
                    """
                    DELETE FROM inventory_live_stock_projection
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
            await app.commit()

        await _assert_ready_rejected(ids)

        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            report = await rebuild_live_stock_warehouse(
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

        truth, projected, company_state, warehouse_state = (
            await _truth_and_projection(ids)
        )
        assert report.candidate_keys == 1
        assert report.drifted_keys == 1
        assert truth == projected == Decimal("10")
        assert company_state == "READY"
        assert warehouse_state == "READY"
    finally:
        await fixture.cleanup_test_companies()


@pytest.mark.asyncio
async def test_r2_truth_check_is_company_scoped() -> None:
    ids = await _prepare_exact_ten()
    try:
        company_a = int(ids["a"])
        warehouse_a = int(ids["a_wh"])
        company_b = int(ids["b"])
        warehouse_b = int(ids["b_wh"])

        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_b)
            await rebuild_live_stock_company(
                app,
                company_id=company_b,
                batch_size=1000,
            )
            await app.commit()

        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_b)
            await app.execute(
                text(
                    """
                    DELETE FROM inventory_live_stock_projection
                    WHERE company_id=:company_id
                      AND warehouse_location_id=:warehouse_id
                    """
                ),
                {
                    "company_id": company_b,
                    "warehouse_id": warehouse_b,
                },
            )
            await app.commit()

        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_a)
            await assert_live_stock_projection_ready(
                app,
                company_id=company_a,
                warehouse_location_id=warehouse_a,
            )
            await app.rollback()

        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_b)
            with pytest.raises(LiveStockProjectionError):
                await assert_live_stock_projection_ready(
                    app,
                    company_id=company_b,
                    warehouse_location_id=warehouse_b,
                )
            await app.rollback()
    finally:
        await fixture.cleanup_test_companies()


@pytest.mark.asyncio
async def test_r2_truth_check_is_warehouse_scoped_within_company() -> None:
    ids = await _prepare_exact_ten()
    try:
        company_id = int(ids["a"])
        primary_warehouse_id = int(ids["a_wh"])
        variant_id = int(ids["a_variant"])

        async with fixture.SessionSU() as su:
            await su.begin()
            secondary_warehouse_id = int(
                (
                    await su.execute(
                        text(
                            """
                            INSERT INTO inventory_locations
                                (company_id, branch_id, name, code,
                                 location_type, vehicle_id, system_role,
                                 is_system_managed, version, is_active,
                                 created_at, updated_at)
                            SELECT company_id, branch_id,
                                   'R2 Empty Warehouse', :code,
                                   'WAREHOUSE', NULL, NULL,
                                   false, 1, true, NOW(), NOW()
                            FROM inventory_locations
                            WHERE company_id=:company_id
                              AND id=:primary_warehouse_id
                            RETURNING id
                            """
                        ),
                        {
                            "company_id": company_id,
                            "primary_warehouse_id": primary_warehouse_id,
                            "code": f"R2-EMPTY-{primary_warehouse_id}",
                        },
                    )
                ).scalar_one()
            )
            await su.commit()

        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            await rebuild_live_stock_company(
                app,
                company_id=company_id,
                batch_size=1000,
            )
            await app.commit()

        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            await app.execute(
                text(
                    """
                    DELETE FROM inventory_live_stock_projection
                    WHERE company_id=:company_id
                      AND warehouse_location_id=:warehouse_id
                      AND product_variant_id=:variant_id
                    """
                ),
                {
                    "company_id": company_id,
                    "warehouse_id": primary_warehouse_id,
                    "variant_id": variant_id,
                },
            )
            await app.commit()

        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            await assert_live_stock_projection_ready(
                app,
                company_id=company_id,
                warehouse_location_id=secondary_warehouse_id,
            )
            with pytest.raises(LiveStockProjectionError):
                await assert_live_stock_projection_ready(
                    app,
                    company_id=company_id,
                    warehouse_location_id=primary_warehouse_id,
                )
            await app.rollback()
    finally:
        await fixture.cleanup_test_companies()


@pytest.mark.asyncio
async def test_r2_concurrent_movement_delta_and_projection_refresh_converge() -> None:
    ids = await _prepare_exact_ten()
    try:
        company_id = int(ids["a"])
        warehouse_id = int(ids["a_wh"])
        variant_id = int(ids["a_variant"])
        balance_id = int(ids["a_bal1"])
        movement_row_locked = asyncio.Event()

        async def movement_delta() -> None:
            async with fixture.SessionApp() as app:
                await app.begin()
                await fixture.set_tenant(app, company_id)
                metadata = await fixture.balance_impact_metadata(
                    app,
                    company_id=company_id,
                    balance_id=balance_id,
                )
                updated = (
                    await app.execute(
                        text(
                            """
                            UPDATE inventory_balances
                            SET on_hand_quantity=11,
                                last_updated=NOW()
                            WHERE company_id=:company_id
                              AND id=:balance_id
                            RETURNING on_hand_quantity, reserved_quantity
                            """
                        ),
                        {
                            "company_id": company_id,
                            "balance_id": balance_id,
                        },
                    )
                ).one()
                movement_row_locked.set()
                # Force the competing full refresh to enter while the movement
                # transaction still owns the authoritative balance row.
                await asyncio.sleep(0.25)
                metadata.update(
                    {
                        "on_hand_before": Decimal("10"),
                        "on_hand_after": Decimal(updated.on_hand_quantity),
                        "reserved_before": Decimal("0"),
                        "reserved_after": Decimal(updated.reserved_quantity),
                    }
                )
                await apply_live_stock_balance_impacts(
                    app,
                    company_id=company_id,
                    impacts=[metadata],
                )
                await app.commit()

        async def full_refresh() -> None:
            await movement_row_locked.wait()
            async with fixture.SessionApp() as app:
                await app.begin()
                await fixture.set_tenant(app, company_id)
                await refresh_live_stock_keys(
                    app,
                    company_id=company_id,
                    keys=[(warehouse_id, variant_id)],
                )
                await app.commit()

        await asyncio.wait_for(
            asyncio.gather(movement_delta(), full_refresh()),
            timeout=15,
        )

        async with fixture.SessionApp() as app:
            await app.begin()
            await fixture.set_tenant(app, company_id)
            await assert_live_stock_projection_ready(
                app,
                company_id=company_id,
                warehouse_location_id=warehouse_id,
            )
            await app.rollback()

        truth, projected, _, _ = await _truth_and_projection(ids)
        assert truth == projected == Decimal("11")
    finally:
        await fixture.cleanup_test_companies()
