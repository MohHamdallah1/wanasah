"""Real PostgreSQL 16 acceptance for CP6.2 shelf-life policy closure.

Runs only against the disposable CI database named wanasah_cp6_policy_test on
127.0.0.1:55456. Runtime is a restricted NOSUPERUSER/NOBYPASSRLS role.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, timedelta
from decimal import Decimal
import os
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import and_, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from context import tenant_context
from domains.inventory_rules import batch_sellability_predicate
from domains.inventory_stock_policy import (
    InventoryStockPolicyReadNotFound,
    read_effective_shelf_life_policy,
)
from models import (
    Company,
    InventoryLocation,
    InventoryStockPolicy,
    Product,
    ProductBatch,
    ProductLocation,
    ProductVariant,
    UOM,
    utc_now,
)
from tests.canonical_actor_fixtures import seed_company_owner_fixture


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CP6_POLICY_PG_GATE") != "1",
        reason="Explicit disposable CP6 policy PostgreSQL gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


def _checked_urls():
    urls = [
        make_url(os.environ[name])
        for name in ("WANASAH_CP6_POLICY_PG_URL", "WANASAH_CP6_POLICY_PG_ADMIN_URL")
    ]
    for url in urls:
        if (
            url.drivername != "postgresql+asyncpg"
            or url.host != "127.0.0.1"
            or url.port != 55456
            or url.database != "wanasah_cp6_policy_test"
        ):
            raise RuntimeError("Refusing any database outside the disposable CP6 policy gate")
    if urls[0].username != "cp6_policy_app" or urls[1].username == urls[0].username:
        raise RuntimeError("CP6 policy requires distinct restricted runtime and migration roles")
    return urls


class Gate:
    def __init__(self, runtime_engine, admin_engine):
        self.runtime_engine = runtime_engine
        self.admin_engine = admin_engine
        self.a = None
        self.b = None
        self.as_of = date(2026, 10, 16)

    @asynccontextmanager
    async def session(self, tenant):
        token = tenant_context.set(tenant.company_id)
        try:
            async with self.runtime_engine.connect() as connection:
                db = AsyncSession(bind=connection, expire_on_commit=False)
                try:
                    await db.execute(
                        text("SELECT set_config('app.current_tenant',:tenant,false)"),
                        {"tenant": str(tenant.company_id)},
                    )
                    await db.execute(text("SET statement_timeout='15000ms'"))
                    yield db
                finally:
                    await db.close()
        finally:
            tenant_context.reset(token)


@pytest_asyncio.fixture(loop_scope="function")
async def pg():
    runtime_url, admin_url = _checked_urls()
    runtime_engine = create_async_engine(runtime_url, poolclass=NullPool)
    admin_engine = create_async_engine(admin_url, poolclass=NullPool)
    gate = Gate(runtime_engine, admin_engine)
    try:
        async with runtime_engine.connect() as connection:
            identity = (
                await connection.execute(
                    text(
                        "SELECT current_database(),current_user,inet_server_port(),r.rolsuper,r.rolbypassrls "
                        "FROM pg_roles r WHERE r.rolname=current_user"
                    )
                )
            ).one()
            assert tuple(identity) == (
                "wanasah_cp6_policy_test",
                "cp6_policy_app",
                55456,
                False,
                False,
            )

        config = AlembicConfig(str(Path(__file__).parents[1] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
        expected_heads = set(ScriptDirectory.from_config(config).get_heads())

        async with AsyncSession(admin_engine, expire_on_commit=False) as seed:
            assert set(
                (await seed.execute(text("SELECT version_num FROM alembic_version"))).scalars()
            ) == expected_heads
            uom = await seed.scalar(select(UOM).where(UOM.code == "EACH"))
            if uom is None:
                uom = UOM(code="EACH", name="CP6 policy each")
                seed.add(uom)
                await seed.flush()

            tenants = []
            for index, minimum_days in ((0, 10), (1, 30)):
                company = Company(
                    name=f"CP6 Policy Company {index}",
                    company_code=f"CP6P-{index}-{uuid4().hex}",
                    timezone="Asia/Amman",
                    currency_code="JOD",
                )
                seed.add(company)
                await seed.flush()
                await seed.execute(
                    text("SELECT set_config('app.current_tenant',:tenant,true)"),
                    {"tenant": str(company.id)},
                )
                owner = await seed_company_owner_fixture(
                    seed,
                    company.id,
                    password="CP6PolicyFixturePassword123",
                )
                product = Product(
                    company_id=company.id,
                    code=f"CP6P-{index}",
                    name=f"CP6 policy product {index}",
                )
                seed.add(product)
                await seed.flush()
                variant = ProductVariant(
                    company_id=company.id,
                    product_id=product.id,
                    name=f"CP6 policy SKU {index}",
                    sku=f"CP6-SKU-{index}-{uuid4().hex[:8]}",
                    base_uom_id=uom.id,
                    quantity_scale=0,
                    quantity_step=Decimal("1"),
                    lot_control_mode="REQUIRED",
                    expiry_control_mode="REQUIRED",
                    lifecycle_status="ACTIVE",
                    published_at=utc_now(),
                )
                locations = [
                    InventoryLocation(
                        company_id=company.id,
                        code=f"CP6-WH-{index}-{slot}-{uuid4().hex[:6]}",
                        name=f"CP6 warehouse {index}-{slot}",
                        location_type="WAREHOUSE",
                        is_active=True,
                    )
                    for slot in range(2 if index == 0 else 1)
                ]
                seed.add_all([variant, *locations])
                await seed.flush()
                for location in locations:
                    seed.add(
                        ProductLocation(
                            company_id=company.id,
                            location_id=location.id,
                            product_variant_id=variant.id,
                            created_by=owner.driver_id,
                            operational_flags={
                                "inbound_enabled": True,
                                "outbound_enabled": True,
                            },
                        )
                    )
                seed.add(
                    InventoryStockPolicy(
                        company_id=company.id,
                        location_id=locations[0].id,
                        product_variant_id=variant.id,
                        minimum_quantity=Decimal("0"),
                        target_quantity=None,
                        minimum_remaining_shelf_life_days=minimum_days,
                        is_active=True,
                    )
                )
                if index == 0:
                    for batch_number, offset in (
                        ("BOUNDARY", 10),
                        ("BELOW", 9),
                        ("TODAY", 0),
                        ("EXPIRED", -1),
                    ):
                        seed.add(
                            ProductBatch(
                                company_id=company.id,
                                product_variant_id=variant.id,
                                batch_number=f"CP6-{batch_number}-{uuid4().hex[:6]}",
                                production_date=gate.as_of - timedelta(days=5),
                                expiry_date=gate.as_of + timedelta(days=offset),
                                disposition="RELEASED",
                                disposition_reason=None,
                                disposition_revision=1,
                                is_active=True,
                            )
                        )
                await seed.flush()
                tenants.append(
                    NS(
                        company_id=company.id,
                        variant_id=variant.id,
                        locations=[row.id for row in locations],
                    )
                )
            gate.a, gate.b = tenants
            await seed.commit()
        yield gate
    finally:
        await runtime_engine.dispose()
        await admin_engine.dispose()


async def _sql_sellability(db, gate, location_id: int):
    minimum_days = func.coalesce(
        InventoryStockPolicy.minimum_remaining_shelf_life_days,
        0,
    )
    sellable = batch_sellability_predicate(
        gate.as_of,
        expiry_control_mode=ProductVariant.expiry_control_mode,
        minimum_remaining_shelf_life_days=minimum_days,
    )
    rows = (
        await db.execute(
            select(ProductBatch.batch_number, sellable.label("sellable"))
            .join(
                ProductVariant,
                and_(
                    ProductVariant.company_id == ProductBatch.company_id,
                    ProductVariant.id == ProductBatch.product_variant_id,
                ),
            )
            .outerjoin(
                InventoryStockPolicy,
                and_(
                    InventoryStockPolicy.company_id == gate.a.company_id,
                    InventoryStockPolicy.location_id == int(location_id),
                    InventoryStockPolicy.product_variant_id == ProductVariant.id,
                    InventoryStockPolicy.is_active.is_(True),
                ),
            )
            .where(
                ProductBatch.company_id == gate.a.company_id,
                ProductBatch.product_variant_id == gate.a.variant_id,
            )
        )
    ).all()
    return {
        next(part for part in str(batch_number).split("-") if part in {"BOUNDARY", "BELOW", "TODAY", "EXPIRED"}): bool(value)
        for batch_number, value in rows
    }


async def test_cp6_effective_policy_is_exact_company_location_product_scope(pg):
    a1, a2 = pg.a.locations
    async with pg.session(pg.a) as db:
        a1_policy = await read_effective_shelf_life_policy(
            db,
            company_id=pg.a.company_id,
            location_id=a1,
            product_variant_id=pg.a.variant_id,
        )
        assert a1_policy.minimum_remaining_shelf_life_days == 10
        assert a1_policy.requirement_applies is True
        assert a1_policy.source == "EXACT_ACTIVE_POLICY"

        a2_policy = await read_effective_shelf_life_policy(
            db,
            company_id=pg.a.company_id,
            location_id=a2,
            product_variant_id=pg.a.variant_id,
        )
        assert a2_policy.minimum_remaining_shelf_life_days == 0
        assert a2_policy.requirement_applies is False
        assert a2_policy.source == "NO_ACTIVE_POLICY"

        with pytest.raises(InventoryStockPolicyReadNotFound):
            await read_effective_shelf_life_policy(
                db,
                company_id=pg.a.company_id,
                location_id=pg.b.locations[0],
                product_variant_id=pg.b.variant_id,
            )
        with pytest.raises(InventoryStockPolicyReadNotFound):
            await read_effective_shelf_life_policy(
                db,
                company_id=pg.a.company_id,
                location_id=a1,
                product_variant_id=pg.b.variant_id,
            )


async def test_cp6_sellability_uses_effective_policy_boundary_and_zero_semantics(pg):
    a1, a2 = pg.a.locations
    async with pg.session(pg.a) as db:
        with_policy = await _sql_sellability(db, pg, a1)
        without_policy = await _sql_sellability(db, pg, a2)

    assert with_policy == {
        "BOUNDARY": True,
        "BELOW": False,
        "TODAY": False,
        "EXPIRED": False,
    }
    assert without_policy == {
        "BOUNDARY": True,
        "BELOW": True,
        "TODAY": True,
        "EXPIRED": False,
    }
