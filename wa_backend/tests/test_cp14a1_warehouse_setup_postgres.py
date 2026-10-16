"""CP14-A1 real PostgreSQL warehouse/branch setup journey.

This gate is intentionally bounded to Warehouse setup. It requires an already
Alembic-migrated disposable PostgreSQL 16 database and a distinct restricted
runtime role. No production/runtime code is patched by this acceptance.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
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

from api import branches
from api.warehouse import locations
from context import tenant_context
from domains.authorization.capabilities import COMPANY_ONLY, PERMISSIONS
from models import (
    Branch,
    Company,
    InventoryLocation,
    OperationIdempotency,
    Permission,
    Role,
    UserRole,
    role_permissions,
)
from schemas import (
    BranchCreateRequest,
    BranchStateRequest,
    BranchUpdateRequest,
    WarehouseLocationCreateRequest,
    WarehouseLocationStateRequest,
    WarehouseLocationUpdateRequest,
)
from tests.canonical_actor_fixtures import (
    seed_company_owner_fixture,
    seed_ordinary_backoffice_fixture,
)


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CP14A1_PG_GATE") != "1",
        reason="Explicit disposable CP14-A1 PostgreSQL gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]

CAPABILITIES = (
    "branch.read",
    "branch.create",
    "branch.update",
    "branch.state",
    "location.read",
    "location.create",
    "location.update",
    "location.state",
)


def _checked_urls():
    runtime = make_url(os.environ["WANASAH_CP14A1_PG_URL"])
    admin = make_url(os.environ["WANASAH_CP14A1_PG_ADMIN_URL"])
    for url in (runtime, admin):
        if (
            url.drivername != "postgresql+asyncpg"
            or url.host != "127.0.0.1"
            or url.port != 55451
            or url.database != "wanasah_cp14a1_test"
        ):
            raise RuntimeError("Refusing any database outside disposable CP14-A1 PostgreSQL")
    if runtime.username != "cp14a1_app" or admin.username == runtime.username:
        raise RuntimeError("CP14-A1 requires distinct restricted runtime and migration roles")
    return runtime, admin


def _assert_opaque(exc: HTTPException, *foreign_values: object) -> None:
    rendered = str(exc.detail)
    for value in foreign_values:
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


async def _grant_company_capabilities(db, *, company_id: int, driver_id: int) -> None:
    role = Role(company_id=company_id, name="CP14-A1 warehouse operator")
    db.add(role)
    await db.flush()
    for code in CAPABILITIES:
        permission = await db.scalar(select(Permission).where(Permission.code == code))
        assert permission is not None, f"Migrated permission missing: {code}"
        await db.execute(
            role_permissions.insert().values(
                company_id=company_id,
                role_id=role.id,
                permission_id=permission.id,
            )
        )
    db.add(UserRole(company_id=company_id, role_id=role.id, driver_id=driver_id))
    await db.flush()


async def _require_branch(access, dependency):
    return await dependency(access=access)


async def _company_idempotency_count(engine, company_id: int) -> int:
    async with _runtime_session(engine, company_id) as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(OperationIdempotency)
                .where(OperationIdempotency.company_id == company_id)
            )
        )


async def test_cp14a1_authorized_non_owner_warehouse_setup_journey():
    runtime_url, admin_url = _checked_urls()
    runtime_engine = create_async_engine(runtime_url, poolclass=NullPool)
    admin_engine = create_async_engine(admin_url, poolclass=NullPool)

    try:
        async with runtime_engine.connect() as connection:
            identity = (
                await connection.execute(
                    text(
                        "SELECT current_database(), current_user, inet_server_port(), "
                        "r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname=current_user"
                    )
                )
            ).one()
            assert tuple(identity) == (
                "wanasah_cp14a1_test",
                "cp14a1_app",
                55451,
                False,
                False,
            )
            for table_name in ("branches", "inventory_locations", "operation_idempotency"):
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

        async with AsyncSession(admin_engine, expire_on_commit=False) as seed:
            company_a = Company(
                name="CP14-A1 Company A",
                company_code="CP14A1-A-" + uuid4().hex,
                timezone="Asia/Amman",
            )
            company_b = Company(
                name="CP14-A1 Company B",
                company_code="CP14A1-B-" + uuid4().hex,
                timezone="Asia/Amman",
            )
            seed.add_all([company_a, company_b])
            await seed.flush()

            await seed.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(company_a.id)},
            )
            owner_a = await seed_company_owner_fixture(
                seed, company_a.id, password="Cp14A1OwnerSynthetic123"
            )
            operator = await seed_ordinary_backoffice_fixture(seed, company_a.id)
            denied = await seed_ordinary_backoffice_fixture(seed, company_a.id)
            await _grant_company_capabilities(
                seed, company_id=company_a.id, driver_id=operator.driver_id
            )

            await seed.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(company_b.id)},
            )
            branch_b = Branch(
                company_id=company_b.id,
                name="Shared Operations",
                branch_code="CP14A1-BR",
                is_active=True,
            )
            seed.add(branch_b)
            await seed.flush()
            warehouse_b1 = InventoryLocation(
                company_id=company_b.id,
                branch_id=branch_b.id,
                name="Shared Central Warehouse",
                code="CP14A1-WH1",
                location_type="WAREHOUSE",
                vehicle_id=None,
                system_role=None,
                is_system_managed=False,
                version=1,
                is_active=True,
            )
            seed.add(warehouse_b1)
            await seed.flush()

            ids = NS(
                company_a=company_a.id,
                company_b=company_b.id,
                branch_b=branch_b.id,
                warehouse_b1=warehouse_b1.id,
            )
            await seed.commit()

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
        for code in CAPABILITIES:
            assert code in PERMISSIONS
        for code in (
            "branch.read",
            "branch.create",
            "branch.update",
            "branch.state",
            "location.create",
        ):
            assert code in COMPANY_ONLY

        branch_create = BranchCreateRequest(
            request_id=uuid4(),
            name="Shared Operations",
            code="CP14A1-BR",
        )
        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            assert access.company_id == ids.company_a
            await _require_branch(access, branches._branch_create)
            created_branch = await branches.create_branch(branch_create, db, access, actor)
            branch_a = int(created_branch["branch"]["id"])
            assert created_branch["branch"]["name"] == "Shared Operations"
            assert created_branch["branch"]["code"] == "CP14A1-BR"
            assert created_branch["branch"]["is_active"] is True

            await _require_branch(access, branches._branch_create)
            assert await branches.create_branch(branch_create, db, access, actor) == created_branch
            assert int(
                await db.scalar(
                    select(func.count())
                    .select_from(Branch)
                    .where(Branch.branch_code == "CP14A1-BR")
                )
            ) == 1

            changed = branch_create.model_copy(update={"name": "Changed replay payload"})
            await _require_branch(access, branches._branch_create)
            with pytest.raises(HTTPException) as conflict:
                await branches.create_branch(changed, db, access, actor)
            assert conflict.value.status_code == 409

        async with _runtime_session(runtime_engine, ids.company_a) as db:
            row = await db.get(Branch, branch_a)
            assert row is not None and row.name == "Shared Operations"

        warehouse_a1_payload = WarehouseLocationCreateRequest(
            request_id=uuid4(),
            name="Shared Central Warehouse",
            code="CP14A1-WH1",
            branch_id=branch_a,
        )
        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            created_a1 = await locations.create_warehouse_location(
                warehouse_a1_payload, db, access, actor
            )
            warehouse_a1 = int(created_a1["location"]["id"])
            assert created_a1["location"]["branch_id"] == branch_a
            assert created_a1["location"]["version"] == 1

            assert (
                await locations.create_warehouse_location(
                    warehouse_a1_payload, db, access, actor
                )
                == created_a1
            )
            assert int(
                await db.scalar(
                    select(func.count())
                    .select_from(InventoryLocation)
                    .where(InventoryLocation.code == "CP14A1-WH1")
                )
            ) == 1

            changed = warehouse_a1_payload.model_copy(
                update={"name": "Changed warehouse replay payload"}
            )
            with pytest.raises(HTTPException) as conflict:
                await locations.create_warehouse_location(changed, db, access, actor)
            assert conflict.value.status_code == 409

        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            created_a2 = await locations.create_warehouse_location(
                WarehouseLocationCreateRequest(
                    request_id=uuid4(),
                    name="Warehouse A2",
                    code="CP14A1-WH2",
                    branch_id=None,
                ),
                db,
                access,
                actor,
            )
            warehouse_a2 = int(created_a2["location"]["id"])
            assert created_a2["location"]["branch_id"] is None

        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            await _require_branch(access, branches._branch_update)
            branch_update = await branches.update_branch(
                branch_a,
                BranchUpdateRequest(
                    request_id=uuid4(),
                    name="Shared Operations Edited",
                    code="CP14A1-BR-EDIT",
                ),
                db,
                access,
                actor,
            )
            assert branch_update["branch"]["name"] == "Shared Operations Edited"
            assert branch_update["branch"]["code"] == "CP14A1-BR-EDIT"

        warehouse_update = WarehouseLocationUpdateRequest(
            request_id=uuid4(),
            expected_version=1,
            name="Shared Central Warehouse Edited",
        )
        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            edited = await locations.update_warehouse_location(
                warehouse_a1, warehouse_update, db, access, actor
            )
            assert edited["location"]["name"] == "Shared Central Warehouse Edited"
            assert edited["location"]["version"] == 2
            assert (
                await locations.update_warehouse_location(
                    warehouse_a1, warehouse_update, db, access, actor
                )
                == edited
            )
            changed = warehouse_update.model_copy(
                update={"name": "Changed warehouse update replay"}
            )
            with pytest.raises(HTTPException) as conflict:
                await locations.update_warehouse_location(
                    warehouse_a1, changed, db, access, actor
                )
            assert conflict.value.status_code == 409

        async with _runtime_session(runtime_engine, ids.company_a) as db:
            row = await db.get(InventoryLocation, warehouse_a1)
            assert row is not None
            assert row.name == "Shared Central Warehouse Edited"
            assert row.version == 2

        async with _runtime_session(runtime_engine, ids.company_a) as db:
            denied_access = denied.access(db)
            branch_count = int(await db.scalar(select(func.count()).select_from(Branch)))
            warehouse_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(InventoryLocation)
                    .where(InventoryLocation.location_type == "WAREHOUSE")
                )
            )
            with pytest.raises(HTTPException) as denied_branch_create:
                await _require_branch(denied_access, branches._branch_create)
            assert denied_branch_create.value.status_code == 403
            with pytest.raises(HTTPException) as denied_branch_update:
                await _require_branch(denied_access, branches._branch_update)
            assert denied_branch_update.value.status_code == 403
            with pytest.raises(HTTPException) as denied_warehouse_create:
                await locations.create_warehouse_location(
                    WarehouseLocationCreateRequest(
                        request_id=uuid4(),
                        name="Denied warehouse",
                        code="DENIED-WH",
                        branch_id=branch_a,
                    ),
                    db,
                    denied_access,
                    denied_actor,
                )
            assert denied_warehouse_create.value.status_code == 403
            with pytest.raises(HTTPException) as denied_warehouse_update:
                await locations.update_warehouse_location(
                    warehouse_a1,
                    WarehouseLocationUpdateRequest(
                        request_id=uuid4(),
                        expected_version=2,
                        name="Denied edit",
                    ),
                    db,
                    denied_access,
                    denied_actor,
                )
            assert denied_warehouse_update.value.status_code == 403
            assert int(await db.scalar(select(func.count()).select_from(Branch))) == branch_count
            assert int(
                await db.scalar(
                    select(func.count())
                    .select_from(InventoryLocation)
                    .where(InventoryLocation.location_type == "WAREHOUSE")
                )
            ) == warehouse_count

        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            await _require_branch(access, branches._branch_read)
            branch_page = await branches.manage_branches(
                search=None,
                include_inactive=True,
                cursor=None,
                limit=50,
                db=db,
                access=access,
            )
            assert branch_page["total"] == 1
            assert [item["id"] for item in branch_page["items"]] == [branch_a]

            warehouse_page = await locations.manage_warehouse_locations(
                search=None,
                include_inactive=True,
                cursor=None,
                limit=50,
                db=db,
                access=access,
            )
            assert warehouse_page["total"] == 2
            assert {item["id"] for item in warehouse_page["items"]} == {
                warehouse_a1,
                warehouse_a2,
            }

            assert await db.get(Branch, ids.branch_b) is None
            assert await db.get(InventoryLocation, ids.warehouse_b1) is None
            assert int(await db.scalar(select(func.count()).select_from(Branch))) == 1
            assert int(
                await db.scalar(
                    select(func.count())
                    .select_from(InventoryLocation)
                    .where(InventoryLocation.location_type == "WAREHOUSE")
                )
            ) == 2

        idempotency_before = await _company_idempotency_count(runtime_engine, ids.company_a)
        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            await _require_branch(access, branches._branch_update)
            with pytest.raises(HTTPException) as foreign_branch:
                await branches.update_branch(
                    ids.branch_b,
                    BranchUpdateRequest(
                        request_id=uuid4(),
                        name="Foreign mutation",
                    ),
                    db,
                    access,
                    actor,
                )
            assert foreign_branch.value.status_code == 404
            _assert_opaque(foreign_branch.value, ids.branch_b, "Shared Operations")
        assert (
            await _company_idempotency_count(runtime_engine, ids.company_a)
            == idempotency_before
        )

        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            with pytest.raises(HTTPException) as foreign_warehouse:
                await locations.update_warehouse_location(
                    ids.warehouse_b1,
                    WarehouseLocationUpdateRequest(
                        request_id=uuid4(),
                        expected_version=1,
                        name="Foreign mutation",
                    ),
                    db,
                    access,
                    actor,
                )
            assert foreign_warehouse.value.status_code == 404
            _assert_opaque(
                foreign_warehouse.value,
                ids.warehouse_b1,
                "Shared Central Warehouse",
            )
        assert (
            await _company_idempotency_count(runtime_engine, ids.company_a)
            == idempotency_before
        )

        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            await _require_branch(access, branches._branch_state)
            state = await branches.deactivate_branch(
                branch_a,
                BranchStateRequest(
                    request_id=uuid4(),
                    reason="CP14-A1 lifecycle proof",
                ),
                db,
                access,
                actor,
            )
            assert state["branch"]["is_active"] is False

        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            a2_before = await db.get(InventoryLocation, warehouse_a2)
            assert a2_before is not None
            assert a2_before.branch_id is None and a2_before.version == 1
            with pytest.raises(HTTPException) as inactive_assignment:
                await locations.update_warehouse_location(
                    warehouse_a2,
                    WarehouseLocationUpdateRequest(
                        request_id=uuid4(),
                        expected_version=1,
                        branch_id=branch_a,
                    ),
                    db,
                    access,
                    actor,
                )
            assert inactive_assignment.value.status_code == 409
            assert inactive_assignment.value.detail["code"] == "WAREHOUSE_BRANCH_INACTIVE"

        async with _runtime_session(runtime_engine, ids.company_a) as db:
            a2_after = await db.get(InventoryLocation, warehouse_a2)
            assert a2_after is not None
            assert a2_after.branch_id is None and a2_after.version == 1

        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            with pytest.raises(HTTPException) as foreign_assignment:
                await locations.update_warehouse_location(
                    warehouse_a2,
                    WarehouseLocationUpdateRequest(
                        request_id=uuid4(),
                        expected_version=1,
                        branch_id=ids.branch_b,
                    ),
                    db,
                    access,
                    actor,
                )
            assert foreign_assignment.value.status_code == 404
            assert foreign_assignment.value.detail["code"] == "WAREHOUSE_BRANCH_NOT_FOUND"
            _assert_opaque(foreign_assignment.value, ids.branch_b)

        async with _runtime_session(runtime_engine, ids.company_a) as db:
            a2_after_foreign = await db.get(InventoryLocation, warehouse_a2)
            assert a2_after_foreign is not None
            assert a2_after_foreign.branch_id is None
            assert a2_after_foreign.version == 1

        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            preserved = await locations.update_warehouse_location(
                warehouse_a1,
                WarehouseLocationUpdateRequest(
                    request_id=uuid4(),
                    expected_version=2,
                    name="Existing inactive-branch relation preserved",
                ),
                db,
                access,
                actor,
            )
            assert preserved["location"]["branch_id"] == branch_a
            assert preserved["location"]["version"] == 3

        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            deactivated = await locations.deactivate_warehouse_location(
                warehouse_a1,
                WarehouseLocationStateRequest(
                    request_id=uuid4(),
                    expected_version=3,
                    reason="CP14-A1 reactivation contract proof",
                ),
                db,
                access,
                actor,
            )
            assert deactivated["location"]["is_active"] is False
            assert deactivated["location"]["version"] == 4

        async with _runtime_session(runtime_engine, ids.company_a) as db:
            access = operator.access(db)
            activated = await locations.activate_warehouse_location(
                warehouse_a1,
                WarehouseLocationStateRequest(
                    request_id=uuid4(),
                    expected_version=4,
                    reason="CP14-A1 reactivation contract proof",
                ),
                db,
                access,
                actor,
            )
            assert activated["location"]["is_active"] is True
            assert activated["location"]["branch_id"] == branch_a
            assert activated["location"]["version"] == 5

        async with _runtime_session(runtime_engine, ids.company_a) as db:
            branch_after_activation = await db.get(Branch, branch_a)
            assert branch_after_activation is not None
            assert branch_after_activation.is_active is False

        async with AsyncSession(admin_engine, expire_on_commit=False) as verify:
            await verify.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(ids.company_b)},
            )
            foreign_branch = await verify.get(Branch, ids.branch_b)
            foreign_warehouse = await verify.get(InventoryLocation, ids.warehouse_b1)
            assert foreign_branch is not None
            assert foreign_branch.name == "Shared Operations"
            assert foreign_branch.branch_code == "CP14A1-BR"
            assert foreign_branch.is_active is True
            assert foreign_warehouse is not None
            assert foreign_warehouse.name == "Shared Central Warehouse"
            assert foreign_warehouse.code == "CP14A1-WH1"
            assert foreign_warehouse.branch_id == ids.branch_b
            assert foreign_warehouse.version == 1
            assert foreign_warehouse.is_active is True
    finally:
        await runtime_engine.dispose()
        await admin_engine.dispose()
