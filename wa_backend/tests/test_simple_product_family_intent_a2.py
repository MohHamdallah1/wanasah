"""A2: regression contract for explicit master creation and 200-char SKU names."""
from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from api.simple_products import (
    SimpleProductCreate,
    _family_cursor,
    _family_next_cursor,
    _request_hash,
)
from domains.simple_products.service import (
    SimpleProductError,
    SimpleProductSpec,
    _BatchFamilyLookup,
    _resolve_family,
)
from models import Product


class FamilyIntentA2Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.actor = SimpleNamespace(id=3, company_id=38)
        self.session = SimpleNamespace(
            execute=AsyncMock(),
            scalar=AsyncMock(),
            scalars=AsyncMock(),
            flush=AsyncMock(),
            add=MagicMock(),
        )
        # SQLAlchemy AsyncSession.scalars() is async, but ScalarResult.all() is sync.
        self.session.scalars.return_value.all = MagicMock(return_value=[])

    def spec(self, name="Chips", **options):
        return SimpleProductSpec(
            name=name,
            units_per_package=1,
            package_uom_code=None,
            unit_price=1,
            **options,
        )

    async def resolve(self, spec):
        return await _resolve_family(
            self.session,
            actor=self.actor,
            spec=spec,
            request_id=uuid4(),
            index=1,
        )

    async def test_none_creates_independent_master_without_name_lookup(self):
        parent = await self.resolve(self.spec(family_mode="none"))
        self.assertIsInstance(parent, Product)
        self.assertEqual(parent.name, "Chips")
        self.assertEqual(parent.company_id, 38)
        self.session.add.assert_called_once_with(parent)
        self.session.scalars.assert_not_called()
        self.session.scalar.assert_not_called()

    async def test_none_supports_200_character_product_name(self):
        parent = await self.resolve(
            self.spec("A" * 200, family_mode="none")
        )
        self.assertEqual(len(parent.name), 200)

    async def test_new_rejects_existing_exact_name_instead_of_reusing(self):
        existing = Product(id=71, company_id=38, code="FAM-A", name="Chips")
        self.session.scalars.return_value.all.return_value = [existing]
        with self.assertRaises(SimpleProductError) as ctx:
            await self.resolve(
                self.spec(family_mode="new", family_name="Chips")
            )
        self.assertEqual(ctx.exception.code, "SIMPLE_PRODUCT_FAMILY_NAME_CONFLICT")
        self.session.add.assert_not_called()

    async def test_new_creates_only_when_name_unused(self):
        self.session.scalars.return_value.all.return_value = []
        parent = await self.resolve(
            self.spec(family_mode="new", family_name="Fresh")
        )
        self.assertEqual(parent.name, "Fresh")
        self.session.add.assert_called_once_with(parent)

    async def test_existing_requires_explicit_id(self):
        with self.assertRaises(SimpleProductError) as ctx:
            await self.resolve(self.spec(family_mode="existing"))
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_existing_uses_tenant_scoped_id(self):
        existing = Product(id=71, company_id=38, code="FAM-A", name="Chips")
        self.session.scalar.return_value = existing
        parent = await self.resolve(
            self.spec(family_mode="existing", family_id=71)
        )
        self.assertIs(parent, existing)
        self.session.add.assert_not_called()

    async def test_batch_id_lookup_is_shared_after_selection_validation(self):
        parent = Product(id=71, company_id=38, code="FAM-A", name="Chips")
        self.session.scalar.return_value = parent
        lookup = _BatchFamilyLookup(frozenset(), {})
        for index in range(1, 101):
            item = self.spec(
                family_mode="existing" if index % 2 else None, family_id=71,
            )
            resolved = await _resolve_family(
                self.session, actor=self.actor, spec=item,
                request_id=uuid4(), index=index, batch_lookup=lookup,
            )
            self.assertIs(resolved, parent)
        self.session.scalar.assert_awaited_once()
        statement = self.session.scalar.await_args.args[0]
        self.assertEqual(
            set(statement.compile().params.values()), {38, 71},
        )
        self.assertEqual(lookup.by_id, {(38, 71): parent})

        for item in (
            self.spec(family_mode="none", family_id=71),
            self.spec(family_mode="new", family_id=71, family_name="Fresh"),
            self.spec(family_id=71, family_name="Chips"),
        ):
            with self.assertRaises(SimpleProductError) as caught:
                await _resolve_family(
                    self.session, actor=self.actor, spec=item,
                    request_id=uuid4(), index=101, batch_lookup=lookup,
                )
            self.assertEqual(caught.exception.status_code, 422)
        self.session.scalar.assert_awaited_once()

    async def test_id_cache_does_not_hide_missing_or_foreign_family(self):
        parent = Product(id=71, company_id=38, code="FAM-A", name="Chips")
        lookup = _BatchFamilyLookup(frozenset(), {}, {(38, 71): parent})
        self.session.scalar.return_value = None
        foreign_actor = SimpleNamespace(id=8, company_id=43)
        for actor, family_id in ((foreign_actor, 71), (self.actor, 72)):
            with self.assertRaises(SimpleProductError) as caught:
                await _resolve_family(
                    self.session, actor=actor,
                    spec=self.spec(family_mode="existing", family_id=family_id),
                    request_id=uuid4(), index=1, batch_lookup=lookup,
                )
            self.assertEqual(caught.exception.code, "SIMPLE_PRODUCT_FAMILY_NOT_FOUND")
            self.assertEqual(caught.exception.status_code, 404)
            self.assertEqual(lookup.by_id, {(38, 71): parent})
        self.assertEqual(self.session.scalar.await_count, 2)

    async def test_fresh_batch_lookup_reloads_after_previous_attempt(self):
        parent = Product(id=71, company_id=38, code="FAM-A", name="Chips")
        self.session.scalar.side_effect = [parent, None]
        item = self.spec(family_mode="existing", family_id=71)
        first = _BatchFamilyLookup(frozenset(), {})
        await _resolve_family(
            self.session, actor=self.actor, spec=item,
            request_id=uuid4(), index=1, batch_lookup=first,
        )
        retry = _BatchFamilyLookup(frozenset(), {})
        with self.assertRaises(SimpleProductError) as caught:
            await _resolve_family(
                self.session, actor=self.actor, spec=item,
                request_id=uuid4(), index=1, batch_lookup=retry,
            )
        self.assertEqual(caught.exception.code, "SIMPLE_PRODUCT_FAMILY_NOT_FOUND")
        self.assertEqual(retry.by_id, {})
        self.assertEqual(self.session.scalar.await_count, 2)

    async def test_none_and_new_reject_conflicting_payload_fields(self):
        for opts in (
            {"family_mode": "none", "family_name": "Chips"},
            {"family_mode": "none", "family_id": 71},
            {"family_mode": "new", "family_id": 71, "family_name": "Chips"},
            {"family_mode": "new"},
        ):
            with self.subTest(opts=opts):
                self.session.add.reset_mock()
                with self.assertRaises(SimpleProductError) as ctx:
                    await self.resolve(self.spec(**opts))
                self.assertEqual(ctx.exception.status_code, 422)
                self.session.add.assert_not_called()

    async def test_legacy_omitted_family_mode_preserves_name_reuse(self):
        existing = Product(id=71, company_id=38, code="FAM-A", name="Chips")
        self.session.scalars.return_value.all.return_value = [existing]
        parent = await self.resolve(self.spec())
        self.assertIs(parent, existing)
        self.session.add.assert_not_called()

    async def test_legacy_omitted_family_mode_accepts_200_chars(self):
        self.session.scalars.return_value.all.return_value = []
        parent = await self.resolve(self.spec("A" * 200))
        self.assertEqual(len(parent.name), 200)


