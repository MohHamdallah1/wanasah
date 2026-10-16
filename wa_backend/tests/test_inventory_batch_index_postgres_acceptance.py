from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.warehouse.batch_index import (
    get_warehouse_inventory_batch_index_cursor,
    get_warehouse_inventory_batch_index_summary,
)
from api.warehouse.live_stock import get_warehouse_inventory_batches
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from models import (
    Company,
    InventoryBalance,
    InventoryLocation,
    Product,
    ProductBatch,
    ProductVariant,
    UOM,
)
from schemas import (
    WarehouseInventoryBatchIndexCursorPage,
    WarehouseInventoryBatchIndexSummaryResponse,
)


pytestmark = pytest.mark.asyncio
_INTERNAL_PREFIX = "__WANASAH_NOLOT__:"


def _owner_access(db: AsyncSession, company_id: int) -> BackofficeCapabilityAccess:
    return BackofficeCapabilityAccess(
        db=db,
        subject=BackofficeAuthorizationSubject(
            principal_id=company_id * 10 + 1,
            backoffice_user_id=company_id * 10 + 2,
            company_id=company_id,
            is_company_owner=True,
            legacy_grant_driver_id=None,
        ),
    )


async def _cursor(db: AsyncSession, access: BackofficeCapabilityAccess, location_id: int, **overrides):
    values = {
        "cursor": None,
        "limit": 50,
        "search": None,
        "expiry_state": "ALL",
        "expiry_warning_days": None,
        "sellability": "ALL",
        "disposition": None,
        "has_unavailable": None,
        "has_damaged": None,
        "has_disposal_pending": None,
        "family_id": None,
        "product_variant_id": None,
        "sort": "EXPIRY_ASC",
    }
    values.update(overrides)
    return await get_warehouse_inventory_batch_index_cursor(
        location_id=location_id,
        db=db,
        access=access,
        **values,
    )


async def _summary(db: AsyncSession, access: BackofficeCapabilityAccess, location_id: int, **overrides):
    values = {
        "expiry_warning_days": 10,
        "search": None,
        "family_id": None,
        "product_variant_id": None,
    }
    values.update(overrides)
    return await get_warehouse_inventory_batch_index_summary(
        location_id=location_id,
        db=db,
        access=access,
        **values,
    )


