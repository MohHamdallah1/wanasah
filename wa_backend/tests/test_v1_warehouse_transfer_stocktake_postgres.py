"""Section5.A real canonical inbound->warehouse transfer->independent stocktake."""
from __future__ import annotations

import asyncio
from datetime import date
import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text

from api.warehouse import inbound, stocktake, transfers
from domains.stocktake.contracts import (
    StocktakeApprovalCommand, StocktakeCountCommand, StocktakeRecountCommand, StocktakeStartCommand,
)
from models import (
    InventoryBalance, InventoryCostEvent, InventoryCostState, InventoryMovement,
    InventoryTransferHeader, InventoryTransferLine, OperationIdempotency,
    ProductBatch, ProductLocation, StocktakeCountAttempt, StocktakeSession,
)
from schemas import UnifiedDispatchRequest, UnifiedReceiveRequest, UnifiedTransferDecisionRequest
from services import apply_inventory_movement
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.warehouse_transfer_stocktake_expected import D, expected_manifest, matrix
from tests.warehouse_transfer_stocktake_support import (
    OWNER_PASSWORD, PASSWORD, canonical_access, checkpoint, command, prepare, save_report,
)

pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_TRANSFER_STOCKTAKE_E2E_PG_GATE") != "1",
                      reason="Explicit migrated disposable PG16 journey only"),
    pytest.mark.asyncio(loop_scope="function"),
]


async def twice(operation):
    """Two real concurrent request transactions, one stable logical command."""
    one, two = await asyncio.wait_for(asyncio.gather(operation(), operation()), timeout=25)
    assert one == two
    assert await operation() == one
    return one


async def denied(case, report, label, operation, status):
    with pytest.raises(HTTPException) as error:
        await operation()
    assert error.value.status_code == status, (label, error.value.detail)
    report["denials"].append({"control": label, "status": status})


def dispatch(case, cartons, request_id=None):
    t = case.tenant
    return UnifiedDispatchRequest(
        request_id=request_id or uuid4(), source_location_id=t.location_id,
        destination_location_id=t.other_location_id, transfer_purpose="WAREHOUSE_BALANCING",
        items=[{"product_variant_id": t.variant_id,
                "quantity": case.authority.to_base(D(cartons), uom_id=case.carton_id, validate_step=True),
                "uom_id": t.uom_id}])


async def reserve(case, action, key):
    t = case.tenant
    async with case.pg.session() as db:
        # Real inventory-engine reservation authority, as in CP8; never an INSERT
        # into balance/movement/cost fixtures. Physical transfers remain CP8 APIs.
        movement = await apply_inventory_movement(
            db, company_id=t.company_id, performed_by=t.owner.driver_id,
            product_variant_id=t.variant_id, batch_id=case.batches["E2E-FIRST"],
            quantity=D("16"), movement_kind="RESERVATION", reservation_action=action,
            reference_type="CP8_RESERVE" if action == "RESERVE" else "CP8_RELEASE",
            reference_id=key, idempotency_key=key,
            source_location_id=t.location_id, destination_location_id=t.location_id,
            source_stock_status="AVAILABLE", destination_stock_status="AVAILABLE")
        result = int(movement.id)
        await db.commit()
        return result


async def review(case, attempt_id, independent):
    t = case.tenant
    async with case.pg.session() as db:
        access = await canonical_access(db, case.receiver)
        result = await stocktake.get_stocktake_review(case.session_id, db, access)
        assert result["latest_attempt"]["id"] == attempt_id
        assert result["independent_recount_satisfied"] is independent
        assert len(result["lines"]) == 1
        row = result["lines"][0]
        assert (row["product_variant_id"], row["batch_id"], row["stock_status"]) == (
            t.variant_id, case.batches["E2E-FIRST"], "AVAILABLE")
        assert (D(row["expected_quantity"]), D(row["actual_quantity"]), D(row["variance_quantity"])) == (
            D("120"), D("104"), D("-16"))
        return result


