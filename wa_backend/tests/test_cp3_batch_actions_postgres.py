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


async def _grant(seed: AsyncSession, tenant, code: str, location_id: int | None) -> None:
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
    assignment = {
        "company_id": tenant.company_id,
        "role_id": role.id,
        "driver_id": tenant.ordinary.driver_id,
    }
    if location_id is None:
        seed.add(UserRole(**assignment))
    else:
        seed.add(UserLocationAccess(**assignment, location_id=location_id))


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


async def _movement_count(db, company_id: int, request_id) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(InventoryMovement)
            .where(
                InventoryMovement.company_id == company_id,
                InventoryMovement.reference_type == "STATUS_RECLASSIFICATION",
                InventoryMovement.reference_id == str(request_id),
            )
        )
    )


async def _prepare(pg):
    a = pg.tenants[0]
    b = pg.tenants[1]
    lot = "CP3-CORE-" + uuid4().hex[:12]

    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(
            text("SELECT set_config('app.current_tenant',:tenant,true)"),
            {"tenant": str(a.company_id)},
        )
        if await seed.scalar(
            select(ProductLocation.id).where(
                ProductLocation.company_id == a.company_id,
                ProductLocation.location_id == a.other_location_id,
                ProductLocation.product_variant_id == a.variant_id,
            )
        ) is None:
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
        await _grant(seed, a, "batch.disposition", None)
        await _grant(seed, a, "inventory.read", a.location_id)
        await _grant(seed, a, "inventory.status_change", a.location_id)
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

    # Authoritative reservation pressure; owner evidence intentionally unresolved.
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(
            text("SELECT set_config('app.current_tenant',:tenant,true)"),
            {"tenant": str(a.company_id)},
        )
        changed = await seed.execute(
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
        assert changed.rowcount == 1
        await seed.commit()

    return NS(
        a=a,
        b=b,
        a_batch_id=a_batch_id,
        b_batch_id=int(b_batch_id),
        initial_revision=initial_revision,
    )


async def test_cp3_postgres_exact_warehouse_status_and_reservation_truth(pg):
    case = await _prepare(pg)
    a = case.a

    async with pg.session() as db:
        source = await live_stock_source_detail.get_live_stock_batch_source(
            a.variant_id,
            case.a_batch_id,
            a.location_id,
            db,
            a.ordinary.access(db),
        )
        available = next(
            row for row in source["statuses"] if row["stock_status"] == "AVAILABLE"
        )
        assert source["location_id"] == a.location_id
        assert source["product_variant_id"] == a.variant_id
        assert source["batch_id"] == case.a_batch_id
        assert source["base_uom_id"] == a.uom_id
        assert source["quantity_scale"] == 6
        assert source["quantity_step"] == "0.000001"
        assert available["on_hand_quantity"] == "10"
        assert available["reserved_quantity"] == "3"
        assert available["movable_quantity"] == "7"
        assert available["reservation_evidence"].coverage == "UNRESOLVED"
        assert [
            (action["destination_status"], action["allowed"], action["eligible_quantity"])
            for action in available["status_change_actions"]
        ] == [
            ("QUARANTINED", True, "7"),
            ("BLOCKED", True, "7"),
            ("RECALLED", True, "7"),
        ]

    # Location-scoped permission cannot authorize A2.
    async with pg.session() as db:
        with pytest.raises(HTTPException) as denied:
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
        assert denied.value.status_code == 403

    async with pg.session() as db:
        before_total_movements = int(
            await db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(InventoryMovement.company_id == a.company_id)
            )
        )
    # Mutation rollback clears SET LOCAL tenant state, so assertions use a fresh session.
    async with pg.session() as db:
        with pytest.raises(HTTPException) as reserved:
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
        assert reserved.value.status_code == 409
    async with pg.session() as db:
        assert int(
            await db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(InventoryMovement.company_id == a.company_id)
            )
        ) == before_total_movements

    request_id = uuid4()
    payload = InventoryStatusChangeRequest(
        request_id=request_id,
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
            payload,
            db,
            a.ordinary.access(db),
            a.ordinary.operational_driver,
        )
        movement_id = int(response["movement_id"])
        assert response["source_status"] == "AVAILABLE"
        assert response["destination_status"] == "QUARANTINED"

    async with pg.session() as db:
        assert await _balance(
            db,
            company_id=a.company_id,
            location_id=a.location_id,
            variant_id=a.variant_id,
            batch_id=case.a_batch_id,
            status="AVAILABLE",
        ) == (Decimal("8"), Decimal("3"))
        assert await _balance(
            db,
            company_id=a.company_id,
            location_id=a.location_id,
            variant_id=a.variant_id,
            batch_id=case.a_batch_id,
            status="QUARANTINED",
        ) == (Decimal("2"), Decimal("0"))
        assert await _balance(
            db,
            company_id=a.company_id,
            location_id=a.other_location_id,
            variant_id=a.variant_id,
            batch_id=case.a_batch_id,
            status="AVAILABLE",
        ) == (Decimal("7"), Decimal("0"))
        assert await _movement_count(db, a.company_id, request_id) == 1

    # Same ambiguous logical command replays exactly one movement.
    async with pg.session() as db:
        replay = await transfers.change_inventory_status(
            payload,
            db,
            a.ordinary.access(db),
            a.ordinary.operational_driver,
        )
        assert int(replay["movement_id"]) == movement_id
    async with pg.session() as db:
        assert await _movement_count(db, a.company_id, request_id) == 1

    # Backend transition authority rejects a forbidden normal destination.
    async with pg.session() as db:
        before = await _balance(
            db,
            company_id=a.company_id,
            location_id=a.location_id,
            variant_id=a.variant_id,
            batch_id=case.a_batch_id,
            status="QUARANTINED",
        )
    async with pg.session() as db:
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
    async with pg.session() as db:
        assert await _balance(
            db,
            company_id=a.company_id,
            location_id=a.location_id,
            variant_id=a.variant_id,
            batch_id=case.a_batch_id,
            status="QUARANTINED",
        ) == before


