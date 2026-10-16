"""GitHub-hosted PostgreSQL 16 acceptance for CP4 Warehouse/Branch lifecycle closure."""
from __future__ import annotations

import os
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
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

from api import branches
from api.warehouse import locations
from models import Branch, Company, Driver, InventoryLocation
from schemas import (
    BranchCreateRequest,
    BranchStateRequest,
    BranchUpdateRequest,
    WarehouseLocationCreateRequest,
    WarehouseLocationStateRequest,
    WarehouseLocationUpdateRequest,
)

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CP4_PG_GATE") != "1",
        reason="Explicit disposable CP4 PostgreSQL gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


def _checked_url():
    url = make_url(os.environ["WANASAH_CP4_PG_URL"])
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host != "127.0.0.1"
        or url.port != 55444
        or url.database != "wanasah_cp4_test"
    ):
        raise RuntimeError("Refusing any database outside the disposable CP4 PostgreSQL gate")
    return url


def _code(exc: HTTPException) -> str | None:
    return exc.detail.get("code") if isinstance(exc.detail, dict) else None


def _access(company_id: int):
    return NS(company_id=company_id, require=AsyncMock(return_value=None))


def _actor(actor_id: int):
    return NS(id=actor_id)


@pytest_asyncio.fixture(loop_scope="function")
async def pg():
    engine = create_async_engine(_checked_url(), poolclass=NullPool)
    try:
        config = AlembicConfig(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
        config.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
        expected_heads = set(ScriptDirectory.from_config(config).get_heads())
        async with AsyncSession(engine, expire_on_commit=False) as seed:
            actual_heads = set((await seed.execute(text("SELECT version_num FROM alembic_version"))).scalars())
            assert actual_heads == expected_heads

            company_a = Company(name="CP4 tenant A", company_code="CP4A-" + uuid4().hex)
            company_b = Company(name="CP4 tenant B", company_code="CP4B-" + uuid4().hex)
            seed.add_all([company_a, company_b])
            await seed.flush()
            actor = Driver(
                company_id=company_a.id,
                username="cp4-" + uuid4().hex,
                password_hash="fixture",
                full_name="CP4 operator",
            )
            seed.add(actor)
            active_branch = Branch(
                company_id=company_a.id,
                name="Active branch",
                branch_code="ACTIVE-" + uuid4().hex[:8].upper(),
                is_active=True,
            )
            inactive_branch = Branch(
                company_id=company_a.id,
                name="Inactive branch",
                branch_code="INACTIVE-" + uuid4().hex[:8].upper(),
                is_active=False,
            )
            foreign_branch = Branch(
                company_id=company_b.id,
                name="Foreign branch",
                branch_code="FOREIGN-" + uuid4().hex[:8].upper(),
                is_active=True,
            )
            seed.add_all([active_branch, inactive_branch, foreign_branch])
            await seed.flush()
            linked = InventoryLocation(
                company_id=company_a.id,
                branch_id=active_branch.id,
                name="Linked warehouse",
                code="LINK-" + uuid4().hex[:8].upper(),
                location_type="WAREHOUSE",
                vehicle_id=None,
                system_role=None,
                is_system_managed=False,
                version=1,
                is_active=True,
            )
            seed.add(linked)
            await seed.commit()

        yield NS(
            engine=engine,
            company_a=company_a.id,
            company_b=company_b.id,
            actor_id=actor.id,
            active_branch=active_branch.id,
            inactive_branch=inactive_branch.id,
            foreign_branch=foreign_branch.id,
            linked=linked.id,
        )
    finally:
        await engine.dispose()


async def test_branch_idempotency_reactivation_and_non_cascade(pg):
    access = _access(pg.company_a)
    actor = _actor(pg.actor_id)
    async with AsyncSession(pg.engine, expire_on_commit=False) as db:
        create_id = uuid4()
        payload = BranchCreateRequest(request_id=create_id, name="Idempotent branch", code="IDEM-" + uuid4().hex[:8].upper())
        first = await branches.create_branch(payload, db, access, actor)
    async with AsyncSession(pg.engine, expire_on_commit=False) as db:
        replay = await branches.create_branch(payload, db, access, actor)
        assert replay == first
        assert await db.scalar(select(func.count(Branch.id)).where(Branch.company_id == pg.company_a, Branch.branch_code == payload.code)) == 1

        update_id = uuid4()
        update = BranchUpdateRequest(request_id=update_id, name="Idempotent branch renamed")
        updated = await branches.update_branch(first["branch"]["id"], update, db, access, actor)
    async with AsyncSession(pg.engine, expire_on_commit=False) as db:
        assert await branches.update_branch(first["branch"]["id"], update, db, access, actor) == updated

        deactivate_id = uuid4()
        state = BranchStateRequest(request_id=deactivate_id, reason="organizational closure")
        deactivated = await branches.deactivate_branch(pg.active_branch, state, db, access, actor)
        assert deactivated["branch"]["is_active"] is False
    async with AsyncSession(pg.engine, expire_on_commit=False) as db:
        replay_state = await branches.deactivate_branch(pg.active_branch, state, db, access, actor)
        assert replay_state == deactivated
        warehouse = await db.get(InventoryLocation, pg.linked)
        assert warehouse.is_active is True
        assert warehouse.branch_id == pg.active_branch

        activated = await branches.activate_branch(
            pg.active_branch,
            BranchStateRequest(request_id=uuid4(), reason="organizational reopen"),
            db,
            access,
            actor,
        )
        assert activated["branch"]["is_active"] is True
        warehouse = await db.get(InventoryLocation, pg.linked)
        assert warehouse.is_active is True
        assert warehouse.branch_id == pg.active_branch


async def test_warehouse_create_update_version_relations_and_inactive_branch_reactivation(pg):
    access = _access(pg.company_a)
    actor = _actor(pg.actor_id)
    capability = AsyncMock(return_value=None)
    guard = AsyncMock(return_value=None)
    rebuild = AsyncMock(return_value=None)
    remove = AsyncMock(return_value=None)

    with (
        patch.object(locations, "_require_location_capability", capability),
        patch.object(locations, "acquire_inventory_location_guard", guard),
        patch.object(locations, "rebuild_live_stock_warehouse", rebuild),
        patch.object(locations, "remove_live_stock_warehouse_projection", remove),
    ):
        async with AsyncSession(pg.engine, expire_on_commit=False) as db:
            create = await locations.create_warehouse_location(
                WarehouseLocationCreateRequest(
                    request_id=uuid4(),
                    name="CP4 created warehouse",
                    code="CP4-" + uuid4().hex[:8].upper(),
                    branch_id=pg.active_branch,
                ),
                db,
                access,
                actor,
            )
            location_id = create["location"]["id"]
            assert create["location"]["branch_id"] == pg.active_branch
            assert create["location"]["version"] == 1

        async with AsyncSession(pg.engine, expire_on_commit=False) as db:
            updated = await locations.update_warehouse_location(
                location_id,
                WarehouseLocationUpdateRequest(
                    request_id=uuid4(),
                    expected_version=1,
                    name="CP4 renamed warehouse",
                ),
                db,
                access,
                actor,
            )
            assert updated["location"]["version"] == 2
            assert updated["location"]["branch_id"] == pg.active_branch

        async with AsyncSession(pg.engine, expire_on_commit=False) as db:
            with pytest.raises(HTTPException) as stale:
                await locations.update_warehouse_location(
                    location_id,
                    WarehouseLocationUpdateRequest(
                        request_id=uuid4(),
                        expected_version=1,
                        name="must not overwrite",
                    ),
                    db,
                    access,
                    actor,
                )
            assert stale.value.status_code == 409
            assert _code(stale.value) == "LOCATION_VERSION_CONFLICT"
            context = stale.value.detail["context"]
            assert context == {"resource_id": location_id, "expected_version": 1, "current_version": 2}
            row = await db.get(InventoryLocation, location_id)
            assert row.name == "CP4 renamed warehouse"
            assert row.version == 2

        async with AsyncSession(pg.engine, expire_on_commit=False) as db:
            with pytest.raises(HTTPException) as inactive_create:
                await locations.create_warehouse_location(
                    WarehouseLocationCreateRequest(
                        request_id=uuid4(), name="blocked", code="BLOCK-" + uuid4().hex[:8].upper(), branch_id=pg.inactive_branch
                    ), db, access, actor,
                )
            assert _code(inactive_create.value) == "WAREHOUSE_BRANCH_INACTIVE"

        async with AsyncSession(pg.engine, expire_on_commit=False) as db:
            with pytest.raises(HTTPException) as inactive_update:
                await locations.update_warehouse_location(
                    location_id,
                    WarehouseLocationUpdateRequest(request_id=uuid4(), expected_version=2, branch_id=pg.inactive_branch),
                    db, access, actor,
                )
            assert _code(inactive_update.value) == "WAREHOUSE_BRANCH_INACTIVE"
            row = await db.get(InventoryLocation, location_id)
            assert row.branch_id == pg.active_branch and row.version == 2

        async with AsyncSession(pg.engine, expire_on_commit=False) as db:
            with pytest.raises(HTTPException) as foreign:
                await locations.update_warehouse_location(
                    location_id,
                    WarehouseLocationUpdateRequest(request_id=uuid4(), expected_version=2, branch_id=pg.foreign_branch),
                    db, access, actor,
                )
            assert foreign.value.status_code == 404
            assert _code(foreign.value) == "WAREHOUSE_BRANCH_NOT_FOUND"

        async with AsyncSession(pg.engine, expire_on_commit=False) as db:
            await branches.deactivate_branch(
                pg.active_branch,
                BranchStateRequest(request_id=uuid4(), reason="organizational only"),
                db,
                access,
                actor,
            )
            row = await db.get(InventoryLocation, location_id)
            assert row.is_active is True and row.branch_id == pg.active_branch and row.version == 2

        async with AsyncSession(pg.engine, expire_on_commit=False) as db:
            deactivated = await locations.deactivate_warehouse_location(
                location_id,
                WarehouseLocationStateRequest(request_id=uuid4(), expected_version=2, reason="warehouse maintenance"),
                db, access, actor,
            )
            assert deactivated["location"]["is_active"] is False
            assert deactivated["location"]["branch_id"] == pg.active_branch
            assert deactivated["location"]["branch_name"] == "Active branch"
            inactive_version = deactivated["location"]["version"]

        async with AsyncSession(pg.engine, expire_on_commit=False) as db:
            reactivated = await locations.activate_warehouse_location(
                location_id,
                WarehouseLocationStateRequest(request_id=uuid4(), expected_version=inactive_version, reason="ready"),
                db, access, actor,
            )
            assert reactivated["location"]["is_active"] is True
            assert reactivated["location"]["branch_id"] == pg.active_branch
            assert reactivated["location"]["branch_name"] == "Active branch"
            branch = await db.get(Branch, pg.active_branch)
            assert branch.is_active is False
