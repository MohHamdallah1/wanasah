"""Dependency-free canonical login response and source boundary checks."""
import ast
from dataclasses import dataclass
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest


BACKEND = Path(__file__).resolve().parents[1]
DASHBOARD_FIELDS = {
    "token", "refresh_token", "principal_id", "backoffice_user_id", "channel",
    "is_company_owner", "company_id", "company_code", "dashboard_access",
}
FIELD_FIELDS = {
    "token", "refresh_token", "principal_id", "representative_id", "channel",
    "company_id", "company_code",
}
# Main a0411978 with only the compatibility imports, reads and arguments removed.
# This freezes password/admission/rate-limit/session/transaction behavior for this cutover.
ORCHESTRATION_DIGEST = "954b9839f5156d68dbf367e8a6d2a3883427cc89f712aa8e3ac1d0862beaddaa"
UNCHANGED_DIGESTS = {
    "main.py": "c079aa0ede7da36bbedc001fa115875358e1b9a596f778e3d81818518f3cf842",
    "api/authentication/login_routes.py": "03bdb8570b67d3d8ebde4b6a72b92952174701e758a2ddbbcee1c1fcf283f2b4",
    "domains/identity/authentication.py": "4ae5599fc17dc48b6e243b8ca9f25d138d0ac10283f575af179725f231729bbd",
    "domains/auth_sessions/codec.py": "d49caa754f116d6da2ae97779f7121957b6ff64f9e745b9266d7d622ab421f0c",
    "domains/auth_sessions/claims.py": "106da81af01bddd982ae59f4498f3c5f22212204953b6ac084ac5bf3359f8509",
    "domains/auth_sessions/login_attempts.py": "887148028d11afe2aa94e9481874aabbc699803e8c22123f82c51a5d265db7fe",
    "domains/auth_sessions/refresh_sessions.py": "b4df8bef4ad2995f968c6dd3f31ab4ede4528d4e64dd1eaa7e373faef7b01fae",
}


def source(path):
    return (BACKEND / path).read_text(encoding="utf-8")


def tree(path):
    return ast.parse(source(path))


def ast_digest(node):
    # Empty generic-parameter fields were added in Python 3.12; ignore their
    # absence/presence so the baseline also works with Python 3.11.
    for part in ast.walk(node):
        if "type_params" in part._fields and not part.type_params:
            part._fields = tuple(field for field in part._fields if field != "type_params")
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def load_pure_builders():
    parsed = tree("api/authentication/login.py")
    names = {"LoginBoundaryRejected", "LoginCompanyContext", "_require_same_company",
             "build_dashboard_login_response", "build_field_login_response"}
    selected = [node for node in parsed.body
                if (isinstance(node, ast.ImportFrom) and node.module == "__future__")
                or (isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names)]
    namespace = dict(globals())
    # Execute the exact pure production definitions, including company validation.
    # Database imports are unnecessary for these response builders.
    exec(compile(ast.Module(body=selected, type_ignores=[]), "canonical_login_builders", "exec",
                 dont_inherit=True), namespace)
    return namespace


class GuardedIdentity(SimpleNamespace):
    @property
    def driver_id(self):
        raise AssertionError("A canonical response must not read an operational identity")

    @property
    def is_admin(self):
        raise AssertionError("A canonical response must not read an administrative flag")


