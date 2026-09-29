"""Opt-in developer DB gates: explicit costing choice and transaction rollback.

Requires WANASAH_C1_DB_GATE=1, WANASAH_C1_EXPECTED_DB and WANASAH_C1_TEST_TENANT.
No production/test-data cleanup; each test rolls back all created records.
"""
from __future__ import annotations

import os
import unittest

from sqlalchemy import select, text

from database import engine
from domains.inventory_costing.service import (
    CostingError,
    activate_costing_for_first_receipt,
    cost_policy_payload,
    get_cost_policy,
    provision_default_cost_policy,
    set_cost_policy,
)
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    open_tenant_session,
)
from models import Driver, InventoryCostPolicy


@unittest.skipUnless(
    os.getenv("WANASAH_C1_DB_GATE") == "1",
    "Run only by explicit developer DB opt-in.",
)
class ExplicitCostPolicyDeveloperDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.company_id = int(os.environ["WANASAH_C1_TEST_TENANT"])
        self.token, self.db = await open_tenant_session(self.company_id)
        dbname = await self.db.scalar(text("SELECT current_database()"))
        self.assertEqual(dbname, os.environ["WANASAH_C1_EXPECTED_DB"])
        tenant = await self.db.scalar(
            text("SELECT current_setting('app.current_tenant', true)")
        )
        self.assertEqual(tenant, str(self.company_id))
        self.actor = await self.db.scalar(
            select(Driver.id).where(
                Driver.company_id == self.company_id,
                Driver.is_active.is_(True),
            ).limit(1)
        )
        self.assertIsNotNone(self.actor, "A tenant-scoped active actor is required.")
        self.assertIsNone(
            await get_cost_policy(self.db, company_id=self.company_id),
            "Use only an authorized test company WITHOUT existing policy.",
        )
        self.assertEqual(
            await self.db.scalar(
                text(
                    "SELECT COALESCE(SUM(on_hand_quantity), 0) "
                    "FROM inventory_balances WHERE company_id=:company_id"
                ),
                {"company_id": self.company_id},
            ), 0,
            "Use an empty development company; do not alter existing stock.",
        )

    async def asyncTearDown(self):
        await self.db.rollback()
        await close_tenant_session(self.token, self.db)
        await engine.dispose()

    async def test_provisioned_default_cannot_be_used_without_confirmation(self):
        row = await provision_default_cost_policy(
            self.db, company_id=self.company_id, actor_id=self.actor,
        )
        self.assertEqual(row.method, "MOVING_AVERAGE")
        self.assertIsNone(row.selected_at)
        self.assertIsNone(row.selected_by)
        payload = await cost_policy_payload(
            self.db, company_id=self.company_id, can_change=True,
        )
        self.assertIsNone(payload["method"])
        self.assertFalse(payload["is_selected"])
        self.assertEqual(payload["selection_status"], "UNSELECTED")
        with self.assertRaises(CostingError) as caught:
            await activate_costing_for_first_receipt(
                self.db, company_id=self.company_id, actor_id=self.actor,
            )
        self.assertEqual(
            caught.exception.code, "INVENTORY_COST_POLICY_SELECTION_REQUIRED"
        )
        self.assertFalse(row.is_active)
        self.assertIsNone(row.locked_at)

    async def test_explicit_moving_average_confirms_default_then_locks(self):
        row = await provision_default_cost_policy(
            self.db, company_id=self.company_id, actor_id=self.actor,
        )
        selected = await set_cost_policy(
            self.db,
            company_id=self.company_id,
            actor_id=self.actor,
            method="MOVING_AVERAGE",
            expected_version=row.version,
        )
        self.assertEqual(selected.selected_by, self.actor)
        self.assertIsNotNone(selected.selected_at)
        self.assertEqual(selected.version, 2)
        payload = await cost_policy_payload(
            self.db, company_id=self.company_id, can_change=True,
        )
        self.assertEqual(payload["selection_status"], "SELECTED")
        self.assertEqual(payload["method"], "MOVING_AVERAGE")
        activated = await activate_costing_for_first_receipt(
            self.db, company_id=self.company_id, actor_id=self.actor,
        )
        self.assertTrue(activated.is_active)
        self.assertIsNotNone(activated.locked_at)
        self.assertEqual(activated.version, 3)
        with self.assertRaises(CostingError) as caught:
            await set_cost_policy(
                self.db, company_id=self.company_id, actor_id=self.actor,
                method="FIFO",
                expected_version=3,
            )
        self.assertEqual(caught.exception.code, "INVENTORY_COST_POLICY_LOCKED")

    async def test_explicit_fifo_is_one_method_and_rolls_back(self):
        selected = await set_cost_policy(
            self.db,
            company_id=self.company_id,
            actor_id=self.actor,
            method="FIFO",
            expected_version=0,
        )
        self.assertEqual(selected.method, "FIFO")
        self.assertEqual(selected.selected_by, self.actor)
        activated = await activate_costing_for_first_receipt(
            self.db, company_id=self.company_id, actor_id=self.actor,
        )
        self.assertTrue(activated.is_active)
        self.assertEqual(activated.method, "FIFO")
        self.assertEqual(
            (await self.db.execute(select(InventoryCostPolicy).where(
                InventoryCostPolicy.company_id == self.company_id
            ))).scalars().one().method,
            "FIFO",
        )


if __name__ == "__main__":
    unittest.main()
