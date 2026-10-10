from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace

from domains.authorization.capabilities import COMPANY_ONLY, PERMISSIONS
from domains.authorization.dashboard_admission import (
    DashboardAdmissionRejected,
    require_dashboard_admission,
)
import domains.authorization.dashboard_admission as admission_module
from domains.identity.contracts import DashboardAuthenticationResult


class FakeSession:
    def __init__(
        self,
        *,
        bridge=None,
        company_capability: str | None = None,
        location_capability: str | None = None,
    ):
        self.bridge = bridge
        self.company_capability = company_capability
        self.location_capability = location_capability
        self.statements = []

    @staticmethod
    def _collection_params(statement) -> list[set[str]]:
        compiled = statement.compile()
        result = []
        for value in compiled.params.values():
            if isinstance(value, (set, frozenset, list, tuple)):
                result.append(set(value))
        return result

    async def scalar(self, statement):
        self.statements.append(statement)
        sql = str(statement)
        if "identity_legacy_driver_map" in sql:
            return self.bridge
        if "user_roles" in sql:
            collections = self._collection_params(statement)
            allowed = next((items for items in collections if items == set(PERMISSIONS)), set())
            return self.company_capability in allowed
        if "user_location_access" in sql:
            collections = self._collection_params(statement)
            allowed = next((items for items in collections if items == set(PERMISSIONS)), set())
            excluded = next((items for items in collections if items == set(COMPANY_ONLY)), set())
            return (
                self.location_capability in allowed
                and self.location_capability not in excluded
            )
        raise AssertionError(f"Unexpected SQL: {sql}")


def dashboard_identity(*, owner: bool = False) -> DashboardAuthenticationResult:
    return DashboardAuthenticationResult(
        principal_id=101,
        company_id=77,
        backoffice_user_id=202,
        username="backoffice-user",
        full_name="Backoffice User",
        auth_revision=5,
        is_company_owner=owner,
    )


def bridge(**overrides):
    values = {
        "company_id": 77,
        "legacy_driver_id": 903,
        "classification": "BACKOFFICE_ONLY",
        "backoffice_principal_id": 101,
        "backoffice_user_id": 202,
        "legacy_is_admin": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class DashboardAdmissionBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_admitted_without_grant_lookup(self):
        db = FakeSession()
        identity = dashboard_identity(owner=True)

        result = await require_dashboard_admission(db, identity)

        self.assertIs(result, identity)
        self.assertEqual(db.statements, [])

    async def test_ordinary_backoffice_with_company_role_admitted(self):
        db = FakeSession(
            bridge=bridge(),
            company_capability="inventory.read",
        )
        identity = dashboard_identity()

        result = await require_dashboard_admission(db, identity)

        self.assertIs(result, identity)
        sql = [str(stmt) for stmt in db.statements]
        self.assertTrue(any("user_roles" in item for item in sql))
        self.assertFalse(any("user_location_access" in item for item in sql))

    async def test_ordinary_backoffice_with_valid_location_grant_admitted(self):
        db = FakeSession(
            bridge=bridge(),
            location_capability="transfer.send",
        )
        identity = dashboard_identity()

        result = await require_dashboard_admission(db, identity)

        self.assertIs(result, identity)
        sql = [str(stmt) for stmt in db.statements]
        self.assertTrue(any("user_roles" in item for item in sql))
        self.assertTrue(any("user_location_access" in item for item in sql))

    async def test_no_grants_rejected(self):
        db = FakeSession(bridge=bridge())

        with self.assertRaises(DashboardAdmissionRejected):
            await require_dashboard_admission(db, dashboard_identity())

    async def test_missing_bridge_rejected(self):
        db = FakeSession(bridge=None, company_capability="inventory.read")

        with self.assertRaises(DashboardAdmissionRejected):
            await require_dashboard_admission(db, dashboard_identity())

        self.assertEqual(len(db.statements), 1)

    async def test_cross_company_mapping_rejected(self):
        db = FakeSession(
            bridge=bridge(company_id=88),
            company_capability="inventory.read",
        )

        with self.assertRaises(DashboardAdmissionRejected):
            await require_dashboard_admission(db, dashboard_identity())

        self.assertEqual(len(db.statements), 1)

    async def test_location_company_only_capability_does_not_widen_admission(self):
        capability = next(iter(COMPANY_ONLY))
        db = FakeSession(
            bridge=bridge(),
            location_capability=capability,
        )

        with self.assertRaises(DashboardAdmissionRejected):
            await require_dashboard_admission(db, dashboard_identity())

        location_statement = next(
            stmt for stmt in db.statements if "user_location_access" in str(stmt)
        )
        collections = FakeSession._collection_params(location_statement)
        self.assertIn(set(PERMISSIONS), collections)
        self.assertIn(set(COMPANY_ONLY), collections)

    async def test_compatibility_is_admin_cannot_influence_result(self):
        identity = dashboard_identity()
        for value in (False, True):
            db = FakeSession(
                bridge=bridge(legacy_is_admin=value),
                company_capability="inventory.read",
            )
            result = await require_dashboard_admission(db, identity)
            self.assertIs(result, identity)

        source = inspect.getsource(admission_module)
        self.assertNotIn("is_admin", source)

    async def test_no_driver_dependency(self):
        source = inspect.getsource(admission_module)
        self.assertNotIn("from models import Driver", source)
        self.assertNotIn("models.Driver", source)

    async def test_principal_and_profile_ids_are_never_driver_aliases(self):
        db = FakeSession(
            bridge=bridge(legacy_driver_id=903),
            company_capability="inventory.read",
        )
        identity = dashboard_identity()

        await require_dashboard_admission(db, identity)

        company_grant_statement = next(
            stmt for stmt in db.statements if "user_roles" in str(stmt)
        )
        params = company_grant_statement.compile().params
        scalar_values = {
            value
            for value in params.values()
            if isinstance(value, int) and not isinstance(value, bool)
        }
        self.assertIn(903, scalar_values)
        self.assertNotIn(identity.principal_id, scalar_values)
        self.assertNotIn(identity.backoffice_user_id, scalar_values)

    async def test_bridge_principal_mismatch_rejected(self):
        db = FakeSession(
            bridge=bridge(backoffice_principal_id=999),
            company_capability="inventory.read",
        )

        with self.assertRaises(DashboardAdmissionRejected):
            await require_dashboard_admission(db, dashboard_identity())

        self.assertEqual(len(db.statements), 1)


if __name__ == "__main__":
    unittest.main()
