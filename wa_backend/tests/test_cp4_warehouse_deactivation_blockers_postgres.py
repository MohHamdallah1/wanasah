"""Real PostgreSQL coverage for practical CP4 warehouse deactivation blockers."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api.warehouse import locations
from models import (
    Branch,
    Company,
    DispatchRoute,
    Driver,
    InventoryLock,
    InventoryLocation,
    InventoryTransferHeader,
    StocktakeSession,
    TenantOperationalPolicy,
    Zone,
)
from schemas import WarehouseLocationStateRequest

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CP4_PG_GATE") != "1",
        reason="Explicit disposable CP4 PostgreSQL gate only",
    ),
    pytest.mark.asyncio,
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


def _utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _blocker(exc: HTTPException) -> tuple[str | None, dict]:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    context = detail.get("context") if isinstance(detail.get("context"), dict) else {}
    return detail.get("code"), context


async def _expect_blocker(db, *, access, actor, location_id, expected: str):
    with pytest.raises(HTTPException) as caught:
        await locations.deactivate_warehouse_location(
            location_id,
            WarehouseLocationStateRequest(
                request_id=uuid4(),
                expected_version=1,
                reason="CP4 blocker acceptance",
            ),
            db,
            access,
            actor,
        )
    assert caught.value.status_code == 409
    code, context = _blocker(caught.value)
    assert code == "LOCATION_DEACTIVATION_BLOCKED"
    assert context.get("blocker_type") == expected

    row = await db.get(InventoryLocation, location_id)
    assert row is not None
    assert row.is_active is True
    assert row.version == 1
    return context


async def test_practical_deactivation_blockers_are_real_and_rollback_cleanly():
    engine = create_async_engine(_checked_url(), poolclass=NullPool)
    capability = AsyncMock(return_value=None)
    guard = AsyncMock(return_value=None)
    remove_projection = AsyncMock(return_value=None)

    try:
        async with AsyncSession(engine, expire_on_commit=False) as seed:
            company = Company(
                name="CP4 blocker tenant",
                company_code="CP4B-" + uuid4().hex,
            )
            seed.add(company)
            await seed.flush()
            actor_row = Driver(
                company_id=company.id,
                username="cp4-blocker-" + uuid4().hex,
                password_hash="fixture",
                full_name="CP4 blocker operator",
            )
            branch = Branch(
                company_id=company.id,
                name="CP4 blocker branch",
                branch_code="B-" + uuid4().hex[:8].upper(),
                is_active=True,
            )
            zone = Zone(company_id=company.id, name="CP4 blocker zone")
            seed.add_all([actor_row, branch, zone])
            await seed.flush()
            source = InventoryLocation(
                company_id=company.id,
                branch_id=branch.id,
                name="CP4 blocker source",
                code="SRC-" + uuid4().hex[:8].upper(),
                location_type="WAREHOUSE",
                vehicle_id=None,
                system_role=None,
                is_system_managed=False,
                version=1,
                is_active=True,
            )
            destination = InventoryLocation(
                company_id=company.id,
                branch_id=branch.id,
                name="CP4 blocker destination",
                code="DST-" + uuid4().hex[:8].upper(),
                location_type="WAREHOUSE",
                vehicle_id=None,
                system_role=None,
                is_system_managed=False,
                version=1,
                is_active=True,
            )
            seed.add_all([source, destination])
            await seed.flush()
            ids = NS(
                company=company.id,
                actor=actor_row.id,
                source=source.id,
                destination=destination.id,
                zone=zone.id,
            )
            await seed.commit()

        access = NS(company_id=ids.company)
        actor = NS(id=ids.actor)

        with (
            patch.object(locations, "_require_location_capability", capability),
            patch.object(locations, "acquire_inventory_location_guard", guard),
            patch.object(
                locations,
                "remove_live_stock_warehouse_projection",
                remove_projection,
            ),
        ):
            # 1) Whole-location InventoryLock backed by a real DRAFT stocktake.
            async with AsyncSession(engine, expire_on_commit=False) as db:
                stocktake = StocktakeSession(
                    company_id=ids.company,
                    location_id=ids.source,
                    reference_number="ST-" + uuid4().hex[:10].upper(),
                    stocktake_type="FULL_COUNT",
                    status="DRAFT",
                    started_by=ids.actor,
                )
                db.add(stocktake)
                await db.flush()
                lock = InventoryLock(
                    company_id=ids.company,
                    stocktake_session_id=stocktake.id,
                    location_id=ids.source,
                    product_variant_id=None,
                    batch_id=None,
                    created_by=ids.actor,
                )
                db.add(lock)
                await db.commit()
                stocktake_id = stocktake.id
                lock_id = lock.id

            async with AsyncSession(engine, expire_on_commit=False) as db:
                context = await _expect_blocker(
                    db,
                    access=access,
                    actor=actor,
                    location_id=ids.source,
                    expected="INVENTORY_LOCK",
                )
                assert context.get("reference_id") == lock_id

            # Release the lock; the still-open stocktake becomes the next blocker.
            async with AsyncSession(engine, expire_on_commit=False) as db:
                lock = await db.get(InventoryLock, lock_id)
                lock.released_by = ids.actor
                lock.released_at = _utc_naive()
                lock.release_reason = "CP4 acceptance progression"
                await db.commit()

            async with AsyncSession(engine, expire_on_commit=False) as db:
                context = await _expect_blocker(
                    db,
                    access=access,
                    actor=actor,
                    location_id=ids.source,
                    expected="OPEN_STOCKTAKE",
                )
                assert context.get("reference_number") is not None

            # Close stocktake and seed an open transfer using only Warehouse-domain rows.
            async with AsyncSession(engine, expire_on_commit=False) as db:
                stocktake = await db.get(StocktakeSession, stocktake_id)
                stocktake.status = "CANCELLED"
                stocktake.cancelled_by = ids.actor
                stocktake.cancelled_at = _utc_naive()
                stocktake.cancellation_reason = "CP4 acceptance progression"
                transfer = InventoryTransferHeader(
                    company_id=ids.company,
                    reference_number="TR-" + uuid4().hex[:10].upper(),
                    source_location_id=ids.source,
                    destination_location_id=ids.destination,
                    transit_location_id=None,
                    workflow_type="DIRECT",
                    status="DRAFT",
                    transfer_purpose="REPLENISHMENT",
                    commercial_context={},
                    dispatched_by=ids.actor,
                )
                db.add(transfer)
                await db.commit()
                transfer_id = transfer.id
                transfer_reference = transfer.reference_number

            async with AsyncSession(engine, expire_on_commit=False) as db:
                context = await _expect_blocker(
                    db,
                    access=access,
                    actor=actor,
                    location_id=ids.source,
                    expected="OPEN_TRANSFER",
                )
                assert context.get("reference_number") == transfer_reference

            # Close transfer and seed the published transfer-destination policy blocker.
            async with AsyncSession(engine, expire_on_commit=False) as db:
                transfer = await db.get(InventoryTransferHeader, transfer_id)
                transfer.status = "CANCELLED"
                transfer.cancelled_by = ids.actor
                transfer.cancelled_at = _utc_naive()
                transfer.decision_reason = "CP4 acceptance progression"
                now = _utc_naive()
                policy = TenantOperationalPolicy(
                    company_id=ids.company,
                    policy_code=locations.TRANSFER_DESTINATION_POLICY_CODE,
                    schema_version=1,
                    revision=1,
                    validated_payload={
                        "quarantine_location_id": ids.source,
                        "disposal_location_id": None,
                        "vendor_return_staging_location_id": None,
                    },
                    status="PUBLISHED",
                    effective_from=now,
                    effective_to=None,
                    approved_by=ids.actor,
                    approved_at=now,
                    created_by=ids.actor,
                )
                db.add(policy)
                await db.commit()
                policy_id = policy.id

            async with AsyncSession(engine, expire_on_commit=False) as db:
                context = await _expect_blocker(
                    db,
                    access=access,
                    actor=actor,
                    location_id=ids.source,
                    expected="PUBLISHED_OPERATIONAL_POLICY",
                )
                assert context.get("policy_id") == policy_id
                assert context.get("policy_revision") == 1

            # Supersede policy and seed an open Dispatch route.
            async with AsyncSession(engine, expire_on_commit=False) as db:
                policy = await db.get(TenantOperationalPolicy, policy_id)
                policy.status = "SUPERSEDED"
                policy.effective_to = _utc_naive()
                route = DispatchRoute(
                    company_id=ids.company,
                    zone_id=ids.zone,
                    driver_id=None,
                    vehicle_id=None,
                    work_session_id=None,
                    source_location_id=ids.source,
                    status="waiting",
                )
                db.add(route)
                await db.commit()
                route_id = route.id

            async with AsyncSession(engine, expire_on_commit=False) as db:
                context = await _expect_blocker(
                    db,
                    access=access,
                    actor=actor,
                    location_id=ids.source,
                    expected="OPEN_DISPATCH_ROUTE",
                )
                assert context.get("reference_id") == route_id

            # After every practical blocker is cleared, the same Warehouse can deactivate.
            async with AsyncSession(engine, expire_on_commit=False) as db:
                route = await db.get(DispatchRoute, route_id)
                route.status = "closed"
                await db.commit()

            async with AsyncSession(engine, expire_on_commit=False) as db:
                result = await locations.deactivate_warehouse_location(
                    ids.source,
                    WarehouseLocationStateRequest(
                        request_id=uuid4(),
                        expected_version=1,
                        reason="all practical blockers cleared",
                    ),
                    db,
                    access,
                    actor,
                )
                assert result["location"]["is_active"] is False
                assert result["location"]["version"] == 2
    finally:
        await engine.dispose()