async def isolation(case, report, header_id, session_id):
    pg, t = case.pg, case.tenant
    foreign = pg.tenants[1]
    async with pg.session(1) as db:
        for model in (InventoryBalance, InventoryMovement, InventoryCostEvent,
                      InventoryTransferHeader, StocktakeSession, StocktakeCountAttempt, ProductBatch):
            flags = (await db.execute(text("""
                SELECT relrowsecurity,relforcerowsecurity FROM pg_class
                WHERE oid=to_regclass(:n)
            """), {"n": model.__tablename__})).one()
            assert tuple(flags) == (True, True), model.__tablename__
            # No company predicate at all: the runtime FORCE RLS boundary applies.
            rows = list((await db.scalars(select(model))).all())
            assert all(r.company_id == foreign.company_id for r in rows)
            assert await db.scalar(select(func.count()).select_from(model).where(
                model.company_id == t.company_id)) == 0
        assert await db.scalar(select(InventoryTransferHeader).where(InventoryTransferHeader.id == header_id)) is None
        assert await db.scalar(select(StocktakeSession).where(StocktakeSession.id == session_id)) is None
        foreign_state = await db.scalar(select(InventoryCostState).where(
            InventoryCostState.product_variant_id == foreign.variant_id))
        assert (D(foreign_state.quantity), D(foreign_state.inventory_value)) == (D("3"), D("21"))
    await denied(case, report, "foreign transfer document", lambda: command(pg, foreign.owner,
        lambda db, access, actor: transfers.get_unified_transfer_detail(header_id, db, access), 1), 404)
    await denied(case, report, "foreign stocktake review", lambda: command(pg, foreign.owner,
        lambda db, access, actor: stocktake.get_stocktake_review(session_id, db, access), 1), 404)
    report["force_rls_tables"] = 7


