"""Frozen Wave 1 wire contract and Wave 2 lifecycle/credential security contract.

Run from wa_backend: python -m unittest tests.test_representatives_architecture tests.test_representatives_contract -v

Router/response/dependency checks fail explicitly on the pre-implementation base.
Real SQL/HTTP tests opt in with WANASAH_REPRESENTATIVES_CONTRACT_DB_URL
(an already-migrated, disposable PostgreSQL DB named representatives_contract_*).
No schema creation/migration or installation happens here. Each test rolls back
its outer transaction, including router commits via SAVEPOINTs.
Representative Permission rows must already exist from the production migration;
this fixture deliberately never repairs a missing permission catalog.

Authentication is overridden with persisted canonical fixture contexts; actual
subject resolution, capability decisions, route validation, services and SQL run.
These tests do not certify JWT decoding, deployment RLS or concurrent lifecycle
safety; those belong to the respective foundation/implementation gates.
"""
from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
import os
from pathlib import Path
import sys
from types import SimpleNamespace
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
UNRESOLVED_RECON_STATES = ("DRAFT", "COUNTING", "PENDING_REVIEW", "RECOUNT_REQUIRED", "APPROVED")
LIFECYCLE_BLOCKERS = ("open_session", "active", "waiting", "postponed", "handshake", "unreconciled",
                      *UNRESOLVED_RECON_STATES)
SESSION_SECRET = "RepresentativesFieldSessionSyntheticKey123456789"


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


