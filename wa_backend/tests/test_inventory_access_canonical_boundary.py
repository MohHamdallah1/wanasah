"""Dependency-free authority, identity, UI and transaction guards for Inventory access."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "wa_backend/api/inventory_permissions.py"
DOMAIN = ROOT / "wa_backend/domains/inventory_access/administration.py"
ADMIN = {"permission_catalog", "roles", "create_role", "update_role", "users", "locations", "user_grants", "grant", "revoke"}
MUTATIONS = {"create_role", "update_role", "grant", "revoke"}


class Rejection(Exception):
    def __init__(self, status_code, detail):
        self.status_code, self.detail = status_code, detail


class InventoryAccessCanonicalBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.source = SOURCE.read_text(encoding="utf-8")
        self.domain = DOMAIN.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.functions = {
            node.name: node
            for node in self.tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def test_no_legacy_authority_or_generic_access_management_capability(self):
        for text in (self.source, self.domain):
            self.assertNotIn("legacy_backoffice_transport", text)
            self.assertNotIn("get_current_driver", text)
            self.assertNotIn(".is_admin", text)
            self.assertNotIn("is_company_admin", text)
            self.assertNotIn("InventoryAccess(", text)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "legacy_actor":
                self.assertEqual(node.attr, "id")

    def test_all_management_routes_are_owner_only_and_introspection_uses_canonical_access(self):
        routes = {name for name, node in self.functions.items() if node.decorator_list}
        self.assertEqual(routes, ADMIN | {"capabilities", "location_capabilities"})
        for name in routes:
            node = self.functions[name]
            defaults = dict(zip([arg.arg for arg in node.args.args][-len(node.args.defaults):], node.args.defaults))
            expected = "_require_company_owner" if name in ADMIN else "get_current_backoffice_capability_access"
            self.assertEqual(ast.unparse(defaults["access"]), f"Depends({expected})")
            if name in MUTATIONS:
                self.assertEqual(ast.unparse(defaults["legacy_actor"]), "Depends(get_current_backoffice_legacy_driver)")

    async def test_exact_owner_decision_rejects_false_or_truthy_non_owner_state(self):
        namespace = {
            "BackofficeCapabilityAccess": object,
            "Depends": lambda dependency: None,
            "get_current_backoffice_capability_access": object,
            "HTTPException": Rejection,
        }
        exec(
            compile(ast.Module(body=[self.functions["_require_company_owner"]], type_ignores=[]), "owner_gate", "exec"),
            namespace,
        )
        for state in (False, 1, "Owner", None):
            with self.assertRaises(Rejection) as denied:
                await namespace["_require_company_owner"](SimpleNamespace(subject=SimpleNamespace(is_company_owner=state)))
            self.assertEqual((denied.exception.status_code, denied.exception.detail), (403, "Authorization denied."))
        current = SimpleNamespace(subject=SimpleNamespace(is_company_owner=True))
        self.assertIs(await namespace["_require_company_owner"](current), current)

    def test_self_response_is_canonical_and_location_reads_remain_canonical(self):
        body = ast.unparse(self.functions["capabilities"])
        for field in (
            "company_id",
            "principal_id",
            "backoffice_user_id",
            "is_company_owner",
            "location_id",
            "permissions",
            "any_permissions",
            "location_permissions",
        ):
            self.assertIn(repr(field), body)
        self.assertIn("access.codes()", body)
        self.assertIn("access.codes(location_id)", body)
        self.assertIn("access.codes_by_location(payload.location_ids)", ast.unparse(self.functions["location_capabilities"]))

    def test_canonical_target_mapping_and_storage_columns_keep_ids_independent(self):
        for condition in (
            "BackofficeUser.id == backoffice_user_id",
            "CompanyPrincipal.company_id == company_id",
            "IdentityLegacyDriverMap.company_id == company_id",
            "IdentityLegacyDriverMap.backoffice_principal_id == target.principal_id",
            "IdentityLegacyDriverMap.backoffice_user_id == backoffice_user_id",
        ):
            self.assertIn(condition, self.domain)
        for name in ("user_grants", "grant", "revoke"):
            body = ast.unparse(self.functions[name])
            self.assertIn("legacy_grant_driver_id = await target_legacy_grant_driver_id(db, access, user_id)", body)
            self.assertNotIn("driver_id == user_id", body)
        self.assertIn("'driver_id': legacy_grant_driver_id", ast.unparse(self.functions["grant"]))

    def test_role_and_grant_mutations_preserve_lock_idempotency_scope_and_atomic_commit(self):
        save = ast.unparse(self.functions["save_role"])
        grant = ast.unparse(self.functions["grant"])
        revoke = ast.unparse(self.functions["revoke"])
        self.assertIn("pg_advisory_xact_lock", save)
        self.assertIn("with_for_update()", save)
        self.assertIn("permission_ids_for_codes(db, codes)", save)
        self.assertNotIn("insert(Permission)", save)
        self.assertIn("await db.commit()", save)
        self.assertIn("on_conflict_do_nothing()", grant)
        self.assertIn("InventoryLocation.company_id == access.company_id", grant)
        self.assertIn("InventoryLocation.location_type.in_(['WAREHOUSE', 'VEHICLE'])", grant)
        self.assertIn("await db.commit()", grant)
        self.assertIn("with_for_update()", revoke)
        self.assertIn("await db.commit()", revoke)

    def test_permission_catalog_is_registry_owned_and_database_validated(self):
        catalog = ast.unparse(self.functions["permission_catalog"])
        self.assertIn("await ensure_permission_catalog(db)", catalog)
        self.assertIn("sorted(PERMISSIONS)", catalog)
        self.assertIn("sorted(COMPANY_ONLY)", catalog)
        self.assertIn("Permission.code.in_(PERMISSIONS)", self.domain)

    def test_audit_company_and_attribution_are_passed_explicitly(self):
        body = ast.unparse(self.functions["audit"])
        self.assertIn("company_id=company_id", body)
        self.assertIn("admin_id=legacy_actor_id", body)
        for name in ("save_role", "grant", "revoke"):
            calls = [
                node for node in ast.walk(self.functions[name])
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "audit"
            ]
            self.assertEqual(len(calls), 1)
            self.assertEqual([ast.unparse(arg) for arg in calls[0].args[:3]], ["db", "access.company_id", "legacy_actor.id"])

    def test_frontend_selects_canonical_profile_and_has_no_legacy_identity_alias(self):
        page = (ROOT / "dashboard/src/pages/inventory/TabInventoryAccess.tsx").read_text(encoding="utf-8")
        contracts = (ROOT / "dashboard/src/pages/inventory/access/contracts.ts").read_text(encoding="utf-8")
        grants = (ROOT / "dashboard/src/pages/inventory/access/GrantAccessPanel.tsx").read_text(encoding="utf-8")
        hook = (ROOT / "dashboard/src/hooks/useInventoryAccess.ts").read_text(encoding="utf-8")
        for forbidden in ("isCompanyAdmin", "is_company_admin", "is_admin", "driver_id"):
            self.assertNotIn(forbidden, page)
            self.assertNotIn(forbidden, contracts)
            self.assertNotIn(forbidden, grants)
            self.assertNotIn(forbidden, hook)
        self.assertIn("isCompanyOwner: data?.is_company_owner === true", hook)
        self.assertIn("key={user.backoffice_user_id} value={user.backoffice_user_id}", grants)
        self.assertIn("dir={i18n.dir()}", page)


if __name__ == "__main__":
    unittest.main()