async def test_canonical_transfer_and_stocktake_one_coherent_journey(pg):
    # This manifest precedes every stock command and every stock/API response.
    expected = matrix(pg.method)
    report = {"method": pg.method, "expected_before_execution": expected_manifest(pg.method),
              "stages": [], "denials": [], "status": "RUNNING"}
    save_report(report, pg.method)
    case = await prepare(pg)
    t = case.tenant
    step = "inbound_first"
    try:
        first = pg.request(quantity="100", cost="16", lot="E2E-FIRST", expiry=date(2099, 1, 1))
        first.items[0].uom_id = case.carton_id
        post_first = lambda: command(pg, t.owner,
            lambda db, access, actor: inbound.warehouse_inbound(first, db, access, actor))
        first_result = await post_first()
        assert await post_first() == first_result
        case.successful_requests.add(str(first.request_id))
        await checkpoint(case, expected[step], report)

        # Same logical UUID in another tenant is independent, not globally aliased.
        foreign = pg.request(party=1, request_id=first.request_id, quantity="3", cost="7",
                             lot="E2E-FIRST", expiry=date(2099, 1, 1))
        await command(pg, pg.tenants[1].owner,
            lambda db, access, actor: inbound.warehouse_inbound(foreign, db, access, actor), 1)

        step = "inbound_second"
        second = pg.request(quantity="50", cost="40", lot="E2E-SECOND", expiry=date(2099, 2, 1))
        second.items[0].uom_id = case.carton_id
        await command(pg, t.owner, lambda db, access, actor: inbound.warehouse_inbound(second, db, access, actor))
        case.successful_requests.add(str(second.request_id))
        await checkpoint(case, expected[step], report)

        step = "reserved"
        reserve_key = "E2E-HOLD-" + uuid4().hex
        assert await reserve(case, "RESERVE", reserve_key) == await reserve(case, "RESERVE", reserve_key)
        await checkpoint(case, expected[step], report)
        await denied(case, report, "cannot dispatch physically present reserved units",
            lambda: command(pg, case.sender, lambda db, access, actor:
                transfers.unified_transfer_dispatch(dispatch(case, "150"), db, access, actor)), 409)
        await denied(case, report, "receiver cannot dispatch source warehouse",
            lambda: command(pg, case.receiver, lambda db, access, actor:
                transfers.unified_transfer_dispatch(dispatch(case, "15"), db, access, actor)), 403)
        async with pg.session() as db:
            assert await db.scalar(select(ProductLocation).where(
                ProductLocation.company_id == t.company_id,
                ProductLocation.location_id == t.other_location_id)) is None
        await checkpoint(case, expected[step], report)

        step = "dispatched_15_cartons"
        payload = dispatch(case, "15")
        assert (payload.items[0].quantity, payload.items[0].uom_id) == (D("120"), t.uom_id)
        send = lambda: command(pg, case.sender, lambda db, access, actor:
            transfers.unified_transfer_dispatch(payload, db, access, actor))
        sent = await twice(send)
        case.successful_requests.add(str(payload.request_id))
        header_id = int(sent["header_id"])
        async with pg.session() as db:
            header = await db.get(InventoryTransferHeader, header_id)
            assert header.status == "IN_TRANSIT" and header.workflow_type == "TRANSIT"
            assert header.source_location_id == t.location_id and header.destination_location_id == t.other_location_id
            lines = list((await db.scalars(select(InventoryTransferLine).where(
                InventoryTransferLine.transfer_header_id == header_id))).all())
            assert [(line.batch_id, D(line.quantity), line.source_stock_status) for line in lines] == [
                (case.batches["E2E-FIRST"], D("120"), "AVAILABLE")]
        await checkpoint(case, expected[step], report)
        changed = payload.model_copy(update={"items": [payload.items[0].model_copy(update={"quantity": D("112")})]})
        await denied(case, report, "dispatch same UUID different cargo", lambda: command(pg, case.sender,
            lambda db, access, actor: transfers.unified_transfer_dispatch(changed, db, access, actor)), 409)
        receipt = UnifiedReceiveRequest(request_id=uuid4(), transfer_header_id=header_id,
                                        destination_location_id=t.other_location_id)
        await denied(case, report, "sender cannot receive", lambda: command(pg, case.sender,
            lambda db, access, actor: transfers.unified_transfer_receive(receipt, db, access, actor)), 403)
        await denied(case, report, "forged receipt destination", lambda: command(pg, case.receiver,
            lambda db, access, actor: transfers.unified_transfer_receive(
                receipt.model_copy(update={"destination_location_id": t.location_id}), db, access, actor)), 409)
        await checkpoint(case, expected[step], report)

        step = "received"
        receive = lambda: command(pg, case.receiver, lambda db, access, actor:
            transfers.unified_transfer_receive(receipt, db, access, actor))
        assert (await twice(receive))["status"] == "POSTED"
        case.successful_requests.add(str(receipt.request_id))
        await checkpoint(case, expected[step], report)

        step = "reject_dispatched"
        rejected_payload = dispatch(case, "2")
        rejected_send = await command(pg, case.sender, lambda db, access, actor:
            transfers.unified_transfer_dispatch(rejected_payload, db, access, actor))
        case.successful_requests.add(str(rejected_payload.request_id))
        rejected_id = int(rejected_send["header_id"])
        await checkpoint(case, expected[step], report)

        step = "rejected_to_source"
        reject_payload = UnifiedTransferDecisionRequest(request_id=uuid4(), decision_reason="Physical delivery declined")
        reject = lambda: command(pg, case.receiver, lambda db, access, actor:
            transfers.unified_transfer_reject(rejected_id, reject_payload, db, access, actor))
        assert (await twice(reject))["status"] == "REJECTED"
        case.successful_requests.add(str(reject_payload.request_id))
        await checkpoint(case, expected[step], report)

        step = "released"
        release_key = "E2E-RELEASE-" + uuid4().hex
        assert await reserve(case, "RELEASE", release_key) == await reserve(case, "RELEASE", release_key)
        await checkpoint(case, expected[step], report)

        step = "count_started"
        start = StocktakeStartCommand(request_id=uuid4(), location_id=t.other_location_id, stocktake_type="FULL_COUNT")
        await denied(case, report, "transfer destination grant is not stocktake.start",
            lambda: command(pg, case.sender, lambda db, access, actor:
                stocktake.start_unified_stocktake(start, db, access, actor)), 403)
        started = await twice(lambda: command(pg, case.receiver, lambda db, access, actor:
            stocktake.start_unified_stocktake(start, db, access, actor)))
        case.session_id = int(started["session_id"])
        case.successful_requests.add(str(start.request_id))
        assert started["snapshot_lines"] == 1
        await checkpoint(case, expected[step], report)
        await denied(case, report, "active count lock blocks incoming transfer", lambda: command(pg, case.sender,
            lambda db, access, actor: transfers.unified_transfer_dispatch(dispatch(case, "1"), db, access, actor)), 409)

        async with pg.session() as db:
            sheet = await stocktake.get_stocktake_count_sheet(
                case.session_id, db, await canonical_access(db, case.receiver), case.receiver.operational_driver)
            assert len(sheet) == 1 and "expected_quantity" not in sheet[0]
            assert sheet[0]["batch_id"] == case.batches["E2E-FIRST"]
        count = StocktakeCountCommand(request_id=uuid4(), items=[{
            "product_variant_id": t.variant_id, "batch_id": case.batches["E2E-FIRST"],
            "stock_status": "AVAILABLE", "actual_quantity": D("104"), "uom_id": t.uom_id}])
        step = "first_count_review"
        counted = await twice(lambda: command(pg, case.receiver, lambda db, access, actor:
            stocktake.submit_stocktake_count(case.session_id, count, db, access, actor)))
        first_attempt = int(counted["attempt_id"])
        case.successful_requests.add(str(count.request_id))
        assert counted["requires_independent_recount"] is True
        await review(case, first_attempt, False)
        await checkpoint(case, expected[step], report)
        await denied(case, report, "count replay cannot change quantity", lambda: command(pg, case.receiver,
            lambda db, access, actor: stocktake.submit_stocktake_count(case.session_id,
                count.model_copy(update={"items": [count.items[0].model_copy(update={"actual_quantity": D("103")})]}),
                db, access, actor)), 409)
        premature = StocktakeApprovalCommand(request_id=uuid4(), count_attempt_id=first_attempt, password=OWNER_PASSWORD)
        await denied(case, report, "negative variance needs independent recount",
            lambda: command(pg, t.owner, lambda db, access, actor:
                stocktake.approve_stocktake_session(case.session_id, premature, db, access, actor)), 409)
        await checkpoint(case, expected[step], report)

        step = "recount_authorized"
        recount = StocktakeRecountCommand(request_id=uuid4(), count_attempt_id=first_attempt,
            reason="Independent confirmation of predetermined sixteen-unit shortage",
            authorizer_username=case.recounter_username, authorizer_password=PASSWORD)
        authorized = await twice(lambda: command(pg, case.receiver, lambda db, access, actor:
            stocktake.recount_stocktake_session(case.session_id, recount, db, access, actor)))
        assert authorized["status"] == "RECOUNT_REQUIRED" and authorized["requires_independent_counter"] is True
        case.successful_requests.add(str(recount.request_id))
        await checkpoint(case, expected[step], report)
        second_count = count.model_copy(update={"request_id": uuid4()})
        await denied(case, report, "original counter cannot perform independent recount",
            lambda: command(pg, case.receiver, lambda db, access, actor:
                stocktake.submit_stocktake_count(case.session_id, second_count, db, access, actor)), 403)

        step = "independent_count_review"
        confirmed = await twice(lambda: command(pg, case.recounter, lambda db, access, actor:
            stocktake.submit_stocktake_count(case.session_id, second_count, db, access, actor)))
        case.successful_requests.add(str(second_count.request_id))
        second_attempt = int(confirmed["attempt_id"])
        assert second_attempt != first_attempt and confirmed["attempt_number"] == 2
        reviewed = await review(case, second_attempt, True)
        assert reviewed["attempt_history"][0]["counted_by"] != reviewed["latest_attempt"]["counted_by"]
        await checkpoint(case, expected[step], report)

        step = "stocktake_posted"
        approval = StocktakeApprovalCommand(request_id=uuid4(), count_attempt_id=second_attempt, password=OWNER_PASSWORD)
        await denied(case, report, "count capability is not approval authority",
            lambda: command(pg, case.receiver, lambda db, access, actor:
                stocktake.approve_stocktake_session(case.session_id, approval, db, access, actor)), 403)
        posted = await twice(lambda: command(pg, t.owner, lambda db, access, actor:
            stocktake.approve_stocktake_session(case.session_id, approval, db, access, actor)))
        assert posted["status"] == "POSTED" and posted["movement_count"] == 1
        case.successful_requests.add(str(approval.request_id))
        await checkpoint(case, expected[step], report)
        await isolation(case, report, header_id, case.session_id)
        async with pg.session() as db:
            assert len(case.successful_requests) == 11
            operations = list((await db.scalars(select(OperationIdempotency).where(
                OperationIdempotency.company_id == t.company_id,
                OperationIdempotency.request_id.in_(case.successful_requests)))).all())
            assert len(operations) == 11
            assert all(op.completed_at and isinstance(op.response_json, dict) for op in operations)
            assert len({op.request_id for op in operations}) == 11
            for hid, status in ((header_id, "POSTED"), (rejected_id, "REJECTED")):
                h = await db.get(InventoryTransferHeader, hid)
                assert h.status == status
                assert await db.scalar(select(func.count()).select_from(InventoryMovement).where(
                    InventoryMovement.transfer_header_id == hid)) == 2
        report["status"] = "PASS"
        report["logical_commands"] = 11
        print("WAREHOUSE_JOURNEY_PASS " + pg.method, flush=True)
    except Exception as exc:
        report["status"], report["failed_stage"], report["error"] = "RED", step, type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        save_report(report, pg.method)
