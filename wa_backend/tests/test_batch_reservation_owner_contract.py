"""Execute the actual read endpoint on synthetic SQLite fixtures only.

No application startup, workers, mutations, or production database access.
PostgreSQL RLS and concurrent-command acceptance remain deployment gates.
"""
import ast
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func as sa_func, Column, Date, MetaData, Table, and_, create_engine, literal, select
from sqlalchemy.dialects import postgresql

from domains.batch_reservation_contracts import OWNER_PREVIEW_LIMIT, ReservationEvidence
from domains.batch_reservation_evidence import reservation_evidence
from domains.dispatch_reservations import reservation_owner_projection
from inventory_access import InventoryAccess
from models import (
    Company, DispatchRoute, InventoryBalance, InventoryLocation, InventoryMovement, InventoryStockPolicy,
    InventoryTransferHeader, InventoryTransferLine, Permission, ProductBatch,
    ProductVariant, UOM, UserLocationAccess, UserRole, role_permissions,
)
from quantity import canonical_quantity
from domains.inventory_rules import batch_metadata_is_sellable
from schemas import WarehouseBatchStockSourcesResponse

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


async def no_terminal_origin_availability(_db, **_kwargs):
    return {}


def no_quality_action_availability(**_kwargs):
    purposes = ("QUARANTINE", "RECALL_RETURN", "RETURN_TO_VENDOR", "DISPOSAL")
    return {
        "allowed_purposes": [],
        "special_actions": [
            {
                "purpose": purpose,
                "allowed": False,
                "eligible_quantity": "0",
                "reason_code": "STATE_RESTRICTION",
            }
            for purpose in purposes
        ],
        "terminal_actions": [],
    }


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


