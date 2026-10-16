"""CP14-A2 real PostgreSQL Product <-> Warehouse readiness acceptance.

Bounded to Product readiness only: explicit ProductLocation assignment/scoping,
operational flags, lifecycle eligibility, and read-only Inbound tracking options.
No receipt, batch, transfer, stocktake, quality, or lifecycle mutation is executed.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
import os
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api import product_locations
from api.warehouse import inbound
from context import tenant_context
from domains.authorization.backoffice_access import BackofficeCapabilityAccessRejected
from domains.authorization.capabilities import COMPANY_ONLY, PERMISSIONS
from models import (
    Company,
    InventoryBalance,
    InventoryLocation,
    InventoryMovement,
    OperationIdempotency,
    Permission,
    Product,
    ProductBatch,
    ProductLocation,
    ProductVariant,
    Role,
    UOM,
    UserLocationAccess,
    role_permissions,
    utc_now,
)
from product_lifecycle import (
    DEFAULT_PRODUCT_LOCATION_FLAGS,
    INBOUND_NEW,
    REPLENISHMENT_NEW,
    ROUTE_LOAD_NEW,
    WAREHOUSE_BALANCING,
    product_location_allows,
)
from schemas import InboundOptionsRequest
from tests.canonical_actor_fixtures import (
    seed_company_owner_fixture,
    seed_ordinary_backoffice_fixture,
)


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CP14A2_PG_GATE") != "1",
        reason="Explicit disposable CP14-A2 PostgreSQL gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]

SCOPED_CAPABILITIES = (
    "product_location.read",
    "product_location.manage",
    "inventory.read",
    "location.read",
    "inbound.create",
)
TRACKING = (
    ("NONE", "NONE"),
    ("OPTIONAL", "OPTIONAL"),
    ("REQUIRED", "REQUIRED"),
)


def _checked_urls():
    runtime = make_url(os.environ["WANASAH_CP14A2_PG_URL"])
    admin = make_url(os.environ["WANASAH_CP14A2_PG_ADMIN_URL"])
    for url in (runtime, admin):
        if (
            url.drivername != "postgresql+asyncpg"
            or url.host != "127.0.0.1"
            or url.port != 55452
            or url.database != "wanasah_cp14a2_test"
        ):
            raise RuntimeError("Refusing any database outside disposable CP14-A2 PostgreSQL")
    if runtime.username != "cp14a2_app" or admin.username == runtime.username:
        raise RuntimeError("CP14-A2 requires distinct restricted runtime and migration roles")
    return runtime, admin


def _assert_opaque(exc: HTTPException, *foreign_ids: int) -> None:
    rendered = repr(exc.detail)
    for value in foreign_ids:
        assert str(value) not in rendered


@asynccontextmanager
async def _runtime_session(engine, company_id: int):
    token = tenant_context.set(company_id)
    try:
        async with engine.connect() as connection:
            db = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                await db.execute(
                    text("SELECT set_config('app.current_tenant', :tenant, false)"),
                    {"tenant": str(company_id)},
                )
                await db.execute(text("SET statement_timeout='15000ms'"))
                yield db
            finally:
                await db.close()
    finally:
        tenant_context.reset(token)


async def _grant_a1_scope(db, *, company_id: int, driver_id: int, location_id: int) -> None:
    role = Role(company_id=company_id, name="CP14-A2 A1 product readiness")
    db.add(role)
    await db.flush()
    for code in SCOPED_CAPABILITIES:
        permission = await db.scalar(select(Permission).where(Permission.code == code))
        assert permission is not None, f"Migrated permission missing: {code}"
        await db.execute(
            role_permissions.insert().values(
                company_id=company_id,
                role_id=role.id,
                permission_id=permission.id,
            )
        )
    db.add(
        UserLocationAccess(
            company_id=company_id,
            role_id=role.id,
            driver_id=driver_id,
            location_id=location_id,
        )
    )
    await db.flush()


async def _seed_variants(db, *, company_id: int, uom_id: int, draft: bool = False):
    variants = []
    for index, (lot_mode, expiry_mode) in enumerate(TRACKING, start=1):
        product = Product(
            company_id=company_id,
            code=f"P{index}",
            name=f"Shared Product {index}",
        )
        db.add(product)
        await db.flush()
        variant = ProductVariant(
            company_id=company_id,
            product_id=product.id,
            name=f"Shared SKU {index}",
            sku=f"SKU-P{index}",
            base_uom_id=uom_id,
            quantity_scale=6,
            quantity_step=Decimal("0.000001"),
            lot_control_mode=lot_mode,
            expiry_control_mode=expiry_mode,
            lifecycle_status="ACTIVE",
            operational_hold="NONE",
            published_at=utc_now(),
        )
        db.add(variant)
        await db.flush()
        variants.append(variant)

    if not draft:
        return variants, None

    product = Product(
        company_id=company_id,
        code="P-DRAFT",
        name="Draft readiness guard",
    )
    db.add(product)
    await db.flush()
    draft_variant = ProductVariant(
        company_id=company_id,
        product_id=product.id,
        name="Draft readiness guard",
        sku="SKU-DRAFT",
        base_uom_id=uom_id,
        quantity_scale=6,
        quantity_step=Decimal("0.000001"),
        lot_control_mode="OPTIONAL",
        expiry_control_mode="OPTIONAL",
        lifecycle_status="DRAFT",
        operational_hold="NONE",
        published_at=None,
    )
    db.add(draft_variant)
    await db.flush()
    return variants, draft_variant


async def test_cp14a2_product_readiness_journey():
    runtime_url, admin_url = _checked_urls()
    runtime_engine = create_async_engine(runtime_url, poolclass=NullPool)
    admin_engine = create_async_engine(admin_url, poolclass=NullPool)

    try:
        # PostgreSQL 16 gate: runtime is restricted and tenant tables are FORCE RLS.
        async with runtime_engine.connect() as connection:
            identity = (
                await connection.execute(
                    text(
                        "SELECT current_database(), current_user, inet_server_port(), "
                        "current_setting('server_version_num')::int, r.rolsuper, r.rolbypassrls "
                        "FROM pg_roles r WHERE r.rolname=current_user"
                    )
                )
            ).one()
            assert identity[0] == "wanasah_cp14a2_test"
            assert identity[1] == "cp14a2_app"
            assert identity[2] == 55452
            assert 160000 <= int(identity[3]) < 170000
            assert tuple(identity[4:]) == (False, False)
            for table_name in (
                "products",
                "product_variants",
                "product_locations",
                "inventory_locations",
                "operation_idempotency",
                "user_location_access",
            ):
                flags = (
                    await connection.execute(
                        text(
                            "SELECT relrowsecurity, relforcerowsecurity "
                            "FROM pg_class WHERE oid=to_regclass(:table_name)"
                        ),
                        {"table_name": table_name},
                    )
                ).one()
                assert tuple(flags) == (True, True), table_name

        config = AlembicConfig(str(Path(__file__).parents[1] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
        expected_heads = set(ScriptDirectory.from_config(config).get_heads())
        async with AsyncSession(admin_engine, expire_on_commit=False) as db:
            actual_heads = set(
                (await db.execute(text("SELECT version_num FROM alembic_version"))).scalars()
            )
            assert actual_heads == expected_heads

        # Fixtures only. ProductLocation A assignments are created through canonical API.
        async with AsyncSession(admin_engine, expire_on_commit=False) as seed:
            uom = await seed.scalar(select(UOM).where(UOM.code == "EACH"))
            if uom is None:
                uom = UOM(code="EACH", name="Each")
                seed.add(uom)
                await seed.flush()

            company_a = Company(
                name="CP14-A2 Company A",
                company_code="CP14A2-A-" + uuid4().hex,
                timezone="Asia/Amman",
            )
            company_b = Company(
                name="CP14-A2 Company B",
                company_code="CP14A2-B-" + uuid4().hex,
                timezone="Asia/Amman",
            )
            seed.add_all([company_a, company_b])
            await seed.flush()

            await seed.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(company_a.id)},
            )
            owner_a = await seed_company_owner_fixture(
                seed, company_a.id, password="Cp14A2OwnerSynthetic123"
            )
            operator = await seed_ordinary_backoffice_fixture(seed, company_a.id)
            denied = await seed_ordinary_backoffice_fixture(seed, company_a.id)
            warehouse_a1 = InventoryLocation(
                company_id=company_a.id,
                name="Shared Warehouse",
                code="CP14A2-WH1",
                location_type="WAREHOUSE",
                is_active=True,
                is_system_managed=False,
                version=1,
            )
            warehouse_a2 = InventoryLocation(
                company_id=company_a.id,
                name="Warehouse A2",
                code="CP14A2-WH2",
                location_type="WAREHOUSE",
                is_active=True,
                is_system_managed=False,
                version=1,
            )
            seed.add_all([warehouse_a1, warehouse_a2])
            await seed.flush()
            variants_a, draft_a = await _seed_variants(
                seed, company_id=company_a.id, uom_id=uom.id, draft=True
            )
            await _grant_a1_scope(
                seed,
                company_id=company_a.id,
                driver_id=operator.driver_id,
                location_id=warehouse_a1.id,
            )

            await seed.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(company_b.id)},
            )
            owner_b = await seed_company_owner_fixture(
                seed, company_b.id, password="Cp14A2OwnerBSynthetic123"
            )
            warehouse_b1 = InventoryLocation(
                company_id=company_b.id,
                name="Shared Warehouse",
                code="CP14A2-WH1",
                location_type="WAREHOUSE",
                is_active=True,
                is_system_managed=False,
                version=1,
            )
            seed.add(warehouse_b1)
            await seed.flush()
            variants_b, _ = await _seed_variants(
                seed, company_id=company_b.id, uom_id=uom.id, draft=False
            )
            seed.add_all(
                [
                    ProductLocation(
                        company_id=company_b.id,
                        location_id=warehouse_b1.id,
                        product_variant_id=variant.id,
                        created_by=owner_b.driver_id,
                        operational_flags=dict(DEFAULT_PRODUCT_LOCATION_FLAGS),
                    )
                    for variant in variants_b
                ]
            )
            await seed.flush()

            ids = NS(
                company_a=company_a.id,
                company_b=company_b.id,
                a1=warehouse_a1.id,
                a2=warehouse_a2.id,
                b1=warehouse_b1.id,
                p1=variants_a[0].id,
                p2=variants_a[1].id,
                p3=variants_a[2].id,
                draft=draft_a.id,
                b_p1=variants_b[0].id,
                b_p2=variants_b[1].id,
                b_p3=variants_b[2].id,
            )
            await seed.commit()

        # Successful journey uses an authorized NON-OWNER. Driver row is provenance only.
        assert owner_a.context.is_company_owner is True
        assert operator.context.is_company_owner is False
        assert denied.context.is_company_owner is False
        assert len(
            {
                operator.context.principal_id,
                operator.context.backoffice_user_id,
                operator.driver_id,
            }
        ) == 3
        actor = NS(id=operator.driver_id)
        denied_actor = NS(id=denied.driver_id)
        assert not hasattr(actor, "company_id")
        assert not hasattr(actor, "is_admin")
        for code in SCOPED_CAPABILITIES:
            assert code in PERMISSIONS
            assert code not in COMPANY_ONLY

        # A1-scoped canonical authority includes ProductLocation, inventory and location reads.
        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            assert access.company_id == ids.company_a
            for code in SCOPED_CAPABILITIES:
                await access.require(code, ids.a1)
            for code in ("product_location.read", "product_location.manage", "inventory.read", "location.read"):
                with pytest.raises(BackofficeCapabilityAccessRejected):
                    await access.require(code, ids.a2)

        # 1) Assign P1/P2/P3 to A1 through canonical ProductLocation API.
        assignment_ids: dict[int, int] = {}
        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            for variant_id in (ids.p1, ids.p2, ids.p3):
                response = await product_locations.create_product_location(
                    product_locations.ProductLocationCreate(
                        request_id=uuid4(),
                        location_id=ids.a1,
                        product_variant_id=variant_id,
                        operational_flags=dict(DEFAULT_PRODUCT_LOCATION_FLAGS),
                    ),
                    db,
                    access,
                    actor,
                )
                item = response["product_location"]
                assert item["location"]["id"] == ids.a1
                assert item["product_variant"]["id"] == variant_id
                assert item["operational_flags"] == {
                    "inbound_enabled": True,
                    "outbound_enabled": True,
                }
                assignment_ids[variant_id] = int(item["id"])

        # Read path is pre-filtered to A1. A2 has no inherited assignment.
        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            page = await product_locations.list_product_locations(
                location_id=ids.a1,
                product_variant_id=None,
                cursor=None,
                limit=50,
                db=db,
                access=access,
            )
            assert {row["product_variant"]["id"] for row in page["items"]} == {
                ids.p1,
                ids.p2,
                ids.p3,
            }
            assert "total" not in page

            with pytest.raises(HTTPException) as a2_read:
                await product_locations.list_product_locations(
                    location_id=ids.a2,
                    product_variant_id=None,
                    cursor=None,
                    limit=50,
                    db=db,
                    access=access,
                )
            assert a2_read.value.status_code == 403

            unscoped = await product_locations.list_product_locations(
                location_id=None,
                product_variant_id=None,
                cursor=None,
                limit=50,
                db=db,
                access=access,
            )
            assert {row["location"]["id"] for row in unscoped["items"]} == {ids.a1}
            foreign_filter = await product_locations.list_product_locations(
                location_id=ids.a1,
                product_variant_id=ids.b_p1,
                cursor=None,
                limit=50,
                db=db,
                access=access,
            )
            assert foreign_filter["items"] == []

            # FORCE RLS hides foreign products/locations/assignments even without tenant predicates.
            assert await db.get(ProductVariant, ids.b_p1) is None
            assert await db.get(InventoryLocation, ids.b1) is None
            assert int(await db.scalar(select(func.count()).select_from(ProductLocation))) == 3
            assert int(await db.scalar(select(func.count()).select_from(ProductVariant))) == 4

        # Company-A cannot assign a Company-B product to A1; rollback leaves no partial row/idempotency.
        async with _runtime_session(runtime_engine, ids.company_a) as db:
            before_idem = int(
                await db.scalar(
                    select(func.count()).select_from(OperationIdempotency).where(
                        OperationIdempotency.company_id == ids.company_a
                    )
                )
            )
        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            with pytest.raises(HTTPException) as foreign_product:
                await product_locations.create_product_location(
                    product_locations.ProductLocationCreate(
                        request_id=uuid4(),
                        location_id=ids.a1,
                        product_variant_id=ids.b_p1,
                    ),
                    db,
                    access,
                    actor,
                )
            assert foreign_product.value.status_code == 404
            assert foreign_product.value.detail["code"] == "VARIANT_NOT_FOUND"
            _assert_opaque(foreign_product.value, ids.b_p1)
        async with _runtime_session(runtime_engine, ids.company_a) as db:
            assert int(await db.scalar(select(func.count()).select_from(ProductLocation))) == 3
            assert int(
                await db.scalar(
                    select(func.count()).select_from(OperationIdempotency).where(
                        OperationIdempotency.company_id == ids.company_a
                    )
                )
            ) == before_idem

        # Company-A cannot use B1, and A1-scoped authority cannot mutate A2.
        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            with pytest.raises(HTTPException) as foreign_location:
                await product_locations.create_product_location(
                    product_locations.ProductLocationCreate(
                        request_id=uuid4(),
                        location_id=ids.b1,
                        product_variant_id=ids.p1,
                    ),
                    db,
                    access,
                    actor,
                )
            assert foreign_location.value.status_code == 404
            _assert_opaque(foreign_location.value, ids.b1)

            with pytest.raises(HTTPException) as a2_mutation:
                await product_locations.create_product_location(
                    product_locations.ProductLocationCreate(
                        request_id=uuid4(),
                        location_id=ids.a2,
                        product_variant_id=ids.p1,
                    ),
                    db,
                    access,
                    actor,
                )
            assert a2_mutation.value.status_code == 403

        # Denied ordinary actor cannot read or manage A1 ProductLocation rows.
        async with _runtime_session(runtime_engine, ids.company_a) as db:
            denied_access = denied.access(db)
            with pytest.raises(HTTPException) as denied_read:
                await product_locations.list_product_locations(
                    location_id=ids.a1,
                    product_variant_id=None,
                    cursor=None,
                    limit=50,
                    db=db,
                    access=denied_access,
                )
            assert denied_read.value.status_code == 403
            with pytest.raises(HTTPException) as denied_manage:
                await product_locations.create_product_location(
                    product_locations.ProductLocationCreate(
                        request_id=uuid4(),
                        location_id=ids.a1,
                        product_variant_id=ids.draft,
                    ),
                    db,
                    denied_access,
                    denied_actor,
                )
            assert denied_manage.value.status_code == 403

        # Product lifecycle guard: a DRAFT variant cannot receive a new assignment.
        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            with pytest.raises(HTTPException) as lifecycle:
                await product_locations.create_product_location(
                    product_locations.ProductLocationCreate(
                        request_id=uuid4(),
                        location_id=ids.a1,
                        product_variant_id=ids.draft,
                    ),
                    db,
                    access,
                    actor,
                )
            assert lifecycle.value.status_code == 409
            assert lifecycle.value.detail["code"] == "PRODUCT_LOCATION_VARIANT_NOT_ACTIVE"
        async with _runtime_session(runtime_engine, ids.company_a) as db:
            assert await db.scalar(
                select(ProductLocation.id).where(
                    ProductLocation.company_id == ids.company_a,
                    ProductLocation.location_id == ids.a1,
                    ProductLocation.product_variant_id == ids.draft,
                )
            ) is None

        # Operational flags are persisted exactly and the canonical helper used by
        # Inbound/outbound paths respects them without translation.
        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            p2_update = await product_locations.update_product_location(
                assignment_ids[ids.p2],
                product_locations.ProductLocationUpdate(
                    request_id=uuid4(),
                    expected_version=1,
                    operational_flags={
                        "inbound_enabled": False,
                        "outbound_enabled": True,
                    },
                ),
                db,
                access,
                actor,
            )
            p3_update = await product_locations.update_product_location(
                assignment_ids[ids.p3],
                product_locations.ProductLocationUpdate(
                    request_id=uuid4(),
                    expected_version=1,
                    operational_flags={
                        "inbound_enabled": True,
                        "outbound_enabled": False,
                    },
                ),
                db,
                access,
                actor,
            )
            p2_flags = p2_update["product_location"]["operational_flags"]
            p3_flags = p3_update["product_location"]["operational_flags"]
            assert inbound.product_location_allows is product_location_allows
            assert product_location_allows(p2_flags, INBOUND_NEW) is False
            assert product_location_allows(p3_flags, INBOUND_NEW) is True
            for operation in (ROUTE_LOAD_NEW, WAREHOUSE_BALANCING, REPLENISHMENT_NEW):
                assert product_location_allows(p2_flags, operation) is True
                assert product_location_allows(p3_flags, operation) is False

        # Catalog -> ProductLocation join -> read-only Inbound options preserves exact
        # NONE / OPTIONAL / REQUIRED lot and expiry values. No receipt is posted.
        expected_modes = {
            ids.p1: ("NONE", "NONE"),
            ids.p2: ("OPTIONAL", "OPTIONAL"),
            ids.p3: ("REQUIRED", "REQUIRED"),
        }
        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            catalog_rows = (
                await db.execute(
                    select(
                        ProductVariant.id,
                        ProductVariant.lot_control_mode,
                        ProductVariant.expiry_control_mode,
                    ).where(ProductVariant.id.in_(expected_modes))
                )
            ).all()
            assert {
                int(row.id): (str(row.lot_control_mode), str(row.expiry_control_mode))
                for row in catalog_rows
            } == expected_modes

            joined_rows = (
                await db.execute(
                    select(
                        ProductLocation.product_variant_id,
                        ProductVariant.lot_control_mode,
                        ProductVariant.expiry_control_mode,
                    )
                    .join(
                        ProductVariant,
                        (ProductVariant.company_id == ProductLocation.company_id)
                        & (ProductVariant.id == ProductLocation.product_variant_id),
                    )
                    .where(ProductLocation.location_id == ids.a1)
                )
            ).all()
            assert {
                int(row.product_variant_id): (
                    str(row.lot_control_mode),
                    str(row.expiry_control_mode),
                )
                for row in joined_rows
            } == expected_modes

            options = await inbound.warehouse_inbound_options(
                InboundOptionsRequest(ids=[ids.p1, ids.p2, ids.p3]),
                db,
                access,
            )
            assert {
                int(row["product_variant_id"]): (
                    row["lot_control_mode"],
                    row["expiry_control_mode"],
                )
                for row in options["items"]
            } == expected_modes

            # Product readiness must not manufacture inventory or a receipt.
            assert int(await db.scalar(select(func.count()).select_from(ProductBatch))) == 0
            assert int(await db.scalar(select(func.count()).select_from(InventoryMovement))) == 0
            assert int(await db.scalar(select(func.count()).select_from(InventoryBalance))) == 0

        # Foreign tenant truth remains untouched despite overlapping product/SKU/location values.
        async with AsyncSession(admin_engine, expire_on_commit=False) as verify:
            foreign_variants = (
                await verify.execute(
                    select(ProductVariant).where(
                        ProductVariant.id.in_([ids.b_p1, ids.b_p2, ids.b_p3])
                    )
                )
            ).scalars().all()
            assert {(row.sku, row.lot_control_mode, row.expiry_control_mode) for row in foreign_variants} == {
                ("SKU-P1", "NONE", "NONE"),
                ("SKU-P2", "OPTIONAL", "OPTIONAL"),
                ("SKU-P3", "REQUIRED", "REQUIRED"),
            }
            assert int(
                await verify.scalar(
                    select(func.count()).select_from(ProductLocation).where(
                        ProductLocation.company_id == ids.company_b,
                        ProductLocation.location_id == ids.b1,
                    )
                )
            ) == 3
    finally:
        await runtime_engine.dispose()
        await admin_engine.dispose()
