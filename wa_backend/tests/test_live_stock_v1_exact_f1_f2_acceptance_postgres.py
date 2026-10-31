"""Exact remaining Live Stock V1 F1/F2 numeric acceptance.

This intentionally reuses the accepted #615/#658 production authorities without
re-running their full suites. Inventory quantities are created only through real
inbound/status/reservation operations; no InventoryBalance quantity is seeded or
updated directly.
"""
from __future__ import annotations

import json
import os
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text

from api import catalog, inventory_stock_policy as stock_policy
from api.warehouse import live_stock, live_stock_source_detail, transfers
from models import (
    InventoryBalance,
    InventoryCostEvent,
    InventoryLiveStockProjection,
    InventoryMovement,
    OperationIdempotency,
    ProductVariant,
)
from schemas import InventoryStatusChangeRequest
from services import apply_inventory_movements_batch
from tests.test_cp7_live_stock_postgres import _grant_inventory_read
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_live_stock_source_action_policy_postgres import _action
from tests.test_live_stock_v1_safety_sales_policy_postgres import (
    _batch_id,
    _catalog_command,
)


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_EXACT_F1_F2_PG_GATE") != "1",
        reason="Explicit disposable PostgreSQL 16 exact F1/F2 gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


# Independent numeric expectations are frozen before any operation executes.
F1_ON_HAND = Decimal("10")
F1_RESERVED = Decimal("2")
F1_SELLABLE = Decimal("8")
F1_UNAVAILABLE_ACTIVE = Decimal("0")
F1_UNAVAILABLE_BLOCKED = Decimal("8")
F1_MINIMUM = Decimal("8")
F2_QUARANTINED = Decimal("10")
F2_RELEASE_ATTEMPT = Decimal("10")
UNIT_COST = Decimal("2")

assert F1_ON_HAND == F1_RESERVED + F1_SELLABLE + F1_UNAVAILABLE_ACTIVE
assert F1_ON_HAND == F1_RESERVED + Decimal("0") + F1_UNAVAILABLE_BLOCKED
assert F2_QUARANTINED == Decimal("10")
assert F2_RELEASE_ATTEMPT == F2_QUARANTINED


def _list_kwargs(tenant, db, access, *, location_id=None):
    return dict(
        location_id=location_id or tenant.location_id,
        cursor=None,
        limit=50,
        search=None,
        only_alerts=False,
        stock_state="all",
        family_id=None,
        has_reserved=False,
        has_unavailable=False,
        has_damaged=False,
        has_recalled=False,
        has_vehicle=False,
        minimum_unset=False,
        sort="name_asc",
        db=db,
        access=access,
    )


async def _assert_runtime_rls(pg_gate) -> None:
    async with pg_gate.runtime_engine.connect() as connection:
        identity = (
            await connection.execute(
                text(
                    "SELECT current_database(), current_user, "
                    "current_setting('server_version_num')::int, "
                    "r.rolsuper, r.rolbypassrls "
                    "FROM pg_roles r WHERE r.rolname=current_user"
                )
            )
        ).one()
        assert identity.current_database == "wanasah_no_lot_contract_test"
        assert identity.current_user == "wanasah_app"
        assert 160000 <= int(identity[2]) < 170000
        assert bool(identity.rolsuper) is False
        assert bool(identity.rolbypassrls) is False
        for table in (
            "product_variants",
            "product_batches",
            "inventory_balances",
            "inventory_movements",
            "operation_idempotency",
            "inventory_live_stock_projection",
        ):
            flags = (
                await connection.execute(
                    text(
                        "SELECT relrowsecurity, relforcerowsecurity "
                        "FROM pg_class WHERE oid=to_regclass(:table)"
                    ),
                    {"table": table},
                )
            ).one()
            assert tuple(flags) == (True, True), table


async def _grant_restricted_reader(pg_gate, tenant) -> None:
    async with pg_gate.admin_engine.begin() as connection:
        from sqlalchemy.ext.asyncio import AsyncSession

        seed = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            await seed.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(tenant.company_id)},
            )
            await _grant_inventory_read(seed, tenant, tenant.location_id)
            await seed.flush()
        finally:
            await seed.close()


async def _post_exact_batch(pg_gate, tenant, *, prefix: str, quantity: Decimal) -> int:
    lot = f"{prefix}-{uuid4().hex[:12]}"
    request = pg_gate.request(
        lot=lot,
        quantity=format(quantity, "f"),
        cost=format(UNIT_COST, "f"),
    )
    async with pg_gate.session() as db:
        assert await pg_gate.post(db, request) == {"message": "INBOUND_POSTED"}
    return await _batch_id(pg_gate, tenant, lot)


