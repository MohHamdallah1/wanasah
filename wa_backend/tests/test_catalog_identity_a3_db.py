"""A3 live developer-DB negative gates for master, SKU and batch boundaries.

Opt in only with WANASAH_A3_DB_GATE=1, WANASAH_A3_EXPECTED_DB,
WANASAH_A3_TENANT_ID, WANASAH_A3_FOREIGN_TENANT_ID,
and WANASAH_A3_FOREIGN_PARENT_ID. Never run by default or on production.

Every attempted invalid INSERT runs inside a savepoint and is rolled back.
"""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    open_tenant_session,
)
from domains.simple_products.service import (
    SimpleProductError,
    SimpleProductSpec,
    _resolve_family,
)
from models import Product


@unittest.skipUnless(
    os.getenv("WANASAH_A3_DB_GATE") == "1",
    "Requires explicit opt-in for an authorized development database.",
)
class CatalogIdentityA3DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.expected_db = os.environ["WANASAH_A3_EXPECTED_DB"]
        self.tenant_id = int(os.environ["WANASAH_A3_TENANT_ID"])
        self.foreign_tenant_id = int(os.environ["WANASAH_A3_FOREIGN_TENANT_ID"])
        self.foreign_parent_id = int(os.environ["WANASAH_A3_FOREIGN_PARENT_ID"])
        self.assertNotEqual(self.tenant_id, self.foreign_tenant_id)
        self.token, self.db = await open_tenant_session(self.tenant_id)
        actual_db = await self.db.scalar(text("SELECT current_database()"))
        self.assertEqual(actual_db, self.expected_db)
        current_tenant = await self.db.scalar(
            text("SELECT current_setting('app.current_tenant', true)")
        )
        self.assertEqual(current_tenant, str(self.tenant_id))

    async def asyncTearDown(self):
        # Never leave transaction data behind, even after an assertion fails.
        await self.db.rollback()
        await close_tenant_session(self.token, self.db)

    async def _assert_fk_rejected(self, query: str, params: dict, constraint: str):
        try:
            async with self.db.begin_nested():
                await self.db.execute(text(query), params)
        except IntegrityError as exc:
            self.assertEqual(
                getattr(exc.orig, "sqlstate", None), "23503",
                f"Expected FK violation {constraint}: {exc}",
            )
            self.assertIn(constraint, str(exc.orig))
        else:
            self.fail(f"Invalid cross-identity INSERT was accepted: {constraint}")

    async def test_deployed_sku_foreign_keys_and_forced_rls(self):
        expected = {
            "fk_product_variant_tenant_product": ("product_variants", "products"),
            "fk_product_batch_tenant_variant": ("product_batches", "product_variants"),
            "fk_inv_balance_variant_batch": ("inventory_balances", "product_batches"),
            "fk_inventory_cost_state_tenant_variant": (
                "inventory_cost_states", "product_variants",
            ),
            "fk_inventory_cost_event_tenant_variant": (
                "inventory_cost_events", "product_variants",
            ),
            "fk_price_book_entry_tenant_variant": (
                "price_book_entries", "product_variants",
            ),
            "fk_visit_item_tenant_variant": ("visit_items", "product_variants"),
        }
        constraints = (
            await self.db.execute(
                text(
                    "SELECT conname, conrelid::regclass::text AS source, "
                    "pg_get_constraintdef(oid) AS definition "
                    "FROM pg_constraint WHERE conname = ANY(:names)"
                ),
                {"names": list(expected)},
            )
        ).mappings().all()
        self.assertEqual({r["conname"] for r in constraints}, set(expected))
        for row in constraints:
            source, target = expected[row["conname"]]
            self.assertEqual(row["source"], source)
            self.assertIn(f"REFERENCES {target}(", row["definition"])
            self.assertIn("company_id", row["definition"])
            if row["conname"] != "fk_product_variant_tenant_product":
                self.assertIn("product_variant_id", row["definition"])

        rls = (
            await self.db.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname = ANY(:tables)"
                ),
                {"tables": [
                    "products", "product_variants", "product_batches",
                    "inventory_balances", "inventory_cost_states",
                    "price_book_entries", "visit_items",
                ]},
            )
        ).mappings().all()
        self.assertEqual(len(rls), 7)
        self.assertTrue(
            all(r["relrowsecurity"] and r["relforcerowsecurity"] for r in rls)
        )

    async def test_other_tenant_parent_is_invisible_to_existing_family(self):
        # Verify the requested foreign ID actually exists in its owner scope.
        foreign_token, foreign_db = await open_tenant_session(
            self.foreign_tenant_id
        )
        try:
            foreign = await foreign_db.scalar(
                select(Product.id).where(
                    Product.company_id == self.foreign_tenant_id,
                    Product.id == self.foreign_parent_id,
                )
            )
            self.assertEqual(foreign, self.foreign_parent_id)
        finally:
            await foreign_db.rollback()
            await close_tenant_session(foreign_token, foreign_db)

        self.assertIsNone(
            await self.db.scalar(
                select(Product.id).where(
                    Product.company_id == self.tenant_id,
                    Product.id == self.foreign_parent_id,
                )
            )
        )
        with self.assertRaises(SimpleProductError) as caught:
            await _resolve_family(
                self.db,
                actor=SimpleNamespace(company_id=self.tenant_id),
                spec=SimpleProductSpec(
                    name="A3 negative cross-company identity",
                    units_per_package=1,
                    family_mode="existing",
                    family_id=self.foreign_parent_id,
                ),
                request_id=uuid4(),
                index=1,
            )
        self.assertEqual(caught.exception.code, "SIMPLE_PRODUCT_FAMILY_NOT_FOUND")
        self.assertEqual(caught.exception.status_code, 404)

    async def test_composite_fk_rejects_cross_company_master_link(self):
        base_uom_id = await self.db.scalar(
            text(
                "SELECT base_uom_id FROM product_variants "
                "WHERE company_id = :company_id ORDER BY id LIMIT 1"
            ),
            {"company_id": self.tenant_id},
        )
        self.assertIsNotNone(base_uom_id)
        await self._assert_fk_rejected(
            "INSERT INTO product_variants "
            "(company_id, product_id, base_uom_id, name, sku, created_at, updated_at) "
            "VALUES (:company_id, :foreign_parent_id, :base_uom_id, "
            ":name, :sku, now(), now())",
            {
                "company_id": self.tenant_id,
                "foreign_parent_id": self.foreign_parent_id,
                "base_uom_id": base_uom_id,
                "name": "A3 invalid FK fixture",
                "sku": "A3-INVALID-" + uuid4().hex,
            },
            "fk_product_variant_tenant_product",
        )

    async def test_wrong_variant_batch_cannot_enter_inventory_balance(self):
        row = (
            await self.db.execute(
                text(
                    "SELECT b.location_id, b.batch_id, b.product_variant_id, "
                    " (SELECT v.id FROM product_variants v "
                    "  WHERE v.company_id = b.company_id "
                    "    AND v.id <> b.product_variant_id "
                    "  ORDER BY v.id LIMIT 1) AS other_variant_id "
                    "FROM inventory_balances b "
                    "WHERE b.company_id = :company_id "
                    "ORDER BY b.id LIMIT 1"
                ),
                {"company_id": self.tenant_id},
            )
        ).mappings().first()
        if row is None or row["other_variant_id"] is None:
            self.fail("Developer fixture missing two variants and a stock balance.")
        await self._assert_fk_rejected(
            "INSERT INTO inventory_balances "
            "(company_id, location_id, product_variant_id, batch_id, last_updated) "
            "VALUES (:company_id, :location_id, :wrong_variant_id, "
            ":batch_id, now())",
            {
                "company_id": self.tenant_id,
                "location_id": row["location_id"],
                "wrong_variant_id": row["other_variant_id"],
                "batch_id": row["batch_id"],
            },
            "fk_inv_balance_variant_batch",
        )


if __name__ == "__main__":
    unittest.main()
