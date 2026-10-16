"""CP14-B operational acceptance: Batch / Quality / Transfers on real PostgreSQL 16.

This suite intentionally reuses the accepted CP8/CP3.4 PostgreSQL fixture and
canonical service/API helpers.  It does not depend on CP14-A and never writes
InventoryBalance directly.
"""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.warehouse import batch_index, ledger, live_stock, live_stock_source_detail, transfers
from domains import inventory_terminal_quality as disposal_domain
from domains import inventory_terminal_vendor as vendor_domain
from domains.inventory_rules import batch_metadata_is_sellable
from models import (
    InventoryBalance,
    InventoryMovement,
    InventoryStockPolicy,
    InventoryTransferHeader,
    InventoryTransferLine,
    Permission,
    ProductBatch,
    ProductVariant,
    role_permissions,
)
from schemas import (
    BatchDispositionChangeRequest,
    InventoryStatusChangeRequest,
    UnifiedReceiveRequest,
    UnifiedTransferDecisionRequest,
    WarehouseBatchStockSourcesResponse,
)
from services import apply_inventory_movement
from tests.test_cp8_transfers_postgres import (
    _grant_location,
    dispatch_payload,
    pg,
    send,
)
from tests.test_cp34_quality_terminal_postgres import (
    dispatch as dispatch_special,
    grant_company,
    movement_snapshot,
    prepare as prepare_quality,
    quantity,
    special,
    stage,
    terminal,
    terminal_payload,
    test_active_costing_transfers_preserve_value_and_only_terminal_exit_consumes_value as _accepted_cost_path,
)


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CP8_PG_GATE") != "1",
        reason="Explicit disposable CP14-B/CP8 PostgreSQL gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _balance(db, tenant, *, location_id: int, batch_id: int, status: str):
    row = (
        await db.execute(
            select(InventoryBalance.on_hand_quantity, InventoryBalance.reserved_quantity).where(
                InventoryBalance.company_id == tenant.company_id,
                InventoryBalance.location_id == location_id,
                InventoryBalance.product_variant_id == tenant.variant_id,
                InventoryBalance.batch_id == batch_id,
                InventoryBalance.stock_status == status,
            )
        )
    ).one_or_none()
    if row is None:
        return Decimal("0"), Decimal("0")
    return Decimal(row.on_hand_quantity), Decimal(row.reserved_quantity)


async def _company_quantity(pg, tenant):
    async with pg.session(tenant) as db:
        return Decimal(
            await db.scalar(
                select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0)).where(
                    InventoryBalance.company_id == tenant.company_id,
                    InventoryBalance.product_variant_id == tenant.variant_id,
                )
            )
        )


async def _movement_count(pg, tenant):
    async with pg.session(tenant) as db:
        return int(
            await db.scalar(
                select(func.count()).select_from(InventoryMovement).where(
                    InventoryMovement.company_id == tenant.company_id
                )
            )
        )


async def _revoke(pg, code: str) -> None:
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as db:
        permission = await db.scalar(select(Permission.id).where(Permission.code == code))
        assert permission is not None, code
        await db.execute(
            role_permissions.delete().where(
                role_permissions.c.company_id == pg.a.company_id,
                role_permissions.c.permission_id == permission,
            )
        )
        await db.commit()


async def _prepare_cp14(pg, *, policy_days: int | None = None) -> None:
    await prepare_quality(pg)
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as db:
        await grant_company(db, pg.a, "batch.disposition")
        await _grant_location(
            db,
            pg.a,
            pg.a.locations[0],
            "inventory.status_change",
            "ledger.read",
        )
        await _grant_location(db, pg.a, pg.a.locations[1], "inventory.read", "ledger.read")
        await _grant_location(db, pg.a, pg.a.quarantine_id, "ledger.read")
        if policy_days is not None:
            db.add(
                InventoryStockPolicy(
                    company_id=pg.a.company_id,
                    location_id=pg.a.locations[0],
                    product_variant_id=pg.a.variant_id,
                    minimum_remaining_shelf_life_days=policy_days,
                    is_active=True,
                )
            )
        await db.commit()


