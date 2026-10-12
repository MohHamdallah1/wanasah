"""Dependency-free canonical Live Stock authority and business-body parity gate."""
import ast
import copy
import hashlib
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "api" / "warehouse" / "live_stock.py"
# Independently derived from 0813f28e28138f37d530b1d5a363edfac4fbc518.
# Only approved auth wiring differs: injected access replaces the legacy access
# constructor/company source, the warehouse guard drops its actor shortcut,
# and any-location rejections are translated at the local HTTP boundary.
# The Owner-only missing-warehouse detail preserves the old batch-product error.
# All SQL, quantity, status, readiness, ordering, cursor and transaction nodes
# remain included. Ignore only absent-versus-empty Python 3.11/3.12 type_params.
BODY_DIGESTS = {
    "_require_live_stock_read_model_ready": "4e79e8aaa6a49fbaae703e47ed0615563d83eba3e480dd126e369794fa2df5b1",
    "_readable_vehicle_locations_subquery": "8e7864d244a7dd263ff15f8960baeec5fe986a7438025ed3549521db8485f441",
    "_latest_readable_vehicle_sources_subquery": "74759a49d7c96c530a236195e91b9dd4413f4c003b17a9104c1128e0aa3e3e1d",
    "_require_live_stock_warehouse_read": "cac05ab4c68aafd9a779076d4e9049ff75c0d368c01453780f4c2a927e225461",
    "_live_stock_ordering": "820432500e5451c46b4db5892602b9257f28ca011c650b3b751c8c4c13e90970",
    "_display_uom_one_subquery": "826bebeb6fa7dc18c3a6c9c85656fb6ad5cdc67828d83b116ccbfb3abd6f609a",
    "_build_visible_inventory_stmt": "d01929ff3e75e78aaa2bf8abb3622ebd687ddf2f46464b5355a7bded156077d3",
    "_build_inventory_alert_variants_stmt": "1b8d1e12fa4d47adc7eca5054b8f200a88f8d968157b1dd80563f72697a14e73",
    "_live_stock_filtered_variant_ids_stmt": "4ef8ee47dab0d4a56b9f5a1578014307cd9626aea7abe1cab9beb6a0824c7523",
    "get_warehouse_inventory_alert_summary": "fbe3b1a8e4cac7d528c346d8bd82ce6059adf43fda6d4afd2e21c0c30bc50609",
    "get_warehouse_inventory_summary": "6eb5aba33248272a158f5e2d267196d70907fa21deb9597a45baedbd9ddf6705",
    "get_warehouse_inventory_families": "503e7a46234da259ea6cfe499b66a91b8536ae9665af495937be241e517ea39a",
    "get_warehouse_inventory_batch_products": "f6bfee27786853d1cd459d1b364439a81eba046fbfdedae7ec965ab1f3d852f8",
    "get_warehouse_inventory": "c8b7a0071db8be55fa7c877938433f59e4d1f9bafffcb22e4cd450995d42a6ee",
    "get_warehouse_inventory_batches": "d54107ad68fb0b2ed3ec7d40b394cfddc069e0b740665f6255a5fcf70f47c3fd",
    "get_quality_batch_candidates": "dbb77198a3646598e08488b36eabb33bd50118746a191b108db3f23e0cb7f95a",
    "get_whole_product_quality_issue_sources": "ed1dfcdedef07f94acfb29c084cf76c7a7062599da39df6d3dca77f3308ac474",
    "get_batch_stock_sources": "3c5afe3ba07b71ce1535af807148c3756f07f6cd6a053597424d204a6ab2c45e"
}
ENDPOINTS = [
    "get_batch_stock_sources",
    "get_quality_batch_candidates",
    "get_warehouse_inventory",
    "get_warehouse_inventory_alert_summary",
    "get_warehouse_inventory_batch_products",
    "get_warehouse_inventory_batches",
    "get_warehouse_inventory_families",
    "get_warehouse_inventory_summary",
    "get_whole_product_quality_issue_sources"
]


def digest(nodes):
    tree = copy.deepcopy(ast.Module(body=nodes, type_ignores=[]))
    for node in ast.walk(tree):
        if getattr(node, "type_params", None) == []:
            del node.type_params
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


class LiveStockCanonicalBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.source = SOURCE.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.functions = {node.name: node for node in self.tree.body
                          if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def test_zero_legacy_authentication_actor_or_flag_authority(self):
        for forbidden in ("get_current_driver", "get_current_admin", ".is_admin",
                          "legacy_actor", "legacy_backoffice_transport", "InventoryAccess"):
            self.assertNotIn(forbidden, self.source)
        names = {node.id for node in ast.walk(self.tree) if isinstance(node, ast.Name)}
        self.assertNotIn("Driver", names)
        imports = {node.module: [alias.name for alias in node.names]
                   for node in self.tree.body if isinstance(node, ast.ImportFrom)}
        self.assertNotIn("api.dependencies", imports)
        self.assertNotIn("Driver", imports["models"])
        self.assertEqual(imports["api.authentication.backoffice_authorization"],
                         ["get_current_backoffice_capability_access"])

