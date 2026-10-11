"""Dependency-free source guards for the temporary legacy transport adapter."""
import ast
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "api" / "authentication" / "legacy_field_transport.py"


class LegacyFieldTransportBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.source = SOURCE.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.names = {node.id for node in ast.walk(self.tree) if isinstance(node, ast.Name)}
        self.attributes = {node.attr for node in ast.walk(self.tree) if isinstance(node, ast.Attribute)}

    def test_no_legacy_flag_migration_label_or_role_authority(self):
        self.assertNotIn("is_admin", self.source)
        self.assertNotIn("classification", self.source)
        self.assertTrue(self.attributes.isdisjoint({"role", "roles", "capabilities"}))

    def test_no_jwt_decoder_or_direct_repeat_of_upstream_authentication(self):
        self.assertTrue(self.names.isdisjoint({"jwt", "decode_company_token", "_decode_access_token",
                                              "credentials", "claims", "token", "HTTPBearer"}))
        self.assertTrue(self.attributes.isdisjoint({"decode", "decode_company_token"}))
        self.assertFalse(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                             and node.func.id == "get_current_driver" for node in ast.walk(self.tree)))
        self.assertFalse(any(isinstance(node, ast.ImportFrom) and "codec" in (node.module or "")
                             for node in ast.walk(self.tree)))

    def test_no_transaction_write_or_tenant_establishment_operations(self):
        self.assertTrue(self.attributes.isdisjoint({"commit", "rollback", "begin", "begin_nested", "flush",
                                                   "add", "add_all", "delete", "update", "connection", "in_transaction"}))
        self.assertTrue(self.names.isdisjoint({"insert", "update", "delete", "tenant_context"}))

    def test_transport_dependency_is_exact_and_cache_is_enabled(self):
        imports = [node for node in ast.walk(self.tree) if isinstance(node, ast.ImportFrom)]
        legacy_import = next(node for node in imports if node.module == "api.dependencies")
        self.assertEqual([alias.name for alias in legacy_import.names], ["get_current_driver"])
        canonical_import = next(node for node in imports if node.level == 1 and node.module == "dependencies")
        self.assertEqual([alias.name for alias in canonical_import.names], ["_authentication_rejected"])
        dependency = next(node for node in self.tree.body if isinstance(node, ast.AsyncFunctionDef)
                          and node.name == "get_legacy_transport_field_context")
        self.assertEqual([arg.arg for arg in dependency.args.args], ["current_driver", "db"])
        self.assertEqual([default.func.id for default in dependency.args.defaults], ["Depends", "Depends"])
        self.assertEqual([default.args[0].id for default in dependency.args.defaults], ["get_current_driver", "get_db"])
        self.assertFalse(any(default.keywords for default in dependency.args.defaults))


if __name__ == "__main__":
    unittest.main()