async def _reserve_exact(pg_gate, tenant, batch_id: int, quantity: Decimal) -> None:
    async with pg_gate.session() as db:
        await apply_inventory_movements_batch(
            db,
            company_id=tenant.company_id,
            performed_by=tenant.owner.driver_id,
            movements=[
                {
                    "product_variant_id": tenant.variant_id,
                    "batch_id": batch_id,
                    "quantity": quantity,
                    "movement_kind": "RESERVATION",
                    "reservation_action": "RESERVE",
                    "source_location_id": tenant.location_id,
                    "destination_location_id": tenant.location_id,
                    "source_stock_status": "AVAILABLE",
                    "destination_stock_status": "AVAILABLE",
                    "reference_type": "EXACT_F1_RESERVE",
                    "reference_id": "EXACT-F1-10-2",
                    "idempotency_key": "EXACT-F1-10-2",
                }
            ],
        )
        await db.commit()


async def _set_minimum_exact(pg_gate, tenant) -> None:
    async with pg_gate.session() as db:
        result = await stock_policy.update_minimum_stock(
            tenant.variant_id,
            stock_policy.MinimumStockUpdateRequest(
                request_id=uuid4(),
                location_id=tenant.location_id,
                uom_id=tenant.uom_id,
                minimum_quantity=F1_MINIMUM,
                expected_minimum_quantity=Decimal("0"),
            ),
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )
        assert Decimal(result["minimum_quantity"]) == F1_MINIMUM


async def _read_surfaces(pg_gate, tenant, batch_id: int, identity):
    async with pg_gate.session() as db:
        access = identity.access(db)
        page = await live_stock.get_warehouse_inventory(
            **_list_kwargs(tenant, db, access)
        )
        row = next(
            item for item in page["items"]
            if int(item["id"]) == int(tenant.variant_id)
        )
        detail = await live_stock.get_warehouse_inventory_batches(
            tenant.variant_id,
            tenant.location_id,
            None,
            100,
            db,
            access,
        )
        batch = next(
            item for item in detail["batches"]
            if int(item["batch_id"]) == int(batch_id)
        )
        source = await live_stock.get_batch_stock_sources(
            batch_id,
            db,
            access,
        )
        source_row = next(
            item for item in source["sources"]
            if int(item["location_id"]) == int(tenant.location_id)
        )
        return row, batch, source, source_row


def _status(source_row: dict, name: str) -> dict:
    return next(
        item for item in source_row["statuses"]
        if item["stock_status"] == name
    )


async def _assert_f1_state(
    pg_gate,
    tenant,
    batch_id: int,
    *,
    expected_sellable: Decimal,
    expected_unavailable: Decimal,
    expected_low_stock: bool,
    expected_hold: str,
) -> None:
    for identity in (tenant.owner, tenant.ordinary):
        row, batch, source, source_row = await _read_surfaces(
            pg_gate, tenant, batch_id, identity
        )
        assert int(source["batch_id"]) == batch_id
        assert int(source["product_variant_id"]) == tenant.variant_id
        assert source["operational_hold"] == expected_hold
        assert [int(item["location_id"]) for item in source["sources"]] == [
            tenant.location_id
        ]

        available = _status(source_row, "AVAILABLE")
        assert Decimal(row["on_hand_quantity"]) == F1_ON_HAND
        assert Decimal(row["reserved_quantity"]) == F1_RESERVED
        assert Decimal(row["available_for_sale_quantity"]) == expected_sellable
        assert Decimal(row["unavailable_quantity"]) == expected_unavailable
        assert Decimal(row["minimum_quantity"]) == F1_MINIMUM
        assert bool(row["is_low_stock"]) is expected_low_stock

        assert Decimal(batch["on_hand_quantity"]) == F1_ON_HAND
        assert Decimal(batch["reserved_quantity"]) == F1_RESERVED
        assert Decimal(batch["available_for_sale_quantity"]) == expected_sellable
        assert Decimal(batch["unavailable_quantity"]) == expected_unavailable
        assert (
            Decimal(batch["reserved_quantity"])
            + Decimal(batch["available_for_sale_quantity"])
            + Decimal(batch["unavailable_quantity"])
            == F1_ON_HAND
        )

        assert Decimal(available["on_hand_quantity"]) == F1_ON_HAND
        assert Decimal(available["reserved_quantity"]) == F1_RESERVED
        assert Decimal(available["movable_quantity"]) == F1_SELLABLE


