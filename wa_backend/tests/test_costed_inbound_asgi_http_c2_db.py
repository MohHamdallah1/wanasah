"""Real ASGI request-validation/router/permission gates for C2 costing.

Authentication dependency is deliberately overridden with tenant-scoped
synthetic identities; this is NOT a full login/session/middleware test.
Each authorized developer-DB test owns one outer transaction, and handler
commit() operations are SAVEPOINT-only. The outer transaction ALWAYS rolls
back stock, cost, policy, idempotency and domain events.
"""
from __future__ import annotations

import os
import unittest
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from api.warehouse.inbound import router
from context import tenant_context
from database import engine, get_db


@unittest.skipUnless(
    os.getenv("WANASAH_C2_HTTP_DB_GATE") == "1",
    "Explicit authorized developer tenant/DB only.",
)
class CostedInboundASGIC2DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.company_id = int(os.environ["WANASAH_C2_HTTP_TENANT"])
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
            os.environ["WANASAH_C2_HTTP_EXPECTED_DB"],
        )
        for table in (
            "inventory_cost_policies", "inventory_movements",
            "inventory_cost_events", "inventory_balances",
        ):
            self.assertEqual(
                await self.db.scalar(
                    text("SELECT count(*) FROM " + table + " WHERE company_id=:c"),
                    {"c": self.company_id},
                ), 0, table,
            )
        actor_id = await self.db.scalar(
            text("SELECT id FROM drivers WHERE company_id=:c "
                 "AND is_admin=true AND is_active=true LIMIT 1"),
            {"c": self.company_id},
        )
        self.assertIsNotNone(actor_id)
        self.actor = SimpleNamespace(
            company_id=self.company_id, id=actor_id, is_admin=True, is_active=True,
        )
        self.app = FastAPI()
        self.app.include_router(router)

        async def db_override():
            yield self.db

        async def actor_override():
            return self.actor

        self.app.dependency_overrides[get_db] = db_override
        self.app.dependency_overrides[get_current_driver] = actor_override
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://wanasah.test",
        )

    async def asyncTearDown(self):
        try:
            await self.http.aclose()
            self.app.dependency_overrides.clear()
            await self.db.close()
            if self.outer.is_active:
                await self.outer.rollback()
        finally:
            await self.conn.close()
            tenant_context.reset(self.token)
            await engine.dispose()

    async def _test_http_costed_receipt(self, method: str):
        unselected = await self.http.get("/warehouse/costing-policy")
        self.assertEqual(unselected.status_code, 200, unselected.text)
        self.assertIsNone(unselected.json()["method"])
        self.assertFalse(unselected.json()["is_selected"])
        variant = (
            await self.db.execute(
                text(
                    "SELECT id,base_uom_id FROM product_variants "
                    "WHERE company_id=:c AND lifecycle_status='ACTIVE' "
                    "AND expiry_control_mode='REQUIRED' LIMIT 1"
                ),
                {"c": self.company_id},
            )
        ).mappings().one()
        warehouse_id = await self.db.scalar(text(
            "SELECT id FROM inventory_locations WHERE company_id=:c "
            "AND location_type='WAREHOUSE' AND is_active=true "
            "AND is_system_managed=false LIMIT 1"
        ), {"c": self.company_id})
        request_id = str(uuid4())
        ref = "C2-HTTP-" + request_id.split("-")[0]
        body = {
            "request_id": request_id, "location_id": warehouse_id,
            "reference_id": ref, "notes": "",
            "items": [{
                "product_variant_id": variant["id"],
                "quantity": "10", "uom_id": variant["base_uom_id"],
                "unit_cost": "2.500000",
                "batch_number": "C2-HTTP-LOT-" + request_id.split("-")[0],
                "production_date": str(date(2026, 1, 1)),
                "expiry_date": str(date(2027, 12, 31)),
            }],
        }
        denied = await self.http.post("/warehouse/inbound", json=body)
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertEqual(
            denied.json()["detail"]["code"],
            "INVENTORY_COST_POLICY_SELECTION_REQUIRED",
        )
        admin_choice = await self.http.put(
            "/warehouse/costing-policy",
            json={
                "request_id": str(uuid4()), "method": method,
                "expected_version": 0,
            },
        )
        self.assertEqual(admin_choice.status_code, 200, admin_choice.text)
        self.assertEqual(admin_choice.json()["method"], method)
        self.assertTrue(admin_choice.json()["is_selected"])
        posted = await self.http.post("/warehouse/inbound", json=body)
        self.assertEqual(posted.status_code, 201, posted.text)
        self.assertEqual(posted.json(), {"message": "INBOUND_POSTED"})
        replay = await self.http.post("/warehouse/inbound", json=body)
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertEqual(replay.json(), posted.json())
        locked = await self.http.get("/warehouse/costing-policy")
        self.assertEqual(locked.status_code, 200)
        self.assertEqual(locked.json()["method"], method)
        self.assertTrue(locked.json()["is_locked"])
        changed = await self.http.put(
            "/warehouse/costing-policy",
            json={
                "request_id": str(uuid4()),
                "method": "FIFO" if method == "MOVING_AVERAGE" else "MOVING_AVERAGE",
                "expected_version": 2,
            },
        )
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(
            changed.json()["detail"]["code"], "INVENTORY_COST_POLICY_LOCKED"
        )
        for table in ("inventory_cost_events", "inventory_movements"):
            count = await self.db.scalar(
                text("SELECT count(*) FROM " + table + " WHERE company_id=:c"),
                {"c": self.company_id},
            )
            self.assertEqual(count, 1, table)

    async def test_fifo_real_asgi_post_and_client_retry(self):
        await self._test_http_costed_receipt("FIFO")

    async def test_moving_average_real_asgi_post_and_client_retry(self):
        await self._test_http_costed_receipt("MOVING_AVERAGE")

    async def test_nonprivileged_actor_gets_403_before_cost_policy_access(self):
        self.actor = SimpleNamespace(
            company_id=self.company_id,
            id=2_147_483_647,
            is_admin=False,
            is_active=True,
        )
        response = await self.http.get("/warehouse/costing-policy")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            await self.db.scalar(
                text("SELECT count(*) FROM inventory_cost_policies WHERE company_id=:c"),
                {"c": self.company_id},
            ), 0,
        )


if __name__ == "__main__":
    unittest.main()
