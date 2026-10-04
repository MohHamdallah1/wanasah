"""Focused read-projection tests on synthetic SQLite, never production data."""
from decimal import Decimal
from datetime import datetime, date
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import Column, MetaData, Table, create_engine
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import joinedload
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from domains.dispatch_archive_navigation import dispatch_archive_target_query
from domains.inventory_archive_navigation import inventory_archive_target_query, inventory_archive_targets
from domains.operations_archive_navigation import operations_archive_target_query
from inventory_access import InventoryAccess
from dispatch_access import route_filter
from models import (
    DispatchLoadPlanLine, DispatchRoute, InventoryBalance, InventoryLocation,
    InventoryLock, InventoryTransferHeader, InventoryTransferLine, Permission,
    ProductLocation, ShortageRequest, StocktakeLine, StocktakeSession,
    ProductVariant, RouteCommercialContext,
    WorkSession, SessionInventorySnapshot,
    UserLocationAccess, UserRole, role_permissions,
)


@pytest.fixture
def store():
    metadata = MetaData()
    definitions = (
        (InventoryLocation, "id company_id location_type is_active vehicle_id"),
        (InventoryBalance, "id company_id location_id product_variant_id batch_id on_hand_quantity reserved_quantity"),
        (InventoryTransferHeader, "id company_id source_location_id destination_location_id reference_number workflow_type status work_session_id"),
        (InventoryTransferLine, "id company_id transfer_header_id product_variant_id"),
        (StocktakeSession, "id company_id stocktake_type status location_id related_work_session_id"),
        (StocktakeLine, "id company_id stocktake_session_id product_variant_id"),
        (InventoryLock, "id company_id stocktake_session_id product_variant_id released_at"),
        (ProductLocation, "id company_id location_id product_variant_id"),
        (DispatchRoute, "id company_id work_session_id source_location_id vehicle_id status"),
        (DispatchLoadPlanLine, "id company_id dispatch_route_id product_variant_id"),
        (ShortageRequest, "id company_id product_variant_id status"),
        (WorkSession, "id company_id end_time inventory_reconciled_at is_settled"),
        (SessionInventorySnapshot, "id company_id work_session_id product_variant_id"),
        (Permission, "id code"), (UserRole, "company_id driver_id role_id"),
        (UserLocationAccess, "company_id driver_id role_id location_id"),
    )
    tables = {model: Table(model.__tablename__, metadata, *(
        Column(name, model.__table__.c[name].type) for name in names.split()
    )) for model, names in definitions}
    grants = Table(role_permissions.name, metadata, *(
        Column(name, role_permissions.c[name].type) for name in ("company_id", "role_id", "permission_id")
    ))
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        metadata.create_all(connection)
        def insert(model, **values):
            connection.execute(tables[model].insert(), values)
        insert(InventoryLocation, id=1, company_id=1, location_type="WAREHOUSE", is_active=True)
        insert(InventoryLocation, id=2, company_id=1, location_type="VEHICLE", is_active=True, vehicle_id=7)
        insert(InventoryLocation, id=3, company_id=1, location_type="WAREHOUSE", is_active=True)
        insert(InventoryBalance, id=11, company_id=1, location_id=1, product_variant_id=101, batch_id=50,
               on_hand_quantity=Decimal("10"), reserved_quantity=Decimal("0"))
        insert(InventoryTransferHeader, id=20, company_id=1, source_location_id=1, destination_location_id=3,
               reference_number="TX-20", workflow_type="TRANSIT", status="IN_TRANSIT")
        insert(InventoryTransferLine, id=201, company_id=1, transfer_header_id=20, product_variant_id=101)
        insert(StocktakeSession, id=30, company_id=1, stocktake_type="CYCLE_COUNT", status="COUNTING", location_id=1)
        insert(StocktakeLine, id=301, company_id=1, stocktake_session_id=30, product_variant_id=101)
        insert(InventoryLock, id=40, company_id=1, stocktake_session_id=30, product_variant_id=101)
        insert(ProductLocation, id=60, company_id=1, location_id=1, product_variant_id=101)
        insert(DispatchRoute, id=70, company_id=1, work_session_id=80, source_location_id=1, vehicle_id=7, status="active")
        insert(DispatchLoadPlanLine, id=701, company_id=1, dispatch_route_id=70, product_variant_id=101)
        insert(InventoryTransferHeader, id=21, company_id=1, source_location_id=1, destination_location_id=2,
               reference_number="HS-21", workflow_type="HANDSHAKE", status="PENDING", work_session_id=80)
        insert(InventoryTransferLine, id=211, company_id=1, transfer_header_id=21, product_variant_id=101)
        insert(ShortageRequest, id=90, company_id=1, product_variant_id=101, status="pending")
        insert(WorkSession, id=80, company_id=1, end_time=datetime(2026, 10, 1), inventory_reconciled_at=datetime(2026, 10, 2), is_settled=False)
        insert(SessionInventorySnapshot, id=95, company_id=1, work_session_id=80, product_variant_id=101)
        codes = ("inventory.read", "catalog.read", "location.read", "transfer.read", "stocktake.read",
                 "product_location.read", "product_location.manage", "dispatch.read", "dispatch.execute",
                 "transfer.receive", "transfer.reject", "transfer.cancel", "stocktake.count", "stocktake.review")
        for index, code in enumerate(codes, 1):
            insert(Permission, id=index, code=code)
        def grant(code, location=None):
            identifier = codes.index(code) + 1
            role = identifier + (location or 0) * 100
            values = dict(company_id=1, driver_id=17, role_id=role)
            if location is None:
                insert(UserRole, **values)
            else:
                insert(UserLocationAccess, **values, location_id=location)
            connection.execute(grants.insert(), dict(company_id=1, role_id=role, permission_id=identifier))
        yield SimpleNamespace(connection=connection, tables=tables, insert=insert, grant=grant)
    engine.dispose()


