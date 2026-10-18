"""PostgreSQL 16 receiver-confirmed representative custody/financial gate acceptance.

Uses only the dedicated disposable CP14-C fixture DB and restricted runtime
role. No direct InventoryBalance writes; physical facts use the movement engine.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from asyncpg import Range
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api import dispatch, representative_settlement as settlement
from models import (
    Company, DispatchRoute, Driver, InventoryBalance, InventoryLocation, InventoryMovement,
    OperationIdempotency, SessionInventorySnapshot,
    PriceBook, PriceBookAssignment, PriceBookEntry, PricePublication,
    Product, ProductBatch, ProductLocation, ProductVariant, RouteCommercialContext,
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


async def _financial_inventory_fingerprint(db, company_id, work_session_id, vehicle_location, warehouse):
    """Exact persisted stock, movement and sealed snapshot state around financial close."""
    balances = (await db.execute(
        select(InventoryBalance.id, InventoryBalance.on_hand_quantity,
               InventoryBalance.reserved_quantity).where(
            InventoryBalance.company_id == company_id,
            InventoryBalance.location_id.in_((vehicle_location, warehouse)),
        ).order_by(InventoryBalance.id)
    )).all()
    movements = (await db.execute(
        select(InventoryMovement.id, InventoryMovement.quantity,
               InventoryMovement.reference_type).where(
            InventoryMovement.company_id == company_id,
            InventoryMovement.work_session_id == work_session_id,
        ).order_by(InventoryMovement.id)
    )).all()
    snapshots = (await db.execute(
        select(SessionInventorySnapshot.id, SessionInventorySnapshot.ending_quantity,
               SessionInventorySnapshot.settled_at, SessionInventorySnapshot.settled_by)
        .where(
            SessionInventorySnapshot.company_id == company_id,
            SessionInventorySnapshot.work_session_id == work_session_id,
        ).order_by(SessionInventorySnapshot.id)
    )).all()
    return balances, movements, snapshots


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
        counter_password = "CP15IndependentCounterSynthetic123"
        counter = await seed_ordinary_backoffice_fixture(
            db, company.id, password=counter_password,
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
        # DRIVER_SHORTAGE uses the actual locked route price authority. Seed a
        # published, effective price and a matching immutable route snapshot;
        # never bypass the commercial evidence requirement in production code.
        earlier = utc_now() - timedelta(days=1)
        book = PriceBook(
            company_id=company.id, code="CP15-LOCKED-PRICE",
            name="Representative settlement locked price",
            currency_code="JOD", status="ACTIVE", created_by=actor.driver_id,
        )
        db.add(book)
        await db.flush()
        published = PricePublication(
            company_id=company.id, price_book_id=book.id,
            revision=1, status="PUBLISHED", effective_at=earlier,
            published_at=earlier, approved_at=earlier,
            approved_by=actor.driver_id, created_by=actor.driver_id,
            request_id=uuid4(),
        )
        db.add(published)
        await db.flush()
        effective = Range(lower=earlier, upper=None, lower_inc=True)
        db.add_all([
            PriceBookEntry(
                company_id=company.id, price_book_id=book.id,
                publication_id=published.id, product_variant_id=variant.id,
                uom_id=uom.id, amount=Decimal("5.000000"),
                effectivity=effective, is_published=True,
                priority=0, entry_metadata={},
            ),
            PriceBookAssignment(
                company_id=company.id, price_book_id=book.id,
                scope_type="COMPANY_DEFAULT", scope_id=None,
                revision=1, priority=0, allow_offers=False,
                effectivity=effective, created_by=actor.driver_id,
            ),
        ])
        zone = Zone(company_id=company.id, name="CP15 Zone", is_active=True)
        db.add(zone)
        await db.flush()
        records = []
        for index in range(3):
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
            # Route and immutable commercial lock precede the WorkSession insert.
            # A session's commercial_context_id cannot be amended later.
            route = DispatchRoute(
                company_id=company.id, zone_id=zone.id,
                driver_id=actor.driver_id, vehicle_id=vehicle.id,
                source_location_id=warehouse.id,
                dispatch_date=date.today(), status="closed",
            )
            db.add(route)
            await db.flush()
            locked_context_id = None
            if index == 1:
                locked = RouteCommercialContext(
                    company_id=company.id, dispatch_route_id=route.id,
                    pricing_locked_at=utc_now(),
                    price_publication_revision=1, assignment_revision=1,
                    offer_ruleset_version=0, tax_ruleset_version=1,
                    transaction_currency_code="JOD", functional_currency_code="JOD",
                    rounding_policy_version=1, tenant_policy_revision=1,
                )
                db.add(locked)
                await db.flush()
                locked_context_id = locked.id
            now = utc_now()
            work = WorkSession(
                company_id=company.id, driver_id=actor.driver_id,
                start_time=now, session_date=date.today(), end_time=now,
                commercial_context_id=locked_context_id, is_settled=False,
            )
            db.add(work)
            await db.flush()
            route.work_session_id = work.id
            await db.flush()
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
            await _grant_company(
                db, company_id=company.id, driver_id=counter.driver_id, code=code,
            )
        await _grant_location(
            db, company_id=company.id, driver_id=counter.driver_id,
            location_id=records[1][1],
            codes=("inventory.read", "stocktake.read", "stocktake.count", "stocktake.recount"),
        )
        # Real foreign ended WorkSession for company-isolation negative coverage.
        await db.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": str(other.id)},
        )
        foreign_actor = await seed_ordinary_backoffice_fixture(
            db, other.id, password="CP15ForeignSynthetic123"
        )
        foreign_zone = Zone(company_id=other.id, name="Foreign Zone", is_active=True)
        db.add(foreign_zone)
        foreign_vehicle = Vehicle(
            company_id=other.id, plate_number="CP15-FOREIGN",
            is_active=True, maintenance_status="Active",
        )
        db.add(foreign_vehicle)
        await db.flush()
        foreign_location = InventoryLocation(
            company_id=other.id, code="CP15-FOREIGN-VEH", name="Foreign Vehicle",
            location_type="VEHICLE", vehicle_id=foreign_vehicle.id, is_active=True,
        )
        db.add(foreign_location)
        foreign_work = WorkSession(
            company_id=other.id, driver_id=foreign_actor.driver_id,
            start_time=utc_now(), session_date=date.today(),
            end_time=utc_now(), is_settled=False,
        )
        db.add(foreign_work)
        await db.flush()
        db.add(DispatchRoute(
            company_id=other.id, zone_id=foreign_zone.id,
            driver_id=foreign_actor.driver_id, vehicle_id=foreign_vehicle.id,
            work_session_id=foreign_work.id, source_location_id=foreign_location.id,
            dispatch_date=date.today(), status="closed",
        ))
        await db.flush()
        foreign_work_id = int(foreign_work.id)
        await db.commit()
        return (
            int(company.id), int(other.id), actor, denied, counter, counter_password,
            int(warehouse.id), int(variant.id), int(batch.id), records, foreign_work_id,
        )


async def test_backoffice_representative_custody_postgres():
    with pytest.raises(ValidationError):
        SettleSessionRequest.model_validate({"actual_cash": "0.000"})
    with pytest.raises(ValidationError):
        SettleSessionRequest.model_validate({
            "request_id": "not-a-uuid", "actual_cash": "0.000",
        })
    runtime_url, admin_url = _checked_urls()
    runtime_engine = create_async_engine(
        runtime_url, poolclass=NullPool, connect_args={"timeout": 15},
    )
    admin_engine = create_async_engine(
        admin_url, poolclass=NullPool, connect_args={"timeout": 15},
    )
    try:
        company, other, actor, denied, counter, counter_password, warehouse, variant, batch, records, foreign_work_id = await _seed(admin_engine)
        matched_session, matched_vehicle = records[0]
        variance_session, variance_vehicle = records[1]
        surplus_session, surplus_vehicle = records[2]

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
            await apply_inventory_movement(
                db, company_id=company, performed_by=actor.driver_id,
                product_variant_id=variant, batch_id=batch,
                quantity=Decimal("2.000"), movement_kind="PHYSICAL",
                reference_type="CP15_TEST_OPENING", reference_id=str(surplus_session),
                idempotency_key="CP15-OPEN-" + uuid4().hex,
                destination_location_id=surplus_vehicle,
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
            changed_items = list(confirmation.items)
            changed_items[0] = changed_items[0].model_copy(
                update={"actual_quantity": "0"}
            )
            with pytest.raises(HTTPException) as modified_replay:
                await settlement.receive_representative_custody(
                    matched_session,
                    confirmation.model_copy(update={"items": changed_items}),
                    db=db, access=access, legacy_actor=actor.operational_driver,
                )
            assert modified_replay.value.status_code == 409
            await db.rollback()
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
                    matched_session, SettleSessionRequest(request_id=uuid4(), actual_cash=Decimal("1"), notes=None),
                    db=db, access=access, legacy_actor=actor.operational_driver,
                )
            assert missing_explanation.value.status_code == 400
            before_financial = await _financial_inventory_fingerprint(
                db, company, matched_session, matched_vehicle, warehouse,
            )
            financial_command = SettleSessionRequest(
                request_id=uuid4(), actual_cash=Decimal("1"),
                notes="Receiver cash difference",
            )
            close = await dispatch.settle_session(
                matched_session, financial_command,
                db=db, access=access, legacy_actor=actor.operational_driver,
            )
            assert await _financial_inventory_fingerprint(
                db, company, matched_session, matched_vehicle, warehouse,
            ) == before_financial
            assert close["is_settled"] is True
            assert await _qty(db, company, warehouse, batch, "DAMAGED") == Decimal("2.125")
            # Ambiguous network retry stays state-idempotent across financial close.
            recovered = await settlement.receive_representative_custody(
                matched_session, confirmation,
                db=db, access=access, legacy_actor=actor.operational_driver,
            )
            assert recovered == closed
            with pytest.raises(HTTPException) as too_late:
                await settlement.receive_representative_custody(
                    matched_session,
                    confirmation.model_copy(update={"request_id": uuid4()}),
                    db=db, access=access, legacy_actor=actor.operational_driver,
                )
            assert too_late.value.status_code == 409
            await db.rollback()
            assert await _qty(db, company, warehouse, batch, "DAMAGED") == Decimal("2.125")

        # Simulate a lost HTTP response by replaying after the committed close
        # in a fresh DB transaction. Same ID + changed cash/notes is a conflict.
        async with _runtime_session(runtime_engine, company) as db:
            access = actor.access(db)
            replay_financial = await dispatch.settle_session(
                matched_session, financial_command,
                db=db, access=access, legacy_actor=actor.operational_driver,
            )
            assert replay_financial == close
            for changed_payload in (
                financial_command.model_copy(update={"actual_cash": Decimal("2.000")}),
                financial_command.model_copy(update={"notes": "Changed explanation"}),
            ):
                with pytest.raises(HTTPException) as idempotency_conflict:
                    await dispatch.settle_session(
                        matched_session, changed_payload,
                        db=db, access=access, legacy_actor=actor.operational_driver,
                    )
                assert idempotency_conflict.value.status_code == 409
                await db.rollback()
            with pytest.raises(HTTPException) as new_id_after_closed:
                await dispatch.settle_session(
                    matched_session,
                    financial_command.model_copy(update={"request_id": uuid4()}),
                    db=db, access=access, legacy_actor=actor.operational_driver,
                )
            assert new_id_after_closed.value.status_code == 409
            await db.rollback()
            audit_rows = (await db.scalars(select(SystemAuditLog.id).where(
                SystemAuditLog.company_id == company,
                SystemAuditLog.target_id == f"Session_{matched_session}_Driver_{actor.driver_id}",
                SystemAuditLog.action_type == "FINANCIAL_SETTLEMENT",
            ))).all()
            assert len(audit_rows) == 1
            idempotency = await db.scalar(select(OperationIdempotency).where(
                OperationIdempotency.company_id == company,
                OperationIdempotency.operation == "DISPATCH_FINANCIAL_SETTLEMENT",
                OperationIdempotency.request_id == str(financial_command.request_id),
            ))
            assert idempotency is not None
            assert idempotency.completed_at is not None
            assert idempotency.response_json == close
            assert await _financial_inventory_fingerprint(
                db, company, matched_session, matched_vehicle, warehouse,
            ) == before_financial

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
            assert "reconciliation_session_id" not in difference
            business_review = await settlement.review_representative_variance(
                variance_session, db=db, access=access,
            )
            assert business_review["requires_independent_recount"] is True
            assert business_review["lines"][0]["actual_quantity"] == "3"
            assert business_review["lines"][0]["variance_quantity"] == "-1"
            assert "stocktake_session_id" not in business_review
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
                    SettleSessionRequest(request_id=uuid4(), actual_cash=Decimal("0"), notes=None),
                    db=db, access=access, legacy_actor=actor.operational_driver,
                )
            assert blocked_financial.value.status_code == 409
            with pytest.raises(HTTPException) as no_handoff:
                await settlement.receive_representative_custody(
                    variance_session, request.model_copy(update={"request_id": uuid4()}),
                    db=db, access=access, legacy_actor=actor.operational_driver,
                )
            assert no_handoff.value.status_code == 409

        # Shortage invokes the same independent recount via business endpoints;
        # no Stocktake ID, batch ID, or attempt ID is ever required from the UI.
        async with _runtime_session(runtime_engine, company) as db:
            access = actor.access(db)
            first = await settlement.review_representative_variance(
                variance_session, db=db, access=access,
            )
            assert first["independent_recount_satisfied"] is False
            authorizer_driver = await db.scalar(select(Driver).where(
                Driver.company_id == company, Driver.id == counter.driver_id,
            ))
            assert authorizer_driver is not None
            recount = await settlement.request_representative_recount(
                variance_session,
                settlement.CustodyVarianceRecount(
                    request_id=uuid4(),
                    reason="Independent physical receiver recount",
                    authorizer_username=authorizer_driver.username,
                    authorizer_password=counter_password,
                ),
                db=db, access=access, legacy_actor=actor.operational_driver,
            )
            assert recount["status"] == "RECOUNT_REQUIRED"

        async with _runtime_session(runtime_engine, company) as db:
            counter_access = counter.access(db)
            sheet = await settlement.representative_recount_sheet(
                variance_session, db=db, access=counter_access,
                legacy_actor=counter.operational_driver,
            )
            assert len(sheet["lines"]) == 1
            assert sheet["lines"][0]["product_name"] == "Custody SKU"
            assert sheet["lines"][0]["batch_number"] == "CP15-BATCH"
            assert "stocktake_line_id" not in sheet["lines"][0]
            counted = await settlement.submit_representative_recount(
                variance_session,
                settlement.CustodyRecountSubmit(
                    request_id=uuid4(),
                    items=[settlement.CustodyCount(
                        line_key=sheet["lines"][0]["line_key"],
                        actual_quantity="3.000",
                    )],
                ),
                db=db, access=counter_access,
                legacy_actor=counter.operational_driver,
            )
            assert counted["status"] == "REVIEW_REQUIRED"
            assert counted["attempt_number"] == 2
            confirmed = await settlement.review_representative_variance(
                variance_session, db=db, access=actor.access(db),
            )
            assert confirmed["independent_recount_satisfied"] is True
            assert confirmed["lines"][0]["variance_quantity"] == "-1"
            assert await _qty(db, company, variance_vehicle, batch, "DAMAGED") == Decimal("4")
            with pytest.raises(HTTPException) as still_blocked:
                await dispatch.settle_session(
                    variance_session,
                    SettleSessionRequest(request_id=uuid4(), actual_cash=Decimal("0"), notes=None),
                    db=db, access=actor.access(db),
                    legacy_actor=actor.operational_driver,
                )
            assert still_blocked.value.status_code == 409

        # A shortage also completes the same independent recount -> adjustment
        # -> receiver-confirmed physical handoff -> financial seal journey.
        async with _runtime_session(runtime_engine, company) as db:
            access = actor.access(db)
            approval = await settlement.approve_representative_variance(
                variance_session,
                settlement.CustodyVarianceApprove(
                    request_id=uuid4(), password=ACTOR_PASSWORD,
                ),
                db=db, access=access, legacy_actor=actor.operational_driver,
            )
            assert approval["status"] == "RECONCILED_AWAITING_RECEIPT"
            assert approval["financial_ready"] is False
            recon_row = await db.scalar(select(StocktakeSession).where(
                StocktakeSession.company_id == company,
                StocktakeSession.related_work_session_id == variance_session,
            ))
            assert recon_row.status == "POSTED"
            shortage_movements = (await db.scalars(select(InventoryMovement).where(
                InventoryMovement.company_id == company,
                InventoryMovement.stocktake_session_id == recon_row.id,
            ))).all()
            assert len(shortage_movements) == 1
            assert shortage_movements[0].reference_type == "DRIVER_SHORTAGE"
            assert Decimal(shortage_movements[0].quantity) == Decimal("1")
            assert await _qty(db, company, variance_vehicle, batch, "DAMAGED") == Decimal("3")
            pending = await settlement.read_representative_custody(
                variance_session, db=db, access=access,
            )
            assert pending["lines"][0]["expected_quantity"] == "3"
            assert pending["custody_received"] is False
            handoff = await settlement.receive_representative_custody(
                variance_session,
                settlement.CustodyConfirm(
                    request_id=uuid4(), destination_location_id=warehouse,
                    receiver_confirms_handoff=True,
                    items=[settlement.CustodyCount(
                        line_key=pending["lines"][0]["line_key"],
                        actual_quantity="3",
                    )],
                ),
                db=db, access=access, legacy_actor=actor.operational_driver,
            )
            assert handoff["status"] == "CUSTODY_RECEIVED"
            assert handoff["financial_ready"] is True
            assert handoff["movement_count"] == 1
            assert await _qty(db, company, variance_vehicle, batch, "DAMAGED") == 0
            assert await _qty(db, company, warehouse, batch, "DAMAGED") == Decimal("5.125")
            # The shortage carries a locked unit-price financial difference;
            # the canonical financial step requires an explicit explanation.
            with pytest.raises(HTTPException) as missing_shortage_reason:
                await dispatch.settle_session(
                    variance_session,
                    SettleSessionRequest(request_id=uuid4(), actual_cash=Decimal("0"), notes=None),
                    db=db, access=access, legacy_actor=actor.operational_driver,
                )
            assert missing_shortage_reason.value.status_code == 400
            await db.rollback()
            cash_close = await dispatch.settle_session(
                variance_session,
                SettleSessionRequest(request_id=uuid4(), 
                    actual_cash=Decimal("0"),
                    notes="One damaged unit missing; DRIVER_SHORTAGE valued at locked JOD 5.000",
                ),
                db=db, access=access, legacy_actor=actor.operational_driver,
            )
            assert cash_close["is_settled"] is True
            assert await _qty(db, company, warehouse, batch, "DAMAGED") == Decimal("5.125")

        # Surplus is approved through canonical Vehicle Recon, then received.
        async with _runtime_session(runtime_engine, company) as db:
            access = actor.access(db)
            prior = await settlement.read_representative_custody(
                surplus_session, db=db, access=access,
            )
            assert prior["lines"][0]["expected_quantity"] == "2"
            surplus = await settlement.receive_representative_custody(
                surplus_session,
                settlement.CustodyConfirm(
                    request_id=uuid4(), destination_location_id=warehouse,
                    receiver_confirms_handoff=True,
                    items=[settlement.CustodyCount(
                        line_key=prior["lines"][0]["line_key"], actual_quantity="3.000",
                    )],
                ),
                db=db, access=access, legacy_actor=actor.operational_driver,
            )
            assert surplus["status"] == "REVIEW_REQUIRED"
            assert surplus["requires_independent_recount"] is False
            assert "reconciliation_session_id" not in surplus
            assert await _qty(db, company, surplus_vehicle, batch, "DAMAGED") == Decimal("2")
            review = await settlement.review_representative_variance(
                surplus_session, db=db, access=access,
            )
            assert Decimal(review["lines"][0]["variance_quantity"]) == Decimal("1")
            assert "stocktake_session_id" not in review
            approval = await settlement.approve_representative_variance(
                surplus_session,
                settlement.CustodyVarianceApprove(request_id=uuid4(), password=ACTOR_PASSWORD),
                db=db, access=access, legacy_actor=actor.operational_driver,
            )
            assert approval["status"] == "RECONCILED_AWAITING_RECEIPT"
            assert approval["financial_ready"] is False
            recon_row = await db.scalar(select(StocktakeSession).where(
                StocktakeSession.company_id == company,
                StocktakeSession.related_work_session_id == surplus_session,
            ))
            assert recon_row.status == "POSTED"
            surplus_movements = (await db.scalars(select(InventoryMovement).where(
                InventoryMovement.company_id == company,
                InventoryMovement.stocktake_session_id == recon_row.id,
            ))).all()
            assert len(surplus_movements) == 1
            assert surplus_movements[0].reference_type == "DRIVER_SURPLUS"
            assert Decimal(surplus_movements[0].quantity) == Decimal("1")
            assert await _qty(db, company, surplus_vehicle, batch, "DAMAGED") == Decimal("3")
            current_work = await db.scalar(select(WorkSession).where(
                WorkSession.company_id == company,
                WorkSession.id == surplus_session,
            ))
            assert current_work.inventory_reconciled_at is not None
            assert current_work.is_settled is False

            counted = await settlement.read_representative_custody(
                surplus_session, db=db, access=access,
            )
            assert counted["lines"][0]["expected_quantity"] == "3"
            receipt = settlement.CustodyConfirm(
                request_id=uuid4(), destination_location_id=warehouse,
                receiver_confirms_handoff=True,
                items=[settlement.CustodyCount(
                    line_key=counted["lines"][0]["line_key"], actual_quantity="3",
                )],
            )
            done = await settlement.receive_representative_custody(
                surplus_session, receipt,
                db=db, access=access, legacy_actor=actor.operational_driver,
            )
            assert done["financial_ready"] is True
            assert done["movement_count"] == 1
            assert await _qty(db, company, surplus_vehicle, batch, "DAMAGED") == 0
            assert await _qty(db, company, warehouse, batch, "DAMAGED") == Decimal("8.125")
            settled = await dispatch.settle_session(
                surplus_session,
                SettleSessionRequest(request_id=uuid4(), actual_cash=Decimal("0"), notes=None),
                db=db, access=access, legacy_actor=actor.operational_driver,
            )
            assert settled["is_settled"] is True
            assert await _qty(db, company, warehouse, batch, "DAMAGED") == Decimal("8.125")

        async with _runtime_session(runtime_engine, company) as db:
            with pytest.raises(HTTPException) as foreign:
                await settlement.read_representative_custody(
                    foreign_work_id, db=db, access=actor.access(db),
                )
            assert foreign.value.status_code == 404
    finally:
        await runtime_engine.dispose()
        await admin_engine.dispose()
