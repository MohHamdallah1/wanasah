import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from api.warehouse import inbound
from schemas import InventoryOpeningValuationFinalizeRequest


def payload():
    return InventoryOpeningValuationFinalizeRequest.model_validate(
        {
            "request_id": str(uuid4()),
            "snapshot_hash": "a" * 64,
            "lines": [{"sku": "SKU-1", "unit_cost": "2.500000"}],
            "confirm_zero_costs": False,
        }
    )


class OpeningValuationApiIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_committed_replay_returns_same_response_without_finalizing_again(self):
        request = payload()
        replay = {
            "message": "OPENING_VALUATION_POSTED",
            "method": "FIFO",
            "currency_code": "JOD",
            "snapshot_hash": "a" * 64,
            "line_count": 1,
            "total_quantity": "2.000000",
            "total_value": "5.000000",
            "zero_cost_count": 0,
            "policy_version": 3,
        }
        db = SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock())
        access = SimpleNamespace(company_id=1)
        actor = SimpleNamespace(id=2)

        with (
            patch.object(inbound, "_require_inbound_access", new=AsyncMock()),
            patch.object(inbound, "_stable_request_hash", return_value="hash"),
            patch.object(
                inbound,
                "begin_idempotent_operation",
                new=AsyncMock(return_value=(SimpleNamespace(), replay)),
            ),
            patch.object(
                inbound,
                "finalize_opening_valuation",
                new=AsyncMock(),
            ) as finalize,
        ):
            result = await inbound.finalize_warehouse_opening_valuation(
                request, db, access, actor,
            )

        self.assertEqual(result, replay)
        finalize.assert_not_awaited()
        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()

    async def test_fresh_finalize_completes_idempotency_record_in_same_commit(self):
        request = payload()
        response = {
            "message": "OPENING_VALUATION_POSTED",
            "method": "FIFO",
            "currency_code": "JOD",
            "snapshot_hash": "a" * 64,
            "line_count": 1,
            "total_quantity": "2.000000",
            "total_value": "5.000000",
            "zero_cost_count": 0,
            "policy_version": 3,
        }
        record = SimpleNamespace()
        db = SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock())
        access = SimpleNamespace(company_id=1)
        actor = SimpleNamespace(id=2)

        with (
            patch.object(inbound, "_require_inbound_access", new=AsyncMock()),
            patch.object(inbound, "_stable_request_hash", return_value="hash"),
            patch.object(
                inbound,
                "begin_idempotent_operation",
                new=AsyncMock(return_value=(record, None)),
            ) as begin,
            patch.object(
                inbound,
                "finalize_opening_valuation",
                new=AsyncMock(return_value=response),
            ) as finalize,
            patch.object(
                inbound,
                "complete_idempotent_operation",
                new=Mock(),
            ) as complete,
        ):
            result = await inbound.finalize_warehouse_opening_valuation(
                request, db, access, actor,
            )

        self.assertEqual(result, response)
        begin.assert_awaited_once()
        finalize.assert_awaited_once()
        complete.assert_called_once_with(record, response)
        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