SAMPLES = {"INVENTORY_BALANCE": 11, "OPEN_TRANSFER": 20, "OPEN_STOCKTAKE": 30,
           "ACTIVE_INVENTORY_LOCK": 40, "PRODUCT_LOCATION": 60, "ACTIVE_ROUTE_LOAD": 70, "OPEN_SHORTAGE": 90}


def access(*, admin=True, company=1):
    return InventoryAccess(None, SimpleNamespace(company_id=company, id=17, is_admin=admin))


def rows(store, query):
    return {row["code"]: dict(row) for row in store.connection.execute(query).mappings()}


def test_exact_inventory_operation_context_and_postgresql_select(store):
    query = inventory_archive_target_query(access(), 101, SAMPLES)
    result = rows(store, query)
    assert len(result) == 5
    assert result["INVENTORY_BALANCE"]["batch_id"] == 50
    assert result["OPEN_TRANSFER"]["operation_id"] == 20
    assert result["OPEN_STOCKTAKE"]["operation_id"] == 30
    assert result["ACTIVE_INVENTORY_LOCK"]["operation_id"] == 30  # lock ID is not session ID
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "UNION ALL" in sql and "FOR UPDATE" not in sql


@pytest.mark.parametrize("query_builder", [inventory_archive_target_query, dispatch_archive_target_query])
def test_company_variant_and_permission_denial(store, query_builder):
    assert rows(store, query_builder(access(company=2), 101, SAMPLES)) == {}
    assert rows(store, query_builder(access(), 999, SAMPLES)) == {}
    assert rows(store, query_builder(access(admin=False), 101, SAMPLES)) == {}


def test_transfer_destination_only_permission_and_unsupported_transit_states(store):
    store.grant("transfer.read", 3)
    store.grant("location.read", 3)
    store.grant("transfer.receive", 3)
    result = rows(store, inventory_archive_target_query(access(admin=False), 101, SAMPLES))
    assert result["OPEN_TRANSFER"]["location_id"] == 3
    for state in ("DRAFT", "PENDING", "ACCEPTED", "POSTED", "CANCELLED"):
        store.connection.execute(store.tables[InventoryTransferHeader].update().where(store.tables[InventoryTransferHeader].c.id == 20).values(status=state))
        result = rows(store, inventory_archive_target_query(access(), 101, SAMPLES))
        if state in ("DRAFT", "PENDING", "ACCEPTED"):
            assert result["OPEN_TRANSFER"]["kind"] == "capability-gap"
            assert result["OPEN_TRANSFER"]["reason"] == "TRANSIT_STATE"
        else:
            assert "OPEN_TRANSFER" not in result


@pytest.mark.parametrize("status", ["DRAFT", "APPROVED", "POSTED", "CANCELLED"])
def test_unsupported_stocktake_states_do_not_promise_an_action(store, status):
    store.connection.execute(store.tables[StocktakeSession].update().values(status=status))
    result = rows(store, inventory_archive_target_query(access(), 101, SAMPLES))
    if status in ("DRAFT", "APPROVED"):
        assert result["OPEN_STOCKTAKE"]["reason"] == "STOCKTAKE_STATE"
        assert result["ACTIVE_INVENTORY_LOCK"]["kind"] == "capability-gap"
    else:
        assert "OPEN_STOCKTAKE" not in result and "ACTIVE_INVENTORY_LOCK" not in result


def test_hidden_stock_sources_are_explicit_gaps_only_when_authorized(store):
    store.connection.execute(store.tables[InventoryLocation].update().where(store.tables[InventoryLocation].c.id == 1).values(location_type="TRANSIT"))
    result = rows(store, inventory_archive_target_query(access(), 101, {"INVENTORY_BALANCE": 11}))
    assert result["INVENTORY_BALANCE"]["reason"] == "INVENTORY_SOURCE"
    assert rows(store, inventory_archive_target_query(access(admin=False), 101, {"INVENTORY_BALANCE": 11})) == {}