def endpoint():
    # Isolate the real function from API startup/dependency configuration.
    path = Path(__file__).parents[1] / "api/warehouse/live_stock.py"
    node = next(n for n in ast.parse(path.read_text(encoding="utf-8")).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_batch_stock_sources")
    node.decorator_list = []
    node.args.defaults = []
    for arg in node.args.args:
        arg.annotation = None
    namespace = dict(
        InventoryAccess=InventoryAccess, ProductBatch=ProductBatch,
        ProductVariant=ProductVariant, InventoryLocation=InventoryLocation,
        InventoryBalance=InventoryBalance, InventoryStockPolicy=InventoryStockPolicy, UOM=UOM, Company=Company,
        select=select, and_=and_, func=_EndpointFunc, Date=Date,
        Decimal=Decimal, canonical_quantity=canonical_quantity,
        HTTPException=HTTPException, reservation_evidence=reservation_evidence,
        OWNER_PREVIEW_LIMIT=OWNER_PREVIEW_LIMIT,
        reservation_owner_projection=reservation_owner_projection,
        batch_metadata_is_sellable=batch_metadata_is_sellable,
        allowed_special_transfer_purposes=no_special_purposes,
        SPECIAL_TRANSFER_PERMISSION=SPECIAL_TRANSFER_PERMISSION,
        read_special_transfer_destinations=no_special_transfer_destinations,
        read_terminal_origin_availability=no_terminal_origin_availability,
        inventory_quality_action_availability=no_quality_action_availability,
        inventory_business_error=lambda code, message: {"code": code, "message": message},
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["get_batch_stock_sources"]


class ReadSession:
    def __init__(self, connection):
        self.connection = connection
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.connection.execute(statement)

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.connection.scalar(statement)

    async def scalars(self, statement):
        self.statements.append(statement)
        return self.connection.scalars(statement)


@pytest.fixture
def store():
    metadata = MetaData()
    definitions = [
        (ProductBatch, "id company_id product_variant_id batch_number production_date expiry_date disposition disposition_reason disposition_revision is_active"),
        (ProductVariant, "id company_id base_uom_id lifecycle_status operational_hold expiry_control_mode"),
        (UOM, "id code"),
        (Company, "id timezone"),
        (InventoryLocation, "id company_id name location_type is_active vehicle_id"),
        (InventoryBalance, "id company_id location_id product_variant_id batch_id stock_status on_hand_quantity reserved_quantity"),
        (InventoryStockPolicy, "id company_id location_id product_variant_id minimum_remaining_shelf_life_days is_active"),
        (InventoryTransferHeader, "id company_id source_location_id destination_location_id reference_number workflow_type status transfer_purpose work_session_id expected_receiver_id dispatched_by"),
        (InventoryTransferLine, "id company_id transfer_header_id product_variant_id batch_id source_stock_status quantity"),
        (InventoryMovement, "id company_id transfer_header_id product_variant_id batch_id source_location_id destination_location_id source_stock_status destination_stock_status movement_kind reservation_action reference_type reference_id quantity work_session_id"),
        (DispatchRoute, "id company_id work_session_id driver_id vehicle_id source_location_id"),
        (Permission, "id code"), (UserRole, "company_id driver_id role_id"),
        (UserLocationAccess, "company_id driver_id role_id location_id"),
    ]
    tables = {}
    for model, names in definitions:
        original = model.__table__
        tables[original.name] = Table(original.name, metadata, *(
            Column(name, original.c[name].type) for name in names.split()
        ))
    tables[role_permissions.name] = Table(role_permissions.name, metadata, *(
        Column(name, role_permissions.c[name].type) for name in ("company_id", "role_id", "permission_id")
    ))
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        metadata.create_all(connection)
        def insert(model, **values):
            connection.execute(tables[model.__table__.name].insert(), values)
        insert(Company, id=1, timezone="UTC")
        insert(UOM, id=1, code="EA")
        insert(
            ProductBatch,
            id=11,
            company_id=1,
            product_variant_id=101,
            batch_number="LOT-11",
            production_date=date(2026, 9, 1),
            expiry_date=date(2027, 9, 1),
            disposition="RELEASED",
            disposition_reason=None,
            disposition_revision=1,
            is_active=True,
        )
        insert(ProductVariant, id=101, company_id=1, base_uom_id=1, lifecycle_status="ACTIVE", operational_hold="RECALL", expiry_control_mode="REQUIRED")
        insert(InventoryLocation, id=1, company_id=1, name="Warehouse", location_type="WAREHOUSE", is_active=True)
        insert(InventoryLocation, id=2, company_id=1, name="Vehicle", location_type="VEHICLE", vehicle_id=10, is_active=True)
        insert(DispatchRoute, id=7, company_id=1, work_session_id=8, driver_id=9, vehicle_id=10, source_location_id=1)
        codes = ("inventory.read", "dispatch.read", "transfer.cancel")
        for i, code in enumerate(codes, 1):
            insert(Permission, id=i, code=code)
        yield SimpleNamespace(connection=connection, db=ReadSession(connection), tables=tables, insert=insert, codes=codes)
    engine.dispose()


def actor(*, admin=True, company=1):
    return SimpleNamespace(company_id=company, id=17, is_admin=admin)


def grant(store, code, location=None):
    role = store.codes.index(code) + 100 + (location or 0) * 10
    values = dict(company_id=1, driver_id=17, role_id=role)
    if location is None:
        store.insert(UserRole, **values)
    else:
        store.insert(UserLocationAccess, **values, location_id=location)
    store.connection.execute(store.tables[role_permissions.name].insert(), dict(
        company_id=1, role_id=role, permission_id=store.codes.index(code) + 1,
    ))


def balance(store, reserved="3.250000", *, location=1, status="AVAILABLE", company=1):
    store.insert(InventoryBalance, id=location * 10 + len(status), company_id=company,
                 location_id=location, product_variant_id=101, batch_id=11,
                 stock_status=status, on_hand_quantity=Decimal("100"), reserved_quantity=Decimal(reserved))


def owner(store, transfer=21, quantity="3.250000", *, location=1, company=1,
          state="PENDING", purpose="ROUTE_LOAD", reserve=True, release=False,
          variant=101, batch=11, receiver=9, movement_quantity=None):
    store.insert(InventoryTransferHeader, id=transfer, company_id=company,
                 source_location_id=location, destination_location_id=2 if location == 1 else 1,
                 reference_number=f"HS-{transfer}", workflow_type="HANDSHAKE", status=state,
                 transfer_purpose=purpose, work_session_id=8, expected_receiver_id=receiver, dispatched_by=17)
    store.insert(InventoryTransferLine, id=transfer, company_id=company,
                 transfer_header_id=transfer, product_variant_id=variant, batch_id=batch,
                 source_stock_status="AVAILABLE", quantity=Decimal(quantity))
    for action in (["RESERVE"] if reserve else []) + (["RELEASE"] if release else []):
        store.insert(InventoryMovement, id=transfer * 10 + (action == "RELEASE"), company_id=company,
                     transfer_header_id=transfer, product_variant_id=variant, batch_id=batch,
                     source_location_id=location, destination_location_id=location,
                     source_stock_status="AVAILABLE", destination_stock_status="AVAILABLE",
                     movement_kind="RESERVATION", reservation_action=action,
                     reference_type=f"HANDSHAKE_{action}", reference_id=f"HS-{transfer}",
                     quantity=Decimal(movement_quantity or quantity), work_session_id=8)


async def read(store, user=None):
    response = await endpoint()(11, store.db, user or actor())
    return WarehouseBatchStockSourcesResponse.model_validate(response).model_dump(mode="json")


@pytest.mark.asyncio
async def test_multiple_owners_explain_exact_quantity_without_multiplying_balance(store):
    balance(store)
    owner(store, quantity="2.000000")
    owner(store, transfer=22, quantity="1.250000")
    response = await read(store)
    assert response["operational_hold"] == "RECALL"
    status = response["sources"][0]["statuses"][0]
    assert status["on_hand_quantity"] == "100"
    assert status["movable_quantity"] == "96.75"
    evidence = status["reservation_evidence"]
    assert evidence["coverage"] == "COMPLETE"
    assert evidence["unattributed_quantity"] == "0"
    assert [o["quantity"] for o in evidence["owners"]] == ["2", "1.25"]
    first = evidence["owners"][0]
    assert first == dict(owner_type="DISPATCH_HANDSHAKE", module="DISPATCH", transfer_id=21,
                         reference_number="HS-21", transfer_purpose="ROUTE_LOAD", work_session_id=8,
                         route_id=7, expected_receiver_id=9, created_by=17, quantity="2",
                         operation_status="PENDING", navigation_target="DISPATCH_ROUTE_TRANSFERS",
                         action="FORCE_CANCEL_HANDSHAKE")
    assert len(store.db.statements) == 4  # Existing permission/batch/global/source reads only.
    sql = str(store.db.statements[-1].compile(dialect=postgresql.dialect()))
    assert "inventory_balances" in sql and "inventory_movements" in sql and "row_number()" in sql
    assert "FOR UPDATE" not in sql


@pytest.mark.asyncio
async def test_vehicle_route_return_is_a_separate_bucket(store):
    balance(store, location=2)
    owner(store, location=2, purpose="ROUTE_RETURN")
    response = await read(store)
    source = response["sources"][0]
    assert source["location_id"] == 2 and source["location_type"] == "VEHICLE"
    assert source["statuses"][0]["reservation_evidence"]["owners"][0]["transfer_purpose"] == "ROUTE_RETURN"


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    dict(state="POSTED"), dict(state="CANCELLED"), dict(state="REJECTED"),
    dict(reserve=False), dict(release=True), dict(movement_quantity="2"),
    dict(company=2), dict(batch=12), dict(variant=102), dict(receiver=10),
    dict(purpose="QUARANTINE"),
])
async def test_nonlive_foreign_or_unproven_evidence_is_unattributed(store, changes):
    balance(store)
    owner(store, **changes)
    evidence = (await read(store))["sources"][0]["statuses"][0]["reservation_evidence"]
    assert evidence["coverage"] == "UNRESOLVED"
    assert evidence["owners"] == [] and evidence["unattributed_quantity"] == "3.25"


