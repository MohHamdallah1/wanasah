"""Isolated PostgreSQL *committed* receipt race and replay gate.

Requires a disposable PostgreSQL 16 instance with developer schema + minimum
synthetic tenant-2 fixtures. Must be run ONLY with:
 WANASAH_C2_COMMITTED_DB_GATE=1,
 WANASAH_C2_COMMITTED_DB=c2_commit_fifo|c2_commit_average,
 WANASAH_C2_COMMITTED_METHOD=FIFO|MOVING_AVERAGE.
The server is restricted to 127.0.0.1:55439. The gate refuses any other
database name, host, port, SQL user or pre-existing policy/cost events.

This test deliberately COMMITS real supplier receipts; it does NOT roll them
back. Destroy the entire disposable PostgreSQL cluster after both methods
pass. Never run against the Wanasah development, shared or production DB.
"""
from __future__ import annotations

import asyncio
import os
import unittest
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from api.warehouse.inbound import (
    apply_inventory_movements_batch as real_apply,
    update_warehouse_costing_policy,
    warehouse_inbound,
)
from context import tenant_context
from schemas import InventoryCostPolicyUpdateRequest, UpgradedInboundRequest


@unittest.skipUnless(
    os.getenv("WANASAH_C2_COMMITTED_DB_GATE") == "1",
    "Requires disposable local PostgreSQL cluster, never normal database.",
)
class CommittedReceiptRaceC2IsolatedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.database_name = os.environ["WANASAH_C2_COMMITTED_DB"]
        self.method = os.environ["WANASAH_C2_COMMITTED_METHOD"]
        if (
            (self.database_name, self.method)
            not in {
                ("c2_commit_fifo", "FIFO"),
                ("c2_commit_average", "MOVING_AVERAGE"),
            }
        ):
            raise RuntimeError("Refusing an unapproved committed test DB/method.")
        self.tenant = 2
        self.context_token = tenant_context.set(self.tenant)
        self.engine = create_async_engine(
            "postgresql+asyncpg://wanasah_app@127.0.0.1:55439/"
            + self.database_name,
            # Several independent reader/writer sessions remain open until
            # final verification; connection identity must stay independent.
            pool_size=16,
            max_overflow=0,
            echo=False,
        )
        self.opened = []
        conn, session = await self._session()
        try:
            identity = (
                await session.execute(
                    text(
                        "SELECT current_database(),current_user,"
                        "inet_server_port(),current_setting('app.current_tenant',true)"
                    )
                )
            ).one()
            self.assertEqual(tuple(identity), (
                self.database_name, "wanasah_app", 55439, "2",
            ))
            for table in (
                "inventory_cost_policies", "inventory_cost_events",
                "inventory_movements", "inventory_balances",
                "operation_idempotency",
            ):
                self.assertEqual(
                    await session.scalar(
                        text(
                            "SELECT COUNT(*) FROM " + table
                            + " WHERE company_id=:tenant"
                        ),
                        {"tenant": self.tenant},
                    ),
                    0, "Commit gate requires a clean disposable DB: "+table,
                )
            actor_id = await session.scalar(
                text(
                    "SELECT id FROM drivers WHERE company_id=2 "
                    "AND is_admin=true AND is_active=true LIMIT 1"
                )
            )
            self.assertIsNotNone(actor_id)
            self.actor = SimpleNamespace(
                id=int(actor_id), company_id=2, is_admin=True, is_active=True,
            )
            self.location_id = await session.scalar(text(
                "SELECT id FROM inventory_locations "
                "WHERE company_id=2 AND location_type='WAREHOUSE' "
                "AND is_system_managed=false AND is_active=true LIMIT 1"
            ))
            row = (
                await session.execute(text(
                    "SELECT id,base_uom_id FROM product_variants "
                    "WHERE company_id=2 AND lifecycle_status='ACTIVE' "
                    "AND expiry_control_mode='REQUIRED' LIMIT 1"
                ))
            ).one()
            self.variant_id, self.uom_id = (int(row[0]), int(row[1]))
            self.assertIsNotNone(self.location_id)
        finally:
            await session.close()
            await conn.close()

    async def asyncTearDown(self):
        try:
            for conn, session in reversed(self.opened):
                if session.is_active:
                    await session.close()
                await conn.close()
            await self.engine.dispose()
        finally:
            tenant_context.reset(self.context_token)

    async def _session(self):
        # Bind the session to ONE connection. The tenant setting survives
        # app-level session.commit() and the checkout cannot switch identity.
        conn = await self.engine.connect()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        await session.execute(
            text("SELECT set_config('app.current_tenant',:tenant,false)"),
            {"tenant": str(self.tenant)},
        )
        self.opened.append((conn, session))
        return conn, session

    def _receipt(
        self, *, request_id=None, quantity="10", cost="2",
        reference=None,
    ):
        rid = request_id or uuid4()
        tag = rid.hex[:14]
        return UpgradedInboundRequest(
            request_id=rid,
            location_id=self.location_id,
            reference_id=reference or ("C2-COMMIT-" + tag),
            items=[{
                "product_variant_id": self.variant_id,
                "quantity": quantity,
                "uom_id": self.uom_id,
                "unit_cost": cost,
                "batch_number": "C2-COMMIT-LOT-" + tag,
                "production_date": date.today() - timedelta(days=30),
                "expiry_date": date.today() + timedelta(days=730),
            }],
        )

    async def _snapshot(self):
        _, db = await self._session()
        return {
            k: await db.scalar(
                text("SELECT count(*) FROM " + k + " WHERE company_id=2"),
            ) for k in (
                "inventory_cost_events", "inventory_movements",
                "inventory_balances", "inventory_cost_layers",
            )
        }

    async def test_two_truly_committed_invoices_retry_and_parallel_race(self):
        _, management = await self._session()
        policy = await update_warehouse_costing_policy(
            payload=InventoryCostPolicyUpdateRequest(
                request_id=uuid4(), method=self.method, expected_version=0,
            ),
            db=management, current_admin=self.actor,
        )
        self.assertEqual(policy["method"], self.method)
        self.assertEqual(policy["version"], 1)
        self.assertEqual(policy["selection_status"], "SELECTED")

        # A successfully committed receipt followed by lost *response*
        # (not dropped TCP transport): retry through an independent connection
        # observes the durable result rather than posting stock again.
        request = self._receipt(quantity="4", cost="2")
        _, first_db = await self._session()
        initial = await warehouse_inbound(
            payload=request, db=first_db, current_admin=self.actor,
        )
        self.assertEqual(initial, {"message": "INBOUND_POSTED"})
        _, retrier = await self._session()
        replay = await warehouse_inbound(
            payload=request, db=retrier, current_admin=self.actor,
        )
        self.assertEqual(replay, initial)
        self.assertEqual(
            (await self._snapshot())["inventory_cost_events"], 1,
        )
        # Independent transaction has already committed at this point.
        _, verifier = await self._session()
        actual_idempotency = await verifier.scalar(
            text(
                "SELECT count(*) FROM operation_idempotency "
                "WHERE company_id=2 AND operation='WAREHOUSE_INBOUND' "
                "AND request_id=:rid AND completed_at IS NOT NULL"
            ), {"rid": str(request.request_id)},
        )
        self.assertEqual(actual_idempotency, 1)

        # Two distinct supplier invoices are both accepted and DURABLY
        # committed. The first transaction pauses AFTER writing its stock and
        # cost event, while the second independently blocks on a company lock.
        _, a = await self._session()
        _, b = await self._session()
        left = self._receipt(quantity="10", cost="2")
        right = self._receipt(quantity="5", cost="3")
        completed_first_stock = asyncio.Event()
        unblock_first = asyncio.Event()

        async def pause_first_after_costs(db, **kwargs):
            result = await real_apply(db, **kwargs)
            if db is a:
                completed_first_stock.set()
                await unblock_first.wait()
            return result

        future1 = future2 = None
        with patch(
            "api.warehouse.inbound.apply_inventory_movements_batch",
            side_effect=pause_first_after_costs,
        ):
            try:
                future1 = asyncio.create_task(warehouse_inbound(
                    payload=left, db=a, current_admin=self.actor,
                ))
                await asyncio.wait_for(completed_first_stock.wait(), 20)
                future2 = asyncio.create_task(warehouse_inbound(
                    payload=right, db=b, current_admin=self.actor,
                ))
                await asyncio.sleep(0.2)
                self.assertFalse(
                    future2.done(),
                    "Second invoice must wait for the first pending cost lock.",
                )
            finally:
                unblock_first.set()
            responses = await asyncio.wait_for(
                asyncio.gather(future1, future2), 25,
            )
        self.assertEqual(responses, [initial, initial])

        # Fresh third-party connection sees both ACTUALLY committed invoices.
        _, persisted = await self._session()
        rows = (
            await persisted.execute(text(
                "SELECT input_quantity,input_unit_cost,total_cost,method "
                "FROM inventory_cost_events "
                "WHERE company_id=2 AND event_type='PURCHASE_IN' "
                "ORDER BY id"
            ))
        ).all()
        self.assertEqual(len(rows), 3)
        self.assertEqual([Decimal(r[2]) for r in rows], [
            Decimal("8"), Decimal("20"), Decimal("15"),
        ])
        self.assertEqual({r[3] for r in rows}, {self.method})
        state = (
            await persisted.execute(text(
                "SELECT quantity,inventory_value FROM inventory_cost_states "
                "WHERE company_id=2 AND product_variant_id=:variant"
            ), {"variant":self.variant_id})
        ).one()
        self.assertEqual(
            (Decimal(state.quantity),Decimal(state.inventory_value)),
            (Decimal("19"),Decimal("43")),
        )
        counts = await self._snapshot()
        self.assertEqual(counts["inventory_movements"], 3)
        self.assertEqual(counts["inventory_cost_events"], 3)
        self.assertEqual(
            counts["inventory_cost_layers"],
            3 if self.method == "FIFO" else 0,
        )
        self.assertEqual(counts["inventory_balances"], 3)

        for invoice in (left, right):
            _, fresh = await self._session()
            self.assertEqual(
                await warehouse_inbound(
                    payload=invoice, db=fresh, current_admin=self.actor,
                ), initial,
            )
        self.assertEqual(
            (await self._snapshot())["inventory_cost_events"], 3,
        )
        print(
            "C2_ISOLATED_DURABLE_COMMIT_OK",
            self.method,
            "3 distinct completed invoices; 3 movements; 3 cost events;",
            "2 parallel independently committed invoices; replay safe",
        )


if __name__ == "__main__":
    unittest.main()
