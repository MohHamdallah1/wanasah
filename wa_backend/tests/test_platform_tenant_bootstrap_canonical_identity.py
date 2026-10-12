"""Focused canonical tenant-bootstrap identity acceptance."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "api" / "platform_manager.py"


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


def _string_constants(node: ast.AST) -> set[str]:
    return {
        item.value
        for item in ast.walk(node)
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    }


def _name_references(node: ast.AST) -> set[str]:
    return {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}


def _parameter_defaults(function: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, ast.AST]:
    positional = function.args.args
    defaults = function.args.defaults
    return {
        arg.arg: default
        for arg, default in zip(positional[-len(defaults):], defaults)
    } if defaults else {}


def _payload_get_compare(
    node: ast.AST,
    *,
    key: str,
    operator_type: type[ast.cmpop],
    expected: object,
) -> bool:
    for item in ast.walk(node):
        if not isinstance(item, ast.Compare) or len(item.ops) != 1 or len(item.comparators) != 1:
            continue
        left = item.left
        if not (
            isinstance(left, ast.Call)
            and isinstance(left.func, ast.Attribute)
            and isinstance(left.func.value, ast.Name)
            and left.func.value.id == "payload"
            and left.func.attr == "get"
            and len(left.args) == 1
            and isinstance(left.args[0], ast.Constant)
            and left.args[0].value == key
        ):
            continue
        if not isinstance(item.ops[0], operator_type):
            continue
        comparator = item.comparators[0]
        if isinstance(comparator, ast.Constant) and comparator.value == expected:
            return True
    return False


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
        current = self.functions["get_current_platform_admin"]
        current_strings = _string_constants(current)

        decode_calls = [
            call for call in _calls(current, "decode")
            if isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "jwt"
        ]
        self.assertEqual(len(decode_calls), 1)
        decode = decode_calls[0]
        self.assertEqual(ast.unparse(decode.args[0]), "credentials.credentials")
        self.assertTrue(
            _payload_get_compare(
                current,
                key="type",
                operator_type=ast.NotEq,
                expected="platform_access",
            )
        )
        self.assertTrue(
            _payload_get_compare(
                current,
                key="is_platform_admin",
                operator_type=ast.IsNot,
                expected=True,
            )
        )
        select_platform_admin = [
            call for call in _calls(current, "select")
            if call.args
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id == "PlatformAdmin"
        ]
        self.assertEqual(len(select_platform_admin), 1)
        active_checks = [
            call for call in _calls(current, "is_")
            if isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Attribute)
            and isinstance(call.func.value.value, ast.Name)
            and call.func.value.value.id == "PlatformAdmin"
            and call.func.value.attr == "is_active"
            and len(call.args) == 1
            and isinstance(call.args[0], ast.Constant)
            and call.args[0].value is True
        ]
        self.assertEqual(len(active_checks), 1)
        self.assertTrue({
            "انتهت صلاحية جلسة مدير المنصة.",
            "توكن مدير المنصة غير صالح.",
            "حساب مدير المنصة غير متاح.",
        } <= current_strings)
        current_http_errors = [
            call for call in _calls(current, "HTTPException")
            if _keywords(call).get("status_code") is not None
        ]
        self.assertGreaterEqual(len(current_http_errors), 3)
        self.assertTrue(all(
            isinstance(_keywords(call)["status_code"], ast.Constant)
            and _keywords(call)["status_code"].value == 401
            for call in current_http_errors
        ))

        login = self.functions["platform_admin_login"]
        login_names = _name_references(login)
        rate_limit_calls = _calls(login, "_check_platform_login_limit")
        self.assertEqual(len(rate_limit_calls), 1)
        self.assertEqual([ast.unparse(arg) for arg in rate_limit_calls[0].args], ["ip", "db"])
        bcrypt_checks = [
            call for call in _calls(login, "checkpw")
            if isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "bcrypt"
        ]
        self.assertEqual(len(bcrypt_checks), 1)
        record_calls = _calls(login, "_record_platform_login")
        self.assertEqual(len(record_calls), 2)
        self.assertEqual(
            sorted(
                call.args[2].value
                for call in record_calls
                if len(call.args) >= 3 and isinstance(call.args[2], ast.Constant)
            ),
            [False, True],
        )
        encode_calls = [
            call for call in _calls(login, "encode")
            if isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "jwt"
        ]
        self.assertEqual(len(encode_calls), 1)
        token_payload = encode_calls[0].args[0]
        self.assertIsInstance(token_payload, ast.Dict)
        token_fields = {
            key.value: value
            for key, value in zip(token_payload.keys, token_payload.values)
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        self.assertEqual(token_fields["type"].value, "platform_access")
        self.assertIs(token_fields["is_platform_admin"].value, True)
        self.assertIn("PlatformAdmin", login_names)
        self.assertTrue(
            {"CompanyPrincipal", "CompanyOwner", "BackofficeUser"}.isdisjoint(login_names)
        )

        listing = self.functions["list_all_tenants"]
        listing_names = _name_references(listing)
        defaults = _parameter_defaults(listing)
        page_query = defaults["page"]
        page_size_query = defaults["page_size"]
        q_query = defaults["q"]
        self.assertEqual(ast.unparse(page_query.func), "Query")
        self.assertEqual(_keywords(page_query)["default"].value, 1)
        self.assertEqual(_keywords(page_query)["ge"].value, 1)
        self.assertEqual(_keywords(page_size_query)["default"].value, 20)
        self.assertEqual(_keywords(page_size_query)["ge"].value, 1)
        self.assertEqual(_keywords(page_size_query)["le"].value, 100)
        self.assertIsNone(_keywords(q_query)["default"].value)
        self.assertEqual(_keywords(q_query)["min_length"].value, 1)
        self.assertEqual(_keywords(q_query)["max_length"].value, 100)

        platform_default = defaults["_platform_admin"]
        self.assertEqual(ast.unparse(platform_default.func), "Depends")
        self.assertEqual(ast.unparse(platform_default.args[0]), "get_current_platform_admin")
        platform_arg = next(arg for arg in listing.args.args if arg.arg == "_platform_admin")
        self.assertEqual(ast.unparse(platform_arg.annotation), "PlatformAdmin")

        ilike_calls = _calls(listing, "ilike")
        ilike_owners = {
            ast.unparse(call.func.value)
            for call in ilike_calls
            if isinstance(call.func, ast.Attribute)
        }
        self.assertEqual(ilike_owners, {"Company.name", "Company.company_code"})

        order_calls = _calls(listing, "order_by")
        self.assertEqual(len(order_calls), 1)
        self.assertEqual(
            [ast.unparse(arg) for arg in order_calls[0].args],
            ["Company.created_at.desc()", "Company.id.desc()"],
        )
        offset_calls = _calls(listing, "offset")
        limit_calls = _calls(listing, "limit")
        self.assertEqual(len(offset_calls), 1)
        self.assertEqual(len(limit_calls), 1)
        self.assertEqual(ast.unparse(offset_calls[0].args[0]), "(page - 1) * page_size")
        self.assertEqual(ast.unparse(limit_calls[0].args[0]), "page_size")

        returns = [node for node in ast.walk(listing) if isinstance(node, ast.Return)]
        self.assertEqual(len(returns), 1)
        self.assertIsInstance(returns[0].value, ast.Dict)
        response_keys = {
            key.value
            for key in returns[0].value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        self.assertEqual(response_keys, {"items", "total", "page", "page_size", "pages"})
        self.assertTrue(
            {"CompanyPrincipal", "CompanyOwner", "BackofficeUser"}.isdisjoint(listing_names)
        )


if __name__ == "__main__":
    unittest.main()