async def test_f1_exact_10_reserved_2_list_batch_source_and_policy_signals(pg):
    await _assert_runtime_rls(pg)
    tenant = pg.tenants[0]
    await _grant_restricted_reader(pg, tenant)

    batch_id = await _post_exact_batch(
        pg, tenant, prefix="EXACT-F1", quantity=F1_ON_HAND
    )
    await _reserve_exact(pg, tenant, batch_id, F1_RESERVED)
    await _set_minimum_exact(pg, tenant)

    # ACTIVE/NONE: 10 physical = 2 reserved + 8 sellable + 0 unavailable.
    await _assert_f1_state(
        pg,
        tenant,
        batch_id,
        expected_sellable=F1_SELLABLE,
        expected_unavailable=F1_UNAVAILABLE_ACTIVE,
        expected_low_stock=True,
        expected_hold="NONE",
    )

    # RETIRING: same physical/reservation truth, zero sellable and exactly 8
    # unavailable. Low-stock is intentionally false because policy alerts only
    # apply to ACTIVE/NONE product authority.
    await _catalog_command(
        pg, tenant, catalog.retire_variant, "Exact F1 retiring 10/2 proof"
    )
    await _assert_f1_state(
        pg,
        tenant,
        batch_id,
        expected_sellable=Decimal("0"),
        expected_unavailable=F1_UNAVAILABLE_BLOCKED,
        expected_low_stock=False,
        expected_hold="NONE",
    )

    await _catalog_command(
        pg, tenant, catalog.restore_variant, "Exact F1 restore before hold"
    )
    await _catalog_command(
        pg,
        tenant,
        catalog.place_variant_sales_hold,
        "Exact F1 sales hold 10/2 proof",
    )
    await _assert_f1_state(
        pg,
        tenant,
        batch_id,
        expected_sellable=Decimal("0"),
        expected_unavailable=F1_UNAVAILABLE_BLOCKED,
        expected_low_stock=False,
        expected_hold="SALES_HOLD",
    )

    await _catalog_command(
        pg,
        tenant,
        catalog.release_variant_sales_hold,
        "Exact F1 release hold before recall",
    )
    await _catalog_command(
        pg, tenant, catalog.recall_variant, "Exact F1 recall 10/2 proof"
    )
    await _assert_f1_state(
        pg,
        tenant,
        batch_id,
        expected_sellable=Decimal("0"),
        expected_unavailable=F1_UNAVAILABLE_BLOCKED,
        expected_low_stock=False,
        expected_hold="RECALL",
    )

    # Same-company restricted reader is authorized only for the chosen
    # warehouse; the other warehouse remains inaccessible.
    async with pg.session() as db:
        with pytest.raises(HTTPException) as denied:
            await live_stock.get_warehouse_inventory(
                **_list_kwargs(
                    tenant,
                    db,
                    tenant.ordinary.access(db),
                    location_id=tenant.other_location_id,
                )
            )
        assert denied.value.status_code == 403

    print(
        "EXACT_F1_PASS "
        + json.dumps(
            {
                "on_hand": "10",
                "reserved": "2",
                "active_sellable": "8",
                "blocked_sellable": "0",
                "blocked_unavailable": "8",
                "minimum": "8",
                "states": [
                    "ACTIVE/NONE",
                    "RETIRING/NONE",
                    "ACTIVE/SALES_HOLD",
                    "ACTIVE/RECALL",
                ],
                "readers": ["owner", "restricted_authorized_warehouse"],
            },
            sort_keys=True,
        ),
        flush=True,
    )


async def _status_change(
    pg_gate,
    tenant,
    *,
    batch_id: int,
    source: str,
    destination: str,
    quantity: Decimal,
    request_id: UUID,
):
    payload = InventoryStatusChangeRequest(
        request_id=request_id,
        location_id=tenant.location_id,
        product_variant_id=tenant.variant_id,
        batch_id=batch_id,
        uom_id=tenant.uom_id,
        source_status=source,
        destination_status=destination,
        quantity=quantity,
        reason=f"Exact F2 {source}->{destination} quantity={quantity}",
    )
    async with pg_gate.session() as db:
        return await transfers.change_inventory_status(
            payload,
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )


async def _f2_fingerprint(pg_gate, tenant, batch_id: int) -> dict:
    async with pg_gate.session() as db:
        balances = (
            await db.execute(
                select(
                    InventoryBalance.stock_status,
                    InventoryBalance.on_hand_quantity,
                    InventoryBalance.reserved_quantity,
                )
                .where(
                    InventoryBalance.company_id == tenant.company_id,
                    InventoryBalance.location_id == tenant.location_id,
                    InventoryBalance.product_variant_id == tenant.variant_id,
                    InventoryBalance.batch_id == batch_id,
                )
                .order_by(InventoryBalance.stock_status)
            )
        ).all()
        movements = (
            await db.execute(
                select(
                    InventoryMovement.id,
                    InventoryMovement.movement_kind,
                    InventoryMovement.source_stock_status,
                    InventoryMovement.destination_stock_status,
                    InventoryMovement.quantity,
                    InventoryMovement.reference_type,
                    InventoryMovement.reference_id,
                )
                .where(
                    InventoryMovement.company_id == tenant.company_id,
                    InventoryMovement.product_variant_id == tenant.variant_id,
                    InventoryMovement.batch_id == batch_id,
                )
                .order_by(InventoryMovement.id)
            )
        ).all()
        projection = await db.scalar(
            select(InventoryLiveStockProjection).where(
                InventoryLiveStockProjection.company_id == tenant.company_id,
                InventoryLiveStockProjection.warehouse_location_id
                == tenant.location_id,
                InventoryLiveStockProjection.product_variant_id
                == tenant.variant_id,
            )
        )
        return {
            "balances": tuple(
                (str(row[0]), Decimal(row[1]), Decimal(row[2]))
                for row in balances
            ),
            "movements": tuple(
                (
                    int(row[0]),
                    str(row[1]),
                    row[2],
                    row[3],
                    Decimal(row[4]),
                    str(row[5]),
                    str(row[6]),
                )
                for row in movements
            ),
            "cost_events": int(
                await db.scalar(
                    select(func.count())
                    .select_from(InventoryCostEvent)
                    .where(
                        InventoryCostEvent.company_id == tenant.company_id,
                        InventoryCostEvent.product_variant_id
                        == tenant.variant_id,
                        InventoryCostEvent.batch_id == batch_id,
                    )
                )
                or 0
            ),
            "projection": (
                Decimal(projection.warehouse_on_hand),
                Decimal(projection.warehouse_reserved),
                Decimal(projection.blocked_status_packs),
                Decimal(projection.recalled_packs),
                Decimal(projection.damaged_packs),
                str(projection.lifecycle_status),
                str(projection.operational_hold),
                bool(projection.is_low_stock),
            )
            if projection is not None
            else None,
        }


async def _assert_no_rejected_command_rows(
    pg_gate,
    tenant,
    request_id: UUID,
) -> None:
    async with pg_gate.session() as db:
        movement = await db.scalar(
            select(InventoryMovement.id).where(
                InventoryMovement.company_id == tenant.company_id,
                InventoryMovement.reference_type == "STATUS_RECLASSIFICATION",
                InventoryMovement.reference_id == str(request_id),
            )
        )
        idem = await db.scalar(
            select(OperationIdempotency.id).where(
                OperationIdempotency.company_id == tenant.company_id,
                OperationIdempotency.operation == "INVENTORY_STATUS_CHANGE",
                OperationIdempotency.request_id == str(request_id),
            )
        )
        assert movement is None
        assert idem is None


async def _assert_f2_source(pg_gate, tenant, batch_id: int, identity) -> None:
    async with pg_gate.session() as db:
        access = identity.access(db)
        source = await live_stock.get_batch_stock_sources(
            batch_id,
            db,
            access,
        )
        assert source["batch_id"] == batch_id
        assert source["product_variant_id"] == tenant.variant_id
        assert [int(item["location_id"]) for item in source["sources"]] == [
            tenant.location_id
        ]
        quarantined = _status(source["sources"][0], "QUARANTINED")
        assert Decimal(quarantined["on_hand_quantity"]) == F2_QUARANTINED
        assert Decimal(quarantined["reserved_quantity"]) == Decimal("0")
        assert Decimal(quarantined["movable_quantity"]) == F2_QUARANTINED


