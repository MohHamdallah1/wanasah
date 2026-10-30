from __future__ import annotations

import json
import os
from decimal import Decimal
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.warehouse import live_stock, live_stock_source_detail
from domains.live_stock_projection.service import rebuild_live_stock_company
from models import (
    InventoryBalance,
    Permission,
    Product,
    ProductBatch,
    ProductLocation,
    ProductVariant,
    Role,
    UserLocationAccess,
    role_permissions,
    utc_now,
)
from tests.test_inbound_no_lot_frozen_postgres import pg


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CP7_PG_GATE") != "1",
        reason="Explicit migrated disposable CP7 PostgreSQL gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _grant_inventory_read(seed: AsyncSession, tenant, location_id: int) -> None:
    permission = await seed.scalar(
        select(Permission).where(Permission.code == "inventory.read")
    )
    assert permission is not None
    role = Role(
        company_id=tenant.company_id,
        name="CP7 live stock reader " + uuid4().hex,
    )
    seed.add(role)
    await seed.flush()
    await seed.execute(
        role_permissions.insert().values(
            company_id=tenant.company_id,
            role_id=role.id,
            permission_id=permission.id,
        )
    )
    seed.add(
        UserLocationAccess(
            company_id=tenant.company_id,
            role_id=role.id,
            driver_id=tenant.ordinary.driver_id,
            location_id=location_id,
        )
    )


async def _prepare_cp7(pg):
    a = pg.tenants[0]
    b = pg.tenants[1]
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        for tenant in (a, b):
            await seed.execute(
                text("SELECT set_config('app.current_tenant',:tenant,true)"),
                {"tenant": str(tenant.company_id)},
            )
            seed.add(
                ProductLocation(
                    company_id=tenant.company_id,
                    location_id=tenant.other_location_id,
                    product_variant_id=tenant.variant_id,
                    created_by=tenant.owner.driver_id,
                    operational_flags={
                        "inbound_enabled": True,
                        "outbound_enabled": True,
                    },
                )
            )
            await seed.flush()
            await rebuild_live_stock_company(seed, company_id=tenant.company_id)
            await seed.commit()

        await seed.execute(
            text("SELECT set_config('app.current_tenant',:tenant,true)"),
            {"tenant": str(a.company_id)},
        )
        await _grant_inventory_read(seed, a, a.location_id)
        base = await seed.get(ProductVariant, a.variant_id)
        assert base is not None
        product = await seed.get(Product, base.product_id)
        assert product is not None
        for index in range(6):
            seed.add(
                ProductVariant(
                    company_id=a.company_id,
                    product_id=product.id,
                    name=f"CP7 deterministic {index:02d}",
                    sku=f"CP7-{index:02d}",
                    base_uom_id=a.uom_id,
                    quantity_scale=6,
                    quantity_step=Decimal("0.000001"),
                    lot_control_mode="OPTIONAL",
                    expiry_control_mode="OPTIONAL",
                    lifecycle_status="ACTIVE",
                    published_at=utc_now(),
                )
            )
        await seed.flush()
        await rebuild_live_stock_company(seed, company_id=a.company_id)
        await seed.commit()

    async with pg.session() as db:
        await pg.post(db, pg.request(lot="A1-ONLY", quantity="2.500001"))
        await pg.post(db, pg.request(quantity="1.25"))
        a2 = pg.request(lot="A2-ONLY", quantity="7").model_copy(
            update={"location_id": a.other_location_id}
        )
        await pg.post(db, a2)
    async with pg.session(1) as db:
        await pg.post(
            db,
            pg.request(party=1, lot="A2-ONLY", quantity="7"),
            party=1,
        )

    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        for tenant in (a, b):
            await seed.execute(
                text("SELECT set_config('app.current_tenant',:tenant,true)"),
                {"tenant": str(tenant.company_id)},
            )
            await rebuild_live_stock_company(seed, company_id=tenant.company_id)
            await seed.commit()

    async with pg.session() as db:
        a_batches = (
            await db.execute(
                select(ProductBatch.id, ProductBatch.batch_number).where(
                    ProductBatch.company_id == a.company_id,
                    ProductBatch.product_variant_id == a.variant_id,
                )
            )
        ).all()
    async with pg.session(1) as db:
        b_batches = (
            await db.execute(
                select(ProductBatch.id, ProductBatch.batch_number).where(
                    ProductBatch.company_id == b.company_id,
                    ProductBatch.product_variant_id == b.variant_id,
                )
            )
        ).all()

    by_number = {row.batch_number: int(row.id) for row in a_batches}
    anonymous_id = next(
        int(row.id)
        for row in a_batches
        if str(row.batch_number).startswith("__WANASAH_NOLOT__")
    )
    return NS(
        a=a,
        b=b,
        a1_real_batch_id=by_number["A1-ONLY"],
        a2_batch_id=by_number["A2-ONLY"],
        anonymous_batch_id=anonymous_id,
        b_batch_id=next(int(row.id) for row in b_batches if row.batch_number == "A2-ONLY"),
    )