async def _batch_page(pg, location_id: int, *, warning_days: int | None = None):
    async with pg.session(pg.a) as db:
        return await batch_index.get_warehouse_inventory_batch_index_cursor(
            location_id=location_id,
            cursor=None,
            limit=50,
            search=None,
            expiry_state="EXPIRING_SOON" if warning_days is not None else "ALL",
            expiry_warning_days=warning_days,
            sellability="ALL",
            disposition=None,
            has_unavailable=None,
            has_damaged=None,
            has_disposal_pending=None,
            family_id=None,
            product_variant_id=pg.a.variant_id,
            sort="EXPIRY_ASC",
            db=db,
            access=pg.a.ordinary.access(db),
        )


def _item(page, batch_id: int):
    return next(row for row in page["items"] if row["batch_id"] == batch_id)


def _opaque_signature(exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        return exc.status_code, detail.get("code")
    return exc.status_code, str(detail)


async def _reserve(pg, *, batch_id: int, quantity_value: str, action: str = "RESERVE"):
    async with pg.session(pg.a) as db:
        movement = await apply_inventory_movement(
            db,
            company_id=pg.a.company_id,
            performed_by=pg.a.owner.driver_id,
            product_variant_id=pg.a.variant_id,
            batch_id=batch_id,
            quantity=Decimal(quantity_value),
            movement_kind="RESERVATION",
            reservation_action=action,
            reference_type="CP14B_RESERVATION",
            reference_id="cp14b-reservation-owner",
            idempotency_key=str(uuid4()),
            source_location_id=pg.a.locations[0],
            destination_location_id=pg.a.locations[0],
            source_stock_status="AVAILABLE",
            destination_stock_status="AVAILABLE",
        )
        await db.commit()
        return movement


async def _ledger_contains(pg, *, location_id: int, movement: InventoryMovement) -> None:
    async with pg.session(pg.a) as db:
        page = await ledger.get_warehouse_ledger_cursor(
            location_id,
            None,
            100,
            None,
            movement.reference_type,
            movement.reference_id,
            db,
            pg.a.ordinary.access(db),
        )
        assert movement.id in {row["id"] for row in page["items"]}


async def test_cp14b_batch_visibility_sellability_disposition_status_reservation_and_isolation(pg):
    await _prepare_cp14(pg, policy_days=31)
    a, b = pg.a, pg.b

    a1 = _item(await _batch_page(pg, a.locations[0]), a.batch_id)
    a2 = _item(await _batch_page(pg, a.locations[1]), a.batch_id)
    assert a1["batch_number"] == "LOT-OVERLAP"
    assert a1["minimum_remaining_shelf_life_days"] == 31
    assert a1["sellability_state"] == "NOT_SELLABLE"
    assert "MINIMUM_REMAINING_SHELF_LIFE_NOT_MET" in a1["sellability_reason_codes"]
    assert a2["minimum_remaining_shelf_life_days"] == 0
    assert a2["sellability_state"] == "SELLABLE"
    assert batch_metadata_is_sellable(
        as_of_date=(await _batch_page(pg, a.locations[0]))["as_of_date"],
        expiry_control_mode=a1["expiry_control_mode"],
        production_date=a1["production_date"],
        expiry_date=a1["expiry_date"],
        minimum_remaining_shelf_life_days=31,
        is_active=True,
        disposition=a1["disposition"],
    ) is False

    warn31 = _item(await _batch_page(pg, a.locations[0], warning_days=31), a.batch_id)
    warn365 = _item(await _batch_page(pg, a.locations[0], warning_days=365), a.batch_id)
    assert (warn31["sellability_state"], warn31["sellability_reason_codes"]) == (
        warn365["sellability_state"], warn365["sellability_reason_codes"]
    )
    expired = _item(await _batch_page(pg, a.locations[1]), a.expired_batch_id)
    assert expired["minimum_remaining_shelf_life_days"] == 0
    assert expired["sellability_state"] == "NOT_SELLABLE"
    assert expired["sellability_reason_codes"] == ["EXPIRED"]

    await _reserve(pg, batch_id=a.batch_id, quantity_value="3")
    async with pg.session(a) as db:
        source = await live_stock_source_detail.get_live_stock_batch_source(
            a.variant_id,
            a.batch_id,
            a.locations[0],
            db,
            a.ordinary.access(db),
        )
        available = next(row for row in source["statuses"] if row["stock_status"] == "AVAILABLE")
        assert available["on_hand_quantity"] == "20"
        assert available["reserved_quantity"] == "3"
        assert available["movable_quantity"] == "17"
        stock_sources = WarehouseBatchStockSourcesResponse.model_validate(
            await live_stock.get_batch_stock_sources(a.batch_id, db, a.ordinary.access(db))
        ).model_dump(mode="json")
        a1_source = next(row for row in stock_sources["sources"] if row["location_id"] == a.locations[0])
        a1_available = next(row for row in a1_source["statuses"] if row["stock_status"] == "AVAILABLE")
        assert Decimal(a1_available["on_hand_quantity"]) - Decimal(a1_available["reserved_quantity"]) == Decimal("17")

    blocked_payload = InventoryStatusChangeRequest(
        request_id=uuid4(),
        location_id=a.locations[0],
        product_variant_id=a.variant_id,
        batch_id=a.batch_id,
        uom_id=a.uom_id,
        source_status="AVAILABLE",
        destination_status="QUARANTINED",
        quantity="18",
        reason="CP14-B reservation protection",
    )
    async with pg.session(a) as db:
        with pytest.raises(HTTPException) as reserved:
            await transfers.change_inventory_status(
                blocked_payload,
                db,
                a.ordinary.access(db),
                a.ordinary.operational_driver,
            )
        assert reserved.value.status_code == 409

    status_payload = blocked_payload.model_copy(
        update={"request_id": uuid4(), "quantity": Decimal("2")}
    )
    async with pg.session(a) as db:
        changed = await transfers.change_inventory_status(
            status_payload,
            db,
            a.ordinary.access(db),
            a.ordinary.operational_driver,
        )
    async with pg.session(a) as db:
        replay = await transfers.change_inventory_status(
            status_payload,
            db,
            a.ordinary.access(db),
            a.ordinary.operational_driver,
        )
        assert replay == changed
    async with pg.session(a) as db:
        assert await _balance(db, a, location_id=a.locations[0], batch_id=a.batch_id, status="AVAILABLE") == (
            Decimal("18"), Decimal("3")
        )
        assert await _balance(db, a, location_id=a.locations[0], batch_id=a.batch_id, status="QUARANTINED") == (
            Decimal("2"), Decimal("0")
        )
        assert await _balance(db, a, location_id=a.locations[1], batch_id=a.batch_id, status="AVAILABLE") == (
            Decimal("20"), Decimal("0")
        )
    async with pg.session(a) as db:
        with pytest.raises(HTTPException) as mismatch:
            await transfers.change_inventory_status(
                status_payload.model_copy(update={"quantity": Decimal("1")}),
                db,
                a.ordinary.access(db),
                a.ordinary.operational_driver,
            )
        assert mismatch.value.status_code == 409
    async with pg.session(a) as db:
        with pytest.raises(HTTPException) as a2_denied:
            await transfers.change_inventory_status(
                status_payload.model_copy(
                    update={"request_id": uuid4(), "location_id": a.locations[1], "quantity": Decimal("1")}
                ),
                db,
                a.ordinary.access(db),
                a.ordinary.operational_driver,
            )
        assert a2_denied.value.status_code == 403

    async with pg.session(a) as db:
        batch = await db.get(ProductBatch, a.batch_id)
        initial_revision = int(batch.disposition_revision)
    disposition_payload = BatchDispositionChangeRequest(
        request_id=uuid4(),
        expected_revision=initial_revision,
        disposition="QUARANTINED",
        reason="CP14-B company-wide disposition",
    )
    async with pg.session(a) as db:
        with pytest.raises(HTTPException) as denied_operator:
            await transfers.change_batch_disposition(
                a.batch_id,
                disposition_payload,
                db,
                a.receiver.access(db),
                a.receiver.operational_driver,
            )
        assert denied_operator.value.status_code == 403
    async with pg.session(a) as db:
        disposition = await transfers.change_batch_disposition(
            a.batch_id,
            disposition_payload,
            db,
            a.ordinary.access(db),
            a.ordinary.operational_driver,
        )
    async with pg.session(a) as db:
        assert await transfers.change_batch_disposition(
            a.batch_id,
            disposition_payload,
            db,
            a.ordinary.access(db),
            a.ordinary.operational_driver,
        ) == disposition
    async with pg.session(a) as db:
        with pytest.raises(HTTPException) as changed_payload:
            await transfers.change_batch_disposition(
                a.batch_id,
                disposition_payload.model_copy(update={"disposition": "BLOCKED"}),
                db,
                a.ordinary.access(db),
                a.ordinary.operational_driver,
            )
        assert changed_payload.value.status_code == 409

    a1_after = _item(await _batch_page(pg, a.locations[0]), a.batch_id)
    a2_after = _item(await _batch_page(pg, a.locations[1]), a.batch_id)
    assert a1_after["disposition"] == a2_after["disposition"] == "QUARANTINED"
    assert a1_after["quarantined_quantity"] == "2"
    assert a2_after["quarantined_quantity"] == "0"

    errors = []
    for batch_id in (b.batch_id, 2147483647):
        async with pg.session(a) as db:
            with pytest.raises(HTTPException) as opaque:
                await transfers.change_batch_disposition(
                    batch_id,
                    BatchDispositionChangeRequest(
                        request_id=uuid4(),
                        expected_revision=1,
                        disposition="QUARANTINED",
                        reason="CP14-B opaque identity",
                    ),
                    db,
                    a.ordinary.access(db),
                    a.ordinary.operational_driver,
                )
            errors.append(_opaque_signature(opaque.value))
    assert errors[0] == errors[1]
    async with pg.session(b) as db:
        foreign = await db.get(ProductBatch, b.batch_id)
        assert foreign.disposition == "RELEASED"

    await _revoke(pg, "inventory.status_change")
    async with pg.session(a) as db:
        with pytest.raises(HTTPException) as revoked_status:
            await transfers.change_inventory_status(
                status_payload,
                db,
                a.ordinary.access(db),
                a.ordinary.operational_driver,
            )
        assert revoked_status.value.status_code == 403
    await _revoke(pg, "batch.disposition")
    async with pg.session(a) as db:
        with pytest.raises(HTTPException) as revoked_disposition:
            await transfers.change_batch_disposition(
                a.batch_id,
                disposition_payload,
                db,
                a.ordinary.access(db),
                a.ordinary.operational_driver,
            )
        assert revoked_disposition.value.status_code == 403


@pytest.mark.parametrize(
    "purpose,status",
    [
        ("QUARANTINE", "QUARANTINED"),
        ("RECALL_RETURN", "RECALLED"),
        ("RETURN_TO_VENDOR", "QUARANTINED"),
        ("DISPOSAL", "DISPOSAL_PENDING"),
    ],
)
async def test_cp14b_quality_staging_is_physical_internal_and_reservation_safe(pg, purpose, status):
    await _prepare_cp14(pg)
    a = pg.a
    await _reserve(pg, batch_id=a.expired_batch_id, quantity_value="19")
    blocked = special(a, purpose, quantity="2")
    if purpose == "RECALL_RETURN":
        async with pg.session(a) as db:
            (await db.get(ProductVariant, a.variant_id)).operational_hold = "RECALL"
            await db.commit()
    with pytest.raises(HTTPException) as reserved:
        await dispatch_special(pg, blocked)
    assert reserved.value.status_code == 409
    await _reserve(pg, batch_id=a.expired_batch_id, quantity_value="19", action="RELEASE")

    payload = special(a, purpose, quantity="4")
    sent = await dispatch_special(pg, payload)
    assert await dispatch_special(pg, payload) == sent
    with pytest.raises(HTTPException) as mismatch:
        await dispatch_special(pg, special(a, purpose, quantity="1", request_id=payload.request_id))
    assert mismatch.value.status_code == 409

    async with pg.session(a) as db:
        received = await transfers.unified_transfer_receive(
            UnifiedReceiveRequest(
                request_id=uuid4(),
                transfer_header_id=sent["header_id"],
                destination_location_id=a.quarantine_id,
            ),
            db,
            a.receiver.access(db),
            a.receiver.operational_driver,
        )
        assert received["status"] == "POSTED"
    assert await _company_quantity(pg, a) == Decimal("180")
    async with pg.session(a) as db:
        header = await db.get(InventoryTransferHeader, sent["header_id"])
        assert header.status == "POSTED" and header.transfer_purpose == purpose
        staged = await _balance(
            db,
            a,
            location_id=a.quarantine_id,
            batch_id=a.expired_batch_id,
            status=status,
        )
        assert staged == (Decimal("4"), Decimal("0"))
        movements = (
            await db.scalars(
                select(InventoryMovement).where(
                    InventoryMovement.company_id == a.company_id,
                    InventoryMovement.transfer_header_id == header.id,
                )
            )
        ).all()
        physical = [row for row in movements if row.movement_kind == "PHYSICAL"]
        status_changes = [row for row in movements if row.movement_kind == "STATUS_CHANGE"]
        assert len(physical) == 2
        assert len(status_changes) == 1
        assert {row.movement_kind for row in movements} == {"PHYSICAL", "STATUS_CHANGE"}
        assert all(row.destination_location_id is not None for row in physical)
        assert not any(row.destination_location_id is None for row in movements)
        received_movement = next(row for row in physical if row.destination_location_id == a.quarantine_id)
    await _ledger_contains(pg, location_id=a.quarantine_id, movement=received_movement)

    await _revoke(pg, "transfer.special." + purpose.lower())
    with pytest.raises(HTTPException) as revoked:
        await dispatch_special(pg, payload)
    assert revoked.value.status_code == 403


@pytest.mark.parametrize("action", ["DISPOSAL", "RETURN_TO_VENDOR"])
async def test_cp14b_terminal_exit_is_source_only_idempotent_atomic_provenanced_and_ledgered(pg, action):
    await _prepare_cp14(pg)
    a = pg.a
    sent = await stage(pg, action)
    before = await movement_snapshot(pg)
    payload = terminal_payload(pg, action)
    domain = disposal_domain if action == "DISPOSAL" else vendor_domain
    real = domain.apply_inventory_movements_batch

    async def fail_after_real_movement(*args, **kwargs):
        await real(*args, **kwargs)
        raise RuntimeError("CP14-B injected terminal rollback")

    with patch.object(domain, "apply_inventory_movements_batch", fail_after_real_movement):
        with pytest.raises(HTTPException) as rolled_back:
            await terminal(pg, action, payload)
        assert rolled_back.value.status_code == 500
    assert await _company_quantity(pg, a) == Decimal("180")
    assert await movement_snapshot(pg) == before

    first, duplicate = await asyncio.gather(terminal(pg, action, payload), terminal(pg, action, payload))
    assert first == duplicate == await terminal(pg, action, payload)
    assert first["origin_transfer_header_ids"] == [sent["header_id"]]
    assert await _company_quantity(pg, a) == Decimal("178")
    with pytest.raises(HTTPException) as mismatch:
        await terminal(pg, action, payload.model_copy(update={"quantity": Decimal("1")}))
    assert mismatch.value.status_code == 409

    async with pg.session(a) as db:
        header = await db.get(InventoryTransferHeader, sent["header_id"])
        assert header.status == "POSTED" and header.transfer_purpose == action
        exits = (
            await db.scalars(
                select(InventoryMovement).where(
                    InventoryMovement.company_id == a.company_id,
                    InventoryMovement.id.in_(first["movement_ids"]),
                )
            )
        ).all()
        assert len(exits) == 1
        exit_movement = exits[0]
        assert exit_movement.movement_kind == "PHYSICAL"
        assert exit_movement.source_location_id == a.quarantine_id
        assert exit_movement.destination_location_id is None
        assert exit_movement.quantity == Decimal("2")
        expected_reference = "FINAL_DISPOSAL" if action == "DISPOSAL" else "FINAL_VENDOR_HANDOVER"
        assert exit_movement.reference_type == expected_reference
    await _ledger_contains(pg, location_id=a.quarantine_id, movement=exit_movement)

    await _revoke(
        pg,
        "inventory.disposal.confirm" if action == "DISPOSAL" else "inventory.vendor_return.confirm",
    )
    with pytest.raises(HTTPException) as revoked:
        await terminal(pg, action, payload)
    assert revoked.value.status_code == 403


async def test_cp14b_normal_transfer_fefo_lifecycle_vehicle_scope_and_ledger_reconcile(pg):
    await _prepare_cp14(pg)
    a, b = pg.a, pg.b
    assert await _company_quantity(pg, a) == Decimal("180")
    await _reserve(pg, batch_id=a.batch_id, quantity_value="3")

    auto = dispatch_payload(
        a,
        request_id=uuid4(),
        items=[dict(product_variant_id=a.variant_id, quantity="4", uom_id=a.uom_id)],
    )
    sent = await send(pg, auto)
    assert await send(pg, auto) == sent
    with pytest.raises(HTTPException) as mismatch:
        await send(pg, auto.model_copy(update={"notes": "changed payload"}))
    assert mismatch.value.status_code == 409
    async with pg.session(a) as db:
        line = await db.scalar(
            select(InventoryTransferLine).where(
                InventoryTransferLine.company_id == a.company_id,
                InventoryTransferLine.transfer_header_id == sent["header_id"],
            )
        )
        assert line.batch_id == a.batch_id
        assert await _balance(db, a, location_id=a.locations[0], batch_id=a.batch_id, status="AVAILABLE") == (
            Decimal("16"), Decimal("3")
        )

    receive_payload = UnifiedReceiveRequest(
        request_id=uuid4(),
        transfer_header_id=sent["header_id"],
        destination_location_id=a.locations[1],
    )
    async with pg.session(a) as db:
        received = await transfers.unified_transfer_receive(
            receive_payload,
            db,
            a.receiver.access(db),
            a.receiver.operational_driver,
        )
    async with pg.session(a) as db:
        assert await transfers.unified_transfer_receive(
            receive_payload,
            db,
            a.receiver.access(db),
            a.receiver.operational_driver,
        ) == received
    async with pg.session(a) as db:
        assert await _balance(db, a, location_id=a.locations[1], batch_id=a.batch_id, status="AVAILABLE") == (
            Decimal("24"), Decimal("0")
        )
        movements = (
            await db.scalars(
                select(InventoryMovement).where(
                    InventoryMovement.company_id == a.company_id,
                    InventoryMovement.transfer_header_id == sent["header_id"],
                )
            )
        ).all()
        assert len(movements) == 2 and all(row.movement_kind == "PHYSICAL" for row in movements)
        dispatch_movement = next(row for row in movements if row.source_location_id == a.locations[0])
        receive_movement = next(row for row in movements if row.destination_location_id == a.locations[1])
    await _ledger_contains(pg, location_id=a.locations[0], movement=dispatch_movement)
    await _ledger_contains(pg, location_id=a.locations[1], movement=receive_movement)
    assert await _company_quantity(pg, a) == Decimal("180")

    for action in ("reject", "cancel"):
        transfer = await send(pg, dispatch_payload(a, items=[dict(product_variant_id=a.variant_id, quantity="2", uom_id=a.uom_id)]))
        async with pg.session(a) as db:
            if action == "reject":
                result = await transfers.unified_transfer_reject(
                    transfer["header_id"],
                    UnifiedTransferDecisionRequest(request_id=uuid4(), decision_reason="CP14-B reject"),
                    db,
                    a.receiver.access(db),
                    a.receiver.operational_driver,
                )
                assert result["status"] == "REJECTED"
            else:
                result = await transfers.unified_transfer_cancel(
                    transfer["header_id"],
                    UnifiedTransferDecisionRequest(request_id=uuid4(), decision_reason="CP14-B cancel"),
                    db,
                    a.ordinary.access(db),
                    a.ordinary.operational_driver,
                )
                assert result["status"] == "CANCELLED"
        async with pg.session(a) as db:
            rows = (
                await db.scalars(
                    select(InventoryMovement).where(
                        InventoryMovement.company_id == a.company_id,
                        InventoryMovement.transfer_header_id == transfer["header_id"],
                    )
                )
            ).all()
            assert len(rows) == 2
            returned = next(row for row in rows if row.destination_location_id == a.locations[0])
        await _ledger_contains(pg, location_id=a.locations[0], movement=returned)
        assert await _company_quantity(pg, a) == Decimal("180")

    override = dispatch_payload(
        a,
        items=[dict(
            product_variant_id=a.variant_id,
            quantity="2",
            uom_id=a.uom_id,
            is_fefo_override=True,
            override_batch_id=a.later_batch_id,
            override_reason_id=a.reason_id,
        )],
    )
    overridden = await send(pg, override)
    async with pg.session(a) as db:
        line = await db.scalar(select(InventoryTransferLine).where(
            InventoryTransferLine.company_id == a.company_id,
            InventoryTransferLine.transfer_header_id == overridden["header_id"],
        ))
        assert line.batch_id == a.later_batch_id
        assert line.fefo_override_reason_id == a.reason_id

    with pytest.raises(HTTPException) as vehicle_direction:
        await send(pg, dispatch_payload(a, destination_location_id=a.vehicle_location_id), a.owner)
    assert vehicle_direction.value.detail["code"] == "TRANSFER_DIRECTION_BLOCKED"
    vehicle_command = special(
        a,
        "QUARANTINE",
        quantity="2",
        source_location_id=a.vehicle_location_id,
    )
    with pytest.raises(HTTPException) as vehicle_scope:
        await dispatch_special(pg, vehicle_command)
    assert vehicle_scope.value.status_code == 403
    async with pg.session(a) as db:
        vehicle_sent = await transfers.special_transfer_dispatch(
            vehicle_command,
            db,
            a.owner.access(db),
            a.owner.operational_driver,
        )
    async with pg.session(a) as db:
        await transfers.unified_transfer_receive(
            UnifiedReceiveRequest(
                request_id=uuid4(),
                transfer_header_id=vehicle_sent["header_id"],
                destination_location_id=a.quarantine_id,
            ),
            db,
            a.receiver.access(db),
            a.receiver.operational_driver,
        )
        assert await _balance(
            db,
            a,
            location_id=a.vehicle_location_id,
            batch_id=a.expired_batch_id,
            status="AVAILABLE",
        ) == (Decimal("18"), Decimal("0"))
        assert await _balance(
            db,
            a,
            location_id=a.quarantine_id,
            batch_id=a.expired_batch_id,
            status="QUARANTINED",
        ) == (Decimal("2"), Decimal("0"))
    assert await _company_quantity(pg, a) == Decimal("180")

    errors = []
    for destination in (b.locations[0], 2147483647):
        with pytest.raises(HTTPException) as opaque:
            await send(pg, dispatch_payload(a, destination_location_id=destination), a.owner)
        errors.append(_opaque_signature(opaque.value))
    assert errors[0] == errors[1]
    vehicle_errors = []
    for source in (b.vehicle_location_id, 2147483647):
        command = special(a, "QUARANTINE", quantity="1", source_location_id=source)
        async with pg.session(a) as db:
            with pytest.raises(HTTPException) as opaque:
                await transfers.special_transfer_dispatch(
                    command,
                    db,
                    a.owner.access(db),
                    a.owner.operational_driver,
                )
            vehicle_errors.append(_opaque_signature(opaque.value))
    assert vehicle_errors[0] == vehicle_errors[1]
    assert await _company_quantity(pg, b) == Decimal("120")

    await _revoke(pg, "inventory.fefo_override")
    with pytest.raises(HTTPException) as revoked_override:
        await send(pg, override)
    assert revoked_override.value.status_code == 403
    await _revoke(pg, "transfer.send")
    with pytest.raises(HTTPException) as revoked_send:
        await send(pg, auto)
    assert revoked_send.value.status_code == 403


async def test_cp14b_concurrent_commands_cannot_overconsume_and_transfer_races_quantity_action(pg):
    await _prepare_cp14(pg)
    a = pg.a
    before_movements = await _movement_count(pg, a)

    def exact_batch_payload(batch_id: int, quantity_value: str):
        return dispatch_payload(
            a,
            request_id=uuid4(),
            items=[dict(
                product_variant_id=a.variant_id,
                quantity=quantity_value,
                uom_id=a.uom_id,
                is_fefo_override=True,
                override_batch_id=batch_id,
                override_reason_id=a.reason_id,
            )],
        )

    first, second = await asyncio.gather(
        send(pg, exact_batch_payload(a.batch_id, "15")),
        send(pg, exact_batch_payload(a.batch_id, "15")),
        return_exceptions=True,
    )
    results = [first, second]
    assert sum(isinstance(row, dict) for row in results) == 1
    failure = next(row for row in results if not isinstance(row, dict))
    assert isinstance(failure, HTTPException) and failure.status_code == 409
    async with pg.session(a) as db:
        on_hand, reserved = await _balance(
            db,
            a,
            location_id=a.locations[0],
            batch_id=a.batch_id,
            status="AVAILABLE",
        )
        assert on_hand == Decimal("5") and reserved == Decimal("0")
        assert on_hand - reserved >= 0
    assert await _movement_count(pg, a) == before_movements + 1
    assert await _company_quantity(pg, a) == Decimal("180")

    transfer_payload = exact_batch_payload(a.later_batch_id, "15")
    status_payload = InventoryStatusChangeRequest(
        request_id=uuid4(),
        location_id=a.locations[0],
        product_variant_id=a.variant_id,
        batch_id=a.later_batch_id,
        uom_id=a.uom_id,
        source_status="AVAILABLE",
        destination_status="QUARANTINED",
        quantity="10",
        reason="CP14-B transfer/status race",
    )

    async def status_change():
        async with pg.session(a) as db:
            return await transfers.change_inventory_status(
                status_payload,
                db,
                a.ordinary.access(db),
                a.ordinary.operational_driver,
            )

    before_race = await _movement_count(pg, a)
    transfer_result, status_result = await asyncio.gather(
        send(pg, transfer_payload),
        status_change(),
        return_exceptions=True,
    )
    race = [transfer_result, status_result]
    assert sum(isinstance(row, dict) for row in race) == 1
    failure = next(row for row in race if not isinstance(row, dict))
    assert isinstance(failure, HTTPException) and failure.status_code == 409
    assert await _movement_count(pg, a) == before_race + 1
    async with pg.session(a) as db:
        available, reserved = await _balance(
            db,
            a,
            location_id=a.locations[0],
            batch_id=a.later_batch_id,
            status="AVAILABLE",
        )
        quarantined, _ = await _balance(
            db,
            a,
            location_id=a.locations[0],
            batch_id=a.later_batch_id,
            status="QUARANTINED",
        )
        assert available >= 0 and reserved >= 0 and quarantined >= 0
        assert available + quarantined in {Decimal("5"), Decimal("20")}
    assert await _company_quantity(pg, a) == Decimal("180")


@pytest.mark.parametrize("action", ["DISPOSAL", "RETURN_TO_VENDOR"])
async def test_cp14b_two_terminal_consumers_same_staging_origin_have_one_winner(pg, action):
    await _prepare_cp14(pg)
    a = pg.a
    sent = await stage(pg, action)
    first, second = await asyncio.gather(
        terminal(pg, action, terminal_payload(pg, action, quantity="3")),
        terminal(pg, action, terminal_payload(pg, action, quantity="3")),
        return_exceptions=True,
    )
    results = [first, second]
    assert sum(isinstance(row, dict) for row in results) == 1
    failure = next(row for row in results if not isinstance(row, dict))
    assert isinstance(failure, HTTPException) and failure.status_code == 409
    winner = next(row for row in results if isinstance(row, dict))
    assert winner["origin_transfer_header_ids"] == [sent["header_id"]]
    assert await _company_quantity(pg, a) == Decimal("177")
    async with pg.session(a) as db:
        status = "DISPOSAL_PENDING" if action == "DISPOSAL" else "QUARANTINED"
        remaining = await _balance(
            db,
            a,
            location_id=a.quarantine_id,
            batch_id=a.expired_batch_id,
            status=status,
        )
        assert remaining == (Decimal("1"), Decimal("0"))
        exits = (
            await db.scalars(
                select(InventoryMovement).where(
                    InventoryMovement.company_id == a.company_id,
                    InventoryMovement.transfer_header_id == sent["header_id"],
                    InventoryMovement.destination_location_id.is_(None),
                )
            )
        ).all()
        assert len(exits) == 1 and exits[0].quantity == Decimal("3")


@pytest.mark.parametrize("method", ["MOVING_AVERAGE", "FIFO"])
@pytest.mark.parametrize("action", ["DISPOSAL", "RETURN_TO_VENDOR"])
async def test_cp14b_cost_value_internal_move_vs_terminal_exit(pg, method, action):
    await _accepted_cost_path(pg, method, action)
