from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
)
from api.authentication.backoffice_compatibility import (
    get_current_backoffice_legacy_driver,
)
from api.warehouse import stocktake
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "api" / "warehouse" / "stocktake.py"


class _ScalarSession:
    def __init__(self, values):
        self.values = list(values)
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        if not self.values:
            raise AssertionError("unexpected scalar call")
        return self.values.pop(0)


def _subject(*, owner=False, locator=903):
    return BackofficeAuthorizationSubject(
        principal_id=101,
        backoffice_user_id=202,
        company_id=77,
        is_company_owner=owner,
        legacy_grant_driver_id=locator,
    )


def _dependency(function, parameter):
    default = inspect.signature(function).parameters[parameter].default
    return default.dependency, default.use_cache


class _ExecuteResult:
    def __init__(self, row):
        self.row = row

    def scalar_one_or_none(self):
        return self.row


class _SecondaryCredentialDB:
    def __init__(self, execute_rows, scalar_rows=()):
        self.execute_rows = list(execute_rows)
        self.scalar_rows = list(scalar_rows)
        self.execute_statements = []
        self.scalar_statements = []

    async def execute(self, statement):
        self.execute_statements.append(statement)
        if not self.execute_rows:
            raise AssertionError("unexpected execute call")
        return _ExecuteResult(self.execute_rows.pop(0))

    async def scalar(self, statement):
        self.scalar_statements.append(statement)
        if not self.scalar_rows:
            raise AssertionError("unexpected scalar call")
        return self.scalar_rows.pop(0)