class FamilyIntentDtoA2Tests(unittest.TestCase):
    def payload(self, **options):
        values = {
            "request_id": uuid4(),
            "name": "Chips",
            "package_uom_code": None,
            "unit_price": "1",
        }
        values.update(options)
        return SimpleProductCreate(**values)

    def test_new_none_existing_are_explicit_and_guarded(self):
        for mode, family_id, family_name in (
            ("none", None, None),
            ("existing", 4, None),
            ("new", None, "Fresh"),
        ):
            payload = self.payload(
                family_mode=mode,
                family_id=family_id,
                family_name=family_name,
            )
            self.assertEqual(payload.family_mode, mode)

        for kwargs in (
            {"family_mode": "none", "family_name": "Chips"},
            {"family_mode": "new", "family_id": 7, "family_name": "New"},
            {"family_mode": "new"},
            {"family_mode": "existing"},
            {"family_mode": "existing", "family_id": 7, "family_name": "X"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.payload(**kwargs)

    def test_legacy_hash_does_not_change_for_omitted_mode(self):
        payload = self.payload()
        legacy = payload.model_dump(
            mode="json", exclude={"request_id", "family_mode"}
        )
        encoded = json.dumps(
            legacy, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        self.assertEqual(
            _request_hash(payload),
            hashlib.sha256(encoded).hexdigest(),
        )

    def test_200_name_and_explicit_family_supported(self):
        payload = self.payload(
            name="A" * 200,
            family_mode="new",
            family_name="F" * 200,
        )
        self.assertEqual(len(payload.name), 200)
        self.assertEqual(len(payload.family_name), 200)


class FamilyCursorA2Tests(unittest.TestCase):
    def test_200_character_family_cursor_round_trip(self):
        for count in (150, 151, 200):
            with self.subTest(count=count):
                name = "ع" * count
                cursor = _family_next_cursor(
                    sort_name=name,
                    family_id=78,
                    company_id=38,
                    search=None,
                    limit=30,
                )
                after_name, after_id = _family_cursor(
                    cursor,
                    company_id=38,
                    search=None,
                    limit=30,
                )
                self.assertEqual((after_name, after_id), (name, 78))
        with self.assertRaises(ValueError):
            _family_next_cursor(
                sort_name="A" * 201,
                family_id=78,
                company_id=38,
                search=None,
                limit=30,
            )


if __name__ == "__main__":
    unittest.main()
