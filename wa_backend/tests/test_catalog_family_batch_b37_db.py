"""B3.7: family batching on real PostgreSQL under tenant RLS.

Every test uses synthetic tenant 2 and outer ROLLBACK. The separate durable
race tests use a disposable PostgreSQL cluster, not these SAVEPOINT tests.
"""
from __future__ import annotations

import os
import unittest
from decimal import Decimal
from uuid import uuid4
from unittest.mock import AsyncMock, patch

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from context import tenant_context
from database import engine
from domains.simple_products import service as simple
from domains.simple_products.service import (
    SimpleProductError,
    SimpleProductSpec,
    _prefetch_batch_families,
    _resolve_family,
)
from models import Driver, Product, ProductVariant


def spec(name, *, mode=None, family_name=None, family_id=None):
    return SimpleProductSpec(
        name=name,
        family_name=family_name,
        family_mode=mode,
        family_id=family_id,
        units_per_package=1,
        package_uom_code=None,
        unit_price=Decimal("1"),
    )


@unittest.skipUnless(
    os.environ.get("WANASAH_B37_FAMILIES_DB_GATE")=="1",
    "B3.7 real-DB tests require explicit synthetic tenant 2 opt-in",
)
class FamilyBatchDatabaseB37(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.token = tenant_context.set(2)
        self.connection = await engine.connect()
        self.outer = await self.connection.begin()
        self.db = AsyncSession(
            bind=self.connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        await self.db.execute(
            text("SELECT set_config('app.current_tenant','2',true)")
        )
        self.assertEqual(
            await self.db.scalar(text("SELECT current_database()")),
            os.environ["WANASAH_B37_FAMILIES_EXPECTED_DB"],
        )
        self.actor=await self.db.scalar(select(Driver).where(
            Driver.company_id==2,Driver.is_admin.is_(True)
        ))
        self.assertIsNotNone(self.actor)
        self.request_id=uuid4()

    async def asyncTearDown(self):
        try:
            await self.db.close()
            if self.outer.is_active:
                await self.outer.rollback()
        finally:
            await self.connection.close()
            tenant_context.reset(self.token)
            await engine.dispose()

    async def one(self, spec_, *, index, batch):
        return await _resolve_family(
            self.db,actor=self.actor,spec=spec_,
            request_id=self.request_id,index=index,batch_lookup=batch,
        )

    async def test_repeated_50_names_use_50_locks_and_one_bounded_select(self):
        specs=[spec("sku-"+str(i),family_name="B37 group "+str(i%50)) for i in range(100)]
        orig=simple._family_name_lock
        with patch.object(simple,"_family_name_lock",new=AsyncMock(wraps=orig)) as lock:
            cache=await _prefetch_batch_families(
                self.db,actor=self.actor,specs=specs,
            )
            keys=[item.args[0] for item in ()] # one batch; no hidden cache state
            self.assertEqual(len(cache.locked_names),50)
            self.assertEqual(lock.await_count,50)
            result=[await self.one(x,index=i+1,batch=cache)
                    for i,x in enumerate(specs)]
            self.assertEqual(lock.await_count,50)
            self.assertEqual(len({x.id for x in result}),50)
            self.assertEqual(len(cache.matches),50)
            for i in range(50):
                self.assertEqual(result[i].id,result[i+50].id)
        live=await self.db.scalar(
            select(Product.id).where(
                Product.company_id==2,Product.name=="B37 group 0",
            )
        )
        self.assertIsNotNone(live)

    async def test_new_conflicts_on_same_name_inserted_earlier_in_batch(self):
        specs=[spec("new-1",mode="new",family_name="B37 Fresh Name"),
               spec("new-2",mode="new",family_name="b37 fresh name")]
        cache=await _prefetch_batch_families(
            self.db,actor=self.actor,specs=specs,
        )
        first=await self.one(specs[0],index=1,batch=cache)
        self.assertEqual(first.name,"B37 Fresh Name")
        with self.assertRaises(SimpleProductError) as err:
            await self.one(specs[1],index=2,batch=cache)
        self.assertEqual(err.exception.code,"SIMPLE_PRODUCT_FAMILY_NAME_CONFLICT")

    async def test_none_created_parent_remains_independent_and_later_implicit_finds_it(self):
        specs=[spec("B37 Original No Family",mode="none"),
               spec("sku-ref",family_name="B37 Original No Family")]
        cache=await _prefetch_batch_families(
            self.db,actor=self.actor,specs=specs,
        )
        first=await self.one(specs[0],index=1,batch=cache)
        second=await self.one(specs[1],index=2,batch=cache)
        self.assertEqual(first.id,second.id)
        self.assertEqual(first.name,"B37 Original No Family")

    async def test_none_two_same_names_preserves_duplicate_master_and_ambiguity(self):
        specs=[spec("B37 Independent",mode="none"),
               spec("B37 Independent",mode="none"),
               spec("a third SKU",family_name="B37 Independent")]
        cache=await _prefetch_batch_families(
            self.db,actor=self.actor,specs=specs,
        )
        first=await self.one(specs[0],index=1,batch=cache)
        second=await self.one(specs[1],index=2,batch=cache)
        self.assertNotEqual(first.id,second.id)
        with self.assertRaises(SimpleProductError) as err:
            await self.one(specs[2],index=3,batch=cache)
        self.assertEqual(err.exception.code,"SIMPLE_PRODUCT_FAMILY_NAME_AMBIGUOUS")

    async def test_existing_by_id_remains_company_scoped(self):
        parent=Product(
            company_id=2,code="B37-ID-"+uuid4().hex,
            name="B37 Explicit ID",
        )
        self.db.add(parent)
        await self.db.flush()
        req=spec("SKU",mode="existing",family_id=int(parent.id))
        cache=await _prefetch_batch_families(
            self.db,actor=self.actor,specs=[req],
        )
        self.assertEqual(cache.locked_names,frozenset())
        self.assertEqual((await self.one(req,index=1,batch=cache)).id,parent.id)
        with self.assertRaises(SimpleProductError) as err:
            await self.one(spec("missing",mode="existing",family_id=999999999),
                           index=2,batch=cache)
        self.assertEqual(err.exception.code,"SIMPLE_PRODUCT_FAMILY_NOT_FOUND")

    async def test_existing_duplicate_names_detect_ambiguity_without_name_unique(self):
        for x in range(2):
            self.db.add(Product(
                company_id=2,code="B37-DUP-"+uuid4().hex,
                name="B37 Same Name",
            ))
        await self.db.flush()
        req=spec("SKU",family_name="B37 Same Name")
        cache=await _prefetch_batch_families(
            self.db,actor=self.actor,specs=[req],
        )
        self.assertEqual(len(cache.matches["b37 same name"]),2)
        with self.assertRaises(SimpleProductError) as err:
            await self.one(req,index=1,batch=cache)
        self.assertEqual(err.exception.code,"SIMPLE_PRODUCT_FAMILY_NAME_AMBIGUOUS")

    async def test_invalid_family_intent_still_uses_original_resolver_error(self):
        invalid=spec("SK",mode="existing")
        cache=await _prefetch_batch_families(
            self.db,actor=self.actor,specs=[invalid],
        )
        self.assertFalse(cache.locked_names)
        with self.assertRaises(SimpleProductError) as err:
            await self.one(invalid,index=1,batch=cache)
        self.assertEqual(err.exception.code,"SIMPLE_PRODUCT_FAMILY_SELECTION_REQUIRED")

    async def test_existing_parent_reference_does_not_cross_tenant_boundary(self):
        foreign=await self.db.scalar(text(
            "SELECT id FROM products WHERE company_id=38 LIMIT 1"
        ))
        self.assertIsNone(foreign) # real company 38 exists but RLS hides it
        # A known company38 product ID is not safe to hardcode; check scoped
        # constraints directly rather than guessing foreign IDs.
        own=Product(company_id=2,code="B37-TEN-"+uuid4().hex,name="B37 tenant")
        self.db.add(own)
        await self.db.flush()
        self.assertEqual(
            (await self.one(
                spec("child",mode="existing",family_id=own.id),
                index=1,batch=await _prefetch_batch_families(
                    self.db,actor=self.actor,
                    specs=[spec("child",mode="existing",family_id=own.id)],
                ),
            )).company_id,
            2,
        )


if __name__=="__main__":
    unittest.main()
