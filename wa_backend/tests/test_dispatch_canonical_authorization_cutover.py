from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

from api import dispatch
from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
)
from api.authentication.backoffice_compatibility import (
    get_current_backoffice_legacy_driver,
)
from api.authentication.dependencies import get_current_backoffice_context
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.authorization.capabilities import COMPANY_ONLY, PERMISSIONS
import dispatch_access


REPO_ROOT = Path(__file__).resolve().parents[2]
DISPATCH_PATH = REPO_ROOT / "wa_backend" / "api" / "dispatch.py"
DISPATCH_ACCESS_PATH = REPO_ROOT / "wa_backend" / "dispatch_access.py"
MIGRATION_PATH = (
    REPO_ROOT
    / "wa_backend"
    / "alembic"
    / "versions"
    / "e4c8a1d6b203_dispatch_auth_permissions.py"
)

COMPANY_CAPABILITIES = {
    "work_session.read",
    "work_session.authorize_sale",
    "work_session.reopen",
    "settlement.read",
    "settlement.execute",
    "shortage.read",
    "shortage.create",
    "shortage.cancel",
    "visit.read",
}
LOCATION_CAPABILITIES = {
    "dispatch.read",
    "dispatch.execute",
    "reconciliation.execute",
}
PERSISTED_CODES = COMPANY_CAPABILITIES | {"reconciliation.execute"}


class _ScalarDB:
    def __init__(self, results):
        self._results = list(results)
        self.scalar_calls = 0

    async def scalar(self, statement):
        self.scalar_calls += 1
        if not self._results:
            raise AssertionError("unexpected scalar call")
        return self._results.pop(0)


class _NeverDB:
    async def scalar(self, statement):
        raise AssertionError("canonical Owner grant resolution must not query grant storage")


class _ExecuteResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _StructuralDB:
    def __init__(self, *, route_row=(11, 22), scalar_results=(11, 11, 22, 33, 33)):
        self.route_row = route_row
        self.scalar_results = list(scalar_results)
        self.executed = []
        self.scalars = []

    async def execute(self, statement):
        self.executed.append(statement)
        return _ExecuteResult(self.route_row)

    async def scalar(self, statement):
        self.scalars.append(statement)
        if not self.scalar_results:
            raise AssertionError("unexpected scalar call")
        return self.scalar_results.pop(0)


class _RejectingAccess:
    async def require(self, *args, **kwargs):
        raise BackofficeCapabilityAccessRejected


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


def _depends_target(function, parameter_name):
    default = inspect.signature(function).parameters[parameter_name].default
    return default.dependency, default.use_cache


