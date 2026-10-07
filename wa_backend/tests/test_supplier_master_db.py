"""Real PostgreSQL V1 acceptance, restricted to an explicitly owned gate database.

Main ORM schema is the upgrade baseline; this feature's actual Alembic revision
is run on it. Runtime is a non-superuser. Each business test rolls back its own
outer transaction; handlers commit SAVEPOINTs. Authentication is overridden,
while API validation, permissions, SQL/RLS, movement/costing and audit are real.
"""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api.dependencies import get_current_driver
from api.suppliers import router as supplier_router
from api.warehouse.inbound import router as inbound_router
from api.warehouse.whole_product_quality import router as quality_router
from api.warehouse.ledger import router as ledger_router
from database import get_db
from inventory_access import PERMISSIONS
from main import WanasahRawASGIMiddleware, custom_http_exception_handler, validation_exception_handler
from models import (Base, Company, Driver, InventoryLocation, Product, ProductVariant,
                    ProductBatch, InventoryMovement, UOM, utc_now, DomainAuditEvent)
from models import OperationIdempotency
from schemas import UpgradedInboundRequest
from api.warehouse._shared import _stable_request_hash
from api.warehouse.whole_product_quality import WholeProductQualityResolveRequest
from domains.inventory_supplier_evidence import InventorySupplierEvidence
from domains.suppliers.models import Supplier

pytestmark = pytest.mark.skipif(os.getenv("WANASAH_SUPPLIER_DB_GATE") != "1", reason="Explicit isolated Supplier gate database only")
GATE_PASSWORD = "SupplierGateSupervisor123"


