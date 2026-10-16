from __future__ import annotations

import base64
import json
import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api import product_locations
from api.warehouse import batch_index, ledger, live_stock, locations, stocktake
from domains.stocktake.contracts import StocktakeStartCommand
from models import Permission, Role, UserLocationAccess, role_permissions
from tests.test_cp7_live_stock_postgres import _cursor_kwargs, _prepare_cp7
from tests.test_inbound_no_lot_frozen_postgres import pg


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CP12_SECURITY_PG_GATE") != "1",
        reason="Explicit migrated disposable CP12 PostgreSQL security gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _grant_scoped_permissions(pg, tenant, codes: tuple[str, ...], location_id: int) -> None:
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(
            text("SELECT set_config('app.current_tenant',:tenant,true)"),
            {"tenant": str(tenant.company_id)},
        )
        role = Role(company_id=tenant.company_id, name="CP12 scoped " + uuid4().hex)
        seed.add(role)
        await seed.flush()
        for code in codes:
            permission = await seed.scalar(select(Permission).where(Permission.code == code))
            assert permission is not None, f"missing migrated permission {code}"
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
        await seed.commit()


def _batch_kwargs(location_id: int, db, access, *, cursor=None, limit=50, search=None):
    return dict(
        location_id=location_id,
        cursor=cursor,
        limit=limit,
        search=search,
        expiry_state="ALL",
        expiry_warning_days=None,
        sellability="ALL",
        disposition=None,
        has_unavailable=None,
        has_damaged=None,
        has_disposal_pending=None,
        family_id=None,
        product_variant_id=None,
        sort="EXPIRY_ASC",
        db=db,
        access=access,
    )


def _json(value) -> str:
    return json.dumps(value, default=str, sort_keys=True)


def _tamper(cursor: str) -> str:
    last = "A" if cursor[-1] != "A" else "B"
    return cursor[:-1] + last


def _collect_ints(value) -> set[int]:
    if isinstance(value, bool):
        return set()
    if isinstance(value, int):
        return {value}
    if isinstance(value, dict):
        result: set[int] = set()
        for child in value.values():
            result.update(_collect_ints(child))
        return result
    if isinstance(value, (list, tuple)):
        result: set[int] = set()
        for child in value:
            result.update(_collect_ints(child))
        return result
    return set()


def _decoded_cursor_text(cursor: str) -> str:
    payload = cursor.split(".", 1)[0]
    payload += "=" * (-len(payload) % 4)
    try:
        return base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


async def _assert_http(call, status: int | tuple[int, ...]):
    statuses = (status,) if isinstance(status, int) else status
    with pytest.raises(HTTPException) as caught:
        await call()
    assert caught.value.status_code in statuses
    return caught.value


