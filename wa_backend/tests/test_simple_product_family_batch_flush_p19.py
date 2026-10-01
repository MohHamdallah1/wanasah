"""Source-focused flush-contract checks for independent legacy import masters."""
from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from domains.product_tracking import ProductTrackingDefaults
from domains.simple_products.service import (
    SimpleProductError,
    SimpleProductSpec,
    _BatchFamilyLookup,
    _plan_unique_implicit_families,
    _prefill_unique_implicit_families,
    _resolve_family,
)
from models import Product


def spec(name: str, *, family_name=None, family_mode=None, family_id=None):
    return SimpleProductSpec(
        name=name, family_name=family_name, family_mode=family_mode,
        family_id=family_id,
        units_per_package=1, package_uom_code=None,
        unit_price=Decimal("1"),
    )


class ImplicitFamilyBatchFlushTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.actor = SimpleNamespace(id=7, company_id=43)
        self.db = SimpleNamespace(
            add_all=MagicMock(), add=MagicMock(), flush=AsyncMock(),
        )
        self.request_id = uuid4()
        self.assigned = []

        async def assign_database_ids():
            for n, row in enumerate(self.assigned, start=1001):
                row.id = n

        self.db.flush.side_effect = assign_database_ids
        self.db.add_all.side_effect = lambda rows: self.assigned.extend(rows)
        self.db.add.side_effect = self.assigned.append

    async def prefill(self, specs, lookup, *, start_index=1):
        # Model inputs already read and validated by earlier ordinary rows.
        await _prefill_unique_implicit_families(
            self.db, actor=self.actor, request_id=self.request_id,
            specs=specs, lookup=lookup,
            candidates=_plan_unique_implicit_families(specs),
            start_index=start_index,
            uom_cache={"EACH": SimpleNamespace(id=1, code="EACH")},
            tracking_defaults=ProductTrackingDefaults(
                lot_control_mode="NONE", expiry_control_mode="NONE",
            ),
            per_spec_barcodes=[(None, None, False) for _ in specs],
        )

    async def fill(self, specs, *, cached=None):
        names = frozenset(
            (row.family_name or row.name).strip().lower()
            for row in specs if row.family_mode is None
        )
        lookup = _BatchFamilyLookup(names, cached or {})
        await self.prefill(specs, lookup)
        return lookup

    async def test_validated_implicit_run_flushes_once_with_own_ids(self):
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
        self.db.flush.assert_not_awaited()
        await self.prefill(rows, lookup, start_index=4)
        self.db.flush.assert_awaited_once()
        self.assertEqual([p.name for p in self.assigned], ["Group B"])
        self.assertEqual(lookup.matches["already here"], [existing])
        self.assertEqual(lookup.matches.get("group a"), None)
        self.assertEqual(lookup.matches["group b"][0].id, 1001)

    async def test_explicit_rows_do_not_disable_unrelated_implicit_prefill(self):
        rows = [
            spec("Independent", family_mode="none"),
            spec("Fresh SKU", family_mode="new", family_name="Fresh family"),
            spec("Existing SKU", family_mode="existing", family_id=91),
            spec("Legacy ID SKU", family_id=91),
            spec("Legacy A"),
            spec("Legacy B"),
        ]
        lookup = await self.fill(rows)
        self.db.flush.assert_not_awaited()
        # Only after the ordinary loop has processed the four explicit rows.
        await self.prefill(rows, lookup, start_index=5)
        self.db.flush.assert_awaited_once()
        self.assertEqual([p.name for p in self.assigned], ["Legacy A", "Legacy B"])
        self.assertEqual([p.code[-5:] for p in self.assigned], ["00005", "00006"])
        self.assertNotIn("independent", lookup.matches)
        self.assertNotIn("fresh family", lookup.matches)

    async def test_explicit_name_overlap_stays_on_ordered_resolver(self):
        for mode in ("none", "new"):
            for explicit_first in (True, False):
                with self.subTest(mode=mode, explicit_first=explicit_first):
                    self.assigned.clear()
                    self.db.flush.reset_mock()
                    explicit = spec(
                        "Shared" if mode == "none" else "Explicit SKU",
                        family_mode=mode,
                        family_name="Shared" if mode == "new" else None,
                    )
                    implicit = spec("Implicit SKU", family_name=" shared ")
                    rows = (
                        [explicit, implicit] if explicit_first
                        else [implicit, explicit]
                    )
                    lookup = await self.fill(rows + [spec("Unrelated")])
                    self.assertEqual(self.assigned, [])
                    self.db.flush.assert_not_awaited()
                    self.assertNotIn("shared", lookup.matches)

                    async def resolve(item, index):
                        return await _resolve_family(
                            self.db, actor=self.actor, request_id=self.request_id,
                            spec=item, index=index, batch_lookup=lookup,
                        )

                    first = await resolve(rows[0], 1)
                    if mode == "new" and not explicit_first:
                        with self.assertRaises(SimpleProductError) as caught:
                            await resolve(rows[1], 2)
                        self.assertEqual(
                            caught.exception.code,
                            "SIMPLE_PRODUCT_FAMILY_NAME_CONFLICT",
                        )
                    else:
                        second = await resolve(rows[1], 2)
                        if mode == "none" and not explicit_first:
                            self.assertNotEqual(first.id, second.id)
                            self.assertEqual(len(lookup.matches["shared"]), 2)
                        else:
                            self.assertIs(first, second)

    async def test_two_none_masters_still_make_later_implicit_name_ambiguous(self):
        rows = [
            spec("Shared", family_mode="none"),
            spec("SHARED", family_mode="none"),
            spec("Implicit", family_name="shared"),
            spec("Unrelated"),
        ]
        lookup = await self.fill(rows)
        self.assertEqual(self.assigned, [])
        self.db.flush.assert_not_awaited()
        for index, item in enumerate(rows[:2], start=1):
            await _resolve_family(
                self.db, actor=self.actor, request_id=self.request_id,
                spec=item, index=index, batch_lookup=lookup,
            )
        with self.assertRaises(SimpleProductError) as caught:
            await _resolve_family(
                self.db, actor=self.actor, request_id=self.request_id,
                spec=rows[2], index=3, batch_lookup=lookup,
            )
        self.assertEqual(
            caught.exception.code, "SIMPLE_PRODUCT_FAMILY_NAME_AMBIGUOUS",
        )

    async def test_invalid_name_keeps_row_level_validation_as_authority(self):
        rows = [spec("X" * 201), spec("Healthy")]
        lookup = await self.fill(rows)
        self.db.flush.assert_not_awaited()
        self.assertEqual(self.assigned, [])
        self.assertEqual(lookup.matches, {})

    async def test_failed_batch_flush_does_not_publish_uncommitted_parent_cache(self):
        self.db.flush.side_effect = RuntimeError("synthetic flush abort")
        lookup = _BatchFamilyLookup(frozenset({"sku"}), {})
        with self.assertRaisesRegex(RuntimeError, "synthetic flush abort"):
            await self.prefill([spec("SKU")], lookup)
        self.assertEqual(lookup.matches, {})


if __name__ == "__main__":
    unittest.main()