def revision_module():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/b7f2a9c4d681_supplier_master_v1.py"
    spec = importlib.util.spec_from_file_location("supplier_revision", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest_asyncio.fixture(scope="module")
async def gate():
    from sqlalchemy.engine import make_url
    admin_url = os.environ["DATABASE_URL_MIGRATION"]
    assert make_url(admin_url).database == "supplier_master_gate"
    schema = "supplier_gate_" + uuid4().hex
    root_engine = create_async_engine(admin_url, poolclass=NullPool)
    async with root_engine.begin() as conn:
        for extension in ("btree_gist", "btree_gin", "pg_trgm"):
            await conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {extension}"))
        await conn.execute(text("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='supplier_runtime') THEN CREATE ROLE supplier_runtime LOGIN; END IF; END $$"))
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    settings = {"server_settings": {"search_path": f"{schema},public"}}
    admin_engine = create_async_engine(admin_url, poolclass=NullPool, connect_args=settings)
    async with admin_engine.begin() as conn:
        baseline_tables = [table for table in Base.metadata.sorted_tables if table.name not in {"suppliers", "inventory_supplier_evidence"}]
        await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=baseline_tables))
        await conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO supplier_runtime'))
        await conn.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO supplier_runtime'))
        await conn.execute(text(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" TO supplier_runtime'))
    async with AsyncSession(admin_engine, expire_on_commit=False) as seed:
        companies = [Company(name=f"Gate {index}", company_code=f"SG{index}") for index in (1, 2)]
        seed.add_all(companies); await seed.flush()
        actors = [Driver(company_id=c.id, username="gate", full_name="Gate admin", password_hash="synthetic", is_admin=True) for c in companies]
        for actor in actors:
            actor.set_password(GATE_PASSWORD)
        seed.add_all(actors); await seed.flush()
        uom = UOM(name="Each", code="EACH"); seed.add(uom); await seed.flush()
        products = [Product(company_id=c.id, code="P", name="Gate product") for c in companies]
        seed.add_all(products); await seed.flush()
        variants = [ProductVariant(company_id=c.id, product_id=p.id, name="Gate product", sku="P", base_uom_id=uom.id,
                                   lifecycle_status="ACTIVE", published_at=utc_now(), expiry_control_mode="NONE") for c, p in zip(companies, products)]
        locations = [InventoryLocation(company_id=c.id, code="WH", name="Gate warehouse", location_type="WAREHOUSE") for c in companies]
        seed.add_all(variants + locations); await seed.flush()
        batch = ProductBatch(company_id=companies[0].id, product_variant_id=variants[0].id, batch_number="LEGACY")
        seed.add(batch); await seed.flush()
        legacy = InventoryMovement(company_id=companies[0].id, performed_by=actors[0].id, destination_location_id=locations[0].id,
                                   destination_stock_status="AVAILABLE", product_variant_id=variants[0].id, batch_id=batch.id,
                                   quantity=1, reference_type="INBOUND_SUPPLIER", reference_id="LEGACY", idempotency_key="LEGACY")
        seed.add(legacy)
        seed.add(DomainAuditEvent(company_id=companies[0].id, actor_user_id=actors[0].id, event_type="INVENTORY_VENDOR_HANDOVER_CONFIRMED",
                                 entity_type="InventoryMovement", entity_id="legacy", reason_code="LEGACY", reason_text="Legacy",
                                 request_id=uuid4(), after_snapshot={"vendor_name": "Manual legacy recipient"}))
        await seed.commit()
    async with admin_engine.begin() as conn:
        old_count = await conn.scalar(text("SELECT count(*) FROM inventory_movements"))
        await conn.execute(text("CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY)"))
        await conn.execute(text("INSERT INTO alembic_version VALUES ('b8e4d7a91c52')"))
        def migrate(sync):
            with Operations.context(MigrationContext.configure(sync, opts={"target_metadata": Base.metadata})):
                revision_module().upgrade()
        await conn.run_sync(migrate)
        await conn.execute(text("UPDATE alembic_version SET version_num='b7f2a9c4d681'"))
        assert await conn.scalar(text("SELECT count(*) FROM inventory_movements")) == old_count
        assert await conn.scalar(text("SELECT count(*) FROM inventory_supplier_evidence")) == 0
        for code in PERMISSIONS:
            await conn.execute(text("INSERT INTO permissions(code) VALUES(:code) ON CONFLICT(code) DO NOTHING"), {"code": code})
    runtime_engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool, connect_args=settings)
    yield SimpleNamespace(engine=runtime_engine, admin_engine=admin_engine, companies=companies, actors=actors,
                          variants=variants, locations=locations, uom=uom, legacy=legacy, schema=schema)
    await runtime_engine.dispose(); await admin_engine.dispose(); await root_engine.dispose()


@pytest_asyncio.fixture
async def api(gate):
    conn = await gate.engine.connect()
    outer = await conn.begin()
    db = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
    actor = SimpleNamespace(id=gate.actors[0].id, company_id=gate.companies[0].id, is_admin=True, is_active=True,
                            password_hash=gate.actors[0].password_hash)
    await db.execute(text("SELECT set_config('app.current_tenant',:tenant,true)"), {"tenant": str(actor.company_id)})
    app = FastAPI()
    for router in (supplier_router, inbound_router, quality_router, ledger_router):
        app.include_router(router)
    app.add_exception_handler(HTTPException, custom_http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_middleware(WanasahRawASGIMiddleware)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_driver] = lambda: actor
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://supplier-gate") as client:
        yield SimpleNamespace(client=client, db=db, actor=actor, gate=gate)
    await db.close(); await outer.rollback(); await conn.close()


async def create(api, name="ABC Trading", code="ABC"):
    body = {"request_id": str(uuid4()), "name": name, "code": code}
    result = await api.client.post("/suppliers", json=body)
    assert result.status_code == 201, result.text
    return result.json(), body


async def state(api, row, active):
    result = await api.client.patch(f"/suppliers/{row['id']}/state", json={"request_id": str(uuid4()), "expected_version": row["version"], "is_active": active})
    assert result.status_code == 200, result.text
    return result.json()


def inbound_body(api, supplier_id):
    return {"request_id": str(uuid4()), "supplier_id": supplier_id, "location_id": api.gate.locations[0].id,
            "reference_id": "SUP-GATE-" + uuid4().hex, "items": [{"product_variant_id": api.gate.variants[0].id,
            "quantity": "4", "uom_id": api.gate.uom.id, "unit_cost": "2.5", "batch_number": "NEW-" + uuid4().hex}]}


def assert_code(response, code, status):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert isinstance(error["context"], dict)
    assert error["request_id"] == response.headers["x-request-id"]


async def cost_policy(api):
    result = await api.client.put("/warehouse/costing-policy", json={"request_id": str(uuid4()), "method": "MOVING_AVERAGE", "expected_version": 0})
    assert result.status_code == 200, result.text


@pytest.mark.asyncio
async def test_supplier_lifecycle_replay_mismatch_and_audit(api):
    row, body = await create(api)
    assert (await api.client.get(f"/suppliers/{row['id']}")).json() == row
    assert (await api.client.post("/suppliers", json=body)).json() == row
    assert_code(await api.client.post("/suppliers", json={**body, "name": "Other"}), "SUPPLIER_REQUEST_CONFLICT", 409)
    edit = await api.client.put(f"/suppliers/{row['id']}", json={"request_id": str(uuid4()), "expected_version": 1, "name": "ABC Distribution", "phone": "+962123"})
    assert edit.status_code == 200, edit.text
    row = edit.json()
    assert row["name"] == "ABC Distribution" and row["version"] == 2
    row = await state(api, row, False); assert not row["is_active"]
    row = await state(api, row, True); assert row["is_active"]
    events = (await api.db.scalars(select(DomainAuditEvent).where(DomainAuditEvent.entity_type == "Supplier"))).all()
    assert len(events) == 4 and all(event.actor_user_id == api.actor.id and event.request_id for event in events)


@pytest.mark.asyncio
async def test_bounded_search_company_code_and_cursor_scope(api):
    for index in range(4):
        await create(api, f"Search {index}", f"S{index}")
    page = await api.client.get("/suppliers?active=true&search=Search&limit=2")
    assert len(page.json()["items"]) == 2 and page.json()["has_more"]
    cursor = page.json()["next_cursor"]
    next_page = await api.client.get("/suppliers", params={"active": "true", "search": "Search", "limit": 2, "cursor": cursor})
    assert len(next_page.json()["items"]) == 2 and not next_page.json()["has_more"]
    assert_code(await api.client.get("/suppliers", params={"active": "false", "search": "Search", "cursor": cursor}), "SUPPLIER_CURSOR_INVALID", 400)
    assert (await api.client.get("/suppliers?limit=101")).status_code == 422
    await create(api, "Duplicate names allowed", None); await create(api, "Duplicate names allowed", None)
    assert_code(await api.client.post("/suppliers", json={"request_id": str(uuid4()), "name": "Code duplicate", "code": "S0"}), "SUPPLIER_DATA_CONFLICT", 409)


@pytest.mark.asyncio
async def test_tenant_and_inactive_selection_fail_closed_at_direct_api(api):
    row, _ = await create(api)
    row = await state(api, row, False)
    assert_code(await api.client.post("/warehouse/inbound", json=inbound_body(api, row["id"])), "SUPPLIER_INACTIVE", 409)
    return_body = {"request_id": str(uuid4()), "action": "RETURN_TO_VENDOR", "reason": "Confirmed issue", "supplier_id": row["id"],
                   "confirmation_password": GATE_PASSWORD}
    path = f"/warehouse/quality/products/{api.gate.variants[0].id}/resolve-all"
    assert_code(await api.client.post(path, json=return_body), "SUPPLIER_INACTIVE", 409)
    api.actor.company_id = api.gate.companies[1].id; api.actor.id = api.gate.actors[1].id
    await api.db.execute(text("SELECT set_config('app.current_tenant',:tenant,true)"), {"tenant": str(api.actor.company_id)})
    assert (await api.client.get("/suppliers")).json()["items"] == []
    assert_code(await api.client.get(f"/suppliers/{row['id']}"), "SUPPLIER_NOT_FOUND", 404)
    assert_code(await api.client.put(f"/suppliers/{row['id']}", json={"request_id": str(uuid4()), "expected_version": row["version"], "name": "Foreign"}), "SUPPLIER_NOT_FOUND", 404)
    foreign_receipt = inbound_body(api, row["id"]); foreign_receipt["location_id"] = api.gate.locations[1].id
    assert_code(await api.client.post("/warehouse/inbound", json=foreign_receipt), "SUPPLIER_NOT_FOUND", 404)
    assert_code(await api.client.post(path, json={**return_body, "request_id": str(uuid4())}), "SUPPLIER_NOT_FOUND", 404)


@pytest.mark.asyncio
async def test_permission_separation_and_revocation_before_replay(api):
    row, body = await create(api)
    api.actor.is_admin = False
    assert_code(await api.client.get("/suppliers"), "SUPPLIER_PERMISSION_DENIED", 403)
    assert_code(await api.client.post("/suppliers", json=body), "SUPPLIER_PERMISSION_DENIED", 403)
    await api.db.execute(text("INSERT INTO roles(company_id,name,is_system_role) VALUES(:company,'Supplier reader',false)"), {"company": api.actor.company_id})
    role_id = await api.db.scalar(text("SELECT id FROM roles WHERE name='Supplier reader'"))
    await api.db.execute(text("INSERT INTO user_roles(company_id,driver_id,role_id) VALUES(:company,:actor,:role)"), {"company": api.actor.company_id, "actor": api.actor.id, "role": role_id})
    await api.db.execute(text("INSERT INTO role_permissions(company_id,role_id,permission_id) SELECT :company,:role,id FROM permissions WHERE code='supplier.read'"), {"company": api.actor.company_id, "role": role_id})
    assert (await api.client.get("/suppliers")).status_code == 200
    assert_code(await api.client.patch(f"/suppliers/{row['id']}/state", json={"request_id": str(uuid4()), "expected_version": 1, "is_active": False}), "SUPPLIER_PERMISSION_DENIED", 403)
    await api.db.execute(text("DELETE FROM role_permissions WHERE role_id=:role"), {"role": role_id})
    assert_code(await api.client.get("/suppliers"), "SUPPLIER_PERMISSION_DENIED", 403)


@pytest.mark.asyncio
async def test_inbound_snapshot_rename_legacy_read_and_replay_after_deactivation(api):
    row, _ = await create(api); await cost_policy(api)
    body = inbound_body(api, row["id"])
    posted = await api.client.post("/warehouse/inbound", json=body)
    assert posted.status_code == 201, posted.text
    edited = await api.client.put(f"/suppliers/{row['id']}", json={"request_id": str(uuid4()), "expected_version": 1, "name": "Renamed", "code": "NEW"})
    assert edited.status_code == 200, edited.text
    row = await state(api, edited.json(), False)
    assert (await api.client.post("/warehouse/inbound", json=body)).json() == posted.json()
    ledger = await api.client.get("/warehouse/ledger/cursor", params={"location_id": api.gate.locations[0].id})
    assert ledger.status_code == 200, ledger.text
    new = next(item for item in ledger.json()["items"] if item["reference"] == body["reference_id"])
    old = next(item for item in ledger.json()["items"] if item["reference"] == "LEGACY")
    assert new["supplier_id"] == row["id"] and new["supplier_name"] == "ABC Trading" and new["supplier_code"] == "ABC"
    assert old["supplier_id"] is None and old["supplier_name"] is None
    assert new["total_cost"] == "10.000000"
    assert_code(await api.client.post("/warehouse/inbound", json={**body, "supplier_id": row["id"] + 999}), "INBOUND_REJECTED", 409)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["RETURN_TO_VENDOR", "DISPOSE"])
