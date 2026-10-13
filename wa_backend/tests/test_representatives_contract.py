"""Wave 1 wire contract from plan section 0.2 at 8d6ab2663598bb9ae9144bf319863a2bd9eb421e.

Run: python -m unittest discover -s wa_backend/tests -p 'test_representatives*.py' -v

Router/response/dependency checks fail explicitly on the pre-implementation base.
Real SQL/HTTP tests opt in with WANASAH_REPRESENTATIVES_CONTRACT_DB_URL
(an already-migrated, disposable PostgreSQL DB named representatives_contract_*).
No schema creation/migration or installation happens here. Each test rolls back
its outer transaction, including router commits via SAVEPOINTs.

Authentication is overridden with persisted canonical fixture contexts; actual
subject resolution, capability decisions, route validation, services and SQL run.
These tests do not certify JWT decoding, deployment RLS or concurrent lifecycle
safety; those belong to the respective foundation/implementation gates.
"""
from __future__ import annotations

import importlib
from decimal import Decimal
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4


BACKEND = Path(__file__).resolve().parents[1]
ROUTES = {
    ("GET", "/representatives"): "representative.read",
    ("GET", "/representatives/{representative_id}"): "representative.read",
    ("POST", "/representatives"): "representative.manage",
    ("PATCH", "/representatives/{representative_id}"): "representative.manage",
    ("POST", "/representatives/{representative_id}/deactivate"): "representative.manage",
    ("POST", "/representatives/{representative_id}/reactivate"): "representative.manage",
    ("POST", "/representatives/{representative_id}/credentials/reset"): "representative.credentials.reset",
}
DB_URL = os.getenv("WANASAH_REPRESENTATIVES_CONTRACT_DB_URL")
VIEW_FIELDS = {"id", "full_name", "username", "phone_number", "is_active", "can_allow_debt", "max_debt_limit"}


def runtime():
    if not (BACKEND / "api/representatives/__init__.py").is_file():
        raise AssertionError("Wave 1 implementation missing: api/representatives")
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    # Import only the dedicated router, never the whole operational application.
    # Fallback configuration has no reachable DB and is only for import/DTO checks.
    fallback = {
        "SECRET_KEY": "RepresentativesContractSyntheticKey123456789",
        "DATABASE_URL": "postgresql+asyncpg://contract@127.0.0.1:1/representatives_contract_unavailable",
    }
    with patch.dict(os.environ, {key: value for key, value in fallback.items() if not os.getenv(key)}):
        fastapi = importlib.import_module("fastapi")
        representatives = importlib.import_module("api.representatives")
        app = fastapi.FastAPI()
        app.include_router(representatives.router)
    return app


def dependencies(dependant):
    yield dependant
    for child in dependant.dependencies:
        yield from dependencies(child)


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def representative_record(value, username):
    return next(row for row in objects(value) if row.get("username") == username)


def body(operation, *, username=None):
    request = {"request_id": str(uuid4())}
    if operation == "create":
        request.update(full_name="Contract Representative", username=username or "created-" + uuid4().hex,
                       phone_number=None, password="SyntheticRepresentative123",
                       can_allow_debt=False, max_debt_limit="0.000")
    elif operation == "patch":
        request.update(phone_number=None)
    elif operation == "reset":
        request.update(new_password="SyntheticResetRepresentative123")
    elif operation not in {"deactivate", "reactivate"}:
        raise AssertionError(f"Unknown test operation {operation}")
    return request


class RepresentativesHTTPShapeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = runtime()

    def test_frozen_routes_exist_and_have_dedicated_canonical_backoffice_dependencies(self):
        from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
        from api.authentication.dependencies import get_current_backoffice_context

        routes = { (method, route.path.rstrip("/")): route
                   for route in self.app.routes if route.path.startswith("/representatives")
                   for method in route.methods }
        self.assertEqual(set(routes), set(ROUTES))  # Includes the no-DELETE invariant.
        for key, route in routes.items():
            with self.subTest(route=key):
                self.assertTrue(route.endpoint.__module__.startswith("api.representatives."))
                calls = {item.call for item in dependencies(route.dependant)}
                self.assertIn(get_current_backoffice_capability_access, calls)
                self.assertIn(get_current_backoffice_context, calls)
                names = {getattr(call, "__name__", "") for call in calls}
                self.assertTrue(names.isdisjoint({"get_current_driver", "get_current_admin", "get_current_field_context"}))

    def test_list_detail_wire_schemas_and_reset_no_content(self):
        schema = self.app.openapi()
        for method, path in (("get", "/representatives"),
                             ("get", "/representatives/{representative_id}")):
            operation = schema["paths"][path][method]
            self.assertIn("200", operation["responses"])
            successful = [operation["responses"]["200"]]
            pending = list(successful)
            seen = set()
            view_found = False
            envelope_found = False
            while pending:
                value = pending.pop()
                for node in objects(value):
                    ref = node.get("$ref")
                    if ref and ref not in seen:
                        seen.add(ref)
                        target = schema
                        for part in ref.removeprefix("#/").split("/"):
                            target = target[part]
                        pending.append(target)
                    properties = set(node.get("properties", {}))
                    if "username" in properties:
                        self.assertEqual(properties, VIEW_FIELDS)
                        view_found = True
                    if "items" in properties:
                        self.assertEqual(properties, {"items", "next_cursor", "has_more"})
                        envelope_found = True
                    self.assertTrue(properties.isdisjoint({"password_hash", "password", "initial_password", "principal_id", "driver_id", "capabilities", "auth_revision"}))
            self.assertTrue(view_found, "Representative view must be an explicit response contract")
            if path == "/representatives":
                self.assertTrue(envelope_found)
        reset = schema["paths"]["/representatives/{representative_id}/credentials/reset"]["post"]
        self.assertIn("204", reset["responses"])
        self.assertNotIn("content", reset["responses"]["204"])
        query = {parameter["name"]: parameter["schema"]
                 for parameter in schema["paths"]["/representatives"]["get"]["parameters"]
                 if parameter["in"] == "query"}
        self.assertEqual(set(query), {"search", "active", "cursor", "limit"})
        self.assertEqual({key: query["limit"][key] for key in ("default", "minimum", "maximum")},
                         {"default": 30, "minimum": 1, "maximum": 100})
        for name, constraints in (("search", {"minLength": 2, "maxLength": 100}), ("cursor", {"maxLength": 512})):
            choices = query[name].get("anyOf", [query[name]])
            string = next(choice for choice in choices if choice.get("type") == "string")
            self.assertEqual({key: string[key] for key in constraints}, constraints)

    async def test_unauthenticated_requests_fail_before_business_data_access(self):
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://representative-contract") as client:
            for method, path in ROUTES:
                with self.subTest(route=(method, path)):
                    path = path.replace("{representative_id}", "202")
                    operation = "create" if path == "/representatives" else "patch" if method == "PATCH" else path.rsplit("/", 1)[-1]
                    kwargs = {"json": body(operation)} if method != "GET" else {}
                    self.assertEqual((await client.request(method, path, **kwargs)).status_code, 401)