async def _deny_exact_quarantine_release(
    pg_gate,
    tenant,
    batch_id: int,
    *,
    expected_code: str,
) -> None:
    async with pg_gate.session() as db:
        advice = await live_stock_source_detail.get_live_stock_batch_source(
            tenant.variant_id,
            batch_id,
            tenant.location_id,
            db,
            tenant.owner.access(db),
        )
    release = _action(advice, "QUARANTINED", "AVAILABLE")
    assert release["eligible_quantity"] == "10"
    assert release["allowed"] is False
    assert release["reason_code"] == expected_code

    before = await _f2_fingerprint(pg_gate, tenant, batch_id)
    denied_request = uuid4()
    with pytest.raises(HTTPException) as rejected:
        await _status_change(
            pg_gate,
            tenant,
            batch_id=batch_id,
            source="QUARANTINED",
            destination="AVAILABLE",
            quantity=F2_RELEASE_ATTEMPT,
            request_id=denied_request,
        )
    assert rejected.value.status_code == 409
    assert rejected.value.detail["code"] == expected_code

    after = await _f2_fingerprint(pg_gate, tenant, batch_id)
    assert after == before
    await _assert_no_rejected_command_rows(pg_gate, tenant, denied_request)


async def test_f2_exact_quarantined_10_hold_recall_denial_audit_and_rollback(pg):
    await _assert_runtime_rls(pg)
    tenant = pg.tenants[0]
    await _grant_restricted_reader(pg, tenant)

    batch_id = await _post_exact_batch(
        pg, tenant, prefix="EXACT-F2", quantity=F2_QUARANTINED
    )
    quarantine_request = uuid4()
    changed = await _status_change(
        pg,
        tenant,
        batch_id=batch_id,
        source="AVAILABLE",
        destination="QUARANTINED",
        quantity=F2_QUARANTINED,
        request_id=quarantine_request,
    )
    assert changed["source_status"] == "AVAILABLE"
    assert changed["destination_status"] == "QUARANTINED"

    # Persisted movement ledger is the audit evidence for the real transition.
    async with pg.session() as db:
        audit = await db.scalar(
            select(InventoryMovement).where(
                InventoryMovement.company_id == tenant.company_id,
                InventoryMovement.reference_type == "STATUS_RECLASSIFICATION",
                InventoryMovement.reference_id == str(quarantine_request),
            )
        )
        assert audit is not None
        assert audit.movement_kind == "STATUS_CHANGE"
        assert audit.source_stock_status == "AVAILABLE"
        assert audit.destination_stock_status == "QUARANTINED"
        assert Decimal(audit.quantity) == F2_QUARANTINED

    for identity in (tenant.owner, tenant.ordinary):
        await _assert_f2_source(pg, tenant, batch_id, identity)

    # Exact authorized-vs-restricted location boundary.
    async with pg.session() as db:
        with pytest.raises(HTTPException) as hidden:
            await live_stock_source_detail.get_live_stock_batch_source(
                tenant.variant_id,
                batch_id,
                tenant.other_location_id,
                db,
                tenant.ordinary.access(db),
            )
        assert hidden.value.status_code in {403, 404}

    await _catalog_command(
        pg,
        tenant,
        catalog.place_variant_sales_hold,
        "Exact F2 SALES_HOLD quarantine=10",
    )
    await _deny_exact_quarantine_release(
        pg,
        tenant,
        batch_id,
        expected_code="PRODUCT_SALES_HOLD",
    )
    await _assert_f2_source(pg, tenant, batch_id, tenant.ordinary)

    await _catalog_command(
        pg,
        tenant,
        catalog.release_variant_sales_hold,
        "Exact F2 release hold before recall",
    )
    await _catalog_command(
        pg,
        tenant,
        catalog.recall_variant,
        "Exact F2 RECALL quarantine=10",
    )
    await _deny_exact_quarantine_release(
        pg,
        tenant,
        batch_id,
        expected_code="PRODUCT_RECALLED",
    )
    await _assert_f2_source(pg, tenant, batch_id, tenant.ordinary)

    final = await _f2_fingerprint(pg, tenant, batch_id)
    assert final["balances"] == (
        ("AVAILABLE", Decimal("0"), Decimal("0")),
        ("QUARANTINED", Decimal("10"), Decimal("0")),
    )
    assert sum((row[1] for row in final["balances"]), Decimal("0")) == F2_QUARANTINED
    assert final["cost_events"] == 1

    print(
        "EXACT_F2_PASS "
        + json.dumps(
            {
                "quarantined": "10",
                "release_attempt": "10",
                "denials": ["PRODUCT_SALES_HOLD", "PRODUCT_RECALLED"],
                "successful_status_audit": "STATUS_RECLASSIFICATION",
                "rejected_movement_rows": 0,
                "rejected_idempotency_rows": 0,
                "readers": ["owner", "restricted_authorized_warehouse"],
                "rollback": True,
            },
            sort_keys=True,
        ),
        flush=True,
    )