class CanonicalLoginNoLegacyBoundaryTests(unittest.TestCase):
    def test_no_legacy_identity_mapping_or_boolean_authority_in_login_runtime(self):
        forbidden = {"Driver", "IdentityLegacyDriverMap", "LegacyLoginCompatibility",
                     "LegacyLoginCompatibilityMissing", "legacy_is_admin", "driver_id",
                     "driver_name", "is_admin", "role", "roles", "capabilities", "classification",
                     "compatibility", "require_dashboard_login_compatibility", "require_field_login_compatibility",
                     "load_dashboard_login_compatibility", "load_field_login_compatibility"}
        for filename in ("login.py", "login_orchestration.py", "login_routes.py", "schemas.py"):
            with self.subTest(module=filename):
                for node in ast.walk(tree("api/authentication/" + filename)):
                    if isinstance(node, ast.ImportFrom):
                        self.assertNotIn("legacy_compatibility", node.module or "")
                    if isinstance(node, ast.Name):
                        self.assertNotIn(node.id, forbidden)
                    if isinstance(node, ast.Attribute):
                        self.assertNotIn(node.attr, forbidden)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        self.assertNotIn(node.value, forbidden)

    def test_typed_and_strict_response_contracts_have_only_canonical_fields(self):
        for filename, dashboard_name, field_name in (
            ("login.py", "DashboardLoginResponse", "FieldLoginResponse"),
            ("schemas.py", "DashboardPrincipalLoginResponse", "FieldPrincipalLoginResponse"),
        ):
            classes = {node.name: node for node in tree("api/authentication/" + filename).body
                       if isinstance(node, ast.ClassDef)}
            for name, expected in ((dashboard_name, DASHBOARD_FIELDS), (field_name, FIELD_FIELDS)):
                fields = {node.target.id for node in classes[name].body if isinstance(node, ast.AnnAssign)}
                self.assertEqual(fields, expected)

    def test_builders_accept_no_mapping_argument_and_run_without_any_legacy_data(self):
        namespace = load_pure_builders()
        company = namespace["LoginCompanyContext"](7, "WNS-01")
        identity = GuardedIdentity(principal_id=101, company_id=7, backoffice_user_id=202,
                                   representative_id=303, is_company_owner=False)
        for name, fields, profile, value, channel in (
            ("build_dashboard_login_response", DASHBOARD_FIELDS, "backoffice_user_id", 202, "DASHBOARD"),
            ("build_field_login_response", FIELD_FIELDS, "representative_id", 303, "FIELD"),
        ):
            builder = namespace[name]
            response = builder(company=company, authentication=identity, access_token="a", refresh_token="r")
            self.assertEqual(set(response), fields)
            self.assertEqual((response["principal_id"], response[profile], response["channel"]), (101, value, channel))
            self.assertEqual((response["company_id"], response["company_code"]), (7, "WNS-01"))
            with self.assertRaises(TypeError):
                builder(company=company, authentication=identity, access_token="a", refresh_token="r", compatibility=None)
            with self.assertRaises(namespace["LoginBoundaryRejected"]):
                builder(company=namespace["LoginCompanyContext"](8, "OTHER"), authentication=identity,
                        access_token="a", refresh_token="r")

    def test_owner_response_uses_explicit_canonical_authentication_result(self):
        namespace = load_pure_builders()
        for owner in (True, False):
            identity = GuardedIdentity(principal_id=101, company_id=7, backoffice_user_id=202,
                                       is_company_owner=owner)
            response = namespace["build_dashboard_login_response"](
                company=namespace["LoginCompanyContext"](7, "WNS-01"), authentication=identity,
                access_token="a", refresh_token="r",
            )
            self.assertIs(response["is_company_owner"], owner)
            self.assertIs(response["dashboard_access"], True)

    def test_token_issuance_keeps_canonical_principal_subject_and_identity_claims(self):
        calls = [node for node in ast.walk(tree("api/authentication/login_orchestration.py"))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "issue_access_token"]
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual({item.arg: ast.unparse(item.value) for item in call.keywords}, {
                "principal_id": "identity.principal_id", "company_id": "identity.company_id",
                "channel": "identity.channel.value", "principal_type": "identity.principal_type.value",
                "auth_revision": "identity.auth_revision", "secret": "secret",
            })

    def test_orchestration_preserves_all_logic_outside_response_preparation(self):
        parsed = tree("api/authentication/login_orchestration.py")
        parsed.body = [node for node in parsed.body
                       if not isinstance(node, ast.ImportFrom) or node.module != "typing"]
        for function in parsed.body:
            if not isinstance(function, ast.AsyncFunctionDef) or function.name not in {
                "login_dashboard_principal", "login_field_principal"
            }:
                continue
            self.assertEqual(function.args.kwonlyargs[-1].arg, "prepare_response")
            self.assertIsNone(function.args.kw_defaults[-1].value)
            function.args.kwonlyargs.pop()
            function.args.kw_defaults.pop()
            preparation = adaptations = 0
            for block in (node for node in function.body if isinstance(node, ast.Try)):
                keep = []
                for node in block.body:
                    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) \
                            and node.targets[0].id == "response_adapter":
                        self.assertEqual(ast.unparse(node.value),
                                         "await prepare_response(db, identity) if prepare_response else None")
                        preparation += 1
                    elif isinstance(node, ast.If) and ast.unparse(node.test) == "response_adapter is not None":
                        self.assertEqual(ast.unparse(node.body[0]), "response = response_adapter(response)")
                        adaptations += 1
                    else:
                        keep.append(node)
                block.body = keep
            self.assertEqual((preparation, adaptations), (1, 1))
        # The approved hook is the only delta to the baseline orchestration body.
        self.assertEqual(ast_digest(parsed), ORCHESTRATION_DIGEST)

    def test_live_auth_mounts_only_canonical_backed_public_transport(self):
        parsed = tree("api/auth.py")
        modules = {node.module for node in parsed.body if isinstance(node, ast.ImportFrom)}
        self.assertEqual(modules, {"fastapi", "api.authentication.login_transport_routes",
                                  "api.authentication.logout_routes", "api.authentication.refresh_routes",
                                  "api.inventory_permissions"})
        includes = [ast.unparse(node.args[0]) for node in ast.walk(parsed)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "include_router"]
        self.assertEqual(includes, ["inventory_permissions_router", "login_router",
                                   "refresh_router", "logout_router"])
        self.assertFalse(any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                             for node in parsed.body))

    def test_live_mount_password_policy_tokens_and_refresh_sessions_are_unchanged(self):
        for path, expected in UNCHANGED_DIGESTS.items():
            with self.subTest(path=path):
                self.assertEqual(hashlib.sha256(source(path).encode()).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