async def test_cp12_company_location_matrix_no_lot_and_opaque_foreign_ids(pg):
    case = await _prepare_cp7(pg)
    a, b = case.a, case.b
    await _grant_scoped_permissions(
        pg,
        a,
        (
            "location.read",
            "product_location.read",
            "ledger.read",
            "stocktake.read",
            "stocktake.start",
        ),
        a.location_id,
    )

    async with pg.session() as db:
        access = a.ordinary.access(db)

        live_page = await live_stock.get_warehouse_inventory(
            **_cursor_kwargs(a.location_id, db, access, limit=50)
        )
        live_ids = {int(item["id"]) for item in live_page["items"]}
        assert a.variant_id in live_ids
        assert b.variant_id not in live_ids

        live_summary = await live_stock.get_warehouse_inventory_summary(
            a.location_id, db, access
        )
        assert live_summary["stock_total"] >= 1

        batches = await batch_index.get_warehouse_inventory_batch_index_cursor(
            **_batch_kwargs(a.location_id, db, access, limit=100)
        )
        batch_ids = {int(item["batch_id"]) for item in batches["items"]}
        assert case.a1_real_batch_id in batch_ids
        assert case.a2_batch_id not in batch_ids
        assert case.b_batch_id not in batch_ids
        assert any(item["batch_number"] is None for item in batches["items"])

        batch_summary = await batch_index.get_warehouse_inventory_batch_index_summary(
            location_id=a.location_id,
            expiry_warning_days=30,
            search=None,
            family_id=None,
            product_variant_id=None,
            db=db,
            access=access,
        )
        assert batch_summary["total_relevant_batches"] == len(batch_ids)

        warehouses = await locations.manage_warehouse_locations(
            search=None,
            include_inactive=False,
            cursor=None,
            limit=200,
            db=db,
            access=access,
        )
        warehouse_ids = {int(item["id"]) for item in warehouses["items"]}
        assert warehouse_ids == {a.location_id}
        assert a.other_location_id not in warehouse_ids
        assert b.location_id not in warehouse_ids

        assignments = await product_locations.list_product_locations(
            location_id=None,
            product_variant_id=None,
            cursor=None,
            limit=200,
            db=db,
            access=access,
        )
        assignment_locations = {int(item["location"]["id"]) for item in assignments["items"]}
        assert assignment_locations == {a.location_id}

        ledger_page = await ledger.get_warehouse_ledger_cursor(
            location_id=a.location_id,
            cursor=None,
            limit=200,
            search=None,
            reference_type=None,
            reference_id=None,
            db=db,
            access=access,
        )
        assert ledger_page["items"]
        for item in ledger_page["items"]:
            assert item["source_location_id"] in {None, a.location_id}
            assert item["destination_location_id"] in {None, a.location_id}

        first = await stocktake.start_unified_stocktake(
            StocktakeStartCommand(
                request_id=uuid4(),
                location_id=a.location_id,
                stocktake_type="CYCLE_COUNT",
                product_variant_id=a.variant_id,
                batch_id=case.a1_real_batch_id,
                related_work_session_id=None,
            ),
            db=db,
            access=access,
            legacy_actor=a.ordinary.operational_driver,
        )
        second = await stocktake.start_unified_stocktake(
            StocktakeStartCommand(
                request_id=uuid4(),
                location_id=a.location_id,
                stocktake_type="CYCLE_COUNT",
                product_variant_id=a.variant_id,
                batch_id=case.anonymous_batch_id,
                related_work_session_id=None,
            ),
            db=db,
            access=access,
            legacy_actor=a.ordinary.operational_driver,
        )
        active = await stocktake.list_active_stocktake_sessions(
            location_id=a.location_id,
            cursor=None,
            limit=200,
            db=db,
            access=access,
        )
        active_ids = {int(item["id"]) for item in active["items"]}
        assert {int(first["session_id"]), int(second["session_id"])} <= active_ids

        serialized = _json(
            {
                "live": live_page,
                "batches": batches,
                "batch_summary": batch_summary,
                "warehouses": warehouses,
                "assignments": assignments,
                "ledger": ledger_page,
                "active": active,
            }
        )
        assert "__WANASAH_NOLOT__" not in serialized
        assert "A2-ONLY" not in serialized

        foreign_checks = (
            lambda: live_stock.get_warehouse_inventory_summary(b.location_id, db, access),
            lambda: batch_index.get_warehouse_inventory_batch_index_summary(
                location_id=b.location_id,
                expiry_warning_days=30,
                search=None,
                family_id=None,
                product_variant_id=None,
                db=db,
                access=access,
            ),
            lambda: ledger.get_warehouse_ledger_cursor(
                location_id=b.location_id,
                cursor=None,
                limit=50,
                search=None,
                reference_type=None,
                reference_id=None,
                db=db,
                access=access,
            ),
            lambda: product_locations.list_product_locations(
                location_id=b.location_id,
                product_variant_id=None,
                cursor=None,
                limit=50,
                db=db,
                access=access,
            ),
        )
        for call in foreign_checks:
            error = await _assert_http(call, (403, 404))
            detail = _json(error.detail)
            exact_ids = _collect_ints(error.detail)
            assert "__WANASAH_NOLOT__" not in detail
            assert case.b_batch_id not in exact_ids
            assert b.variant_id not in exact_ids
            assert b.location_id not in exact_ids


