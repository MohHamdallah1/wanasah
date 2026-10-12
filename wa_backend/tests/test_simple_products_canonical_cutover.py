"""Focused Simple Products canonical HTTP and SQL scope acceptance.

Synthetic SQLite grant/location/catalog data execute actual canonical read seams.
Pricing/product creation is mocked at its public seam. PostgreSQL SQL is compiled
for locking predicates; these checks do not claim concurrent locking/RLS evidence.
"""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Column, MetaData, Table, create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
with patch.dict(os.environ, {
    "ENVIRONMENT": "test",
    "SECRET_KEY": "SimpleProductsCanonicalSyntheticSecret123456789012345678901234567890",
    "DATABASE_URL": "postgresql+asyncpg://simple_unit@127.0.0.1:1/simple_unit",
    "DATABASE_URL_MIGRATION": "postgresql+asyncpg://simple_admin@127.0.0.1:1/simple_unit",
}):
    from api import simple_products as module
    from api.authentication import dependencies as canonical
from database import get_db
from domains.auth_sessions.context import DashboardRequestContext, FieldRequestContext
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.inventory_batch_restrictions import load_batch_restrictions
from domains.inventory_catalog_presence import InventoryCatalogPresenceForbidden, variant_ids_present_in_all_warehouses
from domains.identity.migration.models import IdentityLegacyDriverMap
from models import Driver, InventoryBalance, InventoryLocation, Permission, Product, ProductBatch, ProductVariant, UserLocationAccess, UserRole, role_permissions


def sql(query):
    return str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class ReadSession:
    def __init__(self, session):
        self.session, self.statements = session, []
        self.legacy_flag = None
        self.commit, self.rollback = AsyncMock(), AsyncMock()
        self.begin, self.add = Mock(), Mock()

    async def execute(self, query):
        self.statements.append(query)
        result = self.session.execute(query)
        columns = getattr(query, "column_descriptions", ())
        if self.legacy_flag is not None and columns and columns[0].get("entity") is Driver:
            row = result.scalar_one_or_none()
            # The mapped SQL row has no flag dependency. Only the negative-proof
            # sentinel returned at the operational seam carries the obsolete flag.
            operational = None if row is None else SimpleNamespace(
                id=row.id, company_id=row.company_id, is_active=row.is_active,
                is_admin=self.legacy_flag,
            )
            return Mock(scalar_one_or_none=Mock(return_value=operational))
        return result

    async def scalar(self, query):
        self.statements.append(query)
        return self.session.scalar(query)

    async def scalars(self, query):
        self.statements.append(query)
        return self.session.scalars(query)


class SimpleProductsCanonicalCutoverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        metadata = MetaData()
        self.tables = {}
        definitions = (
            (Driver, None), (IdentityLegacyDriverMap, None), (Product, None), (ProductVariant, None),
            (InventoryLocation, "id company_id name location_type is_active vehicle_id"),
            (InventoryBalance, "id company_id location_id product_variant_id batch_id on_hand_quantity"),
            (ProductBatch, "id company_id product_variant_id disposition disposition_reason disposition_revision"),
            (Permission, "id code"), (UserRole, "company_id driver_id role_id"),
            (UserLocationAccess, "company_id driver_id role_id location_id"),
        )
        for model, names in definitions:
            original = model.__table__
            columns = list(original.columns) if names is None else [original.c[n] for n in names.split()]
            self.tables[original.name] = Table(
                original.name, metadata, *(Column(c.name, c.type, primary_key=c.primary_key) for c in columns),
            )
        self.tables[role_permissions.name] = Table(role_permissions.name, metadata,
            *(Column(c.name, c.type) for c in role_permissions.columns))
        self.engine = create_engine("sqlite://")
        metadata.create_all(self.engine)
        self.connection = self.engine.connect()
        self.session = Session(bind=self.connection, autoflush=False)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.connection.close)
        self.addCleanup(self.session.close)
        self.db = ReadSession(self.session)
        self.role_id = 0
        self.codes = ("catalog.read", "catalog.manage", "catalog.publish", "pricing.manage",
                      "pricing.view", "inventory.read")
        for identifier, code in enumerate(self.codes, 1):
            self.insert(Permission, id=identifier, code=code)
        self.insert(Driver, id=303, company_id=7, is_active=True)
        self.insert(IdentityLegacyDriverMap, company_id=7, legacy_driver_id=303,
                    classification="BACKOFFICE_ONLY", backoffice_principal_id=101, backoffice_user_id=202)
        for identifier, company, name in ((1, 7, "Alpha"), (2, 7, "Beta"), (81, 8, "Foreign")):
            self.insert(Product, id=identifier, company_id=company, code=name, name=name, version=1)
        for identifier, company, product, status in ((42, 7, 1, "ACTIVE"), (43, 7, 2, "RETIRING"),
                                                     (81, 8, 81, "ACTIVE")):
            self.insert(ProductVariant, id=identifier, company_id=company, product_id=product,
                name=str(identifier), sku=str(identifier), base_uom_id=1, lifecycle_status=status,
                operational_hold="NONE", lot_control_mode="NONE", expiry_control_mode="NONE",
                quantity_scale=0, quantity_step=1, packs_per_carton=1, version=1, lifecycle_revision=1,
                package_uses_base_barcode=False)
        for identifier, company in ((21, 7), (22, 7), (81, 8)):
            self.insert(InventoryLocation, id=identifier, company_id=company, name=str(identifier),
                        location_type="WAREHOUSE", is_active=True)
        for identifier, company, location, variant in ((1, 7, 21, 42), (2, 7, 22, 42),
                                                       (3, 7, 21, 43), (4, 8, 81, 81)):
            self.insert(InventoryBalance, id=identifier, company_id=company, location_id=location,
                        product_variant_id=variant, on_hand_quantity=10)

    def insert(self, model, **values):
        self.connection.execute(self.tables[model.__table__.name].insert(), values)

    def grant(self, code, *, location=None, driver=303, company=7):
        self.role_id += 1
        model = UserRole if location is None else UserLocationAccess
        values = dict(company_id=company, driver_id=driver, role_id=self.role_id)
        if location is not None:
            values["location_id"] = location
        self.insert(model, **values)
        self.connection.execute(self.tables[role_permissions.name].insert(),
                                dict(company_id=company, role_id=self.role_id,
                                     permission_id=self.codes.index(code) + 1))

    def access(self, *, owner=False):
        return BackofficeCapabilityAccess(self.db,
            BackofficeAuthorizationSubject(101, 202, 7, owner, None if owner else 303))

    def readonly(self):
        self.db.commit.assert_not_awaited()
        self.db.rollback.assert_not_awaited()
        self.db.begin.assert_not_called()
        self.db.add.assert_not_called()

    async def http(self, path, *, method="GET", payload=None, current=None):
        current = current or DashboardRequestContext(101, 7, 202, 1, False)
        app = FastAPI()
        app.include_router(module.router)
        calls = []
        async def trusted_context():
            calls.append(current)
            return current
        app.dependency_overrides[canonical.get_current_principal_context] = trusted_context
        app.dependency_overrides[get_db] = lambda: self.db
        with patch.object(canonical, "_decode_access_token") as decode, \
                patch.object(module, "list_package_uoms", AsyncMock(return_value=[])), \
                patch.object(module, "load_company", AsyncMock(return_value=SimpleNamespace(currency_code="JOD"))), \
                patch.object(module, "assert_simple_pricing_mode", AsyncMock(return_value=None)), \
                patch.object(module, "current_default_book", AsyncMock(return_value=None)), \
                patch.object(module, "load_sale_shapes", AsyncMock(return_value={})), \
                patch.object(module, "current_prices", AsyncMock(return_value={})), \
                patch.object(module, "current_primary_barcodes", AsyncMock(return_value={})), \
                patch.object(module, "load_current_product_status_reasons", AsyncMock(return_value={})):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://simple.test") as client:
                response = await client.request(method, "/simple-products" + path, json=payload)
            decode.assert_not_called()  # The trusted context override is the only test auth seam.
        self.assertEqual(calls, [current])  # Cached across capability + operational dependencies.
        return response

    async def test_owner_uses_canonical_subject_and_all_four_reads_need_no_driver(self):
        self.connection.execute(self.tables[Driver.__table__.name].delete())
        self.connection.execute(self.tables[IdentityLegacyDriverMap.__table__.name].delete())
        owner = DashboardRequestContext(101, 7, 202, 1, True)
        for path in ("/package-uoms", "/families", "/summary", ""):
            with self.subTest(path=path):
                response = await self.http(path, current=owner)
                self.assertEqual(response.status_code, 200)
        self.assertFalse(any("FROM drivers" in sql(q) for q in self.db.statements))
        self.readonly()

    async def test_ordinary_scoped_catalog_read_uses_independent_mapped_grant_id(self):
        self.grant("catalog.read", driver=101)
        self.grant("catalog.read", driver=202)
        self.assertEqual((await self.http("/families")).status_code, 403)
        self.grant("catalog.read", location=21)
        self.connection.execute(self.tables[Driver.__table__.name].delete())
        response = await self.http("/families")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["id"] for r in response.json()["items"]], [1, 2])
        self.assertFalse(any("FROM drivers" in sql(q) for q in self.db.statements))
        self.readonly()

    async def test_driver_flags_never_supply_missing_capabilities(self):
        for flag in (False, True):
            self.db.legacy_flag = flag
            self.assertEqual((await self.http("/families")).status_code, 403)
        self.grant("catalog.read")
        self.assertEqual((await self.http("/families")).status_code, 200)
        self.readonly()

    async def test_every_create_capability_is_mandatory_and_company_scoped(self):
        required = ("catalog.manage", "catalog.publish", "pricing.manage")
        for code in required:
            self.grant(code, location=21)
        with self.assertRaises(HTTPException):
            await module._require_manage(self.access())
        assignments = self.tables[UserRole.__table__.name]
        permissions = self.tables[role_permissions.name]
        for missing in required:
            self.connection.execute(assignments.delete())
            self.connection.execute(permissions.delete())
            for code in required:
                if code != missing:
                    self.grant(code)
            with self.subTest(missing=missing), self.assertRaises(HTTPException) as failure:
                await module._require_manage(self.access())
            self.assertEqual(failure.exception.status_code, 403)
        for code in required:
            self.grant(code)
        await module._require_manage(self.access())
        self.readonly()

    async def test_canonical_warehouse_intersection_requires_every_exact_location(self):
        self.grant("inventory.read", location=21)
        with self.assertRaises(InventoryCatalogPresenceForbidden):
            await variant_ids_present_in_all_warehouses(self.db, access=self.access(), warehouse_ids=(21, 22))
        self.grant("inventory.read", location=22)
        statement = await variant_ids_present_in_all_warehouses(
            self.db, access=self.access(), warehouse_ids=(21, 22))
        self.assertEqual(list(self.connection.scalars(statement)), [42])
        for ids in ((81,), (999,)):
            with self.assertRaises(InventoryCatalogPresenceForbidden):
                await variant_ids_present_in_all_warehouses(self.db, access=self.access(owner=True), warehouse_ids=ids)
        self.connection.execute(self.tables[InventoryLocation.__table__.name].update().where(
            self.tables[InventoryLocation.__table__.name].c.id == 22).values(is_active=False))
        with self.assertRaises(InventoryCatalogPresenceForbidden):
            await variant_ids_present_in_all_warehouses(self.db, access=self.access(owner=True), warehouse_ids=(22,))
        self.readonly()

    async def test_company_wide_batch_evidence_rejects_location_only_inventory_grants(self):
        self.grant("inventory.read", location=21)
        self.assertEqual(await load_batch_restrictions(self.db, access=self.access(), variant_ids=[42]), {42: None})
        self.assertFalse(any("restricted_batches" in sql(q) for q in self.db.statements))
        self.grant("inventory.read")
        result = await load_batch_restrictions(self.db, access=self.access(), variant_ids=[42])
        self.assertEqual(result[42].affected_batch_count, 0)
        self.assertEqual(result[42].affected_on_hand_quantity, "0.000000")
        self.readonly()

    async def test_product_list_preserves_warehouse_filter_http_denial_and_optional_visibility(self):
        self.grant("catalog.read")
        self.grant("inventory.read", location=21)
        denied = await self.http("?warehouse_id=21&warehouse_id=22")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["detail"]["code"], "SIMPLE_PRODUCT_WAREHOUSE_FILTER_FORBIDDEN")
        self.grant("inventory.read", location=22)
        response = await self.http("?warehouse_id=21&warehouse_id=22")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["id"] for r in response.json()["items"]], [42])
        self.assertIsNone(response.json()["items"][0]["batch_restrictions"])
        self.assertFalse(response.json()["pricing_visible"])
        self.assertIsNone(response.json()["items"][0]["package_price"])
        self.assertIsNone(response.json()["items"][0]["unit_price"])
        denied_price = await self.http("?has_price=true")
        self.assertEqual(denied_price.status_code, 403)
        self.assertEqual(denied_price.json()["detail"]["code"], "SIMPLE_PRODUCT_PRICE_FILTER_FORBIDDEN")
        self.readonly()

    async def test_company_owner_product_list_and_family_cursor_do_not_cross_tenants(self):
        owner = DashboardRequestContext(101, 7, 202, 1, True)
        products = await self.http("?limit=1", current=owner)
        self.assertEqual([r["id"] for r in products.json()["items"]], [42])
        self.assertTrue(products.json()["has_more"])
        next_page = await self.http("?limit=1&cursor=" + products.json()["next_cursor"], current=owner)
        self.assertEqual([r["id"] for r in next_page.json()["items"]], [43])
        first = await self.http("/families?limit=1", current=owner)
        self.assertEqual([r["id"] for r in first.json()["items"]], [1])
        cursor = first.json()["next_cursor"]
        last = await self.http("/families?limit=1&cursor=" + cursor, current=owner)
        self.assertEqual([r["id"] for r in last.json()["items"]], [2])
        self.assertFalse(last.json()["has_more"])
        foreign = await self.http("/families?limit=1&cursor=" + cursor,
                                  current=DashboardRequestContext(101, 8, 202, 1, True))
        self.assertEqual(foreign.status_code, 400)
        self.readonly()

    async def test_foreign_grants_missing_bridge_and_wrong_channel_are_opaque_denials(self):
        self.grant("catalog.read", company=8)
        self.assertEqual((await self.http("/families")).status_code, 403)
        for current in (DashboardRequestContext(999, 7, 202, 1, False),
                        DashboardRequestContext(101, 8, 202, 1, False)):
            response = await self.http("/families", current=current)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json(), {"detail": "Authorization denied."})
        response = await self.http("/families", current=FieldRequestContext(101, 7, 202, 1))
        self.assertEqual(response.status_code, 401)
        self.readonly()

    async def test_create_replay_keeps_mapped_operational_id_without_service_or_audit(self):
        for code in ("catalog.manage", "catalog.publish", "pricing.manage"):
            self.grant(code)
        payload = dict(request_id="4e447464-7d22-4880-a0f0-e4549bf90e30", name="Juice",
                       family_mode="none", package_uom_code=None, units_per_package=1, unit_price="1.5")
        for flag in (False, True):
            self.db.legacy_flag = flag
            with patch.object(module, "begin_idempotent_operation",
                              AsyncMock(return_value=(object(), {"replayed": True}))) as begin, \
                    patch.object(module, "create_products_and_prices", AsyncMock()) as create:
                response = await self.http("", method="POST", payload=payload)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json(), {"replayed": True})
            self.assertEqual((begin.call_args.kwargs["company_id"], begin.call_args.kwargs["actor_id"]), (7, 303))
            create.assert_not_awaited()
        self.assertEqual(self.db.rollback.await_count, 2)
        self.db.commit.assert_not_awaited()
        self.db.add.assert_not_called()

    async def test_family_not_empty_and_cross_company_price_lock_keep_fail_closed_contracts(self):
        for code in ("catalog.manage", "pricing.manage"):
            self.grant(code)
        request_id = UUID("4e447464-7d22-4880-a0f0-e4549bf90e30")
        actor = SimpleNamespace(id=303)  # No tenant or flags on the operational object.
        with patch.object(module, "begin_idempotent_operation", AsyncMock(return_value=(object(), None))):
            with self.assertRaises(HTTPException) as blocked:
                await module.delete_product_family(1, module.FamilyDelete(
                    request_id=request_id, expected_version=1), self.db, self.access(), actor)
            self.assertEqual(blocked.exception.detail["code"], "SIMPLE_PRODUCT_FAMILY_NOT_EMPTY")
            with patch.object(module, "update_prices", AsyncMock()) as prices:
                with self.assertRaises(HTTPException) as foreign:
                    await module.update_simple_product_price(81, module.SimplePriceUpdate(
                        request_id=request_id, unit_price="1.5"), self.db, self.access(), actor)
                prices.assert_not_awaited()
            self.assertEqual(foreign.exception.status_code, 404)
        locked = sql(self.db.statements[-1])
        self.assertIn("product_variants.company_id = 7", locked)
        self.assertIn("product_variants.id = 81", locked)
        self.assertIn("FOR UPDATE", locked)
        self.assertEqual(self.db.rollback.await_count, 2)
        self.db.commit.assert_not_awaited()
        self.db.add.assert_not_called()

    async def test_existing_v3_idempotency_hash_and_price_provenance_use_canonical_tenant(self):
        request_id = UUID("4e447464-7d22-4880-a0f0-e4549bf90e30")
        original = module.SimpleProductCreate(request_id=request_id, name="Juice", unit_price="1.5")
        explicit_legacy = module.SimpleProductCreate(request_id=request_id, name="Juice",
                                                     unit_price="1.5", family_mode=None)
        self.assertEqual(module._request_hash(original), module._request_hash(explicit_legacy))
        self.grant("pricing.manage")
        actor = SimpleNamespace(id=303)
        prices = SimpleNamespace(package_price=None, unit_price=__import__("decimal").Decimal("1.5"))
        with patch.object(module, "begin_idempotent_operation",
                          AsyncMock(return_value=(object(), None))), \
                patch.object(module, "update_prices", AsyncMock(return_value=prices)) as update, \
                patch.object(module, "complete_idempotent_operation") as complete:
            result = await module.update_simple_product_price(42, module.SimplePriceUpdate(
                request_id=request_id, unit_price="1.5"), self.db, self.access(), actor)
        self.assertIs(update.call_args.kwargs["actor"], actor)
        self.assertEqual(update.call_args.kwargs["company_id"], 7)
        audit = self.db.add.call_args.args[0]
        self.assertEqual((audit.company_id, audit.admin_id), (7, 303))
        complete.assert_called_once()
        self.db.commit.assert_awaited_once()
        self.db.rollback.assert_not_awaited()
        self.assertEqual(result["unit_price"], "1.500000")


if __name__ == "__main__":
    unittest.main()