def test_vehicle_stock_and_vehicle_reconciliation_anchor(store):
    store.connection.execute(store.tables[InventoryBalance].update().values(location_id=2))
    store.connection.execute(store.tables[StocktakeSession].update().values(
        stocktake_type="VEHICLE_RECON", location_id=2, related_work_session_id=80))
    result = rows(store, inventory_archive_target_query(access(), 101, SAMPLES))
    assert result["INVENTORY_BALANCE"]["location_id"] == 1
    assert result["OPEN_STOCKTAKE"]["location_id"] == 1
    store.connection.execute(store.tables[InventoryLocation].update().where(store.tables[InventoryLocation].c.id == 2).values(vehicle_id=999))
    assert "OPEN_STOCKTAKE" not in rows(store, inventory_archive_target_query(access(), 101, SAMPLES))


def test_dispatch_handshake_is_not_a_transit_target_and_shortage_remains_admin_only(store):
    samples = {**SAMPLES, "OPEN_TRANSFER": 21}
    result = rows(store, dispatch_archive_target_query(access(), 101, samples))
    assert result["OPEN_TRANSFER"]["route_id"] == 70
    assert result["OPEN_TRANSFER"]["operation_id"] == 21
    assert "OPEN_TRANSFER" not in rows(store, inventory_archive_target_query(access(), 101, samples))
    for code in ("dispatch.read", "dispatch.execute"):
        for location in (1, 2):
            store.grant(code, location)
    result = rows(store, dispatch_archive_target_query(access(admin=False), 101, samples))
    assert "ACTIVE_ROUTE_LOAD" in result and "OPEN_SHORTAGE" not in result
    store.connection.execute(store.tables[InventoryTransferHeader].update().where(store.tables[InventoryTransferHeader].c.id == 21).values(status="ACCEPTED"))
    assert "OPEN_TRANSFER" not in rows(store, dispatch_archive_target_query(access(), 101, samples))


@pytest.mark.asyncio
async def test_assignment_history_reuses_existing_guard_after_authorized_projection(store, monkeypatch):
    calls = []
    async def guard(db, company, location, variant):
        calls.append((company, location, variant))
        return [{"code": "INVENTORY_MOVEMENT"}]
    monkeypatch.setattr("domains.inventory_archive_navigation.product_location_delete_blockers", guard)
    class ReadSession:
        async def execute(self, query):
            return store.connection.execute(query)
    result = await inventory_archive_targets(ReadSession(), access().actor, 101, [{"code": "PRODUCT_LOCATION", "sample_id": 60}])
    assert result["PRODUCT_LOCATION"] == {"kind": "capability-gap", "reason": "PRODUCT_LOCATION_REFERENCES"}
    assert calls == [(1, 1, 101)]
    calls.clear()
    assert await inventory_archive_targets(ReadSession(), access(admin=False).actor, 101, [{"code": "PRODUCT_LOCATION", "sample_id": 60}]) == {}
    assert calls == []


def preflight_endpoint(namespace):
    source = Path(__file__).parents[1] / "api/catalog.py"
    node = next(node for node in ast.parse(source.read_text(encoding="utf-8")).body
                if isinstance(node, ast.AsyncFunctionDef) and node.name == "variant_archive_preflight")
    node.decorator_list = []
    node.args.defaults = []
    for arg in node.args.args:
        arg.annotation = None
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(source), "exec"), namespace)
    return namespace["variant_archive_preflight"]


@pytest.mark.asyncio
@pytest.mark.parametrize("lifecycle,hold,blockers,expected", [
    ("RETIRING", "NONE", [], True), ("ACTIVE", "NONE", [], False),
    ("RETIRING", "RECALL", [], False),
    ("RETIRING", "NONE", [{"code": "STOCK_POLICY", "count": 1, "sample_id": 99}], False),
])
async def test_preflight_adds_hints_without_changing_archive_authority(lifecycle, hold, blockers, expected):
    permission = AsyncMock()
    variant = SimpleNamespace(lifecycle_status=lifecycle, operational_hold=hold, version=4)
    db = SimpleNamespace(scalar=AsyncMock(return_value=variant))
    namespace = dict(
        _require=permission, select=select, ProductVariant=ProductVariant,
        archive_blockers=AsyncMock(return_value=blockers),
        inventory_archive_targets=AsyncMock(return_value={}),
        dispatch_archive_targets=AsyncMock(return_value={}),
        operations_archive_targets=AsyncMock(return_value={}),
    )
    response = await preflight_endpoint(namespace)(101, db, access().actor)
    permission.assert_awaited_once_with(db, access().actor, "catalog.archive")
    assert response["can_archive"] is expected
    assert response["version"] == 4
    assert response["blockers"] == [{**row, "owner_target": None} for row in blockers]
    statement = db.scalar.call_args.args[0].compile(dialect=postgresql.dialect())
    assert set(statement.params.values()) == {1, 101}


