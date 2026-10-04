import ast
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func as sa_func, Column, Date, MetaData, Table, and_, create_engine, literal, select

from domains.batch_reservation_contracts import OWNER_PREVIEW_LIMIT
from domains.batch_reservation_evidence import reservation_evidence
from domains.dispatch_reservations import variant_reservation_owner_projection
from inventory_access import InventoryAccess
from models import (
    Company, DispatchRoute, InventoryBalance, InventoryLocation, InventoryMovement, InventoryStockPolicy,
    InventoryTransferHeader, InventoryTransferLine, Permission, ProductBatch,
    ProductVariant, UOM, UserLocationAccess, UserRole, role_permissions,
)
from quantity import canonical_quantity
from domains.inventory_rules import batch_metadata_is_sellable
from schemas import WarehouseWholeProductIssueSourcesResponse

SPECIAL_TRANSFER_PERMISSION = {
    "RETURN_TO_VENDOR": "transfer.special.return_to_vendor",
    "QUARANTINE": "transfer.special.quarantine",
    "RECALL_RETURN": "transfer.special.recall_return",
    "DISPOSAL": "transfer.special.disposal",
}

def no_special_purposes(**_kwargs):
    return ()



async def no_special_transfer_destinations(_db, *, company_id):
    return {}


class _TimezoneExpression:
    def cast(self, _type):
        return literal(date(2026, 10, 4), type_=Date)


class _EndpointFunc:
    @staticmethod
    def current_timestamp():
        return literal("2026-10-04T00:00:00")

    @staticmethod
    def timezone(_timezone, _timestamp):
        return _TimezoneExpression()

    @staticmethod
    def coalesce(*values):
        return sa_func.coalesce(*values)


async def no_completion_blockers(_db, _company_id, _variant_id):
    return []


async def inventory_completion_blocker(_db, _company_id, _variant_id):
    return [{"code": "INVENTORY_BALANCE", "count": 1, "sample_id": 1}]