class StocktakeCanonicalAuthCutoverTests(unittest.IsolatedAsyncioTestCase):
    def test_source_has_zero_legacy_request_authority(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("get_current_driver", source)
        self.assertNotIn("InventoryAccess", source)
        self.assertNotIn("current_admin", source)
        self.assertNotIn(".is_admin", source)
        self.assertNotIn("legacy_actor.company_id", source)
        self.assertNotIn("principal_id == legacy_actor.id", source)
        self.assertNotIn("principal_id == Driver.id", source)
        self.assertIn("get_current_backoffice_capability_access", source)
        self.assertIn("get_current_backoffice_legacy_driver", source)

    def test_all_routes_use_canonical_backoffice_access(self):
        endpoints = (
            stocktake.list_stocktake_cycle_batches,
            stocktake.list_vehicle_recon_candidates,
            stocktake.list_active_stocktake_sessions,
            stocktake.get_stocktake_session_context,
            stocktake.start_unified_stocktake,
            stocktake.get_stocktake_count_sheet,
            stocktake.submit_stocktake_count,
            stocktake.get_stocktake_review,
            stocktake.approve_stocktake_session,
            stocktake.recount_stocktake_session,
            stocktake.cancel_stocktake_session,
        )
        for endpoint in endpoints:
            dependency, use_cache = _dependency(endpoint, "access")
            self.assertIs(dependency, get_current_backoffice_capability_access)
            self.assertTrue(use_cache)

    def test_only_genuine_operational_routes_load_legacy_actor(self):
        actor_endpoints = (
            stocktake.start_unified_stocktake,
            stocktake.get_stocktake_count_sheet,
            stocktake.submit_stocktake_count,
            stocktake.approve_stocktake_session,
            stocktake.recount_stocktake_session,
            stocktake.cancel_stocktake_session,
        )
        read_only_without_actor = (
            stocktake.list_stocktake_cycle_batches,
            stocktake.list_vehicle_recon_candidates,
            stocktake.list_active_stocktake_sessions,
            stocktake.get_stocktake_session_context,
            stocktake.get_stocktake_review,
        )
        for endpoint in actor_endpoints:
            dependency, use_cache = _dependency(endpoint, "legacy_actor")
            self.assertIs(dependency, get_current_backoffice_legacy_driver)
            self.assertTrue(use_cache)
        for endpoint in read_only_without_actor:
            self.assertNotIn("legacy_actor", inspect.signature(endpoint).parameters)

    def test_exact_capability_mapping_is_preserved(self):
        expected = {
            stocktake.list_stocktake_cycle_batches: "stocktake.start",
            stocktake.list_vehicle_recon_candidates: "stocktake.start",
            stocktake.list_active_stocktake_sessions: "stocktake.read",
            stocktake.get_stocktake_session_context: "stocktake.read",
            stocktake.start_unified_stocktake: "stocktake.start",
            stocktake.get_stocktake_count_sheet: "stocktake.count",
            stocktake.submit_stocktake_count: "stocktake.count",
            stocktake.get_stocktake_review: "stocktake.review",
            stocktake.approve_stocktake_session: "stocktake.approve",
            stocktake.recount_stocktake_session: "stocktake.recount",
            stocktake.cancel_stocktake_session: "stocktake.cancel",
        }
        for endpoint, code in expected.items():
            body = inspect.getsource(endpoint)
            self.assertIn(code, body, msg=endpoint.__name__)
        vehicle_body = inspect.getsource(stocktake.list_vehicle_recon_candidates)
        self.assertIn("location.read", vehicle_body)
        self.assertIn("location_filter('stocktake.start')", vehicle_body)

    async def test_owner_and_ordinary_exact_location_authority(self):
        owner_db = _ScalarSession([11])
        owner_access = BackofficeCapabilityAccess(
            owner_db, _subject(owner=True, locator=None)
        )
        await stocktake._require_location_capability(owner_access, "stocktake.review", 11)
        self.assertEqual(len(owner_db.statements), 1)

        ordinary_db = _ScalarSession([11, True])
        ordinary_access = BackofficeCapabilityAccess(ordinary_db, _subject())
        await stocktake._require_location_capability(
            ordinary_access, "stocktake.review", 11
        )
        self.assertEqual(len(ordinary_db.statements), 2)

    async def test_missing_capability_and_wrong_location_fail_closed(self):
        missing = BackofficeCapabilityAccess(_ScalarSession([11, False]), _subject())
        with self.assertRaises(HTTPException) as caught:
            await stocktake._require_location_capability(
                missing, "stocktake.review", 11
            )
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail, "Authorization denied.")

        foreign = BackofficeCapabilityAccess(_ScalarSession([None]), _subject())
        with self.assertRaises(HTTPException) as caught:
            await stocktake._require_location_capability(
                foreign, "stocktake.cancel", 999
            )
        self.assertEqual(caught.exception.status_code, 403)

    def test_review_and_cancel_use_capabilities_not_admin_persona(self):
        review = inspect.getsource(stocktake.get_stocktake_review)
        cancel = inspect.getsource(stocktake.cancel_stocktake_session)
        self.assertIn("'stocktake.review'", review)
        self.assertIn("'stocktake.cancel'", cancel)
        self.assertNotIn("is_admin", review)
        self.assertNotIn("is_admin", cancel)

    def test_legacy_actor_is_only_operational_attribution_or_credentials(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("legacy_actor.company_id", source)
        self.assertNotIn("legacy_actor.is_admin", source)
        self.assertIn("started_by=legacy_actor.id", source)
        self.assertIn("counted_by=legacy_actor.id", source)
        self.assertIn("session.approved_by = legacy_actor.id", source)
        self.assertIn("cancelled_by = legacy_actor.id", source)
        self.assertIn("admin_id=legacy_actor.id", source)
        self.assertIn("legacy_actor.password_hash", source)
        self.assertIn("company_id = access.company_id", source)

    async def test_secondary_credentials_resolve_independent_canonical_identity_and_recount(self):
        legacy = SimpleNamespace(
            id=903,
            company_id=77,
            username="supervisor",
            password_hash="hash",
            is_active=True,
            is_admin=False,
        )
        bridge = SimpleNamespace(
            company_id=77,
            legacy_driver_id=903,
            backoffice_principal_id=101,
            backoffice_user_id=202,
        )
        principal = SimpleNamespace(
            id=101,
            company_id=77,
            principal_type="BACKOFFICE",
            is_active=True,
            auth_revision=4,
        )
        profile = SimpleNamespace(
            id=202,
            company_id=77,
            principal_id=101,
            principal_type="BACKOFFICE",
        )
        owner = None
        db = _SecondaryCredentialDB(
            [legacy, bridge, principal, profile, owner],
            scalar_rows=[11, True],
        )
        subject = _subject(owner=False, locator=903)
        with patch.object(stocktake.bcrypt, "checkpw", return_value=True), patch.object(
            stocktake,
            "resolve_backoffice_authorization_subject",
            new=AsyncMock(return_value=subject),
        ) as resolver:
            resolved = await stocktake._verify_stocktake_admin_credentials(
                db, 77, "supervisor", "pw", 11
            )
        self.assertIs(resolved, legacy)
        self.assertEqual({101, 202, 903}, {principal.id, profile.id, legacy.id})
        context = resolver.await_args.args[1]
        self.assertEqual(context.principal_id, 101)
        self.assertEqual(context.backoffice_user_id, 202)
        self.assertEqual(context.company_id, 77)
        self.assertFalse(context.is_company_owner)
        self.assertEqual(len(db.scalar_statements), 2)

    async def test_secondary_credentials_fail_closed_on_cross_company_mapping(self):
        legacy = SimpleNamespace(
            id=903,
            company_id=77,
            password_hash="hash",
            is_active=True,
        )
        bridge = SimpleNamespace(
            company_id=88,
            legacy_driver_id=903,
            backoffice_principal_id=101,
            backoffice_user_id=202,
        )
        db = _SecondaryCredentialDB([legacy, bridge])
        with patch.object(stocktake.bcrypt, "checkpw", return_value=True):
            resolved = await stocktake._verify_stocktake_admin_credentials(
                db, 77, "supervisor", "pw", 11
            )
        self.assertIsNone(resolved)
        self.assertEqual(len(db.execute_statements), 2)

    def test_secondary_credential_source_has_no_legacy_authority_shortcut(self):
        source = inspect.getsource(stocktake._verify_stocktake_admin_credentials)
        self.assertIn("IdentityLegacyDriverMap", source)
        self.assertIn("CompanyPrincipal", source)
        self.assertIn("BackofficeUser", source)
        self.assertIn("CompanyOwner", source)
        self.assertIn("DashboardRequestContext", source)
        self.assertIn("resolve_backoffice_authorization_subject", source)
        self.assertIn("BackofficeCapabilityAccess", source)
        self.assertIn("'stocktake.recount'", source)
        self.assertNotIn("is_admin", source)
        self.assertNotIn("classification", source)
        self.assertNotIn("principal_id ==", source)

    def test_locks_state_machine_posting_cursors_and_transactions_remain(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        for marker in (
            "acquire_inventory_location_guard(",
            ".with_for_update()",
            "post_approved_stocktake_adjustments(",
            "validate_vehicle_recon_work_session(",
            "requires_independent_recount",
            "pending_recount_authorized_by",
            "SystemAuditLog(",
            "await db.commit()",
            "await db.rollback()",
            "_encode_stocktake_cursor(",
            "_decode_stocktake_cursor(",
            "_encode_stocktake_cycle_batch_cursor(",
            "_decode_stocktake_cycle_batch_cursor(",
        ):
            self.assertIn(marker, source)
        self.assertGreaterEqual(source.count(".with_for_update()"), 4)


if __name__ == "__main__":
    unittest.main()
