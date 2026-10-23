"""Real FIELD HTTP fixtures on disposable migrated CI PostgreSQL only."""
import os
import unittest
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace as NS
from uuid import uuid4

import httpx
import pytest_asyncio
from sqlalchemy import select, text, delete, event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from main import app
from database import engine as runtime_engine
from context import tenant_context
from domains.authorization.field_models import FieldRepresentativeRole
from domains.authorization.field_provisioning import assign_new_representative_default
from domains.authorization.capabilities import FIELD_ASSIGNABLE_PERMISSIONS, PERMISSIONS
from domains.identity.models import CompanyPrincipal, BackofficeUser
from domains.identity.migration.models import IdentityLegacyDriverMap
from models import (
    Company, UOM, Product, ProductVariant, InventoryLocation, Permission, Role, role_permissions,
    UserRole, Visit, WorkSession, DispatchRoute, InventoryTransferHeader, InventoryTransferLine,
    PriceBookEntry,
)
from tests.canonical_actor_fixtures import seed_company_owner_fixture, seed_field_fixture
from tests.supplier_fixtures import seed_receipt_supplier
import tests.test_costed_driver_customer_return_c2_db as customer_fixture
import tests.test_costed_driver_sale_correction_real_c2_db as sale_fixture
from services import apply_inventory_movements_batch

PASSWORD = "Phase3SyntheticOnly123"


def auth(token):
    return {"Authorization": "Bearer " + token}


async def call(g, method, path, body=None, token=None):
    return await g.client.request(method, path, json=body, headers=auth(token or g.token))


def denied(response, status=403, code="FIELD_CAPABILITY_DENIED"):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["request_id"]
    assert isinstance(error["context"], dict)
    if code:
        assert error["code"] == code, error


async def evidence(g):
    # Hash ALL tenant business rows, not just selected totals; no secrets printed.
    async with g.admin.connect() as db:
        names = (await db.execute(text(
            "SELECT table_name FROM information_schema.columns WHERE table_schema='public' "
            "AND column_name='company_id' ORDER BY table_name"))).scalars().all()
        result = []
        for name in names:
            digest = await db.scalar(text(
                'SELECT array_agg(md5(row_to_json(t)::text) ORDER BY md5(row_to_json(t)::text)) '
                'FROM "' + name + '" t WHERE company_id=:c'), {"c":g.tenant})
            result.append((name, digest))
        return result


async def set_codes(g, codes):
    # Deliberate test setup only; live grant/revoke behavior is separately exercised over HTTP.
    async with AsyncSession(g.admin) as db:
        await db.execute(delete(FieldRepresentativeRole).where(
            FieldRepresentativeRole.company_id == g.tenant,
            FieldRepresentativeRole.field_representative_id == g.field.context.representative_id))
        if set(codes) == FIELD_ASSIGNABLE_PERMISSIONS:
            role_id = g.default_role
        else:
            role = Role(company_id=g.tenant, name="P3-" + uuid4().hex, is_system_role=False)
            db.add(role)
            await db.flush()
            role_id = role.id
            permissions = (await db.scalars(select(Permission.id).where(Permission.code.in_(codes)))).all()
            if permissions:
                await db.execute(role_permissions.insert(), [
                    {"company_id":g.tenant,"role_id":role_id,"permission_id":p} for p in permissions])
        db.add(FieldRepresentativeRole(company_id=g.tenant,
            field_representative_id=g.field.context.representative_id,role_id=role_id))
        await db.commit()


