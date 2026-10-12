"""Focused Catalog canonical HTTP/grant SQL and operational attribution checks.

Synthetic SQLite data execute the canonical grant predicates and Catalog reads.
Mutating business commands use explicit mocks for idempotency/locks; PostgreSQL
row-lock ordering is inspected, not claimed as a concurrent/RLS deployment test.
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
from sqlalchemy import Column, MetaData, Table, create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
with patch.dict(os.environ, {
    "ENVIRONMENT": "test",
    "SECRET_KEY": "CatalogCanonicalSyntheticSecret123456789012345678901234567890",
    "DATABASE_URL": "postgresql+asyncpg://catalog_unit@127.0.0.1:1/catalog_unit",
    "DATABASE_URL_MIGRATION": "postgresql+asyncpg://catalog_admin@127.0.0.1:1/catalog_unit",
}):
    from api import catalog as module
    from api.authentication import dependencies as canonical
from database import get_db
from domains.auth_sessions.context import DashboardRequestContext, FieldRequestContext
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.authorization.capabilities import COMPANY_ONLY
from domains.authorization.inventory_access import InventoryAccess as BaselineAccess
from domains.identity.migration.models import IdentityLegacyDriverMap
from models import Driver, InventoryLocation, Permission, Product, ProductVariant, UserLocationAccess, UserRole, role_permissions


def subject(*, owner=False, company=7):
    return BackofficeAuthorizationSubject(101, 202, company, owner, None if owner else 303)


def sql(statement):
    return str(statement.compile(dialect=postgresql.dialect(),
                                 compile_kwargs={"literal_binds": True}))


_UNSET = object()


class ReadSession:
    def __init__(self, session):
        self.session = session
        self.statements = []
        self.legacy_flag = None
        self.variant_override = _UNSET
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.begin = Mock()

    async def execute(self, statement):
        self.statements.append(statement)
        result = self.session.execute(statement)
        columns = getattr(statement, "column_descriptions", ())
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

    async def scalar(self, statement):
        self.statements.append(statement)
        columns = getattr(statement, "column_descriptions", ())
        if (self.variant_override is not _UNSET and columns
                and columns[0].get("entity") is ProductVariant):
            return self.variant_override
        return self.session.scalar(statement)

    async def scalars(self, statement):
        self.statements.append(statement)
        return self.session.scalars(statement)


class CatalogCanonicalCutoverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        metadata = MetaData()
        self.tables = {}
        for model in (Driver, IdentityLegacyDriverMap, Product, ProductVariant,
                      InventoryLocation, Permission, UserRole, UserLocationAccess):
            original = model.__table__
            self.tables[original.name] = Table(
                original.name, metadata,
                *(Column(c.name, c.type, primary_key=c.primary_key) for c in original.columns),
            )
        self.tables[role_permissions.name] = Table(
            role_permissions.name, metadata,
            *(Column(c.name, c.type) for c in role_permissions.columns),
        )
        self.engine = create_engine("sqlite://")
        metadata.create_all(self.engine)
        self.connection = self.engine.connect()
        self.session = Session(bind=self.connection, autoflush=False)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.connection.close)
        self.addCleanup(self.session.close)
        self.db = ReadSession(self.session)
        self.role_id = 0
        self.codes = ("catalog.read", "catalog.manage", "catalog.publish", "catalog.retire",
                      "catalog.restore", "catalog.archive", "catalog.hold", "inventory.read")
        for identifier, code in enumerate(self.codes, 1):
            self.insert(Permission, id=identifier, code=code)
        self.insert(Driver, id=303, company_id=7, is_active=True)
        self.insert(IdentityLegacyDriverMap, company_id=7, legacy_driver_id=303,
                    classification="BACKOFFICE_ONLY", backoffice_principal_id=101,
                    backoffice_user_id=202)
        for identifier, company in ((21, 7), (22, 7), (81, 8)):
            self.insert(InventoryLocation, id=identifier, company_id=company,
                        name=str(identifier), location_type="WAREHOUSE", is_active=True)
        for identifier, company, name in ((1, 7, "Alpha"), (2, 7, "Beta"), (81, 8, "Foreign")):
            self.insert(Product, id=identifier, company_id=company, code=name, name=name, version=1)

    def insert(self, model, **values):
        self.connection.execute(self.tables[model.__table__.name].insert(), values)

    def change_driver(self, **values):
        self.connection.execute(self.tables[Driver.__table__.name].update().values(**values))
        self.session.expire_all()

    def grant(self, code, *, location=None, driver=303, company=7):
        self.role_id += 1
        assignment = UserRole if location is None else UserLocationAccess
        values = dict(company_id=company, driver_id=driver, role_id=self.role_id)
        if location is not None:
            values["location_id"] = location
        self.insert(assignment, **values)
        self.connection.execute(self.tables[role_permissions.name].insert(),
                                dict(company_id=company, role_id=self.role_id,
                                     permission_id=self.codes.index(code) + 1))

    def access(self, *, owner=False, company=7):
        return BackofficeCapabilityAccess(self.db, subject(owner=owner, company=company))

    def assert_read_only(self):
        self.db.commit.assert_not_awaited()
        self.db.rollback.assert_not_awaited()
        self.db.begin.assert_not_called()

    async def http(self, path, *, current=None, method="GET", payload=None):
        app = FastAPI()
        app.include_router(module.router)
        if current is None:
            current = DashboardRequestContext(101, 7, 202, 1, False)
        context_calls = []
        async def trusted_context():
            context_calls.append(current)
            return current
        app.dependency_overrides[canonical.get_current_principal_context] = trusted_context
        app.dependency_overrides[get_db] = lambda: self.db
        with patch.object(canonical, "_decode_access_token") as decode:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://catalog.test") as client:
                response = await client.request(method, "/catalog" + path, json=payload)
            decode.assert_not_called()  # Trusted context is injected; Catalog never re-decodes.
        self.assertEqual(context_calls, [current])  # Shared across access + compatibility seams.
        return response

    async def test_canonical_owner_needs_no_bridge_or_driver_for_reads(self):
        self.connection.execute(self.tables[IdentityLegacyDriverMap.__table__.name].delete())
        self.connection.execute(self.tables[Driver.__table__.name].delete())
        response = await self.http("/products?limit=1",
                                   current=DashboardRequestContext(101, 7, 202, 1, True))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()["items"]], [1])
        self.assertTrue(response.json()["has_more"])
        self.assertIsNotNone(response.json()["next_cursor"])
        self.assert_read_only()

    async def test_scoped_read_grant_preserves_any_location_without_driver_lookup(self):
        self.grant("catalog.read", location=21)
        self.connection.execute(self.tables[Driver.__table__.name].delete())
        response = await self.http("/products")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()["items"]], [1, 2])
        self.assertFalse(any("FROM drivers" in sql(q) for q in self.db.statements))
        self.assert_read_only()

    async def test_principal_profile_and_driver_ids_are_independent_grant_locators(self):
        self.grant("catalog.read", driver=101)
        self.grant("catalog.read", driver=202)
        response = await self.http("/products")
        self.assertEqual(response.status_code, 403)
        self.grant("catalog.read", driver=303)
        response = await self.http("/products")
        self.assertEqual(response.status_code, 200)
        self.assert_read_only()

    async def test_missing_capability_ignores_both_driver_flag_values(self):
        for flag in (False, True):
            self.db.legacy_flag = flag
            response = await self.http("/products")
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["detail"],
                             "لا تملك صلاحية تنفيذ هذه العملية ضمن الموقع المحدد.")
        self.assert_read_only()

    async def test_company_only_catalog_commands_reject_location_only_grants(self):
        for code in self.codes[:-1]:
            self.grant(code, location=21)
            if code in COMPANY_ONLY:
                with self.subTest(code=code), self.assertRaises(HTTPException) as failure:
                    await module._require(self.access(), code)
                self.assertEqual(failure.exception.status_code, 403)
            else:
                await module._require(self.access(), code)
        self.assert_read_only()

    async def test_company_granted_backoffice_retains_every_catalog_command(self):
        for code in self.codes[:-1]:
            self.grant(code)
            await module._require(self.access(), code)
        self.assert_read_only()

    async def test_exact_location_filter_denies_ungranted_and_foreign_locations(self):
        self.grant("inventory.read", location=21)
        access = self.access()
        statement = select(InventoryLocation.id).where(
            InventoryLocation.company_id == access.company_id,
            access.location_filter("inventory.read"),
        )
        self.assertEqual(list(self.connection.scalars(statement)), [21])
        self.grant("inventory.read", location=81, company=8)
        self.assertEqual(list(self.connection.scalars(statement)), [21])
        self.assert_read_only()

    async def test_grant_sql_parity_for_every_catalog_scope_and_recall_scope(self):
        ordinary = self.access()
        baseline = BaselineAccess(self.db, SimpleNamespace(company_id=7, id=303, is_admin=False))
        owner = self.access(owner=True)
        baseline_owner = BaselineAccess(self.db, SimpleNamespace(company_id=7, id=303, is_admin=True))
        for code in self.codes:
            for scope in ({}, {"any_location": True}, {"location_id": 21}):
                with self.subTest(code=code, scope=scope):
                    old_scope = {"location": scope["location_id"]} if "location_id" in scope else scope
                    self.assertEqual(sql(select(ordinary.allows(code, **scope))),
                                     sql(select(baseline.allows(code, **old_scope))))
                    self.assertEqual(sql(select(owner.allows(code, **scope))),
                                     sql(select(baseline_owner.allows(code, **old_scope))))

    async def test_foreign_grants_and_missing_or_wrong_context_fail_closed(self):
        self.grant("catalog.read", company=8)
        self.assertEqual((await self.http("/products")).status_code, 403)
        for current in (DashboardRequestContext(999, 7, 202, 1, False),
                        DashboardRequestContext(101, 7, 999, 1, False),
                        DashboardRequestContext(101, 8, 202, 1, False)):
            response = await self.http("/products", current=current)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json(), {"detail": "Authorization denied."})
        response = await self.http("/products", current=FieldRequestContext(101, 7, 202, 1))
        self.assertEqual(response.status_code, 401)
        self.assert_read_only()

    async def test_cross_company_product_and_variant_queries_remain_tenant_filtered(self):
        for owner in (False, True):
            self.grant("catalog.manage")
            self.db.variant_override = None
            with self.assertRaises(HTTPException) as failure:
                await module.variant_delete_draft_preflight(81, self.db, self.access(owner=owner))
            self.assertEqual(failure.exception.status_code, 404)
            self.assertIn("product_variants.company_id = 7", sql(self.db.statements[-1]))
            self.assertIn("product_variants.id = 81", sql(self.db.statements[-1]))
        self.assert_read_only()

    async def test_mutation_replay_uses_mapped_driver_id_and_one_trusted_context(self):
        self.grant("catalog.manage")
        payload = {"request_id": "4e447464-7d22-4880-a0f0-e4549bf90e30",
                   "code": "NEW", "name": "New product"}
        for flag in (False, True):
            self.db.legacy_flag = flag
            replay = {"message": "replayed"}
            with patch.object(module, "begin_idempotent_operation",
                              AsyncMock(return_value=(None, replay))) as begin:
                response = await self.http("/products", method="POST", payload=payload)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json(), replay)
            begin.assert_awaited_once()
            self.assertEqual(begin.call_args.kwargs["company_id"], 7)
            self.assertEqual(begin.call_args.kwargs["actor_id"], 303)
        self.assertEqual(self.db.rollback.await_count, 2)
        self.db.commit.assert_not_awaited()
        self.db.begin.assert_not_called()

    async def test_mutation_requires_active_exact_mapped_driver_operational_row(self):
        self.grant("catalog.manage")
        payload = {"request_id": "4e447464-7d22-4880-a0f0-e4549bf90e30",
                   "code": "NEW", "name": "New product"}
        with patch.object(module, "begin_idempotent_operation", AsyncMock()) as begin:
            for values in ({"is_active": False}, {"is_active": True, "company_id": 8}):
                self.change_driver(**values)
                response = await self.http("/products", method="POST", payload=payload)
                self.assertEqual(response.status_code, 401)
            self.connection.execute(self.tables[Driver.__table__.name].delete())
            self.session.expire_all()
            self.assertEqual((await self.http("/products", method="POST", payload=payload)).status_code, 401)
            begin.assert_not_awaited()
        self.assert_read_only()

    async def test_archive_preflight_forwards_same_access_and_preserves_blockers(self):
        self.grant("catalog.archive")
        access = self.access()
        self.db.variant_override = SimpleNamespace(lifecycle_status="RETIRING",
                                                   operational_hold="NONE", version=4)
        blockers = [{"code": "OPEN_SHORTAGE", "count": 1, "sample_id": 90}]
        target = {"kind": "shortage", "operation_id": 90}
        with patch.object(module, "archive_blockers", AsyncMock(return_value=blockers)) as guard, \
                patch.object(module, "inventory_archive_targets", AsyncMock(return_value={})) as inventory, \
                patch.object(module, "dispatch_archive_targets",
                             AsyncMock(return_value={"OPEN_SHORTAGE": target})) as dispatch, \
                patch.object(module, "operations_archive_targets", AsyncMock(return_value={})) as operations:
            result = await module.variant_archive_preflight(501, self.db, access)
        guard.assert_awaited_once_with(self.db, 7, 501)
        for adapter in (inventory, dispatch, operations):
            adapter.assert_awaited_once_with(self.db, access, 501, blockers)
        self.assertFalse(result["can_archive"])
        self.assertEqual(result["blockers"], [{**blockers[0], "owner_target": target}])
        self.assert_read_only()

    async def test_recall_summary_is_optional_and_scoped_by_inventory_read(self):
        self.grant("catalog.hold")
        self.db.variant_override = SimpleNamespace(version=4, operational_hold="RECALL")
        access = self.access()
        with patch.object(module, "recall_completion_blockers", AsyncMock(return_value=[])), \
                patch.object(module, "read_variant_inventory_issue_summary",
                             AsyncMock(return_value={"visible": True})) as summary:
            result = await module.variant_recall_readiness(501, self.db, access)
            self.assertIsNone(result["inventory_summary"])
            summary.assert_not_awaited()
            self.grant("inventory.read", location=21)
            result = await module.variant_recall_readiness(501, self.db, access)
            self.assertEqual(result["inventory_summary"], {"visible": True})
        self.assertEqual(summary.call_args.kwargs["company_id"], 7)
        predicate = summary.call_args.kwargs["readable_location_filter"]
        readable = select(InventoryLocation.id).where(InventoryLocation.company_id == 7, predicate)
        self.assertEqual(list(self.connection.scalars(readable)), [21])
        self.assert_read_only()

    async def test_lifecycle_replay_and_missing_row_keep_attribution_and_lock_order(self):
        payload = module.LifecycleCommand(request_id=UUID("4e447464-7d22-4880-a0f0-e4549bf90e30"),
                                          expected_version=4, reason="Focused test")
        actor = SimpleNamespace(id=303)  # No tenant/flag fields available.
        access = self.access(owner=True)
        self.db.variant_override = None
        order = []
        async def begin(*args, **kwargs):
            order.append("idempotency")
            self.assertEqual((kwargs["company_id"], kwargs["actor_id"]), (7, 303))
            return object(), None
        async def guards(db, company, ids, *, exclusive):
            order.append("lifecycle_guard")
            self.assertEqual((company, ids, exclusive), (7, [81], True))
        with patch.object(module, "begin_idempotent_operation", begin), \
                patch.object(module, "acquire_product_lifecycle_guards", guards):
            with self.assertRaises(HTTPException) as failure:
                await module._run_variant_state_command(variant_id=81, payload=payload,
                    command="archive", permission="catalog.archive", db=self.db,
                    access=access, legacy_actor=actor)
        self.assertEqual(failure.exception.status_code, 404)
        self.assertEqual(order, ["idempotency", "lifecycle_guard"])
        locked_sql = sql(self.db.statements[-1])
        self.assertIn("product_variants.company_id = 7", locked_sql)
        self.assertIn("FOR UPDATE", locked_sql)
        self.db.rollback.assert_awaited_once()
        self.db.commit.assert_not_awaited()
        self.db.begin.assert_not_called()
        self.db.rollback.reset_mock()
        with patch.object(module, "begin_idempotent_operation",
                          AsyncMock(return_value=(object(), {"replayed": True}))), \
                patch.object(module, "acquire_product_lifecycle_guards", AsyncMock()) as guard:
            result = await module._run_variant_state_command(variant_id=81, payload=payload,
                command="archive", permission="catalog.archive", db=self.db,
                access=access, legacy_actor=actor)
        self.assertEqual(result, {"replayed": True})
        guard.assert_not_awaited()
        self.db.rollback.assert_awaited_once()
        self.db.commit.assert_not_awaited()

    async def test_denied_mutation_has_no_idempotency_lock_or_transaction_side_effect(self):
        payload = module.LifecycleCommand(request_id=UUID("4e447464-7d22-4880-a0f0-e4549bf90e30"),
                                          expected_version=4, reason="Focused test")
        with patch.object(module, "begin_idempotent_operation", AsyncMock()) as begin, \
                patch.object(module, "acquire_product_lifecycle_guards", AsyncMock()) as guard:
            with self.assertRaises(HTTPException) as failure:
                await module._run_variant_state_command(variant_id=501, payload=payload,
                    command="publish", permission="catalog.publish", db=self.db,
                    access=self.access(), legacy_actor=SimpleNamespace(id=303, is_admin=True))
        self.assertEqual(failure.exception.status_code, 403)
        begin.assert_not_awaited()
        guard.assert_not_awaited()
        self.assert_read_only()


if __name__ == "__main__":
    unittest.main()
