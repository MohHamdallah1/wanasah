"""Focused development seed / bootstrap canonical identity acceptance."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = ROOT / "seed_dev.py"
PLATFORM_PATH = ROOT / "api" / "platform_manager.py"


def _functions(tree: ast.Module) -> dict[str, ast.AST]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _assigned_constructor(function: ast.AST, variable: str, constructor: str) -> ast.Call:
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == variable
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == constructor
        ):
            return node.value
    raise AssertionError(f"{variable} = {constructor}(...) not found")


def _keywords(call: ast.Call) -> dict[str, ast.AST]:
    return {item.arg: item.value for item in call.keywords if item.arg is not None}


class DevSeedCanonicalIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed_source = SEED_PATH.read_text(encoding="utf-8")
        cls.seed_tree = ast.parse(cls.seed_source)
        cls.seed_function = _functions(cls.seed_tree)["_ensure_company_and_admin"]
        cls.seed_unparsed = ast.unparse(cls.seed_function)
        cls.platform_source = PLATFORM_PATH.read_text(encoding="utf-8")
        cls.platform_tree = ast.parse(cls.platform_source)
        cls.platform_create = _functions(cls.platform_tree)["create_new_tenant"]

    def test_seed_has_zero_driver_is_admin_reads_or_writes(self):
        self.assertNotIn(".is_admin", self.seed_source)
        self.assertNotIn("is_admin=", self.seed_source)
        driver_call = _assigned_constructor(self.seed_function, "admin", "Driver")
        self.assertNotIn("is_admin", _keywords(driver_call))

    def test_seed_creates_canonical_owner_chain_before_legacy_driver(self):
        for fragment in (
            "CompanyPrincipal(",
            "BackofficeUser(",
            "CompanyOwner(",
            "Driver(",
            "IdentityLegacyDriverMap(",
        ):
            self.assertIn(fragment, self.seed_unparsed)
        positions = [
            self.seed_unparsed.index(fragment)
            for fragment in (
                "CompanyPrincipal(",
                "BackofficeUser(",
                "CompanyOwner(",
                "Driver(",
                "IdentityLegacyDriverMap(",
            )
        ]
        self.assertEqual(positions, sorted(positions))

        principal = _assigned_constructor(
            self.seed_function, "owner_principal", "CompanyPrincipal"
        )
        principal_kw = _keywords(principal)
        self.assertEqual(ast.unparse(principal_kw["company_id"]), "company.id")
        self.assertEqual(principal_kw["username"].id, "ADMIN_USERNAME")
        self.assertEqual(
            ast.unparse(principal_kw["principal_type"]),
            "PrincipalType.BACKOFFICE.value",
        )
        self.assertIs(principal_kw["is_active"].value, True)
        self.assertEqual(principal_kw["auth_revision"].value, 1)

        user = _assigned_constructor(
            self.seed_function, "owner_backoffice_user", "BackofficeUser"
        )
        user_kw = _keywords(user)
        self.assertEqual(ast.unparse(user_kw["company_id"]), "company.id")
        self.assertEqual(ast.unparse(user_kw["principal_id"]), "owner_principal.id")

        owner = _assigned_constructor(
            self.seed_function, "company_owner", "CompanyOwner"
        )
        owner_kw = _keywords(owner)
        self.assertEqual(ast.unparse(owner_kw["company_id"]), "company.id")
        self.assertEqual(
            ast.unparse(owner_kw["backoffice_user_id"]),
            "owner_backoffice_user.id",
        )

    def test_rerun_queries_before_create_and_repairs_exact_rows(self):
        for fragment in (
            "select(CompanyPrincipal).where(",
            "CompanyPrincipal.username == ADMIN_USERNAME",
            "if owner_principal is None:",
            "select(BackofficeUser).where(",
            "BackofficeUser.principal_id == owner_principal.id",
            "if owner_backoffice_user is None:",
            "select(CompanyOwner).where(CompanyOwner.company_id == company.id)",
            "if company_owner is None:",
            "select(Driver).where(",
            "Driver.username == ADMIN_USERNAME",
            "if admin is None:",
            "if identity_map is None:",
        ):
            self.assertIn(fragment, self.seed_unparsed)

        self.assertEqual(self.seed_unparsed.count("CompanyPrincipal("), 1)
        self.assertEqual(self.seed_unparsed.count("BackofficeUser("), 1)
        self.assertEqual(self.seed_unparsed.count("CompanyOwner("), 1)
        self.assertEqual(self.seed_unparsed.count("Driver("), 1)
        self.assertEqual(self.seed_unparsed.count("IdentityLegacyDriverMap("), 1)

        self.assertIn(
            "company_owner.backoffice_user_id = owner_backoffice_user.id",
            self.seed_unparsed,
        )
        for fragment in (
            "identity_map.classification = 'BACKOFFICE_ONLY'",
            "identity_map.legacy_driver_id = admin.id",
            "identity_map.backoffice_principal_id = owner_principal.id",
            "identity_map.backoffice_user_id = owner_backoffice_user.id",
            "identity_map.field_principal_id = None",
            "identity_map.field_representative_id = None",
        ):
            self.assertIn(fragment, self.seed_unparsed)

    def test_bridge_uses_exact_independent_canonical_and_legacy_ids(self):
        bridge = _assigned_constructor(
            self.seed_function, "identity_map", "IdentityLegacyDriverMap"
        )
        kw = _keywords(bridge)
        self.assertEqual(kw["classification"].value, "BACKOFFICE_ONLY")
        self.assertEqual(ast.unparse(kw["company_id"]), "company.id")
        self.assertEqual(ast.unparse(kw["legacy_driver_id"]), "admin.id")
        self.assertEqual(
            ast.unparse(kw["backoffice_principal_id"]), "owner_principal.id"
        )
        self.assertEqual(
            ast.unparse(kw["backoffice_user_id"]), "owner_backoffice_user.id"
        )
        self.assertIsNone(kw["field_principal_id"].value)
        self.assertIsNone(kw["field_representative_id"].value)

        for forbidden in (
            "owner_principal.id = owner_backoffice_user.id",
            "owner_principal.id = admin.id",
            "owner_backoffice_user.id = admin.id",
            "admin.id = owner_principal.id",
            "admin.id = owner_backoffice_user.id",
        ):
            self.assertNotIn(forbidden, self.seed_unparsed)

    def test_legacy_driver_keeps_password_and_provenance_only_not_owner_authority(self):
        driver = _assigned_constructor(self.seed_function, "admin", "Driver")
        kw = _keywords(driver)
        self.assertEqual(ast.unparse(kw["company_id"]), "company.id")
        self.assertEqual(kw["username"].id, "ADMIN_USERNAME")
        self.assertEqual(
            ast.unparse(kw["password_hash"]), "owner_principal.password_hash"
        )
        self.assertIs(kw["is_active"].value, True)
        self.assertNotIn("is_admin", kw)
        self.assertIn(
            "admin.password_hash = owner_principal.password_hash",
            self.seed_unparsed,
        )
        for name in (
            "create_price_book",
            "create_assignment",
            "provision_default_cost_policy",
        ):
            self.assertIn(f"actor_id=admin.id", self.seed_unparsed)
        for forbidden in (
            "Role(",
            "UserRole(",
            "Permission(",
            "is_company_owner =",
        ):
            self.assertNotIn(forbidden, self.seed_unparsed)

    def test_development_credentials_and_safety_guards_remain(self):
        for fragment in (
            'COMPANY_CODE = "WNS-01"',
            'ADMIN_USERNAME = "admin_1"',
            'ADMIN_PASSWORD = "password"',
            'ADMIN_FULL_NAME = "مدير التطوير"',
            'environment not in {"development", "dev", "local", "test"}',
            'host not in {"127.0.0.1", "localhost", "::1"}',
            '("dev", "test", "local")',
        ):
            self.assertIn(fragment, self.seed_source)
        self.assertIn("bcrypt.checkpw", self.seed_source)
        self.assertIn("bcrypt.hashpw", self.seed_source)

    def test_platform_bootstrap_driver_has_no_is_admin_semantics(self):
        create_source = ast.unparse(self.platform_create)
        driver_call = _assigned_constructor(
            self.platform_create, "admin_driver", "Driver"
        )
        self.assertNotIn("is_admin", _keywords(driver_call))
        self.assertNotIn("admin_driver.is_admin", create_source)
        self.assertNotIn("Driver.is_admin", create_source)

        owner = _assigned_constructor(
            self.platform_create, "company_owner", "CompanyOwner"
        )
        owner_kw = _keywords(owner)
        self.assertEqual(ast.unparse(owner_kw["company_id"]), "company.id")
        self.assertEqual(
            ast.unparse(owner_kw["backoffice_user_id"]),
            "owner_backoffice_user.id",
        )
        bridge = _assigned_constructor(
            self.platform_create, "identity_map", "IdentityLegacyDriverMap"
        )
        bridge_kw = _keywords(bridge)
        self.assertEqual(
            ast.unparse(bridge_kw["legacy_driver_id"]), "admin_driver.id"
        )
        self.assertEqual(
            ast.unparse(bridge_kw["backoffice_principal_id"]),
            "owner_principal.id",
        )
        self.assertEqual(
            ast.unparse(bridge_kw["backoffice_user_id"]),
            "owner_backoffice_user.id",
        )

    def test_no_request_runtime_authority_is_reintroduced(self):
        for source in (self.seed_source, ast.unparse(self.platform_create)):
            self.assertNotIn("Driver.is_admin", source)
            self.assertNotIn("admin_driver.is_admin", source)
            self.assertNotIn("admin.is_admin", source)
        platform_driver = _assigned_constructor(
            self.platform_create, "admin_driver", "Driver"
        )
        self.assertNotIn("is_admin", _keywords(platform_driver))


if __name__ == "__main__":
    unittest.main()
