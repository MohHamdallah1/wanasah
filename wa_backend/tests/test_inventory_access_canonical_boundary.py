"""Dependency-free authority, identity, UI and workflow cutover guards."""
import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "wa_backend/api/inventory_permissions.py"
ADMIN = {"permission_catalog", "roles", "create_role", "update_role", "users", "locations", "user_grants", "grant", "revoke"}
MUTATIONS = {"create_role", "update_role", "grant", "revoke"}
# Main 5579a8db business bodies, excluding the authorized identity/audit seam changes.
WORKFLOWS = {
    "roles": "e4b09a73956f3870d5ec4dcc023be58e1681ea4b3a44bee515d280b8a770ab52",
    "save_role": "a0abe6d6e378049a3b28bc6cad9cc17a11671722928440ea49dd8d8a5bbd600d",
    "locations": "bb08c47461d24efc682cbb24f636bbc79185f05ffb03a7bc22e62c0009a8c192",
    "user_grants": "c2ed4845e72b91e5a44f8d2f83b2a1c1dab5876fa4f30447c40dee375159bb40",
    "grant": "aa74ca173b392869bb7485fd1bf5eef3f58373d1daacb60d19b91da69e256118",
    "revoke": "e8eb16dd04e2a6c058354b319a61e7fe7557245f2b8cd6972431619c08ef6806",
}


class Workflow(ast.NodeTransformer):
    def visit_Name(self, node):
        node.id = {"actor": "access", "user_id": "legacy_grant_driver_id"}.get(node.id, node.id)
        return node

    def visit_Expr(self, node):
        value = node.value.value if isinstance(node.value, ast.Await) else node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in {
            "audit", "user_exists", "target_legacy_grant_driver_id",
        }:
            return None
        return self.generic_visit(node)

    def visit_Assign(self, node):
        value = node.value.value if isinstance(node.value, ast.Await) else node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "target_legacy_grant_driver_id":
            return None
        return self.generic_visit(node)


class Rejection(Exception):
    def __init__(self, status_code, detail):
        self.status_code, self.detail = status_code, detail


class InventoryAccessCanonicalBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.source = SOURCE.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.functions = {node.name: node for node in self.tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def test_no_legacy_authority_or_generic_access_management_capability(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, {"get_current_admin", "InventoryAccess"})
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"is_admin", "is_company_admin", "classification"})
                if isinstance(node.value, ast.Name) and node.value.id == "legacy_actor":
                    self.assertEqual(node.attr, "id")
                if isinstance(node.value, ast.Name) and node.value.id == "Driver":
                    self.fail("Driver columns must not resolve users or authority")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertFalse(node.value.startswith(("authorization.", "access.", "admin.", "supervisor.", "manager.")))

    def test_all_management_routes_are_owner_only_and_both_introspection_routes_are_not(self):
        routes = {name for name, node in self.functions.items() if node.decorator_list}
        self.assertEqual(routes, ADMIN | {"capabilities", "location_capabilities"})
        for name in routes:
            node = self.functions[name]
            defaults = dict(zip([arg.arg for arg in node.args.args][-len(node.args.defaults):], node.args.defaults))
            dependency = defaults["access"]
            expected = "_require_company_owner" if name in ADMIN else "get_legacy_transport_backoffice_capability_access"
            self.assertEqual(ast.unparse(dependency), f"Depends({expected})")
            if name in MUTATIONS:
                self.assertEqual(ast.unparse(defaults["legacy_actor"]), "Depends(get_current_driver)")
        self.assertNotIn(".require(", self.source)

    async def test_exact_owner_decision_rejects_false_or_truthy_non_owner_state(self):
        namespace = {"BackofficeCapabilityAccess": object, "Depends": lambda dependency: None,
                     "get_legacy_transport_backoffice_capability_access": object, "HTTPException": Rejection}
        exec(compile(ast.Module(body=[self.functions["_require_company_owner"]], type_ignores=[]), "owner_gate", "exec"), namespace)
        for state in (False, 1, "Owner", None):
            with self.assertRaises(Rejection) as denied:
                await namespace["_require_company_owner"](SimpleNamespace(subject=SimpleNamespace(is_company_owner=state)))
            self.assertEqual((denied.exception.status_code, denied.exception.detail), (403, "Authorization denied."))
        current = SimpleNamespace(subject=SimpleNamespace(is_company_owner=True))
        self.assertIs(await namespace["_require_company_owner"](current), current)

    def test_self_response_is_canonical_and_uses_existing_backoffice_capability_access(self):
        dictionaries = [node for node in ast.walk(self.functions["capabilities"]) if isinstance(node, ast.Dict)]
        fields = {key.value for key in dictionaries[0].keys}
        self.assertEqual(fields, {"company_id", "principal_id", "backoffice_user_id", "is_company_owner", "location_id",
                                  "permissions", "any_permissions", "location_permissions"})
        imports = [node for node in self.tree.body if isinstance(node, ast.ImportFrom)]
        self.assertTrue(any(node.module == "domains.authorization.capabilities" for node in imports))
        self.assertTrue(any(node.module == "domains.authorization.backoffice_access" for node in imports))

    def test_canonical_target_mapping_and_storage_columns_keep_ids_independent(self):
        target = ast.unparse(self.functions["target_legacy_grant_driver_id"])
        for condition in ("BackofficeUser.id == backoffice_user_id", "CompanyPrincipal.company_id == access.company_id",
                          "IdentityLegacyDriverMap.company_id == access.company_id",
                          "IdentityLegacyDriverMap.backoffice_principal_id == target.principal_id",
                          "IdentityLegacyDriverMap.backoffice_user_id == backoffice_user_id"):
            self.assertIn(condition, target)
        for name in ("user_grants", "grant", "revoke"):
            body = ast.unparse(self.functions[name])
            self.assertIn("legacy_grant_driver_id = await target_legacy_grant_driver_id(db, access, user_id)", body)
            self.assertNotIn("driver_id == user_id", body)
        self.assertIn("'driver_id': legacy_grant_driver_id", ast.unparse(self.functions["grant"]))

    def test_locks_role_rules_location_validation_pagination_and_transactions_are_preserved(self):
        for name, expected in WORKFLOWS.items():
            # Parse afresh because the normalization mutates its input.
            node = next(node for node in ast.parse(self.source).body if isinstance(node, ast.AsyncFunctionDef) and node.name == name)
            normalized = Workflow().visit(ast.Module(body=node.body, type_ignores=[]))
            actual = hashlib.sha256(ast.dump(normalized, include_attributes=False).encode()).hexdigest()
            self.assertEqual(actual, expected, name)

    def test_audit_company_and_attribution_are_passed_explicitly(self):
        body = ast.unparse(self.functions["audit"])
        self.assertIn("company_id=company_id", body)
        self.assertIn("admin_id=legacy_actor_id", body)
        self.assertNotIn("actor.company_id", body)
        for name in ("save_role", "grant", "revoke"):
            calls = [node for node in ast.walk(self.functions[name]) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name) and node.func.id == "audit"]
            self.assertEqual(len(calls), 1)
            self.assertEqual([ast.unparse(arg) for arg in calls[0].args[:3]], ["db", "access.company_id", "legacy_actor.id"])

    def test_frontend_selects_canonical_profile_and_displays_localized_owner(self):
        page = (ROOT / "dashboard/src/pages/inventory/TabInventoryAccess.tsx").read_text(encoding="utf-8")
        hook = (ROOT / "dashboard/src/hooks/useInventoryAccess.ts").read_text(encoding="utf-8")
        for forbidden in ("is_admin", "Admin كامل الصلاحيات", "driver_id"):
            self.assertNotIn(forbidden, page)
        self.assertNotIn("driver_id", hook)
        for forbidden in ("isCompanyAdmin", "is_company_admin", "is_admin"):
            self.assertNotIn(forbidden, page)
            self.assertNotIn(forbidden, hook)
        self.assertIn("isCompanyOwner: data?.is_company_owner === true", hook)
        dashboard = ROOT / "dashboard/src"
        for runtime in dashboard.rglob("*"):
            if runtime.suffix in {".ts", ".tsx"} and "test" not in runtime.relative_to(dashboard).parts:
                self.assertNotIn("isCompanyAdmin", runtime.read_text(encoding="utf-8"), str(runtime))
        self.assertIn("key={user.backoffice_user_id} value={user.backoffice_user_id}", page)
        self.assertIn("/inventory/access/users/${backofficeUserId}/grants", page)
        self.assertIn("t('inventoryAccessAdmin.companyOwner')", page)
        self.assertIn("dir={i18n.dir()}", page)


if __name__ == "__main__":
    unittest.main()
