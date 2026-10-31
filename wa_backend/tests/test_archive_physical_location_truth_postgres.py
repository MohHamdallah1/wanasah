from __future__ import annotations

from datetime import date
from decimal import Decimal
import os
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects import postgresql

from api.warehouse import stocktake
from domains.inventory_archive_navigation import inventory_archive_target_query
from domains.inventory_vehicle_load.service import mutate_vehicle_load
from domains.stocktake.contracts import StocktakeStartCommand
from domains.vehicles.contracts import CreateVehicleCommand
from domains.vehicles.management import create_vehicle
from models import (
    DispatchRoute,
    InventoryBalance,
    InventoryLocation,
    InventoryLock,
    Permission,
    Role,
    UserLocationAccess,
    WorkSession,
    Zone,
    role_permissions,
    utc_now,
)
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_ARCHIVE_PHYSICAL_PG_GATE") != "1",
        reason="Explicit disposable PostgreSQL 16 archive physical-location gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _grant_archive_reader(pg_gate, tenant, *, vehicle_location_id: int) -> None:
    codes = {
        "catalog.read",
        "inventory.read",
        "location.read",
        "stocktake.read",
    }
    async with AsyncSession(pg_gate.admin_engine, expire_on_commit=False) as db:
        await db.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": str(tenant.company_id)},
        )
        permissions = (
            await db.scalars(select(Permission).where(Permission.code.in_(sorted(codes))))
        ).all()
        assert {permission.code for permission in permissions} == codes

        role = Role(
            company_id=tenant.company_id,
            name="Archive physical-location reader " + uuid4().hex[:10],
        )
        db.add(role)
        await db.flush()

        for permission in permissions:
            await db.execute(
                role_permissions.insert().values(
                    company_id=tenant.company_id,
                    role_id=int(role.id),
                    permission_id=int(permission.id),
                )
            )

        # Deliberately authorize both the Route source Warehouse and the Vehicle.
        # The rejected implementation would therefore have enough permission to
        # manufacture the Warehouse identity; the corrected projection must not.
        for location_id in (tenant.location_id, vehicle_location_id):
            db.add(
                UserLocationAccess(
                    company_id=tenant.company_id,
                    driver_id=tenant.ordinary.driver_id,
                    location_id=int(location_id),
                    role_id=int(role.id),
                )
            )
        await db.commit()