async def _seed(db: AsyncSession):
    today = await db.scalar(select(func.current_date()))
    now = datetime.utcnow()

    db.add_all(
        [
            Company(id=9101, name="CP2 Tenant A", company_code="CP2-A", timezone="UTC"),
            Company(id=9201, name="CP2 Tenant B", company_code="CP2-B", timezone="UTC"),
            UOM(id=9101, name="CP2 Piece", code="CP2-PC"),
        ]
    )
    await db.flush()

    db.add_all(
        [
            InventoryLocation(id=9131, company_id=9101, name="A Warehouse", code="CP2-A-W1", location_type="WAREHOUSE", is_active=True),
            InventoryLocation(id=9132, company_id=9101, name="A Warehouse 2", code="CP2-A-W2", location_type="WAREHOUSE", is_active=True),
            InventoryLocation(id=9231, company_id=9201, name="B Warehouse", code="CP2-B-W1", location_type="WAREHOUSE", is_active=True),
            Product(id=9110, company_id=9101, code="CP2-MILK", name="Milk Family"),
            Product(id=9120, company_id=9101, code="CP2-OTHER", name="Other Family"),
            Product(id=9210, company_id=9201, code="CP2-FOREIGN", name="Foreign Family"),
        ]
    )
    await db.flush()

    db.add_all(
        [
            ProductVariant(
                id=9111,
                company_id=9101,
                product_id=9110,
                base_uom_id=9101,
                name="Milk Premium",
                sku="CP2-MILK-100",
                lot_control_mode="REQUIRED",
                expiry_control_mode="REQUIRED",
                lifecycle_status="ACTIVE",
                published_at=now,
                quantity_scale=2,
                quantity_step=Decimal("0.25"),
            ),
            ProductVariant(
                id=9121,
                company_id=9101,
                product_id=9120,
                base_uom_id=9101,
                name="Anonymous Optional",
                sku="CP2-ANON",
                lot_control_mode="OPTIONAL",
                expiry_control_mode="OPTIONAL",
                lifecycle_status="ACTIVE",
                published_at=now,
                quantity_scale=0,
                quantity_step=Decimal("1"),
            ),
            ProductVariant(
                id=9211,
                company_id=9201,
                product_id=9210,
                base_uom_id=9101,
                name="Foreign Milk Premium",
                sku="CP2-FOREIGN-100",
                lot_control_mode="REQUIRED",
                expiry_control_mode="REQUIRED",
                lifecycle_status="ACTIVE",
                published_at=now,
            ),
        ]
    )
    await db.flush()

    batches = [
        ProductBatch(id=9141, company_id=9101, product_variant_id=9111, batch_number="LOT-EXPIRED", production_date=today - timedelta(days=20), expiry_date=today - timedelta(days=1), disposition="RELEASED", is_active=True),
        ProductBatch(id=9142, company_id=9101, product_variant_id=9121, batch_number=f"{_INTERNAL_PREFIX}CP2-ANON", production_date=None, expiry_date=None, disposition="RELEASED", is_active=True),
        ProductBatch(id=9143, company_id=9101, product_variant_id=9111, batch_number="LOT-QUARANTINE", production_date=None, expiry_date=today + timedelta(days=5), disposition="QUARANTINED", disposition_reason="quality hold", is_active=True),
        ProductBatch(id=9144, company_id=9101, product_variant_id=9111, batch_number="LOT-BLOCKED", production_date=None, expiry_date=today + timedelta(days=20), disposition="BLOCKED", disposition_reason="blocked", is_active=True),
        ProductBatch(id=9145, company_id=9101, product_variant_id=9111, batch_number="100%_A\\B", production_date=None, expiry_date=today + timedelta(days=10), disposition="RELEASED", is_active=True),
        ProductBatch(id=9146, company_id=9101, product_variant_id=9111, batch_number="LOT-EQUAL", production_date=None, expiry_date=today + timedelta(days=10), disposition="RELEASED", is_active=True),
        ProductBatch(id=9147, company_id=9101, product_variant_id=9121, batch_number="LOT-NODATE", production_date=None, expiry_date=None, disposition="RELEASED", is_active=True),
        ProductBatch(id=9150, company_id=9101, product_variant_id=9111, batch_number="LOT-OTHER-LOCATION", production_date=None, expiry_date=today + timedelta(days=8), disposition="RELEASED", is_active=True),
        ProductBatch(id=9241, company_id=9201, product_variant_id=9211, batch_number="FOREIGN-SECRET", production_date=None, expiry_date=today + timedelta(days=3), disposition="RELEASED", is_active=True),
    ]
    db.add_all(batches)
    await db.flush()

    balances = [
        InventoryBalance(id=9161, company_id=9101, location_id=9131, product_variant_id=9111, batch_id=9141, stock_status="AVAILABLE", on_hand_quantity=Decimal("4"), reserved_quantity=Decimal("0")),
        InventoryBalance(id=9162, company_id=9101, location_id=9131, product_variant_id=9121, batch_id=9142, stock_status="AVAILABLE", on_hand_quantity=Decimal("2"), reserved_quantity=Decimal("0")),
        InventoryBalance(id=9163, company_id=9101, location_id=9131, product_variant_id=9111, batch_id=9143, stock_status="QUARANTINED", on_hand_quantity=Decimal("3"), reserved_quantity=Decimal("0")),
        InventoryBalance(id=9164, company_id=9101, location_id=9131, product_variant_id=9111, batch_id=9144, stock_status="BLOCKED", on_hand_quantity=Decimal("4"), reserved_quantity=Decimal("0")),
        InventoryBalance(id=9165, company_id=9101, location_id=9131, product_variant_id=9111, batch_id=9145, stock_status="AVAILABLE", on_hand_quantity=Decimal("10"), reserved_quantity=Decimal("2")),
        InventoryBalance(id=9166, company_id=9101, location_id=9131, product_variant_id=9111, batch_id=9145, stock_status="QUARANTINED", on_hand_quantity=Decimal("3"), reserved_quantity=Decimal("0")),
        InventoryBalance(id=9167, company_id=9101, location_id=9131, product_variant_id=9111, batch_id=9145, stock_status="BLOCKED", on_hand_quantity=Decimal("4"), reserved_quantity=Decimal("0")),
        InventoryBalance(id=9168, company_id=9101, location_id=9131, product_variant_id=9111, batch_id=9145, stock_status="RECALLED", on_hand_quantity=Decimal("5"), reserved_quantity=Decimal("0")),
        InventoryBalance(id=9169, company_id=9101, location_id=9131, product_variant_id=9111, batch_id=9145, stock_status="DAMAGED", on_hand_quantity=Decimal("6"), reserved_quantity=Decimal("0")),
        InventoryBalance(id=9170, company_id=9101, location_id=9131, product_variant_id=9111, batch_id=9145, stock_status="DISPOSAL_PENDING", on_hand_quantity=Decimal("7"), reserved_quantity=Decimal("0")),
        InventoryBalance(id=9171, company_id=9101, location_id=9131, product_variant_id=9111, batch_id=9146, stock_status="AVAILABLE", on_hand_quantity=Decimal("6"), reserved_quantity=Decimal("0")),
        InventoryBalance(id=9172, company_id=9101, location_id=9131, product_variant_id=9121, batch_id=9147, stock_status="AVAILABLE", on_hand_quantity=Decimal("5"), reserved_quantity=Decimal("0")),
        InventoryBalance(id=9173, company_id=9101, location_id=9132, product_variant_id=9111, batch_id=9150, stock_status="AVAILABLE", on_hand_quantity=Decimal("9"), reserved_quantity=Decimal("0")),
        InventoryBalance(id=9271, company_id=9201, location_id=9231, product_variant_id=9211, batch_id=9241, stock_status="AVAILABLE", on_hand_quantity=Decimal("99"), reserved_quantity=Decimal("0")),
    ]
    db.add_all(balances)
    await db.flush()
    return today


