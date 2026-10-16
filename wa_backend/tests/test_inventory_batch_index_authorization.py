from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

os.environ.setdefault(
    "SECRET_KEY",
    "Cp2BatchIndexSyntheticKeyAbc123456789012345678901234567890",
)
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://cp2@127.0.0.1:1/cp2",
)

from api.warehouse.batch_index import _require_warehouse_inventory_read
from domains.authorization.backoffice_access import BackofficeCapabilityAccessRejected


class _Result:
    def __init__(self, row):
        self.row = row

    def one_or_none(self):
        return self.row


class _Db:
    def __init__(self, row):
        self.row = row
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _Result(self.row)


class _Access:
    company_id = 7

    def __init__(self, *, reject=False):
        self.reject = reject
        self.calls = []

    async def require(self, code, location_id=None, *, any_location=False):
        self.calls.append((code, location_id, any_location))
        if self.reject:
            raise BackofficeCapabilityAccessRejected


@pytest.mark.asyncio
async def test_exact_selected_warehouse_inventory_read_is_required():
    db = _Db(SimpleNamespace(location_type="WAREHOUSE", is_active=True))
    access = _Access()
    await _require_warehouse_inventory_read(
        db,
        company_id=access.company_id,
        location_id=41,
        access=access,
    )
    assert access.calls == [("inventory.read", 41, False)]
    sql = str(
        db.statements[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "inventory_locations.company_id = 7" in sql
    assert "inventory_locations.id = 41" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row",
    [
        None,
        SimpleNamespace(location_type="WAREHOUSE", is_active=False),
        SimpleNamespace(location_type="VEHICLE", is_active=True),
    ],
)
async def test_foreign_inactive_or_nonwarehouse_location_is_tenant_opaque(row):
    db = _Db(row)
    access = _Access()
    with pytest.raises(HTTPException) as exc:
        await _require_warehouse_inventory_read(
            db,
            company_id=access.company_id,
            location_id=88,
            access=access,
        )
    assert exc.value.status_code == 404
    assert access.calls == []
    assert "company" not in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_missing_exact_location_permission_is_denied_without_owner_shortcut():
    db = _Db(SimpleNamespace(location_type="WAREHOUSE", is_active=True))
    access = _Access(reject=True)
    with pytest.raises(HTTPException) as exc:
        await _require_warehouse_inventory_read(
            db,
            company_id=access.company_id,
            location_id=41,
            access=access,
        )
    assert exc.value.status_code == 403
    assert access.calls == [("inventory.read", 41, False)]


def test_routes_use_access_company_id_and_no_legacy_or_owner_authority():
    source = (
        Path(__file__).resolve().parents[1]
        / "api"
        / "warehouse"
        / "batch_index.py"
    ).read_text(encoding="utf-8")
    assert source.count("company_id = access.company_id") == 2
    assert 'access.require("inventory.read", location_id=int(location_id))' in source
    assert "get_current_backoffice_legacy_driver" not in source
    assert "legacy_actor" not in source
    assert "actor.company_id" not in source
    assert "is_company_owner" not in source
    assert ".is_admin" not in source


def test_all_tenant_sources_are_explicitly_company_scoped():
    source = (
        Path(__file__).resolve().parents[1]
        / "api"
        / "warehouse"
        / "batch_index.py"
    ).read_text(encoding="utf-8")
    for guard in (
        "InventoryBalance.company_id == int(company_id)",
        "InventoryLocation.company_id == int(company_id)",
        "ProductBatch.company_id == company_id",
        "ProductVariant.company_id == company_id",
        "Product.company_id == company_id",
        "InventoryStockPolicy.company_id == company_id",
    ):
        assert guard in source