@pytest.mark.asyncio
async def test_inventory_permission_alone_does_not_reveal_dispatch_identity(store):
    grant(store, "inventory.read", 1)
    balance(store)
    owner(store)
    evidence = (await read(store, actor(admin=False)))["sources"][0]["statuses"][0]["reservation_evidence"]
    assert evidence["owners"] == [] and evidence["reason"] == "OWNER_EVIDENCE_UNAVAILABLE"


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_route_and_exact_source_permissions_drive_navigation_and_action(store, cancel):
    grant(store, "inventory.read", 1)
    grant(store, "dispatch.read", 1)
    grant(store, "dispatch.read", 2)
    # Cancellation on the other endpoint is insufficient.
    grant(store, "transfer.cancel", 1 if cancel else 2)
    balance(store)
    owner(store)
    first = (await read(store, actor(admin=False)))["sources"][0]["statuses"][0]["reservation_evidence"]["owners"][0]
    assert first["navigation_target"] == "DISPATCH_ROUTE_TRANSFERS"
    assert first["action"] == ("FORCE_CANCEL_HANDSHAKE" if cancel else None)


@pytest.mark.asyncio
async def test_missing_route_vehicle_permission_hides_owner(store):
    grant(store, "inventory.read", 1)
    grant(store, "dispatch.read", 1)
    balance(store)
    owner(store)
    evidence = (await read(store, actor(admin=False)))["sources"][0]["statuses"][0]["reservation_evidence"]
    assert not evidence["owners"]


