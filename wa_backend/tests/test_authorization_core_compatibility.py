from __future__ import annotations

from pathlib import Path
import re
import unittest

from fastapi import HTTPException
from sqlalchemy import select

import domains.authorization as authorization
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.authorization.capabilities import COMPANY_ONLY, PERMISSIONS
from domains.authorization.guards import (
    require_inbound_adjustment,
    require_stocktake,
    require_transfer,
    transfer_filter,
)
from models import InventoryTransferHeader


ROOT = Path(__file__).resolve().parents[1]
AUTH_ROOT = ROOT / "domains" / "authorization"


class _Result:
    def __init__(self, row):
        self._row = row

    def one_or_none(self):
        return self._row


class _GuardDb:
    def __init__(self, *, scalar=None, execute=None):
        self.scalar_results = list(scalar or [])
        self.execute_results = list(execute or [])
        self.scalar_statements = []
        self.execute_statements = []

    async def scalar(self, statement):
        self.scalar_statements.append(statement)
        if not self.scalar_results:
            raise AssertionError("unexpected scalar() call")
        return self.scalar_results.pop(0)

    async def execute(self, statement):
        self.execute_statements.append(statement)
        if not self.execute_results:
            raise AssertionError("unexpected execute() call")
        return _Result(self.execute_results.pop(0))


def _subject(*, owner: bool = False, locator: int | None = 903):
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


def _active_runtime_python_files():
    excluded_parts = {
        "tests",
        "scripts",
        "perf_reports",
        "alembic",
        "migrations",
        "__pycache__",
    }
    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT)
        if any(part in excluded_parts for part in relative.parts):
            continue
        # Historical root compatibility facade is outside this branch's OWN
        # surface and has no live runtime importer. Its callers are audited
        # separately below; active request/runtime code must not depend on it.
        if relative.as_posix() == "inventory_access.py":
            continue
        yield path


class AuthorizationCoreRetirementTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_driver_authorization_surface_is_retired(self):
        self.assertFalse((AUTH_ROOT / "subject.py").exists())
        self.assertFalse((AUTH_ROOT / "inventory_access.py").exists())

        for name in (
            "AuthorizationSubject",
            "InventoryAccess",
            "LegacyDriverAuthorizationSource",
            "inventory_actor",
            "subject_from_legacy_driver",
        ):
            self.assertFalse(hasattr(authorization, name), name)

        init_source = (AUTH_ROOT / "__init__.py").read_text(encoding="utf-8")
        guards_source = (AUTH_ROOT / "guards.py").read_text(encoding="utf-8")
        for forbidden in (
            "InventoryAccess",
            "AuthorizationSubject",
            "LegacyDriverAuthorizationSource",
            "inventory_actor",
            "subject_from_legacy_driver",
            "legacy_full_authority",
            ".is_admin",
        ):
            self.assertNotIn(forbidden, init_source)
            self.assertNotIn(forbidden, guards_source)

    async def test_no_active_runtime_importer_or_legacy_driver_authority_remains(self):
        retired_names = (
            "InventoryAccess",
            "AuthorizationSubject",
            "LegacyDriverAuthorizationSource",
            "inventory_actor",
            "subject_from_legacy_driver",
        )
        exact_patterns = {
            name: re.compile(rf"\b{re.escape(name)}\b")
            for name in retired_names
        }
        forbidden_authority = (
            "actor.is_admin",
            "legacy_full_authority",
            "subject_from_legacy_driver",
        )

        offenders = []
        for path in _active_runtime_python_files():
            source = path.read_text(encoding="utf-8-sig")
            relative = path.relative_to(ROOT).as_posix()
            for name, pattern in exact_patterns.items():
                if pattern.search(source):
                    offenders.append(f"{relative}: {name}")
            for needle in forbidden_authority:
                if needle in source:
                    offenders.append(f"{relative}: {needle}")

        self.assertEqual(offenders, [])

        facade_importers = []
        import_pattern = re.compile(
            r"(?:^|\n)\s*(?:from\s+inventory_access\s+import|import\s+inventory_access\b)"
        )
        for path in _active_runtime_python_files():
            source = path.read_text(encoding="utf-8-sig")
            if import_pattern.search(source):
                facade_importers.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(facade_importers, [])

    async def test_no_generic_replacement_admin_boolean_exists_in_authorization_domain(self):
        offenders = []
        for path in AUTH_ROOT.glob("*.py"):
            source = path.read_text(encoding="utf-8-sig")
            for needle in (
                "is_admin",
                "admin_override",
                "full_authority",
            ):
                if re.search(rf"\b{needle}\b", source):
                    offenders.append(f"{path.name}: {needle}")
        self.assertEqual(offenders, [])

    async def test_retained_transfer_guard_accepts_canonical_access_and_preserves_scope(self):
        db = _GuardDb(scalar=[11, True], execute=[(11, 12)])
        access = BackofficeCapabilityAccess(db, _subject())

        await require_transfer(access, "transfer.send", 501, side="source")

        header_sql, header_params = _compiled(db.execute_statements[0])
        location_sql, location_params = _compiled(db.scalar_statements[0])
        grant_sql, grant_params = _compiled(db.scalar_statements[1])
        self.assertIn("inventory_transfer_headers.company_id", header_sql)
        self.assertIn(77, header_params.values())
        self.assertIn(501, header_params.values())
        self.assertIn("inventory_locations.company_id", location_sql)
        self.assertIn(77, location_params.values())
        self.assertIn(11, location_params.values())
        self.assertIn("user_roles", grant_sql)
        self.assertIn("user_location_access", grant_sql)
        self.assertIn(903, grant_params.values())
        self.assertIn(11, grant_params.values())

    async def test_transfer_guard_preserves_404_before_capability_check(self):
        db = _GuardDb(execute=[None])
        access = BackofficeCapabilityAccess(db, _subject())

        with self.assertRaises(HTTPException) as caught:
            await require_transfer(access, "transfer.read", 404)
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(db.scalar_statements, [])

    async def test_stocktake_and_inbound_guards_preserve_404_before_require(self):
        stocktake_db = _GuardDb(scalar=[None])
        stocktake_access = BackofficeCapabilityAccess(stocktake_db, _subject())
        with self.assertRaises(HTTPException) as stocktake_error:
            await require_stocktake(stocktake_access, "stocktake.count", 41)
        self.assertEqual(stocktake_error.exception.status_code, 404)
        self.assertEqual(len(stocktake_db.scalar_statements), 1)

        inbound_db = _GuardDb(scalar=[None])
        inbound_access = BackofficeCapabilityAccess(inbound_db, _subject())
        with self.assertRaises(HTTPException) as inbound_error:
            await require_inbound_adjustment(inbound_access, 51)
        self.assertEqual(inbound_error.exception.status_code, 404)
        self.assertEqual(len(inbound_db.scalar_statements), 1)

    async def test_transfer_filter_remains_pre_pagination_and_exact_side_scoped(self):
        access = BackofficeCapabilityAccess(_GuardDb(), _subject())
        statement = select(InventoryTransferHeader.id).where(
            InventoryTransferHeader.company_id == access.company_id,
            transfer_filter(access, "transfer.read"),
        )
        sql, params = _compiled(statement)
        self.assertIn("inventory_transfer_headers.company_id", sql)
        self.assertIn("inventory_transfer_headers.source_location_id", sql)
        self.assertIn("inventory_transfer_headers.destination_location_id", sql)
        self.assertIn("user_roles", sql)
        self.assertIn("user_location_access", sql)
        self.assertIn(77, params.values())
        self.assertIn(903, params.values())

    async def test_company_owner_authority_is_only_canonical_owner_state(self):
        owner = BackofficeCapabilityAccess(None, _subject(owner=True, locator=None))
        self.assertEqual(await owner.codes(), sorted(PERMISSIONS))
        await owner.require_all(("inventory.read", "catalog.manage"))

        ordinary = BackofficeCapabilityAccess(_GuardDb(scalar=[False]), _subject())
        with self.assertRaises(BackofficeCapabilityAccessRejected):
            await ordinary.require("inventory.read")

    async def test_capability_catalog_keeps_location_scoped_terminal_permissions(self):
        self.assertIn("inventory.disposal.confirm", PERMISSIONS)
        self.assertIn("inventory.vendor_return.confirm", PERMISSIONS)
        self.assertNotIn("inventory.disposal.confirm", COMPANY_ONLY)
        self.assertNotIn("inventory.vendor_return.confirm", COMPANY_ONLY)
        self.assertFalse(any(code.startswith("admin.") for code in PERMISSIONS))


if __name__ == "__main__":
    unittest.main()
