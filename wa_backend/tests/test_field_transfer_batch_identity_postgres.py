"""Real migrated PostgreSQL rollback, movement atomicity and exact replay."""
import os
import unittest
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, text
from api import driver
from models import InventoryTransferHeader, InventoryTransferLine, WorkSession, utc_now
from schemas import BatchTransferResponseRequest
from services import InventoryMutationError, apply_inventory_movements_batch
from tests.test_costed_driver_customer_return_c2_db import RealCustomerReturnC2DatabaseTests


@unittest.skipUnless(os.getenv("WANASAH_FIELD_CONTRACT_PG_GATE") == "1", "Disposable CI PostgreSQL only")
class TransferBatchIdentityPostgresTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = RealCustomerReturnC2DatabaseTests.asyncSetUp
    asyncTearDown = RealCustomerReturnC2DatabaseTests.asyncTearDown
    _create_business_fixture = RealCustomerReturnC2DatabaseTests._create_business_fixture

    async def prepare(self):
        _, vehicle_location, batch = await self._create_business_fixture("FIFO")
        session_id = await self.db.scalar(select(WorkSession.id).where(
            WorkSession.company_id == self.tenant, WorkSession.driver_id == self.field.driver.id))
        headers = []
        for _ in range(3):
            header = InventoryTransferHeader(
                company_id=self.tenant, reference_number="BATCH-ID-" + uuid4().hex,
                source_location_id=self.warehouse_id, destination_location_id=vehicle_location,
                workflow_type="HANDSHAKE", status="PENDING", transfer_purpose="REPLENISHMENT",
                commercial_context={}, work_session_id=session_id,
                expected_receiver_id=self.field.driver.id, dispatched_by=self.actor.id)
            self.db.add(header)
            await self.db.flush()
            line = InventoryTransferLine(
                company_id=self.tenant, transfer_header_id=header.id,
                product_variant_id=self.variant["id"], batch_id=batch, quantity=Decimal("1"),
                source_stock_status="AVAILABLE", lifecycle_revision_snapshot=1,
                lifecycle_status_snapshot="ACTIVE", operational_hold_snapshot="NONE")
            self.db.add(line)
            await self.db.flush()
            await apply_inventory_movements_batch(self.db, company_id=self.tenant,
                performed_by=self.actor.id, movements=[{
                    "product_variant_id": self.variant["id"], "batch_id": batch,
                    "quantity": Decimal("1"), "movement_kind": "RESERVATION",
                    "reservation_action": "RESERVE", "reference_type": "HANDSHAKE_RESERVE",
                    "reference_id": header.reference_number,
                    "idempotency_key": "BATCH-RES-" + str(header.id),
                    "source_location_id": self.warehouse_id,
                    "destination_location_id": self.warehouse_id,
                    "source_stock_status": "AVAILABLE", "destination_stock_status": "AVAILABLE",
                    "work_session_id": session_id, "transfer_header_id": header.id,
                }])
            headers.append(int(header.id))
        await self.db.commit()
        return headers

    def payload(self, ids, decision="rejected", reasons=None):
        return BatchTransferResponseRequest(transfers=[
            {"transfer_id": value, "status": decision,
             "reason": (reasons or {}).get(value, "Fixture reason") if decision == "rejected" else None}
            for value in ids])

    async def invoke(self, payload):
        return await driver.batch_respond_to_transfers(payload, self.db,
            self.field.context, self.field.driver)

    async def evidence(self, ids):
        # Query stored evidence after rollback rather than trusting expired ORM state.
        headers = (await self.db.execute(text(
            "SELECT id,status,decision_reason,received_by FROM inventory_transfer_headers "
            "WHERE company_id=:c AND id=ANY(:ids) ORDER BY id"),
            {"c": self.tenant, "ids": ids})).all()
        movements = await self.db.scalar(text(
            "SELECT count(*) FROM inventory_movements WHERE company_id=:c "
            "AND transfer_header_id=ANY(:ids)"), {"c": self.tenant, "ids": ids})
        audits = await self.db.scalar(text(
            "SELECT count(*) FROM system_audit_logs WHERE company_id=:c "
            "AND target_id=ANY(:refs)"), {"c": self.tenant, "refs": ["Transfer_"+str(i) for i in ids]})
        reservations = await self.db.scalar(text(
            "SELECT sum(reserved_quantity) FROM inventory_balances WHERE company_id=:c"),
            {"c": self.tenant})
        return (headers, movements, audits, reservations)

    async def test_middle_reason_conflict_rolls_back_entire_new_batch(self):
        ids = await self.prepare()
        await self.invoke(self.payload([ids[1]]))
        before = await self.evidence(ids)
        with self.assertRaises(HTTPException) as error:
            await self.invoke(self.payload(ids, reasons={ids[1]: "Different reason"}))
        self.assertEqual(error.exception.detail["code"], "FIELD_TRANSFER_DECISION_CONFLICT")
        self.assertEqual(error.exception.detail["context"], {"transfer_id": ids[1]})
        self.assertEqual(await self.evidence(ids), before)
        self.assertEqual([row.status for row in before[0]], ["PENDING", "REJECTED", "PENDING"])

    async def test_failure_after_real_movement_writes_rolls_back_all_effects(self):
        ids = await self.prepare()
        before = await self.evidence(ids)
        async def write_then_fail(*args, **kwargs):
            await apply_inventory_movements_batch(*args, **kwargs)
            await self.db.flush()
            raise InventoryMutationError("Synthetic failure after real movement writes")
        with patch.object(driver, "apply_inventory_movements_batch", side_effect=write_then_fail):
            with self.assertRaises(HTTPException) as error:
                await self.invoke(self.payload(ids))
        self.assertEqual(error.exception.detail["code"], "FIELD_TRANSFER_BATCH_INVENTORY_CONFLICT")
        self.assertEqual(error.exception.detail["context"], {})
        self.assertEqual(await self.evidence(ids), before)

    async def test_accepted_batch_exact_replay_has_no_second_effect(self):
        ids = await self.prepare()
        command = self.payload(ids, "accepted")
        await self.invoke(command)
        before = await self.evidence(ids)
        await self.invoke(command)
        self.assertEqual(await self.evidence(ids), before)
        self.assertTrue(all(row.status == "POSTED" for row in before[0]))

    async def test_rejected_batch_same_reason_exact_replay_has_no_second_effect(self):
        ids = await self.prepare()
        command = self.payload(ids)
        await self.invoke(command)
        before = await self.evidence(ids)
        await self.invoke(command)
        self.assertEqual(await self.evidence(ids), before)
        self.assertTrue(all(row.status == "REJECTED" for row in before[0]))