def _cursor_kwargs(location_id: int, db, access, *, cursor=None, limit=50, search=None):
    return dict(
        location_id=location_id,
        cursor=cursor,
        limit=limit,
        search=search,
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
        access=access,
    )


async def test_cp7_exact_warehouse_company_rls_and_no_lot_isolation(pg):
    case = await _prepare_cp7(pg)
    a = case.a
    b = case.b

    async with pg.session() as db:
        access = a.ordinary.access(db)
        page = await live_stock.get_warehouse_inventory(
            **_cursor_kwargs(a.location_id, db, access)
        )
        row = next(item for item in page["items"] if item["id"] == a.variant_id)
        assert row["on_hand_quantity"] == "3.750001"
        assert row["available_for_sale_quantity"] == "3.750001"
        assert row["reserved_quantity"] == "0"

        batches = await live_stock.get_warehouse_inventory_batches(
            a.variant_id,
            a.location_id,
            None,
            100,
            db,
            access,
        )
        assert {item["batch_id"] for item in batches["batches"]} == {
            case.a1_real_batch_id,
            case.anonymous_batch_id,
        }
        assert any(item["batch_number"] is None for item in batches["batches"])
        serialized = json.dumps({"page": page, "batches": batches}, default=str)
        assert "__WANASAH_NOLOT__" not in serialized
        assert "A2-ONLY" not in serialized

        source = await live_stock_source_detail.get_live_stock_batch_source(
            a.variant_id,
            case.a1_real_batch_id,
            a.location_id,
            db,
            access,
        )
        assert source["location_id"] == a.location_id
        assert source["batch_id"] == case.a1_real_batch_id
        assert source["statuses"][0]["on_hand_quantity"] == "2.500001"

        with pytest.raises(HTTPException) as hidden_a2:
            await live_stock_source_detail.get_live_stock_batch_source(
                a.variant_id,
                case.a2_batch_id,
                a.location_id,
                db,
                access,
            )
        assert hidden_a2.value.status_code == 404

        with pytest.raises(HTTPException) as foreign_location:
            await live_stock_source_detail.get_live_stock_batch_source(
                b.variant_id,
                case.b_batch_id,
                b.location_id,
                db,
                access,
            )
        assert foreign_location.value.status_code in {403, 404}

        # Deliberately omit company predicates: FORCE RLS must still hide B.
        assert await db.scalar(
            select(ProductBatch).where(ProductBatch.id == case.b_batch_id)
        ) is None
        assert await db.scalar(
            select(InventoryBalance).where(
                InventoryBalance.location_id == b.location_id
            )
        ) is None


async def test_cp7_list_and_batch_detail_share_product_sale_gate(pg):
    """The visible batch partition must not promise saleable stock under a hold.

    Explicit PostgreSQL-only gate; no mocks and no change to movement authority.
    """
    case = await _prepare_cp7(pg)
    a = case.a
    expected_physical = Decimal("3.750001")

    for lifecycle, hold, expected_sellable in (
        ("ACTIVE", "NONE", expected_physical),
        ("ACTIVE", "SALES_HOLD", Decimal("0")),
        ("ACTIVE", "RECALL", Decimal("0")),
        ("RETIRING", "NONE", Decimal("0")),
    ):
        async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
            await seed.execute(
                text("SELECT set_config('app.current_tenant',:tenant,true)"),
                {"tenant": str(a.company_id)},
            )
            variant = await seed.get(ProductVariant, a.variant_id)
            assert variant is not None
            variant.lifecycle_status = lifecycle
            variant.operational_hold = hold
            variant.retired_at = utc_now() if lifecycle == "RETIRING" else None
            await seed.flush()
            await rebuild_live_stock_company(seed, company_id=a.company_id)
            await seed.commit()

        async with pg.session() as db:
            access = a.ordinary.access(db)
            page = await live_stock.get_warehouse_inventory(
                **_cursor_kwargs(a.location_id, db, access)
            )
            row = next(
                item for item in page["items"] if item["id"] == a.variant_id
            )
            detail = await live_stock.get_warehouse_inventory_batches(
                a.variant_id, a.location_id, None, 100, db, access
            )
            assert detail["batches"]
            assert Decimal(row["on_hand_quantity"]) == expected_physical
            assert Decimal(row["reserved_quantity"]) == 0
            assert Decimal(row["available_for_sale_quantity"]) == expected_sellable
            assert Decimal(row["unavailable_quantity"]) == (
                expected_physical - expected_sellable
            )
            assert sum(
                (Decimal(b["on_hand_quantity"]) for b in detail["batches"]),
                Decimal("0"),
            ) == expected_physical
            assert sum(
                (Decimal(b["available_for_sale_quantity"]) for b in detail["batches"]),
                Decimal("0"),
            ) == expected_sellable
            for batch in detail["batches"]:
                on_hand = Decimal(batch["on_hand_quantity"])
                reserved = Decimal(batch["reserved_quantity"])
                sellable = Decimal(batch["available_for_sale_quantity"])
                unavailable = Decimal(batch["unavailable_quantity"])
                assert on_hand == reserved + sellable + unavailable
                assert sellable >= 0 and unavailable >= 0


