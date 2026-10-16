"""Real PostgreSQL 16 acceptance for CP11 Inventory access / Backoffice seam."""
from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api import inventory_permissions
from context import tenant_context
from domains.authorization.capabilities import COMPANY_ONLY, PERMISSIONS
from models import (
    Company,
    InventoryLocation,
    Permission,
    Role,
    SystemAuditLog,
    UserLocationAccess,
    UserRole,
    Vehicle,
    role_permissions,
)
from tests.canonical_actor_fixtures import seed_company_owner_fixture, seed_ordinary_backoffice_fixture


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CP11_PG_GATE") != "1",
        reason="Explicit disposable CP11 PostgreSQL gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


def _checked_urls():
    names = ("WANASAH_CP11_PG_URL", "WANASAH_CP11_PG_ADMIN_URL")
    urls = [make_url(os.environ[name]) for name in names]
    for url in urls:
        if (
            url.drivername != "postgresql+asyncpg"
            or url.host != "127.0.0.1"
            or url.port != 55451
            or url.database != "wanasah_cp11_test"
        ):
            raise RuntimeError("Refusing any database outside the disposable CP11 PostgreSQL gate")
    if urls[0].username != "cp11_app" or urls[1].username == urls[0].username:
        raise RuntimeError("CP11 requires distinct restricted runtime and migration roles")
    return urls


