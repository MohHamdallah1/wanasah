"""Independent Checkpoint 1 lot/expiry acceptance specification.

Run from wa_backend with: python -B -m pytest -p no:cacheprovider -q
    tests/test_inbound_no_lot_frozen_contract.py

The receipt tests execute the real schema, handler, capability resolver, supplier
selection, idempotency and batch persistence on synthetic in-memory relations.
PostgreSQL locks/tenant context, the clock, inventory/cost posting, and purchase-
reference persistence are synthetic boundaries. The audit-lock query, canonical
receipt authorization and purchase-reference selection validation stay real.
This is NOT a PostgreSQL/RLS/concurrency acceptance gate; the companion opt-in
module covers committed database effects.

Presentation probes execute real endpoint serializers with bounded scripted DB
rows. They never replace the batch formatter or sanitize the observed output.
No application startup, customer database or filesystem fixture is used.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
import os
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "InboundFrozenSyntheticKeyAa12345678901234567890")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://no_lot_unit@127.0.0.1:1/no_lot_unit")

import pytest
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import (BigInteger, Column, Integer, JSON, MetaData, Table,
                        UniqueConstraint, create_engine, event, select, true)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from api.warehouse import inbound, ledger, live_stock, stocktake, transfers
from api.warehouse import whole_product_quality_preview as quality_preview
from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.identity.models import BackofficeUser, CompanyPrincipal
from domains.inventory_costing.purchase_reference.authorization import require_receipt_access
from domains.inventory_supplier_evidence import InventorySupplierEvidence
from domains.suppliers.models import Supplier
from models import (Company, DomainAuditEvent, InventoryBalance, InventoryLocation,
                    InventoryLock, InventoryMovement, OperationIdempotency, Permission,
                    ProductBatch, ProductLocation, ProductUomConversion,
                    ProductVariant, StocktakeSession, TransactionalOutbox, UOM, UserLocationAccess, UserRole,
                    role_permissions)
from schemas import (BatchDispositionChangeRequest, InboundBatchItem,
                     UpgradedInboundRequest)

AS_OF = date(2026, 10, 15)
PAST = AS_OF - timedelta(days=30)
FUTURE = AS_OF + timedelta(days=365)
PREFIX = "__WANASAH_NOLOT__"
INTERNAL = "__WANASAH_NOLOT__:R0123456789abcdef0123456789abcdef:P-:E-"
REAL_LOT = "Manufacturer-Lot/AbC-009"
PERMISSIONS = ("inbound.create", "supplier.read", "inventory.read", "ledger.read",
               "transfer.read", "stocktake.start", "batch.disposition")


def assert_no_leak(value):
    encoded = json.dumps(jsonable_encoder(value), ensure_ascii=False)
    assert PREFIX.casefold() not in encoded.casefold(), "Internal storage identity leaked to an operator payload/error"


def assert_business_lots(value, expected):
    """Require a non-vacuous public batch_number, recursively including nested rows."""
    found = []

    def visit(node):
        if isinstance(node, dict):
            for key, child in node.items():
                if key == "batch_number":
                    found.append(child)
                visit(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                visit(child)

    visit(jsonable_encoder(value))
    assert found, "Probe returned no business-facing batch_number field"
    assert all(item == expected for item in found), found
    assert_no_leak(value)


class MemorySession:
    """Async facade over real SQLite relations; advisory locks have no semantics here."""
    def __init__(self, session):
        self.session = session
        self.audit_id = -1
        self.tenant_id = "1"  # default trusted context for the HTTP fixture

    async def execute(self, statement, *args, **kwargs):
        return self.session.execute(statement, *args, **kwargs)

    async def scalar(self, statement):
        return self.session.scalar(statement)

    async def scalars(self, statement):
        return self.session.scalars(statement)

    def add(self, row):
        if isinstance(row, (DomainAuditEvent, TransactionalOutbox)) and row.id is None:
            row.id = self.audit_id
            self.audit_id -= 1
        self.session.add(row)

    def add_all(self, rows):
        for row in rows:
            self.add(row)

    async def flush(self):
        self.session.flush()

    async def commit(self):
        self.session.commit()

    async def rollback(self):
        self.session.rollback()


class ReceiptHarness:
    def __init__(self):
        self.engine = create_engine("sqlite://")

        @event.listens_for(self.engine, "connect")
        def functions(connection, _record):
            connection.create_function("hashtext", 1, lambda _value: 1)
            connection.create_function("hashtextextended", 2, lambda _value, _seed: 1)
            connection.create_function("pg_advisory_xact_lock", -1, lambda *_args: 0)
            connection.create_function("pg_advisory_xact_lock_shared", -1, lambda *_args: 0)
            # Model the trusted DB dependency's tenant context, not PostgreSQL RLS.
            connection.create_function("current_setting", 2, lambda key, _missing:
                                       self.db.tenant_id if key == "app.current_tenant" else None)

        metadata = MetaData()
        self.tables = {}
        models = (Company, InventoryLocation, ProductVariant, ProductLocation,
                  ProductUomConversion, ProductBatch, OperationIdempotency,
                  InventoryMovement, UOM, Permission, UserRole, UserLocationAccess,
                  DomainAuditEvent, TransactionalOutbox, Supplier, InventorySupplierEvidence,
                  InventoryLock, StocktakeSession, CompanyPrincipal, BackofficeUser)
        for original in [model.__table__ for model in models] + [role_permissions]:
            columns = []
            for column in original.c:
                kind = JSON() if isinstance(column.type, JSONB) else column.type
                if isinstance(kind, BigInteger) and column.primary_key:
                    kind = Integer()
                server_default = column.server_default
                if column.computed is not None or (server_default is not None and "::" in str(server_default.arg)):
                    server_default = None
                columns.append(Column(column.name, kind, primary_key=column.primary_key,
                                      nullable=column.nullable, server_default=server_default))
            constraints = [UniqueConstraint(*(c.name for c in item.columns), name=item.name)
                           for item in original.constraints if isinstance(item, UniqueConstraint)]
            self.tables[original.name] = Table(original.name, metadata, *columns, *constraints)
        metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.db = MemorySession(self.session)
        self.actor = NS(id=909, company_id=1)
        self.posted = []

        async def movement_boundary(_db, *, company_id, performed_by, movements):
            assert company_id in (1, 2)
            assert performed_by == 909
            self.posted.extend(movements)
            return [NS(id=len(self.posted) + index) for index, _ in enumerate(movements)]

        async def begin_reference_boundary(_db, *, access, operation, location_id):
            # Keep real identity, tenant and exact-location authorization. Only
            # the PostgreSQL transaction/writer persistence is outside this fixture.
            assert _db is self.db
            await require_receipt_access(_db, access, location_id)
            assert operation in self.session
            assert operation.company_id == access.company_id
            assert operation.operation == "WAREHOUSE_INBOUND"
            assert operation.completed_at is None and operation.response_json is None
            return NS(operation=operation, access=access, location_id=location_id)

        async def write_reference_boundary(_db, *, access, writer, reference_id,
                                           movement_ids, selections):
            # The synthetic movement boundary emits no persisted cost events;
            # their reference provenance is covered by PostgreSQL acceptance.
            assert _db is self.db and writer.access is access
            await require_receipt_access(_db, access, writer.location_id)
            assert writer.operation.completed_at is None
            assert writer.operation.response_json is None
            assert reference_id and movement_ids

        self.movement = AsyncMock(side_effect=movement_boundary)
        self.begin_reference = AsyncMock(side_effect=begin_reference_boundary)
        self.write_reference = AsyncMock(side_effect=write_reference_boundary)
        self.clock = AsyncMock(return_value=AS_OF)
        self.activate = AsyncMock()
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(inbound, "apply_inventory_movements_batch", self.movement))
        self.stack.enter_context(patch.object(inbound, "activate_costing_for_first_receipt", self.activate))
        self.stack.enter_context(patch.object(inbound, "get_company_local_date", self.clock))
        self.stack.enter_context(patch.object(inbound, "begin_receipt_reference", self.begin_reference))
        self.stack.enter_context(patch.object(inbound, "write_receipt_references", self.write_reference))
        for tenant, variant, location, supplier in ((1, 101, 41, 31), (2, 202, 82, 62)):
            self.insert(Company, id=tenant, company_code=f"SYN-{tenant}", name=f"Synthetic {tenant}", timezone="Asia/Amman", currency_code="JOD", is_active=True)
            self.insert(CompanyPrincipal, id=1100 + tenant, company_id=tenant,
                        username=f"synthetic-{tenant}", password_hash="not-a-login-fixture",
                        full_name="Synthetic operator", principal_type="BACKOFFICE",
                        is_active=True, auth_revision=1)
            self.insert(BackofficeUser, id=2201 + tenant, company_id=tenant,
                        principal_id=1100 + tenant, principal_type="BACKOFFICE")
            self.insert(InventoryLocation, id=location, company_id=tenant, code=f"WH-{tenant}",
                        name="Synthetic warehouse", location_type="WAREHOUSE", is_active=True,
                        is_system_managed=False, version=1)
            self.insert(ProductVariant, id=variant, company_id=tenant, product_id=tenant,
                        base_uom_id=1, name="Synthetic product", sku=f"SKU-{tenant}",
                        quantity_scale=6, quantity_step=Decimal("0.000001"),
                        lot_control_mode="REQUIRED", expiry_control_mode="OPTIONAL",
                        lifecycle_status="ACTIVE", operational_hold="NONE",
                        lifecycle_revision=1, version=1, packs_per_carton=1,
                        default_max_samples_per_day=0)
            self.insert(ProductLocation, id=tenant, company_id=tenant, product_variant_id=variant,
                        location_id=location, operational_flags={"inbound_enabled": True, "outbound_enabled": True},
                        version=1, created_by=909)
            self.insert(Supplier, id=supplier, company_id=tenant, name="Synthetic supplier",
                        is_active=True, version=1, created_by=909, updated_by=909)
        self.insert(UOM, id=1, code="EACH", name="Each")
        self.insert(UOM, id=2, code="CARTON", name="Carton")
        for number, code in enumerate(PERMISSIONS, 1):
            self.insert(Permission, id=number, code=code)
        self.session.commit()

    def insert(self, model, **values):
        self.session.execute(model.__table__.insert(), values)

    def configure(self, lot="REQUIRED", expiry="OPTIONAL", *, variant=101, **values):
        self.session.execute(self.tables["product_variants"].update().where(
            self.tables["product_variants"].c.id == variant).values(
                lot_control_mode=lot, expiry_control_mode=expiry, **values))
        self.session.commit()

    def access(self, *, company=1, owner=True):
        return BackofficeCapabilityAccess(self.db, BackofficeAuthorizationSubject(
            principal_id=1100 + company, backoffice_user_id=2201 + company, company_id=company,
            is_company_owner=owner, legacy_grant_driver_id=None if owner else 909))

    def grant(self, code, *, location=None):
        role_id = PERMISSIONS.index(code) + 100
        model = UserRole if location is None else UserLocationAccess
        values = dict(company_id=1, driver_id=909, role_id=role_id)
        if location is not None:
            values["location_id"] = location
        self.insert(model, **values)
        self.session.execute(self.tables[role_permissions.name].insert(), dict(
            company_id=1, role_id=role_id, permission_id=PERMISSIONS.index(code) + 1))
        self.session.commit()

    def body(self, lot=REAL_LOT, **overrides):
        item = dict(product_variant_id=101, quantity="2.500001", uom_id=1,
                    unit_cost="0.123456", batch_number=lot, production_date=PAST, expiry_date=FUTURE)
        item.update(overrides.pop("item", {}))
        result = dict(request_id=uuid4(), supplier_id=31, location_id=41, items=[item])
        result.update(overrides)
        # Derive once from the final operation ID; retries reuse this same body.
        result.setdefault("reference_id", f"CP1-SYNTHETIC-{result['request_id']}")
        return result

    async def post(self, body, *, access=None):
        # ValidationError is a deliberate failing assertion on the old null-rejecting schema.
        payload = UpgradedInboundRequest.model_validate(body)
        resolved_access = access or self.access()
        self.db.tenant_id = str(resolved_access.company_id)
        return await inbound.warehouse_inbound(payload, self.db, resolved_access, self.actor)

    def batches(self):
        self.session.expire_all()
        return list(self.session.scalars(select(ProductBatch).order_by(ProductBatch.id)))

    def close(self):
        self.stack.close()
        self.session.close()
        self.engine.dispose()


@pytest.fixture
def receipt():
    harness = ReceiptHarness()
    try:
        yield harness
    finally:
        harness.close()


async def rejected(receipt, body, code, *, status=None, access=None):
    before = receipt.movement.await_count
    with pytest.raises(HTTPException) as caught:
        await receipt.post(body, access=access)
    assert caught.value.detail["code"] == code
    if status is not None:
        assert caught.value.status_code == status
    assert_no_leak(caught.value.detail)
    assert receipt.movement.await_count == before
    return caught.value


@pytest.mark.parametrize("supplied", [True, False], ids=["null", "omitted"])
def test_request_accepts_missing_lot(supplied):
    data = dict(product_variant_id=101, quantity="1", uom_id=1, unit_cost="0.1")
    if supplied:
        data["batch_number"] = None
    item = InboundBatchItem.model_validate(data)
    assert item.batch_number is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,lot,code", [
    ("REQUIRED", None, "INBOUND_LOT_REQUIRED"),
    ("REQUIRED", REAL_LOT, None),
    ("OPTIONAL", None, None),
    ("OPTIONAL", REAL_LOT, None),
    ("NONE", None, None),
    ("NONE", REAL_LOT, "INBOUND_LOT_NOT_ALLOWED"),
])
async def test_lot_mode_matrix(receipt, mode, lot, code):
    receipt.configure(mode)
    body = receipt.body(lot)
    if code:
        await rejected(receipt, body, code, status=422)
        assert receipt.batches() == []
    else:
        assert await receipt.post(body) == {"message": "INBOUND_POSTED"}
        assert len(receipt.batches()) == 1
        if lot is None:
            assert receipt.batches()[0].batch_number.startswith(PREFIX)
        else:
            assert receipt.batches()[0].batch_number == REAL_LOT


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,lot,code", [
    ("REQUIRED", None, "INBOUND_LOT_REQUIRED"), ("REQUIRED", REAL_LOT, None),
    ("OPTIONAL", None, None), ("OPTIONAL", REAL_LOT, None),
    ("NONE", None, None), ("NONE", REAL_LOT, "INBOUND_LOT_NOT_ALLOWED"),
])
async def test_http_request_matrix_uses_canonical_non_owner_dependencies(receipt, mode, lot, code):
    receipt.configure(mode)
    receipt.grant("inbound.create", location=41)
    receipt.grant("supplier.read")
    app = FastAPI()
    app.include_router(inbound.router)

    async def db_dependency():
        yield receipt.db

    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_backoffice_capability_access] = lambda: receipt.access(owner=False)
    app.dependency_overrides[get_current_backoffice_legacy_driver] = lambda: receipt.actor
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://no-lot.test") as client:
        response = await client.post("/warehouse/inbound", json=jsonable_encoder(receipt.body(lot)))
    assert response.status_code == (422 if code else 201), response.text
    if code:
        detail = response.json()["detail"]
        assert isinstance(detail, dict), "Required/forbidden lot errors must use the frozen coded business contract"
        assert detail["code"] == code
    else:
        assert response.json() == {"message": "INBOUND_POSTED"}
    assert_no_leak(response.json())


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,code", [
    ("NONE", "INBOUND_LOT_NOT_ALLOWED"),
    ("OPTIONAL", "INBOUND_LOT_RESERVED"),
    ("REQUIRED", "INBOUND_LOT_RESERVED"),
])
@pytest.mark.parametrize("value", [INTERNAL, INTERNAL.lower(), "  " + INTERNAL + "  "])
async def test_client_cannot_supply_reserved_storage_identity(receipt, mode, code, value):
    receipt.configure(mode)
    await rejected(receipt, receipt.body(value), code, status=422)
    assert receipt.batches() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["NONE", "OPTIONAL"])
async def test_different_requests_same_metadata_never_share_anonymous_batch(receipt, mode):
    receipt.configure(mode)
    await receipt.post(receipt.body(None))
    await receipt.post(receipt.body(None))
    batches = receipt.batches()
    assert len(batches) == 2
    assert len({b.batch_number for b in batches}) == 2
    assert len({m["batch_id"] for m in receipt.posted}) == 2


@pytest.mark.asyncio
async def test_anonymous_metadata_groups_split_but_distinct_uoms_share_group(receipt):
    receipt.configure("OPTIONAL")
    receipt.insert(ProductUomConversion, id=1, company_id=1, product_variant_id=101,
                   from_uom_id=2, to_uom_id=1, numerator=Decimal("12"), denominator=Decimal("1"))
    receipt.session.commit()
    body = receipt.body(None)
    row = body["items"][0]
    body["items"] = [row, {**row, "uom_id": 2}, {**row, "expiry_date": FUTURE + timedelta(days=1)}]
    body["purchase_reference_selections"] = [
        dict(product_variant_id=101, uom_id=2, unit_cost=row["unit_cost"]),
    ]
    await receipt.post(body)
    assert len(receipt.batches()) == 2
    assert len(receipt.posted) == 3
    assert sorted(m["quantity"] for m in receipt.posted) == [Decimal("2.500001"), Decimal("2.500001"), Decimal("30.000012")]
    assert sorted([m["batch_id"] for m in receipt.posted].count(b.id) for b in receipt.batches()) == [1, 2]


@pytest.mark.asyncio
async def test_anonymous_null_and_nonnull_metadata_form_distinct_groups(receipt):
    receipt.configure("NONE", "OPTIONAL")
    body = receipt.body(None)
    body["items"] = [{**body["items"][0], "production_date": production, "expiry_date": expiry}
                     for production, expiry in ((None, None), (None, FUTURE), (PAST, None), (PAST, FUTURE))]
    await receipt.post(body)
    assert len(receipt.batches()) == 4
    assert len({m["batch_id"] for m in receipt.posted}) == 4


@pytest.mark.asyncio
async def test_optional_real_and_anonymous_lots_do_not_share_identity_with_equal_dates(receipt):
    receipt.configure("OPTIONAL")
    body = receipt.body(None)
    body["items"].append({**body["items"][0], "batch_number": REAL_LOT})
    await receipt.post(body)
    assert len(receipt.batches()) == 2
    assert REAL_LOT in {b.batch_number for b in receipt.batches()}
    assert len({m["batch_id"] for m in receipt.posted}) == 2


@pytest.mark.asyncio
async def test_duplicate_anonymous_group_and_uom_is_rejected(receipt):
    receipt.configure("NONE")
    body = receipt.body(None)
    InboundBatchItem.model_validate(body["items"][0])  # Rejecting null is not proof of duplicate protection.
    body["items"] *= 2
    with pytest.raises((ValidationError, HTTPException)):
        await receipt.post(body)
    assert receipt.movement.await_count == 0
    assert receipt.batches() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("lot,mode", [(None, "NONE"), (None, "OPTIONAL"), (REAL_LOT, "REQUIRED")])
@pytest.mark.parametrize("change", [
    {"unit_cost": "0.654321"}, {"quantity": "3"}, {"batch_number": "Another-real-lot"},
    {"production_date": PAST - timedelta(days=1)}, {"expiry_date": FUTURE + timedelta(days=1)},
], ids=["cost", "quantity", "lot", "production", "expiry"])
async def test_exact_replay_and_changed_input_are_durable(receipt, lot, mode, change):
    receipt.configure(mode)
    body = receipt.body(lot)
    initial = await receipt.post(body)
    original_ids = [b.id for b in receipt.batches()]
    assert await receipt.post(body) == initial
    assert [b.id for b in receipt.batches()] == original_ids
    assert receipt.movement.await_count == 1
    changed = {**body, "items": [{**body["items"][0], **change}]}
    with pytest.raises(HTTPException) as caught:
        await receipt.post(changed)
    assert caught.value.status_code == 409
    assert_no_leak(caught.value.detail)
    assert receipt.movement.await_count == 1


@pytest.mark.asyncio
async def test_replay_precedes_supplier_and_current_lot_rules(receipt):
    body = receipt.body()
    first = await receipt.post(body)
    receipt.configure("NONE")
    receipt.session.execute(receipt.tables["suppliers"].update().values(is_active=False))
    receipt.session.commit()
    assert await receipt.post(body) == first
    assert receipt.movement.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("original,replacement", [
    ((None, FUTURE), (PAST, FUTURE)),
    ((PAST, FUTURE), (None, FUTURE)),
    ((PAST, None), (PAST, FUTURE)),
    ((PAST, FUTURE), (PAST, None)),
    ((PAST, FUTURE), (PAST - timedelta(days=1), FUTURE)),
    ((PAST, FUTURE), (PAST, FUTURE + timedelta(days=1))),
])
async def test_named_lot_metadata_requires_exact_null_aware_match(receipt, original, replacement):
    await receipt.post(receipt.body(item=dict(production_date=original[0], expiry_date=original[1])))
    await rejected(receipt, receipt.body(item=dict(production_date=replacement[0], expiry_date=replacement[1])),
                   "INBOUND_BATCH_METADATA_CONFLICT", status=409)
    batch = receipt.batches()[0]
    assert (batch.production_date, batch.expiry_date) == original


@pytest.mark.asyncio
async def test_matching_real_lot_reuses_batch_preserving_each_purchase_input(receipt):
    for price in ("0.123456", "0.654321"):
        await receipt.post(receipt.body(item={"unit_cost": price}))
    assert len(receipt.batches()) == 1
    assert receipt.movement.await_count == 2
    assert len({line["batch_id"] for line in receipt.posted}) == 1
    assert [line["inventory_cost_input"]["input_unit_cost"] for line in receipt.posted] == [Decimal("0.123456"), Decimal("0.654321")]


@pytest.mark.asyncio
@pytest.mark.parametrize("lot_mode", ["NONE", "OPTIONAL", "REQUIRED"])
@pytest.mark.parametrize("expiry_mode,expiry,code", [
    ("NONE", None, None), ("NONE", FUTURE, "INBOUND_EXPIRY_NOT_ALLOWED"),
    ("OPTIONAL", None, None), ("OPTIONAL", FUTURE, None),
    ("REQUIRED", None, "INBOUND_EXPIRY_REQUIRED"), ("REQUIRED", FUTURE, None),
])
async def test_lot_and_expiry_modes_are_independent(receipt, lot_mode, expiry_mode, expiry, code):
    receipt.configure(lot_mode, expiry_mode)
    body = receipt.body(REAL_LOT if lot_mode == "REQUIRED" else None, item={"expiry_date": expiry})
    if code:
        await rejected(receipt, body, code, status=422)
    else:
        await receipt.post(body)
        assert receipt.batches()[0].expiry_date == expiry


@pytest.mark.asyncio
@pytest.mark.parametrize("production,expiry,code", [
    (PAST, AS_OF - timedelta(days=1), "INBOUND_BATCH_EXPIRED"),
    (AS_OF + timedelta(days=1), FUTURE, "INBOUND_PRODUCTION_DATE_FUTURE"),
    (AS_OF, AS_OF, None), (None, None, None),
])
async def test_company_local_date_boundaries_for_anonymous_stock(receipt, production, expiry, code):
    receipt.configure("NONE", "OPTIONAL")
    body = receipt.body(None, item={"production_date": production, "expiry_date": expiry})
    if code:
        await rejected(receipt, body, code, status=422)
    else:
        await receipt.post(body)
        receipt.clock.assert_awaited_once_with(receipt.db, 1)


@pytest.mark.asyncio
async def test_production_after_expiry_remains_rejected(receipt):
    receipt.configure("OPTIONAL", "OPTIONAL")
    body = receipt.body(None, item={"production_date": FUTURE, "expiry_date": PAST})
    await rejected(receipt, body, "INBOUND_BATCH_DATES_INVALID", status=422)
    receipt.clock.assert_awaited_once_with(receipt.db, 1)
    assert receipt.batches() == []


@pytest.mark.asyncio
async def test_foreign_variant_and_supplier_fail_closed(receipt):
    await rejected(receipt, receipt.body(item={"product_variant_id": 202}), "INBOUND_VARIANT_UNAVAILABLE", status=409)
    await rejected(receipt, receipt.body(supplier_id=62), "SUPPLIER_NOT_FOUND", status=404)
    assert receipt.batches() == []


@pytest.mark.asyncio
async def test_same_request_id_across_companies_has_independent_anonymous_stock(receipt):
    receipt.configure("NONE")
    receipt.configure("NONE", variant=202)
    body = receipt.body(None)
    await receipt.post(body)
    other = {**body, "supplier_id": 62, "location_id": 82,
             "items": [{**body["items"][0], "product_variant_id": 202}]}
    await receipt.post(other, access=receipt.access(company=2))
    assert {b.company_id for b in receipt.batches()} == {1, 2}
    assert len({b.id for b in receipt.batches()}) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("anonymous", [False, True], ids=["real-lot", "anonymous"])
async def test_non_owner_exact_location_grant_can_post_but_other_location_cannot(receipt, anonymous):
    receipt.configure("NONE" if anonymous else "REQUIRED")
    lot = None if anonymous else REAL_LOT
    receipt.grant("inbound.create", location=41)
    receipt.grant("supplier.read")
    access = receipt.access(owner=False)
    await receipt.post(receipt.body(lot), access=access)
    receipt.insert(InventoryLocation, id=42, company_id=1, code="WH-OTHER", name="Other",
                   location_type="WAREHOUSE", is_active=True, is_system_managed=False, version=1)
    receipt.session.commit()
    with pytest.raises(HTTPException) as caught:
        await receipt.post(receipt.body(lot, location_id=42), access=access)
    assert caught.value.status_code == 403
    assert receipt.movement.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("anonymous", [False, True], ids=["real-lot", "anonymous"])
async def test_product_location_inbound_disabled_remains_authoritative(receipt, anonymous):
    receipt.configure("NONE" if anonymous else "REQUIRED")
    receipt.session.execute(receipt.tables["product_locations"].update().where(
        receipt.tables["product_locations"].c.company_id == 1).values(
            operational_flags={"inbound_enabled": False, "outbound_enabled": True}))
    receipt.session.commit()
    await rejected(receipt, receipt.body(None if anonymous else REAL_LOT), "PRODUCT_LOCATION_INBOUND_DISABLED", status=409)


@pytest.mark.asyncio
@pytest.mark.parametrize("anonymous", [False, True], ids=["real-lot", "anonymous"])
@pytest.mark.parametrize("supplier,active,code,status", [
    (None, True, "SUPPLIER_REQUIRED", 422), (31, False, "SUPPLIER_INACTIVE", 409),
    (999, True, "SUPPLIER_NOT_FOUND", 404),
])
async def test_supplier_checks_unchanged(receipt, supplier, active, code, status, anonymous):
    receipt.configure("NONE" if anonymous else "REQUIRED")
    if not active:
        receipt.session.execute(receipt.tables["suppliers"].update().where(
            receipt.tables["suppliers"].c.id == 31).values(is_active=False))
        receipt.session.commit()
    await rejected(receipt, receipt.body(None if anonymous else REAL_LOT, supplier_id=supplier), code, status=status)


@pytest.mark.asyncio
async def test_location_grant_does_not_replace_company_supplier_permission(receipt):
    receipt.grant("inbound.create", location=41)
    await rejected(receipt, receipt.body(), "SUPPLIER_PERMISSION_DENIED", status=403,
                   access=receipt.access(owner=False))


@pytest.mark.asyncio
@pytest.mark.parametrize("anonymous", [False, True], ids=["real-lot", "anonymous"])
async def test_quantity_conversion_and_cost_inputs_remain_exact_decimals(receipt, anonymous):
    receipt.configure("NONE" if anonymous else "REQUIRED")
    receipt.insert(ProductUomConversion, id=1, company_id=1, product_variant_id=101,
                   from_uom_id=2, to_uom_id=1, numerator=Decimal("12"), denominator=Decimal("1"))
    receipt.session.commit()
    await receipt.post(receipt.body(None if anonymous else REAL_LOT, item={"uom_id": 2}))
    movement = receipt.posted[0]
    assert movement["quantity"] == Decimal("30.000012")
    assert isinstance(movement["quantity"], Decimal)
    cost = movement["inventory_cost_input"]
    assert cost["input_quantity"] == Decimal("2.500001")
    assert cost["input_unit_cost"] == Decimal("0.123456")
    assert cost["total_cost"] == Decimal("0.308640")
    assert all(not isinstance(value, float) for value in cost.values())
    receipt.activate.assert_awaited_once_with(receipt.db, company_id=1, actor_id=909)


@pytest.mark.asyncio
@pytest.mark.parametrize("anonymous", [False, True], ids=["real-lot", "anonymous"])
async def test_large_micro_quantity_is_not_rounded_through_binary_float(receipt, anonymous):
    receipt.configure("NONE" if anonymous else "REQUIRED")
    await receipt.post(receipt.body(None if anonymous else REAL_LOT,
                                   item={"quantity": "9007199254.740993", "unit_cost": "0.000001"}))
    movement = receipt.posted[0]
    assert movement["quantity"] == Decimal("9007199254.740993")
    assert movement["inventory_cost_input"]["input_quantity"] == Decimal("9007199254.740993")
    assert movement["inventory_cost_input"]["total_cost"] == Decimal("9007.199255")
    assert all(not isinstance(value, float) for value in movement["inventory_cost_input"].values())


@pytest.mark.asyncio
async def test_unrepresentable_base_quantity_is_rejected(receipt):
    receipt.configure(quantity_scale=0, quantity_step=Decimal("1"))
    await rejected(receipt, receipt.body(), "INBOUND_QUANTITY_CONVERSION_INVALID", status=422)


def test_storage_invariants_are_unchanged():
    assert InventoryBalance.__table__.c.batch_id.nullable is False
    assert InventoryMovement.__table__.c.batch_id.nullable is False
    assert ProductBatch.__table__.c.batch_number.nullable is False
    for model, name, columns in (
        (ProductBatch, "uq_product_batch_number", ("company_id", "product_variant_id", "batch_number")),
        (InventoryBalance, "uq_inv_balance_core", ("company_id", "location_id", "product_variant_id", "batch_id", "stock_status")),
    ):
        constraint = next(c for c in model.__table__.constraints if c.name == name)
        assert tuple(c.name for c in constraint.columns) == columns
    fk = next(c for c in InventoryBalance.__table__.foreign_key_constraints if c.name == "fk_inv_balance_variant_batch")
    assert tuple(c.parent.name for c in fk.elements) == ("company_id", "product_variant_id", "batch_id")


@pytest.mark.asyncio
async def test_disposition_revision_error_does_not_echo_stored_internal_identity(receipt):
    receipt.insert(ProductBatch, id=11, company_id=1, product_variant_id=101,
                   batch_number=INTERNAL, production_date=None, expiry_date=None)
    receipt.session.commit()
    with pytest.raises(HTTPException) as caught:
        await transfers.change_batch_disposition(11, BatchDispositionChangeRequest(
            request_id=uuid4(), expected_revision=2, disposition="QUARANTINED", reason="Inspection"),
            receipt.db, receipt.access(), receipt.actor)
    assert caught.value.detail["code"] == "BATCH_DISPOSITION_REVISION_CONFLICT"
    assert_no_leak(caught.value.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_after_batch", [False, True], ids=["first-receipt", "failed-receipt"])
async def test_first_inbound_product_location_is_atomic_and_warehouse_scoped(receipt, fail_after_batch):
    receipt.session.execute(receipt.tables["product_locations"].delete().where(
        receipt.tables["product_locations"].c.company_id == 1))
    receipt.session.commit()
    with ExitStack() as patches:
        if fail_after_batch:
            patches.enter_context(patch.object(inbound, "activate_costing_for_first_receipt", AsyncMock(side_effect=RuntimeError("Injected pre-commit failure"))))
            with pytest.raises(HTTPException) as caught:
                await receipt.post(receipt.body())
            assert caught.value.status_code == 500
        else:
            await receipt.post(receipt.body())
    assignments = list(receipt.session.scalars(select(ProductLocation).where(ProductLocation.company_id == 1)))
    assert [(row.location_id, row.product_variant_id) for row in assignments] == ([] if fail_after_batch else [(41, 101)])
    if fail_after_batch:
        assert receipt.batches() == []


class Result:
    def __init__(self, rows=(), scalar=None, one=None):
        self.rows, self.value, self.row = list(rows), scalar, one

    def all(self):
        return self.rows

    def scalars(self):
        return self

    def scalar_one(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value

    def one_or_none(self):
        return self.row


class ScriptedDB:
    def __init__(self, *, execute=(), scalar=(), scalars=()):
        self.responses = dict(execute=list(execute), scalar=list(scalar), scalars=list(scalars))

    def take(self, kind):
        assert self.responses[kind], f"Unexpected {kind} query; update probe fixture, never bypass serializer"
        return self.responses[kind].pop(0)

    async def execute(self, _statement):
        return self.take("execute")

    async def scalar(self, _statement):
        return self.take("scalar")

    async def scalars(self, _statement):
        return self.take("scalars")

    async def commit(self):
        pass

    async def rollback(self):
        pass


def presentation_access():
    return NS(company_id=1, require=AsyncMock(), allows=lambda *_a, **_kw: true(),
              location_filter=lambda *_a, **_kw: true(), codes=AsyncMock(return_value=[]),
              codes_by_location=AsyncMock(return_value={41: ["inventory.read"]}))


def batch_row(number, **extra):
    return NS(id=11, batch_id=11, product_variant_id=101, batch_number=number,
              production_date=None, expiry_date=None, disposition="RELEASED",
              disposition_reason=None, disposition_revision=1, is_active=True,
              lot_control_mode="NONE",  # Historical real lots must not be hidden from product mode alone.
              updated_at=datetime(2026, 10, 15), **extra)


@pytest.mark.asyncio
@pytest.mark.parametrize("number,expected", [(INTERNAL, None), (REAL_LOT, REAL_LOT)])
@pytest.mark.parametrize("surface", ["inventory", "stock_sources", "ledger", "transfer_detail", "stocktake", "quality_average", "quality_fifo", "disposition"])
async def test_operator_surfaces_never_expose_internal_lot(surface, number, expected):
    access = presentation_access()
    with ExitStack() as patches:
        if surface == "inventory":
            row = batch_row(number, on_hand_total=Decimal("5"), reserved_total=Decimal("0"),
                            sellable_on_hand=Decimal("5"), sellable_reserved=Decimal("0"),
                            quarantined_quantity=0, blocked_quantity=0, recalled_quantity=0,
                            damaged_quantity=0, disposal_pending_quantity=0, expiry_unavailable_quantity=0)
            db = ScriptedDB(execute=[Result(one=NS(location_type="WAREHOUSE", is_active=True, can_read=True)),
                Result(one=NS(variant_id=101, currency_code="JOD", as_of_date=AS_OF)),
                Result(rows=[NS(batch_id=11, expiry_date=None)]), Result(rows=[row]), Result()])
            response = await live_stock.get_warehouse_inventory_batches(101, 41, None, 100, db, access)
            assert response["batches"][0]["batch_id"] == 11
        elif surface == "stock_sources":
            row = batch_row(number, base_uom_id=1, base_uom_code="EACH", lifecycle_status="ACTIVE",
                            operational_hold="NONE", expiry_control_mode="NONE", batch_is_active=True, as_of_date=AS_OF)
            db = ScriptedDB(execute=[Result(one=row), Result()], scalar=[True])
            for name, result in (("first_quality_source_limit_excess", None),
                                 ("read_special_transfer_destinations", {}), ("read_terminal_origin_availability", {})):
                patches.enter_context(patch.object(live_stock, name, AsyncMock(return_value=result)))
            response = await live_stock.get_batch_stock_sources(11, db, access)
            assert response["batch_id"] == 11
        elif surface == "ledger":
            movement = NS(id=9, batch_id=11, product_variant_id=101, movement_kind="PHYSICAL",
                          quantity=Decimal("5"), source_location_id=None, destination_location_id=41,
                          source_stock_status=None, destination_stock_status="AVAILABLE", notes=None,
                          created_at=datetime(2026, 10, 15), reference_id="receipt-9", reference_type="INBOUND_SUPPLIER")
            uom = NS(id=1, code="EACH", name="Each")
            snapshot = NS(movement_id=9, location_delta=Decimal("5"),
                          cumulative_delta=Decimal("5"), total_delta=Decimal("5"),
                          current_total=Decimal("5"))
            db = ScriptedDB(
                execute=[
                    Result(scalar=1),  # filtered movement count
                    Result(rows=[(movement, "Product", uom, 6, Decimal("0.000001"), "Operator")]),
                    Result(rows=[snapshot]),  # product/location balance reconstruction
                    Result(),  # display UOMs: fall back to the real base UOM
                    Result(rows=[(11, number)]),
                    Result(rows=[(41, "Warehouse")]),
                    Result(),  # movement impacts
                ],
                scalar=[41, "JOD"],  # exact warehouse authorization, then currency
                scalars=[Result(), Result()],  # supplier evidence, then cost events
            )
            access.db = db
            response = await ledger.get_warehouse_ledger_cursor(41, None, 50, None, None, "receipt-9", db, access)
            access.require.assert_awaited_once_with("ledger.read", 41)
            assert response["items"][0]["id"] == 9
        elif surface == "transfer_detail":
            line = NS(id=19, product_variant_id=101, batch_id=11, quantity=Decimal("5"),
                      fefo_override_reason_id=None, fefo_overridden_by=None, fefo_override_note=None)
            db = ScriptedDB(execute=[Result(scalar=NS(id=7)), Result(rows=[(line, "Product", 1, number, None)])])
            patches.enter_context(patch.object(transfers, "_require_transfer_document", AsyncMock()))
            header = dict(id=7, reference_number="TRANSFER-7", source_location_id=41,
                          source_location_name="Origin", destination_location_id=42,
                          destination_location_name="Destination", transfer_purpose="WAREHOUSE_BALANCING",
                          status="POSTED", dispatched_by=909, dispatched_by_name="Operator",
                          line_count=1, total_quantity="5", created_at=datetime(2026, 10, 15),
                          updated_at=datetime(2026, 10, 15))
            patches.enter_context(patch.object(transfers, "_serialize_transfer_headers", AsyncMock(return_value=[header])))
            response = await transfers.get_unified_transfer_detail(7, db, access)
            assert response["lines"][0]["batch_id"] == 11
        elif surface == "stocktake":
            db = ScriptedDB(execute=[Result(scalar=41), Result(scalar=101), Result(scalar=1),
                                     Result(rows=[batch_row(number)])])
            response = await stocktake.list_stocktake_cycle_batches(41, 101, None, None, 50, db, access)
            assert response["items"][0]["id"] == 11
        elif surface.startswith("quality_"):
            method = "FIFO" if surface.endswith("fifo") else "MOVING_AVERAGE"
            rows = [NS(location_id=41, batch_id=11, on_hand_quantity=Decimal("5"), reserved_quantity=0,
                       location_name="Warehouse", location_type="WAREHOUSE", location_active=True, batch_number=number)]
            execute = [Result(one=NS(operational_hold="RECALL", lifecycle_revision=1)), Result(rows=rows)]
            if method == "FIFO":
                execute.append(Result(rows=[NS(batch_id=11, remaining_quantity=Decimal("5"),
                                               remaining_value=Decimal("10"), batch_number=number)]))
            db = ScriptedDB(execute=execute, scalar=[NS(currency_code="JOD"),
                NS(quantity=Decimal("5"), inventory_value=Decimal("10"), average_unit_cost=Decimal("2"))])
            patches.enter_context(patch.object(quality_preview, "_current_recall_reason", AsyncMock(return_value=None)))
            patches.enter_context(patch.object(quality_preview, "get_cost_policy", AsyncMock(return_value=NS(is_active=True, method=method))))
            response = await quality_preview.get_whole_product_quality_preview(101, db, access)
            assert response["valuation_available"] is True
            assert len(response["valuation_lines"]) == 1
        else:
            db = ScriptedDB()
            patches.enter_context(patch.object(transfers, "_require_transfer_capability", AsyncMock()))
            patches.enter_context(patch.object(transfers, "begin_idempotent_operation", AsyncMock(return_value=(NS(), None))))
            patches.enter_context(patch.object(transfers, "complete_idempotent_operation"))
            patches.enter_context(patch.object(transfers, "change_product_batch_disposition", AsyncMock(return_value=batch_row(number))))
            response = await transfers.change_batch_disposition(11, BatchDispositionChangeRequest(
                request_id=uuid4(), expected_revision=1, disposition="QUARANTINED", reason="Inspection"), db, access, NS(id=909))
            assert response["batch_id"] == 11
        assert_business_lots(response, expected)
        # Exercise declared transport DTOs too: a serializer-only null fix must
        # not leave FastAPI response validation rejecting anonymous batches.
        endpoint = {
            "inventory": live_stock.get_warehouse_inventory_batches,
            "stock_sources": live_stock.get_batch_stock_sources,
            "ledger": ledger.get_warehouse_ledger_cursor,
            "transfer_detail": transfers.get_unified_transfer_detail,
            "stocktake": stocktake.list_stocktake_cycle_batches,
            "quality_average": quality_preview.get_whole_product_quality_preview,
            "quality_fifo": quality_preview.get_whole_product_quality_preview,
            "disposition": transfers.change_batch_disposition,
        }[surface]
        module = {
            "inventory": live_stock, "stock_sources": live_stock, "ledger": ledger,
            "transfer_detail": transfers, "stocktake": stocktake,
            "quality_average": quality_preview, "quality_fifo": quality_preview,
            "disposition": transfers,
        }[surface]
        response_model = next(route.response_model for route in module.router.routes if route.endpoint is endpoint)
        if response_model is not None:
            assert_business_lots(TypeAdapter(response_model).validate_python(response), expected)
        assert all(not remaining for remaining in db.responses.values()), db.responses
