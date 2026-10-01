"""Source-focused flush-contract checks for independent legacy import masters."""
from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from domains.simple_products.service import (
    SimpleProductSpec,
    _BatchFamilyLookup,
    _prefill_unique_implicit_families,
)
from models import Product


def spec(name: str, *, family_name=None, family_mode=None):
    return SimpleProductSpec(
        name=name, family_name=family_name, family_mode=family_mode,
        units_per_package=1, package_uom_code=None,
        unit_price=Decimal("1"),
    )


class ImplicitFamilyBatchFlushTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.actor = SimpleNamespace(id=7, company_id=43)
        self.db = SimpleNamespace(add_all=MagicMock(), flush=AsyncMock())
        self.request_id = uuid4()
        self.assigned = []

        async def assign_database_ids():
            for n, row in enumerate(self.assigned, start=1001):
                row.id = n

        self.db.flush.side_effect = assign_database_ids
        self.db.add_all.side_effect = lambda rows: self.assigned.extend(rows)

    async def fill(self, specs, *, cached=None):
        names = frozenset(
            (row.family_name or row.name).lower()
            for row in specs if row.family_mode is None
        )
        lookup = _BatchFamilyLookup(names, cached or {})
        await _prefill_unique_implicit_families(
            self.db, actor=self.actor, request_id=self.request_id,
            specs=specs, lookup=lookup,
        )
        return lookup

    async def test_100_distinct_unmatched_import_names_flush_once_with_own_ids(self):
        rows = [spec(f"SKU {i:03d}") for i in range(100)]
        lookup = await self.fill(rows)
        self.db.flush.assert_awaited_once()
        self.db.add_all.assert_called_once()
        self.assertEqual(len(self.assigned), 100)
        self.assertEqual([row.id for row in self.assigned], list(range(1001, 1101)))
        self.assertEqual(
            [lookup.matches[f"sku {i:03d}"][0].id for i in range(100)],
            list(range(1001, 1101)),
        )
        self.assertEqual(
            len({row.code for row in self.assigned}), 100,
        )
        self.assertTrue(all(row.company_id == 43 for row in self.assigned))

    async def test_existing_and_repeated_family_names_keep_original_resolver(self):
        existing = Product(id=91, company_id=43, code="EXISTS", name="Already here")
        rows = [
            spec("One", family_name="Group A"),
            spec("Two", family_name="Group A"),
            spec("Three", family_name="Already here"),
            spec("Four", family_name="Group B"),
        ]
        lookup = await self.fill(rows, cached={"already here": [existing]})
        self.db.flush.assert_awaited_once()
        self.assertEqual([p.name for p in self.assigned], ["Group B"])
        self.assertEqual(lookup.matches["already here"], [existing])
        self.assertEqual(lookup.matches.get("group a"), None)
        self.assertEqual(lookup.matches["group b"][0].id, 1001)

    async def test_explicit_family_intent_skips_fast_path_entirely(self):
        rows = [
            spec("Legacy"),
            spec("Independent", family_mode="none"),
        ]
        await self.fill(rows)
        self.db.flush.assert_not_awaited()
        self.db.add_all.assert_not_called()

    async def test_invalid_name_keeps_row_level_validation_as_authority(self):
        rows = [spec("X" * 201), spec("Healthy")]
        lookup = await self.fill(rows)
        self.db.flush.assert_awaited_once()
        self.assertEqual([p.name for p in self.assigned], ["Healthy"])
        self.assertNotIn("x" * 201, lookup.matches)

    async def test_failed_batch_flush_does_not_publish_uncommitted_parent_cache(self):
        self.db.flush.side_effect = RuntimeError("synthetic flush abort")
        lookup = _BatchFamilyLookup(frozenset({"sku"}), {})
        with self.assertRaisesRegex(RuntimeError, "synthetic flush abort"):
            await _prefill_unique_implicit_families(
                self.db, actor=self.actor, request_id=self.request_id,
                specs=[spec("SKU")], lookup=lookup,
            )
        self.assertEqual(lookup.matches, {})


if __name__ == "__main__":
    unittest.main()
