"""Per-batch UOM read deduplication: no cross-transaction state and fail closed.

Scoped, immutable reference lookup optimization for the same standard
simple-product, Excel import and pricing backend facade. DB accounting, RLS,
pricing, idempotency, error contracts and UOM conversion semantics do not
change. B3 synthetic database benchmark supplies separate runtime proof.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from domains.simple_products.service import (
    SimpleProductError,
    SimpleProductSpec,
    _load_shape_for_spec,
    _load_uom_code,
)


def spec(name="Test", package="CARTON", count=24):
    return SimpleProductSpec(
        name=name,
        units_per_package=count,
        package_uom_code=package,
    )


class ProductCreationBatchUomCacheB3Tests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_carton_uses_two_reference_queries_per_batch(self):
        each = SimpleNamespace(id=1, code="EACH")
        carton = SimpleNamespace(id=2, code="CARTON")
        db = SimpleNamespace(scalar=AsyncMock(side_effect=(each, carton)))
        cache = {}
        results = [
            await _load_shape_for_spec(db, spec=spec("Product " + str(i)), batch_cache=cache)
            for i in range(100)
        ]
        self.assertEqual(db.scalar.await_count, 2)
        self.assertEqual(set(cache), {"EACH", "CARTON"})
        self.assertTrue(all(x.base_uom is each and x.package_uom is carton for x in results))
        self.assertTrue(all(x.units_per_package == 24 for x in results))

    async def test_different_supported_package_codes_cached_independently(self):
        each = SimpleNamespace(id=1, code="EACH")
        carton = SimpleNamespace(id=2, code="CARTON")
        pack = SimpleNamespace(id=3, code="PACK")
        db = SimpleNamespace(scalar=AsyncMock(side_effect=(each, carton, pack)))
        cache = {}
        first = await _load_shape_for_spec(db, spec=spec("Carton"), batch_cache=cache)
        second = await _load_shape_for_spec(db, spec=spec("Pack", "PACK", 6), batch_cache=cache)
        repeated = await _load_shape_for_spec(db, spec=spec("Pack 2", "PACK", 12), batch_cache=cache)
        self.assertEqual(db.scalar.await_count, 3)
        self.assertIs(first.package_uom, carton)
        self.assertIs(second.package_uom, pack)
        self.assertIs(repeated.package_uom, pack)
        self.assertEqual((second.units_per_package, repeated.units_per_package), (6, 12))

    async def test_no_outer_package_still_resolves_only_base_once(self):
        each = SimpleNamespace(id=1, code="EACH")
        db = SimpleNamespace(scalar=AsyncMock(return_value=each))
        cache = {}
        a = await _load_shape_for_spec(db, spec=spec("No Package", None, 1), batch_cache=cache)
        b = await _load_shape_for_spec(db, spec=spec("No Package Two", None, 1), batch_cache=cache)
        self.assertEqual(db.scalar.await_count, 1)
        self.assertIsNone(a.package_uom)
        self.assertIsNone(b.package_uom)
        self.assertEqual((a.units_per_package, b.units_per_package), (1, 1))

    async def test_new_batch_cannot_read_previous_session_references(self):
        a_each = SimpleNamespace(id=1, code="EACH")
        a_carton = SimpleNamespace(id=2, code="CARTON")
        b_each = SimpleNamespace(id=91, code="EACH")
        b_carton = SimpleNamespace(id=92, code="CARTON")
        db_a = SimpleNamespace(scalar=AsyncMock(side_effect=(a_each, a_carton)))
        db_b = SimpleNamespace(scalar=AsyncMock(side_effect=(b_each, b_carton)))
        a = await _load_shape_for_spec(db_a, spec=spec(), batch_cache={})
        b = await _load_shape_for_spec(db_b, spec=spec(), batch_cache={})
        self.assertIs(a.base_uom, a_each)
        self.assertIs(b.base_uom, b_each)
        self.assertIsNot(a.package_uom, b.package_uom)
        self.assertEqual(db_a.scalar.await_count, 2)
        self.assertEqual(db_b.scalar.await_count, 2)

    async def test_missing_uom_is_not_cached_and_returns_original_error(self):
        each = SimpleNamespace(id=1, code="EACH")
        db = SimpleNamespace(scalar=AsyncMock(side_effect=(each, None, None)))
        cache = {}
        with self.assertRaises(SimpleProductError) as caught:
            await _load_shape_for_spec(db, spec=spec(), batch_cache=cache)
        self.assertEqual(caught.exception.code, "SIMPLE_PRODUCT_UOM_MISSING")
        self.assertEqual(caught.exception.context, {"uom_code": "CARTON"})
        self.assertEqual(set(cache), {"EACH"})
        with self.assertRaises(SimpleProductError):
            await _load_shape_for_spec(db, spec=spec(), batch_cache=cache)
        self.assertEqual(db.scalar.await_count, 3)
        self.assertEqual(set(cache), {"EACH"})

    async def test_legacy_non_cached_lookup_preserves_one_sql_per_call(self):
        each = SimpleNamespace(id=1, code="EACH")
        db = SimpleNamespace(scalar=AsyncMock(return_value=each))
        first = await _load_uom_code(db, "each")
        second = await _load_uom_code(db, " EACH ")
        self.assertIs(first, each)
        self.assertIs(second, each)
        self.assertEqual(db.scalar.await_count, 2)


if __name__ == "__main__":
    unittest.main()
