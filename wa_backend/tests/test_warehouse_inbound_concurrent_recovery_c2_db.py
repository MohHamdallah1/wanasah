"""C2 concurrent in-flight requests, idempotency and interruption recovery.

Never commits into customer storage: each real PostgreSQL connection owns an
outer transaction, app handler commit() is SAVEPOINT only; tearDown rolls
back outer transactions. Lock timeout is test-injected solely into the SECOND
connection to bound waiting. This proves rollback-safe in-flight contention,
not real simultaneous committed invoices or an actual dropped TCP socket.
"""
from __future__ import annotations

from tests.supplier_fixtures import seed_receipt_supplier

import asyncio
import os
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.warehouse.inbound import warehouse_inbound, apply_inventory_movements_batch as real_apply
from context import tenant_context
from database import engine
from domains.inventory_costing.service import set_cost_policy
from schemas import UpgradedInboundRequest


@unittest.skipUnless(
    os.getenv("WANASAH_C2_CONCURRENT_DB_GATE") == "1",
    "Explicit authorized developer tenant/DB required.",
)
class InflightWarehouseContentionC2Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.company_id = int(os.environ["WANASAH_C2_CONCURRENT_TENANT"])
        self.token = tenant_context.set(self.company_id)
        self.conn = await engine.connect()
        self.outer = await self.conn.begin()
        self.db = AsyncSession(
            bind=self.conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        await self.db.execute(
            text("SELECT set_config('app.current_tenant',:tenant,true)"),
            {"tenant": str(self.company_id)},
        )
        self.assertEqual(
            await self.db.scalar(text("SELECT current_database()")),
            os.environ["WANASAH_C2_CONCURRENT_EXPECTED_DB"],
        )
        for table in (
            "inventory_cost_policies",
            "inventory_cost_events",
            "inventory_balances",
            "operation_idempotency",
        ):
            self.assertEqual(await self._count(table), 0, table)
        actor_id = await self.db.scalar(
            text(
                "SELECT id FROM drivers WHERE company_id=:c AND is_admin=true "
                "AND is_active=true ORDER BY id LIMIT 1"
            ),
            {"c": self.company_id},
        )
        self.assertIsNotNone(actor_id)
        self.actor = SimpleNamespace(
            id=actor_id, company_id=self.company_id,
            is_admin=True, is_active=True,
        )
        self.supplier_id = await seed_receipt_supplier(self.db, self.actor)
        self.location_id = await self.db.scalar(
            text(
                "SELECT id FROM inventory_locations WHERE company_id=:c "
                "AND location_type='WAREHOUSE' AND is_active=true "
                "AND is_system_managed=false LIMIT 1"
            ),
            {"c": self.company_id},
        )
        self.variant = (
            await self.db.execute(
                text(
                    "SELECT id,base_uom_id FROM product_variants "
                    "WHERE company_id=:c AND lifecycle_status='ACTIVE' "
                    "AND operational_hold='NONE' "
                    "AND expiry_control_mode='REQUIRED' LIMIT 1"
                ),
                {"c": self.company_id},
            )
        ).mappings().one()
        self.assertIsNotNone(self.location_id)
        self.secondary_conn = None
        self.secondary_outer = None
        self.secondary_db = None

    async def asyncTearDown(self):
        try:
            if self.secondary_db is not None:
                await self.secondary_db.close()
            if self.secondary_outer is not None and self.secondary_outer.is_active:
                await self.secondary_outer.rollback()
            if self.secondary_conn is not None:
                await self.secondary_conn.close()
            await self.db.close()
            if self.outer.is_active:
                await self.outer.rollback()
        finally:
            await self.conn.close()
            tenant_context.reset(self.token)
            await engine.dispose()

    async def _count(self, table: str) -> int:
        assert table in {
            "inventory_cost_policies", "inventory_cost_events",
            "inventory_movements", "inventory_balances",
            "operation_idempotency", "inventory_cost_layers",
        }
        return int(await self.db.scalar(
            text("SELECT count(*) FROM " + table + " WHERE company_id=:c"),
            {"c": self.company_id},
        ))

    async def _choose(self, method: str) -> None:
        chosen = await set_cost_policy(
            self.db, company_id=self.company_id, actor_id=self.actor.id,
            method=method, expected_version=0,
        )
        self.assertEqual(chosen.method, method)
        await self.db.commit()  # savepoint only; cannot persist outside outer

    def _request(self, *, request_id=None, reference=None):
        identifier = request_id or uuid4()
        name = "C2-RACE-" + identifier.hex[:16]
        return UpgradedInboundRequest(
            supplier_id=self.supplier_id,
            request_id=identifier,
            reference_id=reference or name,
            location_id=self.location_id,
            items=[{
                "product_variant_id": self.variant["id"],
                "quantity": "6",
                "uom_id": self.variant["base_uom_id"],
                "unit_cost": "3",
                "batch_number": name,
                "production_date": date.today() - timedelta(days=30),
                "expiry_date": date.today() + timedelta(days=730),
            }],
        )

    async def _prepare_competing_transaction(self):
        self.secondary_conn = await engine.connect()
        self.secondary_outer = await self.secondary_conn.begin()
        await self.secondary_conn.execute(
            text("SELECT set_config('app.current_tenant',:tenant,true)"),
            {"tenant": str(self.company_id)},
        )
        await self.secondary_conn.execute(
            text("SET LOCAL lock_timeout='450ms'")
        )
        self.secondary_db = AsyncSession(
            bind=self.secondary_conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

    async def _race_with_live_uncommitted_request(
        self, method: str, *, different_request_same_invoice: bool,
    ) -> None:
        await self._choose(method)
        request = self._request()
        reached_stock_write = asyncio.Event()
        release_first = asyncio.Event()

        async def pause_after_real_inventory_write(db, **kwargs):
            result = await real_apply(db, **kwargs)
            if db is self.db:
                reached_stock_write.set()
                await release_first.wait()
            return result

        first = None
        with patch(
            "api.warehouse.inbound.apply_inventory_movements_batch",
            side_effect=pause_after_real_inventory_write,
        ):
            try:
                first = asyncio.create_task(
                    warehouse_inbound(
                        payload=request, db=self.db, current_admin=self.actor,
                    )
                )
                await asyncio.wait_for(reached_stock_write.wait(), timeout=12)
                self.assertEqual(await self._count("inventory_cost_events"), 1)
                self.assertEqual(await self._count("inventory_movements"), 1)

                await self._prepare_competing_transaction()
                if different_request_same_invoice:
                    competing = self._request(
                        request_id=uuid4(),
                        reference=request.reference_id,
                    )
                else:
                    competing = request

                # Two real concurrent database connections. The second writer
                # times out on request/ref advisory lock, and the app must
                # return an actionable retryable 409, not a generic 500.
                with self.assertRaises(HTTPException) as caught:
                    await asyncio.wait_for(
                        warehouse_inbound(
                            payload=competing,
                            db=self.secondary_db,
                            current_admin=self.actor,
                        ),
                        timeout=8,
                    )
                self.assertEqual(caught.exception.status_code, 409)
                self.assertEqual(
                    caught.exception.detail["code"],
                    "INBOUND_CONCURRENT_CONFLICT",
                )
            finally:
                release_first.set()
                if first is not None:
                    result = await asyncio.wait_for(first, timeout=12)
                    self.assertEqual(result, {"message": "INBOUND_POSTED"})

        # After transaction ONE finishes its app-layer SAVEPOINT, retry
        # contract is correct in the same external test transaction.
        if different_request_same_invoice:
            with self.assertRaises(HTTPException) as retry:
                await warehouse_inbound(
                    payload=competing, db=self.db, current_admin=self.actor,
                )
            self.assertEqual(
                retry.exception.detail["code"], "INBOUND_REFERENCE_DUPLICATE"
            )
        else:
            replay = await warehouse_inbound(
                payload=competing, db=self.db, current_admin=self.actor,
            )
            self.assertEqual(replay, {"message": "INBOUND_POSTED"})
        self.assertEqual(await self._count("inventory_movements"), 1)
        self.assertEqual(await self._count("inventory_cost_events"), 1)
        self.assertEqual(await self._count("inventory_balances"), 1)
        self.assertEqual(await self._count("inventory_cost_layers"), 1 if method == "FIFO" else 0)

    async def test_fifo_same_request_inflight_has_bounded_retryable_contention(self):
        await self._race_with_live_uncommitted_request(
            "FIFO", different_request_same_invoice=False,
        )

    async def test_average_different_request_same_supplier_reference_blocks(self):
        await self._race_with_live_uncommitted_request(
            "MOVING_AVERAGE", different_request_same_invoice=True,
        )

    async def test_cancelled_request_before_commit_can_be_rolled_back_and_retried(self):
        await self._choose("FIFO")
        payload = self._request()
        reached = asyncio.Event()
        pause = asyncio.Event()

        async def wait_after_stock_posting(db, **kwargs):
            result = await real_apply(db, **kwargs)
            reached.set()
            await pause.wait()
            return result

        task = None
        with patch(
            "api.warehouse.inbound.apply_inventory_movements_batch",
            side_effect=wait_after_stock_posting,
        ):
            task = asyncio.create_task(
                warehouse_inbound(
                    payload=payload, db=self.db, current_admin=self.actor,
                )
            )
            try:
                await asyncio.wait_for(reached.wait(), timeout=12)
                self.assertEqual(await self._count("inventory_cost_events"), 1)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                pause.set()
                if task is not None and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        # An abandoned/cancelled request is not a successful posting. The
        # request-scoped DB session must roll back before it is reused.
        await self.db.rollback()
        self.assertEqual(await self._count("inventory_movements"), 0)
        self.assertEqual(await self._count("inventory_cost_events"), 0)
        self.assertEqual(
            await self.db.scalar(
                text(
                    "SELECT count(*) FROM operation_idempotency "
                    "WHERE company_id=:c AND operation='WAREHOUSE_INBOUND'"
                ),
                {"c": self.company_id},
            ),
            0,
        )
        accepted = await warehouse_inbound(
            payload=payload, db=self.db, current_admin=self.actor,
        )
        self.assertEqual(accepted, {"message": "INBOUND_POSTED"})
        self.assertEqual(await self._count("inventory_cost_events"), 1)
        self.assertEqual(await self._count("inventory_movements"), 1)


if __name__ == "__main__":
    unittest.main()
