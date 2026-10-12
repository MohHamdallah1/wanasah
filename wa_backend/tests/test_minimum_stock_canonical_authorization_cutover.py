from __future__ import annotations

import ast
import inspect
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from api import inventory_stock_policy as stock_policy
from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.authorization.capabilities import COMPANY_ONLY, PERMISSIONS


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "api" / "inventory_stock_policy.py"
MIGRATION_PATH = (
    ROOT
    / "alembic"
    / "versions"
    / "c8a41d9e6f20_inventory_minimum_stock_manage_permission.py"
)
CAPABILITY = "inventory.minimum_stock.manage"


class _ScalarDB:
    def __init__(self, value):
        self.scalar = AsyncMock(return_value=value)


class _NoDB:
    def __getattr__(self, name):
        raise AssertionError(f"Unexpected DB operation: {name}")


class _PreviewAccess:
    def __init__(self, *, company_id=77, reject_visibility=False):
        self.company_id = company_id
        self.reject_visibility = reject_visibility
        self.calls = []

    async def require(self, code, location_id=None, *, any_location=False):
        self.calls.append((code, location_id, any_location))
        if self.reject_visibility:
            raise BackofficeCapabilityAccessRejected


class _MutationDB:
    def __init__(self):
        self.added = []
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    def add(self, value):
        self.added.append(value)


class _LegacyActor:
    def __init__(self, *, actor_id=903, legacy_admin_value=False):
        self.id = actor_id
        self._legacy_admin_value = legacy_admin_value

    @property
    def is_admin(self):
        raise AssertionError("legacy is_admin must not participate in authority")

    @property
    def company_id(self):
        raise AssertionError("legacy company_id must not be business authority")


