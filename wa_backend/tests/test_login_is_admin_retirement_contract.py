from __future__ import annotations

import ast
from pathlib import Path
import unittest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
TRANSPORT = BACKEND / "api" / "authentication" / "login_transport.py"
LEGACY = BACKEND / "domains" / "identity" / "legacy_compatibility.py"
SCHEMAS = BACKEND / "schemas.py"
LOGIN_TSX = ROOT / "dashboard" / "src" / "pages" / "Login.tsx"


def classes(path: Path) -> dict[str, ast.ClassDef]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    return {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}


class LoginIsAdminRetirementContractTests(unittest.TestCase):
    def test_dashboard_transport_has_no_is_admin_alias(self):
        source = TRANSPORT.read_text(encoding="utf-8-sig")
        contract = classes(TRANSPORT)["DashboardLoginTransportResponse"]
        fields = {
            node.target.id
            for node in contract.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        self.assertNotIn("is_admin", fields)
        self.assertNotIn("is_admin", source)
        self.assertIn("legacy_driver_id=legacy_driver_id", source)
        self.assertIn("driver_id=legacy_driver_id", source)

    def test_field_transport_has_no_is_admin_false_alias(self):
        source = TRANSPORT.read_text(encoding="utf-8-sig")
        contract = classes(TRANSPORT)["FieldLoginTransportResponse"]
        fields = {
            node.target.id
            for node in contract.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        self.assertNotIn("is_admin", fields)
        self.assertNotIn("is_admin", source)
        self.assertIn("dashboard_access: Literal[False] = False", source)

    def test_legacy_compatibility_never_reads_or_returns_driver_is_admin(self):
        source = LEGACY.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertNotIn("is_admin", attrs)
        self.assertNotIn("legacy_is_admin", source)
        self.assertIn("Driver.id", source)
        self.assertIn("Driver.company_id", source)
        self.assertIn("Driver.full_name", source)

    def test_dead_root_login_response_is_removed_and_has_no_runtime_importer(self):
        schema_classes = classes(SCHEMAS)
        self.assertNotIn("LoginResponse", schema_classes)
        offenders = []
        for path in BACKEND.rglob("*.py"):
            if "tests" in path.parts or "perf_reports" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "schemas":
                    if any(alias.name == "LoginResponse" for alias in node.names):
                        offenders.append(str(path.relative_to(ROOT)))
                if (
                    isinstance(node, ast.Attribute)
                    and node.attr == "LoginResponse"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "schemas"
                ):
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_dashboard_client_uses_canonical_admission_and_owner_navigation(self):
        source = LOGIN_TSX.read_text(encoding="utf-8-sig")
        self.assertNotIn("is_admin", source)
        self.assertIn("if (data.dashboard_access !== true)", source)
        self.assertIn("navigate(data.is_company_owner ? '/' : '/inventory');", source)
        for field in ("is_company_owner", "dashboard_access", "principal_id", "backoffice_user_id"):
            self.assertIn(f"{field}:", source)

    def test_driver_id_client_compatibility_remains(self):
        source = LOGIN_TSX.read_text(encoding="utf-8-sig")
        self.assertIn("driver_id: number;", source)
        self.assertIn("localStorage.setItem('driver_id', String(data.driver_id));", source)


if __name__ == "__main__":
    unittest.main()
