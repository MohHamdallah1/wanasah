import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from fastapi import HTTPException

from api.warehouse import inbound
from api.warehouse._shared import WarehouseAuditLockInfo
from schemas import UpgradedInboundRequest


class InboundAuditLockBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_receipt_is_rejected_by_backend_when_full_stocktake_lock_is_active(self):
        payload = UpgradedInboundRequest.model_validate(
            {
                "request_id": str(uuid4()),
                "supplier_id": 55,
                "location_id": 3,
                "reference_id": "INV-AUDIT-LOCK",
                "items": [
                    {
                        "product_variant_id": 1,
                        "quantity": "2",
                        "uom_id": 1,
                        "unit_cost": "3.000000",
                        "batch_number": None,
                        "production_date": None,
                        "expiry_date": None,
                    }
                ],
            }
        )
        db = SimpleNamespace(rollback=AsyncMock())
        access = SimpleNamespace(company_id=1)
        actor = SimpleNamespace(id=2)
        operation = SimpleNamespace()

        with (
            patch.object(inbound, "_require_inbound_access", new=AsyncMock()),
            patch.object(inbound, "_require_active_warehouse_setup", new=AsyncMock()),
            patch.object(inbound, "require_supplier_permission", new=AsyncMock()),
            patch.object(inbound, "_stable_request_hash", new=Mock(return_value="hash")),
            patch.object(
                inbound,
                "begin_idempotent_operation",
                new=AsyncMock(return_value=(operation, None)),
            ),
            patch.object(
                inbound,
                "acquire_inventory_location_guard",
                new=AsyncMock(),
            ) as location_guard,
            patch.object(
                inbound,
                "_active_full_warehouse_audit_lock",
                new=AsyncMock(
                    return_value=WarehouseAuditLockInfo(
                        stocktake_session_id=7,
                        stocktake_reference="STK-LOCK-123",
                        stocktake_status="COUNTING",
                    )
                ),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await inbound.warehouse_inbound(payload, db, access, actor)

        error = raised.exception
        self.assertEqual(error.status_code, 409)
        self.assertEqual(error.detail["code"], "INBOUND_WAREHOUSE_AUDIT_LOCKED")
        self.assertEqual(
            error.detail["context"],
            {
                "stocktake_session_id": 7,
                "stocktake_reference": "STK-LOCK-123",
                "stocktake_status": "COUNTING",
            },
        )
        location_guard.assert_awaited_once_with(
            db,
            1,
            3,
            exclusive=False,
        )
        db.rollback.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
