"""PostgreSQL 16 receiver-confirmed representative custody/financial gate acceptance.

Uses only the dedicated disposable CP14-C fixture DB and restricted runtime
role. No direct InventoryBalance writes; physical facts use the movement engine.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api import dispatch, representative_settlement as settlement
from models import (
    Company, DispatchRoute, InventoryBalance, InventoryLocation, InventoryMovement,
    Product, ProductBatch, ProductLocation, ProductVariant,
    StocktakeCountAttemptLine, StocktakeSession, SystemAuditLog, UOM, Vehicle,
    WorkSession, Zone, utc_now,
)
from schemas import SettleSessionRequest
from services import apply_inventory_movement
from tests.canonical_actor_fixtures import seed_ordinary_backoffice_fixture
from tests.test_cp14c_stocktake_lifecycle_postgres import (
    _checked_urls, _ensure_permissions, _grant_company, _grant_location,
    _runtime_session,
)

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CP14C_PG_GATE") != "1",
        reason="Only dedicated disposable CP14-C PostgreSQL gate is allowed",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]

ACTOR_PASSWORD = "CP15ReceiverSynthetic123"
LOCATION_CODES = (
    "inventory.read", "transfer.send", "stocktake.start", "stocktake.count",
    "stocktake.read", "stocktake.review", "stocktake.approve", "stocktake.recount",
)
RECEIVING_CODES = ("transfer.destination", "inventory.read")


async def _qty(db, company_id, location_id, batch_id, stock_status):
    return Decimal((await db.scalar(
        select(InventoryBalance.on_hand_quantity).where(
            InventoryBalance.company_id == company_id,
            InventoryBalance.location_id == location_id,
            InventoryBalance.batch_id == batch_id,
            InventoryBalance.stock_status == stock_status,
        )
    )) or 0)


async def _seed(admin_engine):
    async with AsyncSession(admin_engine, expire_on_commit=False) as db:
        await _ensure_permissions(db, set(LOCATION_CODES + RECEIVING_CODES + (
            "settlement.read", "settlement.execute",
        )))
        uom = await db.scalar(select(UOM).where(UOM.code == "EACH"))
        if uom is None:
            uom = UOM(code="EACH", name="Each")
            db.add(uom)
            await db.flush()
        company = Company(
            name="CP15 Representative Settlement", company_code="CP15-R-" + uuid4().hex,
            timezone="Asia/Amman",
        )
        other = Company(
            name="CP15 Foreign", company_code="CP15-F-" + uuid4().hex,
            timezone="Asia/Amman",
        )
        db.add_all((company, other))
        await db.flush()
        await db.execute(text("SELECT set_config('app.current_tenant', :tenant, true)"),
                         {"tenant": str(company.id)})
        actor = await seed_ordinary_backoffice_fixture(
            db, company.id, password=ACTOR_PASSWORD
        )
        denied = await seed_ordinary_backoffice_fixture(
            db, company.id, password="CP15DeniedSynthetic123"
        )
        warehouse = InventoryLocation(
            company_id=company.id, name="Receiving warehouse",
            code="CP15-RECEIVE", location_type="WAREHOUSE", is_active=True,
        )
        db.add(warehouse)
        product = Product(company_id=company.id, code="CP15-P", name="Custody product")
        db.add(product)
        await db.flush()
        variant = ProductVariant(
            company_id=company.id, product_id=product.id, name="Custody SKU",
            sku="CP15-SKU", base_uom_id=uom.id, quantity_scale=3,
            quantity_step=Decimal("0.001"), lot_control_mode="REQUIRED",
            expiry_control_mode="OPTIONAL", lifecycle_status="ACTIVE",
            published_at=utc_now(),
        )
        db.add(variant)
        await db.flush()
        batch = ProductBatch(
            company_id=company.id, product_variant_id=variant.id,
            batch_number="CP15-BATCH",
        )
        db.add(batch)
        await db.flush()
        db.add(ProductLocation(
            company_id=company.id, location_id=warehouse.id,
            product_variant_id=variant.id, created_by=actor.driver_id,
        ))
        zone = Zone(company_id=company.id, name="CP15 Zone", is_active=True)
        db.add(zone)
        await db.flush()
        records = []
        for index in range(2):
            vehicle = Vehicle(
                company_id=company.id, plate_number=f"CP15-V{index}",
                is_active=True, maintenance_status="Active",
            )
            db.add(vehicle)
            await db.flush()
            custody = InventoryLocation(
                company_id=company.id, code=f"CP15-CUSTODY-{index}",
                name=f"CP15 Vehicle {index}", location_type="VEHICLE",
                vehicle_id=vehicle.id, is_active=True,
            )
            db.add(custody)
            await db.flush()
            now = utc_now()
            work = WorkSession(
                company_id=company.id, driver_id=actor.driver_id,
                start_time=now, session_date=date.today(), end_time=now,
                is_settled=False,
            )
            db.add(work)
            await db.flush()
            db.add(DispatchRoute(
                company_id=company.id, zone_id=zone.id,
                driver_id=actor.driver_id, vehicle_id=vehicle.id,
                work_session_id=work.id, source_location_id=warehouse.id,
                dispatch_date=date.today(), status="closed",
            ))
            records.append((int(work.id), int(custody.id)))
        for session_id, location_id in records:
            await _grant_location(
                db, company_id=company.id, driver_id=actor.driver_id,
                location_id=location_id, codes=LOCATION_CODES,
            )
        await _grant_location(
            db, company_id=company.id, driver_id=actor.driver_id,
            location_id=warehouse.id, codes=RECEIVING_CODES,
        )
        for code in ("settlement.read", "settlement.execute"):
            await _grant_company(
                db, company_id=company.id, driver_id=actor.driver_id, code=code,
            )
        await db.commit()
        return (
            int(company.id), int(other.id), actor, denied, int(warehouse.id),
            int(variant.id), int(batch.id), records,
        )


async def test_backoffice_representative_custody_postgres():
    runtime_url, admin_url = _checked_urls()
    runtime_engine = create_async_engine(
        runtime_url, poolclass=NullPool, connect_args={"timeout": 15},
    )
    admin_engine = create_async_engine(
        admin_url, poolclass=NullPool, connect_args={"timeout": 15},
    )
    try:
        company, other, actor, denied, warehouse, variant, batch, records = await _seed(admin_engine)
        matched_session, matched_vehicle = records[0]
        variance_session, variance_vehicle = records[1]

        async with _runtime_session(runtime_engine, company) as db:
            for status, qty in (("AVAILABLE", "6.250"), ("DAMAGED", "2.125")):
                await apply_inventory_movement(
                    db, company_id=company, performed_by=actor.driver_id,
                    product_variant_id=variant, batch_id=batch, quantity=Decimal(qty),
                    movement_kind="PHYSICAL", reference_type="CP15_TEST_OPENING",
                    reference_id=str(matched_session),
                    idempotency_key="CP15-OPEN-" + uuid4().hex,
                    destination_location_id=matched_vehicle,
                    destination_stock_status=status,
                )
            await apply_inventory_movement(
                db, company_id=company, performed_by=actor.driver_id,
                product_variant_id=variant, batch_id=batch,
                quantity=Decimal("4.000"), movement_kind="PHYSICAL",
                reference_type="CP15_TEST_OPENING", reference_id=str(variance_session),
                idempotency_key="CP15-OPEN-" + uuid4().hex,
                destination_location_id=variance_vehicle,
                destination_stock_status="DAMAGED",
            )
            await db.commit()

        async with _runtime_session(runtime_engine, company) as db:
            access = actor.access(db)
            preview = await settlement.read_representative_custody(
                matched_session, db=db, access=access,
            )
            assert {line["stock_status"] for line in preview["lines"]} == {
                "AVAILABLE", "DAMAGED",
            }
            assert sorted(line["expected_quantity"] for line in preview["lines"]) == [
                "2.125", "6.25",
            ]
            assert all(line["batch_number"] == "CP15-BATCH" for line in preview["lines"])
            with pytest.raises(HTTPException) as denied_receiver:
                await settlement.receive_representative_custody(
                    matched_session,
                    settlement.CustodyConfirm(
                        request_id=uuid4(), destination_location_id=warehouse,
                        receiver_confirms_handoff=True,
                        items=[settlement.CustodyCount(
                            line_key=l["line_key"], actual_quantity=l["expected_quantity"],
                        ) for l in preview["lines"]],
                    ),
                    db=db, access=denied.access(db),
                    legacy_actor=denied.operational_driver,
                )
            assert denied_receiver.value.status_code == 403
            await db.rollback()
            preview = await settlement.read_representative_custody(
                matched_session, db=db, access=access,
            )
            confirmation = settlement.CustodyConfirm(
                request_id=uuid4(), destination_location_id=warehouse,
                receiver_confirms_handoff=True,
                items=[settlement.CustodyCount(
                    line_key=l["line_key"], actual_quantity=l["expected_quantity"],
                ) for l in preview["lines"]],
            )
            closed = await settlement.receive_representative_custody(
                matched_session, confirmation, db=db, access=access,
                legacy_actor=actor.operational_driver,
            )
            assert closed["status"] == "CUSTODY_RECEIVED"
            assert closed["movement_count"] == 2
            replay = await settlement.receive_representative_custody(
                matched_session, confirmation, db=db, access=access,
                legacy_actor=actor.operational_driver,
            )
            assert replay == closed
            movement_rows = (await db.scalars(
                select(InventoryMovement).where(
                    InventoryMovement.company_id == company,
                    InventoryMovement.work_session_id == matched_session,
                    InventoryMovement.reference_type == "REPRESENTATIVE_CUSTODY_RECEIPT",
                )
            )).all()
            assert len(movement_rows) == 2
            assert {(m.source_stock_status, m.destination_stock_status) for m in movement_rows} == {
                ("AVAILABLE", "AVAILABLE"), ("DAMAGED", "DAMAGED"),
            }
            assert all(m.batch_id == batch and m.source_location_id == matched_vehicle and
                       m.destination_location_id == warehouse for m in movement_rows)
            assert await _qty(db, company, matched_vehicle, batch, "AVAILABLE") == 0
            assert await _qty(db, company, matched_vehicle, batch, "DAMAGED") == 0
            assert await _qty(db, company, warehouse, batch, "AVAILABLE") == Decimal("6.250")
            assert await _qty(db, company, warehouse, batch, "DAMAGED") == Decimal("2.125")
            settled = await db.scalar(select(WorkSession).where(
                WorkSession.company_id == company, WorkSession.id == matched_session,
            ))
            assert settled.inventory_reconciled_at is not None
            assert settled.is_settled is False
            count_audit = int(await db.scalar(select(func.count()).select_from(SystemAuditLog).where(
                SystemAuditLog.company_id == company,
                SystemAuditLog.target_id == f"WorkSession_{matched_session}",
                SystemAuditLog.action_type == "REPRESENTATIVE_CUSTODY_RECEIVED",
            )))
            assert count_audit == 1
            with pytest.raises(HTTPException) as repeat_fresh_id:
                await settlement.receive_representative_custody(
                    matched_session, confirmation.model_copy(update={"request_id": uuid4()}),
                    db=db, access=access, legacy_actor=actor.operational_driver,
                )
            assert repeat_fresh_id.value.status_code == 409
            await db.rollback()

        async with _runtime_session(runtime_engine, company) as db:
            # Financial close consumes the sealed receipt and does not touch stock.
            access = actor.access(db)
            with pytest.raises(HTTPException) as missing_explanation:
                await dispatch.settle_session(
                    matched_session, SettleSessionRequest(actual_cash=Decimal("1"), notes=None),
                    db=db, access=access, legacy_actor=actor.operational_driver,
                )
            assert missing_explanation.value.status_code == 400
            close = await dispatch.settle_session(
                matched_session,
                SettleSessionRequest(actual_cash=Decimal("1"), notes="Receiver cash difference"),
                db=db, access=access, legacy_actor=actor.operational_driver,
            )
            assert close["is_settled"] is True
            assert await _qty(db, company, warehouse, batch, "DAMAGED") == Decimal("2.125")

        async with _runtime_session(runtime_engine, company) as db:
            access = actor.access(db)
            preview = await settlement.read_representative_custody(
                variance_session, db=db, access=access,
            )
            assert len(preview["lines"]) == 1
            request = settlement.CustodyConfirm(
                request_id=uuid4(), destination_location_id=warehouse,
                receiver_confirms_handoff=True,
                items=[settlement.CustodyCount(
                    line_key=preview["lines"][0]["line_key"], actual_quantity="3.000",
                )],
            )
            difference = await settlement.receive_representative_custody(
                variance_session, request, db=db, access=access,
                legacy_actor=actor.operational_driver,
            )
            assert difference["status"] == "REVIEW_REQUIRED"
            assert difference["movement_count"] == 0
            assert difference["requires_independent_recount"] is True
            record = await db.scalar(select(StocktakeSession).where(
                StocktakeSession.company_id == company,
                StocktakeSession.related_work_session_id == variance_session,
            ))
            assert record.status == "PENDING_REVIEW"
            attempt_line = await db.scalar(select(StocktakeCountAttemptLine).where(
                StocktakeCountAttemptLine.company_id == company,
                StocktakeCountAttemptLine.stocktake_session_id == record.id,
            ))
            assert attempt_line.expected_quantity == Decimal("4")
            assert attempt_line.actual_quantity == Decimal("3")
            assert attempt_line.variance_quantity == Decimal("-1")
            assert await _qty(db, company, variance_vehicle, batch, "DAMAGED") == Decimal("4")
            assert await _qty(db, company, warehouse, batch, "DAMAGED") == Decimal("2.125")
            retry = await settlement.receive_representative_custody(
                variance_session, request, db=db, access=access,
                legacy_actor=actor.operational_driver,
            )
            assert retry == difference
            with pytest.raises(HTTPException) as blocked_financial:
                await dispatch.settle_session(
                    variance_session,
                    SettleSessionRequest(actual_cash=Decimal("0"), notes=None),
                    db=db, access=access, legacy_actor=actor.operational_driver,
                )
            assert blocked_financial.value.status_code == 409
            with pytest.raises(HTTPException) as no_handoff:
                await settlement.receive_representative_custody(
                    variance_session, request.model_copy(update={"request_id": uuid4()}),
                    db=db, access=access, legacy_actor=actor.operational_driver,
                )
            assert no_handoff.value.status_code == 409

        async with _runtime_session(runtime_engine, company) as db:
            with pytest.raises(HTTPException) as foreign:
                await settlement.read_representative_custody(
                    2147483647, db=db, access=actor.access(db),
                )
            assert foreign.value.status_code == 404
    finally:
        await runtime_engine.dispose()
        await admin_engine.dispose()