async def test_cp12_cursor_tamper_scope_filter_and_payload_safety(pg):
    case = await _prepare_cp7(pg)
    a, b = case.a, case.b
    await _grant_scoped_permissions(
        pg,
        a,
        ("ledger.read", "stocktake.read", "stocktake.start"),
        a.location_id,
    )
    await _grant_scoped_permissions(
        pg,
        b,
        ("inventory.read", "ledger.read", "stocktake.read"),
        b.location_id,
    )

    async with pg.session() as db:
        access = a.ordinary.access(db)

        live_first = await live_stock.get_warehouse_inventory(
            **_cursor_kwargs(a.location_id, db, access, limit=1)
        )
        assert live_first["next_cursor"]
        await _assert_http(
            lambda: live_stock.get_warehouse_inventory(
                **_cursor_kwargs(
                    a.location_id,
                    db,
                    access,
                    cursor=_tamper(live_first["next_cursor"]),
                    limit=1,
                )
            ),
            400,
        )
        await _assert_http(
            lambda: live_stock.get_warehouse_inventory(
                **_cursor_kwargs(
                    a.location_id,
                    db,
                    access,
                    cursor=live_first["next_cursor"],
                    limit=1,
                    search="different-filter",
                )
            ),
            400,
        )

        batch_first = await batch_index.get_warehouse_inventory_batch_index_cursor(
            **_batch_kwargs(a.location_id, db, access, limit=1)
        )
        assert batch_first["next_cursor"]
        await _assert_http(
            lambda: batch_index.get_warehouse_inventory_batch_index_cursor(
                **_batch_kwargs(
                    a.location_id,
                    db,
                    access,
                    cursor=_tamper(batch_first["next_cursor"]),
                    limit=1,
                )
            ),
            400,
        )
        await _assert_http(
            lambda: batch_index.get_warehouse_inventory_batch_index_cursor(
                **_batch_kwargs(
                    a.location_id,
                    db,
                    access,
                    cursor=batch_first["next_cursor"],
                    limit=1,
                    search="other",
                )
            ),
            400,
        )

        ledger_first = await ledger.get_warehouse_ledger_cursor(
            location_id=a.location_id,
            cursor=None,
            limit=1,
            search=None,
            reference_type=None,
            reference_id=None,
            db=db,
            access=access,
        )
        assert ledger_first["next_cursor"]
        await _assert_http(
            lambda: ledger.get_warehouse_ledger_cursor(
                location_id=a.location_id,
                cursor=_tamper(ledger_first["next_cursor"]),
                limit=1,
                search=None,
                reference_type=None,
                reference_id=None,
                db=db,
                access=access,
            ),
            400,
        )
        await _assert_http(
            lambda: ledger.get_warehouse_ledger_cursor(
                location_id=a.location_id,
                cursor=ledger_first["next_cursor"],
                limit=1,
                search="different",
                reference_type=None,
                reference_id=None,
                db=db,
                access=access,
            ),
            400,
        )

        for cursor in (
            live_first["next_cursor"],
            batch_first["next_cursor"],
            ledger_first["next_cursor"],
        ):
            assert "__WANASAH_NOLOT__" not in _decoded_cursor_text(cursor)

        first = await stocktake.start_unified_stocktake(
            StocktakeStartCommand(
                request_id=uuid4(),
                location_id=a.location_id,
                stocktake_type="CYCLE_COUNT",
                product_variant_id=a.variant_id,
                batch_id=case.a1_real_batch_id,
                related_work_session_id=None,
            ),
            db=db,
            access=access,
            legacy_actor=a.ordinary.operational_driver,
        )
        await stocktake.start_unified_stocktake(
            StocktakeStartCommand(
                request_id=uuid4(),
                location_id=a.location_id,
                stocktake_type="CYCLE_COUNT",
                product_variant_id=a.variant_id,
                batch_id=case.anonymous_batch_id,
                related_work_session_id=None,
            ),
            db=db,
            access=access,
            legacy_actor=a.ordinary.operational_driver,
        )
        stocktake_first = await stocktake.list_active_stocktake_sessions(
            location_id=a.location_id,
            cursor=None,
            limit=1,
            db=db,
            access=access,
        )
        assert stocktake_first["next_cursor"]
        await _assert_http(
            lambda: stocktake.list_active_stocktake_sessions(
                location_id=a.location_id,
                cursor=_tamper(stocktake_first["next_cursor"]),
                limit=1,
                db=db,
                access=access,
            ),
            400,
        )
        await _assert_http(
            lambda: stocktake.list_active_stocktake_sessions(
                location_id=a.other_location_id,
                cursor=stocktake_first["next_cursor"],
                limit=1,
                db=db,
                access=a.owner.access(db),
            ),
            400,
        )
        assert int(first["session_id"]) > 0
        assert "__WANASAH_NOLOT__" not in _decoded_cursor_text(stocktake_first["next_cursor"])

        live_cursor = live_first["next_cursor"]
        batch_cursor = batch_first["next_cursor"]
        ledger_cursor = ledger_first["next_cursor"]
        stocktake_cursor = stocktake_first["next_cursor"]

    async with pg.session(1) as db:
        b_access = b.ordinary.access(db)
        await _assert_http(
            lambda: live_stock.get_warehouse_inventory(
                **_cursor_kwargs(b.location_id, db, b_access, cursor=live_cursor, limit=1)
            ),
            400,
        )
        await _assert_http(
            lambda: batch_index.get_warehouse_inventory_batch_index_cursor(
                **_batch_kwargs(b.location_id, db, b_access, cursor=batch_cursor, limit=1)
            ),
            400,
        )
        await _assert_http(
            lambda: ledger.get_warehouse_ledger_cursor(
                location_id=b.location_id,
                cursor=ledger_cursor,
                limit=1,
                search=None,
                reference_type=None,
                reference_id=None,
                db=db,
                access=b_access,
            ),
            400,
        )
        await _assert_http(
            lambda: stocktake.list_active_stocktake_sessions(
                location_id=b.location_id,
                cursor=stocktake_cursor,
                limit=1,
                db=db,
                access=b_access,
            ),
            400,
        )


