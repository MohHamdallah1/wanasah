from __future__ import annotations

from pathlib import Path
import unittest

from sqlalchemy import select

from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.authorization.capabilities import COMPANY_ONLY, PERMISSIONS
from models import InventoryLocation


ROOT = Path(__file__).resolve().parents[1]


class _ScalarRows:
    def __init__(self, values):
        self._values = list(values)

    def all(self):
        return list(self._values)


class _Rows:
    def __init__(self, values):
        self._values = list(values)

    def all(self):
        return list(self._values)


class FakeSession:
    def __init__(self, *, scalar=None, scalars=None, execute=None):
        self.scalar_results = list(scalar or [])
        self.scalars_results = list(scalars or [])
        self.execute_results = list(execute or [])
        self.scalar_statements = []
        self.scalars_statements = []
        self.execute_statements = []

    async def scalar(self, statement):
        self.scalar_statements.append(statement)
        if not self.scalar_results:
            raise AssertionError("unexpected scalar() call")
        return self.scalar_results.pop(0)

    async def scalars(self, statement):
        self.scalars_statements.append(statement)
        if not self.scalars_results:
            raise AssertionError("unexpected scalars() call")
        return _ScalarRows(self.scalars_results.pop(0))

    async def execute(self, statement):
        self.execute_statements.append(statement)
        if not self.execute_results:
            raise AssertionError("unexpected execute() call")
        return _Rows(self.execute_results.pop(0))


def _subject(*, owner=False, locator=903):
    return BackofficeAuthorizationSubject(
        principal_id=101,
        backoffice_user_id=202,
        company_id=77,
        is_company_owner=owner,
        legacy_grant_driver_id=locator,
    )


def _compiled(statement):
    compiled = statement.compile()
    return str(compiled), compiled.params


class CanonicalBackofficeCapabilityAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_full_capability_set(self):
        access = BackofficeCapabilityAccess(None, _subject(owner=True, locator=None))
        self.assertEqual(await access.codes(), sorted(PERMISSIONS))
        self.assertEqual(str(access.allows(PERMISSIONS)).lower(), "true")
        await access.require_all(PERMISSIONS)

    async def test_owner_requires_no_grant_lookup(self):
        class NoDB:
            def __getattr__(self, name):
                raise AssertionError(f"Owner authority unexpectedly touched DB: {name}")

        access = BackofficeCapabilityAccess(NoDB(), _subject(owner=True, locator=None))
        await access.require("inventory.read")
        await access.require_all(("inventory.read", "catalog.read"))
        self.assertEqual(await access.codes(), sorted(PERMISSIONS))
        self.assertEqual(str(access.allows("dispatch.execute")).lower(), "true")

    async def test_ordinary_company_wide_grant(self):
        db = FakeSession(scalar=[True])
        access = BackofficeCapabilityAccess(db, _subject())
        await access.require("inventory.read")

        sql, params = _compiled(db.scalar_statements[0])
        self.assertIn("user_roles", sql)
        self.assertNotIn("user_location_access", sql)
        self.assertIn(903, params.values())
        self.assertIn(77, params.values())

    async def test_exact_location_grant(self):
        db = FakeSession(scalar=[11, True])
        access = BackofficeCapabilityAccess(db, _subject())
        await access.require("transfer.send", location_id=11)

        location_sql, location_params = _compiled(db.scalar_statements[0])
        grant_sql, grant_params = _compiled(db.scalar_statements[1])
        self.assertIn("inventory_locations", location_sql)
        self.assertIn(77, location_params.values())
        self.assertIn(11, location_params.values())
        self.assertIn("user_roles", grant_sql)
        self.assertIn("user_location_access", grant_sql)
        self.assertIn(903, grant_params.values())
        self.assertIn(11, grant_params.values())

    async def test_company_only_excluded_from_location_grant(self):
        access = BackofficeCapabilityAccess(FakeSession(), _subject())
        sql, params = _compiled(access.allows("catalog.manage", location_id=11))
        self.assertIn("user_location_access", sql)
        self.assertIn("permissions.code NOT IN", sql)
        flattened = []
        for value in params.values():
            if isinstance(value, (list, tuple, set, frozenset)):
                flattened.extend(value)
        self.assertTrue(COMPANY_ONLY <= set(flattened))

    async def test_foreign_location_rejected(self):
        db = FakeSession(scalar=[None])
        access = BackofficeCapabilityAccess(db, _subject())
        with self.assertRaises(BackofficeCapabilityAccessRejected):
            await access.require("inventory.read", location_id=44)
        self.assertEqual(len(db.scalar_statements), 1)

    async def test_missing_grant_rejected(self):
        db = FakeSession(scalar=[False])
        access = BackofficeCapabilityAccess(db, _subject())
        with self.assertRaises(BackofficeCapabilityAccessRejected):
            await access.require("inventory.read")

    async def test_require_all_preserves_all_semantics(self):
        db = FakeSession(scalar=[True, False])
        access = BackofficeCapabilityAccess(db, _subject())
        with self.assertRaises(BackofficeCapabilityAccessRejected):
            await access.require_all(
                ("inventory.read", "catalog.read"),
                any_location=True,
            )
        self.assertEqual(len(db.scalar_statements), 2)

    async def test_codes_returns_bounded_canonical_codes_only(self):
        db = FakeSession(scalars=[["catalog.read", "inventory.read"]])
        access = BackofficeCapabilityAccess(db, _subject())
        self.assertEqual(
            await access.codes(any_location=True),
            ["catalog.read", "inventory.read"],
        )

        sql, params = _compiled(db.scalars_statements[0])
        self.assertIn("permissions.code IN", sql)
        flattened = []
        for value in params.values():
            if isinstance(value, (list, tuple, set, frozenset)):
                flattened.extend(value)
        self.assertTrue(PERMISSIONS <= set(flattened))
        self.assertIn(903, params.values())

    async def test_codes_by_location_preserves_exact_location_scope(self):
        db = FakeSession(
            scalars=[
                [11, 12],
                ["inventory.read"],
            ],
            execute=[
                [(11, "transfer.send"), (12, "transfer.receive")],
            ],
        )
        access = BackofficeCapabilityAccess(db, _subject())
        result = await access.codes_by_location([12, 11, 999])

        self.assertEqual(
            result,
            {
                11: ["inventory.read", "transfer.send"],
                12: ["inventory.read", "transfer.receive"],
            },
        )
        visible_sql, visible_params = _compiled(db.scalars_statements[0])
        local_sql, local_params = _compiled(db.execute_statements[0])
        self.assertIn("inventory_locations", visible_sql)
        self.assertIn("user_location_access", visible_sql)
        self.assertIn("user_location_access.location_id IN", local_sql)
        self.assertIn(903, visible_params.values())
        self.assertIn(903, local_params.values())
        flattened = []
        for value in local_params.values():
            if isinstance(value, (list, tuple, set, frozenset)):
                flattened.extend(value)
        self.assertTrue((PERMISSIONS - COMPANY_ONLY) <= set(flattened))

    async def test_malformed_or_missing_legacy_locator_rejected(self):
        for locator in (None, 0, -1, True, "903"):
            with self.subTest(locator=locator):
                access = BackofficeCapabilityAccess(FakeSession(), _subject(locator=locator))
                with self.assertRaises(BackofficeCapabilityAccessRejected):
                    access.allows("inventory.read")

    async def test_unknown_permission_rejected_before_authority_shortcuts(self):
        owner = BackofficeCapabilityAccess(None, _subject(owner=True, locator=None))
        with self.assertRaises(ValueError):
            owner.allows("admin.anything")
        with self.assertRaises(ValueError):
            await owner.require_all(("inventory.read", "admin.anything"))

    async def test_ids_remain_independent(self):
        access = BackofficeCapabilityAccess(FakeSession(), _subject())
        sql, params = _compiled(access.allows("inventory.read"))
        values = list(params.values())
        self.assertIn(903, values)
        self.assertNotIn(101, values)
        self.assertNotIn(202, values)
        self.assertIn("user_roles.driver_id", sql)

    async def test_owner_codes_by_location_uses_tenant_locations_not_grants(self):
        db = FakeSession(scalars=[[11, 12]])
        access = BackofficeCapabilityAccess(db, _subject(owner=True, locator=None))
        result = await access.codes_by_location([11, 12, 999])
        self.assertEqual(set(result), {11, 12})
        self.assertEqual(result[11], sorted(PERMISSIONS))
        sql, params = _compiled(db.scalars_statements[0])
        self.assertIn("inventory_locations", sql)
        self.assertNotIn("user_roles", sql)
        self.assertNotIn("user_location_access", sql)
        self.assertIn(77, params.values())

    async def test_no_driver_is_admin_or_legacy_full_authority_dependency(self):
        source = (
            ROOT / "domains" / "authorization" / "backoffice_access.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("from models import Driver", source)
        self.assertNotIn(".is_admin", source)
        self.assertNotIn("legacy_full_authority", source)
        self.assertNotIn("subject.principal_id ==", source)
        self.assertNotIn("subject.backoffice_user_id ==", source)

    async def test_sql_predicate_remains_composable_before_pagination(self):
        access = BackofficeCapabilityAccess(FakeSession(), _subject())
        statement = select(InventoryLocation.id).where(
            InventoryLocation.company_id == 77,
            access.allows("inventory.read", location_id=InventoryLocation.id),
        )
        sql, _ = _compiled(statement)
        self.assertIn("inventory_locations", sql)
        self.assertIn("user_roles", sql)
        self.assertIn("user_location_access", sql)


if __name__ == "__main__":
    unittest.main()
