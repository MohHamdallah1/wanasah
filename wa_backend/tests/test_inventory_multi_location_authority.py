from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import Column, MetaData, Table, create_engine

from inventory_access import InventoryAccess
from models import InventoryLocation, Permission, UserLocationAccess, UserRole, role_permissions


class ReadSession:
    def __init__(self, connection):
        self.connection = connection

    async def scalar(self, statement):
        return self.connection.scalar(statement)


@pytest.fixture
def access_store():
    metadata = MetaData()
    definitions = [
        (InventoryLocation, "id company_id name location_type is_active"),
        (Permission, "id code"),
        (UserLocationAccess, "company_id driver_id role_id location_id"),
        (UserRole, "company_id driver_id role_id"),
    ]
    tables = {}
    for model, names in definitions:
        original = model.__table__
        tables[original.name] = Table(
            original.name,
            metadata,
            *(Column(name, original.c[name].type) for name in names.split()),
        )
    tables[role_permissions.name] = Table(
        role_permissions.name,
        metadata,
        *(Column(name, role_permissions.c[name].type)
          for name in ("company_id", "role_id", "permission_id")),
    )
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        metadata.create_all(connection)
        def insert(model, **values):
            connection.execute(tables[model.__table__.name].insert(), values)

        insert(InventoryLocation, id=1, company_id=1, name="Warehouse A", location_type="WAREHOUSE", is_active=True)
        insert(InventoryLocation, id=2, company_id=1, name="Warehouse B", location_type="WAREHOUSE", is_active=True)
        insert(Permission, id=1, code="transfer.send")
        insert(Permission, id=2, code="transfer.destination")
        for role_id, permission_id in ((101, 1), (102, 2)):
            insert(UserLocationAccess, company_id=1, driver_id=17, role_id=role_id, location_id=1)
            connection.execute(tables[role_permissions.name].insert(), {
                "company_id": 1,
                "role_id": role_id,
                "permission_id": permission_id,
            })
        yield SimpleNamespace(
            db=ReadSession(connection),
            actor=SimpleNamespace(company_id=1, id=17, is_admin=False),
        )
    engine.dispose()


@pytest.mark.asyncio
async def test_exact_location_permissions_do_not_leak_between_warehouses(access_store):
    access = InventoryAccess(access_store.db, access_store.actor)
    await access.require("transfer.send", 1)
    await access.require("transfer.destination", 1)

    for code in ("transfer.send", "transfer.destination"):
        with pytest.raises(HTTPException) as exc:
            await access.require(code, 2)
        assert exc.value.status_code == 403


def test_special_transfer_rechecks_exact_source_and_server_derived_destination():
    path = Path(__file__).parents[1] / "api/warehouse/transfers.py"
    source = " ".join(path.read_text(encoding="utf-8").split())
    assert 'await access.require("transfer.send", payload.source_location_id)' in source
    assert 'await access.require( "transfer.destination", destination_location_id, )' in source