async def test_cp12_unauthorized_operator_gets_no_sensitive_payload(pg):
    case = await _prepare_cp7(pg)
    a = case.a
    async with pg.session() as db:
        access = a.ordinary.access(db)  # _prepare_cp7 grants only inventory.read at A1.

        denied_calls = (
            lambda: ledger.get_warehouse_ledger_cursor(
                location_id=a.location_id,
                cursor=None,
                limit=50,
                search=None,
                reference_type=None,
                reference_id=None,
                db=db,
                access=access,
            ),
            lambda: locations.manage_warehouse_locations(
                search=None,
                include_inactive=False,
                cursor=None,
                limit=50,
                db=db,
                access=access,
            ),
            lambda: product_locations.list_product_locations(
                location_id=a.location_id,
                product_variant_id=None,
                cursor=None,
                limit=50,
                db=db,
                access=access,
            ),
            lambda: stocktake.start_unified_stocktake(
                StocktakeStartCommand(
                    request_id=uuid4(),
                    location_id=a.location_id,
                    stocktake_type="FULL_COUNT",
                    product_variant_id=None,
                    batch_id=None,
                    related_work_session_id=None,
                ),
                db=db,
                access=access,
                legacy_actor=a.ordinary.operational_driver,
            ),
        )
        for call in denied_calls:
            error = await _assert_http(call, 403)
            detail = _json(error.detail)
            for forbidden in (
                "__WANASAH_NOLOT__",
                "unit_cost",
                "total_cost",
                "supplier_name",
                "password_hash",
            ):
                assert forbidden not in detail
