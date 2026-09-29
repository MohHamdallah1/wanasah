"""C2 bounded real PostgreSQL cost policy concurrency contention gate.

Proves an in-flight company policy selection prevents a second writer from
crossing the advisory lock. This is not a full successful two-receipt race
or a performance benchmark. External transactions always roll back.
"""
from __future__ import annotations

import os
import unittest

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from context import tenant_context
from database import engine
from domains.inventory_costing.service import set_cost_policy


@unittest.skipUnless(
    os.getenv("WANASAH_C2_LOCK_DB_GATE") == "1",
    "Only explicitly authorized empty developer tenant/DB.",
)
class CostPolicyLockContentionC2Tests(unittest.IsolatedAsyncioTestCase):
    async def test_inflight_fifo_choice_serializes_another_company_writer(self):
        company = int(os.environ["WANASAH_C2_LOCK_TENANT"])
        token = tenant_context.set(company)
        conn1 = conn2 = None
        outer1 = outer2 = None
        db1 = db2 = None
        try:
            conn1 = await engine.connect()
            outer1 = await conn1.begin()
            db1 = AsyncSession(
                bind=conn1, expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            await db1.execute(
                text("SELECT set_config('app.current_tenant',:tenant,true)"),
                {"tenant": str(company)},
            )
            self.assertEqual(
                await db1.scalar(text("SELECT current_database()")),
                os.environ["WANASAH_C2_LOCK_EXPECTED_DB"],
            )
            self.assertEqual(
                await db1.scalar(
                    text("SELECT count(*) FROM inventory_cost_policies WHERE company_id=:c")
                    , {"c": company},
                ),
                0,
            )
            actor = await db1.scalar(
                text("SELECT id FROM drivers WHERE company_id=:c AND is_admin=true "
                     "AND is_active=true LIMIT 1"), {"c": company},
            )
            self.assertIsNotNone(actor)
            first = await set_cost_policy(
                db1, company_id=company, actor_id=actor,
                method="FIFO", expected_version=0,
            )
            await db1.commit()  # commit only the SAVEPOINT; outer1 keeps advisory lock
            self.assertEqual(first.method, "FIFO")

            conn2 = await engine.connect()
            outer2 = await conn2.begin()
            await conn2.execute(
                text("SELECT set_config('app.current_tenant',:tenant,true)"),
                {"tenant": str(company)},
            )
            await conn2.execute(text("SET LOCAL lock_timeout='350ms'"))
            db2 = AsyncSession(
                bind=conn2, expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            with self.assertRaises(DBAPIError) as blocked:
                await set_cost_policy(
                    db2, company_id=company, actor_id=actor,
                    method="MOVING_AVERAGE", expected_version=0,
                )
            self.assertEqual(
                getattr(blocked.exception.orig, "sqlstate", None),
                "55P03",
                "Second cost-policy writer must be blocked by company advisory lock.",
            )
            stored = await db1.scalar(
                text("SELECT method FROM inventory_cost_policies WHERE company_id=:c"),
                {"c": company},
            )
            self.assertEqual(stored, "FIFO")
        finally:
            try:
                if db2 is not None:
                    await db2.close()
                if outer2 is not None and outer2.is_active:
                    await outer2.rollback()
                if conn2 is not None:
                    await conn2.close()
                if db1 is not None:
                    await db1.close()
                if outer1 is not None and outer1.is_active:
                    await outer1.rollback()
                if conn1 is not None:
                    await conn1.close()
            finally:
                tenant_context.reset(token)
                await engine.dispose()


if __name__ == "__main__":
    unittest.main()