@pytest.mark.asyncio
async def test_hidden_source_never_leaks_even_with_company_dispatch_permission(store):
    grant(store, "inventory.read", 1)
    grant(store, "dispatch.read")
    balance(store)
    balance(store, location=2)
    owner(store)
    owner(store, transfer=22, location=2, purpose="ROUTE_RETURN")
    response = await read(store, actor(admin=False))
    assert [s["location_id"] for s in response["sources"]] == [1]
    assert [o["transfer_id"] for o in response["sources"][0]["statuses"][0]["reservation_evidence"]["owners"]] == [21]


@pytest.mark.asyncio
async def test_preview_is_bounded_and_reports_omitted_quantity(store):
    balance(store, "21")
    for transfer in range(21, 42):
        owner(store, transfer=transfer, quantity="1")
    status = (await read(store))["sources"][0]["statuses"][0]
    assert status["reserved_quantity"] == "21"
    evidence = status["reservation_evidence"]
    assert len(evidence["owners"]) == 20 and evidence["owners_truncated"] is True
    assert evidence["coverage"] == "PARTIAL" and evidence["reason"] == "OWNER_PREVIEW_LIMIT"
    assert evidence["unattributed_quantity"] == "1"
    assert len(store.db.statements) == 4


@pytest.mark.asyncio
async def test_partial_and_inconsistent_balances_are_never_claimed_complete(store):
    balance(store, "4")
    owner(store)
    status = (await read(store))["sources"][0]["statuses"][0]
    assert status["reservation_evidence"]["coverage"] == "PARTIAL"
    assert status["reservation_evidence"]["unattributed_quantity"] == "0.75"
    store.connection.execute(store.tables["inventory_balances"].update().values(reserved_quantity=Decimal("1")))
    evidence = (await read(store))["sources"][0]["statuses"][0]["reservation_evidence"]
    assert evidence["coverage"] == "UNRESOLVED" and evidence["reason"] == "OWNER_EVIDENCE_MISMATCH"
    assert evidence["owners"] == []


@pytest.mark.asyncio
async def test_zero_and_unsupported_stock_status_have_explicit_coverage(store):
    balance(store, "0")
    balance(store, "2", status="BLOCKED")
    statuses = (await read(store))["sources"][0]["statuses"]
    assert statuses[0]["reservation_evidence"]["coverage"] == "NONE"
    assert statuses[1]["reservation_evidence"]["coverage"] == "UNRESOLVED"


@pytest.mark.asyncio
async def test_foreign_tenant_and_inventory_denial_fail_closed(store):
    with pytest.raises(HTTPException) as foreign:
        await read(store, actor(company=2))
    assert foreign.value.status_code == 404
    with pytest.raises(HTTPException) as denied:
        await read(store, actor(admin=False))
    assert denied.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [InventoryTransferLine, InventoryMovement, DispatchRoute])
async def test_each_owner_join_rejects_foreign_tenant_rows(store, model):
    balance(store)
    owner(store)
    store.connection.execute(store.tables[model.__tablename__].update().values(company_id=2))
    evidence = (await read(store))["sources"][0]["statuses"][0]["reservation_evidence"]
    assert evidence["owners"] == [] and evidence["coverage"] == "UNRESOLVED"


def test_quantity_contract_reuses_exact_canonical_quantity_and_rejects_lossy_values():
    from pydantic import ValidationError
    evidence = ReservationEvidence(coverage="UNRESOLVED", unattributed_quantity="0.000001")
    assert evidence.model_dump(mode="json")["unattributed_quantity"] == "0.000001"
    for invalid in (-1, 0.1, "NaN", "0.0000001"):
        with pytest.raises(ValidationError):
            ReservationEvidence(coverage="UNRESOLVED", unattributed_quantity=invalid)
