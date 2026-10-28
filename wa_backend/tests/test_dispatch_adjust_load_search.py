"""Bounded read-only route/source stock discovery, including a real 50k catalog."""
import os
import json
from uuid import uuid4
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, insert, select

from api import dispatch, dispatch_products
from database import get_db
from domains import dispatch_adjust_load_read as reads
from domains.authorization.backoffice_access import BackofficeCapabilityAccessRejected
from domains.inventory_vehicle_load.service import vehicle_load_source_inventory
from models import InventoryBalance, InventoryMovement, ProductBatch, ProductLocation, ProductVariant, utc_now
from domains.dispatch_product_discovery import dispatch_product_page
from domains.dispatch_product_cursor import DispatchProductCursorError
from schemas import DispatchInitResponse
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
        raw = await self.read_page(**query)
        return [item["load"] for item in raw["items"]] if isinstance(raw, dict) else raw

    async def read_page(self, **query):
        return await dispatch.get_route_live_inventory(self.context.rid, self.db, self.context.seed.owner.access(self.db), **query)

    async def discovery(self, purpose="LOAD", **query):
        return await dispatch_products.search_dispatch_products(purpose=purpose, search=query.pop("search", "Scale"),
            cursor=query.pop("cursor", None), limit=query.pop("limit", 80), route_id=query.pop("route_id", self.context.rid),
            warehouse_id=None, vehicle_id=None, db=self.db, access=self.context.seed.owner.access(self.db), **query)

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
        before = DispatchInitResponse.model_validate(await dispatch.dispatch_init(self.db, self.context.seed.owner.access(self.db))).model_dump(mode="json")
        ids = await self.seed_candidates(50_000)
        statements = []
        def record(conn, cursor, statement, parameters, context, many):
            statements.append(statement.lower())
        engine = self.db.bind.sync_engine
        event.listen(engine, "before_cursor_execute", record)
        try:
            after = DispatchInitResponse.model_validate(await dispatch.dispatch_init(self.db, self.context.seed.owner.access(self.db))).model_dump(mode="json")
        finally:
            event.remove(engine, "before_cursor_execute", record)
        self.assertNotIn("products", after)
        self.assertEqual(before, after)
        self.assertEqual(len(json.dumps(before)), len(json.dumps(after)))
        self.assertFalse(any("product_variants" in sql for sql in statements), statements)
        with patch.object(reads, "route_load_uom_metadata", wraps=reads.route_load_uom_metadata) as metadata:
            loaded = await self.read()
            self.assertEqual([(row["product_id"], row["current_base_quantity"]) for row in loaded], [(str(self.pid), Decimal(25))])
            self.assertEqual(loaded[0]["display_factor_to_base"], "8")
            self.assertEqual(metadata.call_args.kwargs["variant_ids"], [self.pid])
            automatic = await self.read_page(search="")
            self.assertEqual(len(automatic["items"]), 80)
            self.assertTrue(automatic["has_more"])
            self.assertEqual(len(metadata.call_args.kwargs["variant_ids"]), 80)
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

    async def test_200_results_80_80_40_unique_and_last_can_be_adjusted(self):
        ids = await self.seed_candidates(200)
        balance = await self.db.scalar(select(InventoryBalance).where(InventoryBalance.company_id == self.company,
            InventoryBalance.location_id == self.wh, InventoryBalance.product_variant_id == self.pid))
        balance.on_hand_quantity = 0  # Custody stays pinned separately; only 200 eligible source rows.
        await self.db.commit()
        for query in ("", "Scale"):
            seen, cursor = [], None
            for size in (80, 80, 40):
                page = await self.read_page(search=query, cursor=cursor)
                self.assertEqual(len(page["items"]), size)
                self.assertEqual(page["has_more"], size == 80)
                seen.extend(int(item["id"]) for item in page["items"])
                cursor = page["next_cursor"]
            self.assertIsNone(cursor)
            self.assertEqual(seen, ids)
            self.assertEqual(len(set(seen)), 200)
        self.assertEqual(len((await self.discovery(search=""))["items"]), 80)
        last = page["items"][-1]
        self.assertEqual(last["load"]["current_base_quantity"], 0)
        request_id = uuid4()
        result = await self.context.adjust(rows=[dict(product_id=int(last["id"]), delta_base="5")], request_id=request_id)
        self.assertEqual(result["mode"], "DIRECT")
        self.assertEqual(await self.context.adjust(rows=[dict(product_id=int(last["id"]), delta_base="5")], request_id=request_id), result)
        qty = await self.db.scalar(select(InventoryBalance.on_hand_quantity).where(InventoryBalance.company_id == self.company,
            InventoryBalance.location_id == self.context.vid, InventoryBalance.product_variant_id == ids[-1]))
        self.assertEqual(qty, 5)

    async def test_blank_source_page_omits_zero_stock_but_retains_vehicle_custody(self):
        [positive, zero] = await self.seed_candidates(2)
        balances = (await self.db.scalars(select(InventoryBalance).where(InventoryBalance.company_id == self.company,
            InventoryBalance.location_id == self.wh, InventoryBalance.product_variant_id.in_([self.pid, zero])))).all()
        for balance in balances:
            balance.on_hand_quantity = 0
        await self.db.commit()
        self.assertEqual([row["product_id"] for row in await self.read()], [str(self.pid)])
        self.assertEqual((await self.read())[0]["current_base_quantity"], 25)
        for query in ("", " ", "s", "Scale"):
            self.assertEqual([item["id"] for item in (await self.read_page(search=query))["items"]], [str(positive)])
        # The zero stock population is still eligible demand for Shortages.
        self.assertEqual([item["id"] for item in (await self.discovery("SHORTAGE"))["items"]], [str(positive), str(zero)])
        first = await self.read_page(search="", limit=1)
        self.assertFalse(first["has_more"])
        # A held loaded item remains readable for unload, never an ordinary add candidate.
        self.context.seed.variant.operational_hold = "RECALL"
        await self.db.commit()
        self.assertEqual([row["product_id"] for row in await self.read()], [str(self.pid)])
        self.assertEqual([item["id"] for item in (await self.discovery(search=""))["items"]], [str(positive)])

    async def test_cursor_is_bound_to_tenant_source_route_query_and_eligibility(self):
        await self.seed_candidates(3)
        first = await self.read_page(search="Scale", limit=1)
        cursor = first["next_cursor"]
        self.assertTrue(cursor)
        # Both load pickers share the same endpoint-independent domain cursor.
        same = await self.discovery(search="Scale", cursor=cursor, limit=1)
        self.assertNotEqual(first["items"][0]["id"], same["items"][0]["id"])
        for query in (dict(search="Other", cursor=cursor), dict(search="Scale", cursor=cursor + "x")):
            with self.assertRaises(HTTPException) as caught:
                await self.read_page(**query)
            self.assertEqual(caught.exception.detail["code"], "DISPATCH_PRODUCT_CURSOR_INVALID")
        for changed in (dict(company_id=self.company + 1), dict(route_id=self.context.rid + 1),
                        dict(warehouse_id=self.context.seed.warehouse_b_id), dict(purpose="SHORTAGE")):
            args = dict(company_id=self.company, purpose="LOAD", search="Scale", cursor=cursor,
                route_id=self.context.rid, warehouse_id=self.wh, vehicle_id=self.context.seed.vehicle_id,
                work_session_id=None, vehicle_location_id=self.context.vid, driver_id=self.context.actor_id)
            args.update(changed)
            with self.assertRaises(DispatchProductCursorError):
                await dispatch_product_page(self.db, **args)
        self.context.route.source_location_id = self.context.seed.warehouse_b_id
        await self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            await self.read_page(search="Scale", cursor=cursor)
        self.assertEqual(caught.exception.status_code, 400)

    async def test_shortage_uses_replenishment_without_warehouse_stock(self):
        [pid] = await self.seed_candidates(1)
        balance = await self.db.scalar(select(InventoryBalance).where(InventoryBalance.company_id == self.company,
            InventoryBalance.location_id == self.wh, InventoryBalance.product_variant_id == pid))
        balance.on_hand_quantity = 0
        await self.db.commit()
        self.assertEqual((await self.discovery())["items"], [])
        shortage = await self.discovery("SHORTAGE")
        self.assertEqual([item["id"] for item in shortage["items"]], [str(pid)])
        self.assertIsNone(shortage["items"][0]["load"])
        variant = await self.db.get(ProductVariant, pid)
        for state, hold in (("ACTIVE", "RECALL"), ("ACTIVE", "SALES_HOLD"), ("ARCHIVED", "NONE")):
            variant.lifecycle_status, variant.operational_hold = state, hold
            variant.archived_at = utc_now() if state == "ARCHIVED" else None
            variant.retired_at = variant.archived_at
            await self.db.commit()
            self.assertEqual((await self.discovery("SHORTAGE"))["items"], [])

    async def test_launch_and_shortage_discovery_enforce_canonical_permission_and_tenant(self):
        await self.seed_candidates(2)
        kwargs = dict(purpose="LOAD", search="Scale", cursor=None, limit=80, route_id=None,
            warehouse_id=self.wh, vehicle_id=self.context.seed.vehicle_id, db=self.db)
        real = self.context.seed.owner.access(self.db)
        page = await dispatch_products.search_dispatch_products(**kwargs, access=real)
        self.assertEqual(len(page["items"]), 2)
        for forbidden in (self.wh, self.context.vid):
            async def require(code, location_id=None, **extra):
                if location_id == forbidden:
                    raise BackofficeCapabilityAccessRejected("denied")
                return await real.require(code, location_id, **extra)
            denied = SimpleNamespace(company_id=self.company, db=self.db, require=require)
            with self.subTest(location=forbidden), self.assertRaises(HTTPException) as caught:
                await dispatch_products.search_dispatch_products(**kwargs, access=denied)
            self.assertEqual(caught.exception.status_code, 403)
        foreign = SimpleNamespace(company_id=self.company + 999999, db=self.db)
        with self.assertRaises(HTTPException) as caught:
            await dispatch_products.search_dispatch_products(**kwargs, access=foreign)
        self.assertEqual(caught.exception.status_code, 404)
        calls = []
        async def reject_shortage(code, **extra):
            calls.append(code)
            raise BackofficeCapabilityAccessRejected("denied")
        denied = SimpleNamespace(company_id=self.company, db=self.db, require=reject_shortage)
        with self.assertRaises(HTTPException) as caught:
            await dispatch_products.search_dispatch_products(**{**kwargs, "purpose": "SHORTAGE"}, access=denied)
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(calls, ["shortage.create"])

    async def test_http_page_transport_and_query_validation(self):
        await self.seed_candidates(3)
        app = FastAPI()
        app.include_router(dispatch.router)
        access = self.context.seed.owner.access(self.db)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[dispatch._dispatch_read_access] = lambda: access
        app.dependency_overrides[dispatch_products.get_current_backoffice_capability_access] = lambda: access
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for url in (f"/dispatch/route/{self.context.rid}/live_inventory?search=Scale&limit=2",
                        f"/dispatch/products?purpose=LOAD&vehicle_id={self.context.seed.vehicle_id}&warehouse_id={self.wh}&search=Scale&limit=2",
                        "/dispatch/products?purpose=SHORTAGE&search=Scale&limit=2"):
                response = await client.get(url)
                self.assertEqual(response.status_code, 200, response.text)
                page = response.json()
                self.assertEqual(len(page["items"]), 2)
                self.assertTrue(page["has_more"])
                self.assertIsInstance(page["next_cursor"], str)
                if "SHORTAGE" not in url:
                    self.assertEqual(page["items"][0]["load"]["current_base_quantity"], "0")
                else:
                    self.assertIsNone(page["items"][0]["load"])
                response2 = await client.get(url + "&cursor=" + page["next_cursor"])
                self.assertEqual(response2.status_code, 200, response2.text)
                self.assertEqual(len(response2.json()["items"]), 1)
                self.assertFalse(response2.json()["has_more"])
            for query in ("purpose=LOAD&limit=81", "purpose=INVALID", "purpose=SHORTAGE&search=" + "x" * 101):
                self.assertEqual((await client.get("/dispatch/products?" + query)).status_code, 422)
            self.assertEqual((await client.get("/dispatch/products?purpose=LOAD&search=Scale")).json()["detail"]["code"],
                "DISPATCH_PRODUCT_CONTEXT_REQUIRED")

    async def test_each_direct_plus_minus_five_has_one_movement_and_replay_none(self):
        for delta, expected in ((5, 30), (-5, 25)):
            before = await self.db.scalar(select(func.count()).select_from(InventoryMovement).where(InventoryMovement.company_id == self.company))
            request_id = uuid4()
            response = await self.context.adjust(delta, request_id=request_id)
            self.assertEqual(await self.context.physical(), expected)
            self.assertEqual(await self.context.adjust(delta, request_id=request_id), response)
            after = await self.db.scalar(select(func.count()).select_from(InventoryMovement).where(InventoryMovement.company_id == self.company))
            self.assertEqual(after - before, 1)

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
        with patch("domains.dispatch_product_discovery.warehouse_load_candidate_ids_statement", side_effect=AssertionError("invalid search must not scan catalog")):
            for query in ("a\x00", "x" * 101):
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