async def test_cp7_a2_exact_location_and_cross_company_overlap_are_structural(pg):
    case = await _prepare_cp7(pg)
    a = case.a
    async with pg.session() as db:
        owner = a.owner.access(db)
        a1 = await live_stock.get_warehouse_inventory_batches(
            a.variant_id, a.location_id, None, 100, db, owner
        )
        a2 = await live_stock.get_warehouse_inventory_batches(
            a.variant_id, a.other_location_id, None, 100, db, owner
        )
        assert case.a2_batch_id not in {item["batch_id"] for item in a1["batches"]}
        assert case.a2_batch_id in {item["batch_id"] for item in a2["batches"]}
        a2_item = next(item for item in a2["batches"] if item["batch_id"] == case.a2_batch_id)
        assert a2_item["batch_number"] == "A2-ONLY"
        assert a2_item["on_hand_quantity"] == "7"


async def test_cp7_search_pagination_cursor_binding_and_no_duplicate_rows(pg):
    case = await _prepare_cp7(pg)
    a = case.a
    async with pg.session() as db:
        access = a.ordinary.access(db)
        first = await live_stock.get_warehouse_inventory(
            **_cursor_kwargs(a.location_id, db, access, limit=1)
        )
        assert first["has_more"] is True
        assert first["next_cursor"]
        second = await live_stock.get_warehouse_inventory(
            **_cursor_kwargs(
                a.location_id,
                db,
                access,
                cursor=first["next_cursor"],
                limit=1,
            )
        )
        assert {item["id"] for item in first["items"]}.isdisjoint(
            {item["id"] for item in second["items"]}
        )

        search = await live_stock.get_warehouse_inventory(
            **_cursor_kwargs(a.location_id, db, access, search="No-lot")
        )
        assert [item["id"] for item in search["items"]] == [a.variant_id]
        assert case.b.variant_id not in {item["id"] for item in search["items"]}

        with pytest.raises(HTTPException):
            await live_stock.get_warehouse_inventory(
                **_cursor_kwargs(
                    a.other_location_id,
                    db,
                    a.owner.access(db),
                    cursor=first["next_cursor"],
                    limit=1,
                )
            )


async def test_cp7_summary_is_location_authorized_and_foreign_location_is_opaque(pg):
    case = await _prepare_cp7(pg)
    a = case.a
    b = case.b
    async with pg.session() as db:
        access = a.ordinary.access(db)
        summary = await live_stock.get_warehouse_inventory_summary(
            a.location_id, db, access
        )
        assert summary["stock_total"] >= 1
        assert summary["alert_count"] >= 0
        with pytest.raises(HTTPException) as caught:
            await live_stock.get_warehouse_inventory_summary(
                b.location_id, db, access
            )
        assert caught.value.status_code in {403, 404}


async def test_cp7_sql_statement_count_does_not_grow_per_returned_row(pg):
    case = await _prepare_cp7(pg)
    a = case.a

    async def count_call(callback):
        count = 0

        def before_cursor_execute(*_args, **_kwargs):
            nonlocal count
            count += 1

        event.listen(
            pg.runtime_engine.sync_engine,
            "before_cursor_execute",
            before_cursor_execute,
        )
        try:
            return await callback(), count
        finally:
            event.remove(
                pg.runtime_engine.sync_engine,
                "before_cursor_execute",
                before_cursor_execute,
            )

    async with pg.session() as db:
        access = a.ordinary.access(db)
        small, small_count = await count_call(
            lambda: live_stock.get_warehouse_inventory(
                **_cursor_kwargs(a.location_id, db, access, limit=1)
            )
        )
        large, large_count = await count_call(
            lambda: live_stock.get_warehouse_inventory(
                **_cursor_kwargs(a.location_id, db, access, limit=50)
            )
        )
        _, summary_count = await count_call(
            lambda: live_stock.get_warehouse_inventory_summary(
                a.location_id, db, access
            )
        )
        _, detail_count = await count_call(
            lambda: live_stock.get_warehouse_inventory_batches(
                a.variant_id, a.location_id, None, 100, db, access
            )
        )
        _, source_count = await count_call(
            lambda: live_stock_source_detail.get_live_stock_batch_source(
                a.variant_id,
                case.a1_real_batch_id,
                a.location_id,
                db,
                access,
            )
        )

    assert len(large["items"]) > len(small["items"])
    assert large_count <= small_count + 1
    assert summary_count < 20
    assert detail_count < 20
    assert source_count < 20
    print(
        "CP7_SQL_COUNTS",
        {
            "cursor_small": small_count,
            "cursor_large": large_count,
            "summary": summary_count,
            "batch_detail": detail_count,
            "source_detail": source_count,
        },
    )
