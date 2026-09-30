"""Real PostgreSQL/RLS authority tests for bounded Pricing draft batches.

Opt-in only. Synthetic tenant 2. Every test runs in an external transaction
with SQLAlchemy SAVEPOINT commits and an outer ROLLBACK, never alters source.
"""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from context import tenant_context
from database import engine
from domains.pricing.core import PricingError
from domains.pricing.publishing import (
    create_draft_entries_bulk,
    create_price_book,
    create_publication,
    publish_publication,
)
from models import Driver, PriceBookEntry, ProductUomConversion, UOM


@unittest.skipUnless(
    os.environ.get("WANASAH_B3_PRICING_DB_GATE") == "1",
    "Opt-in required for synthetic dev DB",
)
class BulkPricingB3DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.token = tenant_context.set(2)
        self.conn = await engine.connect()
        self.outer = await self.conn.begin()
        self.db = AsyncSession(
            bind=self.conn, expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        await self.db.execute(
            text("SELECT set_config('app.current_tenant', '2', true)")
        )
        self.assertEqual(
            await self.db.scalar(text("SELECT current_database()")),
            os.environ["WANASAH_B3_PRICING_EXPECTED_DB"],
        )
        self.assertEqual(
            await self.db.scalar(text(
                "SELECT COUNT(*) FROM price_books WHERE company_id=2"
            )), 0,
        )
        self.actor_id = int(await self.db.scalar(
            select(Driver.id).where(
                Driver.company_id == 2, Driver.is_admin.is_(True)
            ).limit(1)
        ))
        self.each = int(await self.db.scalar(
            select(UOM.id).where(UOM.code == "EACH")
        ))
        self.carton = int(await self.db.scalar(
            select(UOM.id).where(UOM.code == "CARTON")
        ))
        self.at = datetime.now(timezone.utc)

    async def asyncTearDown(self):
        try:
            await self.db.close()
            if self.outer.is_active:
                await self.outer.rollback()
        finally:
            await self.conn.close()
            tenant_context.reset(self.token)
            await engine.dispose()

    async def _publication(self):
        book = await create_price_book(
            self.db, company_id=2, actor_id=self.actor_id,
            code="B3-TEST-" + uuid4().hex[:12],
            name="Temporary batch pricing", currency_code="JOD",
        )
        return await create_publication(
            self.db, company_id=2, actor_id=self.actor_id,
            book_id=book.id, expected_book_version=book.version,
            effective_at=self.at, request_id=uuid4(),
        )

    def _entry(self, variant_id=1, uom_id=None, amount="3.1234567"):
        return {
            "product_variant_id": variant_id,
            "uom_id": self.each if uom_id is None else uom_id,
            "amount": amount,
            "effective_from": self.at,
            "effective_to": None,
            "priority": 0,
            "metadata": {"managed_by": "simple_products", "source": "B3"},
        }

    async def test_batch_two_uoms_publish_and_version_are_preserved(self):
        pub = await self._publication()
        self.db.add(ProductUomConversion(
            company_id=2, product_variant_id=1,
            from_uom_id=self.carton, to_uom_id=self.each,
            numerator=Decimal("24"), denominator=Decimal("1"),
            quantity_scale=0,
        ))
        await self.db.flush()
        start_version = int(pub.version)
        rows = await create_draft_entries_bulk(
            self.db, company_id=2, publication_id=int(pub.id),
            expected_publication_version=start_version,
            entries=[
                self._entry(amount="3.1234567"),
                self._entry(uom_id=self.carton, amount="72"),
            ],
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(pub.version, start_version + 2)
        self.assertEqual([str(row.amount) for row in rows],
                         ["3.123457", "72.000000"])
        self.assertTrue(all(row.is_published is False for row in rows))
        self.assertEqual({row.uom_id for row in rows},
                         {self.each, self.carton})
        self.assertTrue(all(row.entry_metadata["source"] == "B3" for row in rows))

        await publish_publication(
            self.db, company_id=2, actor_id=self.actor_id,
            publication_id=pub.id, expected_version=pub.version,
        )
        self.assertEqual(pub.status, "PUBLISHED")
        self.assertEqual(pub.version, start_version + 3)
        current = (await self.db.execute(
            select(PriceBookEntry).where(
                PriceBookEntry.company_id == 2,
                PriceBookEntry.publication_id == pub.id,
            )
        )).scalars().all()
        self.assertEqual(len(current), 2)
        self.assertTrue(all(row.is_published for row in current))

    async def test_bulk_invalid_variant_cannot_insert_partial_prices(self):
        pub = await self._publication()
        old_version = pub.version
        with self.assertRaises(PricingError) as caught:
            await create_draft_entries_bulk(
                self.db, company_id=2,
                publication_id=pub.id,
                expected_publication_version=old_version,
                entries=[self._entry(), self._entry(variant_id=999999)],
            )
        self.assertEqual(caught.exception.code, "PRICE_UOM_MAPPING_UNRESOLVED")
        self.assertEqual(pub.version, old_version)
        self.assertEqual(await self.db.scalar(
            text("SELECT COUNT(*) FROM price_book_entries "
                 "WHERE company_id=2 AND publication_id=:p"),
            {"p": pub.id},
        ), 0)

    async def test_unmapped_package_and_negative_price_fail_closed(self):
        pub = await self._publication()
        wrong = await create_draft_entries_bulk(
            self.db, company_id=2,
            publication_id=pub.id,
            expected_publication_version=pub.version,
            entries=[],
        )
        self.assertEqual(wrong, [])
        self.assertEqual(pub.version, 1)
        with self.assertRaises(PricingError) as bad_uom:
            await create_draft_entries_bulk(
                self.db, company_id=2,
                publication_id=pub.id,
                expected_publication_version=pub.version,
                entries=[self._entry(uom_id=self.carton)],
            )
        self.assertEqual(bad_uom.exception.code, "PRICE_UOM_MAPPING_UNRESOLVED")
        with self.assertRaises(PricingError) as bad_money:
            await create_draft_entries_bulk(
                self.db, company_id=2,
                publication_id=pub.id,
                expected_publication_version=pub.version,
                entries=[self._entry(amount="-1")],
            )
        self.assertEqual(bad_money.exception.code, "PRICE_AMOUNT_INVALID")
        self.assertEqual(await self.db.scalar(
            text("SELECT COUNT(*) FROM price_book_entries "
                 "WHERE company_id=2 AND publication_id=:p"),
            {"p": pub.id},
        ), 0)

    async def test_new_sku_price_skips_only_proven_empty_history(self):
        """No predecessor => no history rewrite, but price remains published."""
        pub = await self._publication()
        await create_draft_entries_bulk(
            self.db, company_id=2, publication_id=pub.id,
            expected_publication_version=pub.version,
            entries=[self._entry(amount="4.25")],
        )
        sql_text = []
        def capture(_conn, _cursor, statement, _params, _context, _many):
            if "fresh_pairs AS MATERIALIZED" in statement or "new_starts AS" in statement:
                sql_text.append(statement)
        event.listen(engine.sync_engine, "before_cursor_execute", capture)
        try:
            await publish_publication(
                self.db, company_id=2, actor_id=self.actor_id,
                publication_id=pub.id, expected_version=pub.version,
            )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", capture)
        self.assertEqual(pub.status, "PUBLISHED")
        self.assertEqual(
            sum("fresh_pairs AS MATERIALIZED" in item for item in sql_text), 1,
        )
        # Preserve D6's bounded index-probe plan. Unbounded correlated EXISTS
        # can be de-correlated into one full old-book scan per fresh pair.
        self.assertEqual(
            sum(
                "CROSS JOIN LATERAL" in item and "LIMIT 1" in item
                for item in sql_text
            ), 1,
        )
        self.assertEqual(
            sum("new_starts AS" in item for item in sql_text), 0,
        )
        recorded = (await self.db.execute(
            select(PriceBookEntry).where(
                PriceBookEntry.company_id == 2,
                PriceBookEntry.publication_id == pub.id,
            )
        )).scalars().all()
        self.assertEqual(len(recorded), 1)
        self.assertTrue(recorded[0].is_published)
        self.assertEqual(recorded[0].amount, Decimal("4.25"))

    async def test_later_publication_closes_previous_window_without_overlap(self):
        """Materialized current-price check cannot skip effective-date closure."""
        first=await self._publication()
        prices=await create_draft_entries_bulk(
            self.db,company_id=2,publication_id=first.id,
            expected_publication_version=first.version,
            entries=[self._entry(amount="3.0")],
        )
        self.assertEqual(len(prices),1)
        await publish_publication(
            self.db,company_id=2,actor_id=self.actor_id,
            publication_id=first.id,expected_version=first.version,
        )
        next_start=self.at+timedelta(hours=3)
        second=await create_publication(
            self.db,company_id=2,actor_id=self.actor_id,
            book_id=first.price_book_id,
            expected_book_version=1,effective_at=next_start,
            request_id=uuid4(),
        )
        replacement=self._entry(amount="5.0")
        replacement["effective_from"]=next_start
        await create_draft_entries_bulk(
            self.db,company_id=2,publication_id=second.id,
            expected_publication_version=second.version,
            entries=[replacement],
        )
        seen_history = []
        def capture_revision(_conn, _cursor, statement, _params, _context, _many):
            if "new_starts AS" in statement:
                seen_history.append(statement)
        event.listen(engine.sync_engine, "before_cursor_execute", capture_revision)
        try:
            await publish_publication(
                self.db,company_id=2,actor_id=self.actor_id,
                publication_id=second.id,expected_version=second.version,
            )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", capture_revision)
        self.assertGreaterEqual(len(seen_history), 2)
        published=(await self.db.execute(select(PriceBookEntry).where(
            PriceBookEntry.company_id==2,
            PriceBookEntry.price_book_id==first.price_book_id,
            PriceBookEntry.product_variant_id==1,
            PriceBookEntry.is_published.is_(True),
        ).order_by(PriceBookEntry.publication_id))).scalars().all()
        self.assertEqual(len(published),2)
        old,new=published
        # The predecessor is closed through an authoritative raw PostgreSQL
        # UPDATE, which intentionally bypasses SQLAlchemy's session identity
        # map. Refresh the ORM instance before inspecting its persisted range.
        await self.db.refresh(old)
        await self.db.refresh(new)
        self.assertEqual(old.effectivity.upper,next_start)
        self.assertIsNone(new.effectivity.upper)
        self.assertEqual(new.effectivity.lower,next_start)
        self.assertEqual((old.amount,new.amount),
                         (Decimal("3"),Decimal("5")))
        self.assertFalse(old.effectivity.upper_inc)

    async def test_version_conflict_and_boundedness(self):
        pub = await self._publication()
        with self.assertRaises(PricingError) as err:
            await create_draft_entries_bulk(
                self.db, company_id=2,
                publication_id=pub.id,
                expected_publication_version=42,
                entries=[self._entry()],
            )
        self.assertEqual(err.exception.code, "PRICE_PUBLICATION_VERSION_CONFLICT")
        with self.assertRaises(ValueError):
            await create_draft_entries_bulk(
                self.db, company_id=2,
                publication_id=pub.id,
                expected_publication_version=pub.version,
                entries=[self._entry()] * 201,
            )

    async def test_effective_date_before_publication_rejected(self):
        pub = await self._publication()
        bad = self._entry()
        bad["effective_from"] = self.at - timedelta(seconds=1)
        with self.assertRaises(PricingError) as err:
            await create_draft_entries_bulk(
                self.db, company_id=2,
                publication_id=pub.id,
                expected_publication_version=pub.version,
                entries=[bad],
            )
        self.assertEqual(err.exception.code, "PRICE_EFFECTIVITY_BEFORE_PUBLICATION")


if __name__ == "__main__":
    unittest.main()