    def test_all_nine_endpoints_use_the_existing_cached_canonical_dependency(self):
        actual = {name for name, node in self.functions.items() if node.decorator_list}
        self.assertEqual(actual, set(ENDPOINTS))
        for name in ENDPOINTS:
            with self.subTest(endpoint=name):
                node = self.functions[name]
                args = {arg.arg: arg for arg in node.args.args}
                defaults = dict(zip([arg.arg for arg in node.args.args][-len(node.args.defaults):],
                                    node.args.defaults))
                self.assertEqual(args["access"].annotation.id, "BackofficeCapabilityAccess")
                self.assertEqual(ast.unparse(defaults["access"]),
                                 "Depends(get_current_backoffice_capability_access)")
                self.assertEqual(defaults["access"].keywords, [])
                self.assertNotIn("current_admin", args)
                access_reads = [part for part in ast.walk(node)
                                if isinstance(part, ast.Attribute)
                                and isinstance(part.value, ast.Name) and part.value.id == "access"
                                and part.attr == "company_id"]
                self.assertEqual(len(access_reads), 1)

    def test_all_original_business_bodies_and_query_builders_preserved(self):
        self.assertEqual(set(self.functions), set(BODY_DIGESTS) |
                         {"_require_live_stock_any_location_read"})
        for name, expected in BODY_DIGESTS.items():
            with self.subTest(function=name):
                body = self.functions[name].body
                if name == "_require_live_stock_warehouse_read":
                    body = body[1:]  # Auth-boundary explanatory docstring only.
                self.assertEqual(digest(body), expected)

    def test_warehouse_structural_checks_precede_permission_queries_and_owner_error_formatting(self):
        node = self.functions["_require_live_stock_warehouse_read"]
        statements = node.body[1:]
        self.assertEqual(statements[0].targets[0].id, "location_exists")
        existence = ast.unparse(statements[0])
        for invariant in ("InventoryLocation.company_id == company_id",
                          "InventoryLocation.id == location_id",
                          "InventoryLocation.location_type == 'WAREHOUSE'",
                          "InventoryLocation.is_active.is_(True)"):
            self.assertIn(invariant, existence)
        self.assertEqual(ast.unparse(statements[1].test), "location_exists is None")
        self.assertIn("status_code=404", ast.unparse(statements[1]))
        self.assertEqual(statements[2].targets[0].id, "permission_row")
        self.assertIn("access.allows('inventory.read', location_id)", ast.unparse(statements[2]))
        self.assertIn("access.allows('inventory.read')", ast.unparse(statements[2]))
        # Canonical Owner state only selects the already-required 404 payload.
        owner_reads = [part for part in ast.walk(node)
                       if isinstance(part, ast.Attribute) and part.attr == "is_company_owner"]
        self.assertEqual(len(owner_reads), 1)
        self.assertIn(owner_reads[0], list(ast.walk(statements[1])))
        self.assertFalse(any(isinstance(part, ast.Return) for statement in statements[:4]
                             for part in ast.walk(statement)))

    def test_any_location_preserves_capability_and_http_rejection_contract(self):
        node = self.functions["_require_live_stock_any_location_read"]
        self.assertEqual(ast.unparse(node.body[1].body[0]),
                         "await access.require('inventory.read', any_location=True)")
        handler = node.body[1].handlers[0]
        self.assertEqual(handler.type.id, "BackofficeCapabilityAccessRejected")
        self.assertIn("status_code=403", ast.unparse(handler))
        for name in ("get_quality_batch_candidates", "get_whole_product_quality_issue_sources",
                     "get_batch_stock_sources"):
            calls = [part for part in ast.walk(self.functions[name])
                     if isinstance(part, ast.Call) and isinstance(part.func, ast.Name)
                     and part.func.id == "_require_live_stock_any_location_read"]
            self.assertEqual(len(calls), 1, name)

    def test_capability_mapping_retains_existing_read_and_action_codes(self):
        codes = {part.args[0].value for part in ast.walk(self.tree)
                 if isinstance(part, ast.Call) and isinstance(part.func, ast.Attribute)
                 and isinstance(part.func.value, ast.Name) and part.func.value.id == "access"
                 and part.func.attr in {"allows", "require", "location_filter"}
                 and part.args and isinstance(part.args[0], ast.Constant)}
        self.assertEqual(codes, {"inventory.read", "transfer.send",
                                "inventory.vendor_return.confirm", "inventory.disposal.confirm"})


if __name__ == "__main__":
    unittest.main()
