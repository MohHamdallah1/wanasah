"""Seed only a disposable GitHub PostgreSQL fixture after canonical Alembic."""
import asyncio
import os
from uuid import uuid4

import main  # Register canonical metadata; never create/alter schema here.
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from context import tenant_context
from models import Company, InventoryLocation, Product, ProductVariant, UOM, utc_now
from tests.canonical_actor_fixtures import seed_company_owner_fixture


async def seed():
    assert os.environ.get("WANASAH_FIELD_CONTRACT_PG_GATE") == "1"
    url = os.environ["DATABASE_URL_MIGRATION"]
    assert make_url(url).database == "wanasah_field_contracts"
    assert make_url(url).host in ("127.0.0.1", "localhost")
    engine = create_async_engine(url, poolclass=NullPool)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        company = Company(name="FIELD prerequisite synthetic", company_code="FIELD-" + uuid4().hex[:16])
        db.add(company)
        await db.flush()
        token = tenant_context.set(company.id)
        try:
            await db.execute(text("SELECT set_config('app.current_tenant',:t,true)"), {"t": str(company.id)})
            await seed_company_owner_fixture(db, company.id, password="FieldSyntheticFixture123")
            base = await db.scalar(select(UOM.id).where(UOM.code == "EACH"))
            product = Product(company_id=company.id, code="FIELD-MASTER", name="FIELD synthetic product")
            warehouse = InventoryLocation(
                company_id=company.id, code="FIELD-WH", name="FIELD warehouse",
                location_type="WAREHOUSE", is_active=True, is_system_managed=False,
            )
            db.add_all([product, warehouse])
            await db.flush()
            db.add(ProductVariant(
                company_id=company.id, product_id=product.id, sku="FIELD-SKU",
                name="FIELD tracked juice", base_uom_id=base, packs_per_carton=50,
                lot_control_mode="REQUIRED", expiry_control_mode="REQUIRED",
                lifecycle_status="ACTIVE", published_at=utc_now(),
            ))
            await db.commit()
            tenant = company.id
        finally:
            tenant_context.reset(token)
    await engine.dispose()
    variables = {
        "WANASAH_C2_CUSTOMER_RETURN_DB_GATE": "1",
        "WANASAH_C2_CUSTOMER_RETURN_TEST_TENANT": str(tenant),
        "WANASAH_C2_CUSTOMER_RETURN_EXPECTED_DB": "wanasah_field_contracts",
        "WANASAH_C2_REAL_SALE_DB_GATE": "1",
        "WANASAH_C2_REAL_SALE_TEST_TENANT": str(tenant),
        "WANASAH_C2_REAL_SALE_EXPECTED_DB": "wanasah_field_contracts",
    }
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as output:
        output.write("".join(key + "=" + value + "\n" for key, value in variables.items()))
    print(f"FIELD_DISPOSABLE_FIXTURE_COMPANY={tenant}")


if __name__ == "__main__":
    asyncio.run(seed())
