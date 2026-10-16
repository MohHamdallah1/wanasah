from __future__ import annotations

import os
from decimal import Decimal
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.warehouse import live_stock_source_detail, transfers
from models import (
    InventoryBalance,
    InventoryMovement,
    Permission,
    ProductBatch,
    ProductLocation,
    Role,
    UserLocationAccess,
    UserRole,
    role_permissions,
)
from schemas import BatchDispositionChangeRequest, InventoryStatusChangeRequest
from tests.test_inbound_no_lot_frozen_postgres import pg


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CP3_PG_GATE") != "1",
        reason="Explicit migrated disposable CP3 PostgreSQL gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _grant(
    seed: AsyncSession,
    tenant,
    code: str,
    *,
    location_id: int | None,
) -> None:
    permission = await seed.scalar(select(Permission).where(Permission.code == code))
    assert permission is not None, f"missing migrated permission: {code}"
    role = Role(company_id=tenant.company_id, name=f"CP3 {code} {uuid4().hex}")
    seed.add(role)
    await seed.flush()
    await seed.execute(
        role_permissions.insert().values(
            company_id=tenant.company_id,
            role_id=role.id,
            permission_id=permission.id,
        )
    )
    assignment = dict(
        company_id=tenant.company_id,
        role_id=role.id,
        driver_id=tenant.ordinary.driver_id,
    )
    if location_id is None:
        seed.add(UserRole(**assignment))
    else:
        seed.add(UserLocationAccess(**assignment, location_id=location_id))


async def _prepare(pg):
    a = pg.tenants[0]
    b = pg.tenants[1]
    lot = "CP3-CORE-" + uuid4().hex[:12]

    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(
            text("SELECT set_config('app.current_tenant',:tenant,true)"),
            {"tenant": str(a.company_id)},
        )
        existing = await seed.scalar(
            select(ProductLocation.id).where(
                ProductLocation.company_id == a.company_id,
                ProductLocation.location_id == a.other_location_id,
                ProductLocation.product_variant_id == a.variant_id,
            )
        )
        if existing is None:
            seed.add(
                ProductLocation(
                    company_id=a.company_id,
                    location_id=a.other_location_id,
                    product_variant_id=a.variant_id,
                    created_by=a.owner.driver_id,
                    operational_flags={
                        "inbound_enabled": True,
                        "outbound_enabled": True,
                    },
                )
            )
        await _grant(seed, a, "batch.disposition", location_id=None)
        await _grant(seed, a, "inventory.read", location_id=a.location_id)
        await _grant(seed, a, "inventory.status_change", location_id=a.location_id)
        await seed.commit()

    async with pg.session() as db:
        await pg.post(db, pg.request(lot=lot, quantity="10"))
        await pg.post(
            db,
            pg.request(lot=lot, quantity="7").model_copy(
                update={"location_id": a.other_location_id}
            ),
        )
    async with pg.session(1) as db:
        await pg.post(db, pg.request(party=1, lot=lot, quantity="9"), party=1)

    async with pg.session() as db:
        a_batch = await db.scalar(
            select(ProductBatch).where(
                ProductBatch.company_id == a.company_id,
                ProductBatch.product_variant_id == a.variant_id,
                ProductBatch.batch_number == lot,
            )
        )
        assert a_batch is not None
        a_batch_id = int(a_batch.id)
        initial_revision = int(a_batch.disposition_revision)
    async with pg.session(1) as db:
        b_batch_id = await db.scalar(
            select(ProductBatch.id).where(
                ProductBatch.company_id == b.company_id,
                ProductBatch.product_variant_id == b.variant_id,
                ProductBatch.batch_number == lot,
            )
        )
        assert b_batch_id is not None

    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(
            text("SELECT set_config('app.current_tenant',:tenant,true)"),
            {"tenant": str(a.company_id)},
        )
        result = await seed.execute(
            update(InventoryBalance)
            .where(
                InventoryBalance.company_id == a.company_id,
                InventoryBalance.location_id == a.location_id,
                InventoryBalance.product_variant_id == a.variant_id,
                InventoryBalance.batch_id == a_batch_id,
                InventoryBalance.stock_status == "AVAILABLE",
            )
            .values(reserved_quantity=Decimal("3"))
        )
        assert result.rowcount == 1
        await seed.commit()

    return NS(
        a=a,
        b=b,
        lot=lot,
        a_batch_id=a_batch_id,
        b_batch_id=int(b_batch_id),
        initial_revision=initial_revision,
    )


