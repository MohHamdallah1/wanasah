"""Real PostgreSQL authorization and cursor gate for the Inventory selector.

Run only against the existing isolated, migrated no-lot fixture target. No mocks
and no skips: WANASAH_NO_LOT_PG_* environment must explicitly select that DB.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.warehouse import live_stock, locations
from models import InventoryLocation, UserLocationAccess
from tests.test_cp7_live_stock_postgres import _prepare_cp7
from tests.test_cp12_inventory_security_postgres import _grant_scoped_permissions
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401

pytestmark = pytest.mark.asyncio(loop_scope="function")


def _call(db, access, *, search=None, cursor=None, selected=None, limit=100):
    return locations.discover_inventory_warehouse_selection(
        search=search,
        cursor=cursor,
        selected_location_id=selected,
        limit=limit,
        db=db,
        access=access,
    )


async def test_inventory_only_and_location_only_grants_do_not_widen_management(pg):
    case = await _prepare_cp7(pg)
    a, b = case.a, case.b

    async with pg.session() as db:
        scoped = a.ordinary.access(db)
        inventory_only = await _call(db, scoped, selected=a.other_location_id)
        assert [item["id"] for item in inventory_only["items"]] == [a.location_id]
        assert inventory_only["selected"] is None
        assert all(set(item) == {"id", "name", "code"} for item in inventory_only["items"])
        with pytest.raises(HTTPException) as blocked:
            await locations.manage_warehouse_locations(
                search=None, include_inactive=False, cursor=None, limit=100,
                db=db, access=scoped,
            )
        assert blocked.value.status_code == 403

        foreign = await _call(db, scoped, selected=b.location_id)
        assert foreign["selected"] is None
        assert all(item["id"] != b.location_id for item in foreign["items"])

    await _grant_scoped_permissions(pg, a, ("location.read",), a.other_location_id)

    async with pg.session() as db:
        scoped = a.ordinary.access(db)
        response = await _call(db, scoped, selected=a.other_location_id)
        assert {item["id"] for item in response["items"]} == {
            a.location_id, a.other_location_id,
        }
        assert response["selected"]["id"] == a.other_location_id
        # location.read at the second warehouse does NOT grant inventory.read.
        with pytest.raises(HTTPException) as blocked:
            await live_stock.get_warehouse_inventory_summary(
                a.other_location_id, db, scoped,
            )
        assert blocked.value.status_code == 403
        managed = await locations.manage_warehouse_locations(
            search=None, include_inactive=False, cursor=None, limit=100,
            db=db, access=scoped,
        )
        assert [item["id"] for item in managed["items"]] == [a.other_location_id]

    async with pg.session(1) as db:
        # The second company's ordinary user has no grants in this fixture.
        # Denial is the correct behavior, not an empty successful listing.
        other_company = b.ordinary.access(db)
        with pytest.raises(HTTPException) as denied:
            await _call(db, other_company, selected=a.location_id)
        assert denied.value.status_code == 403


async def test_owner_can_page_and_search_beyond_200_and_cannot_replay_cursor_scope(pg):
    case = await _prepare_cp7(pg)
    a, b = case.a, case.b
    unique = uuid4().hex[:12]
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": str(a.company_id)},
        )
        extras = [
            InventoryLocation(
                company_id=a.company_id,
                name=f"Selection warehouse {unique} {index:03}",
                code=f"SEL-{unique}-{index:03}",
                location_type="WAREHOUSE",
            )
            for index in range(205)
        ]
        seed.add_all(extras)
        await seed.flush()
        beyond_id = int(extras[-1].id)
        await seed.commit()

    async with pg.session() as db:
        owner = a.owner.access(db)
        first = await _call(db, owner, selected=beyond_id, limit=75)
        assert first["selected"]["id"] == beyond_id
        assert first["has_more"] is True
        assert len(first["items"]) == 75
        cursor = None
        seen = set()
        for _ in range(4):
            page = await _call(db, owner, cursor=cursor, limit=75)
            identifiers = [item["id"] for item in page["items"]]
            assert not seen.intersection(identifiers)
            seen.update(identifiers)
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert beyond_id in seen
        assert len(seen) >= 205
        assert cursor is None

        searched = await _call(
            db, owner, search=f"{unique}-204", selected=beyond_id,
        )
        assert [item["id"] for item in searched["items"]] == [beyond_id]

        with pytest.raises(HTTPException) as mismatched:
            await _call(db, owner, search="another", cursor=first["next_cursor"])
        assert mismatched.value.status_code == 400

    async with pg.session(1) as db:
        foreign = await _call(db, b.owner.access(db), selected=beyond_id)
        assert foreign["selected"] is None
        assert all(item["id"] != beyond_id for item in foreign["items"])


async def test_live_revoke_is_enforced_for_list_and_restored_selection(pg):
    case = await _prepare_cp7(pg)
    a = case.a
    async with pg.session() as db:
        reader = a.ordinary.access(db)
        assert (await _call(db, reader, selected=a.location_id))["selected"]["id"] == a.location_id

    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": str(a.company_id)},
        )
        await seed.execute(
            delete(UserLocationAccess).where(
                UserLocationAccess.company_id == a.company_id,
                UserLocationAccess.driver_id == a.ordinary.driver_id,
                UserLocationAccess.location_id == a.location_id,
            )
        )
        await seed.commit()

    async with pg.session() as db:
        reader = a.ordinary.access(db)
        with pytest.raises(HTTPException) as blocked:
            await _call(db, reader, selected=a.location_id)
        assert blocked.value.status_code == 403
        with pytest.raises(HTTPException) as denied:
            await live_stock.get_warehouse_inventory_summary(
                a.location_id, db, reader,
            )
        assert denied.value.status_code == 403