def endpoint(blocker_reader=no_completion_blockers):
    path = Path(__file__).parents[1] / "api/warehouse/live_stock.py"
    node = next(
        n for n in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(n, ast.AsyncFunctionDef)
        and n.name == "get_whole_product_quality_issue_sources"
    )
    node.decorator_list = []
    node.args.defaults = []
    for arg in node.args.args:
        arg.annotation = None
    namespace = dict(
        InventoryAccess=InventoryAccess,
        ProductVariant=ProductVariant,
        ProductBatch=ProductBatch,
        InventoryLocation=InventoryLocation,
        InventoryBalance=InventoryBalance,
        InventoryStockPolicy=InventoryStockPolicy,
        UOM=UOM,
        Company=Company,
        select=select,
        and_=and_,
        func=_EndpointFunc,
        Date=Date,
        Decimal=Decimal,
        canonical_quantity=canonical_quantity,
        HTTPException=HTTPException,
        reservation_evidence=reservation_evidence,
        OWNER_PREVIEW_LIMIT=OWNER_PREVIEW_LIMIT,
        variant_reservation_owner_projection=variant_reservation_owner_projection,
        recall_completion_blockers=blocker_reader,
        batch_metadata_is_sellable=batch_metadata_is_sellable,
        allowed_special_transfer_purposes=no_special_purposes,
        SPECIAL_TRANSFER_PERMISSION=SPECIAL_TRANSFER_PERMISSION,
        read_special_transfer_destinations=no_special_transfer_destinations,
                inventory_business_error=lambda code, message, context=None: {
            "code": code,
            "message": message,
            "context": context,
        },
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["get_whole_product_quality_issue_sources"]


class ReadSession:
    def __init__(self, connection):
        self.connection = connection

    async def execute(self, statement):
        return self.connection.execute(statement)

    async def scalar(self, statement):
        return self.connection.scalar(statement)

    async def scalars(self, statement):
        return self.connection.scalars(statement)


@pytest.fixture
def store():
    metadata = MetaData()
    definitions = [
        (ProductBatch, "id company_id product_variant_id batch_number production_date expiry_date disposition disposition_reason disposition_revision is_active"),
        (ProductVariant, "id company_id version base_uom_id lifecycle_status operational_hold expiry_control_mode"),
        (UOM, "id code"),
        (Company, "id timezone"),
        (InventoryLocation, "id company_id name location_type is_active vehicle_id"),
        (InventoryBalance, "id company_id location_id product_variant_id batch_id stock_status on_hand_quantity reserved_quantity"),
        (InventoryStockPolicy, "id company_id location_id product_variant_id minimum_remaining_shelf_life_days is_active"),
        (InventoryTransferHeader, "id company_id source_location_id destination_location_id reference_number workflow_type status transfer_purpose work_session_id expected_receiver_id dispatched_by"),
        (InventoryTransferLine, "id company_id transfer_header_id product_variant_id batch_id source_stock_status quantity"),
        (InventoryMovement, "id company_id transfer_header_id product_variant_id batch_id source_location_id destination_location_id source_stock_status destination_stock_status movement_kind reservation_action reference_type reference_id quantity work_session_id"),
        (DispatchRoute, "id company_id work_session_id driver_id vehicle_id source_location_id"),
        (Permission, "id code"),
        (UserRole, "company_id driver_id role_id"),
        (UserLocationAccess, "company_id driver_id role_id location_id"),
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

        insert(Company, id=1, timezone="UTC")
        insert(UOM, id=1, code="EA")
        insert(ProductVariant, id=101, company_id=1, version=7, base_uom_id=1, lifecycle_status="ACTIVE", operational_hold="RECALL", expiry_control_mode="REQUIRED")
        for batch_id in (11, 12):
            insert(
                ProductBatch,
                id=batch_id,
                company_id=1,
                product_variant_id=101,
                batch_number=f"LOT-{batch_id}",
                production_date=date(2026, 9, 1),
                expiry_date=date(2027, 9, 1),
                disposition="RELEASED",
                disposition_reason=None,
                disposition_revision=1,
            )
        insert(InventoryLocation, id=1, company_id=1, name="Warehouse A", location_type="WAREHOUSE", is_active=True, vehicle_id=None)
        insert(InventoryLocation, id=2, company_id=1, name="Vehicle 2", location_type="VEHICLE", is_active=True, vehicle_id=20)
        insert(InventoryLocation, id=3, company_id=1, name="Warehouse B", location_type="WAREHOUSE", is_active=True, vehicle_id=None)
        insert(InventoryBalance, id=1, company_id=1, location_id=1, product_variant_id=101, batch_id=11, stock_status="AVAILABLE", on_hand_quantity=Decimal("10"), reserved_quantity=Decimal("0"))
        insert(InventoryBalance, id=2, company_id=1, location_id=2, product_variant_id=101, batch_id=11, stock_status="AVAILABLE", on_hand_quantity=Decimal("3"), reserved_quantity=Decimal("0"))
        insert(InventoryBalance, id=3, company_id=1, location_id=3, product_variant_id=101, batch_id=12, stock_status="AVAILABLE", on_hand_quantity=Decimal("7"), reserved_quantity=Decimal("0"))
        codes = ("inventory.read", "dispatch.read", "transfer.cancel")
        for i, code in enumerate(codes, 1):
            insert(Permission, id=i, code=code)
        yield SimpleNamespace(connection=connection, db=ReadSession(connection), tables=tables, insert=insert, codes=codes)
    engine.dispose()


def actor(*, admin=True):
    return SimpleNamespace(company_id=1, id=17, is_admin=admin)


def grant(store, code, location):
    role = store.codes.index(code) + 100 + location * 10
    store.insert(UserLocationAccess, company_id=1, driver_id=17, role_id=role, location_id=location)
    store.connection.execute(store.tables[role_permissions.name].insert(), {
        "company_id": 1,
        "role_id": role,
        "permission_id": store.codes.index(code) + 1,
    })


async def read(store, *, user=None, cursor=None, limit=25, blocker_reader=no_completion_blockers):
    raw = await endpoint(blocker_reader)(101, cursor, limit, store.db, user or actor())
    return WarehouseWholeProductIssueSourcesResponse.model_validate(raw).model_dump(mode="json")


@pytest.mark.asyncio
async def test_whole_product_issue_lists_warehouse_and_vehicle_separately(store):
    result = await read(store)
    assert result["product_variant_id"] == 101
    assert result["ready_to_resume_sales"] is True
    assert [item["batch_id"] for item in result["batches"]] == [11, 12]
    sources = result["batches"][0]["sources"]
    assert [(item["location_id"], item["location_type"]) for item in sources] == [
        (2, "VEHICLE"),
        (1, "WAREHOUSE"),
    ]


@pytest.mark.asyncio
async def test_whole_product_issue_respects_location_permissions_and_backend_readiness(store):
    grant(store, "inventory.read", 1)
    result = await read(store, user=actor(admin=False), blocker_reader=inventory_completion_blocker)
    assert [item["batch_id"] for item in result["batches"]] == [11]
    assert [item["location_id"] for item in result["batches"][0]["sources"]] == [1]
    assert result["ready_to_resume_sales"] is False
    assert result["company_requirements_remaining"] is True


@pytest.mark.asyncio
async def test_whole_product_issue_uses_bounded_batch_cursor(store):
    first = await read(store, limit=1)
    assert first["has_more"] is True
    assert first["next_cursor"] == 11
    assert [item["batch_id"] for item in first["batches"]] == [11]
    second = await read(store, cursor=first["next_cursor"], limit=1)
    assert second["has_more"] is False
    assert second["next_cursor"] is None
    assert [item["batch_id"] for item in second["batches"]] == [12]
