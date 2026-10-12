from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "api" / "taxation.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
FUNCTIONS = {
    node.name: node
    for node in TREE.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}

READ_ONLY_ENDPOINTS = (
    "get_policy",
    "preview_tax",
    "list_jurisdictions",
    "list_rule_sets",
    "list_versions",
    "get_version",
    "validate_tax_version",
)

MUTATION_ENDPOINTS = (
    "add_jurisdiction",
    "edit_jurisdiction",
    "remove_jurisdiction",
    "add_rule_set",
    "edit_rule_set",
    "remove_rule_set",
    "add_version",
    "edit_version",
    "remove_version",
    "submit_tax_version",
    "publish_tax_version",
    "approve_tax_version",
    "cancel_tax_version_endpoint",
)


def _source(name: str) -> str:
    return ast.get_source_segment(SOURCE, FUNCTIONS[name]) or ""


def _parameter_default(function_name: str, parameter: str) -> ast.expr | None:
    function = FUNCTIONS[function_name]
    names = [item.arg for item in function.args.args]
    defaults = [None] * (len(names) - len(function.args.defaults)) + list(
        function.args.defaults
    )
    return dict(zip(names, defaults, strict=True))[parameter]


def _assert_depends(
    case: unittest.TestCase,
    function_name: str,
    parameter: str,
    dependency_name: str,
) -> None:
    default = _parameter_default(function_name, parameter)
    case.assertIsInstance(default, ast.Call, function_name)
    case.assertIsInstance(default.func, ast.Name, function_name)
    case.assertEqual(default.func.id, "Depends", function_name)
    case.assertEqual(len(default.args), 1, function_name)
    case.assertIsInstance(default.args[0], ast.Name, function_name)
    case.assertEqual(default.args[0].id, dependency_name, function_name)


class TaxationCanonicalAuthorizationCutoverTests(unittest.TestCase):
    def test_source_has_zero_legacy_request_authority(self):
        for forbidden in (
            "get_current_driver",
            "get_current_admin",
            "InventoryAccess",
            ".is_admin",
            "actor.company_id",
            "legacy_actor.company_id",
        ):
            self.assertNotIn(forbidden, SOURCE)
        self.assertIn("get_current_backoffice_capability_access", SOURCE)
        self.assertIn("get_current_backoffice_legacy_driver", SOURCE)
        self.assertIn("BackofficeCapabilityAccess", SOURCE)

    def test_every_tax_route_uses_canonical_backoffice_access(self):
        for endpoint in (*READ_ONLY_ENDPOINTS, *MUTATION_ENDPOINTS):
            _assert_depends(
                self,
                endpoint,
                "access",
                "get_current_backoffice_capability_access",
            )

    def test_only_mutations_load_legacy_driver(self):
        for endpoint in READ_ONLY_ENDPOINTS:
            names = [item.arg for item in FUNCTIONS[endpoint].args.args]
            self.assertNotIn("legacy_actor", names, endpoint)
        for endpoint in MUTATION_ENDPOINTS:
            _assert_depends(
                self,
                endpoint,
                "legacy_actor",
                "get_current_backoffice_legacy_driver",
            )

    def test_exact_tax_capability_mapping_is_preserved(self):
        for endpoint in READ_ONLY_ENDPOINTS:
            self.assertIn('await _require(access, "tax.view")', _source(endpoint))
        for endpoint in (
            "add_jurisdiction",
            "edit_jurisdiction",
            "remove_jurisdiction",
            "add_rule_set",
            "edit_rule_set",
            "remove_rule_set",
            "add_version",
            "edit_version",
            "remove_version",
        ):
            self.assertIn('await _require(access, "tax.manage")', _source(endpoint))

        command_source = _source("_version_command")
        self.assertIn(
            'permission = "tax.approve" if action == "approve" else "tax.manage"',
            command_source,
        )
        self.assertIn("await _require(access, permission)", command_source)

    def test_require_preserves_any_location_and_fail_closed_contract(self):
        source = _source("_require")
        self.assertIn("await access.require(permission, any_location=True)", source)
        self.assertIn("except BackofficeCapabilityAccessRejected:", source)
        self.assertIn(
            'raise HTTPException(403, detail="Authorization denied.") from None',
            source,
        )

    def test_tenant_authority_is_canonical_and_legacy_actor_is_id_only(self):
        legacy_attributes = {
            node.attr
            for node in ast.walk(TREE)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "legacy_actor"
        }
        self.assertEqual(legacy_attributes, {"id"})

        protected_keywords = {"company_id": ("access", "company_id")}
        for node in ast.walk(TREE):
            if not isinstance(node, ast.keyword) or node.arg not in protected_keywords:
                continue
            expected_object, expected_attribute = protected_keywords[node.arg]
            self.assertIsInstance(node.value, ast.Attribute, ast.unparse(node))
            self.assertIsInstance(node.value.value, ast.Name, ast.unparse(node))
            self.assertEqual(node.value.value.id, expected_object, ast.unparse(node))
            self.assertEqual(node.value.attr, expected_attribute, ast.unparse(node))

        for keyword_name in ("actor_id", "admin_id"):
            for node in ast.walk(TREE):
                if not isinstance(node, ast.keyword) or node.arg != keyword_name:
                    continue
                self.assertIsInstance(node.value, ast.Attribute, ast.unparse(node))
                self.assertIsInstance(node.value.value, ast.Name, ast.unparse(node))
                self.assertEqual(node.value.value.id, "legacy_actor", ast.unparse(node))
                self.assertEqual(node.value.attr, "id", ast.unparse(node))

    def test_mutation_transaction_and_idempotency_shape_is_preserved(self):
        source = _source("_mutation")
        for expected in (
            "begin_idempotent_operation",
            "if replay is not None:",
            "await db.rollback()",
            "response = await fn()",
            "_audit(",
            "complete_idempotent_operation(record, response)",
            "await db.commit()",
            "except TaxError as exc:",
            "except InventoryMutationError as exc:",
            "except IntegrityError as exc:",
            "company_id=access.company_id",
            "actor_id=legacy_actor.id",
        ):
            self.assertIn(expected, source)

    def test_audit_uses_canonical_company_and_legacy_driver_provenance(self):
        source = _source("_audit")
        self.assertIn("company_id=access.company_id", source)
        self.assertIn("admin_id=legacy_actor.id", source)


if __name__ == "__main__":
    unittest.main()
