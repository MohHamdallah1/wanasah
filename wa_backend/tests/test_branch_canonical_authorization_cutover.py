from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from api import branches
from api.authentication.legacy_backoffice_transport import (
    get_legacy_transport_backoffice_capability_access,
)
from api.dependencies import get_current_driver
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.authorization.capabilities import COMPANY_ONLY, PERMISSIONS


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
SOURCE_PATH = ROOT / "api" / "branches.py"
MIGRATION_PATH = (
    ROOT / "alembic" / "versions" / "d3b7e1a4c920_branch_permissions.py"
)
BRANCH_CAPABILITIES = (
    "branch.read",
    "branch.create",
    "branch.update",
    "branch.state",
)


class _ScalarDB:
    def __init__(self, value):
        self.scalar = AsyncMock(return_value=value)


class _NoDB:
    def __getattr__(self, name):
        raise AssertionError(f"Owner authorization unexpectedly touched DB: {name}")


class _LegacyActor:
    def __init__(self, *, actor_id=903, legacy_admin_value=False):
        self.id = actor_id
        self._legacy_admin_value = legacy_admin_value

    @property
    def is_admin(self):
        raise AssertionError("legacy is_admin must not participate in authority")

    @property
    def company_id(self):
        raise AssertionError("legacy company_id must not be authorization authority")


class _TransportDriver:
    def __init__(self, *, company_id=77, driver_id=903):
        self.company_id = company_id
        self.id = driver_id

    @property
    def is_admin(self):
        raise AssertionError("transport Driver.is_admin must never be read")


class _TransportDB:
    def __init__(self, *rows):
        self.scalar = AsyncMock(side_effect=rows)


def _bridge():
    return SimpleNamespace(
        company_id=77,
        legacy_driver_id=903,
        backoffice_principal_id=101,
        backoffice_user_id=202,
    )


def _principal():
    return SimpleNamespace(
        company_id=77,
        id=101,
        principal_type="BACKOFFICE",
        is_active=True,
        auth_revision=4,
    )


def _profile():
    return SimpleNamespace(
        company_id=77,
        id=202,
        principal_id=101,
        principal_type="BACKOFFICE",
    )


def _owner():
    return SimpleNamespace(company_id=77, backoffice_user_id=202)


def _ordinary_subject() -> BackofficeAuthorizationSubject:
    return BackofficeAuthorizationSubject(
        principal_id=101,
        backoffice_user_id=202,
        company_id=77,
        is_company_owner=False,
        legacy_grant_driver_id=903,
    )


def _owner_subject() -> BackofficeAuthorizationSubject:
    return BackofficeAuthorizationSubject(
        principal_id=101,
        backoffice_user_id=202,
        company_id=77,
        is_company_owner=True,
        legacy_grant_driver_id=None,
    )


