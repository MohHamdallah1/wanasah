"""Review fences and original-attempt recovery; PG write acceptance is separate."""
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from domains.representative_settlement_multi_vehicle import review_evidence as evidence
from domains.representative_settlement_multi_vehicle import variance_workflow as workflow
from domains.representative_settlement_multi_vehicle.contracts import CustodyRejected, VarianceApproval, VarianceCount
from domains.stocktake.contracts import StocktakeApprovalCommand
from domains.stocktake.idempotency import stocktake_request_hash
from services import OperationIdempotencyError
from tests.test_dispatch_m04_domain import NOW, vehicles


def attempt(identifier, parent=None):
    return NS(id=identifier, recount_of_attempt_id=parent, attempt_number=identifier,
              counted_by=900, submitted_at=NOW)


def recon():
    return NS(id=61, company_id=1, related_work_session_id=71, location_id=110,
              reference_number="VREC-EXAMPLE")


def line():
    return NS(stocktake_line_id=201, expected_quantity=Decimal(83),
              actual_quantity=Decimal(82), variance_quantity=Decimal(-1))


@pytest.mark.asyncio
async def test_review_token_changes_with_counter_attempt_location_and_exact_quantity():
    db = NS(scalars=AsyncMock(return_value=NS(all=lambda: [line()])))
    a, b = vehicles()
    first = await evidence.review_token(db, recon=recon(), vehicle=a, attempt=attempt(41))
    assert first != await evidence.review_token(db, recon=recon(), vehicle=a, attempt=attempt(42))
    assert first != await evidence.review_token(db, recon=recon(), vehicle=b, attempt=attempt(41))
    changed = line()
    changed.actual_quantity, changed.variance_quantity = Decimal(81), Decimal(-2)
    db.scalars.return_value = NS(all=lambda: [changed])
    assert first != await evidence.review_token(db, recon=recon(), vehicle=a, attempt=attempt(41))


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_after_pre_read", [False, True])
async def test_lost_recount_response_recovers_original_parent_even_after_financial_close(monkeypatch, commit_after_pre_read):
    from api.warehouse import stocktake
    a = vehicles()[0]
    header, parent, submitted = recon(), attempt(41), attempt(42, parent=41)
    prior = NS(state="COMMITTED", response_json={"attempt_id": 42})
    # First count pre-read may occur just before the other identical request commits.
    sequence = [parent, submitted, parent] if commit_after_pre_read else [submitted, parent, submitted, parent]
    db = NS(scalar=AsyncMock(side_effect=sequence))
    monkeypatch.setattr(workflow, "variance_scope", AsyncMock(return_value=(NS(is_settled=True), a, header)))
    monkeypatch.setattr(workflow, "previous_command", AsyncMock(return_value=None if commit_after_pre_read else prior))
    monkeypatch.setattr(workflow, "lock_idempotent_operation_record", AsyncMock(return_value=("request", prior)))
    rows = {"a" * 24: {"product_variant_id": 12, "batch_id": 19, "stock_status": "AVAILABLE", "base_uom_id": 1}}
    monkeypatch.setattr(workflow, "internal_count_rows", AsyncMock(return_value=rows))
    current_stock = AsyncMock(side_effect=AssertionError("Committed replay must not inspect later stock"))
    monkeypatch.setattr(workflow, "load_vehicle_snapshot", current_stock)
    submit = AsyncMock(return_value={"status": "PENDING_REVIEW"})
    monkeypatch.setattr(stocktake, "submit_stocktake_count", submit)
    payload = VarianceCount(request_id=uuid4(), count_token=evidence.count_token(
        recon=header, vehicle=a, attempt=parent), items=[{"line_key": "a" * 24, "actual_quantity": "82"}])
    result = await workflow.run_vehicle_variance(
        db, access=NS(company_id=1), actor=NS(id=900), session_id=71, vehicle_id=10, payload=payload, action="count")
    assert result["status"] == "PENDING_REVIEW"
    assert submit.await_args.args[1].request_id == payload.request_id
    assert submit.await_args.args[1].items[0].actual_quantity == Decimal(82)
    current_stock.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_notes", [False, True])
async def test_commit_race_rechecks_full_original_approval_hash_and_never_accepts_changed_body(monkeypatch, changed_notes):
    from api.warehouse import stocktake
    a, header = vehicles()[0], recon()
    original, later = attempt(41), attempt(42)
    prior = NS(state="COMMITTED", response_json={"attempt_id": 41})
    db = NS(scalar=AsyncMock(side_effect=[later, original, original]),
            scalars=AsyncMock(return_value=NS(all=lambda: [line()])))
    monkeypatch.setattr(workflow, "variance_scope", AsyncMock(return_value=(NS(is_settled=True), a, header)))
    monkeypatch.setattr(workflow, "previous_command", AsyncMock(side_effect=[None, prior]))
    request_id = uuid4()
    payload = VarianceApproval(request_id=request_id,
        review_token=await evidence.review_token(db, recon=header, vehicle=a, attempt=original),
        password="SyntheticApproval123", notes="changed" if changed_notes else None)
    original_hash = stocktake_request_hash(StocktakeApprovalCommand(
        request_id=request_id, count_attempt_id=41, password=payload.password, notes=None), target=61)
    calls = []
    async def lock(*args, request_hash, **kwargs):
        calls.append(request_hash)
        if request_hash != original_hash:
            raise OperationIdempotencyError("IDEMPOTENCY_PAYLOAD_CONFLICT", "Different body")
        return str(request_id), prior
    monkeypatch.setattr(workflow, "lock_idempotent_operation_record", lock)
    approve = AsyncMock(return_value={"status": "POSTED", "movement_count": 1})
    monkeypatch.setattr(stocktake, "approve_stocktake_session", approve)
    arguments = dict(access=NS(company_id=1), actor=NS(id=900), session_id=71,
                     vehicle_id=10, payload=payload, action="approve")
    if changed_notes:
        with pytest.raises(OperationIdempotencyError, match="Different body"):
            await workflow.run_vehicle_variance(db, **arguments)
        approve.assert_not_awaited()
    else:
        assert (await workflow.run_vehicle_variance(db, **arguments))["movement_count"] == 1
        assert approve.await_args.args[1].count_attempt_id == 41
    assert len(calls) == 2
