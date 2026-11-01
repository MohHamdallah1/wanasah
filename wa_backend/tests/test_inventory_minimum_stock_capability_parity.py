"""CP6 authorization parity through real FastAPI dependencies; no PostgreSQL.

Canonical capability SQL executes against an in-memory SQLite grant store.
Business persistence/idempotency/projection seams are mocked: these tests do not
claim PostgreSQL locking, RLS or concurrency acceptance.
"""
from __future__ import annotations

import inspect
import os
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

os.environ.setdefault("SECRET_KEY", "CP6ParityFocusedTestKeyAa123456789012345678901234")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/cp6_unused"
)

import httpx
from fastapi import FastAPI
from sqlalchemy import Column, MetaData, Table, create_engine

from api import inventory_stock_policy as policy
from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
)
from api.authentication.backoffice_compatibility import (
    get_current_backoffice_legacy_driver,
)
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from models import (
    InventoryLocation,
    InventoryStockPolicy,
    Permission,
    SystemAuditLog,
    UserLocationAccess,
    UserRole,
    role_permissions,
)

MANAGE = "inventory.minimum_stock.manage"
LOCATION = 55
COMPANY = 77
VARIANT = 11
ROUTES = {
    "preview": ("POST", "/warehouse/inventory/minimum-stock/bulk/preview"),
    "bulk": ("PUT", "/warehouse/inventory/minimum-stock/bulk"),
    "single": ("PUT", "/warehouse/inventory/11/minimum-stock"),
}


class _AuthorizationDB:
    def __init__(self, connection):
        self.connection = connection
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.connection.execute(statement).scalar()


class _Result:
    def __init__(self, value=None, rows=()):
        self.value = value
        self.rows = list(rows)

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def mappings(self):
        return self

    def all(self):
        return list(self.rows)


class _BusinessDB:
    def __init__(self, results=()):
        self.results = list(results)
        self.added = []
        self.execute = AsyncMock(side_effect=self._execute)
        self.scalar = AsyncMock(return_value=1)
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def _execute(self, statement, *args, **kwargs):
        if not self.results:
            raise AssertionError("Unexpected business SQL")
        return self.results.pop(0)

    def add(self, value):
        self.added.append(value)


class _LegacyActor:
    id = 903

    @property
    def company_id(self):
        raise AssertionError("Legacy company is not tenant authority")

    @property
    def is_admin(self):
        raise AssertionError("Legacy admin flag is not authority")


class InventoryMinimumStockCapabilityParityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_engine("sqlite://")
        self.connection = self.engine.connect()
        metadata = MetaData()
        self.tables = {}
        for source, columns in (
            (InventoryLocation.__table__, "id company_id location_type is_active"),
            (Permission.__table__, "id code"),
            (UserRole.__table__, "company_id driver_id role_id"),
            (UserLocationAccess.__table__, "company_id driver_id role_id location_id"),
            (role_permissions, "company_id role_id permission_id"),
        ):
            self.tables[source.name] = Table(
                source.name,
                metadata,
                *(Column(name, source.c[name].type) for name in columns.split()),
            )
        metadata.create_all(self.connection)
        self.connection.execute(
            self.tables[InventoryLocation.__tablename__].insert(),
            [
                {"id": 55, "company_id": 77, "location_type": "WAREHOUSE", "is_active": True},
                {"id": 56, "company_id": 77, "location_type": "WAREHOUSE", "is_active": True},
                {"id": 99, "company_id": 88, "location_type": "WAREHOUSE", "is_active": True},
            ],
        )
        self.connection.execute(
            self.tables[Permission.__tablename__].insert(),
            [{"id": 1, "code": MANAGE}, {"id": 2, "code": "inventory.read"}],
        )
        self.connection.execute(
            self.tables[role_permissions.name].insert(),
            [
                {"company_id": company, "role_id": role, "permission_id": permission}
                for company in (77, 88)
                for role, permission in ((10, 1), (20, 2))
            ],
        )
        # Same legacy locator, foreign-company grants: never authority in company 77.
        self.connection.execute(
            self.tables[UserRole.__tablename__].insert(),
            [{"company_id": 88, "driver_id": 903, "role_id": 10}],
        )
        self.connection.execute(
            self.tables[UserLocationAccess.__tablename__].insert(),
            [{"company_id": 88, "driver_id": 903, "role_id": 20, "location_id": 99}],
        )
        self.auth_db = _AuthorizationDB(self.connection)
        self._grants()
        self.business_db = _BusinessDB()
        self.app = FastAPI()
        self.app.include_router(policy.router)

        async def access_override():
            return self.access

        async def db_override():
            return self.business_db

        async def actor_override():
            return _LegacyActor()

        self.app.dependency_overrides[get_current_backoffice_capability_access] = access_override
        self.app.dependency_overrides[get_db] = db_override
        self.app.dependency_overrides[get_current_backoffice_legacy_driver] = actor_override
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://cp6.test"
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        self.connection.close()
        self.engine.dispose()

    def _grants(self, *, manage=True, readable=(55,), owner=False):
        roles = self.tables[UserRole.__tablename__]
        locations = self.tables[UserLocationAccess.__tablename__]
        self.connection.execute(roles.delete().where(roles.c.company_id == COMPANY))
        self.connection.execute(locations.delete().where(locations.c.company_id == COMPANY))
        if manage:
            self.connection.execute(
                roles.insert(), {"company_id": COMPANY, "driver_id": 903, "role_id": 10}
            )
        if readable:
            self.connection.execute(
                locations.insert(),
                [
                    {"company_id": COMPANY, "driver_id": 903, "role_id": 20, "location_id": value}
                    for value in readable
                ],
            )
        self.access = BackofficeCapabilityAccess(
            db=self.auth_db,
            subject=BackofficeAuthorizationSubject(
                principal_id=101,
                backoffice_user_id=202,
                company_id=COMPANY,
                is_company_owner=owner,
                legacy_grant_driver_id=None if owner else 903,
            ),
        )

    def _body(self, kind):
        if kind == "single":
            return {
                "request_id": str(uuid4()), "location_id": LOCATION, "uom_id": 1,
                "minimum_quantity": "2", "expected_minimum_quantity": "1",
            }
        body = {
            "location_id": LOCATION, "scope": "PRODUCT",
            "product_variant_ids": [VARIANT], "minimum_quantity": "2",
            "apply_mode": "OVERWRITE",
        }
        if kind == "bulk":
            body["request_id"] = str(uuid4())
        return body

    def _business(self, kind, *, minimum="1", target="10", active=True,
                  scale=0, step="1", factor="1", conversion=False,
                  assigned=True, warehouse=True):
        current = SimpleNamespace(
            product_variant_id=VARIANT, minimum_quantity=Decimal(minimum),
            target_quantity=Decimal(target) if target is not None else None,
            is_active=active,
        )
        if kind == "single":
            results = [
                _Result(value=SimpleNamespace(id=LOCATION) if warehouse else None),
                _Result(value=SimpleNamespace(
                    base_uom_id=1, quantity_scale=scale, quantity_step=Decimal(step),
                )),
            ]
            if conversion:
                results.append(_Result(rows=[
                    SimpleNamespace(numerator=Decimal("5"), denominator=Decimal("2"))
                ]))
            results.extend([_Result(), _Result(value=current)])
        else:
            candidate = {
                "variant_id": VARIANT, "base_uom_id": 1, "quantity_scale": scale,
                "quantity_step": Decimal(step), "family_id": 3,
                "display_candidate_count": 1, "display_uom_id": 2,
                "display_factor_to_base": Decimal(factor),
            }
            results = [
                _Result(value=LOCATION if warehouse else None),
                _Result(rows=[candidate]),
            ]
            if kind == "bulk":
                results.append(_Result())  # Existing policy advisory lock.
            results.append(_Result(rows=[current]))
        db = _BusinessDB(results)
        db.scalar.return_value = 1 if assigned else None
        return db, current

    async def _request(self, kind, *, body=None, db=None, replay=None,
                       projection_error=None):
        self.business_db = db if db is not None else self._business(kind)[0]
        self.begin = AsyncMock(return_value=(SimpleNamespace(), replay))
        self.complete = Mock()
        self.refresh = AsyncMock(side_effect=projection_error)
        method, url = ROUTES[kind]
        with (
            patch.object(policy, "begin_idempotent_operation", self.begin),
            patch.object(policy, "complete_idempotent_operation", self.complete),
            patch.object(policy, "refresh_live_stock_keys", self.refresh),
        ):
            return await self.client.request(method, url, json=body or self._body(kind))

    def _assert_no_business_access(self, db):
        db.execute.assert_not_awaited()
        db.scalar.assert_not_awaited()
        db.flush.assert_not_awaited()
        db.commit.assert_not_awaited()
        self.assertEqual(db.added, [])
        self.begin.assert_not_awaited()

    async def test_preview_and_both_writes_have_equivalent_capability_requirements(self):
        cases = (
            (True, (55,), 200),
            (True, (), 403),
            (False, (55,), 403),
            (True, (56,), 403),
            (False, (), 403),
        )
        for kind in ROUTES:
            for manage, readable, expected in cases:
                with self.subTest(kind=kind, manage=manage, readable=readable):
                    self._grants(manage=manage, readable=readable)
                    db, _ = self._business(kind)
                    response = await self._request(kind, db=db)
                    self.assertEqual(response.status_code, expected, response.text)
                    if expected == 403:
                        self.assertEqual(response.json(), {"detail": "Authorization denied."})
                        self._assert_no_business_access(db)

    async def test_foreign_and_missing_locations_are_opaque_even_for_owner(self):
        for owner in (False, True):
            for kind in ROUTES:
                bodies = []
                for location in (99, 999):
                    with self.subTest(owner=owner, kind=kind, location=location):
                        self._grants(owner=owner, readable=(55, 56))
                        body = self._body(kind)
                        body["location_id"] = location
                        db = _BusinessDB()
                        response = await self._request(kind, body=body, db=db)
                        self.assertEqual(response.status_code, 403, response.text)
                        self._assert_no_business_access(db)
                        bodies.append(response.json())
                self.assertEqual(bodies[0], bodies[1])

    async def test_canonical_owner_needs_no_grant_but_keeps_business_validation(self):
        self._grants(manage=False, readable=(), owner=True)
        for kind in ROUTES:
            with self.subTest(kind=kind):
                response = await self._request(kind)
                self.assertEqual(response.status_code, 200, response.text)
                db, _ = self._business(kind, warehouse=False)
                response = await self._request(kind, db=db)
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(response.json()["detail"]["code"], "STOCK_MINIMUM_LOCATION_NOT_FOUND")
                db.commit.assert_not_awaited()
                sql = str(db.execute.await_args_list[0].args[0].compile(
                    compile_kwargs={"literal_binds": True}
                ))
                self.assertIn("inventory_locations.company_id = 77", sql)
                self.assertIn("inventory_locations.is_active IS true", sql)
        self.assertTrue(all("user_roles" not in str(stmt) for stmt in self.auth_db.statements))

    async def test_nonowner_independent_ids_preserve_canonical_tenant_and_audit_actor(self):
        for kind in ("bulk", "single"):
            with self.subTest(kind=kind):
                self._grants()
                response = await self._request(kind)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(self.begin.await_args.kwargs["company_id"], COMPANY)
                self.assertEqual(self.begin.await_args.kwargs["actor_id"], 903)
                audits = [row for row in self.business_db.added if isinstance(row, SystemAuditLog)]
                self.assertEqual(len(audits), 1)
                self.assertEqual((audits[0].company_id, audits[0].admin_id), (77, 903))
                self.assertEqual(audits[0].old_value, "1")
                self.assertEqual(audits[0].new_value, "2")
                self.assertEqual(self.refresh.await_args.kwargs["company_id"], COMPANY)
                self.assertEqual(self.refresh.await_args.kwargs["keys"], [(55, 11)])
                self.complete.assert_called_once()
                self.business_db.commit.assert_awaited_once()
        grant_sql = "\n".join(str(stmt.compile(
            compile_kwargs={"literal_binds": True}
        )) for stmt in self.auth_db.statements)
        self.assertIn("driver_id = 903", grant_sql)
        self.assertNotIn("driver_id = 101", grant_sql)
        self.assertNotIn("driver_id = 202", grant_sql)

    async def test_replay_rechecks_current_manage_and_exact_location_read(self):
        for kind in ("bulk", "single"):
            body = self._body(kind)
            replay = {"location_id": LOCATION, "changed": False, "replayed": True}
            self._grants()
            response = await self._request(kind, body=body, replay=replay)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), replay)
            self.business_db.commit.assert_not_awaited()
            self.business_db.rollback.assert_awaited_once()
            self.complete.assert_not_called()
            self.refresh.assert_not_awaited()
            for manage, readable in ((False, (55,)), (True, ()), (True, (56,))):
                with self.subTest(kind=kind, manage=manage, readable=readable):
                    self._grants(manage=manage, readable=readable)
                    db = _BusinessDB()
                    response = await self._request(kind, body=body, db=db, replay=replay)
                    self.assertEqual(response.status_code, 403, response.text)
                    self._assert_no_business_access(db)

    async def test_bulk_scopes_modes_and_conversion_keep_existing_semantics(self):
        for scope in ("ALL", "FAMILY", "PRODUCT"):
            for mode in ("ONLY_UNSET", "OVERWRITE"):
                with self.subTest(scope=scope, mode=mode):
                    body = self._body("bulk")
                    body.update(scope=scope, apply_mode=mode, product_variant_ids=[])
                    if scope == "PRODUCT":
                        body["product_variant_ids"] = [11]
                    elif scope == "FAMILY":
                        body["family_ids"] = [3]
                    db, current = self._business("bulk", factor="2.5")
                    response = await self._request("bulk", body=body, db=db)
                    self.assertEqual(response.status_code, 200, response.text)
                    skipped = mode == "ONLY_UNSET"
                    self.assertEqual(response.json()["skipped_existing_count"], int(skipped))
                    self.assertEqual(response.json()["affected_count"], 0 if skipped else 1)
                    self.assertEqual(response.json()["unit_mode"], "DISPLAY_UOM_PER_PRODUCT")
                    self.assertEqual(current.minimum_quantity, Decimal("1" if skipped else "5"))
                    if skipped:
                        self.refresh.assert_not_awaited()
                    else:
                        self.refresh.assert_awaited_once()
                    db.commit.assert_awaited_once()

    async def test_single_direct_uom_conversion_keeps_expected_minimum_in_base_units(self):
        body = self._body("single")
        body["uom_id"] = 2
        db, current = self._business("single", conversion=True)
        response = await self._request("single", body=body, db=db)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["minimum_quantity"], "5")
        self.assertEqual(response.json()["entered_quantity"], "2")
        self.assertEqual(current.minimum_quantity, Decimal("5"))

    async def test_single_unassigned_catalog_product_and_version_target_precision_guards(self):
        cases = (
            ({}, {"expected_minimum_quantity": "0"}, 409, "STOCK_MINIMUM_VERSION_CONFLICT"),
            ({"target": "1"}, {}, 409, "STOCK_MINIMUM_EXCEEDS_TARGET"),
            ({"active": False}, {}, 409, "STOCK_MINIMUM_POLICY_INACTIVE"),
            ({}, {"minimum_quantity": "1.5"}, 422, "STOCK_MINIMUM_QUANTITY_INVALID"),
            ({"minimum": "2", "step": "2"}, {"minimum_quantity": "3", "expected_minimum_quantity": "2"},
             422, "STOCK_MINIMUM_QUANTITY_INVALID"),
        )
        for setup, changes, status, code in cases:
            with self.subTest(code=code, setup=setup):
                body = self._body("single")
                body.update(changes)
                db, current = self._business("single", **setup)
                before = current.minimum_quantity
                response = await self._request("single", body=body, db=db)
                self.assertEqual(response.status_code, status, response.text)
                self.assertEqual(response.json()["detail"]["code"], code)
                self.assertEqual(current.minimum_quantity, before)
                db.commit.assert_not_awaited()
                db.rollback.assert_awaited_once()
                self.refresh.assert_not_awaited()
                self.complete.assert_not_called()

    async def test_active_unassigned_catalog_product_accepts_minimum_without_provisioning(self):
        # A threshold is policy, not ProductLocation assignment or physical stock.
        # All three entry points must accept a company-owned ACTIVE variant.
        for kind in ("preview", "bulk", "single"):
            with self.subTest(kind=kind):
                db, current = self._business(kind, assigned=False)
                response = await self._request(kind, db=db)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json().get("matched_count", 1), 1)
                if kind != "preview":
                    self.assertEqual(current.minimum_quantity, Decimal("2"))
                    db.commit.assert_awaited_once()
                    self.refresh.assert_awaited_once()
                statements = [
                    str(call.args[0]) for call in db.execute.await_args_list
                ]
                self.assertTrue(statements)
                self.assertFalse(any("product_locations" in query for query in statements))

    async def test_bulk_conflicts_remain_atomic_before_audit_projection_and_commit(self):
        for setup in ({"target": "1"}, {"active": False}, {"step": "3"}):
            with self.subTest(setup=setup):
                db, current = self._business("bulk", **setup)
                response = await self._request("bulk", db=db)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(response.json()["detail"]["code"], "STOCK_MINIMUM_BULK_CONFLICT")
                self.assertEqual(current.minimum_quantity, Decimal("1"))
                self.assertEqual(db.added, [])
                db.commit.assert_not_awaited()
                db.rollback.assert_awaited_once()
                self.refresh.assert_not_awaited()

    async def test_bulk_company_catalog_candidates_and_tenant_predicates(self):
        for kind in ("preview", "bulk"):
            db, _ = self._business(kind)
            response = await self._request(kind, db=db)
            self.assertEqual(response.status_code, 200, response.text)
            statements = [
                call.args[0] for call in db.execute.await_args_list
                if "GROUP BY" in str(call.args[0])
            ]
            self.assertEqual(len(statements), 1)
            sql = str(statements[0].compile(compile_kwargs={"literal_binds": True}))
            self.assertIn("FROM product_variants", sql)
            self.assertNotIn("product_locations", sql)
            self.assertIn("product_variants.company_id = 77", sql)
            self.assertIn("product_variants.lifecycle_status = 'ACTIVE'", sql)

    async def test_projection_failure_preserves_transaction_rollback(self):
        for kind in ("bulk", "single"):
            with self.subTest(kind=kind):
                response = await self._request(
                    kind, projection_error=policy.LiveStockProjectionError("unavailable")
                )
                self.assertEqual(response.status_code, 503, response.text)
                self.business_db.commit.assert_not_awaited()
                self.business_db.rollback.assert_awaited_once()
                self.complete.assert_not_called()

    def test_no_extra_route_or_body_envelope_and_manage_dependency_is_retained(self):
        observed = set()
        for route in self.app.routes:
            if not hasattr(route, "dependant") or "minimum-stock" not in route.path:
                continue
            observed.update(
                (method, route.path.replace("{product_variant_id}", str(VARIANT)))
                for method in route.methods
            )
            calls = []

            def visit(dependant):
                calls.append(dependant.call)
                for nested in dependant.dependencies:
                    visit(nested)

            visit(route.dependant)
            self.assertIn(policy._manage_minimum_stock, calls)
            self.assertIn(get_current_backoffice_capability_access, calls)
            if "PUT" in route.methods:
                self.assertIn(get_current_backoffice_legacy_driver, calls)
        self.assertEqual(observed, set(ROUTES.values()))
        source = inspect.getsource(policy)
        self.assertNotIn(".is_admin", source)
        self.assertNotIn("legacy_actor.company_id", source)

    async def test_bulk_create_preserves_existing_policy_defaults(self):
        body = self._body("bulk")
        db, _ = self._business("bulk")
        db.results[-1] = _Result(rows=[])
        response = await self._request("bulk", body=body, db=db)
        self.assertEqual(response.status_code, 200, response.text)
        created = [row for row in db.added if isinstance(row, InventoryStockPolicy)]
        self.assertEqual(len(created), 1)
        self.assertEqual((created[0].company_id, created[0].location_id, created[0].product_variant_id),
                         (COMPANY, LOCATION, VARIANT))
        self.assertEqual(created[0].minimum_quantity, Decimal("2"))
        self.assertIsNone(created[0].target_quantity)
        self.assertEqual(created[0].minimum_remaining_shelf_life_days, 0)
        self.assertTrue(created[0].is_active)


if __name__ == "__main__":
    unittest.main()
