"""F4: actual PostgreSQL due-key selection, HTTP transaction and 10k boundary.

The projector's expensive per-variant recomputation is replaced ONLY by an
in-transaction SQL advance of the exact service-selected keys. This keeps the
10,000/10,001 read-repair/commit regression small while exercising the real
projection due-key query, FORCE RLS, and PostgreSQL transaction persistence.
The unchanged projector calculation is covered by its separate gates.
"""
from __future__ import annotations

import os
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy import Integer, bindparam

from api.warehouse import live_stock
from domains.live_stock_projection import service as projector
from tests.test_inbound_no_lot_frozen_postgres import pg

pytestmark = [pytest.mark.asyncio(loop_scope="function")]

_LIMIT = 10_000


async def _due(db, *, company: int, location: int) -> int:
    return int((await db.scalar(text("""
        SELECT count(*) FROM inventory_live_stock_projection
        WHERE company_id = :company AND warehouse_location_id = :location
          AND next_transition_date <=
            (timezone('Asia/Amman', current_timestamp))::date
    """), {"company": company, "location": location})) or 0)


async def _seed(db, tenant, count: int) -> tuple[int, int]:
    info = (await db.execute(text("""
        SELECT product_id, base_uom_id FROM product_variants
        WHERE company_id = :company AND id = :variant
    """), {"company": tenant.company_id, "variant": tenant.variant_id})).one()
    inserted = await db.execute(text("""
        WITH candidates AS (
            INSERT INTO product_variants
                (company_id, product_id, base_uom_id, name, sku,
                 lifecycle_status, published_at, created_at, updated_at)
            SELECT :company, :product, :uom, 'F4 variant ' || g,
                   'F4-' || g::text,
                   'ACTIVE', current_timestamp, current_timestamp, current_timestamp
            FROM generate_series(1, :count) AS g
            RETURNING id, name
        )
        INSERT INTO inventory_live_stock_projection (
            company_id, warehouse_location_id, product_variant_id,
            variant_name, lifecycle_status, operational_hold,
            has_active_policy, is_low_stock, computed_for_date,
            next_transition_date, updated_at
        )
        SELECT :company, :location, id, name, 'ACTIVE', 'NONE',
               true, false,
               (timezone('Asia/Amman', current_timestamp))::date - 2,
               (timezone('Asia/Amman', current_timestamp))::date - 1,
               current_timestamp
        FROM candidates
    """), {"company": tenant.company_id, "product": info.product_id,
            "uom": info.base_uom_id, "location": tenant.location_id, "count": count})
    assert inserted.rowcount == count
    # A different warehouse's three due keys must never be refreshed.
    other = await db.execute(text("""
        INSERT INTO inventory_live_stock_projection (
            company_id, warehouse_location_id, product_variant_id,
            variant_name, lifecycle_status, operational_hold,
            has_active_policy, is_low_stock, computed_for_date,
            next_transition_date, updated_at
        )
        SELECT company_id, :other_location, id, name, 'ACTIVE', 'NONE',
               true, false,
               (timezone('Asia/Amman', current_timestamp))::date - 2,
               (timezone('Asia/Amman', current_timestamp))::date - 1,
               current_timestamp
        FROM product_variants
        WHERE company_id = :company AND sku LIKE :prefix
        ORDER BY id LIMIT 3
    """), {"company": tenant.company_id, "other_location": tenant.other_location_id,
            "prefix": "F4-%"})
    assert other.rowcount == 3
    await db.commit()
    return tenant.location_id, tenant.other_location_id