class BranchCanonicalAuthorizationCutoverTests(unittest.IsolatedAsyncioTestCase):
    def test_architecture_constitution_freezes_canonical_identity_and_is_admin_prohibition(self):
        architecture = (REPO_ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
        rules = (REPO_ROOT / ".rules").read_text(encoding="utf-8")
        agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

        for source in (architecture, rules, agents):
            self.assertIn("CompanyPrincipal", source)
            self.assertIn("BACKOFFICE", source)
            self.assertIn("FIELD_REPRESENTATIVE", source)
            self.assertIn("BackofficeUser", source)
            self.assertIn("FieldRepresentative", source)
            self.assertIn("CompanyOwner", source)
            self.assertIn("Driver.is_admin", source)
            self.assertIn("is_superuser", source)
            self.assertIn("is_manager", source)
            self.assertIn("is_owner", source)
            self.assertIn("capability", source.lower())
            self.assertIn("scope", source.lower())

        self.assertIn("Permanent prohibition on generic admin-flag authority", architecture)
        self.assertIn("zero Runtime authority or classification dependence", architecture)
        self.assertIn("automated source/architecture CI gate", architecture)
        self.assertIn("temporary adapters must not grow new business semantics", rules)
        self.assertIn("Temporary compatibility adapters must not acquire new business semantics", agents)

    def test_branch_capabilities_are_canonical_and_company_only(self):
        for code in BRANCH_CAPABILITIES:
            self.assertIn(code, PERMISSIONS)
            self.assertIn(code, COMPANY_ONLY)

    def test_permission_migration_persists_exact_catalog_codes_without_grants(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")

        self.assertIn('revision = "d3b7e1a4c920"', source)
        self.assertIn('down_revision = "c8a41d9e6f20"', source)
        self.assertIn("INSERT INTO permissions (code) VALUES", source)
        self.assertIn("ON CONFLICT (code) DO NOTHING", source)
        for code in BRANCH_CAPABILITIES:
            self.assertEqual(source.count(f"('{code}')"), 1)
        self.assertNotIn("description", source.lower())
        self.assertNotIn("INSERT INTO role_permissions", source)
        self.assertIn("def downgrade()", source)
        self.assertIn("Permission catalog rows are retained", source)
        self.assertIn("pass", source)

    def test_route_dependency_mapping_matches_frozen_branch_contract(self):
        expected = {
            branches.list_branch_options: branches._branch_read,
            branches.manage_branches: branches._branch_read,
            branches.create_branch: branches._branch_create,
            branches.update_branch: branches._branch_update,
            branches.activate_branch: branches._branch_state,
            branches.deactivate_branch: branches._branch_state,
        }
        for endpoint, dependency in expected.items():
            with self.subTest(endpoint=endpoint.__name__):
                access_depends = inspect.signature(endpoint).parameters["access"].default
                self.assertIs(access_depends.dependency, dependency)
                self.assertTrue(access_depends.use_cache)

    async def test_ordinary_backoffice_with_exact_company_capability_succeeds(self):
        access = BackofficeCapabilityAccess(
            db=_ScalarDB(True),
            subject=_ordinary_subject(),
        )

        result = await branches._branch_create(access=access)

        self.assertIs(result, access)
        statement = access.db.scalar.await_args.args[0]
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("branch.create", sql)
        self.assertIn("user_roles", sql)

    async def test_missing_branch_capability_maps_to_opaque_403(self):
        access = BackofficeCapabilityAccess(
            db=_ScalarDB(False),
            subject=_ordinary_subject(),
        )

        with self.assertRaises(HTTPException) as caught:
            await branches._branch_update(access=access)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail, "Authorization denied.")
        self.assertNotIn("branch.update", str(caught.exception.detail))
        self.assertNotIn("903", str(caught.exception.detail))

    async def test_owner_succeeds_through_canonical_owner_semantics(self):
        access = BackofficeCapabilityAccess(db=_NoDB(), subject=_owner_subject())

        for dependency in (
            branches._branch_read,
            branches._branch_create,
            branches._branch_update,
            branches._branch_state,
        ):
            with self.subTest(dependency=dependency):
                result = await dependency(access=access)
                self.assertIs(result, access)

    async def test_branch_reads_use_canonical_access_company_id(self):
        access = SimpleNamespace(company_id=77)
        db = object()
        page = {"items": [], "next_cursor": None, "has_more": False, "total": 0}

        with patch.object(branches, "_list_branches", AsyncMock(return_value=page)) as listing:
            result = await branches.list_branch_options(
                search=None,
                cursor=None,
                limit=50,
                db=db,
                access=access,
            )

        self.assertEqual(result, page)
        listing.assert_awaited_once_with(
            db,
            company_id=77,
            search=None,
            include_inactive=False,
            cursor=None,
            limit=50,
            mode="options",
        )

    async def test_legacy_admin_flag_has_zero_effect_on_state_attribution(self):
        access = SimpleNamespace(company_id=77)
        payload = object()
        db = object()
        results = []

        for legacy_value in (False, True):
            actor = _LegacyActor(actor_id=903, legacy_admin_value=legacy_value)
            with patch.object(
                branches,
                "_change_branch_state",
                AsyncMock(return_value={"ok": True}),
            ) as change:
                result = await branches.activate_branch(
                    branch_id=55,
                    payload=payload,
                    db=db,
                    access=access,
                    legacy_actor=actor,
                )
            results.append(result)
            change.assert_awaited_once_with(
                branch_id=55,
                payload=payload,
                activate=True,
                db=db,
                company_id=77,
                actor_id=903,
            )

        self.assertEqual(results, [{"ok": True}, {"ok": True}])

    def test_source_has_zero_legacy_branch_authority(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)

        self.assertNotIn("get_current_admin", source)
        self.assertNotIn("InventoryAccess", source)
        self.assertNotIn(".is_admin", source)
        self.assertNotIn("legacy_actor.company_id", source)
        self.assertNotIn("legacy_actor.is_admin", source)
        self.assertNotIn("current_driver.company_id", source)
        self.assertNotIn('"location.create"', source)
        self.assertNotIn('"location.update"', source)
        self.assertFalse(
            any(
                isinstance(node, ast.Attribute) and node.attr == "is_admin"
                for node in ast.walk(tree)
            )
        )

    def test_company_authority_and_legacy_attribution_are_separated(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")

        self.assertGreaterEqual(source.count("access.company_id"), 6)
        self.assertEqual(source.count("legacy_actor.id"), 4)
        self.assertEqual(source.count("actor_id=actor_id"), 3)
        self.assertGreaterEqual(source.count("admin_id=actor_id"), 3)
        self.assertNotIn("legacy_actor.company_id", source)
        self.assertNotIn("legacy_actor.is_admin", source)

    def test_existing_cursor_lock_idempotency_audit_and_transaction_behavior_remains(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")

        for expected in (
            "_encode_cursor",
            "_decode_cursor",
            ".limit(limit + 1)",
            ".with_for_update()",
            "begin_idempotent_operation",
            "complete_idempotent_operation",
            "SystemAuditLog",
            "BRANCH_CREATE",
            "BRANCH_UPDATE",
            "BRANCH_ACTIVATE",
            "BRANCH_DEACTIVATE",
            "await db.commit()",
            "await db.rollback()",
            "Branch.company_id == company_id",
            "Branch.branch_code == payload.code",
        ):
            self.assertIn(expected, source)

    def test_fastapi_caches_shared_legacy_transport_authentication_once(self):
        app = FastAPI()
        calls = {"driver": 0}
        driver = _TransportDriver()
        db = _TransportDB(_bridge(), _principal(), _profile(), _owner())

        async def counted_driver():
            calls["driver"] += 1
            return driver

        async def fake_db():
            yield db

        @app.get("/probe")
        async def probe(
            access: BackofficeCapabilityAccess = Depends(branches._branch_create),
            legacy_actor=Depends(get_current_driver),
        ):
            return {
                "company_id": access.company_id,
                "actor_id": legacy_actor.id,
            }

        app.dependency_overrides[get_current_driver] = counted_driver
        app.dependency_overrides[get_db] = fake_db

        response = TestClient(app).get("/probe")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"company_id": 77, "actor_id": 903})
        self.assertEqual(calls["driver"], 1)

        access_depends = inspect.signature(
            branches._branch_create
        ).parameters["access"].default
        self.assertIs(
            access_depends.dependency,
            get_legacy_transport_backoffice_capability_access,
        )
        self.assertTrue(access_depends.use_cache)


if __name__ == "__main__":
    unittest.main()