class MinimumStockCanonicalAuthorizationCutoverTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_gets_manage_through_canonical_owner_semantics(self):
        subject = BackofficeAuthorizationSubject(
            principal_id=101,
            backoffice_user_id=202,
            company_id=77,
            is_company_owner=True,
            legacy_grant_driver_id=None,
        )
        access = BackofficeCapabilityAccess(db=_NoDB(), subject=subject)

        result = await stock_policy._manage_minimum_stock(access=access)

        self.assertIs(result, access)
        self.assertEqual(access.company_id, 77)

    async def test_ordinary_backoffice_company_manage_grant_succeeds(self):
        subject = BackofficeAuthorizationSubject(
            principal_id=101,
            backoffice_user_id=202,
            company_id=77,
            is_company_owner=False,
            legacy_grant_driver_id=903,
        )
        db = _ScalarDB(True)
        access = BackofficeCapabilityAccess(db=db, subject=subject)

        result = await stock_policy._manage_minimum_stock(access=access)

        self.assertIs(result, access)
        statement = db.scalar.await_args.args[0]
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn(CAPABILITY, sql)

    async def test_ordinary_backoffice_without_manage_gets_403(self):
        subject = BackofficeAuthorizationSubject(
            principal_id=101,
            backoffice_user_id=202,
            company_id=77,
            is_company_owner=False,
            legacy_grant_driver_id=903,
        )
        access = BackofficeCapabilityAccess(db=_ScalarDB(False), subject=subject)

        with self.assertRaises(HTTPException) as caught:
            await stock_policy._manage_minimum_stock(access=access)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail, "Authorization denied.")

    async def test_inventory_read_alone_cannot_authorize_mutation(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        self.assertIn(
            '_manage_minimum_stock = require_backoffice_capability(\n    "inventory.minimum_stock.manage"\n)',
            source,
        )
        self.assertNotIn('require_backoffice_capability("inventory.read")', source)

    async def test_preview_requires_exact_selected_location_inventory_read(self):
        access = _PreviewAccess(reject_visibility=True)
        payload = stock_policy.BulkMinimumStockBase(
            location_id=55,
            scope="ALL",
            minimum_quantity="2",
        )

        with self.assertRaises(HTTPException) as caught:
            await stock_policy.preview_bulk_minimum_stock(
                payload=payload,
                db=_NoDB(),
                access=access,
            )

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(access.calls, [("inventory.read", 55, False)])

    async def test_preview_with_manage_and_visibility_preserves_structural_validation(self):
        access = _PreviewAccess(company_id=77)
        payload = stock_policy.BulkMinimumStockBase(
            location_id=55,
            scope="ALL",
            minimum_quantity="2",
        )
        plan = {
            "candidates": [],
            "updates": [],
            "entered_quantity": Decimal("2"),
            "matched_count": 0,
            "affected_count": 0,
            "skipped_existing_count": 0,
            "inactive_conflicts": [],
            "target_conflicts": [],
            "invalid_quantity": [],
        }
        db = object()

        with (
            patch.object(stock_policy, "_require_active_warehouse", AsyncMock()) as warehouse,
            patch.object(
                stock_policy,
                "_plan_bulk_minimum",
                AsyncMock(return_value=plan),
            ) as planner,
        ):
            response = await stock_policy.preview_bulk_minimum_stock(
                payload=payload,
                db=db,
                access=access,
            )

        self.assertEqual(response["location_id"], 55)
        warehouse.assert_awaited_once_with(db, company_id=77, location_id=55)
        self.assertEqual(planner.await_args.kwargs["company_id"], 77)
        self.assertEqual(access.calls, [("inventory.read", 55, False)])

    async def test_bulk_apply_legacy_admin_values_are_identical_attribution_only(self):
        payload = stock_policy.BulkMinimumStockApplyRequest(
            request_id=uuid4(),
            location_id=55,
            scope="ALL",
            minimum_quantity="2",
            apply_mode="OVERWRITE",
        )
        access = SimpleNamespace(company_id=77)
        plan = {
            "candidates": [object()],
            "updates": [
                {
                    "variant_id": 11,
                    "policy": SimpleNamespace(minimum_quantity=Decimal("1")),
                    "old_minimum": Decimal("1"),
                    "new_minimum": Decimal("2"),
                    "display_uom_id": 1,
                }
            ],
            "entered_quantity": Decimal("2"),
            "matched_count": 1,
            "affected_count": 1,
            "skipped_existing_count": 0,
            "inactive_conflicts": [],
            "target_conflicts": [],
            "invalid_quantity": [],
        }

        observations = []
        for legacy_value in (False, True):
            db = _MutationDB()
            begin = AsyncMock(return_value=(SimpleNamespace(), None))
            with (
                patch.object(
                    stock_policy,
                    "_require_active_warehouse",
                    AsyncMock(),
                ) as warehouse,
                patch.object(stock_policy, "begin_idempotent_operation", begin),
                patch.object(
                    stock_policy,
                    "_plan_bulk_minimum",
                    AsyncMock(return_value=plan),
                ),
                patch.object(stock_policy, "refresh_live_stock_keys", AsyncMock()),
                patch.object(
                    stock_policy,
                    "complete_idempotent_operation",
                    Mock(),
                ),
            ):
                response = await stock_policy.apply_bulk_minimum_stock(
                    payload=payload,
                    db=db,
                    access=access,
                    legacy_actor=_LegacyActor(legacy_admin_value=legacy_value),
                )

            self.assertTrue(response["changed"])
            self.assertEqual(warehouse.await_args.kwargs["company_id"], 77)
            self.assertEqual(begin.await_args.kwargs["company_id"], 77)
            self.assertEqual(begin.await_args.kwargs["actor_id"], 903)
            audit = next(
                value
                for value in db.added
                if value.__class__.__name__ == "SystemAuditLog"
            )
            observations.append((audit.company_id, audit.admin_id))
            db.commit.assert_awaited_once()

        self.assertEqual(observations, [(77, 903), (77, 903)])

    async def test_active_warehouse_rejects_missing_cross_company_or_invalid_shape(self):
        class Result:
            def scalar_one_or_none(self):
                return None

        db = SimpleNamespace(execute=AsyncMock(return_value=Result()))

        with self.assertRaises(HTTPException) as caught:
            await stock_policy._require_active_warehouse(
                db,
                company_id=77,
                location_id=55,
            )

        self.assertEqual(caught.exception.status_code, 404)
        statement = db.execute.await_args.args[0]
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("inventory_locations.company_id = 77", sql)
        self.assertIn("inventory_locations.id = 55", sql)
        self.assertIn("inventory_locations.location_type = 'WAREHOUSE'", sql)
        self.assertIn("inventory_locations.is_active IS true", sql)

    def test_source_has_zero_is_admin_zero_legacy_inventory_access_and_canonical_transport(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)

        self.assertNotIn(".is_admin", source)
        self.assertNotIn("InventoryAccess", source)
        self.assertNotIn("legacy_backoffice_transport", source)
        self.assertNotIn("get_current_driver", source)
        self.assertIn("require_backoffice_capability", source)
        self.assertIn("get_current_backoffice_legacy_driver", source)
        self.assertFalse(
            any(
                isinstance(node, ast.Attribute) and node.attr == "is_admin"
                for node in ast.walk(tree)
            )
        )

    def test_company_authority_and_legacy_actor_usage_are_separated(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")

        self.assertGreaterEqual(source.count("company_id = access.company_id"), 3)
        self.assertNotIn("legacy_actor.company_id", source)
        self.assertNotIn("legacy_actor.is_admin", source)
        self.assertEqual(source.count("legacy_actor.id"), 2)
        self.assertEqual(source.count("actor_id = int(legacy_actor.id)"), 2)
        self.assertIn("actor_id=actor_id", source)
        self.assertIn("admin_id=actor_id", source)

    def test_apply_and_single_use_canonical_operational_actor_dependency(self):
        for endpoint in (stock_policy.apply_bulk_minimum_stock, stock_policy.update_minimum_stock):
            actor_depends = inspect.signature(endpoint).parameters["legacy_actor"].default
            self.assertIs(actor_depends.dependency, get_current_backoffice_legacy_driver)
            self.assertTrue(actor_depends.use_cache)

        capability_depends = inspect.signature(stock_policy._manage_minimum_stock).parameters["access"].default
        self.assertIs(capability_depends.dependency, get_current_backoffice_capability_access)
        self.assertTrue(capability_depends.use_cache)

        self.assertNotIn("legacy_actor", inspect.signature(stock_policy.preview_bulk_minimum_stock).parameters)

    def test_lock_idempotency_projection_and_transaction_guards_remain(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")

        for expected in (
            "pg_advisory_xact_lock",
            ".with_for_update()",
            "begin_idempotent_operation",
            "complete_idempotent_operation",
            "refresh_live_stock_keys",
            "await db.commit()",
            "await db.rollback()",
        ):
            self.assertIn(expected, source)

    def test_capability_is_canonical_and_company_only(self):
        self.assertIn(CAPABILITY, PERMISSIONS)
        self.assertIn(CAPABILITY, COMPANY_ONLY)

    def test_permission_persistence_uses_existing_migration_convention_without_grant(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")

        self.assertIn('revision = "c8a41d9e6f20"', source)
        self.assertIn('down_revision = "b7e3f6a1c902"', source)
        self.assertIn("INSERT INTO permissions (code)", source)
        self.assertIn(CAPABILITY, source)
        self.assertIn("ON CONFLICT (code) DO NOTHING", source)
        self.assertNotIn("permissions (code, description)", source)
        self.assertNotIn("PERMISSION_DESCRIPTION", source)
        self.assertNotIn("INSERT INTO role_permissions", source)
        self.assertIn("def downgrade():", source)
        self.assertIn("Permission catalog rows are retained", source)
        self.assertIn("pass", source)
        self.assertNotIn("NOT EXISTS", source)
        self.assertNotIn("role_permissions", source)


if __name__ == "__main__":
    unittest.main()