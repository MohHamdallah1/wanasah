from __future__ import annotations

import ast
import inspect
import unittest
from types import SimpleNamespace

from domains.auth_sessions.context import DashboardRequestContext, FieldRequestContext
from domains.authorization.backoffice_subject import (
    BackofficeAuthorizationSubjectRejected,
    resolve_backoffice_authorization_subject,
)


class FakeDB:
    def __init__(self, bridge=None, *, fail_on_scalar: bool = False):
        self.bridge = bridge
        self.fail_on_scalar = fail_on_scalar
        self.scalar_calls = 0
        self.statements = []

    async def scalar(self, statement):
        self.scalar_calls += 1
        self.statements.append(statement)
        if self.fail_on_scalar:
            raise AssertionError("bridge lookup must not occur")
        return self.bridge


def dashboard_context(
    *,
    principal_id: int = 101,
    company_id: int = 7,
    backoffice_user_id: int = 301,
    is_company_owner: bool = False,
):
    return DashboardRequestContext(
        principal_id=principal_id,
        company_id=company_id,
        backoffice_user_id=backoffice_user_id,
        auth_revision=3,
        is_company_owner=is_company_owner,
    )


def bridge(
    *,
    company_id: int = 7,
    principal_id: int = 101,
    backoffice_user_id: int = 301,
    legacy_driver_id: int = 9001,
):
    return SimpleNamespace(
        company_id=company_id,
        backoffice_principal_id=principal_id,
        backoffice_user_id=backoffice_user_id,
        legacy_driver_id=legacy_driver_id,
        classification="DUAL_SPLIT",
    )


class CanonicalBackofficeAuthorizationSubjectTests(unittest.IsolatedAsyncioTestCase):
    async def test_canonical_owner_subject(self):
        db = FakeDB(fail_on_scalar=True)
        result = await resolve_backoffice_authorization_subject(
            db,
            dashboard_context(is_company_owner=True),
        )
        self.assertEqual(result.principal_id, 101)
        self.assertEqual(result.backoffice_user_id, 301)
        self.assertEqual(result.company_id, 7)
        self.assertTrue(result.is_company_owner)
        self.assertIsNone(result.legacy_grant_driver_id)

    async def test_owner_works_without_bridge_authority(self):
        db = FakeDB(None, fail_on_scalar=True)
        result = await resolve_backoffice_authorization_subject(
            db,
            dashboard_context(is_company_owner=True),
        )
        self.assertTrue(result.is_company_owner)
        self.assertEqual(db.scalar_calls, 0)

    async def test_ordinary_backoffice_exact_bridge_success(self):
        db = FakeDB(bridge())
        result = await resolve_backoffice_authorization_subject(db, dashboard_context())
        self.assertFalse(result.is_company_owner)
        self.assertEqual(result.legacy_grant_driver_id, 9001)
        self.assertEqual(db.scalar_calls, 1)

    async def test_missing_bridge_rejected(self):
        with self.assertRaises(BackofficeAuthorizationSubjectRejected):
            await resolve_backoffice_authorization_subject(FakeDB(None), dashboard_context())

    async def test_cross_company_rejected(self):
        with self.assertRaises(BackofficeAuthorizationSubjectRejected):
            await resolve_backoffice_authorization_subject(
                FakeDB(bridge(company_id=8)),
                dashboard_context(company_id=7),
            )

    async def test_principal_mismatch_rejected(self):
        with self.assertRaises(BackofficeAuthorizationSubjectRejected):
            await resolve_backoffice_authorization_subject(
                FakeDB(bridge(principal_id=999)),
                dashboard_context(principal_id=101),
            )

    async def test_profile_mismatch_rejected(self):
        with self.assertRaises(BackofficeAuthorizationSubjectRejected):
            await resolve_backoffice_authorization_subject(
                FakeDB(bridge(backoffice_user_id=777)),
                dashboard_context(backoffice_user_id=301),
            )

    async def test_ids_remain_independent(self):
        result = await resolve_backoffice_authorization_subject(
            FakeDB(bridge(principal_id=11, backoffice_user_id=22, legacy_driver_id=33)),
            dashboard_context(principal_id=11, backoffice_user_id=22),
        )
        self.assertEqual(
            (result.principal_id, result.backoffice_user_id, result.legacy_grant_driver_id),
            (11, 22, 33),
        )

    async def test_wrong_context_type_rejected(self):
        field = FieldRequestContext(
            principal_id=101,
            company_id=7,
            representative_id=401,
            auth_revision=3,
        )
        with self.assertRaises(BackofficeAuthorizationSubjectRejected):
            await resolve_backoffice_authorization_subject(FakeDB(bridge()), field)  # type: ignore[arg-type]

    async def test_invalid_context_ids_rejected(self):
        for bad in (0, -1, True):
            with self.subTest(bad=bad):
                with self.assertRaises(BackofficeAuthorizationSubjectRejected):
                    await resolve_backoffice_authorization_subject(
                        FakeDB(bridge()),
                        dashboard_context(principal_id=bad),  # type: ignore[arg-type]
                    )

    async def test_malformed_legacy_driver_id_rejected(self):
        for bad in (0, -1, True, "9001"):
            with self.subTest(bad=bad):
                with self.assertRaises(BackofficeAuthorizationSubjectRejected):
                    await resolve_backoffice_authorization_subject(
                        FakeDB(bridge(legacy_driver_id=bad)),  # type: ignore[arg-type]
                        dashboard_context(),
                    )

    def test_no_driver_dependency_or_is_admin_authority(self):
        import domains.authorization.backoffice_subject as module

        tree = ast.parse(inspect.getsource(module))
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        loaded_names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        attributes = {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }

        self.assertNotIn("Driver", imported_names)
        self.assertNotIn("Driver", loaded_names)
        self.assertNotIn("is_admin", attributes)
        self.assertNotIn("classification", attributes)


if __name__ == "__main__":
    unittest.main()