async def test_whole_product_return_snapshot_and_dispose_parity(api, action):
    row, _ = await create(api); await cost_policy(api)
    posted = await api.client.post("/warehouse/inbound", json=inbound_body(api, row["id"]))
    assert posted.status_code == 201, posted.text
    await api.db.execute(text("UPDATE product_variants SET operational_hold='RECALL' WHERE id=:variant"), {"variant": api.gate.variants[0].id})
    body = {"request_id": str(uuid4()), "action": action, "reason": "Confirmed issue", "confirmation_password": GATE_PASSWORD}
    if action == "RETURN_TO_VENDOR": body["supplier_id"] = row["id"]
    path = f"/warehouse/quality/products/{api.gate.variants[0].id}/resolve-all"
    await api.db.commit()
    movement_count = await api.db.scalar(text("SELECT count(*) FROM inventory_movements"))
    assert_code(await api.client.post(path, json={**body, "confirmation_password": "wrong"}), "SUPERVISOR_CONFIRMATION_FAILED", 403)
    assert await api.db.scalar(text("SELECT count(*) FROM inventory_movements")) == movement_count
    response = await api.client.post(path, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["total_quantity"] == "4" and response.json()["location_count"] == 1
    assert (await api.client.post(path, json=body)).json() == response.json()
    assert await api.db.scalar(text("SELECT sum(on_hand_quantity) FROM inventory_balances")) == 0
    assert await api.db.scalar(text("SELECT operational_hold FROM product_variants WHERE id=:variant"), {"variant": api.gate.variants[0].id}) == "NONE"
    assert await api.db.scalar(select(DomainAuditEvent.id).where(DomainAuditEvent.event_type == "ProductRecallClosed")) is not None
    # A new valid supervisor credential must not change business command identity.
    changed_credential = Driver(); changed_credential.set_password("RefreshedSupervisor123")
    api.actor.password_hash = changed_credential.password_hash
    assert (await api.client.post(path, json={**body, "confirmation_password": "RefreshedSupervisor123"})).json() == response.json()
    final_evidence = (await api.db.scalars(select(InventorySupplierEvidence).join(InventoryMovement,
        InventoryMovement.id == InventorySupplierEvidence.movement_id).where(InventoryMovement.reference_type == "FINAL_VENDOR_HANDOVER"))).all()
    if action == "RETURN_TO_VENDOR":
        assert len(final_evidence) == 1 and final_evidence[0].supplier_name == "ABC Trading"
        event = await api.db.scalar(select(DomainAuditEvent).where(DomainAuditEvent.event_type == "INVENTORY_VENDOR_HANDOVER_CONFIRMED", DomainAuditEvent.entity_id != "legacy"))
        assert event.after_snapshot["supplier_id"] == row["id"]
        assert event.after_snapshot["vendor_name"] == "ABC Trading"
        renamed = await api.client.put(f"/suppliers/{row['id']}", json={"request_id": str(uuid4()), "expected_version": 1, "name": "Later name"})
        assert renamed.status_code == 200
        await api.db.refresh(final_evidence[0])
        assert final_evidence[0].supplier_name == "ABC Trading" and final_evidence[0].request_id.hex == body["request_id"].replace("-", "")
    else:
        assert not final_evidence
    legacy = await api.db.scalar(select(DomainAuditEvent).where(DomainAuditEvent.entity_id == "legacy"))
    assert legacy.after_snapshot["vendor_name"] == "Manual legacy recipient"


@pytest.mark.asyncio
async def test_rls_missing_tenant_cross_tenant_write_and_immutable_evidence(api):
    assert not await api.db.scalar(text("SELECT rolsuper FROM pg_roles WHERE rolname=current_user"))
    row, _ = await create(api)
    await api.db.execute(text("SELECT set_config('app.current_tenant','',true)"))
    assert await api.db.scalar(text("SELECT count(*) FROM suppliers")) == 0
    await api.db.execute(text("SELECT set_config('app.current_tenant',:tenant,true)"), {"tenant": str(api.actor.company_id)})
    with pytest.raises(Exception, match="row-level security"):
        async with api.db.begin_nested():
            await api.db.execute(text("INSERT INTO suppliers(company_id,name,created_by,updated_by) VALUES(:company,'Foreign',:actor,:actor)"), {"company": api.gate.companies[1].id, "actor": api.gate.actors[1].id})
    await cost_policy(api)
    assert (await api.client.post("/warehouse/inbound", json=inbound_body(api, row["id"]))).status_code == 201
    async with api.gate.admin_engine.begin() as conn:
        assert await conn.scalar(text("SELECT relforcerowsecurity FROM pg_class WHERE oid='suppliers'::regclass"))
    # Runtime cannot update evidence; the trigger also protects privileged updates.
    with pytest.raises(Exception, match="permission denied"):
        await api.db.execute(text("UPDATE inventory_supplier_evidence SET supplier_name='Rewritten'"))
    await api.db.rollback()


@pytest.mark.asyncio
async def test_single_migration_head_and_downgrade_preserves_identity(api):
    config = AlembicConfig(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == ["b7f2a9c4d681"]
    async with api.gate.admin_engine.connect() as conn:
        outer = await conn.begin()
        await conn.execute(text("INSERT INTO suppliers(company_id,name,created_by,updated_by) VALUES(:company,'Downgrade guard',:actor,:actor)"), {"company": api.actor.company_id, "actor": api.actor.id})
        def downgrade(sync):
            with Operations.context(MigrationContext.configure(sync)):
                revision_module().downgrade()
        with pytest.raises(Exception, match="Cannot downgrade"):
            await conn.run_sync(downgrade)
        await outer.rollback()
    # A migration actor unable to bypass RLS cannot prove an all-company empty
    # history. Its downgrade must fail before DROP, even with no tenant context.
    await api.db.execute(text("SELECT set_config('app.current_tenant','',true)"))
    with pytest.raises(Exception, match="row-level security"):
        async with api.db.begin_nested():
            await api.db.run_sync(lambda sync_session: downgrade(sync_session.connection()))


@pytest.mark.asyncio
@pytest.mark.parametrize("credential_in_hash", [False, True])
async def test_legacy_commands_replay_but_new_manual_operations_are_rejected(api, credential_in_hash):
    old_inbound = inbound_body(api, None); old_inbound.pop("supplier_id")
    old_quality = {"request_id": str(uuid4()), "action": "RETURN_TO_VENDOR", "reason": "Legacy issue",
                   "recipient_name": "Manual historical recipient", "handover_reference": "LEGACY-HANDOVER",
                   "confirmation_password": GATE_PASSWORD}
    for payload, model, operation, response, context in (
        (old_inbound, UpgradedInboundRequest, "WAREHOUSE_INBOUND", {"message": "INBOUND_POSTED"}, None),
        (old_quality, WholeProductQualityResolveRequest, "WHOLE_PRODUCT_QUALITY_RESOLVE_ALL", {
            "message": "Legacy completed", "action": "RETURN_TO_VENDOR", "product_variant_id": api.gate.variants[0].id,
            "total_quantity": "1", "location_count": 1, "locations": [{"location_id": api.gate.locations[0].id, "location_name": "Gate warehouse", "quantity": "1"}]},
         {"product_variant_id": api.gate.variants[0].id}),
    ):
        api.db.add(OperationIdempotency(company_id=api.actor.company_id, operation=operation, request_id=payload["request_id"],
            request_hash=_stable_request_hash(model(**payload), context=context,
                exclude_fields={"supplier_id"} if credential_in_hash else {"supplier_id", "confirmation_password"}),
            created_by=api.actor.id, completed_at=utc_now(), response_json=response))
    await api.db.commit()
    assert (await api.client.post("/warehouse/inbound", json=old_inbound)).status_code == 201
    path = f"/warehouse/quality/products/{api.gate.variants[0].id}/resolve-all"
    assert (await api.client.post(path, json=old_quality)).status_code == 200
    assert_code(await api.client.post(path, json={**old_quality, "reason": "Changed history"}), "WHOLE_PRODUCT_QUALITY_REJECTED", 409)
    assert_code(await api.client.post("/warehouse/inbound", json={**old_inbound, "request_id": str(uuid4())}), "SUPPLIER_REQUIRED", 422)
    assert_code(await api.client.post(path, json={**old_quality, "request_id": str(uuid4())}), "SUPPLIER_REQUIRED", 422)


@pytest.mark.asyncio
async def test_privileged_snapshot_update_is_blocked_by_database_trigger(api):
    async with api.gate.admin_engine.connect() as conn:
        outer = await conn.begin()
        supplier_id = await conn.scalar(text("INSERT INTO suppliers(company_id,name,created_by,updated_by) VALUES(:company,'Immutable',:actor,:actor) RETURNING id"),
            {"company": api.actor.company_id, "actor": api.actor.id})
        await conn.execute(text("INSERT INTO inventory_supplier_evidence(company_id,movement_id,supplier_id,supplier_name,request_id) VALUES(:company,:movement,:supplier,'Immutable',:request)"),
            {"company": api.actor.company_id, "movement": api.gate.legacy.id, "supplier": supplier_id, "request": uuid4()})
        with pytest.raises(Exception, match="Supplier document evidence is immutable"):
            await conn.execute(text("UPDATE inventory_supplier_evidence SET supplier_name='Rewritten'"))
        await outer.rollback()


@pytest.mark.asyncio
async def test_multisupplier_stock_is_one_operator_selected_return_and_location_atomic(api):
    supplier_a, _ = await create(api, "Supplier A", "A")
    supplier_b, _ = await create(api, "Supplier B", "B")
    await cost_policy(api)
    second = InventoryLocation(company_id=api.actor.company_id, code="WH2", name="Second warehouse", location_type="WAREHOUSE")
    api.db.add(second); await api.db.flush()
    second_id = second.id
    for supplier_id, location_id in ((supplier_a["id"], api.gate.locations[0].id), (supplier_b["id"], second_id)):
        receipt = inbound_body(api, supplier_id); receipt["location_id"] = location_id
        posted = await api.client.post("/warehouse/inbound", json=receipt)
        assert posted.status_code == 201, posted.text
    await api.db.execute(text("UPDATE product_variants SET operational_hold='RECALL' WHERE id=:variant"), {"variant": api.gate.variants[0].id})
    role_ids = []
    for name, codes in (("Gate company", ("supplier.read", "transfer.special.return_to_vendor")),
                        ("Gate location", ("inventory.read", "transfer.send", "inventory.vendor_return.confirm", "inbound.create"))):
        role_id = await api.db.scalar(text("INSERT INTO roles(company_id,name,is_system_role) VALUES(:company,:name,false) RETURNING id"),
            {"company": api.actor.company_id, "name": name})
        role_ids.append(role_id)
        for code in codes:
            await api.db.execute(text("INSERT INTO role_permissions(company_id,role_id,permission_id) SELECT :company,:role,id FROM permissions WHERE code=:code"),
                {"company": api.actor.company_id, "role": role_id, "code": code})
    await api.db.execute(text("INSERT INTO user_roles(company_id,driver_id,role_id) VALUES(:company,:actor,:role)"),
        {"company": api.actor.company_id, "actor": api.actor.id, "role": role_ids[0]})
    grant = text("INSERT INTO user_location_access(company_id,driver_id,location_id,role_id) VALUES(:company,:actor,:location,:role)")
    await api.db.execute(grant, {"company": api.actor.company_id, "actor": api.actor.id, "location": api.gate.locations[0].id, "role": role_ids[1]})
    # Grant edits represent independently committed access administration.
    await api.db.commit(); api.actor.is_admin = False
    body = {"request_id": str(uuid4()), "action": "RETURN_TO_VENDOR", "reason": "Confirmed issue", "supplier_id": supplier_a["id"],
            "confirmation_password": GATE_PASSWORD}
    path = f"/warehouse/quality/products/{api.gate.variants[0].id}/resolve-all"
    assert_code(await api.client.post(path, json=body), "WHOLE_PRODUCT_QUALITY_LOCATION_PERMISSION_DENIED", 403)
    assert await api.db.scalar(text("SELECT sum(on_hand_quantity) FROM inventory_balances")) == 8
    await api.db.execute(grant, {"company": api.actor.company_id, "actor": api.actor.id, "location": second_id, "role": role_ids[1]})
    await api.db.commit()
    returned = await api.client.post(path, json=body)
    assert returned.status_code == 200, returned.text
    assert returned.json()["total_quantity"] == "8" and returned.json()["location_count"] == 2
    selected_ids = (await api.db.scalars(select(InventorySupplierEvidence.supplier_id).join(InventoryMovement,
        InventoryMovement.id == InventorySupplierEvidence.movement_id).where(InventoryMovement.reference_type == "FINAL_VENDOR_HANDOVER"))).all()
    assert selected_ids == [supplier_a["id"], supplier_a["id"]]
    await api.db.execute(text("DELETE FROM user_location_access WHERE location_id=:location"), {"location": second_id})
    await api.db.commit()
    assert_code(await api.client.post(path, json=body), "WHOLE_PRODUCT_QUALITY_LOCATION_PERMISSION_DENIED", 403)