class DispatchCanonicalAuthorizationCutoverTests(unittest.IsolatedAsyncioTestCase):
    def test_dispatch_sources_have_zero_legacy_admin_authority(self):
        dispatch_source = DISPATCH_PATH.read_text(encoding="utf-8")
        access_source = DISPATCH_ACCESS_PATH.read_text(encoding="utf-8")

        self.assertNotIn("get_current_admin", dispatch_source)
        self.assertNotIn(".is_admin", dispatch_source)
        self.assertNotIn(".is_admin", access_source)
        self.assertNotIn("InventoryAccess", dispatch_source)
        self.assertNotIn("legacy_full_authority", dispatch_source)
        self.assertNotIn("legacy_full_authority", access_source)
        self.assertNotIn("legacy_backoffice_transport", dispatch_source)
        self.assertNotIn("get_current_driver", dispatch_source)
        self.assertIn("get_current_backoffice_legacy_driver", dispatch_source)

    def test_frozen_dispatch_related_capabilities_are_catalogued_with_exact_scope(self):
        self.assertTrue(COMPANY_CAPABILITIES <= PERMISSIONS)
        self.assertTrue(COMPANY_CAPABILITIES <= COMPANY_ONLY)
        self.assertTrue(LOCATION_CAPABILITIES <= PERMISSIONS)
        self.assertNotIn("reconciliation.execute", COMPANY_ONLY)
        self.assertNotIn("dispatch.read", COMPANY_ONLY)
        self.assertNotIn("dispatch.execute", COMPANY_ONLY)
        self.assertIn("sales_return.create", PERMISSIONS)
        self.assertNotIn("sales_return.create", COMPANY_ONLY)

    def test_permission_migration_persists_only_missing_frozen_codes_without_grants(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        self.assertIn('revision = "e4c8a1d6b203"', source)
        self.assertIn('down_revision = "e6f2a8c9d410"', source)
        self.assertIn("INSERT INTO permissions (code) VALUES", source)
        self.assertIn("ON CONFLICT (code) DO NOTHING", source)
        for code in sorted(PERSISTED_CODES):
            self.assertEqual(source.count(f"('{code}')"), 1)
        self.assertNotIn("role_permissions", source)
        self.assertNotIn("description", source.lower())
        self.assertIn("def downgrade()", source)
        self.assertIn("pass", source)

    def test_session_and_settlement_endpoints_use_exact_frozen_capabilities(self):
        expected = {
            dispatch.authorize_session: dispatch._work_session_authorize_sale,
            dispatch.get_admin_dashboard_data: dispatch._work_session_read,
            dispatch.get_session_settlement_report: dispatch._settlement_read,
            dispatch.settle_session: dispatch._settlement_execute,
            dispatch.undo_end_work: dispatch._work_session_reopen,
        }
        for endpoint, dependency in expected.items():
            target, use_cache = _depends_target(endpoint, "access")
            self.assertIs(target, dependency)
            self.assertTrue(use_cache)

        source = DISPATCH_PATH.read_text(encoding="utf-8")
        self.assertIn(
            'require_backoffice_capability("work_session.authorize_sale")',
            source,
        )
        self.assertIn(
            'require_backoffice_capability("work_session.read")',
            source,
        )
        self.assertIn(
            'require_backoffice_capability("work_session.reopen")',
            source,
        )
        self.assertIn(
            'require_backoffice_capability("settlement.read")',
            source,
        )
        self.assertIn(
            'require_backoffice_capability("settlement.execute")',
            source,
        )

    def test_shortage_endpoints_use_exact_frozen_capabilities(self):
        expected = {
            dispatch.get_shortages: dispatch._shortage_read,
            dispatch.add_shortages: dispatch._shortage_create,
            dispatch.delete_shortage: dispatch._shortage_cancel,
        }
        for endpoint, dependency in expected.items():
            target, use_cache = _depends_target(endpoint, "access")
            self.assertIs(target, dependency)
            self.assertTrue(use_cache)

    def test_dispatch_read_and_execute_surfaces_use_exact_frozen_capabilities(self):
        read_endpoints = (
            dispatch.dispatch_init,
            dispatch.get_vehicle_inventory,
            dispatch.get_route_live_inventory,
            dispatch.get_route_transfers,
            dispatch.get_dispatch_shops,
            dispatch.get_active_routes,
        )
        execute_endpoints = (
            dispatch.dispatch_route,
            dispatch.adjust_route_inventory,
            dispatch.force_cancel_handshake,
            dispatch.update_route_status,
        )
        for endpoint in read_endpoints:
            target, _ = _depends_target(endpoint, "access")
            self.assertIs(target, dispatch._dispatch_read_access)
        for endpoint in execute_endpoints:
            target, _ = _depends_target(endpoint, "access")
            self.assertIs(target, dispatch._dispatch_execute_access)

        source = DISPATCH_PATH.read_text(encoding="utf-8")
        self.assertIn('await require_any_location(access, "dispatch.read")', source)
        self.assertIn('await require_any_location(access, "dispatch.execute")', source)
        self.assertIn("await require_route(access, 'dispatch.read', route_id)", source)
        self.assertIn("await require_route(access, 'dispatch.execute', route_id)", source)
        self.assertIn("await require_vehicle(access, 'dispatch.execute', payload.vehicle_id)", source)
        self.assertIn('access, "dispatch.execute", int(transfer_source_location_id)', source)

    def test_company_level_dispatch_master_mutations_do_not_reuse_driver_authority(self):
        endpoints = (
            dispatch.bulk_update_shops,
            dispatch.admin_add_shop,
            dispatch.add_zone,
            dispatch.archive_zone,
            dispatch.update_zone,
            dispatch.restore_zone,
            dispatch.edit_shop_details,
            dispatch.bulk_import_shops,
        )
        for endpoint in endpoints:
            target, _ = _depends_target(endpoint, "access")
            self.assertIs(target, dispatch._dispatch_company_execute)
        target, _ = _depends_target(dispatch.get_archived_zones, "access")
        self.assertIs(target, dispatch._dispatch_company_read)

    def test_visit_and_reconciliation_frozen_codes_are_ready_without_fake_endpoint_mapping(self):
        self.assertIn("visit.read", PERMISSIONS)
        self.assertIn("visit.read", COMPANY_ONLY)
        self.assertIn("reconciliation.execute", PERMISSIONS)
        self.assertNotIn("reconciliation.execute", COMPANY_ONLY)

        tree = ast.parse(DISPATCH_PATH.read_text(encoding="utf-8"))
        route_strings = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "router":
                    if node.args and isinstance(node.args[0], ast.Constant):
                        route_strings.append(str(node.args[0].value))
        self.assertFalse(any("/visit" in route for route in route_strings))
        self.assertFalse(any("reconciliation" in route for route in route_strings))

    async def test_ordinary_backoffice_exact_capability_succeeds(self):
        db = _ScalarDB([True])
        access = BackofficeCapabilityAccess(db=db, subject=_ordinary_subject())
        await dispatch_access.require_any_location(access, "dispatch.read")
        self.assertEqual(db.scalar_calls, 1)

    async def test_missing_capability_is_opaque_403(self):
        with self.assertRaises(HTTPException) as caught:
            await dispatch_access.require_any_location(_RejectingAccess(), "dispatch.read")
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail, "Authorization denied.")

    async def test_company_level_capability_rejection_is_opaque_403(self):
        dependency = dispatch._work_session_read
        with self.assertRaises(HTTPException) as caught:
            await dependency(access=_RejectingAccess())
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail, "Authorization denied.")

    async def test_company_owner_uses_canonical_owner_semantics(self):
        access = BackofficeCapabilityAccess(db=_NeverDB(), subject=_owner_subject())
        await dispatch_access.require_any_location(access, "dispatch.execute")

    async def test_company_owner_still_passes_route_vehicle_location_structural_validation(self):
        db = _StructuralDB()
        access = BackofficeCapabilityAccess(db=db, subject=_owner_subject())
        await dispatch_access.require_route(access, "dispatch.execute", 44)

        self.assertEqual(len(db.executed), 1)
        self.assertEqual(len(db.scalars), 5)
        rendered = " ".join(str(statement) for statement in [*db.executed, *db.scalars])
        self.assertIn("dispatch_routes.company_id", rendered)
        self.assertIn("inventory_locations.company_id", rendered)
        self.assertIn("vehicles.company_id", rendered)
        self.assertIn("inventory_locations.location_type", rendered)
        self.assertIn("inventory_locations.is_active", rendered)

    async def test_foreign_or_missing_route_is_not_authorized_even_for_owner(self):
        db = _StructuralDB(route_row=None, scalar_results=())
        access = BackofficeCapabilityAccess(db=db, subject=_owner_subject())
        with self.assertRaises(HTTPException) as caught:
            await dispatch_access.require_route(access, "dispatch.execute", 999)
        self.assertEqual(caught.exception.status_code, 404)

    def test_company_authority_comes_from_canonical_access_only(self):
        source = DISPATCH_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)

        legacy_actor_attrs = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "legacy_actor"
        }
        self.assertEqual(legacy_actor_attrs, {"id"})
        self.assertNotIn("legacy_actor.company_id", source)
        self.assertNotIn("legacy_actor.is_admin", source)
        self.assertNotIn("current_admin", source)
        self.assertIn("access.company_id", source)

    def test_legacy_actor_id_is_only_fk_audit_provenance_or_operational_locator(self):
        source = DISPATCH_PATH.read_text(encoding="utf-8")
        self.assertNotIn("legacy_actor.company_id", source)
        self.assertNotIn("legacy_actor.is_admin", source)
        self.assertNotIn("legacy_actor.roles", source)

        allowed_contexts = (
            "admin_id=legacy_actor.id",
            "actor_id=legacy_actor.id",
            "performed_by=legacy_actor.id",
            "updated_by=legacy_actor.id",
            "dispatched_by=legacy_actor_id",
            "performed_by=legacy_actor_id",
            "updated_by=legacy_actor_id",
            "admin_id=legacy_actor_id",
            "legacy_actor_id=legacy_actor_id",
            "cancelled_by = legacy_actor.id",
            "added_by_driver_id=legacy_actor.id",
            "session.driver_id == legacy_actor.id",
            "legacy_actor_id=legacy_actor.id",
        )
        for line in source.splitlines():
            if "legacy_actor.id" in line or "legacy_actor_id" in line:
                if "legacy_actor_id: int" in line:
                    continue
                self.assertTrue(
                    any(context in line for context in allowed_contexts),
                    msg=f"unexpected legacy actor use: {line.strip()}",
                )

    def test_legacy_is_admin_true_or_false_cannot_change_dispatch_authority(self):
        source = DISPATCH_PATH.read_text(encoding="utf-8")
        true_actor = SimpleNamespace(id=903, company_id=999, is_admin=True)
        false_actor = SimpleNamespace(id=903, company_id=1, is_admin=False)
        self.assertEqual(true_actor.id, false_actor.id)
        self.assertNotIn("legacy_actor.is_admin", source)
        self.assertNotIn("legacy_actor.company_id", source)

    def test_self_authorization_separation_of_duties_guard_remains(self):
        source = inspect.getsource(dispatch.authorize_session)
        self.assertIn("session.driver_id == legacy_actor.id", source)
        self.assertIn("تضارب مصالح", source)
        self.assertIn(".with_for_update()", source)

    def test_locks_idempotency_and_transaction_guards_remain(self):
        source = DISPATCH_PATH.read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count(".with_for_update()"), 25)
        self.assertIn("begin_idempotent_operation(", source)
        self.assertIn("complete_idempotent_operation(", source)
        self.assertIn("pg_advisory_xact_lock", source)
        self.assertIn("acquire_inventory_location_guards(", source)
        self.assertIn("lock_route_commercial_context(", source)
        self.assertIn("await db.commit()", source)
        self.assertIn("await db.rollback()", source)
        self.assertIn("inventory_reconciled_at", source)
        self.assertIn("is_settled", source)

    def test_fastapi_dependency_cache_reuses_same_canonical_authentication(self):
        endpoint_access, endpoint_access_cache = _depends_target(
            dispatch.dispatch_route, "access"
        )
        endpoint_actor, endpoint_actor_cache = _depends_target(
            dispatch.dispatch_route, "legacy_actor"
        )
        self.assertIs(endpoint_access, dispatch._dispatch_execute_access)
        self.assertIs(endpoint_actor, get_current_backoffice_legacy_driver)
        self.assertTrue(endpoint_access_cache)
        self.assertTrue(endpoint_actor_cache)

        access_target, access_cache = _depends_target(
            dispatch._dispatch_execute_access, "access"
        )
        self.assertIs(access_target, get_current_backoffice_capability_access)
        self.assertTrue(access_cache)

        capability_context, capability_context_cache = _depends_target(
            get_current_backoffice_capability_access, "current"
        )
        actor_context, actor_context_cache = _depends_target(
            get_current_backoffice_legacy_driver, "current"
        )
        self.assertIs(capability_context, get_current_backoffice_context)
        self.assertIs(actor_context, get_current_backoffice_context)
        self.assertTrue(capability_context_cache)
        self.assertTrue(actor_context_cache)

        source = (
            DISPATCH_PATH.read_text(encoding="utf-8")
            + DISPATCH_ACCESS_PATH.read_text(encoding="utf-8")
        ).lower()
        self.assertNotIn("decode_company_token", source)
        self.assertNotIn("jwt.decode", source)

    def test_dispatch_transport_is_retired_globally_from_active_runtime(self):
        retired_symbols = (
            "legacy_backoffice_transport",
            "get_legacy_transport_backoffice_context",
            "get_legacy_transport_backoffice_capability_access",
            "require_legacy_transport_backoffice_capability",
        )
        hits = []
        runtime_root = REPO_ROOT / "wa_backend"
        for path in runtime_root.rglob("*.py"):
            relative = path.relative_to(runtime_root)
            if "tests" in relative.parts or "alembic" in relative.parts:
                continue
            source = path.read_text(encoding="utf-8")
            for symbol in retired_symbols:
                if symbol in source:
                    hits.append(f"{relative}:{symbol}")
        self.assertEqual(hits, [])

        auth_dir = REPO_ROOT / "wa_backend" / "api" / "authentication"
        self.assertFalse((auth_dir / "legacy_backoffice_transport.py").exists())
        compatibility = (auth_dir / "backoffice_compatibility.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("get_current_backoffice_legacy_driver", compatibility)
        self.assertIn("resolve_backoffice_legacy_actor_locator", compatibility)
        self.assertNotIn(".is_admin", compatibility)

    def test_canonical_and_legacy_identity_ids_are_independent(self):
        subject = _ordinary_subject()
        legacy_driver_id = 903
        self.assertEqual(
            len({subject.principal_id, subject.backoffice_user_id, legacy_driver_id}),
            3,
        )
        source = DISPATCH_PATH.read_text(encoding="utf-8")
        self.assertNotIn("principal_id == legacy_actor.id", source)
        self.assertNotIn("principal_id == Driver.id", source)


if __name__ == "__main__":
    unittest.main()