async def _balance(db, *, company_id, location_id, variant_id, batch_id, status):
    row = (
        await db.execute(
            select(
                InventoryBalance.on_hand_quantity,
                InventoryBalance.reserved_quantity,
            ).where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == location_id,
                InventoryBalance.product_variant_id == variant_id,
                InventoryBalance.batch_id == batch_id,
                InventoryBalance.stock_status == status,
            )
        )
    ).one_or_none()
    if row is None:
        return Decimal("0"), Decimal("0")
    return Decimal(row.on_hand_quantity), Decimal(row.reserved_quantity)


async def test_cp3_real_postgres_isolation_reservations_replay_and_transition_truth(pg):
    case = await _prepare(pg)
    a = case.a
    b = case.b

    # Server-derived exact-Warehouse eligibility uses authoritative free quantity.
    async with pg.session() as db:
        source = await live_stock_source_detail.get_live_stock_batch_source(
            a.variant_id,
            case.a_batch_id,
            a.location_id,
            db,
            a.ordinary.access(db),
        )
        assert source["location_id"] == a.location_id
        assert source["product_variant_id"] == a.variant_id
        assert source["batch_id"] == case.a_batch_id
        available = next(
            item for item in source["statuses"] if item["stock_status"] == "AVAILABLE"
        )
        assert available["on_hand_quantity"] == "10"
        assert available["reserved_quantity"] == "3"
        assert available["movable_quantity"] == "7"
        assert available["reservation_evidence"].coverage == "UNRESOLVED"
        assert [
            (item["destination_status"], item["allowed"], item["eligible_quantity"])
            for item in available["status_change_actions"]
        ] == [
            ("QUARANTINED", True, "7"),
            ("BLOCKED", True, "7"),
            ("RECALLED", True, "7"),
        ]

    # Exact-location capability: the same non-owner cannot mutate A2.
    async with pg.session() as db:
        with pytest.raises(HTTPException) as denied_a2:
            await transfers.change_inventory_status(
                InventoryStatusChangeRequest(
                    request_id=uuid4(),
                    location_id=a.other_location_id,
                    product_variant_id=a.variant_id,
                    batch_id=case.a_batch_id,
                    uom_id=a.uom_id,
                    source_status="AVAILABLE",
                    destination_status="QUARANTINED",
                    quantity="1",
                    reason="CP3 location isolation",
                ),
                db,
                a.ordinary.access(db),
                a.ordinary.operational_driver,
            )
        assert denied_a2.value.status_code == 403

    # Reservation truth blocks an over-free mutation and leaves no partial movement.
    async with pg.session() as db:
        before_movements = int(
            await db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(InventoryMovement.company_id == a.company_id)
            )
        )
        with pytest.raises(HTTPException) as over_reserved:
            await transfers.change_inventory_status(
                InventoryStatusChangeRequest(
                    request_id=uuid4(),
                    location_id=a.location_id,
                    product_variant_id=a.variant_id,
                    batch_id=case.a_batch_id,
                    uom_id=a.uom_id,
                    source_status="AVAILABLE",
                    destination_status="QUARANTINED",
                    quantity="8",
                    reason="CP3 reservation protection",
                ),
                db,
                a.ordinary.access(db),
                a.ordinary.operational_driver,
            )
        assert over_reserved.value.status_code == 409
        assert int(
            await db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(InventoryMovement.company_id == a.company_id)
            )
        ) == before_movements

    # Allowed exact-quantity transition posts one authoritative movement.
    status_request_id = uuid4()
    status_payload = InventoryStatusChangeRequest(
        request_id=status_request_id,
        location_id=a.location_id,
        product_variant_id=a.variant_id,
        batch_id=case.a_batch_id,
        uom_id=a.uom_id,
        source_status="AVAILABLE",
        destination_status="QUARANTINED",
        quantity="2",
        reason="CP3 exact status change",
    )
    async with pg.session() as db:
        response = await transfers.change_inventory_status(
            status_payload,
            db,
            a.ordinary.access(db),
            a.ordinary.operational_driver,
        )
        movement_id = int(response["movement_id"])
        assert response["source_status"] == "AVAILABLE"
        assert response["destination_status"] == "QUARANTINED"

    async with pg.session() as db:
        a1_available = await _balance(
            db,
            company_id=a.company_id,
            location_id=a.location_id,
            variant_id=a.variant_id,
            batch_id=case.a_batch_id,
            status="AVAILABLE",
        )
        a1_quarantine = await _balance(
            db,
            company_id=a.company_id,
            location_id=a.location_id,
            variant_id=a.variant_id,
            batch_id=case.a_batch_id,
            status="QUARANTINED",
        )
        a2_available = await _balance(
            db,
            company_id=a.company_id,
            location_id=a.other_location_id,
            variant_id=a.variant_id,
            batch_id=case.a_batch_id,
            status="AVAILABLE",
        )
        assert a1_available == (Decimal("8"), Decimal("3"))
        assert a1_quarantine == (Decimal("2"), Decimal("0"))
        assert a2_available == (Decimal("7"), Decimal("0"))
        movement = await db.get(InventoryMovement, movement_id)
        assert movement is not None
        assert movement.location_id if hasattr(movement, "location_id") else True
        status_movement_count = int(
            await db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(
                    InventoryMovement.company_id == a.company_id,
                    InventoryMovement.reference_type == "STATUS_RECLASSIFICATION",
                    InventoryMovement.reference_id == str(status_request_id),
                )
            )
        )
        assert status_movement_count == 1

    # Same ambiguous logical command replays without a duplicate movement.
    async with pg.session() as db:
        replay = await transfers.change_inventory_status(
            status_payload,
            db,
            a.ordinary.access(db),
            a.ordinary.operational_driver,
        )
        assert int(replay["movement_id"]) == movement_id
        assert int(
            await db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(
                    InventoryMovement.company_id == a.company_id,
                    InventoryMovement.reference_type == "STATUS_RECLASSIFICATION",
                    InventoryMovement.reference_id == str(status_request_id),
                )
            )
        ) == 1

    # Frozen Backend matrix rejects impossible normal operator destinations.
    async with pg.session() as db:
        before = await _balance(
            db,
            company_id=a.company_id,
            location_id=a.location_id,
            variant_id=a.variant_id,
            batch_id=case.a_batch_id,
            status="QUARANTINED",
        )
        with pytest.raises(HTTPException) as forbidden:
            await transfers.change_inventory_status(
                InventoryStatusChangeRequest(
                    request_id=uuid4(),
                    location_id=a.location_id,
                    product_variant_id=a.variant_id,
                    batch_id=case.a_batch_id,
                    uom_id=a.uom_id,
                    source_status="QUARANTINED",
                    destination_status="DAMAGED",
                    quantity="1",
                    reason="CP3 forbidden transition proof",
                ),
                db,
                a.ordinary.access(db),
                a.ordinary.operational_driver,
            )
        assert forbidden.value.status_code == 409
        assert await _balance(
            db,
            company_id=a.company_id,
            location_id=a.location_id,
            variant_id=a.variant_id,
            batch_id=case.a_batch_id,
            status="QUARANTINED",
        ) == before

    # Authorized non-owner disposition is company-wide and idempotent.
    disposition_request_id = uuid4()
    disposition_payload = BatchDispositionChangeRequest(
        request_id=disposition_request_id,
        expected_revision=case.initial_revision,
        disposition="QUARANTINED",
        reason="CP3 company-wide quarantine",
    )
    async with pg.session() as db:
        disposition_response = await transfers.change_batch_disposition(
            case.a_batch_id,
            disposition_payload,
            db,
            a.ordinary.access(db),
            a.ordinary.operational_driver,
        )
        assert disposition_response["disposition"] == "QUARANTINED"
        new_revision = int(disposition_response["disposition_revision"])
        assert new_revision > case.initial_revision
    async with pg.session() as db:
        replay = await transfers.change_batch_disposition(
            case.a_batch_id,
            disposition_payload,
            db,
            a.ordinary.access(db),
            a.ordinary.operational_driver,
        )
        assert int(replay["disposition_revision"]) == new_revision
        batch = await db.get(ProductBatch, case.a_batch_id)
        assert batch is not None
        assert batch.disposition == "QUARANTINED"
        # Quantity in both A warehouses remains unchanged by company-wide disposition.
        assert sum(await _balance(
            db,
            company_id=a.company_id,
            location_id=a.location_id,
            variant_id=a.variant_id,
            batch_id=case.a_batch_id,
            status=status,
        )[0] for status in ("AVAILABLE", "QUARANTINED")) == Decimal("10")
        assert (await _balance(
            db,
            company_id=a.company_id,
            location_id=a.other_location_id,
            variant_id=a.variant_id,
            batch_id=case.a_batch_id,
            status="AVAILABLE",
        ))[0] == Decimal("7")

    # Revision conflict never overwrites newer truth.
    async with pg.session() as db:
        with pytest.raises(HTTPException) as conflict:
            await transfers.change_batch_disposition(
                case.a_batch_id,
                BatchDispositionChangeRequest(
                    request_id=uuid4(),
                    expected_revision=case.initial_revision,
                    disposition="BLOCKED",
                    reason="CP3 stale revision",
                ),
                db,
                a.ordinary.access(db),
                a.ordinary.operational_driver,
            )
        assert conflict.value.status_code == 409
        assert conflict.value.detail["code"] == "BATCH_DISPOSITION_REVISION_CONFLICT"
        batch = await db.get(ProductBatch, case.a_batch_id)
        assert batch is not None and batch.disposition == "QUARANTINED"

    # QUARANTINED -> AVAILABLE rechecks current batch sellability and is denied.
    async with pg.session() as db:
        with pytest.raises(HTTPException) as not_sellable:
            await transfers.change_inventory_status(
                InventoryStatusChangeRequest(
                    request_id=uuid4(),
                    location_id=a.location_id,
                    product_variant_id=a.variant_id,
                    batch_id=case.a_batch_id,
                    uom_id=a.uom_id,
                    source_status="QUARANTINED",
                    destination_status="AVAILABLE",
                    quantity="1",
                    reason="CP3 release must recheck sellability",
                ),
                db,
                a.ordinary.access(db),
                a.ordinary.operational_driver,
            )
        assert not_sellable.value.status_code == 409

    # Company B cannot be mutated through Company A authority; B truth is intact.
    async with pg.session() as db:
        with pytest.raises(HTTPException):
            await transfers.change_batch_disposition(
                case.b_batch_id,
                BatchDispositionChangeRequest(
                    request_id=uuid4(),
                    expected_revision=1,
                    disposition="QUARANTINED",
                    reason="CP3 cross-company denial",
                ),
                db,
                a.ordinary.access(db),
                a.ordinary.operational_driver,
            )
    async with pg.session(1) as db:
        foreign = await db.get(ProductBatch, case.b_batch_id)
        assert foreign is not None
        assert foreign.disposition == "RELEASED"
        with pytest.raises(HTTPException) as unauthorized:
            await transfers.change_batch_disposition(
                case.b_batch_id,
                BatchDispositionChangeRequest(
                    request_id=uuid4(),
                    expected_revision=int(foreign.disposition_revision),
                    disposition="QUARANTINED",
                    reason="CP3 unauthorized non-owner",
                ),
                db,
                b.ordinary.access(db),
                b.ordinary.operational_driver,
            )
        assert unauthorized.value.status_code == 403
