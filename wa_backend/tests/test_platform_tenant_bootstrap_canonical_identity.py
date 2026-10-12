"""Focused canonical tenant-bootstrap identity acceptance."""
from __future__ import annotations

import ast
import copy
import hashlib
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "api" / "platform_manager.py"

UNCHANGED_FUNCTION_DIGESTS = {
    "get_current_platform_admin": "7508417d2784742e8165f67db75062da307a7904b3ae4ff152f6cab1abb08dba",
    "_check_platform_login_limit": "9b8009a6812688806b171dc68a7dff6d1ac86f1f5edc5b27feb54beee9a0c208",
    "_record_platform_login": "0abd16abb0555ed8c82870d3e20004eb7d9fc42112b8cdf024ba4e7e50ad5804",
    "platform_admin_login": "04f084104e83e1593a93339caf6643bea346abaa4ee243f73d30c8a5595eee1c",
    "list_all_tenants": "b7cb0657b102c9d0389126b5ab53e796981f58ea32fd188b561bbb860e4bf582",
}


def _digest(node: ast.AST) -> str:
    tree = copy.deepcopy(node)
    for item in ast.walk(tree):
        if getattr(item, "type_params", None) == []:
            del item.type_params
    return hashlib.sha256(
        ast.dump(tree, include_attributes=False).encode()
    ).hexdigest()


def _functions(tree: ast.Module) -> dict[str, ast.AST]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _assigned_call(function: ast.AST, variable: str) -> ast.Call:
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == variable
            and isinstance(node.value, ast.Call)
        ):
            return node.value
    raise AssertionError(f"assignment for {variable} not found")


def _keywords(call: ast.Call) -> dict[str, ast.AST]:
    return {item.arg: item.value for item in call.keywords if item.arg is not None}


def _calls(function: ast.AST, name: str) -> list[ast.Call]:
    result = []
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == name:
                result.append(node)
            elif isinstance(node.func, ast.Attribute) and node.func.attr == name:
                result.append(node)
    return result


class PlatformTenantBootstrapCanonicalIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.functions = _functions(cls.tree)
        cls.create = cls.functions["create_new_tenant"]

    def test_creates_canonical_backoffice_principal(self):
        call = _assigned_call(self.create, "owner_principal")
        self.assertEqual(ast.unparse(call.func), "CompanyPrincipal")
        kw = _keywords(call)
        self.assertEqual(ast.unparse(kw["company_id"]), "company.id")
        self.assertEqual(ast.unparse(kw["username"]), "payload.admin_username")
        self.assertEqual(ast.unparse(kw["password_hash"]), "hashed_pw")
        self.assertEqual(ast.unparse(kw["full_name"]), "payload.admin_full_name")
        self.assertEqual(
            ast.unparse(kw["principal_type"]),
            "PrincipalType.BACKOFFICE.value",
        )
        self.assertIs(kw["is_active"].value, True)
        self.assertEqual(kw["auth_revision"].value, 1)

    def test_creates_backoffice_user_linked_to_exact_principal(self):
        call = _assigned_call(self.create, "owner_backoffice_user")
        self.assertEqual(ast.unparse(call.func), "BackofficeUser")
        kw = _keywords(call)
        self.assertEqual(ast.unparse(kw["company_id"]), "company.id")
        self.assertEqual(ast.unparse(kw["principal_id"]), "owner_principal.id")
        self.assertEqual(
            ast.unparse(kw["principal_type"]),
            "PrincipalType.BACKOFFICE.value",
        )

    def test_creates_explicit_company_owner(self):
        call = _assigned_call(self.create, "company_owner")
        self.assertEqual(ast.unparse(call.func), "CompanyOwner")
        kw = _keywords(call)
        self.assertEqual(ast.unparse(kw["company_id"]), "company.id")
        self.assertEqual(
            ast.unparse(kw["backoffice_user_id"]),
            "owner_backoffice_user.id",
        )

    def test_legacy_driver_is_compatibility_only_and_not_owner_authority(self):
        call = _assigned_call(self.create, "admin_driver")
        self.assertEqual(ast.unparse(call.func), "Driver")
        kw = _keywords(call)
        self.assertEqual(ast.unparse(kw["company_id"]), "company.id")
        self.assertEqual(ast.unparse(kw["username"]), "payload.admin_username")
        self.assertEqual(ast.unparse(kw["password_hash"]), "hashed_pw")
        self.assertEqual(ast.unparse(kw["full_name"]), "payload.admin_full_name")
        self.assertIs(kw["is_admin"].value, False)
        self.assertIs(kw["is_active"].value, True)
        create_source = ast.unparse(self.create)
        self.assertNotIn("is_admin=True", create_source)
        self.assertNotIn("if admin_driver.is_admin", create_source)

    def test_identity_legacy_driver_map_is_exact_backoffice_only_shape(self):
        call = _assigned_call(self.create, "identity_map")
        self.assertEqual(ast.unparse(call.func), "IdentityLegacyDriverMap")
        kw = _keywords(call)
        self.assertEqual(kw["classification"].value, "BACKOFFICE_ONLY")
        self.assertEqual(ast.unparse(kw["company_id"]), "company.id")
        self.assertEqual(ast.unparse(kw["legacy_driver_id"]), "admin_driver.id")
        self.assertEqual(
            ast.unparse(kw["backoffice_principal_id"]),
            "owner_principal.id",
        )
        self.assertEqual(
            ast.unparse(kw["backoffice_user_id"]),
            "owner_backoffice_user.id",
        )
        self.assertIsInstance(kw["field_principal_id"], ast.Constant)
        self.assertIsNone(kw["field_principal_id"].value)
        self.assertIsInstance(kw["field_representative_id"], ast.Constant)
        self.assertIsNone(kw["field_representative_id"].value)

    def test_ids_are_independent_and_never_forced_equal(self):
        source = ast.unparse(self.create)
        forbidden = (
            "owner_principal.id = owner_backoffice_user.id",
            "owner_principal.id = admin_driver.id",
            "owner_backoffice_user.id = admin_driver.id",
            "admin_driver.id = owner_principal.id",
            "admin_driver.id = owner_backoffice_user.id",
        )
        for fragment in forbidden:
            self.assertNotIn(fragment, source)
        self.assertIn("principal_id=owner_principal.id", source)
        self.assertIn("backoffice_user_id=owner_backoffice_user.id", source)
        self.assertIn("legacy_driver_id=admin_driver.id", source)

    def test_all_canonical_identity_rows_share_new_company_and_no_field_identity_created(self):
        source = ast.unparse(self.create)
        for variable in (
            "owner_principal",
            "owner_backoffice_user",
            "company_owner",
            "admin_driver",
            "identity_map",
        ):
            call = _assigned_call(self.create, variable)
            self.assertEqual(
                ast.unparse(_keywords(call)["company_id"]),
                "company.id",
                variable,
            )
        self.assertNotIn("FieldRepresentative(", source)
        self.assertNotIn("FIELD_REPRESENTATIVE", source)

    def test_existing_price_assignment_and_cost_provenance_use_legacy_driver_id(self):
        for name in (
            "create_price_book",
            "create_assignment",
            "provision_default_cost_policy",
        ):
            calls = _calls(self.create, name)
            self.assertEqual(len(calls), 1, name)
            kw = _keywords(calls[0])
            self.assertEqual(ast.unparse(kw["company_id"]), "company.id")
            self.assertEqual(ast.unparse(kw["actor_id"]), "admin_driver.id")
        source = ast.unparse(self.create)
        self.assertNotIn("actor_id=owner_principal.id", source)
        self.assertNotIn("actor_id=owner_backoffice_user.id", source)

    def test_duplicate_company_precheck_and_409_contract_remain_before_writes(self):
        body = self.create.body
        first_try = next(i for i, node in enumerate(body) if isinstance(node, ast.Try))
        pre_try = ast.unparse(ast.Module(body=body[:first_try], type_ignores=[]))
        self.assertIn("select(Company.id).filter_by(company_code=payload.company_code)", pre_try)
        self.assertIn(
            "HTTPException(status_code=409, detail='رمز الشركة (company_code) مستخدم بالفعل.')",
            pre_try,
        )
        self.assertNotIn("db.add(", pre_try)
        self.assertNotIn("db.commit(", pre_try)

    def test_downstream_provisioning_failure_rolls_back_entire_bootstrap(self):
        source = ast.unparse(self.create)
        create_book = source.index("await create_price_book")
        create_assignment = source.index("await create_assignment")
        cost_policy = source.index("await provision_default_cost_policy")
        commit = source.index("await db.commit()")
        self.assertLess(create_book, create_assignment)
        self.assertLess(create_assignment, cost_policy)
        self.assertLess(cost_policy, commit)
        self.assertEqual(source.count("await db.commit()"), 1)
        self.assertEqual(source.count("await db.rollback()"), 2)
        handlers = next(node for node in self.create.body if isinstance(node, ast.Try)).handlers
        self.assertEqual(len(handlers), 2)
        self.assertTrue(
            all("await db.rollback()" in ast.unparse(handler) for handler in handlers)
        )

    def test_rls_branch_subscription_currency_password_and_response_contracts_remain(self):
        source = ast.unparse(self.create)
        for fragment in (
            "subscription_status=payload.subscription_status",
            "currency_code=payload.currency_code",
            "text(\"SELECT set_config('app.current_tenant', :tenant_id, true)\")",
            "{'tenant_id': str(company.id)}",
            "name='الفرع الرئيسي'",
            "branch_code='HQ'",
            "payload.admin_password.encode('utf-8')",
            "bcrypt.gensalt()",
            "'company_id': company.id",
            "'company_code': company.company_code",
        ):
            self.assertIn(fragment, source)
        decorator = self.create.decorator_list[0]
        self.assertEqual(ast.unparse(decorator.func), "router.post")
        self.assertEqual(decorator.args[0].value, "/companies")
        self.assertEqual(_keywords(decorator)["status_code"].value, 201)

    def test_platform_admin_login_and_company_listing_are_unchanged(self):
        for name, expected in UNCHANGED_FUNCTION_DIGESTS.items():
            self.assertEqual(_digest(self.functions[name]), expected, name)
        self.assertNotIn("CompanyPrincipal", ast.unparse(self.functions["platform_admin_login"]))
        self.assertNotIn("CompanyOwner", ast.unparse(self.functions["platform_admin_login"]))


if __name__ == "__main__":
    unittest.main()