class Gate:
    def __init__(self, runtime_engine, admin_engine):
        self.runtime_engine = runtime_engine
        self.admin_engine = admin_engine
        self.a = None
        self.b = None

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
            assert tuple(identity) == ("wanasah_cp11_test", "cp11_app", 55451, False, False)

        config = AlembicConfig(str(Path(__file__).parents[1] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
        expected_heads = set(ScriptDirectory.from_config(config).get_heads())

        async with AsyncSession(admin_engine, expire_on_commit=False) as seed:
            assert set((await seed.execute(text("SELECT version_num FROM alembic_version"))).scalars()) == expected_heads
            persisted_codes = set((await seed.scalars(select(Permission.code))).all())
            missing = set(PERMISSIONS) - persisted_codes
            assert not missing, f"Clean bootstrap is missing canonical permissions: {sorted(missing)}"

            companies = [
                Company(name="CP11 Company A", company_code="CP11A-" + uuid4().hex, timezone="Asia/Amman", currency_code="JOD"),
                Company(name="CP11 Company B", company_code="CP11B-" + uuid4().hex, timezone="Asia/Amman", currency_code="JOD"),
            ]
            seed.add_all(companies)
            await seed.flush()

            tenants = []
            for index, company in enumerate(companies):
                await seed.execute(
                    text("SELECT set_config('app.current_tenant',:tenant,true)"),
                    {"tenant": str(company.id)},
                )
                owner = await seed_company_owner_fixture(seed, company.id, password="CP11FixturePassword123")
                ordinary = await seed_ordinary_backoffice_fixture(seed, company.id)
                vehicle = Vehicle(
                    company_id=company.id,
                    plate_number=f"CP11-{index}-{uuid4().hex[:10]}",
                )
                seed.add(vehicle)
                await seed.flush()
                locations = [
                    InventoryLocation(
                        company_id=company.id,
                        code=f"CP11-WH-{index}-{slot}-{uuid4().hex[:6]}",
                        name="Shared Warehouse",
                        location_type="WAREHOUSE",
                        is_active=True,
                    )
                    for slot in range(2 if index == 0 else 1)
                ]
                locations.append(InventoryLocation(
                    company_id=company.id,
                    code=f"CP11-VEH-{index}-{uuid4().hex[:6]}",
                    name="Shared Vehicle",
                    location_type="VEHICLE",
                    vehicle_id=vehicle.id,
                    is_active=True,
                ))
                seed.add_all(locations)
                await seed.flush()
                tenants.append(NS(
                    company_id=company.id,
                    owner=owner,
                    ordinary=ordinary,
                    warehouses=[row.id for row in locations if row.location_type == "WAREHOUSE"],
                    vehicle=next(row.id for row in locations if row.location_type == "VEHICLE"),
                ))
            gate.a, gate.b = tenants
            await seed.commit()

        yield gate
    finally:
        await runtime_engine.dispose()
        await admin_engine.dispose()


async def _create_role(db, tenant, name, codes):
    return await inventory_permissions.save_role(
        inventory_permissions.RoleInput(name=name, permissions=list(codes)),
        db,
        tenant.owner.access(db),
        tenant.owner.operational_driver,
    )


async def _grant(db, tenant, role_id, location_id):
    return await inventory_permissions.grant(
        user_id=tenant.ordinary.context.backoffice_user_id,
        payload=inventory_permissions.GrantInput(role_id=role_id, location_id=location_id),
        db=db,
        access=tenant.owner.access(db),
        legacy_actor=tenant.owner.operational_driver,
    )


@pytest.mark.asyncio
async def test_cp11_owner_admin_is_tenant_scoped_and_foreign_targets_are_opaque(pg):
    async with pg.session(pg.a) as db:
        a_role = await _create_role(db, pg.a, "Shared role", ["inventory.read"])
        roles = await inventory_permissions.roles(0, 100, db, pg.a.owner.access(db))
        users = await inventory_permissions.users(0, 100, db, pg.a.owner.access(db))
        locations = await inventory_permissions.locations(0, 100, db, pg.a.owner.access(db))
        assert a_role["id"] in {row["id"] for row in roles["items"]}
        assert pg.b.ordinary.context.backoffice_user_id not in {
            row["backoffice_user_id"] for row in users["items"]
        }
        visible_locations = {row["id"] for row in locations["items"]}
        assert set(pg.a.warehouses + [pg.a.vehicle]) <= visible_locations
        assert not visible_locations.intersection(set(pg.b.warehouses + [pg.b.vehicle]))
        with pytest.raises(HTTPException) as foreign:
            await inventory_permissions.user_grants(
                pg.b.ordinary.context.backoffice_user_id,
                "location",
                0,
                100,
                db,
                pg.a.owner.access(db),
            )
        assert foreign.value.status_code == 404

        assert pg.a.ordinary.context.principal_id != pg.a.ordinary.context.backoffice_user_id
        assert pg.a.ordinary.context.principal_id != pg.a.ordinary.driver_id
        assert pg.a.ordinary.context.backoffice_user_id != pg.a.ordinary.driver_id
        with pytest.raises(HTTPException) as denied:
            await inventory_permissions._require_company_owner(pg.a.ordinary.access(db))
        assert denied.value.status_code == 403

    async with pg.session(pg.b) as db:
        b_role = await _create_role(db, pg.b, "Shared role", ["inventory.read"])
        roles = await inventory_permissions.roles(0, 100, db, pg.b.owner.access(db))
        assert b_role["id"] in {row["id"] for row in roles["items"]}
        assert a_role["id"] not in {row["id"] for row in roles["items"]}


@pytest.mark.asyncio
async def test_cp11_company_warehouse_and_vehicle_scopes_remain_exact(pg):
    async with pg.session(pg.a) as db:
        warehouse_role = await _create_role(db, pg.a, "Warehouse reader", ["inventory.read"])
        vehicle_role = await _create_role(db, pg.a, "Vehicle ledger", ["ledger.read"])
        company_role = await _create_role(db, pg.a, "Company supplier", ["supplier.read"])
        a1, a2 = pg.a.warehouses
        va = pg.a.vehicle

        # COMPANY_ONLY capabilities do not become effective from a location grant.
        await _grant(db, pg.a, company_role["id"], a1)
        before_company = await inventory_permissions.capabilities(a1, db, pg.a.ordinary.access(db))
        assert "supplier.read" not in before_company["location_permissions"]

        await _grant(db, pg.a, warehouse_role["id"], a1)
        await _grant(db, pg.a, vehicle_role["id"], va)
        await _grant(db, pg.a, company_role["id"], None)

        a1_caps = await inventory_permissions.capabilities(a1, db, pg.a.ordinary.access(db))
        a2_caps = await inventory_permissions.capabilities(a2, db, pg.a.ordinary.access(db))
        va_caps = await inventory_permissions.capabilities(va, db, pg.a.ordinary.access(db))
        assert "inventory.read" in a1_caps["location_permissions"]
        assert "ledger.read" not in a1_caps["location_permissions"]
        assert "inventory.read" not in a2_caps["location_permissions"]
        assert "ledger.read" not in a2_caps["location_permissions"]
        assert "ledger.read" in va_caps["location_permissions"]
        assert "inventory.read" not in va_caps["location_permissions"]
        for payload in (a1_caps, a2_caps, va_caps):
            assert "supplier.read" in payload["permissions"]
            assert "supplier.read" in payload["location_permissions"]

        batch = await inventory_permissions.location_capabilities(
            inventory_permissions.LocationCapabilitiesInput(
                location_ids=[a1, a2, va, pg.b.warehouses[0], pg.b.vehicle]
            ),
            pg.a.ordinary.access(db),
        )
        assert set(map(int, batch["locations"].keys())) == {a1, a2, va}
        assert "inventory.read" in batch["locations"][a1]
        assert "inventory.read" not in batch["locations"][a2]
        assert "ledger.read" in batch["locations"][va]

        with pytest.raises(HTTPException) as foreign_location:
            await inventory_permissions.capabilities(
                pg.b.warehouses[0], db, pg.a.ordinary.access(db)
            )
        assert foreign_location.value.status_code == 403


@pytest.mark.asyncio
async def test_cp11_grants_are_idempotent_persistent_and_revocation_is_current_authority(pg):
    async with pg.session(pg.a) as db:
        role = await _create_role(db, pg.a, "A1 runtime", ["inventory.read"])
        a1 = pg.a.warehouses[0]
        first = await _grant(db, pg.a, role["id"], a1)
        second = await _grant(db, pg.a, role["id"], a1)
        assert first == {"created": True}
        assert second == {"created": False}

        persisted = await db.scalar(select(func.count()).select_from(UserLocationAccess).where(
            UserLocationAccess.company_id == pg.a.company_id,
            UserLocationAccess.driver_id == pg.a.ordinary.driver_id,
            UserLocationAccess.role_id == role["id"],
            UserLocationAccess.location_id == a1,
        ))
        assert persisted == 1

        ordinary_access = pg.a.ordinary.access(db)
        assert "inventory.read" in await ordinary_access.codes(a1)
        grants = await inventory_permissions.user_grants(
            pg.a.ordinary.context.backoffice_user_id,
            "location",
            0,
            100,
            db,
            pg.a.owner.access(db),
        )
        grant_id = next(row["id"] for row in grants["items"] if row["role_id"] == role["id"])
        assert await inventory_permissions.revoke(
            pg.a.ordinary.context.backoffice_user_id,
            grant_id,
            "location",
            db,
            pg.a.owner.access(db),
            pg.a.owner.operational_driver,
        ) == {"revoked": True}
        # Reusing a previously constructed access object must query current grants.
        assert "inventory.read" not in await ordinary_access.codes(a1)
        refreshed = await inventory_permissions.user_grants(
            pg.a.ordinary.context.backoffice_user_id,
            "location",
            0,
            100,
            db,
            pg.a.owner.access(db),
        )
        assert all(row["id"] != grant_id for row in refreshed["items"])

        audit_rows = (await db.scalars(select(SystemAuditLog).where(
            SystemAuditLog.company_id == pg.a.company_id,
            SystemAuditLog.admin_id == pg.a.owner.driver_id,
            SystemAuditLog.action_type.in_(["INVENTORY_GRANT_ADDED", "INVENTORY_GRANT_REVOKED"]),
        ))).all()
        assert {row.action_type for row in audit_rows} == {
            "INVENTORY_GRANT_ADDED",
            "INVENTORY_GRANT_REVOKED",
        }


@pytest.mark.asyncio
async def test_cp11_failed_mutations_leave_no_partial_grants(pg):
    async with pg.session(pg.a) as db:
        role = await _create_role(db, pg.a, "Atomic grant", ["inventory.read"])
        before = await db.scalar(select(func.count()).select_from(UserLocationAccess).where(
            UserLocationAccess.company_id == pg.a.company_id,
            UserLocationAccess.driver_id == pg.a.ordinary.driver_id,
        ))
        with pytest.raises(HTTPException) as foreign_location:
            await _grant(db, pg.a, role["id"], pg.b.warehouses[0])
        assert foreign_location.value.status_code == 404
        with pytest.raises(HTTPException) as foreign_target:
            await inventory_permissions.grant(
                pg.b.ordinary.context.backoffice_user_id,
                inventory_permissions.GrantInput(role_id=role["id"], location_id=pg.a.warehouses[0]),
                db,
                pg.a.owner.access(db),
                pg.a.owner.operational_driver,
            )
        assert foreign_target.value.status_code == 404
        with pytest.raises(HTTPException) as unknown_role:
            await _grant(db, pg.a, 2_000_000_000, pg.a.warehouses[0])
        assert unknown_role.value.status_code == 404
        after = await db.scalar(select(func.count()).select_from(UserLocationAccess).where(
            UserLocationAccess.company_id == pg.a.company_id,
            UserLocationAccess.driver_id == pg.a.ordinary.driver_id,
        ))
        assert after == before

        role_count = await db.scalar(select(func.count()).select_from(Role).where(Role.company_id == pg.a.company_id))
        with pytest.raises(HTTPException) as invalid_code:
            await inventory_permissions.save_role(
                NS(name="Must not persist", permissions=["invented.permission"]),
                db,
                pg.a.owner.access(db),
                pg.a.owner.operational_driver,
            )
        assert invalid_code.value.status_code == 422
        assert await db.scalar(select(func.count()).select_from(Role).where(Role.company_id == pg.a.company_id)) == role_count


@pytest.mark.asyncio
async def test_cp11_catalog_and_role_storage_match_registry_including_ledger(pg):
    async with pg.session(pg.a) as db:
        catalog = await inventory_permissions.permission_catalog(db, pg.a.owner.access(db))
        assert catalog["permissions"] == sorted(PERMISSIONS)
        assert catalog["company_only"] == sorted(COMPANY_ONLY)
        role = await _create_role(db, pg.a, "Ledger operator", ["ledger.read", "ledger.adjust"])
        stored = set((await db.scalars(select(Permission.code).join(
            role_permissions,
            role_permissions.c.permission_id == Permission.id,
        ).where(
            role_permissions.c.company_id == pg.a.company_id,
            role_permissions.c.role_id == role["id"],
        ))).all())
        assert stored == {"ledger.read", "ledger.adjust"}

        company = await _grant(db, pg.a, role["id"], None)
        assert company == {"created": True}
        persisted = await db.scalar(select(func.count()).select_from(UserRole).where(
            UserRole.company_id == pg.a.company_id,
            UserRole.driver_id == pg.a.ordinary.driver_id,
            UserRole.role_id == role["id"],
        ))
        assert persisted == 1