async def test_archive_navigation_preserves_vehicle_location_under_real_pg16(pg):
    tenant = pg.tenants[0]

    # The shared gate itself proves the session uses PostgreSQL 16's restricted
    # runtime role with FORCE RLS. Re-assert the exact role properties here so
    # G6 cannot accidentally run under the migration/fixture administrator.
    async with pg.session() as db:
        identity = (
            await db.execute(
                text(
                    "SELECT current_user, r.rolsuper, r.rolbypassrls "
                    "FROM pg_roles r WHERE r.rolname=current_user"
                )
            )
        ).one()
        assert tuple(identity) == ("wanasah_app", False, False)

    # Canonical inbound only. No direct InventoryBalance writes.
    receipt = pg.request(
        lot="ARCHIVE-PHYS-" + uuid4().hex[:10],
        quantity="100",
        cost="2",
    )
    async with pg.session() as db:
        assert await pg.post(db, receipt) == {"message": "INBOUND_POSTED"}

    # Canonical Vehicle creation and canonical Warehouse -> Vehicle movement.
    async with pg.session() as db:
        vehicle = await create_vehicle(
            db,
            company_id=tenant.company_id,
            actor_id=int(tenant.owner.operational_driver.id),
            command=CreateVehicleCommand(
                request_id=str(uuid4()),
                plate_number="ARCH-" + uuid4().hex[:10],
                vehicle_type="Van",
                maintenance_status="Active",
            ),
        )
        vehicle_id = int(vehicle["id"])
        vehicle_location_id = int(
            await db.scalar(
                select(InventoryLocation.id).where(
                    InventoryLocation.company_id == tenant.company_id,
                    InventoryLocation.vehicle_id == vehicle_id,
                    InventoryLocation.location_type == "VEHICLE",
                    InventoryLocation.is_active.is_(True),
                )
            )
        )

    async with pg.session() as db:
        moved = await mutate_vehicle_load(
            db,
            access=tenant.owner.access(db),
            actor_id=tenant.owner.driver_id,
            vehicle_id=vehicle_id,
            warehouse_id=int(tenant.location_id),
            direction="ADD",
            request_id=uuid4(),
            items=[
                {
                    "product_variant_id": tenant.variant_id,
                    "quantity": Decimal("30"),
                }
            ],
        )
        assert moved["movement_count"] == 1

    # VEHICLE_RECON still legitimately needs historical WorkSession/Route
    # operational context. Seed only that context; it is deliberately sourced
    # from the Warehouse so any forbidden source-location substitution is visible.
    async with pg.session() as db:
        zone = Zone(
            company_id=tenant.company_id,
            name="Archive physical-location zone " + uuid4().hex[:8],
            is_active=True,
        )
        db.add(zone)
        await db.flush()

        ended = utc_now()
        work = WorkSession(
            company_id=tenant.company_id,
            driver_id=tenant.owner.driver_id,
            start_time=ended,
            end_time=ended,
            session_date=date.today(),
            is_authorized_to_sell=False,
            is_settled=False,
        )
        db.add(work)
        await db.flush()

        route = DispatchRoute(
            company_id=tenant.company_id,
            zone_id=int(zone.id),
            driver_id=tenant.owner.driver_id,
            vehicle_id=vehicle_id,
            work_session_id=int(work.id),
            source_location_id=int(tenant.location_id),
            dispatch_date=date.today(),
            status="closed",
        )
        db.add(route)
        await db.commit()
        work_session_id = int(work.id)

    # Canonical stocktake command creates the VEHICLE_RECON session and active
    # InventoryLock at the Vehicle location. No direct stocktake/lock inserts.
    async with pg.session() as db:
        started = await stocktake.start_unified_stocktake(
            StocktakeStartCommand(
                request_id=uuid4(),
                location_id=vehicle_location_id,
                stocktake_type="VEHICLE_RECON",
                related_work_session_id=work_session_id,
                notes="G6 archive physical-location acceptance",
            ),
            db=db,
            access=tenant.owner.access(db),
            legacy_actor=tenant.owner.operational_driver,
        )
        stocktake_session_id = int(started["session_id"])
        assert started["snapshot_lines"] >= 1

    async with pg.session() as db:
        balance_id = await db.scalar(
            select(InventoryBalance.id).where(
                InventoryBalance.company_id == tenant.company_id,
                InventoryBalance.location_id == vehicle_location_id,
                InventoryBalance.product_variant_id == tenant.variant_id,
                InventoryBalance.on_hand_quantity > 0,
            )
        )
        lock_id = await db.scalar(
            select(InventoryLock.id).where(
                InventoryLock.company_id == tenant.company_id,
                InventoryLock.stocktake_session_id == stocktake_session_id,
                InventoryLock.location_id == vehicle_location_id,
                InventoryLock.released_at.is_(None),
            )
        )
        assert balance_id is not None
        assert lock_id is not None

    await _grant_archive_reader(
        pg,
        tenant,
        vehicle_location_id=vehicle_location_id,
    )

    async with pg.session() as db:
        query = inventory_archive_target_query(
            tenant.ordinary.access(db),
            tenant.variant_id,
            {
                "INVENTORY_BALANCE": int(balance_id),
                "OPEN_STOCKTAKE": stocktake_session_id,
                "ACTIVE_INVENTORY_LOCK": int(lock_id),
            },
        )
        sql = str(
            query.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()
        assert "dispatch_routes" not in sql
        assert "source_location_id" not in sql

        rows = {
            row["code"]: dict(row)
            for row in (await db.execute(query)).mappings().all()
        }

    assert set(rows) == {
        "INVENTORY_BALANCE",
        "OPEN_STOCKTAKE",
        "ACTIVE_INVENTORY_LOCK",
    }
    for code in rows:
        assert int(rows[code]["location_id"]) == vehicle_location_id
        assert rows[code]["kind"] == "capability-gap"
        assert rows[code]["reason"] == "INVENTORY_SOURCE"

    # The operational Route remains Warehouse-sourced, proving archive identity
    # did not simply echo the Route source.
    assert int(tenant.location_id) != vehicle_location_id
