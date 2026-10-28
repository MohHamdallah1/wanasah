"""Bounded read-only route/source stock discovery, including a real 50k catalog."""
import os
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select

from api import dispatch
from database import get_db
from domains import dispatch_adjust_load_read as reads
from domains.authorization.backoffice_access import BackofficeCapabilityAccessRejected
from domains.inventory_vehicle_load.service import vehicle_load_source_inventory
from models import InventoryBalance, InventoryMovement, ProductBatch, ProductLocation, ProductVariant
from product_lifecycle import DEFAULT_PRODUCT_LOCATION_FLAGS
from tests import test_dispatch_adjust_load_uom as adjustment_fixture


@unittest.skipUnless(os.environ.get("WANASAH_ADJUST_LOAD_PG_GATE") == "1", "disposable PostgreSQL gate not enabled")
class AdjustLoadSearchPostgres(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.context = adjustment_fixture.ActiveRouteAdjustLoadPostgres("runTest")
        await self.context.asyncSetUp()
        self.addAsyncCleanup(self.context.seed.asyncTearDown)
        self.db, self.company = self.context.db, self.context.company
        self.pid, self.wh = self.context.pid, self.context.wh

    async def read(self, **query):
        return await dispatch.get_route_live_inventory(self.context.rid, self.db, self.context.seed.owner.access(self.db), **query)

    async def seed_candidates(self, count):
        """Batched fixture inserts only: no operational DB, no product-per-row reads."""
        template = self.context.seed.variant
        ids = []
        for start in range(0, count, 1000):
            rows = [dict(company_id=self.company, product_id=template.product_id, base_uom_id=template.base_uom_id,
                name=f"Scale {index:05}", sku=f"SEARCH-{index}", lifecycle_status="ACTIVE", operational_hold="NONE",
                published_at=template.published_at, lot_control_mode="NONE", expiry_control_mode="NONE", packs_per_carton=1)
                for index in range(start, min(start + 1000, count))]
            batch_ids = (await self.db.scalars(insert(ProductVariant).returning(ProductVariant.id), rows)).all()
            ids.extend(batch_ids)
            await self.db.execute(insert(ProductLocation), [dict(company_id=self.company, location_id=self.wh,
                product_variant_id=pid, operational_flags=dict(DEFAULT_PRODUCT_LOCATION_FLAGS), created_by=self.context.actor_id) for pid in batch_ids])
            batches = (await self.db.execute(insert(ProductBatch).returning(ProductBatch.product_variant_id, ProductBatch.id),
                [dict(company_id=self.company, product_variant_id=pid, batch_number="SEARCH", disposition="RELEASED", is_active=True) for pid in batch_ids])).all()
            await self.db.execute(insert(InventoryBalance), [dict(company_id=self.company, location_id=self.wh,
                product_variant_id=pid, batch_id=bid, stock_status="AVAILABLE", on_hand_quantity=5, reserved_quantity=0) for pid, bid in batches])
        await self.db.commit()
        return ids

    async def test_50k_eligible_catalog_opens_only_custody_and_bounds_search_before_uom(self):
        ids = await self.seed_candidates(50_000)
        with patch.object(reads, "route_load_uom_metadata", wraps=reads.route_load_uom_metadata) as metadata:
            loaded = await self.read()
            self.assertEqual([(row["product_id"], row["current_base_quantity"]) for row in loaded], [(str(self.pid), Decimal(25))])
            self.assertEqual(loaded[0]["display_factor_to_base"], "8")
            self.assertEqual(metadata.call_args.kwargs["variant_ids"], [self.pid])
            found = await self.read(search="Scale")
            self.assertEqual(len(found), 80)
            self.assertEqual(len(metadata.call_args.kwargs["variant_ids"]), 80)
            self.assertEqual(len(await self.read(search="Scale", limit=3)), 3)
            needle = await self.read(search="Scale 49999")
            self.assertEqual([row["product_id"] for row in needle], [str(ids[-1])])
            self.assertEqual(needle[0]["current_base_quantity"], 0)
        # Neither discovery path can change physical custody, reservations or movements.
        self.assertEqual(await self.context.physical(), 25)
        self.assertEqual(await self.context.physical(self.wh), 100)
        self.assertEqual((await self.db.scalars(select(InventoryMovement.id).where(InventoryMovement.company_id == self.company))).all(), [])

    async def test_pending_only_rows_are_included_even_after_hold_and_no_vehicle_balance(self):
        await self.context.bind()
        await self.context.adjust(8)
        # The pending product remains discoverable independent of lifecycle filtering.
        self.context.seed.variant.operational_hold = "RECALL"
        await self.db.commit()
        with patch.object(reads, "route_vehicle_base_totals", AsyncMock(return_value={})):
            rows = await self.read()
        self.assertEqual([(row["product_id"], row["pending_base_quantity"]) for row in rows], [(str(self.pid), Decimal(8))])

    async def test_warehouse_eligibility_and_legacy_vehicle_search_share_one_authority(self):
        ids = await self.seed_candidates(2)
        new_id = (await self.read(search="Scale 00000"))[0]["product_id"]
        assignment = await self.db.scalar(select(ProductLocation).where(ProductLocation.company_id == self.company,
            ProductLocation.location_id == self.wh, ProductLocation.product_variant_id == int(new_id)))
        assignment.operational_flags = {**DEFAULT_PRODUCT_LOCATION_FLAGS, "outbound_enabled": False}
        await self.db.commit()
        self.assertEqual(await self.read(search="Scale 00000"), [])
        # Read-only hydration is bounded to requested eligible or actually loaded IDs.
        self.assertEqual(await self.read(product_ids=[int(new_id)]), [])
        other = await self.db.scalar(select(ProductVariant).where(ProductVariant.id == ids[1]))
        other.operational_hold = "RECALL"
        self.context.seed.variant.operational_hold = "RECALL"
        await self.db.commit()
        self.assertEqual(await self.read(search="Scale"), [])
        self.assertEqual([row["product_id"] for row in await self.read()], [str(self.pid)])
        self.assertEqual([row["product_id"] for row in await self.read(product_ids=[self.pid])], [str(self.pid)])
        # SALES_HOLD also blocks ROUTE_LOAD_NEW under the existing matrix.
        other.operational_hold = "SALES_HOLD"
        await self.db.commit()
        self.assertEqual(await self.read(search="Scale"), [])
        other.operational_hold = "NONE"
        await self.db.commit()
        self.assertEqual(len(await self.read(search="Scale")), 1)
        self.context.route.status = "closed"
        await self.db.commit()
        legacy = await vehicle_load_source_inventory(self.db, access=self.context.seed.owner.access(self.db),
            vehicle_id=self.context.seed.vehicle_id, warehouse_id=self.wh, search="Scale", cursor=None, limit=80)
        self.assertEqual([str(item["product_variant_id"]) for item in legacy["items"]], [str(other.id)])
        self.context.route.source_location_id = self.context.seed.warehouse_b_id
        await self.db.commit()
        self.assertEqual(await self.read(search="Scale"), [])

    async def test_search_rejects_other_tenants_and_missing_location_capability(self):
        real = self.context.seed.owner.access(self.db)
        for forbidden in (self.wh, self.context.vid):
            async def require(code, location_id=None, **kwargs):
                if location_id == forbidden:
                    raise BackofficeCapabilityAccessRejected("denied")
                return await real.require(code, location_id, **kwargs)
            denied = SimpleNamespace(company_id=self.company, db=self.db, require=require)
            with self.subTest(location=forbidden), self.assertRaises(HTTPException) as caught:
                await dispatch.get_route_live_inventory(self.context.rid, self.db, denied, search="Scale")
            self.assertEqual(caught.exception.status_code, 403)
        foreign = SimpleNamespace(company_id=self.company + 999999, db=self.db)
        with self.assertRaises(HTTPException) as caught:
            await dispatch.get_route_live_inventory(self.context.rid, self.db, foreign, search="Scale")
        self.assertEqual(caught.exception.status_code, 404)

    async def test_batch_and_free_stock_authority_excludes_unavailable_candidates(self):
        [pid] = await self.seed_candidates(1)
        balance = await self.db.scalar(select(InventoryBalance).where(InventoryBalance.company_id == self.company,
            InventoryBalance.location_id == self.wh, InventoryBalance.product_variant_id == pid))
        batch = await self.db.scalar(select(ProductBatch).where(ProductBatch.company_id == self.company,
            ProductBatch.product_variant_id == pid))
        for field, value, original in (("reserved_quantity", 5, 0), ("stock_status", "QUARANTINED", "AVAILABLE")):
            setattr(balance, field, value)
            await self.db.commit()
            self.assertEqual(await self.read(search="Scale"), [])
            setattr(balance, field, original)
        batch.is_active = False
        await self.db.commit()
        self.assertEqual(await self.read(search="Scale"), [])
        batch.is_active = True
        await self.db.commit()
        self.assertEqual(len(await self.read(search="Scale")), 1)

    async def test_short_invalid_search_and_http_query_bounds_fail_safely(self):
        with patch.object(reads, "warehouse_load_candidate_ids_statement", side_effect=AssertionError("invalid search must not scan catalog")):
            for query in ("", "a", " ", "a\x00", "%"):
                self.assertEqual(await self.read(search=query), [])
        app = FastAPI()
        app.include_router(dispatch.router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[dispatch._dispatch_read_access] = lambda: self.context.seed.owner.access(self.db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for query in ("limit=81&search=Scale", "limit=0&search=Scale", "search=" + "x" * 101,
                          "&".join("product_ids=1" for _ in range(81))):
                response = await client.get(f"/dispatch/route/{self.context.rid}/live_inventory?{query}")
                self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
