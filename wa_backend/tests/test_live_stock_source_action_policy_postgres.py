"""F2/F3: exact source-action advice must agree with canonical mutation rejection.

Tests require the disposable, migrated PostgreSQL fixture and a restricted RLS role;
they never connect to a user database. No skip/xfail overrides.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.warehouse import live_stock_source_detail, transfers
from domains.batch_actions import status_change_availability_for_batch
from models import (
    InventoryBalance,
    InventoryStockPolicy,
    Permission,
    ProductBatch,
    ProductVariant,
    UserLocationAccess,
    role_permissions,
)
from schemas import InventoryStatusChangeRequest
from services import get_company_local_date
from models import utc_now
from tests.test_cp3_batch_actions_postgres import _prepare
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401

pytestmark = pytest.mark.asyncio(loop_scope="function")


def _command(case, *, source="AVAILABLE", destination="QUARANTINED", quantity="2.500001"):
    return InventoryStatusChangeRequest(
        request_id=uuid4(),
        location_id=case.a.location_id,
        product_variant_id=case.a.variant_id,
        batch_id=case.a_batch_id,
        uom_id=case.a.uom_id,
        source_status=source,
        destination_status=destination,
        quantity=quantity,
        reason="F2/F3 authoritative mutation parity",
    )


async def _mutate(pg, case, *, source="AVAILABLE", destination="QUARANTINED", quantity="2.500001"):
    async with pg.session() as db:
        return await transfers.change_inventory_status(
            _command(case, source=source, destination=destination, quantity=quantity),
            db,
            case.a.ordinary.access(db),
            case.a.ordinary.operational_driver,
        )


async def _source(pg, case, *, identity=None):
    async with pg.session() as db:
        return await live_stock_source_detail.get_live_stock_batch_source(
            case.a.variant_id,
            case.a_batch_id,
            case.a.location_id,
            db,
            (identity or case.a.ordinary).access(db),
        )


def _action(source, from_status, to_status):
    status = next(
        item for item in source["statuses"] if item["stock_status"] == from_status
    )
    return next(
        action
        for action in status["status_change_actions"]
        if action["destination_status"] == to_status
    )


async def _set_variant(pg, case, **changes):
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(
            text("SELECT set_config('app.current_tenant', :company, true)"),
            {"company": str(case.a.company_id)},
        )
        updated = await seed.execute(
            update(ProductVariant)
            .where(
                ProductVariant.company_id == case.a.company_id,
                ProductVariant.id == case.a.variant_id,
            )
            .values(**changes)
        )
        assert updated.rowcount == 1
        await seed.commit()


@pytest.mark.parametrize("hold", ["SALES_HOLD", "RECALL"])
async def test_f2_hold_cannot_advertise_quarantine_release_when_post_rejects(pg, hold):
    case = await _prepare(pg)
    # The actual movement engine first establishes an eligible fractional bucket.
    await _mutate(pg, case)
    await _set_variant(pg, case, operational_hold=hold)

    source = await _source(pg, case)
    release = _action(source, "QUARANTINED", "AVAILABLE")
    assert release["eligible_quantity"] == "2.500001"
    assert release["allowed"] is False
    assert release["reason_code"] == (
        "PRODUCT_RECALLED" if hold == "RECALL" else "PRODUCT_SALES_HOLD"
    )

    # Hold must not block a permitted safety escalation to RECALLED.
    recall = _action(source, "QUARANTINED", "RECALLED")
    assert recall["allowed"] is True

    with pytest.raises(HTTPException) as rejected:
        await _mutate(
            pg, case, source="QUARANTINED", destination="AVAILABLE", quantity="0.500001",
        )
    assert rejected.value.status_code == 409
    assert rejected.value.detail["code"] == (
        "PRODUCT_RECALLED" if hold == "RECALL" else "PRODUCT_SALES_HOLD"
    )

    async with pg.session() as db:
        qty = await db.scalar(select(InventoryBalance.on_hand_quantity).where(
            InventoryBalance.company_id == case.a.company_id,
            InventoryBalance.location_id == case.a.location_id,
            InventoryBalance.product_variant_id == case.a.variant_id,
            InventoryBalance.batch_id == case.a_batch_id,
            InventoryBalance.stock_status == "QUARANTINED",
        ))
        assert Decimal(qty) == Decimal("2.500001")

    # A foreign-company selection never exposes this source.
    async with pg.session(1) as db:
        with pytest.raises(HTTPException) as forbidden:
            await live_stock_source_detail.get_live_stock_batch_source(
                case.a.variant_id, case.a_batch_id, case.a.location_id,
                db, case.b.owner.access(db),
            )
        assert forbidden.value.status_code in (403, 404)


async def test_f2_archived_lifecycle_does_not_advertise_mutations(pg):
    case = await _prepare(pg)
    await _mutate(pg, case)
    # The lifecycle timestamps are part of a real database check constraint.
    await _set_variant(
        pg, case, lifecycle_status="ARCHIVED",
        retired_at=utc_now(), archived_at=utc_now(),
    )

    source = await _source(pg, case)
    for status in source["statuses"]:
        for action in status["status_change_actions"]:
            assert action["allowed"] is False
            assert action["reason_code"] == "PRODUCT_NOT_OPERATIONAL"

    with pytest.raises(HTTPException) as rejected:
        await _mutate(
            pg, case, source="QUARANTINED", destination="AVAILABLE", quantity="0.500001",
        )
    assert rejected.value.status_code == 409


async def test_f3_inactive_shelf_life_policy_is_ignored_but_active_policy_blocks(pg):
    case = await _prepare(pg)
    await _mutate(pg, case)
    async with pg.session() as db:
        today = await get_company_local_date(db, case.a.company_id)

    expiry = today + timedelta(days=10)
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(
            text("SELECT set_config('app.current_tenant', :company, true)"),
            {"company": str(case.a.company_id)},
        )
        updated = await seed.execute(
            update(ProductBatch)
            .where(ProductBatch.company_id == case.a.company_id, ProductBatch.id == case.a_batch_id)
            .values(expiry_date=expiry)
        )
        assert updated.rowcount == 1
        policy = InventoryStockPolicy(
            company_id=case.a.company_id,
            location_id=case.a.location_id,
            product_variant_id=case.a.variant_id,
            minimum_quantity=Decimal("0"),
            minimum_remaining_shelf_life_days=30,
            is_active=True,
        )
        seed.add(policy)
        await seed.commit()

    active = _action(await _source(pg, case), "QUARANTINED", "AVAILABLE")
    assert active["allowed"] is False
    assert active["reason_code"] == "BATCH_NOT_SELLABLE"
    with pytest.raises(HTTPException) as rejected:
        await _mutate(
            pg, case, source="QUARANTINED", destination="AVAILABLE", quantity="0.500001",
        )
    assert rejected.value.status_code == 409
    assert rejected.value.detail["code"] == "SHELF_LIFE_POLICY_BLOCKED"

    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(
            text("SELECT set_config('app.current_tenant', :company, true)"),
            {"company": str(case.a.company_id)},
        )
        updated = await seed.execute(
            update(InventoryStockPolicy).where(
                InventoryStockPolicy.company_id == case.a.company_id,
                InventoryStockPolicy.location_id == case.a.location_id,
                InventoryStockPolicy.product_variant_id == case.a.variant_id,
            ).values(is_active=False)
        )
        assert updated.rowcount == 1
        await seed.commit()

    inactive = _action(await _source(pg, case), "QUARANTINED", "AVAILABLE")
    assert inactive["allowed"] is True
    assert inactive["reason_code"] == "ALLOWED"
    assert inactive["eligible_quantity"] == "2.500001"
    result = await _mutate(
        pg, case, source="QUARANTINED", destination="AVAILABLE", quantity="0.500001",
    )
    assert result["destination_status"] == "AVAILABLE"


async def test_f3_expiry_boundaries_reservation_and_permission_are_exact_decimal():
    from datetime import date
    today = date(2026, 10, 30)
    base = dict(
        source_status="QUARANTINED",
        eligible_quantity=Decimal("0.500001"),
        can_change=True,
        as_of_date=today,
        expiry_control_mode="REQUIRED",
        production_date=today - timedelta(days=5),
        is_active=True,
        disposition="RELEASED",
        lifecycle_status="ACTIVE",
        operational_hold="NONE",
    )
    def released(**changes):
        kwargs = {**base, **changes}
        return next(
            action for action in status_change_availability_for_batch(**kwargs)
            if action["destination_status"] == "AVAILABLE"
        )

    assert released(
        expiry_date=today + timedelta(days=10),
        minimum_remaining_shelf_life_days=10,
    )["allowed"] is True
    assert released(
        expiry_date=today + timedelta(days=10),
        minimum_remaining_shelf_life_days=11,
    )["reason_code"] == "BATCH_NOT_SELLABLE"
    assert released(
        expiry_date=today,
        minimum_remaining_shelf_life_days=0,
    )["allowed"] is True
    assert released(
        expiry_date=today - timedelta(days=1),
        minimum_remaining_shelf_life_days=0,
    )["reason_code"] == "BATCH_NOT_SELLABLE"
    assert released(
        expiry_date=today + timedelta(days=10),
        minimum_remaining_shelf_life_days=0,
        can_change=False,
    )["reason_code"] == "PERMISSION_REQUIRED"
    assert released(
        expiry_date=today + timedelta(days=10),
        minimum_remaining_shelf_life_days=0,
        eligible_quantity=Decimal("0"),
    )["reason_code"] == "NO_ELIGIBLE_QUANTITY"

    assert released(
        expiry_date=today + timedelta(days=10),
        minimum_remaining_shelf_life_days=0,
        lifecycle_status="DRAFT",
        operational_hold="NONE",
    )["reason_code"] == "PRODUCT_NOT_OPERATIONAL"
    assert released(
        expiry_date=today + timedelta(days=10),
        minimum_remaining_shelf_life_days=0,
        lifecycle_status="RETIRING",
        operational_hold="NONE",
    )["allowed"] is True


async def test_f2_f3_permission_revocation_and_reserved_fractional_bucket(pg):
    case = await _prepare(pg)
    await _mutate(pg, case)

    # Fractional reservations are legal ONLY on AVAILABLE. The database
    # explicitly forbids reservations on quarantined status buckets.
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(
            text("SELECT set_config('app.current_tenant', :company, true)"),
            {"company": str(case.a.company_id)},
        )
        changed = await seed.execute(
            update(InventoryBalance)
            .where(
                InventoryBalance.company_id == case.a.company_id,
                InventoryBalance.location_id == case.a.location_id,
                InventoryBalance.product_variant_id == case.a.variant_id,
                InventoryBalance.batch_id == case.a_batch_id,
                InventoryBalance.stock_status == "AVAILABLE",
            )
            .values(reserved_quantity=Decimal("3.000001"))
        )
        assert changed.rowcount == 1
        await seed.commit()

    source = await _source(pg, case)
    quarantine = _action(source, "AVAILABLE", "QUARANTINED")
    assert quarantine["eligible_quantity"] == "4.499998"
    assert quarantine["allowed"] is True

    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(
            text("SELECT set_config('app.current_tenant', :company, true)"),
            {"company": str(case.a.company_id)},
        )
        status_role_ids = (
            select(role_permissions.c.role_id)
            .join(Permission, Permission.id == role_permissions.c.permission_id)
            .where(
                role_permissions.c.company_id == case.a.company_id,
                Permission.code == "inventory.status_change",
            )
        )
        removed = await seed.execute(
            delete(UserLocationAccess).where(
                UserLocationAccess.company_id == case.a.company_id,
                UserLocationAccess.driver_id == case.a.ordinary.driver_id,
                UserLocationAccess.location_id == case.a.location_id,
                UserLocationAccess.role_id.in_(status_role_ids),
            )
        )
        assert removed.rowcount == 1
        await seed.commit()

    denied_source = await _source(pg, case)
    quarantine = _action(denied_source, "AVAILABLE", "QUARANTINED")
    assert quarantine["allowed"] is False
    assert quarantine["reason_code"] == "PERMISSION_REQUIRED"
    assert quarantine["eligible_quantity"] == "4.499998"

    with pytest.raises(HTTPException) as denied:
        await _mutate(
            pg, case, source="AVAILABLE", destination="QUARANTINED", quantity="0.500001",
        )
    assert denied.value.status_code == 403