@pytest.mark.asyncio
async def test_missing_variant_keeps_404_and_does_not_project_owner_data():
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))
    read = AsyncMock()
    namespace = dict(_require=AsyncMock(), select=select, ProductVariant=ProductVariant,
                     _error=lambda status, code, message: HTTPException(status, {"code": code}),
                     archive_blockers=read, inventory_archive_targets=read, dispatch_archive_targets=read)
    with pytest.raises(HTTPException) as failure:
        await preflight_endpoint(namespace)(101, db, access().actor)
    assert failure.value.status_code == 404
    read.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("function_name,filter_name,identifier", [
    ("get_active_routes", "route_id", 70), ("get_shortages", "shortage_id", 90),
])
async def test_owner_lookup_filters_existing_read_without_changing_default_scope(function_name, filter_name, identifier):
    source = Path(__file__).parents[1] / "api/dispatch.py"
    node = next(node for node in ast.parse(source.read_text(encoding="utf-8")).body
                if isinstance(node, ast.AsyncFunctionDef) and node.name == function_name)
    if function_name == "get_shortages":
        assert ast.unparse(node.args.defaults[1]) == "Depends(get_current_admin)"
    node.decorator_list = []
    node.args.defaults = []
    for arg in node.args.args:
        arg.annotation = None
    namespace = dict(InventoryAccess=InventoryAccess, select=select, DispatchRoute=DispatchRoute,
                     RouteCommercialContext=RouteCommercialContext, and_=and_, route_filter=route_filter,
                     ShortageRequest=ShortageRequest, joinedload=joinedload)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(source), "exec"), namespace)
    class CapturedRead(Exception):
        pass
    statements = []
    class ReadSession:
        async def scalar(self, query):
            return True
        async def execute(self, query):
            statements.append(query)
            raise CapturedRead()
    for value in (None, identifier):
        with pytest.raises(CapturedRead):
            await namespace[function_name](ReadSession(), access().actor, **{filter_name: value})
    baseline, focused = [query.compile(dialect=postgresql.dialect()) for query in statements]
    assert identifier not in baseline.params.values()
    assert identifier in focused.params.values()
    assert 1 in baseline.params.values() and 1 in focused.params.values()
    assert "FOR UPDATE" not in str(focused)


def test_custody_snapshot_resolves_financial_session_only_with_current_authority(store):
    samples = {"OPEN_CUSTODY": 95}
    query = operations_archive_target_query(access().actor, 101, samples)
    assert store.connection.execute(query).scalars().all() == [80]
    assert operations_archive_target_query(access(admin=False).actor, 101, samples) is None
    assert store.connection.execute(operations_archive_target_query(access(company=2).actor, 101, samples)).scalars().all() == []
    assert store.connection.execute(operations_archive_target_query(access().actor, 999, samples)).scalars().all() == []
    for changed in ({"end_time": None}, {"inventory_reconciled_at": None}, {"is_settled": True}):
        table = store.tables[WorkSession]
        store.connection.execute(table.update().values(end_time=datetime(2026, 10, 1), inventory_reconciled_at=datetime(2026, 10, 2), is_settled=False))
        store.connection.execute(table.update().values(**changed))
        assert store.connection.execute(query).scalars().all() == []


@pytest.mark.asyncio
async def test_operations_focused_read_keeps_historical_unsettled_session_scope():
    source = Path(__file__).parents[1] / "api/dispatch.py"
    node = next(node for node in ast.parse(source.read_text(encoding="utf-8")).body
                if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_admin_dashboard_data")
    assert ast.unparse(node.args.defaults[1]) == "Depends(get_current_admin)"
    node.decorator_list = []
    node.args.defaults = []
    for arg in node.args.args:
        arg.annotation = None
    namespace = dict(select=select, WorkSession=WorkSession, joinedload=joinedload, or_=or_,
                     get_company_local_date=AsyncMock(return_value=date(2026, 10, 4)))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(source), "exec"), namespace)
    class CapturedRead(Exception):
        pass
    statements = []
    class ReadSession:
        async def execute(self, query):
            statements.append(query)
            raise CapturedRead()
    for value in (None, 80):
        with pytest.raises(CapturedRead):
            await namespace["get_admin_dashboard_data"](ReadSession(), access().actor, value)
    baseline, focused = [query.compile(dialect=postgresql.dialect()) for query in statements]
    assert 80 not in baseline.params.values() and 80 in focused.params.values()
    assert "is_settled IS false" in str(focused) and "session_date" in str(focused)
    assert 1 in focused.params.values()