@unittest.skipUnless(DB_URL, "Needs explicitly isolated, migrated Representatives PostgreSQL database; not executed")
class RepresentativesSQLHTTPContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.engine import make_url
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.pool import NullPool
        from sqlalchemy import text
        import httpx

        url = make_url(DB_URL)
        self.assertEqual(url.drivername, "postgresql+asyncpg")
        self.assertTrue((url.database or "").startswith("representatives_contract_"), "Refuse non-gate databases")
        self.app = runtime()
        self.engine = create_async_engine(url, poolclass=NullPool)
        self.addAsyncCleanup(self.engine.dispose)
        self.connection = await self.engine.connect()
        self.addAsyncCleanup(self.connection.close)
        self.outer = await self.connection.begin()
        self.addAsyncCleanup(self.outer.rollback)
        self.db = AsyncSession(bind=self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        self.addAsyncCleanup(self.db.close)
        self.text = text

        from models import Company
        from tests.canonical_actor_fixtures import seed_company_owner_fixture, seed_ordinary_backoffice_fixture, seed_field_fixture
        from database import get_db
        from api.authentication.dependencies import get_current_backoffice_context

        self.companies = [Company(name="Representative contract " + uuid4().hex,
                                  company_code="RC" + uuid4().hex) for _ in range(2)]
        self.db.add_all(self.companies)
        await self.db.flush()
        self.owners, self.fields = [], []
        for company in self.companies:
            await self.tenant(company.id)
            self.owners.append(await seed_company_owner_fixture(self.db, company.id, password="SyntheticRepresentative123"))
            self.fields.append(await seed_field_fixture(self.db, company.id))
        await self.tenant(self.companies[0].id)
        self.ordinary = await seed_ordinary_backoffice_fixture(self.db, self.companies[0].id)
        await self.tenant(self.companies[1].id)
        self.foreign_ordinary = await seed_ordinary_backoffice_fixture(self.db, self.companies[1].id)
        from sqlalchemy import select
        from models import Permission
        for code in set(ROUTES.values()):
            if await self.db.scalar(select(Permission.id).where(Permission.code == code)) is None:
                self.db.add(Permission(code=code))
        await self.db.commit()  # Release seed SAVEPOINT only; outer transaction owns cleanup.
        self.current = self.owners[0]
        await self.tenant(self.current.context.company_id)
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_current_backoffice_context] = lambda: self.current.context
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://representative-contract")
        self.addAsyncCleanup(self.client.aclose)

    async def tenant(self, company_id):
        await self.db.execute(self.text("SELECT set_config('app.current_tenant', :tenant, true)"), {"tenant": str(company_id)})

    async def request(self, method, path, **kwargs):
        await self.tenant(self.current.context.company_id)
        return await self.client.request(method, path, **kwargs)

    def safe(self, response):
        for node in objects(response.json()):
            self.assertTrue(set(node).isdisjoint({"password_hash", "password", "initial_password"}))

    def view(self, row):
        self.assertEqual(set(row), VIEW_FIELDS)
        self.assertIs(type(row["id"]), int)
        self.assertIs(type(row["is_active"]), bool)
        self.assertIs(type(row["can_allow_debt"]), bool)
        self.assertGreaterEqual(Decimal(str(row["max_debt_limit"])), Decimal("0"))

    async def detail(self, field):
        response = await self.request("GET", f"/representatives/{field.context.representative_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.safe(response)
        self.view(response.json())
        return response.json()

    async def test_owner_reads_only_field_profiles_with_independent_ids_and_no_secrets(self):
        field = self.fields[0]
        self.assertEqual(len({field.context.principal_id, field.context.representative_id, field.driver.id}), 3)
        response = await self.request("GET", "/representatives")
        self.assertEqual(response.status_code, 200, response.text)
        self.safe(response)
        self.assertEqual(set(response.json()), {"items", "next_cursor", "has_more"})
        from domains.identity.models import CompanyPrincipal
        principal = await self.db.get(CompanyPrincipal, field.context.principal_id)
        row = representative_record(response.json(), principal.username)
        self.assertEqual(row["id"], field.context.representative_id)
        self.view(row)
        detail = await self.detail(field)
        self.assertEqual(detail["id"], field.context.representative_id)
        owner_principal = await self.db.get(CompanyPrincipal, self.owners[0].context.principal_id)
        self.assertFalse(any(node.get("username") == owner_principal.username
                             for node in objects(response.json())))
        self.assertFalse(any(node["id"] == self.fields[1].context.representative_id
                             for node in objects(response.json()) if "username" in node))

    async def test_cross_company_detail_and_every_targeted_mutation_match_missing_objects(self):
        self.current = self.owners[1]
        own_detail = await self.detail(self.fields[1])
        from domains.identity.models import CompanyPrincipal
        principal = await self.db.get(CompanyPrincipal, self.fields[1].context.principal_id)
        self.current = self.owners[0]  # Owner must still obey object/tenant isolation.
        foreign = self.fields[1].context.representative_id
        absent = 2_147_483_647
        paths = [("GET", "", None), ("PATCH", "", "patch"),
                 ("POST", "/deactivate", "deactivate"), ("POST", "/reactivate", "reactivate"),
                 ("POST", "/credentials/reset", "reset")]
        for method, suffix, operation in paths:
            with self.subTest(operation=operation or "detail"):
                kwargs = {"json": body(operation)} if operation else {}
                response = await self.request(method, f"/representatives/{foreign}{suffix}", **kwargs)
                missing = await self.request(method, f"/representatives/{absent}{suffix}", **kwargs)
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(response.status_code, missing.status_code)
                # Correlation IDs may differ; the stable reason must not.
                def reason(value):
                    if isinstance(value, dict):
                        return {key: reason(child) for key, child in value.items()
                                if key not in {"request_id", "correlation_id", "representative_id"}}
                    return value
                self.assertEqual(reason(response.json()), reason(missing.json()))
                self.assertNotIn(principal.username, response.text)
        self.current = self.owners[1]
        self.assertEqual(await self.detail(self.fields[1]), own_detail, "Denied requests must not mutate the foreign representative")

    async def test_exact_company_capabilities_and_legacy_persona_flags_have_no_authority(self):
        from domains.identity.models import CompanyPrincipal
        from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
        from types import SimpleNamespace

        principal = await self.db.get(CompanyPrincipal, self.fields[0].context.principal_id)
        self.current = self.ordinary
        self.assertEqual(len({self.current.context.principal_id, self.current.context.backoffice_user_id, self.current.driver_id}), 3)
        for flag in (False, True):
            # Synthetic non-ORM sentinel: the removed column is never constructed.
            actor = SimpleNamespace(**vars(self.current.operational_driver), is_admin=flag)
            self.app.dependency_overrides[get_current_backoffice_legacy_driver] = lambda: actor
            for (method, path), capability in ROUTES.items():
                with self.subTest(flag=flag, route=(method, path)):
                    path = path.replace("{representative_id}", str(self.fields[0].context.representative_id))
                    operation = "create" if path == "/representatives" else "patch" if method == "PATCH" else path.rsplit("/", 1)[-1]
                    kwargs = {"json": body(operation)} if method != "GET" else {}
                    denied = await self.request(method, path, **kwargs)
                    self.assertEqual(denied.status_code, 403, denied.text)
        # A foreign-company role cannot grant read authority in the current company.
        # Use actual canonical grant storage; never simulate policy in a fake access.
        for company, location_only in ((self.companies[1].id, False), (self.companies[0].id, True), (self.companies[0].id, False)):
            await self.tenant(company)
            role = await self.db.scalar(self.text("INSERT INTO roles(company_id,name,is_system_role) VALUES(:company,:name,false) RETURNING id"),
                                       {"company": company, "name": "Representative read " + uuid4().hex})
            await self.db.execute(self.text("INSERT INTO role_permissions(company_id,role_id,permission_id) SELECT :company,:role,id FROM permissions WHERE code='representative.read'"),
                                  {"company": company, "role": role})
            if location_only:
                from models import InventoryLocation
                location = InventoryLocation(company_id=company, code="RC" + uuid4().hex, name="Contract warehouse", location_type="WAREHOUSE")
                self.db.add(location); await self.db.flush()
                await self.db.execute(self.text("INSERT INTO user_location_access(company_id,driver_id,role_id,location_id) VALUES(:company,:actor,:role,:location)"),
                                      {"company": company, "actor": self.current.driver_id, "role": role, "location": location.id})
            else:
                await self.db.execute(self.text("INSERT INTO user_roles(company_id,driver_id,role_id) VALUES(:company,:actor,:role)"),
                                      {"company": company, "actor": self.current.driver_id if company == self.current.context.company_id else self.foreign_ordinary.driver_id, "role": role})
            await self.db.commit()  # Persist grants within outer rollback boundary.
            response = await self.request("GET", "/representatives")
            self.assertEqual(response.status_code, 200 if company == self.current.context.company_id and not location_only else 403)
        self.assertEqual(representative_record(response.json(), principal.username)["id"], self.fields[0].context.representative_id)
        self.assertEqual((await self.request("POST", "/representatives", json=body("create"))).status_code, 403)
        # Replace this one company role's capabilities, rather than accumulating
        # grants: every endpoint must accept its exact capability and reject the
        # other two. A valid target/DTO prevents 422 from masquerading as denial.
        for granted in sorted(set(ROUTES.values())):
            await self.db.execute(self.text("DELETE FROM role_permissions WHERE company_id=:company AND role_id=:role"),
                                  {"company": self.current.context.company_id, "role": role})
            await self.db.execute(self.text("INSERT INTO role_permissions(company_id,role_id,permission_id) SELECT :company,:role,id FROM permissions WHERE code=:code"),
                                  {"company": self.current.context.company_id, "role": role, "code": granted})
            await self.db.commit()
            for (method, path), required in ROUTES.items():
                with self.subTest(granted=granted, route=(method, path)):
                    path = path.replace("{representative_id}", str(self.fields[0].context.representative_id))
                    operation = "create" if path == "/representatives" else "patch" if method == "PATCH" else path.rsplit("/", 1)[-1]
                    kwargs = {"json": body(operation)} if method != "GET" else {}
                    response = await self.request(method, path, **kwargs)
                    if granted == required:
                        expected = 201 if operation == "create" and method == "POST" else 204 if operation == "reset" else 200
                        if operation in {"deactivate", "reactivate"}:
                            self.assertGreaterEqual(response.status_code, 200, response.text)
                            self.assertLess(response.status_code, 300, response.text)
                        else:
                            self.assertEqual(response.status_code, expected, response.text)
                    else:
                        self.assertEqual(response.status_code, 403, response.text)
        # A trusted FIELD context is still the wrong channel for this HTTP family.
        self.current = self.fields[0]
        denied = await self.request("GET", "/representatives")
        self.assertEqual(denied.status_code, 403, denied.text)

    async def test_create_is_company_scoped_field_only_and_invalid_debt_never_persists(self):
        from sqlalchemy import func, select
        from domains.identity.models import BackofficeUser, CompanyPrincipal, FieldRepresentative

        username = "created-" + uuid4().hex
        payload = body("create", username=username)
        response = await self.request("POST", "/representatives", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        self.safe(response)
        self.view(response.json())
        principal = await self.db.scalar(select(CompanyPrincipal).where(CompanyPrincipal.company_id == self.current.context.company_id, CompanyPrincipal.username == username))
        self.assertIsNotNone(principal)
        self.assertEqual(principal.principal_type, "FIELD_REPRESENTATIVE")
        profile = await self.db.scalar(select(FieldRepresentative).where(FieldRepresentative.company_id == self.current.context.company_id, FieldRepresentative.principal_id == principal.id))
        self.assertIsNotNone(profile)
        self.assertEqual(profile.principal_type, "FIELD_REPRESENTATIVE")
        self.assertIsNone(await self.db.scalar(select(BackofficeUser.id).where(BackofficeUser.company_id == principal.company_id, BackofficeUser.principal_id == principal.id)))
        baseline = await self.db.scalar(select(func.count()).select_from(CompanyPrincipal).where(CompanyPrincipal.company_id == self.current.context.company_id))
        for changes in ({"max_debt_limit": "-0.001", "can_allow_debt": True}, {"max_debt_limit": "not-a-number"},
                        {"username": []}, {"full_name": ""}, {"password": "short"}, {"request_id": "not-a-uuid"},
                        {"username": "x" * 81}, {"full_name": "x" * 121}, {"phone_number": "1" * 21}, {"password": "x" * 73}):
            with self.subTest(changes=changes):
                invalid = {**body("create"), **changes}
                rejected = await self.request("POST", "/representatives", json=invalid)
                self.assertEqual(rejected.status_code, 422, rejected.text)
                self.assertEqual(await self.db.scalar(select(func.count()).select_from(CompanyPrincipal).where(CompanyPrincipal.company_id == self.current.context.company_id)), baseline)
        for forbidden in ({"company_id": self.companies[1].id}, {"principal_type": "BACKOFFICE"},
                          {"principal_id": principal.id}, {"representative_id": profile.id},
                          {"role": "Owner"}, {"capabilities": ["representative.manage"]}, {"is_admin": True}):
            with self.subTest(forbidden=forbidden):
                rejected = await self.request("POST", "/representatives", json={**body("create"), **forbidden})
                self.assertEqual(rejected.status_code, 422, rejected.text)
                self.assertEqual(await self.db.scalar(select(func.count()).select_from(CompanyPrincipal).where(CompanyPrincipal.company_id == self.current.context.company_id)), baseline)
        defaults = body("create")
        defaults.pop("can_allow_debt"); defaults.pop("max_debt_limit")
        response = await self.request("POST", "/representatives", json=defaults)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertIs(response.json()["can_allow_debt"], False)
        self.assertEqual(Decimal(str(response.json()["max_debt_limit"])), Decimal("0.000"))
        await self.tenant(self.companies[1].id)
        self.assertIsNone(await self.db.scalar(select(CompanyPrincipal.id).where(CompanyPrincipal.company_id == self.companies[1].id, CompanyPrincipal.username == username)))

    async def test_list_filters_order_and_opaque_cursor_are_tenant_safe(self):
        from domains.identity.models import CompanyPrincipal
        from tests.canonical_actor_fixtures import seed_field_fixture

        fixtures = [self.fields[0]]
        for name, active in (("Alpha", True), ("Alpha", True), ("Aardvark", False)):
            field = await seed_field_fixture(self.db, self.current.context.company_id)
            fixtures.append(field)
            principal = await self.db.get(CompanyPrincipal, field.context.principal_id)
            principal.full_name = name
            principal.is_active = active
            principal.phone_number = "0771234567" if not active else None
        await self.db.commit()
        response = await self.request("GET", "/representatives")
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json(parse_float=Decimal)["items"]
        self.assertEqual({row["id"] for row in rows}, {field.context.representative_id for field in fixtures})
        self.assertEqual(rows, sorted(rows, key=lambda row: (not row["is_active"], row["full_name"].casefold(), row["id"])))
        found, cursor = [], None
        while True:
            page = await self.request("GET", "/representatives", params={"limit": 1, **({"cursor": cursor} if cursor else {})})
            self.assertEqual(page.status_code, 200, page.text)
            value = page.json(parse_float=Decimal)
            self.assertEqual(set(value), {"items", "next_cursor", "has_more"})
            self.assertEqual(len(value["items"]), 1)
            found.extend(value["items"])
            self.assertLessEqual(len(found), len(rows), "Cursor must advance without duplicate rows")
            if not value["has_more"]:
                self.assertIsNone(value["next_cursor"])
                break
            self.assertIsInstance(value["next_cursor"], str)
            self.assertNotEqual(value["next_cursor"], cursor)
            cursor = value["next_cursor"]
        self.assertEqual(found, rows)
        for active in (True, False):
            filtered = await self.request("GET", "/representatives", params={"active": str(active).lower()})
            self.assertEqual(filtered.status_code, 200, filtered.text)
            self.assertEqual(filtered.json(parse_float=Decimal)["items"], [row for row in rows if row["is_active"] == active])
        principal = await self.db.get(CompanyPrincipal, fixtures[0].context.principal_id)
        filtered = await self.request("GET", "/representatives", params={"search": principal.username})
        self.assertEqual(filtered.status_code, 200, filtered.text)
        self.assertEqual([row["id"] for row in filtered.json()["items"]], [fixtures[0].context.representative_id])
        for search in ("Aardvark", "0771234567"):
            filtered = await self.request("GET", "/representatives", params={"search": search, "active": "false"})
            self.assertEqual(filtered.status_code, 200, filtered.text)
            self.assertEqual([row["id"] for row in filtered.json()["items"]], [fixtures[-1].context.representative_id])
        for query in ({"limit": 0}, {"limit": 101}, {"search": "x"}, {"search": "x" * 101}, {"cursor": "x" * 513}, {"active": "not-a-boolean"}):
            with self.subTest(query=query):
                self.assertEqual((await self.request("GET", "/representatives", params=query)).status_code, 422)

    async def test_create_patch_lifecycle_and_reset_replay_without_duplicate_effects(self):
        from datetime import timedelta
        from sqlalchemy import func, select
        from domains.identity.models import CompanyPrincipal, FieldRepresentative
        from domains.auth_sessions.models import PrincipalRefreshToken
        from domains.identity.authentication import verify_existing_password
        from models import utc_now

        payload = body("create")
        payload.update(can_allow_debt=True, max_debt_limit="123456789.001")
        first = await self.request("POST", "/representatives", json=payload)
        replay = await self.request("POST", "/representatives", json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(replay.status_code, 201, replay.text)
        row = first.json(parse_float=Decimal)
        self.view(row)
        self.assertEqual(row, replay.json(parse_float=Decimal))
        self.assertEqual(Decimal(str(row["max_debt_limit"])), Decimal("123456789.001"))
        principal = await self.db.scalar(select(CompanyPrincipal).where(CompanyPrincipal.company_id == self.current.context.company_id, CompanyPrincipal.username == payload["username"]))
        self.assertTrue(await verify_existing_password(payload["password"], principal.password_hash))
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(FieldRepresentative).where(FieldRepresentative.company_id == principal.company_id, FieldRepresentative.principal_id == principal.id)), 1)
        conflict = await self.request("POST", "/representatives", json={**payload, "full_name": "Different command"})
        self.assertEqual(conflict.status_code, 409, conflict.text)
        path = f"/representatives/{row['id']}"
        edit = {**body("patch"), "full_name": "Changed name"}
        updated = await self.request("PATCH", path, json=edit)
        self.assertEqual(updated.status_code, 200, updated.text)
        changed = updated.json(parse_float=Decimal)
        self.assertEqual(changed, {**row, "full_name": "Changed name"})  # Omitted fields preserved.
        self.assertEqual((await self.request("PATCH", path, json=edit)).json(parse_float=Decimal), changed)
        conflict = await self.request("PATCH", f"/representatives/{self.fields[0].context.representative_id}", json=edit)
        self.assertEqual(conflict.status_code, 409, conflict.text)
        for forbidden in ({"password": "SyntheticRepresentative123"}, {"is_active": False},
                          {"company_id": self.companies[1].id}, {"principal_id": principal.id}, {"role": "Owner"},
                          {"max_debt_limit": "-0.001"}, {"max_debt_limit": "not-a-number"}):
            with self.subTest(forbidden=forbidden):
                rejected = await self.request("PATCH", path, json={**body("patch"), **forbidden})
                self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertEqual((await self.request("PATCH", path, json={"request_id": str(uuid4())})).status_code, 422)
        self.assertEqual((await self.request("GET", path)).json(parse_float=Decimal), changed)
        for operation, active in (("deactivate", False), ("reactivate", True)):
            command = body(operation)
            for _ in range(2):
                result = await self.request("POST", path + "/" + operation, json=command)
                self.assertGreaterEqual(result.status_code, 200, result.text)
                self.assertLess(result.status_code, 300, result.text)
                self.assertIs((await self.request("GET", path)).json()["is_active"], active)
        await self.db.refresh(principal)
        revision, old_hash = principal.auth_revision, principal.password_hash
        target_session = PrincipalRefreshToken(company_id=principal.company_id, principal_id=principal.id,
            channel="FIELD", token="contract-" + uuid4().hex, expires_at=utc_now() + timedelta(days=1), auth_revision=revision)
        other_session = PrincipalRefreshToken(company_id=principal.company_id, principal_id=self.current.context.principal_id,
            channel="DASHBOARD", token="contract-" + uuid4().hex, expires_at=utc_now() + timedelta(days=1), auth_revision=self.current.context.auth_revision)
        self.db.add_all([target_session, other_session])
        await self.db.commit()
        reset = body("reset")
        for _ in range(2):
            result = await self.request("POST", path + "/credentials/reset", json=reset)
            self.assertEqual(result.status_code, 204, result.text)
            self.assertEqual(result.content, b"")
            await self.db.refresh(principal)
            await self.db.refresh(target_session)
            await self.db.refresh(other_session)
            self.assertEqual(principal.auth_revision, revision + 1)
            self.assertNotEqual(principal.password_hash, old_hash)
            self.assertTrue(await verify_existing_password(reset["new_password"], principal.password_hash))
            self.assertTrue(target_session.is_revoked)
            self.assertFalse(other_session.is_revoked)
        result = await self.request("POST", path + "/credentials/reset", json={**reset, "new_password": "DifferentPassword123"})
        self.assertEqual(result.status_code, 409, result.text)


if __name__ == "__main__":
    unittest.main()
