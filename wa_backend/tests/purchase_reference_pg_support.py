"""Fixtures for a disposable GitHub PostgreSQL database, never a developer DB."""
from contextlib import asynccontextmanager
from decimal import Decimal
import os
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest_asyncio
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from models import (
    Company, InventoryLocation, Permission, PriceBook, Product, ProductUomConversion,
    ProductVariant, Role, UOM, UserRole, role_permissions, utc_now,
)
from tests.canonical_actor_fixtures import seed_company_owner_fixture, seed_ordinary_backoffice_fixture
from domains.authorization.capabilities import PERMISSIONS


class Gate:
    def __init__(self, runtime, admin):
        self.runtime, self.admin = runtime, admin

    @asynccontextmanager
    async def session(self, tenant):
        async with AsyncSession(self.runtime, expire_on_commit=False) as db:
            await db.execute(text("SELECT set_config('app.current_tenant',:tenant,false)"),
                             {"tenant": str(tenant.company_id)})
            await db.execute(text("SET statement_timeout='10000ms'"))
            try:
                yield db
            finally:
                await db.rollback()

    async def write(self, tenant, payload, actor=None):
        from domains.inventory_costing.purchase_reference.public import write_manual_reference
        async with self.session(tenant) as db:
            result = await write_manual_reference(
                db, access=(actor or tenant.owner).access(db),
                product_variant_id=tenant.variant_id, payload=payload,
            )
            await db.commit()
            return result

    async def grant(self, tenant, codes):
        async with AsyncSession(self.admin, expire_on_commit=False) as db:
            await db.execute(text("SELECT set_config('app.current_tenant',:tenant,true)"),
                             {"tenant": str(tenant.company_id)})
            role = Role(company_id=tenant.company_id, name="PCR-" + uuid4().hex)
            db.add(role)
            await db.flush()
            ids = list((await db.scalars(select(Permission.id).where(Permission.code.in_(codes)))).all())
            assert len(ids) == len(codes)
            await db.execute(role_permissions.insert(), [
                {"company_id": tenant.company_id, "role_id": role.id, "permission_id": value} for value in ids
            ])
            db.add(UserRole(company_id=tenant.company_id, driver_id=tenant.ordinary.driver_id, role_id=role.id))
            await db.commit()
            return role.id


@pytest_asyncio.fixture
async def pg():
    if os.getenv("WANASAH_PURCHASE_REFERENCE_DB_GATE") != "1":
        raise RuntimeError("Disposable PostgreSQL gate opt-in is required")
    runtime_url, admin_url = [make_url(os.environ[name]) for name in ("DATABASE_URL", "DATABASE_URL_MIGRATION")]
    for url in (runtime_url, admin_url):
        if (url.drivername != "postgresql+asyncpg" or url.host != "127.0.0.1"
                or url.port != 5432 or url.database != "wanasah_purchase_reference_gate"):
            raise RuntimeError("Refusing a database outside the disposable purchase-reference gate")
    assert runtime_url.username == "purchase_reference_runtime"
    assert admin_url.username == "purchase_reference_gate"
    runtime = create_async_engine(runtime_url, poolclass=NullPool)
    admin = create_async_engine(admin_url, poolclass=NullPool)
    gate = Gate(runtime, admin)
    try:
        async with runtime.connect() as db:
            identity = (await db.execute(text(
                "SELECT current_database(),current_user,r.rolsuper,r.rolbypassrls "
                "FROM pg_roles r WHERE r.rolname=current_user"
            ))).one()
            assert tuple(identity) == ("wanasah_purchase_reference_gate", "purchase_reference_runtime", False, False)
        async with AsyncSession(admin, expire_on_commit=False) as db:
            # The disposable DB must be at THIS checked-out repository's
            # canonical migration head; a frozen list of past heads silently
            # breaks whenever an unrelated accepted migration is added.
            expected_migration = ScriptDirectory.from_config(
                Config("alembic.ini")
            ).get_current_head()
            actual_migration = await db.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            assert actual_migration == expected_migration, (
                actual_migration, expected_migration
            )
            for code in PERMISSIONS:
                await db.execute(text("INSERT INTO permissions(code) VALUES(:code) ON CONFLICT(code) DO NOTHING"),
                                 {"code": code})
            each = await db.scalar(select(UOM).where(UOM.code == "EACH"))
            carton = await db.scalar(select(UOM).where(UOM.code == "CARTON"))
            tenants = []
            for _ in range(2):
                company = Company(name="Purchase reference gate", company_code="PCR-" + uuid4().hex,
                                  timezone="Asia/Amman", currency_code="JOD")
                db.add(company)
                await db.flush()
                await db.execute(text("SELECT set_config('app.current_tenant',:tenant,true)"),
                                 {"tenant": str(company.id)})
                owner = await seed_company_owner_fixture(db, company.id, password="ReferenceFixturePassword123")
                ordinary = await seed_ordinary_backoffice_fixture(db, company.id)
                product = Product(company_id=company.id, code="P", name="Reference product")
                db.add(product)
                await db.flush()
                variant = ProductVariant(
                    company_id=company.id, product_id=product.id, name="Reference SKU", sku="PCR",
                    base_uom_id=each.id, quantity_scale=0, quantity_step=Decimal("1"),
                    lot_control_mode="NONE", expiry_control_mode="NONE",
                    lifecycle_status="ACTIVE", published_at=utc_now(),
                )
                warehouse = InventoryLocation(company_id=company.id, code="WH", name="Reference warehouse",
                                              location_type="WAREHOUSE", is_active=True)
                book = PriceBook(company_id=company.id, code="PCR", name="Independent sale prices",
                                 currency_code="JOD", created_by=owner.driver_id)
                db.add_all([variant, warehouse, book])
                await db.flush()
                db.add(ProductUomConversion(
                    company_id=company.id, product_variant_id=variant.id,
                    from_uom_id=carton.id, to_uom_id=each.id,
                    numerator=Decimal("12"), denominator=Decimal("1"), quantity_scale=0,
                ))
                tenants.append(NS(company_id=company.id, variant_id=variant.id,
                                  each_id=each.id, carton_id=carton.id, location_id=warehouse.id,
                                  owner=owner, ordinary=ordinary))
            await db.commit()
            gate.a, gate.b = tenants
        yield gate
    finally:
        await runtime.dispose()
        await admin.dispose()