def _item(response: dict, batch_id: int) -> dict:
    return next(item for item in response["items"] if item["batch_id"] == batch_id)


async def test_cp2_batch_index_real_postgres_acceptance():
    if os.getenv("CP2_POSTGRES_ACCEPTANCE") != "1":
        pytest.skip("requires the isolated CP2 GitHub-hosted PostgreSQL service")

    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    statements: list[str] = []

    def _count(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _count)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with maker(bind=connection) as db:
                    today = await _seed(db)
                    owner = _owner_access(db, 9101)

                    # Authoritative warehouse-wide read: only positive on-hand batch rows at this exact warehouse.
                    all_rows = await _cursor(db, owner, 9131)
                    ids = {row["batch_id"] for row in all_rows["items"]}
                    assert ids == {9141, 9142, 9143, 9144, 9145, 9146, 9147}
                    assert 9150 not in ids and 9241 not in ids

                    # Anonymous internal identity is never public and nullable dates serialize as JSON null.
                    anonymous = _item(all_rows, 9142)
                    assert anonymous["batch_number"] is None
                    page_json = WarehouseInventoryBatchIndexCursorPage.model_validate(all_rows).model_dump(mode="json")
                    encoded_page = json.dumps(page_json, sort_keys=True)
                    assert _INTERNAL_PREFIX not in encoded_page
                    serialized_anon = next(row for row in page_json["items"] if row["batch_id"] == 9142)
                    assert serialized_anon["production_date"] is None
                    assert serialized_anon["expiry_date"] is None

                    internal_search = await _cursor(db, owner, 9131, search="__WANASAH_NOLOT__")
                    assert internal_search["items"] == []
                    assert _INTERNAL_PREFIX not in json.dumps(internal_search, default=str)

                    # Exact-location tenant isolation and cross-company fail closed.
                    other_location = await _cursor(db, owner, 9132)
                    assert {row["batch_id"] for row in other_location["items"]} == {9150}
                    with pytest.raises(HTTPException) as foreign_location:
                        await _cursor(db, owner, 9231)
                    assert foreign_location.value.status_code == 404
                    foreign_owner = _owner_access(db, 9201)
                    foreign_rows = await _cursor(db, foreign_owner, 9231)
                    assert {row["batch_id"] for row in foreign_rows["items"]} == {9241}
                    assert "FOREIGN-SECRET" not in json.dumps(all_rows, default=str)

                    # SQL-owned filters are applied before LIMIT/keyset pagination.
                    expiry_page = await _cursor(db, owner, 9131, limit=1, expiry_state="EXPIRING_SOON", expiry_warning_days=10)
                    assert [row["batch_id"] for row in expiry_page["items"]] == [9143]
                    blocked_page = await _cursor(db, owner, 9131, limit=1, disposition="BLOCKED")
                    assert [row["batch_id"] for row in blocked_page["items"]] == [9144]
                    sellable_page = await _cursor(db, owner, 9131, limit=1, sellability="SELLABLE")
                    assert sellable_page["items"][0]["batch_id"] not in {9141, 9143, 9144}
                    assert sellable_page["items"][0]["sellability_state"] == "SELLABLE"

                    # Multi-token search ANDs tokens on the same row; LIKE metacharacters remain literal.
                    multi = await _cursor(db, owner, 9131, search="milk 100")
                    assert {row["batch_id"] for row in multi["items"]} == {9145}
                    for literal in ("%", "_", "\\"):
                        literal_rows = await _cursor(db, owner, 9131, search=literal)
                        assert {row["batch_id"] for row in literal_rows["items"]} == {9145}

                    # Equal sort values remain deterministic through the batch_id tiebreaker and keyset continuation.
                    first = await _cursor(
                        db,
                        owner,
                        9131,
                        limit=1,
                        expiry_state="EXPIRING_SOON",
                        expiry_warning_days=10,
                        disposition="RELEASED",
                        product_variant_id=9111,
                        sort="EXPIRY_ASC",
                    )
                    assert first["items"][0]["batch_id"] == 9145
                    assert first["has_more"] is True and first["next_cursor"]
                    assert _INTERNAL_PREFIX not in first["next_cursor"]
                    second = await _cursor(
                        db,
                        owner,
                        9131,
                        cursor=first["next_cursor"],
                        limit=1,
                        expiry_state="EXPIRING_SOON",
                        expiry_warning_days=10,
                        disposition="RELEASED",
                        product_variant_id=9111,
                        sort="EXPIRY_ASC",
                    )
                    assert second["items"][0]["batch_id"] == 9146
                    assert {first["items"][0]["batch_id"]}.isdisjoint({second["items"][0]["batch_id"]})

                    # Cursor scope is bound to every filter/sort/location dimension.
                    for changed in (
                        {"search": "milk"},
                        {"sort": "PRODUCT_ASC"},
                    ):
                        with pytest.raises(HTTPException) as mismatch:
                            await _cursor(db, owner, 9131, cursor=first["next_cursor"], limit=1, expiry_state="EXPIRING_SOON", expiry_warning_days=10, disposition="RELEASED", product_variant_id=9111, **changed)
                        assert mismatch.value.status_code == 400
                    with pytest.raises(HTTPException) as location_mismatch:
                        await _cursor(db, owner, 9132, cursor=first["next_cursor"], limit=1, expiry_state="EXPIRING_SOON", expiry_warning_days=10, disposition="RELEASED", product_variant_id=9111)
                    assert location_mismatch.value.status_code == 400

                    # Summary is computed from the same authoritative batch/inventory dataset.
                    summary = await _summary(db, owner, 9131)
                    assert summary == {
                        "location_id": 9131,
                        "as_of_date": today,
                        "total_relevant_batches": 7,
                        "expired_count": 1,
                        "expiring_soon_count": 3,
                        "non_sellable_count": 3,
                        "quarantined_count": 1,
                        "blocked_count": 1,
                        "recalled_count": 0,
                        "damaged_or_disposal_attention_count": 1,
                    }
                    summary_json = WarehouseInventoryBatchIndexSummaryResponse.model_validate(summary).model_dump(mode="json")
                    assert summary_json["total_relevant_batches"] == 7

                    # Physical and business quantity partitions reconcile exactly for a mixed-status batch.
                    mixed = _item(all_rows, 9145)
                    assert mixed["on_hand_quantity"] == "35"
                    assert mixed["reserved_quantity"] == "2"
                    assert mixed["available_status_quantity"] == "10"
                    assert mixed["available_for_sale_quantity"] == "8"
                    assert mixed["unavailable_quantity"] == "25"
                    assert mixed["quarantined_quantity"] == "3"
                    assert mixed["blocked_quantity"] == "4"
                    assert mixed["recalled_quantity"] == "5"
                    assert mixed["damaged_quantity"] == "6"
                    assert mixed["disposal_pending_quantity"] == "7"
                    assert Decimal(mixed["available_status_quantity"]) + Decimal(mixed["quarantined_quantity"]) + Decimal(mixed["blocked_quantity"]) + Decimal(mixed["recalled_quantity"]) + Decimal(mixed["damaged_quantity"]) + Decimal(mixed["disposal_pending_quantity"]) == Decimal(mixed["on_hand_quantity"])
                    assert Decimal(mixed["available_for_sale_quantity"]) + Decimal(mixed["unavailable_quantity"]) + Decimal(mixed["reserved_quantity"]) == Decimal(mixed["on_hand_quantity"])

                    # The pre-existing product-first drill-down executes unchanged against the same real PostgreSQL data.
                    drill_down = await get_warehouse_inventory_batches(
                        product_variant_id=9111,
                        location_id=9131,
                        cursor=None,
                        limit=100,
                        db=db,
                        access=owner,
                    )
                    assert {row["batch_id"] for row in drill_down["items"]} >= {9141, 9143, 9144, 9145, 9146}

                    # Count every SQL statement for one cursor read, then prove page size does not cause per-row growth.
                    statements.clear()
                    await _cursor(db, owner, 9131, limit=1)
                    count_limit_1 = len(statements)
                    statements.clear()
                    await _cursor(db, owner, 9131, limit=7)
                    count_limit_7 = len(statements)
                    print(f"CP2_SQL_COUNT_CURSOR_READ_LIMIT_1={count_limit_1}")
                    print(f"CP2_SQL_COUNT_CURSOR_READ_LIMIT_7={count_limit_7}")
                    assert count_limit_1 == count_limit_7
                    assert count_limit_1 <= 5
            finally:
                await transaction.rollback()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _count)
        await engine.dispose()