async def new_transfers(g, count=2, destination=None):
    ids = []
    async with AsyncSession(g.admin, expire_on_commit=False) as db:
        await db.execute(text("SELECT set_config('app.current_tenant',:c,true)"),{"c":str(g.tenant)})
        for _ in range(count):
            header = InventoryTransferHeader(
                company_id=g.tenant, reference_number="P3-" + uuid4().hex,
                source_location_id=g.warehouse_id, destination_location_id=destination or g.location,
                workflow_type="HANDSHAKE", status="PENDING", transfer_purpose="REPLENISHMENT",
                commercial_context={}, work_session_id=g.session,
                expected_receiver_id=g.field.driver.id, dispatched_by=g.actor.id)
            db.add(header)
            await db.flush()
            db.add(InventoryTransferLine(company_id=g.tenant, transfer_header_id=header.id,
                product_variant_id=g.variant["id"], batch_id=g.batch, quantity=Decimal("1"),
                source_stock_status="AVAILABLE", lifecycle_revision_snapshot=1,
                lifecycle_status_snapshot="ACTIVE", operational_hold_snapshot="NONE"))
            await db.flush()
            await apply_inventory_movements_batch(db, company_id=g.tenant,performed_by=g.actor.id,
                movements=[{"product_variant_id":g.variant["id"],"batch_id":g.batch,"quantity":Decimal("1"),
                    "movement_kind":"RESERVATION","reservation_action":"RESERVE",
                    "reference_type":"HANDSHAKE_RESERVE","reference_id":header.reference_number,
                    "idempotency_key":"P3-RES-" + str(header.id),
                    "source_location_id":g.warehouse_id,"destination_location_id":g.warehouse_id,
                    "source_stock_status":"AVAILABLE","destination_stock_status":"AVAILABLE",
                    "work_session_id":g.session,"transfer_header_id":header.id}])
            ids.append(header.id)
        await db.commit()
    return ids


async def seed_business(admin):
    token = None
    try:
        async with AsyncSession(admin, expire_on_commit=False) as db:
            company = Company(name="Phase3 Synthetic", company_code="P3-" + uuid4().hex[:16], timezone="UTC")
            db.add(company)
            await db.flush()
            token = tenant_context.set(company.id)
            await db.execute(text("SELECT set_config('app.current_tenant',:c,true)"),{"c":str(company.id)})
            owner = await seed_company_owner_fixture(db,company.id,password=PASSWORD)
            field = await seed_field_fixture(db,company.id,password=PASSWORD)
            other = await seed_field_fixture(db,company.id,password=PASSWORD)
            await assign_new_representative_default(db,company.id,field.context.representative_id)
            await assign_new_representative_default(db,company.id,other.context.representative_id)
            supplier = await seed_receipt_supplier(db,owner.operational_driver)
            base = await db.scalar(select(UOM.id).where(UOM.code=="EACH"))
            product = Product(company_id=company.id,code="P3",name="Synthetic product")
            warehouse = InventoryLocation(company_id=company.id,code="P3-WH",name="Warehouse",
                location_type="WAREHOUSE",is_active=True,is_system_managed=False)
            db.add_all([product,warehouse])
            await db.flush()
            variant = ProductVariant(company_id=company.id,product_id=product.id,sku="P3-SKU",
                name="Synthetic tracked item",base_uom_id=base,packs_per_carton=50,
                lot_control_mode="REQUIRED",expiry_control_mode="REQUIRED",
                lifecycle_status="ACTIVE",published_at=__import__("models").utc_now())
            db.add(variant)
            await db.commit()
            g = NS(tenant=company.id,company_code=company.company_code,owner=owner,
                actor=owner.operational_driver,field=field,other=other,warehouse_id=warehouse.id,
                variant={"id":variant.id,"base_uom_id":base,"packs_per_carton":50},
                supplier_id=supplier,db=db,admin=admin)
            # Reuse proven fixture authorities; execute real inbound, pricing, tax and cost engines.
            checker = unittest.TestCase()
            g.assertEqual, g.assertIsNotNone = checker.assertEqual, checker.assertIsNotNone
            async def commercial(visit):
                context_id=await sale_fixture.RealDriverSaleCorrectionC2DatabaseTests._create_real_commercial_context(g,visit)
                # The older sale fixture publishes EACH only. FIELD read models
                # require an explicit published CARTON price as well; never derive it in the client.
                base_price=await db.scalar(select(PriceBookEntry).where(
                    PriceBookEntry.company_id==g.tenant,
                    PriceBookEntry.product_variant_id==g.variant["id"]))
                carton=await db.scalar(select(UOM.id).where(UOM.code=="CARTON"))
                db.add(PriceBookEntry(company_id=g.tenant,price_book_id=base_price.price_book_id,
                    publication_id=base_price.publication_id,product_variant_id=g.variant["id"],
                    uom_id=carton,amount=Decimal("250.000000"),effectivity=base_price.effectivity,
                    is_published=True,priority=0,entry_metadata={}))
                await db.flush()
                return context_id
            g.visit,g.location,g.batch = await customer_fixture.RealCustomerReturnC2DatabaseTests._create_business_fixture(
                g,"FIFO",commercial_context_factory=commercial)
            route = await db.scalar(select(DispatchRoute).where(DispatchRoute.company_id==g.tenant))
            g.route,g.session,g.zone,g.vehicle = route.id,route.work_session_id,route.zone_id,route.vehicle_id
            g.default_role = await db.scalar(select(Role.id).where(
                Role.company_id==g.tenant,Role.system_key=="FIELD_REPRESENTATIVE_V1"))
            g.field_name = await db.scalar(select(CompanyPrincipal.username).where(
                CompanyPrincipal.id==field.context.principal_id))
            g.other_name = await db.scalar(select(CompanyPrincipal.username).where(
                CompanyPrincipal.id==other.context.principal_id))
            g.owner_name = await db.scalar(select(CompanyPrincipal.username).where(
                CompanyPrincipal.id==owner.context.principal_id))
            # Independent BO subject shares only the legacy operational locator.
            principal = CompanyPrincipal(company_id=g.tenant,username="dual-"+uuid4().hex,
                full_name="BO dual",password_hash=field.driver.password_hash,principal_type="BACKOFFICE",
                is_active=True,auth_revision=1)
            db.add(principal)
            await db.flush()
            profile = BackofficeUser(company_id=g.tenant,principal_id=principal.id)
            db.add(profile)
            await db.flush()
            bridge = await db.get(IdentityLegacyDriverMap,(g.tenant,field.driver.id))
            bridge.classification="DUAL_SPLIT"
            bridge.backoffice_principal_id,bridge.backoffice_user_id=principal.id,profile.id
            role = Role(company_id=g.tenant,name="BO-full",is_system_role=False)
            db.add(role)
            await db.flush()
            ids=(await db.scalars(select(Permission.id).where(Permission.code.in_(PERMISSIONS)))).all()
            await db.execute(role_permissions.insert(),[
                {"company_id":g.tenant,"role_id":role.id,"permission_id":p} for p in ids])
            db.add(UserRole(company_id=g.tenant,driver_id=field.driver.id,role_id=role.id))
            g.bo_name=principal.username
            await db.commit()
            return g
    finally:
        if token is not None:
            tenant_context.reset(token)


