"""Focused Live Stock canonical HTTP, SQL scope, and query contract acceptance.

Uses synthetic SQLite grant/location data and mocked readiness only. PostgreSQL
business queries are compiled with canonical grant predicates; RLS/deployment evidence
is separate. HTTP tests override only the already-trusted principal context.
"""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Column, MetaData, Table, create_engine, select
from sqlalchemy.dialects import postgresql

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
with patch.dict(os.environ, {
    "ENVIRONMENT": "test",
    "SECRET_KEY": "LiveStockCanonicalSyntheticSecret123456789012345678901234567890",
    "DATABASE_URL": "postgresql+asyncpg://live_unit@127.0.0.1:1/live_unit",
    "DATABASE_URL_MIGRATION": "postgresql+asyncpg://live_admin@127.0.0.1:1/live_unit",
}):
    from api.warehouse import live_stock as module
    from api.authentication import dependencies as canonical

from database import get_db
from domains.auth_sessions.context import DashboardRequestContext, FieldRequestContext
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.identity.migration.models import IdentityLegacyDriverMap
from models import Driver, InventoryLocation, Permission, Product, ProductVariant, UserLocationAccess, UserRole, role_permissions


class ReadSession:
    def __init__(self, connection):
        self.connection = connection
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.connection.execute(statement)

    async def scalar(self, statement):
        self.statements.append(statement)
        descriptions = getattr(statement, "column_descriptions", ())
        if descriptions and descriptions[0].get("entity") is IdentityLegacyDriverMap:
            row = self.connection.execute(statement).mappings().one_or_none()
            return None if row is None else SimpleNamespace(**dict(row))
        return self.connection.scalar(statement)

    async def scalars(self, statement):
        self.statements.append(statement)
        return self.connection.scalars(statement)


def subject(*, owner=False, company_id=7):
    return BackofficeAuthorizationSubject(
        principal_id=101, backoffice_user_id=202, company_id=company_id,
        is_company_owner=owner, legacy_grant_driver_id=None if owner else 303,
    )


def sql(statement):
    return str(statement.compile(dialect=postgresql.dialect(),
                                 compile_kwargs={"literal_binds": True}))


class LiveStockCanonicalCutoverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        metadata = MetaData()
        definitions = (
            (InventoryLocation, "id company_id name location_type is_active vehicle_id"),
            (Permission, "id code"),
            (UserRole, "company_id driver_id role_id"),
            (UserLocationAccess, "company_id driver_id role_id location_id"),
            (Driver, "id company_id"),
            (Product, "id company_id name code"),
            (IdentityLegacyDriverMap, " ".join(IdentityLegacyDriverMap.__table__.columns.keys())),
        )
        self.tables = {}
        for model, names in definitions:
            original = model.__table__
            self.tables[original.name] = Table(
                original.name, metadata, *(Column(name, original.c[name].type) for name in names.split())
            )
        self.tables[role_permissions.name] = Table(
            role_permissions.name, metadata,
            *(Column(name, role_permissions.c[name].type)
              for name in ("company_id", "role_id", "permission_id")),
        )
        self.engine = create_engine("sqlite://")
        metadata.create_all(self.engine)
        self.connection = self.engine.connect()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.connection.close)
        self.db = ReadSession(self.connection)
        self.insert(Permission, id=1, code="inventory.read")
        self.insert(Driver, id=303, company_id=7)
        self.insert(IdentityLegacyDriverMap, company_id=7, legacy_driver_id=303,
                    classification="BACKOFFICE_ONLY", backoffice_principal_id=101,
                    backoffice_user_id=202)
        for location_id, company, kind, active, vehicle in (
            (21, 7, "WAREHOUSE", True, None), (22, 7, "WAREHOUSE", True, None),
            (23, 7, "VEHICLE", True, 501), (24, 7, "VEHICLE", False, 502),
            (25, 7, "VEHICLE", True, None), (26, 7, "VEHICLE", True, 503),
            (27, 7, "WAREHOUSE", False, None), (81, 8, "WAREHOUSE", True, None),
            (82, 8, "VEHICLE", True, 801),
        ):
            self.insert(InventoryLocation, id=location_id, company_id=company,
                        name=str(location_id), location_type=kind, is_active=active, vehicle_id=vehicle)
        for product_id, company, name in ((1, 7, "Alpha"), (2, 7, "Beta"),
                                          (3, 7, "Gamma"), (81, 8, "Foreign")):
            self.insert(Product, id=product_id, company_id=company, name=name, code=name)

    def insert(self, model, **values):
        self.connection.execute(self.tables[model.__table__.name].insert(), values)

    def grant(self, *, location_id=None, driver_id=303, company_id=7):
        role_id = 1000 + len(self.db.statements) + (location_id or 0) + driver_id
        assignment = UserRole if location_id is None else UserLocationAccess
        values = dict(company_id=company_id, driver_id=driver_id, role_id=role_id)
        if location_id is not None:
            values["location_id"] = location_id
        self.insert(assignment, **values)
        self.connection.execute(self.tables[role_permissions.name].insert(),
                                dict(company_id=company_id, role_id=role_id, permission_id=1))

    def access(self, *, owner=False, company_id=7):
        return BackofficeCapabilityAccess(self.db, subject(owner=owner, company_id=company_id))

    async def warehouse_read(self, access, location_id=21, **kwargs):
        return await module._require_live_stock_warehouse_read(
            self.db, company_id=access.company_id, location_id=location_id, access=access, **kwargs
        )

    async def test_owner_uses_canonical_subject_and_still_checks_active_tenant_warehouse(self):
        self.assertTrue(await self.warehouse_read(self.access(owner=True)))
        self.assertEqual(len(self.db.statements), 2)
        self.assertIn("inventory_locations.company_id = 7", sql(self.db.statements[0]))
        self.assertIn("inventory_locations.is_active IS true", sql(self.db.statements[0]))
        self.assertNotIn("drivers", sql(self.db.statements[1]))
        self.assertNotIn("user_roles", sql(self.db.statements[1]))

    async def test_company_grant_and_exact_location_grant_keep_distinct_visibility_modes(self):
        self.grant(location_id=21)
        self.assertFalse(await self.warehouse_read(self.access()))
        with self.assertRaises(HTTPException) as denied:
            await self.warehouse_read(self.access(), 22)
        self.assertEqual(denied.exception.status_code, 403)
        self.grant()
        self.assertTrue(await self.warehouse_read(self.access(), 22))

    async def test_absent_grant_and_wrong_principal_or_profile_id_do_not_grant_access(self):
        for wrong_id in (101, 202):
            self.grant(location_id=21, driver_id=wrong_id)
        with self.assertRaises(HTTPException) as denied:
            await self.warehouse_read(self.access())
        self.assertEqual(denied.exception.status_code, 403)
        self.grant(location_id=21, driver_id=303)
        self.assertFalse(await self.warehouse_read(self.access()))
        query = sql(self.db.statements[-1])
        self.assertIn("user_location_access.driver_id = 303", query)
        self.assertNotIn("user_location_access.driver_id = 101", query)
        self.assertNotIn("user_location_access.driver_id = 202", query)

    async def test_missing_foreign_inactive_and_vehicle_locations_fail_for_owner_and_ordinary(self):
        self.grant()
        for owner in (False, True):
            for location in (999, 81, 27, 23):
                with self.subTest(owner=owner, location=location):
                    self.db.statements.clear()
                    with self.assertRaises(HTTPException) as denied:
                        await self.warehouse_read(self.access(owner=owner), location)
                    self.assertEqual(denied.exception.status_code, 404)
                    self.assertEqual(len(self.db.statements), 1)

    async def test_owner_batch_product_missing_warehouse_error_contract_is_preserved(self):
        detail = module.inventory_business_error("LIVE_STOCK_LOCATION_NOT_FOUND",
                                                  "The selected warehouse is unavailable.")
        for owner in (False, True):
            with self.assertRaises(HTTPException) as denied:
                await self.warehouse_read(self.access(owner=owner), 999, owner_not_found_detail=detail)
            self.assertEqual(denied.exception.status_code, 404)
            if owner:
                self.assertEqual(denied.exception.detail, detail)
            else:
                self.assertIsInstance(denied.exception.detail, str)

    async def test_any_location_accepts_location_only_grant_and_preserves_403_denial(self):
        with self.assertRaises(HTTPException) as denied:
            await module._require_live_stock_any_location_read(self.access())
        self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual(denied.exception.detail, "لا تملك صلاحية تنفيذ هذه العملية ضمن الموقع المحدد.")
        self.grant(location_id=23)
        await module._require_live_stock_any_location_read(self.access())
        await module._require_live_stock_any_location_read(self.access(owner=True))

    async def test_driver_flag_neither_promotes_ordinary_user_nor_demotes_company_owner(self):
        for flag in (True, False):
            # Legacy operational data are sentinel-only; Live Stock never loads them.
            self.db.operational_driver = SimpleNamespace(id=303, company_id=7, is_admin=flag)
            with self.assertRaises(HTTPException) as denied:
                await self.warehouse_read(self.access())
            self.assertEqual(denied.exception.status_code, 403)
            self.assertTrue(await self.warehouse_read(self.access(owner=True)))
        self.grant(location_id=21)
        for flag in (True, False):
            # Legacy operational data are sentinel-only; Live Stock never loads them.
            self.db.operational_driver = SimpleNamespace(id=303, company_id=7, is_admin=flag)
            self.assertFalse(await self.warehouse_read(self.access()))
        self.assertTrue(all("FROM drivers" not in sql(statement) for statement in self.db.statements))

    async def test_vehicle_visibility_filters_exact_grants_active_state_and_tenant_in_sql(self):
        self.grant(location_id=21)
        self.grant(location_id=23)
        self.grant(location_id=82, company_id=8)
        for owner, expected in ((False, [23]), (True, [23, 26])):
            query = module._readable_vehicle_locations_subquery(company_id=7, access=self.access(owner=owner))
            rows = self.connection.execute(select(query.c.id).order_by(query.c.id)).scalars().all()
            self.assertEqual(rows, expected)

    async def test_family_read_preserves_company_filter_ordering_and_limit_plus_one(self):
        self.grant(location_id=21)
        for owner in (False, True):
            response = await module.get_warehouse_inventory_families(
                location_id=21, search=None, limit=2, db=self.db, access=self.access(owner=owner)
            )
            self.assertEqual([item["name"] for item in response["items"]], ["Alpha", "Beta"])
            self.assertTrue(response["has_more"])
            query = sql(self.db.statements[-1])
            self.assertIn("products.company_id = 7", query)
            self.assertIn("ORDER BY products.name ASC, products.id ASC", query)
            self.assertIn("LIMIT 3", query)

    def test_postgresql_business_queries_keep_canonical_tenant_and_scope_predicates(self):
        for owner in (False, True):
            access = self.access(owner=owner)
            self.assertIsInstance(access, BackofficeCapabilityAccess)
            self.assertIs(access.subject.is_company_owner, owner)
            vehicle = sql(module._readable_vehicle_locations_subquery(
                company_id=access.company_id, access=access,
            ).select())
            visible = sql(module._build_visible_inventory_stmt(
                company_id=access.company_id, location_id=21, access=access,
                company_wide_inventory_read=owner, limit=2, sort="name_desc",
                candidate_filters=(ProductVariant.id > 10,),
            ))
            filtered = sql(module._live_stock_filtered_variant_ids_stmt(
                company_id=access.company_id, location_id=21, access=access,
                company_wide_inventory_read=owner, stock_state="sellable",
                has_reserved=True, has_unavailable=True, has_damaged=False,
                has_recalled=True, has_vehicle=True, minimum_unset=False,
            ))

            for rendered in (vehicle, visible, filtered):
                with self.subTest(owner=owner, query=rendered[:80]):
                    self.assertNotIn("drivers", rendered)
                    self.assertNotIn("is_admin", rendered)
                    self.assertNotIn("company_id = 8", rendered)
                    if owner:
                        self.assertNotIn("user_roles", rendered)
                        self.assertNotIn("user_location_access", rendered)
                    else:
                        for predicate in (
                            "user_roles.company_id = 7",
                            "user_location_access.company_id = 7",
                            "role_permissions.company_id = 7",
                            "user_roles.driver_id = 303",
                            "user_location_access.driver_id = 303",
                            "permissions.code IN ('inventory.read')",
                            "user_location_access.location_id = inventory_locations.id",
                        ):
                            self.assertIn(predicate, rendered)

            for predicate in ("inventory_locations.company_id = 7",
                              "inventory_locations.location_type = 'VEHICLE'",
                              "inventory_locations.is_active IS true",
                              "inventory_locations.vehicle_id IS NOT NULL"):
                self.assertIn(predicate, vehicle)
            self.assertIn("product_variants.company_id = 7", visible)
            self.assertIn("product_variants.id > 10", visible)
            self.assertIn("warehouse_location_id = 21", visible)
            self.assertIn("LIMIT 3", visible)
            ordering = (
                "visible_inventory_candidates.variant_name DESC, "
                "visible_inventory_candidates.id DESC"
            )
            self.assertIn("ORDER BY " + ordering, visible)
            self.assertIn("live_stock_filter_variant.company_id = 7", filtered)
            self.assertIn("warehouse_location_id = 21", filtered)
            self.assertIn("warehouse_sellable_on_hand", filtered)
            self.assertIn("warehouse_reserved", filtered)
            self.assertIn("recalled_packs", filtered)
            for rendered in (visible, filtered):
                self.assertIn("inventory_balances.company_id = 7", rendered)
                self.assertNotIn("dispatch_routes", rendered)
                self.assertNotIn("latest_readable_vehicle_sources", rendered)
                self.assertNotIn("vehicle_packs", rendered)

    async def http_request(self, context, path, readiness):
        app = FastAPI()
        app.include_router(module.router)
        async def trusted_context():
            return context
        async def request_db():
            return self.db
        app.dependency_overrides[canonical.get_current_principal_context] = trusted_context
        app.dependency_overrides[get_db] = request_db
        with patch.object(module, "_require_live_stock_read_model_ready", readiness):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://live-stock.test") as client:
                return await client.get(path, params={"location_id": 21})

    async def test_real_canonical_http_dependency_uses_owner_or_exact_bridge_without_driver_load(self):
        self.grant(location_id=21)
        for owner in (False, True):
            self.db.statements.clear()
            context = DashboardRequestContext(principal_id=101, company_id=7, backoffice_user_id=202,
                                               auth_revision=13, is_company_owner=owner)
            readiness = AsyncMock(return_value=SimpleNamespace(alert_count=5))
            response = await self.http_request(context, "/warehouse/inventory/alerts/summary", readiness)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {"alert_count": 5})
            readiness.assert_awaited_once_with(self.db, company_id=7, location_id=21)
            queries = [sql(statement) for statement in self.db.statements]
            mapping = [query for query in queries if "FROM identity_legacy_driver_map" in query]
            self.assertEqual(len(mapping), 0 if owner else 1)
            if mapping:
                self.assertIn("backoffice_principal_id = 101", mapping[0])
                self.assertIn("backoffice_user_id = 202", mapping[0])
                self.assertIn("company_id = 7", mapping[0])
            self.assertTrue(all("FROM drivers" not in query for query in queries))

    async def test_http_denial_stops_before_readiness_and_missing_bridge_fails_closed(self):
        context = DashboardRequestContext(101, 7, 202, 13, False)
        readiness = AsyncMock()
        response = await self.http_request(context, "/warehouse/inventory/alerts/summary", readiness)
        self.assertEqual(response.status_code, 403)
        readiness.assert_not_awaited()
        self.connection.execute(self.tables["identity_legacy_driver_map"].delete())
        response = await self.http_request(context, "/warehouse/inventory/alerts/summary", readiness)
        self.assertEqual(response.status_code, 403)
        readiness.assert_not_awaited()

    async def test_field_context_is_rejected_by_all_nine_backoffice_routes_before_business_queries(self):
        paths = (
            "/warehouse/inventory/alerts/summary", "/warehouse/inventory/summary",
            "/warehouse/inventory/families", "/warehouse/inventory/batch-products",
            "/warehouse/inventory/cursor", "/warehouse/inventory/101/batches",
            "/warehouse/variants/101/quality-batch-candidates",
            "/warehouse/variants/101/quality-issue-sources", "/warehouse/batches/31/stock-sources",
        )
        context = FieldRequestContext(101, 7, 404, 13)
        for path in paths:
            with self.subTest(path=path):
                self.db.statements.clear()
                readiness = AsyncMock()
                response = await self.http_request(context, path, readiness)
                self.assertEqual(response.status_code, 401, response.text)
                self.assertEqual(response.json(), {"detail": canonical._AUTH_REJECTION_DETAIL})
                self.assertEqual(self.db.statements, [])
                readiness.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
