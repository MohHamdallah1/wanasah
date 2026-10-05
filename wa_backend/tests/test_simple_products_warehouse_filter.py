import os
from types import SimpleNamespace

os.environ.setdefault("SECRET_KEY", "WarehouseFilterTestSecretKeyAa1234567890")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest
from fastapi import HTTPException
from sqlalchemy import true
from sqlalchemy.dialects import postgresql

import api.simple_products as simple_products
import domains.inventory_catalog_presence as inventory_presence


class _Scalars:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class _Db:
    def __init__(self, readable_ids):
        self.readable_ids = readable_ids
        self.validation_sql = None

    async def scalars(self, statement):
        self.validation_sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        return _Scalars(self.readable_ids)


class _Access:
    def __init__(self, _db, _actor):
        pass

    def location_filter(self, _permission, _column=None):
        return true()


@pytest.mark.asyncio
async def test_multi_warehouse_filter_is_permission_scoped_set_intersection(monkeypatch):
    monkeypatch.setattr(inventory_presence, "InventoryAccess", _Access)
    db = _Db([3, 7])

    statement = await inventory_presence.variant_ids_present_in_all_warehouses(
        db,
        actor=SimpleNamespace(company_id=2, id=9, is_admin=False),
        company_id=2,
        warehouse_ids=(3, 7),
    )

    validation_sql = " ".join(db.validation_sql.split()).lower()
    assert "inventory_locations.company_id = 2" in validation_sql
    assert "inventory_locations.id in (3, 7)" in validation_sql
    assert "inventory_locations.location_type = 'warehouse'" in validation_sql

    sql = " ".join(
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).split()
    ).lower()
    assert "inventory_balances.company_id = 2" in sql
    assert "inventory_balances.location_id in (3, 7)" in sql
    assert "inventory_balances.on_hand_quantity > 0" in sql
    assert "group by inventory_balances.product_variant_id" in sql
    assert "count(distinct(inventory_balances.location_id)) = 2" in sql


@pytest.mark.asyncio
async def test_multi_warehouse_filter_refuses_any_unreadable_selected_location(monkeypatch):
    monkeypatch.setattr(inventory_presence, "InventoryAccess", _Access)
    db = _Db([3])
    with pytest.raises(inventory_presence.InventoryCatalogPresenceForbidden) as exc:
        await inventory_presence.variant_ids_present_in_all_warehouses(
            db,
            actor=SimpleNamespace(company_id=2, id=9, is_admin=False),
            company_id=2,
            warehouse_ids=(3, 7),
        )
    assert isinstance(exc.value, inventory_presence.InventoryCatalogPresenceForbidden)


def test_warehouse_ids_are_canonical_bounded_and_cursor_scoped():
    assert simple_products._normalized_warehouse_ids([7, 3, 7]) == (3, 7)
    with pytest.raises(HTTPException):
        simple_products._normalized_warehouse_ids([0])
    with pytest.raises(HTTPException):
        simple_products._normalized_warehouse_ids(list(range(1, 22)))

    common = dict(
        company_id=2,
        search=None,
        family_id=None,
        lifecycle=None,
        tracking_type=None,
        simple_compatible=None,
        has_barcode=None,
        has_price=None,
        lot_tracked=None,
        expiry_tracked=None,
        sort_by="id",
        sort_dir="asc",
        limit=100,
    )
    scope_a = simple_products._product_cursor_scope(**common, warehouse_ids=(3, 7))
    scope_b = simple_products._product_cursor_scope(**common, warehouse_ids=(3,))
    assert scope_a != scope_b