async def test_cp3_postgres_company_wide_disposition_revision_and_tenant_isolation(pg):
    case = await _prepare(pg)
    a = case.a
    b = case.b

    # Establish a real QUARANTINED source while the batch is still sellable.
    async with pg.session() as db:
        await transfers.change_inventory_status(
            InventoryStatusChangeRequest(
                request_id=uuid4(),
                location_id=a.location_id,
                product_variant_id=a.variant_id,
                batch_id=case.a_batch_id,
                uom_id=a.uom_id,
                source_status="AVAILABLE",
                destination_status="QUARANTINED",
                quantity="1",
                reason="CP3 prepare quarantine source",
            ),
            db,
            a.ordinary.access(db),
            a.ordinary.operational_driver,
        )

    request_id = uuid4()
    payload = BatchDispositionChangeRequest(
        request_id=request_id,
        expected_revision=case.initial_revision,
        disposition="QUARANTINED",
        reason="CP3 company-wide quarantine",
    )
    async with pg.session() as db:
        response = await transfers.change_batch_disposition(
            case.a_batch_id,
            payload,
            db,
            a.ordinary.access(db),
            a.ordinary.operational_driver,
        )
        new_revision = int(response["disposition_revision"])
        assert response["disposition"] == "QUARANTINED"
        assert new_revision > case.initial_revision

    async with pg.session() as db:
        replay = await transfers.change_batch_disposition(
            case.a_batch_id,
            payload,
            db,
            a.ordinary.access(db),
            a.ordinary.operational_driver,
        )
        assert int(replay["disposition_revision"]) == new_revision

    async with pg.session() as db:
        batch = await db.get(ProductBatch, case.a_batch_id)
        assert batch is not None and batch.disposition == "QUARANTINED"
        a1_available = await _balance(
            db,
            company_id=a.company_id,
            location_id=a.location_id,
            variant_id=a.variant_id,
            batch_id=case.a_batch_id,
            status="AVAILABLE",
        )
        a1_quarantined = await _balance(
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
        assert a1_available[0] + a1_quarantined[0] == Decimal("10")
        assert a2_available[0] == Decimal("7")

    # Stale revision cannot overwrite the newer company-wide truth.
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
    async with pg.session() as db:
        batch = await db.get(ProductBatch, case.a_batch_id)
        assert batch is not None and batch.disposition == "QUARANTINED"

    # QUARANTINED -> AVAILABLE must recheck the now-unsellable batch.
    async with pg.session() as db:
        with pytest.raises(HTTPException) as release:
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
                    reason="CP3 release sellability recheck",
                ),
                db,
                a.ordinary.access(db),
                a.ordinary.operational_driver,
            )
        assert release.value.status_code == 409

    # Company A authority cannot reach Company B's batch.
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

    # Company B ordinary has no disposition grant and remains unchanged.
    async with pg.session(1) as db:
        foreign = await db.get(ProductBatch, case.b_batch_id)
        assert foreign is not None and foreign.disposition == "RELEASED"
        expected_revision = int(foreign.disposition_revision)
    async with pg.session(1) as db:
        with pytest.raises(HTTPException) as unauthorized:
            await transfers.change_batch_disposition(
                case.b_batch_id,
                BatchDispositionChangeRequest(
                    request_id=uuid4(),
                    expected_revision=expected_revision,
                    disposition="QUARANTINED",
                    reason="CP3 unauthorized non-owner",
                ),
                db,
                b.ordinary.access(db),
                b.ordinary.operational_driver,
            )
        assert unauthorized.value.status_code == 403
    async with pg.session(1) as db:
        foreign = await db.get(ProductBatch, case.b_batch_id)
        assert foreign is not None and foreign.disposition == "RELEASED"
