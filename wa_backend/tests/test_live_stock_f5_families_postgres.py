"""F5/UI-03: authorized bounded family keyset pagination on disposable PG16.

Uses the existing migrated non-BYPASSRLS PostgreSQL fixture and real server
authorization. No real user data, migrations, projection or movement changes.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from api.warehouse import live_stock
from models import Product
from tests.test_inbound_no_lot_frozen_postgres import pg

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_F5_PG_GATE") != "1",
        reason="Explicit disposable PostgreSQL F5 acceptance only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _seed_families(pg, count: int) -> None:
    tenant = pg.tenants[0]
    async with pg.session() as db:
        prefix = uuid4().hex[:12]
        db.add_all([
            Product(
                company_id=tenant.company_id,
                name=f"F5 Family {i // 2:04d}",
                code=f"F5-{prefix}-{i:04d}",
            )
            for i in range(count)
        ])
        await db.commit()


async def _read(pg, *, location_id=None, search=None, cursor=None, limit=50, party=0):
    tenant = pg.tenants[party]
    async with pg.session(party) as db:
        return await live_stock.get_warehouse_inventory_families(
            location_id=location_id or tenant.location_id,
            search=search,
            cursor=cursor,
            limit=limit,
            db=db,
            access=tenant.owner.access(db),
        )


@pytest.mark.parametrize("family_count", [51, 101, 151])
async def test_family_keyset_reaches_last_row_without_duplicates(pg, family_count):
    await _seed_families(pg, family_count)
    pages = []
    cursor = None
    seen = set()
    while True:
        response = await _read(pg, search=" f5   family ", cursor=cursor)
        items = response["items"]
        assert len(items) <= 50
        assert items
        assert all(item["id"] not in seen for item in items)
        assert [(item["name"], item["id"]) for item in items] == sorted(
            (item["name"], item["id"]) for item in items
        )
        seen.update(item["id"] for item in items)
        assert response["has_more"] == (response["next_cursor"] is not None)
        pages.append(len(items))
        if not response["has_more"]:
            break
        assert response["next_cursor"] != cursor
        cursor = response["next_cursor"]
        assert isinstance(cursor, str) and len(cursor) <= 2048
        assert len(pages) <= 4
    assert len(seen) == family_count
    assert pages == [50] * (family_count // 50) + (
        [family_count % 50] if family_count % 50 else []
    )
    print(f"F5_KEYSET_PASS count={family_count} pages={pages}")


async def test_family_cursor_scope_unfiltered_and_access_checks(pg):
    await _seed_families(pg, 101)
    a, b = pg.tenants
    first = await _read(pg, search=None)
    assert len(first["items"]) == 50
    assert first["has_more"] and first["next_cursor"]
    continuation = await _read(pg, search=None, cursor=first["next_cursor"])
    assert len(continuation["items"]) <= 50
    assert not ({row["id"] for row in first["items"]} &
                {row["id"] for row in continuation["items"]})

    for different in (
        {"search": "f5 family"},
        {"location_id": a.other_location_id},
    ):
        with pytest.raises(HTTPException) as invalid:
            await _read(pg, cursor=first["next_cursor"], **different)
        assert invalid.value.status_code == 400

    with pytest.raises(HTTPException) as denied:
        await _read(pg, location_id=b.location_id)
    assert denied.value.status_code in {403, 404}

    with pytest.raises(HTTPException) as foreign:
        await _read(pg, party=1, location_id=a.location_id,
                    cursor=first["next_cursor"])
    assert foreign.value.status_code in {403, 404}

    with pytest.raises(HTTPException) as corrupt:
        await _read(pg, cursor="not-a-valid-cursor")
    assert corrupt.value.status_code == 400
    print("F5_SCOPE_PASS wrong_location_search_tenant_and_invalid_cursor_denied")


async def test_family_literal_search_and_last_page(pg):
    await _seed_families(pg, 101)
    # Escape LIKE wildcards: percent and underscore do not match all families.
    for query in ("f5 %", "f5 _"):
        response = await _read(pg, search=query)
        assert response == {"items": [], "has_more": False, "next_cursor": None}

    page = await _read(pg, search="F5 FAMILY", limit=100)
    assert len(page["items"]) == 100
    assert page["next_cursor"] is not None
    second = await _read(pg, search="F5 FAMILY", cursor=page["next_cursor"], limit=100)
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    print("F5_101_PASS pages=[100,1] literal_wildcard_search=PASS")