def not_found_contract(response):
    def stable(value):
        if isinstance(value, dict):
            return {key: stable(child) for key, child in value.items()
                    if key not in {"request_id", "correlation_id", "representative_id"}}
        return value
    return stable(response.json())


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
                if key[1].endswith(("/deactivate", "/reactivate")):
                    self.assertEqual(route.endpoint.__module__, "api.representatives.lifecycle")
                elif key[1].endswith("/credentials/reset"):
                    self.assertEqual(route.endpoint.__module__, "api.representatives.credentials")
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
        from sqlalchemy import select, text
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

        from models import Company, Permission
        from tests.canonical_actor_fixtures import seed_company_owner_fixture, seed_ordinary_backoffice_fixture, seed_field_fixture
        from database import get_db
        from api.authentication.dependencies import get_current_backoffice_context

        required = set(ROUTES.values())
        present = set((await self.db.scalars(
            select(Permission.code).where(Permission.code.in_(required))
        )).all())
        self.assertEqual(required - present, set(),
                         "Migrated contract DB is missing Representative Permission rows; apply the production Alembic catalog migration. The fixture will not insert them.")
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
        # HTTP rollback expires ORM objects. Keep fixture locators as primitives;
        # inspect database state afresh rather than implicitly lazy-loading IDs.
        self.driver_ids = {field.context.representative_id: field.driver.id for field in self.fields}
        self.companies = [SimpleNamespace(id=company.id) for company in self.companies]
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

    @asynccontextmanager
    async def case(self):
        """Isolate each blocker subcase even when a handler commits/rolls back."""
        await self.db.rollback()
        savepoint = await self.connection.begin_nested()
        try:
            yield
        finally:
            await self.db.rollback()
            await savepoint.rollback()
            self.db.expire_all()

    async def identity_state(self, field):
        from sqlalchemy import select
        from domains.identity.models import CompanyPrincipal, FieldRepresentative
        from domains.identity.migration.models import IdentityLegacyDriverMap
        from models import Driver

        context = field.context
        await self.tenant(context.company_id)
        predicates = {
            "principal": (CompanyPrincipal, CompanyPrincipal.id == context.principal_id),
            "profile": (FieldRepresentative, FieldRepresentative.id == context.representative_id),
            "map": (IdentityLegacyDriverMap, IdentityLegacyDriverMap.legacy_driver_id == self.driver_ids[context.representative_id]),
            "driver": (Driver, Driver.id == self.driver_ids[context.representative_id]),
        }
        state = {}
        for name, (model, locator) in predicates.items():
            row = (await self.db.execute(select(*model.__table__.columns).where(
                model.company_id == context.company_id, locator,
            ))).mappings().one()
            state[name] = dict(row)
        self.assertEqual(state["profile"]["principal_id"], state["principal"]["id"])
        self.assertEqual(state["map"]["field_principal_id"], state["principal"]["id"])
        self.assertEqual(state["map"]["field_representative_id"], state["profile"]["id"])
        self.assertEqual(state["map"]["legacy_driver_id"], state["driver"]["id"])
        self.assertEqual(len({state[name]["id"] for name in ("principal", "profile", "driver")}), 3)
        return state

    async def history_state(self, field):
        from sqlalchemy import select
        from models import WorkSession, DispatchRoute, StocktakeSession, InventoryTransferHeader

        await self.tenant(field.context.company_id)
        return {model.__tablename__: [dict(row) for row in (await self.db.execute(
            select(*model.__table__.columns).where(model.company_id == field.context.company_id).order_by(model.id)
        )).mappings().all()] for model in (WorkSession, DispatchRoute, StocktakeSession, InventoryTransferHeader)}

    async def mutation_counts(self):
        from sqlalchemy import func, select
        from models import SystemAuditLog, DomainAuditEvent, OperationIdempotency

        await self.tenant(self.current.context.company_id)
        return tuple([await self.db.scalar(select(func.count()).select_from(model).where(
            model.company_id == self.current.context.company_id,
        )) for model in (SystemAuditLog, DomainAuditEvent, OperationIdempotency)])

    async def seed_history(self, field, kind):
        """Use real FK/state vocabulary; keep F from masking E or G."""
        from models import WorkSession, DispatchRoute, StocktakeSession, InventoryTransferHeader, InventoryLocation, Vehicle, Zone, utc_now

        company = field.context.company_id
        driver = self.driver_ids[field.context.representative_id]
        await self.tenant(company)
        now = utc_now()
        session = WorkSession(company_id=company, driver_id=driver, start_time=now - timedelta(hours=3),
                              end_time=None if kind == "open_session" else now - timedelta(hours=2), is_settled=False)
        if kind not in {"open_session", "unreconciled"}:
            session.inventory_reconciled_at = now - timedelta(hours=1)
            session.inventory_reconciled_by = driver
        self.db.add(session)
        if kind in {"open_session", "unreconciled", "financial_pending"}:
            await self.db.commit()
            return
        vehicle = Vehicle(company_id=company, plate_number=uuid4().hex[:20])
        zone = Zone(company_id=company, name="Contract " + uuid4().hex)
        self.db.add_all([vehicle, zone]); await self.db.flush()
        source = InventoryLocation(company_id=company, code="SRC" + uuid4().hex, name="Contract source", location_type="WAREHOUSE")
        destination = InventoryLocation(company_id=company, code="V" + uuid4().hex, name="Contract vehicle", location_type="VEHICLE", vehicle_id=vehicle.id)
        self.db.add_all([source, destination]); await self.db.flush()
        self.db.add(DispatchRoute(company_id=company, zone_id=zone.id, driver_id=driver, vehicle_id=vehicle.id,
                                  work_session_id=session.id, source_location_id=source.id,
                                  status=kind if kind in {"active", "waiting", "postponed"} else "closed"))
        if kind in {"handshake", "unrelated_transit"}:
            transit = None
            if kind == "unrelated_transit":
                transit = InventoryLocation(company_id=company, code="T" + uuid4().hex, name="Contract transit", location_type="IN_TRANSIT")
                self.db.add(transit); await self.db.flush()
            self.db.add(InventoryTransferHeader(company_id=company, reference_number="RC-" + uuid4().hex,
                source_location_id=source.id, destination_location_id=destination.id,
                workflow_type="HANDSHAKE" if kind == "handshake" else "TRANSIT",
                status="PENDING" if kind == "handshake" else "IN_TRANSIT", transfer_purpose="ROUTE_LOAD",
                commercial_context={}, dispatched_by=driver, expected_receiver_id=driver if kind == "handshake" else None,
                work_session_id=session.id if kind == "handshake" else None,
                transit_location_id=transit.id if transit is not None else None))
        elif kind in UNRESOLVED_RECON_STATES:
            # A sealed WS is deliberately non-blocking by F. A surviving open
            # VEHICLE_RECON must independently fail closed even in this debt state.
            self.db.add(StocktakeSession(company_id=company, location_id=destination.id,
                reference_number="RC-" + uuid4().hex, stocktake_type="VEHICLE_RECON", status=kind,
                related_work_session_id=session.id, started_by=driver, created_at=now, snapshot_cutoff_at=now,
                approved_by=driver if kind == "APPROVED" else None, approved_at=now if kind == "APPROVED" else None,
                pending_recount_authorized_by=driver if kind == "RECOUNT_REQUIRED" else None,
                pending_recount_reason="Contract recount" if kind == "RECOUNT_REQUIRED" else None))
        await self.db.commit()

    async def sessions(self, field):
        from domains.auth_sessions.refresh_sessions import create_refresh_session
        from domains.auth_sessions.codec import issue_access_token

        context = field.context
        await self.tenant(context.company_id)
        target = [await create_refresh_session(self.db, context, secret=SESSION_SECRET) for _ in range(2)]
        owner = await create_refresh_session(self.db, self.owners[0].context, secret=SESSION_SECRET)
        foreign = self.fields[1]
        await self.tenant(foreign.context.company_id)
        other = await create_refresh_session(self.db, foreign.context, secret=SESSION_SECRET)
        await self.db.commit()
        access = issue_access_token(principal_id=context.principal_id, company_id=context.company_id,
            channel="FIELD", principal_type="FIELD_REPRESENTATIVE", auth_revision=context.auth_revision, secret=SESSION_SECRET)
        return target, (owner, other), access

    async def assert_sessions_revoked(self, field, evidence):
        from sqlalchemy import select
        from domains.auth_sessions.models import PrincipalRefreshToken
        from domains.auth_sessions.refresh_sessions import rotate_refresh_session, RefreshSessionRejected
        from domains.auth_sessions.codec import decode_company_token
        from domains.auth_sessions.context import resolve_access_context, RequestContextRejected

        targets, others, access = evidence
        for session, revoked in [(item, True) for item in targets] + [(item, False) for item in others]:
            await self.tenant(session.company_id)
            row = (await self.db.execute(select(PrincipalRefreshToken.is_revoked).where(
                PrincipalRefreshToken.company_id == session.company_id, PrincipalRefreshToken.token == session.refresh_token,
            ))).scalar_one()
            self.assertIs(row, revoked)
        await self.tenant(field.context.company_id)
        with self.assertRaises(RefreshSessionRejected):
            await rotate_refresh_session(self.db, targets[0].refresh_token, secret=SESSION_SECRET)
        claims = decode_company_token(access, secret=SESSION_SECRET, expected_type="access")
        self.assertEqual(claims.principal_id, field.context.principal_id)
        with self.assertRaises(RequestContextRejected):
            await resolve_access_context(self.db, claims)

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
        self.assertEqual(len({field.context.principal_id, field.context.representative_id,
                              self.driver_ids[field.context.representative_id]}), 3)
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
        foreign_username = principal.username
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
                self.assertEqual(not_found_contract(response), not_found_contract(missing))
                self.assertNotIn(foreign_username, response.text)
        self.current = self.owners[1]
        self.assertEqual(await self.detail(self.fields[1]), own_detail, "Denied requests must not mutate the foreign representative")

    async def test_exact_company_capabilities_and_legacy_persona_flags_have_no_authority(self):
        from domains.identity.models import CompanyPrincipal
        from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
        from types import SimpleNamespace

        principal = await self.db.get(CompanyPrincipal, self.fields[0].context.principal_id)
        username = principal.username  # Denial rollbacks expire the ORM instance.
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
        self.assertEqual(representative_record(response.json(), username)["id"], self.fields[0].context.representative_id)
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

    async def test_create_patch_replay_without_duplicate_effects(self):
        from sqlalchemy import func, select
        from domains.identity.models import CompanyPrincipal, FieldRepresentative
        from domains.identity.authentication import verify_existing_password

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
        principal_id = principal.id
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
                          {"company_id": self.companies[1].id}, {"principal_id": principal_id}, {"role": "Owner"},
                          {"max_debt_limit": "-0.001"}, {"max_debt_limit": "not-a-number"}):
            with self.subTest(forbidden=forbidden):
                rejected = await self.request("PATCH", path, json={**body("patch"), **forbidden})
                self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertEqual((await self.request("PATCH", path, json={"request_id": str(uuid4())})).status_code, 422)
        self.assertEqual((await self.request("GET", path)).json(parse_float=Decimal), changed)

    async def test_deactivation_blocker_matrix_and_foreign_company_rows(self):
        field, foreign = self.fields
        for kind in LIFECYCLE_BLOCKERS:
            with self.subTest(blocker=kind, company="own"):
                async with self.case():
                    before = await self.identity_state(field)
                    await self.seed_history(field, kind)
                    history = await self.history_state(field)
                    response = await self.request("POST", f"/representatives/{field.context.representative_id}/deactivate", json=body("deactivate"))
                    self.assertTrue(400 <= response.status_code < 500, response.text)
                    self.assertNotIn(response.status_code, (401, 403, 404), "Valid authorized target must reach the business blocker")
                    self.assertTrue(any(isinstance(node.get("code"), str) for node in objects(response.json())),
                                    "A business blocker must expose a stable code, not a transport-validation failure")
                    self.assertEqual(await self.identity_state(field), before)
                    self.assertEqual(await self.history_state(field), history)
            with self.subTest(blocker=kind, company="foreign"):
                async with self.case():
                    await self.seed_history(foreign, kind)
                    before = await self.identity_state(foreign)
                    history = await self.history_state(foreign)
                    command = body("deactivate")
                    denied = await self.request("POST", f"/representatives/{foreign.context.representative_id}/deactivate", json=command)
                    missing = await self.request("POST", "/representatives/2147483647/deactivate", json=command)
                    self.assertEqual(denied.status_code, 404, denied.text)
                    self.assertEqual(missing.status_code, 404, missing.text)
                    self.assertEqual(not_found_contract(denied), not_found_contract(missing))
                    allowed = await self.request("POST", f"/representatives/{field.context.representative_id}/deactivate", json=body("deactivate"))
                    self.assertTrue(200 <= allowed.status_code < 300, allowed.text)
                    self.assertEqual(await self.identity_state(foreign), before)
                    self.assertEqual(await self.history_state(foreign), history)
        # Financial settlement is separate from inventory closure. Non-handshake
        # transit is likewise not a receiver-specific PENDING HANDSHAKE blocker.
        for kind in ("financial_pending", "unrelated_transit", "other_handshake_receiver"):
            with self.subTest(safe=kind):
                async with self.case():
                    if kind == "other_handshake_receiver":
                        from tests.canonical_actor_fixtures import seed_field_fixture
                        await self.tenant(field.context.company_id)
                        other = await seed_field_fixture(self.db, field.context.company_id)
                        self.driver_ids[other.context.representative_id] = other.driver.id
                        await self.seed_history(other, "handshake")
                    else:
                        await self.seed_history(field, kind)
                    history = await self.history_state(field)
                    response = await self.request("POST", f"/representatives/{field.context.representative_id}/deactivate", json=body("deactivate"))
                    self.assertTrue(200 <= response.status_code < 300, response.text)
                    self.assertEqual(await self.history_state(field), history)

    async def test_deactivate_epoch_and_reactivate_preserve_operational_identity_and_history(self):
        field = self.fields[0]
        await self.seed_history(field, "history")
        before = await self.identity_state(field)
        history = await self.history_state(field)
        evidence = await self.sessions(field)
        path = f"/representatives/{field.context.representative_id}"
        command = body("deactivate")
        first = await self.request("POST", path + "/deactivate", json=command)
        self.assertTrue(200 <= first.status_code < 300, first.text)
        inactive = await self.identity_state(field)
        self.assertIs(inactive["principal"]["is_active"], False)
        self.assertEqual(inactive["principal"]["auth_revision"], before["principal"]["auth_revision"] + 1)
        self.assertEqual(inactive["principal"]["password_hash"], before["principal"]["password_hash"])
        for name in ("driver", "map"):
            self.assertEqual(inactive[name], before[name])
        self.assertEqual(inactive["profile"]["id"], before["profile"]["id"])
        self.assertEqual(await self.history_state(field), history)
        await self.assert_sessions_revoked(field, evidence)
        counts = await self.mutation_counts()
        replay = await self.request("POST", path + "/deactivate", json=command)
        self.assertEqual(replay.status_code, first.status_code, replay.text)
        self.assertEqual(await self.identity_state(field), inactive)
        self.assertEqual(await self.mutation_counts(), counts, "Replay must not duplicate audit/idempotency mutations")
        reactivate = body("reactivate")
        reactivated, reactivation_counts = None, None
        for _ in range(2):
            response = await self.request("POST", path + "/reactivate", json=reactivate)
            self.assertTrue(200 <= response.status_code < 300, response.text)
            active = await self.identity_state(field)
            self.assertIs(active["principal"]["is_active"], True)
            self.assertEqual(active["principal"]["auth_revision"], inactive["principal"]["auth_revision"])
            for name in ("driver", "map"):
                self.assertEqual(active[name], before[name])
            for name in ("principal", "profile"):
                self.assertEqual(active[name]["id"], before[name]["id"])
            self.assertEqual(await self.history_state(field), history)
            await self.assert_sessions_revoked(field, evidence)
            if reactivated is None:
                reactivated, reactivation_counts = active, await self.mutation_counts()
            else:
                self.assertEqual(active, reactivated)
                self.assertEqual(await self.mutation_counts(), reactivation_counts)

    async def test_reset_replay_hashes_and_writes_once_and_invalidates_canonical_sessions(self):
        import re
        from sqlalchemy import event
        from domains.identity import credentials as identity_credentials
        from domains.identity.authentication import verify_existing_password

        field = self.fields[0]
        before = await self.identity_state(field)
        evidence = await self.sessions(field)
        path = f"/representatives/{field.context.representative_id}/credentials/reset"
        reset = body("reset")
        writes = []
        def record(_connection, _cursor, statement, _parameters, _context, _many):
            if re.search(r'\b(?:UPDATE|INSERT\s+INTO|DELETE\s+FROM)\s+(?:"?\w+"?\.)?"?company_principals"?(?=\s|\()', statement, re.I):
                writes.append(statement)
        event.listen(self.connection.sync_connection, "before_cursor_execute", record)
        try:
            with patch.object(identity_credentials.bcrypt, "hashpw", wraps=identity_credentials.bcrypt.hashpw) as hasher:
                first = await self.request("POST", path, json=reset)
                self.assertEqual(first.status_code, 204, first.text)
                self.assertEqual(first.content, b"")
                changed = await self.identity_state(field)
                self.assertIs(changed["principal"]["is_active"], True)
                self.assertEqual(changed["principal"]["auth_revision"], before["principal"]["auth_revision"] + 1)
                self.assertNotEqual(changed["principal"]["password_hash"], before["principal"]["password_hash"])
                self.assertTrue(await verify_existing_password(reset["new_password"], changed["principal"]["password_hash"]))
                self.assertEqual(changed["driver"], before["driver"], "Reset must not mutate the operational Driver password/hash/state")
                self.assertEqual(changed["map"], before["map"])
                self.assertEqual(hasher.call_count, 1)
                self.assertTrue(writes, "Observe the actual canonical credential write")
                count, mutations = len(writes), await self.mutation_counts()
                replay = await self.request("POST", path, json=reset)
                self.assertEqual(replay.status_code, 204, replay.text)
                self.assertEqual(replay.content, b"")
                self.assertEqual(hasher.call_count, 1, "Replay must not hash again")
                self.assertEqual(len(writes), count, "Replay must not write credentials again")
                self.assertEqual(await self.identity_state(field), changed)
                self.assertEqual(await self.mutation_counts(), mutations)
                conflict = await self.request("POST", path, json={**reset, "new_password": "DifferentPassword123"})
                self.assertEqual(conflict.status_code, 409, conflict.text)
                self.assertEqual(hasher.call_count, 1)
                self.assertEqual(len(writes), count)
                self.assertEqual(await self.identity_state(field), changed)
        finally:
            event.remove(self.connection.sync_connection, "before_cursor_execute", record)
        # Principal remains active: access rejection now specifically follows the
        # auth_revision mismatch, not a deactivation or a legacy Driver flag.
        await self.assert_sessions_revoked(field, evidence)

    async def test_wave2_strict_bodies_and_utf8_reset_password_boundary(self):
        from domains.identity.authentication import verify_existing_password

        field = self.fields[0]
        path = f"/representatives/{field.context.representative_id}"
        before = await self.identity_state(field)
        for operation in ("deactivate", "reactivate", "reset"):
            suffix = "/credentials/reset" if operation == "reset" else "/" + operation
            for changes in ({"request_id": "not-a-uuid"}, {"company_id": self.companies[1].id}, {"password": "UnapprovedPassword123"}):
                with self.subTest(operation=operation, invalid=tuple(changes)):
                    response = await self.request("POST", path + suffix, json={**body(operation), **changes})
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertEqual(await self.identity_state(field), before)
        for password in ("a" * 7, "م" * 7, "a" * 73, "م" * 37, "😀" * 19):
            with self.subTest(characters=len(password), utf8_bytes=len(password.encode("utf-8"))):
                response = await self.request("POST", path + "/credentials/reset", json={**body("reset"), "new_password": password})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(await self.identity_state(field), before)
        for password in ("abcd1234", "م" * 36, "😀" * 18):
            with self.subTest(valid_utf8_bytes=len(password.encode("utf-8"))):
                response = await self.request("POST", path + "/credentials/reset", json={**body("reset"), "new_password": password})
                self.assertEqual(response.status_code, 204, response.text)
                self.assertEqual(response.content, b"")
                changed = await self.identity_state(field)
                self.assertEqual(changed["driver"], before["driver"])
                self.assertEqual(changed["principal"]["auth_revision"], before["principal"]["auth_revision"] + 1)
                self.assertTrue(await verify_existing_password(password, changed["principal"]["password_hash"]))
                before = changed


if __name__ == "__main__":
    unittest.main()
