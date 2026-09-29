"""Immutable supplier purchase-cost evidence: opt-in developer DB negative gate.

Run only against a named authorized DEVELOPMENT database and tenant that has
an existing PURCHASE_IN cost event. The attempted UPDATE is in a savepoint.
"""
from __future__ import annotations

import os
import unittest

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from database import engine
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    open_tenant_session,
)


@unittest.skipUnless(
    os.environ.get("WANASAH_C3_DB_GATE") == "1",
    "Requires explicit authorized developer DB opt-in.",
)
class ImmutableReceiptCostHistoryC3Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.company_id = int(os.environ["WANASAH_C3_TEST_TENANT"])
        self.token, self.db = await open_tenant_session(self.company_id)
        actual_db = await self.db.scalar(text("SELECT current_database()"))
        self.assertEqual(actual_db, os.environ["WANASAH_C3_EXPECTED_DB"])

    async def asyncTearDown(self):
        await self.db.rollback()
        await close_tenant_session(self.token, self.db)
        await engine.dispose()

    async def test_original_purchase_cost_event_rejects_rewrite_after_posting(self):
        before = (
            await self.db.execute(
                text(
                    "SELECT id, input_unit_cost, total_cost, method, batch_id "
                    "FROM inventory_cost_events "
                    "WHERE company_id=:company_id AND event_type='PURCHASE_IN' "
                    "ORDER BY id LIMIT 1"
                ),
                {"company_id": self.company_id},
            )
        ).mappings().first()
        self.assertIsNotNone(before, "Existing purchase event fixture is required")
        errors: list[str | None] = []
        try:
            async with self.db.begin_nested():
                # A same-value attempt still demonstrates permission + trigger protection.
                await self.db.execute(
                    text(
                        "UPDATE inventory_cost_events "
                        "SET input_unit_cost=input_unit_cost "
                        "WHERE company_id=:company_id AND id=:event_id"
                    ),
                    {"company_id": self.company_id, "event_id": before["id"]},
                )
        except SQLAlchemyError as error:
            errors.append(getattr(error.orig, "sqlstate", None))
        self.assertTrue(errors, "Posted purchase-cost source event was writable")
        self.assertIn(errors[0], {"42501", "P0001"}, errors)
        after = (
            await self.db.execute(
                text(
                    "SELECT id, input_unit_cost, total_cost, method, batch_id "
                    "FROM inventory_cost_events "
                    "WHERE company_id=:company_id AND id=:event_id"
                ),
                {"company_id": self.company_id, "event_id": before["id"]},
            )
        ).mappings().one()
        self.assertEqual(dict(before), dict(after))
        self.assertEqual(
            await self.db.scalar(
                text(
                    "SELECT COUNT(*) FROM inventory_cost_events "
                    "WHERE company_id=:company_id AND id=:event_id"
                ),
                {"company_id": self.company_id, "event_id": before["id"]},
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