@pytest_asyncio.fixture(scope="module")
async def gate():
    for key in ("DATABASE_URL","DATABASE_URL_MIGRATION"):
        url=make_url(os.environ[key])
        assert url.database=="field_auth_phase3_gate" and url.host in ("127.0.0.1","localhost")
    admin=create_async_engine(os.environ["DATABASE_URL_MIGRATION"],poolclass=NullPool)
    @event.listens_for(admin.sync_engine,"begin")
    def seed_tenant(connection):
        connection.execute(text("SELECT set_config('app.current_tenant',:c,true)"),
                           {"c":str(tenant_context.get() or "")})
    g=await seed_business(admin)
    foreign=await seed_business(admin)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),
                                 base_url="http://field-phase3") as client:
        g.client=client
        async def login(company,name,path):
            r=await client.post(path,json={"company_code":company,"username":name,"password":PASSWORD})
            assert r.status_code==200,r.text
            return r.json()
        g.login=await login(g.company_code,g.field_name,"/driver/login")
        g.token=g.login["token"]
        g.other_token=(await login(g.company_code,g.other_name,"/driver/login"))["token"]
        g.owner_token=(await login(g.company_code,g.owner_name,"/login"))["token"]
        g.bo_token=(await login(g.company_code,g.bo_name,"/login"))["token"]
        g.foreign_token=(await login(foreign.company_code,foreign.field_name,"/driver/login"))["token"]
        g.foreign=foreign
        g.transfers=await new_transfers(g)
        async with runtime_engine.connect() as db:
            privileges=(await db.execute(text(
                "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"))).one()
            assert privileges==(False,False)
        yield g
    await runtime_engine.dispose()
    await admin.dispose()
