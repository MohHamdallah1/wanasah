"""Transaction-port tests; real PG16 writer/race acceptance is separate."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from domains.authorization.backoffice_access import BackofficeCapabilityAccessRejected
from domains.representative_settlement_multi_vehicle import activation, application, inventory_integration
from domains.representative_settlement_multi_vehicle.contracts import CustodyRejected
from tests.test_dispatch_m04_domain import command, snapshot, vehicles


class Database:
    def __init__(self):
        self.commit, self.rollback = AsyncMock(), AsyncMock()
        self.scalar = AsyncMock(return_value=None)
        self.scalars = AsyncMock(return_value=NS(all=lambda: [10, 20]))


@pytest.fixture
def transaction(monkeypatch):
    db = Database()
    work = NS(id=71, company_id=1, is_settled=False)
    access = NS(company_id=1, subject=NS(principal_id=391), require=AsyncMock())
    record = NS(state="PENDING", completed_at=None, response_json=None, cancelled_at=None, cancelled_by=None)
    begin = AsyncMock(return_value=(record, None))
    monkeypatch.setattr(activation, "require_m04_schema", AsyncMock())
    monkeypatch.setattr(application, "begin_idempotent_operation", begin)
    monkeypatch.setattr(application, "session_responsibilities", AsyncMock(return_value=(work, vehicles())))
    monkeypatch.setattr(application, "load_vehicle_snapshot", AsyncMock(return_value=snapshot()))
    monkeypatch.setattr(application, "acquire_inventory_location_guard", AsyncMock())
    monkeypatch.setattr(application, "movement_watermark", AsyncMock(return_value=812))
    seal = AsyncMock(return_value=work)
    monkeypatch.setattr(inventory_integration, "seal_canonical_location", seal)
    receipt = AsyncMock(return_value=NS(id=501))
    monkeypatch.setattr(application, "persist_checkpoint", receipt)
    monkeypatch.setattr(application, "seal_session_if_complete", AsyncMock(return_value=False))
    inventory = NS(require_clear_or_reviewed=AsyncMock(return_value=None),
                   physical_handoff=AsyncMock(return_value=2),
                   submit_variance=AsyncMock(return_value={"status": "REVIEW_REQUIRED"}))
    return NS(db=db, work=work, access=access, record=record, begin=begin,
              inventory=inventory, seal=seal, receipt=receipt)


async def execute(t, payload=None):
    return await application.record_vehicle_count(
        t.db, access=t.access, actor_id=900, session_id=71, vehicle_id=10,
        command=payload or command(), inventory=t.inventory,
    )


@pytest.mark.asyncio
async def test_matching_count_seals_before_commit_and_never_requests_physical_movement(transaction):
    t = transaction
    result = await execute(t)
    assert result["movement_count"] == 0 and result["mode"] == "COUNT_IN_PLACE"
    t.inventory.physical_handoff.assert_not_awaited()
    t.inventory.submit_variance.assert_not_awaited()
    t.seal.assert_awaited_once()
    t.receipt.assert_awaited_once()
    assert t.record.state == "COMMITTED" and t.record.response_json == result
    t.db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_difference_stays_pending_without_checkpoint_or_stock_correction(transaction):
    t = transaction
    payload = command()
    payload.items[0].actual_quantity = "82"
    result = await execute(t, payload)
    assert result["status"] == "REVIEW_REQUIRED" and result["financial_ready"] is False
    t.inventory.submit_variance.assert_awaited_once()
    t.inventory.physical_handoff.assert_not_awaited()
    t.seal.assert_not_awaited()
    t.receipt.assert_not_awaited()
    assert t.record.state == "COMMITTED"


@pytest.mark.asyncio
async def test_receiving_failure_rolls_back_without_receipt_or_committed_idempotency(transaction):
    t = transaction
    t.inventory.physical_handoff.side_effect = CustodyRejected("RECEIVING_WAREHOUSE_NOT_FOUND")
    with pytest.raises(CustodyRejected):
        await execute(t, command(mode="PHYSICAL_HANDOFF", destination_location_id=400,
                                 receiver_confirms_handoff=True))
    t.db.rollback.assert_awaited_once()
    t.db.commit.assert_not_awaited()
    t.receipt.assert_not_awaited()
    assert t.record.state == "PENDING"


@pytest.mark.asyncio
async def test_lost_response_replays_before_settled_guard_without_second_count(transaction):
    t = transaction
    t.work.is_settled = True
    t.begin.return_value = (t.record, {"checkpoint_id": 501, "movement_count": 0})
    assert (await execute(t))["checkpoint_id"] == 501
    t.receipt.assert_not_awaited()
    t.inventory.physical_handoff.assert_not_awaited()
    t.db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoked_grant_does_not_disclose_a_previous_command_response(transaction):
    t = transaction
    t.access.require.side_effect = BackofficeCapabilityAccessRejected()
    with pytest.raises(CustodyRejected, match="AUTHORIZATION_DENIED"):
        await execute(t)
    t.begin.assert_not_awaited()
    t.receipt.assert_not_awaited()


@pytest.mark.asyncio
async def test_changed_inventory_watermark_rejects_count_without_any_effect(transaction, monkeypatch):
    from dataclasses import replace
    t = transaction
    monkeypatch.setattr(application, "load_vehicle_snapshot", AsyncMock(
        return_value=replace(snapshot(), movement_watermark=813)))
    with pytest.raises(CustodyRejected, match="SNAPSHOT_STALE"):
        await execute(t)
    t.receipt.assert_not_awaited()
    t.inventory.physical_handoff.assert_not_awaited()
    t.db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_different_request_cannot_replace_a_signed_vehicle_receipt(transaction):
    t = transaction
    t.db.scalar.return_value = 501
    with pytest.raises(CustodyRejected, match="ALREADY_COUNTED"):
        await execute(t)
    t.receipt.assert_not_awaited()
    t.db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_variance_batches_all_lines_and_preserves_independent_review_without_stock_writes():
    from decimal import Decimal
    from models import InventoryMovement, StocktakeCountAttempt, StocktakeCountAttemptLine, StocktakeSession
    from domains.representative_settlement_multi_vehicle.variance import persist_variance
    added = []
    async def flush():
        for index, row in enumerate(added, 1):
            if hasattr(row, "id") and row.id is None:
                row.id = index
    db = NS(add=added.append, add_all=added.extend, flush=AsyncMock(side_effect=flush))
    rows = {f"{i:024x}": {"line_key": f"{i:024x}", "variant_id": i + 1, "batch_id": i + 1,
                           "stock_status": "DAMAGED", "expected_quantity": Decimal(10),
                           "sku": str(i), "batch_number": "LOT"} for i in range(500)}
    policy = AsyncMock(return_value=True)
    result = await persist_variance(
        db, company_id=1, work=NS(id=71, driver_id=103), vehicle_location_id=110,
        actor_id=900, rows=rows, actual={key: Decimal(9) for key in rows}, notes=None,
        requires_independent_recount=policy,
    )
    assert result["requires_independent_recount"] is True and result["movement_count"] == 0
    assert db.flush.await_count == 3
    assert len([r for r in added if isinstance(r, StocktakeCountAttemptLine)]) == 500
    assert [r for r in added if isinstance(r, StocktakeSession)][0].status == "PENDING_REVIEW"
    assert [r for r in added if isinstance(r, StocktakeCountAttempt)][0].requires_independent_recount
    assert not [r for r in added if isinstance(r, InventoryMovement)]
    assert policy.await_args.args[2] == [(Decimal(10), Decimal(-1))] * 500
