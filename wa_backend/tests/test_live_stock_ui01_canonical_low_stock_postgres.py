"""UI-01 canonical low-stock flag: real projection -> bounded HTTP cursor.

Uses the existing disposable migrated PostgreSQL fixture with real inventory
mutation, tenant and warehouse checks. No projection or accounting mocks.
"""
from __future__ import annotations

import os
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.warehouse import live_stock
from domains.live_stock_projection.service import rebuild_live_stock_company
from models import (
    InventoryLiveStockProjection,
    InventoryStockPolicy,
    ProductVariant,
    utc_now,
)
from tests.test_inbound_no_lot_frozen_postgres import pg

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_UI01_PG_GATE") != "1",
        reason="Explicit isolated UI-01 PostgreSQL gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _cursor(pg, *, party=0, location_id=None):
    tenant = pg.tenants[party]
    async with pg.session(party) as db:
        return await live_stock.get_warehouse_inventory(
            location_id=location_id or tenant.location_id,
            cursor=None,
            limit=50,
            search=None,
            only_alerts=False,
            stock_state="all",
            family_id=None,
            has_reserved=False,
            has_unavailable=False,
            has_damaged=False,
            has_recalled=False,
            has_vehicle=False,
            minimum_unset=False,
            sort="name_asc",
            db=db,
            access=tenant.owner.access(db),
        )


async def test_ui01_canonical_policy_and_cursor_flag(pg):
    tenant = pg.tenants[0]
    # Ten physical units committed through the normal inventory engine.
    async with pg.session() as db:
        await pg.post(db, pg.request(quantity="10", lot="UI01-BASE"))

    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as admin:
        await admin.execute(
            text("SELECT set_config('app.current_tenant',:tenant,true)"),
            {"tenant": str(tenant.company_id)},
        )
        admin.add(
            InventoryStockPolicy(
                company_id=tenant.company_id,
                location_id=tenant.location_id,
                product_variant_id=tenant.variant_id,
                minimum_quantity=Decimal("10"),
                target_quantity=None,
                is_active=True,
            )
        )
        await admin.flush()
        await rebuild_live_stock_company(admin, company_id=tenant.company_id)
        await admin.commit()

    cases = (
        ("ACTIVE", "NONE", "0", False),       # No minimum, no alert.
        ("ACTIVE", "NONE", "9", False),       # Free 10 > minimum 9.
        ("ACTIVE", "NONE", "10", True),       # Exact equality is low stock.
        ("ACTIVE", "NONE", "11", True),       # Free 10 < minimum 11.
        ("RETIRING", "NONE", "10", False),
        ("ACTIVE", "SALES_HOLD", "10", False),
        ("ACTIVE", "RECALL", "10", False),
    )

    for lifecycle, hold, minimum, expected in cases:
        async with AsyncSession(pg.admin_engine, expire_on_commit=False) as admin:
            await admin.execute(
                text(
                    "SELECT set_config('app.current_tenant',:tenant,true)"
                ),
                {"tenant": str(tenant.company_id)},
            )
            policy = await admin.scalar(
                select(InventoryStockPolicy).where(
                    InventoryStockPolicy.company_id == tenant.company_id,
                    InventoryStockPolicy.location_id == tenant.location_id,
                    InventoryStockPolicy.product_variant_id == tenant.variant_id,
                )
            )
            assert policy is not None
            policy.minimum_quantity = Decimal(minimum)
            variant = await admin.get(ProductVariant, tenant.variant_id)
            assert variant is not None
            variant.lifecycle_status = lifecycle
            variant.operational_hold = hold
            variant.retired_at = utc_now() if lifecycle == "RETIRING" else None
            await admin.flush()
            await rebuild_live_stock_company(admin, company_id=tenant.company_id)
            projected = await admin.scalar(
                select(InventoryLiveStockProjection.is_low_stock).where(
                    InventoryLiveStockProjection.company_id == tenant.company_id,
                    InventoryLiveStockProjection.warehouse_location_id == tenant.location_id,
                    InventoryLiveStockProjection.product_variant_id == tenant.variant_id,
                )
            )
            assert projected is expected
            await admin.commit()

        page = await _cursor(pg)
        row = next(item for item in page["items"] if item["id"] == tenant.variant_id)
        assert type(row["is_low_stock"]) is bool
        assert row["is_low_stock"] is expected
        assert row["minimum_quantity"] == minimum
        assert page["has_more"] == (page["next_cursor"] is not None)
        # FastAPI response-model validation is strict and keeps the flag.
        from schemas import WarehouseInventoryCursorPage
        parsed = WarehouseInventoryCursorPage.model_validate(page)
        assert parsed.items[0].is_low_stock is expected
        print(f"UI01_PG_PASS lifecycle={lifecycle} hold={hold} minimum={minimum} alert={expected}")

    # Existing company and warehouse authorization paths are unchanged.
    with pytest.raises(HTTPException) as wrong_company:
        await _cursor(pg, location_id=pg.tenants[1].location_id)
    assert wrong_company.value.status_code in {403, 404}
    print("UI01_PG_SCOPE_PASS different_company_denied")
