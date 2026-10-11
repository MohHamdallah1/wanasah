"""Dependency-free authority and transaction boundary regression gates."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


MODULE_PATH = (Path(__file__).resolve().parents[1] / "api" / "authentication"
               / "field_compatibility.py")


class CanonicalFieldRuntimeCompatibilityBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        self.attributes = {node.attr for node in ast.walk(self.tree) if isinstance(node, ast.Attribute)}
        self.names = {node.id for node in ast.walk(self.tree) if isinstance(node, ast.Name)}
        self.imports = [node for node in ast.walk(self.tree) if isinstance(node, ast.ImportFrom)]

    def test_no_legacy_boolean_role_or_bridge_classification_authority(self):
        forbidden = {"is_admin", "classification", "role", "roles", "capabilities"}
        self.assertTrue(self.attributes.isdisjoint(forbidden))
        self.assertTrue(self.names.isdisjoint(forbidden | {"IdentityLegacyDriverMap"}))
        self.assertFalse(any(node.module == "api.dependencies" for node in self.imports))

    def test_no_jwt_decoding_or_parallel_authentication_boundary(self):
        forbidden = {"jwt", "decode", "decode_company_token", "_decode_access_token",
                     "HTTPBearer", "HTTPAuthorizationCredentials", "credentials", "claims", "token"}
        self.assertTrue(self.names.isdisjoint(forbidden))
        self.assertTrue(self.attributes.isdisjoint(forbidden))
        self.assertFalse(any("codec" in (node.module or "") for node in self.imports))

    def test_no_transaction_or_persistence_mutation(self):
        self.assertTrue(self.attributes.isdisjoint({
            "commit", "rollback", "begin", "begin_nested", "flush", "add", "add_all",
            "delete", "connection", "in_transaction",
        }))

    def test_only_canonical_field_dependency_and_subject_resolver_are_imported(self):
        imports = {node.module: {alias.name for alias in node.names} for node in self.imports}
        self.assertEqual(imports["dependencies"],
                         {"_authentication_rejected", "get_current_field_context"})
        self.assertEqual(imports["domains.authorization.field_subject"],
                         {"resolve_field_authorization_subject"})
        self.assertEqual(imports["domains.auth_sessions.context"], {"FieldRequestContext"})
        self.assertEqual(imports["database"], {"get_db"})


if __name__ == "__main__":
    unittest.main()