@pytest.mark.parametrize("due_count", [10_000, 10_001])
async def test_f4_bounded_durable_recovery(pg, monkeypatch, due_count):
    if os.getenv("WANASAH_F4_PG_GATE") != "1":
        pytest.fail("F4 requires explicit isolated PostgreSQL acceptance gate")

    tenant = pg.tenants[0]
    counts: list[int] = []

    async with pg.session() as db:
        location, other_location = await _seed(db, tenant, due_count)
        assert await _due(db, company=tenant.company_id, location=location) == due_count
        assert await _due(db, company=tenant.company_id, location=other_location) == 3

        # Keep the REAL service's bounded, ordered due-key selection. Replace
        # only the expensive per-key recomputation kernel with equivalent SQL
        # that advances the selected due dates; the outer API and RLS are real.
        async def advance_selected_keys(session, *, company_id, keys,
                                        computed_for_date=None, **_options):
            assert company_id == tenant.company_id
            assert computed_for_date is not None
            assert isinstance(computed_for_date, date)
            assert 0 < len(keys) <= _LIMIT
            assert all(warehouse == location for warehouse, _variant in keys)
            ids = [variant for _warehouse, variant in keys]
            counts.append(len(ids))
            statement = text("""
                UPDATE inventory_live_stock_projection
                SET next_transition_date = NULL,
                    computed_for_date = :as_of_date,
                    revision = revision + 1
                WHERE company_id = :company AND warehouse_location_id = :location
                  AND product_variant_id = ANY(:variant_ids)
            """).bindparams(bindparam("variant_ids", type_=ARRAY(Integer)))
            result = await session.execute(statement, {
                "as_of_date": computed_for_date, "company": tenant.company_id,
                "location": location, "variant_ids": ids,
            })
            assert result.rowcount == len(ids)

        monkeypatch.setattr(projector, "refresh_live_stock_keys",
                            advance_selected_keys)

        if due_count == _LIMIT:
            result = await live_stock._require_live_stock_read_model_ready(
                db, company_id=tenant.company_id, location_id=location)
            assert result is not None
            assert await _due(db, company=tenant.company_id, location=location) == 0
            assert counts == [_LIMIT]
        else:
            with pytest.raises(HTTPException) as response:
                await live_stock._require_live_stock_read_model_ready(
                    db, company_id=tenant.company_id, location_id=location)
            assert response.value.status_code == 503
            assert response.value.detail["code"] == "LIVE_STOCK_PROJECTION_NOT_READY"
            assert counts == [_LIMIT]
            # Explicit rollback simulates FastAPI request teardown. The
            # first 10,000 corrections MUST survive as a committed batch.
            await db.rollback()
            assert await _due(db, company=tenant.company_id, location=location) == 1
            assert await _due(db, company=tenant.company_id, location=other_location) == 3
            result = await live_stock._require_live_stock_read_model_ready(
                db, company_id=tenant.company_id, location_id=location)
            assert result is not None
            assert await _due(db, company=tenant.company_id, location=location) == 0
            assert counts == [_LIMIT, 1]

        assert await _due(db, company=tenant.company_id, location=other_location) == 3

    # A different tenant remains invisible under actual runtime FORCE RLS.
    async with pg.session(1) as foreign:
        assert await _due(foreign, company=tenant.company_id, location=tenant.location_id) == 0

    print(f"F4_PG_BOUNDARY=PASS due={due_count} batches={counts} "
          f"scoped_other_warehouse_due=3")


async def test_f4_broken_repair_rolls_back_without_false_ready(pg, monkeypatch):
    if os.getenv("WANASAH_F4_PG_GATE") != "1":
        pytest.fail("F4 requires explicit isolated PostgreSQL acceptance gate")

    tenant = pg.tenants[0]
    async with pg.session() as db:
        location, _ = await _seed(db, tenant, 7)

        async def broken_repair(session, *, company_id, keys,
                                computed_for_date=None, **_options):
            assert company_id == tenant.company_id
            await session.execute(text("""
                UPDATE inventory_live_stock_projection
                SET next_transition_date = NULL
                WHERE company_id = :company AND warehouse_location_id = :location
                  AND product_variant_id = :variant
            """), {"company": tenant.company_id, "location": location,
                    "variant": keys[0][1]})
            raise projector.LiveStockProjectionError("injected transactional failure")

        monkeypatch.setattr(projector, "refresh_live_stock_keys", broken_repair)
        with pytest.raises(HTTPException) as response:
            await live_stock._require_live_stock_read_model_ready(
                db, company_id=tenant.company_id, location_id=location)
        assert response.value.status_code == 503
        await db.rollback()
        assert await _due(db, company=tenant.company_id, location=location) == 7
        print("F4_PG_TRANSACTION_ERROR=PASS zero_partial_commit=7")
