"""Focused Catalog canonical wiring and baseline business/HTTP-contract parity."""
import ast
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

SOURCE = Path(__file__).resolve().parents[1] / "api" / "catalog.py"
# Independently transformed from acd9ca5f0c2da588b6ae2a3f33202b914a61949b:
# actor.company_id -> access.company_id; actor.id -> legacy_actor.id;
# _require receives access; _audit receives access + mapped actor; lifecycle
# wrappers forward both; archive adapters receive access; recall reuses access.
# All schemas, route defaults/decorators, SQL/locks, lifecycle rules, idempotency,
# audit values and transaction/error nodes remain included. Only auth imports,
# auth parameters and the separately tested _require body are excluded.
BUSINESS_DIGEST = "752f438b95c97856de4f5722c9a8bce45730ab48b886b41228d539dd0f448806"
CAPABILITIES = {
    "list_uoms": "catalog.read", "list_products": "catalog.read",
    "list_variants": "catalog.read", "resolve_variants": "catalog.read",
    "list_conversions": "catalog.read", "list_barcodes": "catalog.read",
    "parse_gs1_endpoint": "catalog.read",
    "create_product": "catalog.manage", "update_product": "catalog.manage",
    "create_variant": "catalog.manage", "update_variant": "catalog.manage",
    "rename_variant_name": "catalog.manage", "reassign_variant_family": "catalog.manage",
    "create_conversion": "catalog.manage", "update_conversion": "catalog.manage",
    "create_barcode": "catalog.manage", "replace_variant_primary_barcode": "catalog.manage",
    "set_variant_package_barcode_independent": "catalog.manage",
    "update_barcode": "catalog.manage", "variant_delete_draft_preflight": "catalog.manage",
    "delete_draft_variant": "catalog.manage", "publish_variant": "catalog.publish",
    "retire_variant": "catalog.retire", "restore_variant": "catalog.restore",
    "variant_archive_preflight": "catalog.archive", "archive_variant": "catalog.archive",
    "variant_recall_readiness": "catalog.hold", "place_variant_sales_hold": "catalog.hold",
    "release_variant_sales_hold": "catalog.hold", "recall_variant_preflight": "catalog.hold",
    "recall_variant": "catalog.hold", "cancel_variant_recall": "catalog.hold",
    "close_variant_recall": "catalog.hold",
}
PROVENANCE_ROUTES = {
    "create_product", "update_product", "create_variant", "update_variant",
    "rename_variant_name", "reassign_variant_family", "create_conversion",
    "update_conversion", "create_barcode", "replace_variant_primary_barcode",
    "set_variant_package_barcode_independent", "update_barcode", "publish_variant",
    "delete_draft_variant", "retire_variant", "restore_variant", "archive_variant",
    "place_variant_sales_hold", "release_variant_sales_hold", "recall_variant",
    "cancel_variant_recall", "close_variant_recall",
}


def business_digest(tree):
    tree = copy.deepcopy(tree)
    ignored = {"api.authentication.backoffice_authorization",
               "api.authentication.backoffice_compatibility",
               "domains.authorization.backoffice_access"}
    tree.body = [n for n in tree.body
                 if not (isinstance(n, ast.ImportFrom) and n.module in ignored)
                 and not (isinstance(n, ast.AsyncFunctionDef) and n.name == "_require")]
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                node.decorator_list or node.name in {"_audit", "_run_variant_state_command"}):
            args = node.args
            defaults = dict(zip([a.arg for a in args.args][-len(args.defaults):],
                                args.defaults)) if args.defaults else {}
            args.args = [a for a in args.args if a.arg not in {"access", "legacy_actor"}]
            args.defaults = [defaults[a.arg] for a in args.args if a.arg in defaults]
            pairs = [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults)
                     if a.arg not in {"access", "legacy_actor"}]
            args.kwonlyargs = [a for a, d in pairs]
            args.kw_defaults = [d for a, d in pairs]
    # Ignore only empty Python 3.12 declaration metadata, retaining real generics.
    for node in ast.walk(tree):
        if getattr(node, "type_params", None) == []:
            del node.type_params
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


def extract(name, namespace):
    node = next(n for n in ast.parse(SOURCE.read_text(encoding="utf-8")).body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    node.decorator_list = []
    node.args.defaults = []
    node.args.kw_defaults = [None] * len(node.args.kwonlyargs)
    node.returns = None
    for arg in node.args.args + node.args.kwonlyargs:
        arg.annotation = None
    tree = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(tree, str(SOURCE), "exec"), namespace)
    return namespace[name]


class CatalogCanonicalBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.source = SOURCE.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.functions = {n.name: n for n in self.tree.body
                          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def test_no_legacy_auth_tenant_flag_or_token_authority(self):
        for forbidden in ("get_current_driver", "get_current_admin", "InventoryAccess",
                          ".is_admin", "actor.company_id", "legacy_backoffice_transport"):
            self.assertNotIn(forbidden, self.source)
        imports = {n.module for n in self.tree.body if isinstance(n, ast.ImportFrom)}
        self.assertNotIn("api.dependencies", imports)
        self.assertFalse(any("jwt" in str(name).lower() for name in imports))
        for forbidden in ("jwt.decode", "decode_company_token", "_decode_access_token"):
            self.assertFalse(forbidden in self.source, forbidden)

    def test_all_33_routes_use_cached_canonical_access_and_only_22_need_driver(self):
        routes = {name: n for name, n in self.functions.items() if n.decorator_list}
        self.assertEqual(set(routes), set(CAPABILITIES))
        for name, node in routes.items():
            with self.subTest(route=name):
                args = {a.arg: a for a in node.args.args}
                defaults = dict(zip([a.arg for a in node.args.args][-len(node.args.defaults):],
                                    node.args.defaults))
                self.assertEqual(ast.unparse(args["access"].annotation), "BackofficeCapabilityAccess")
                self.assertEqual(ast.unparse(defaults["access"]),
                                 "Depends(get_current_backoffice_capability_access)")
                self.assertEqual(defaults["access"].keywords, [])
                self.assertEqual("legacy_actor" in args, name in PROVENANCE_ROUTES)
                if name in PROVENANCE_ROUTES:
                    self.assertEqual(ast.unparse(args["legacy_actor"].annotation), "Driver")
                    self.assertEqual(ast.unparse(defaults["legacy_actor"]),
                                     "Depends(get_current_backoffice_legacy_driver)")
                    self.assertEqual(defaults["legacy_actor"].keywords, [])
                self.assertNotIn("actor", args)

    def test_exact_catalog_capabilities_and_any_location_http_denial(self):
        for name, expected in CAPABILITIES.items():
            node = self.functions[name]
            call = node.body[0].value.value
            if call.func.id == "_require":
                self.assertEqual([ast.unparse(a) for a in call.args], ["access", repr(expected)])
            else:
                self.assertEqual(call.func.id, "_run_variant_state_command")
                self.assertEqual(next(k.value.value for k in call.keywords if k.arg == "permission"),
                                 expected)
        helper = self.functions["_require"]
        self.assertEqual(ast.unparse(helper.body[0].body[0]),
                         "await access.require(permission, any_location=True)")
        self.assertEqual(helper.body[0].handlers[0].type.id, "BackofficeCapabilityAccessRejected")
        self.assertIn("status_code=403", ast.unparse(helper))
        self.assertNotIn("is_company_owner", self.source)

    def test_driver_values_are_only_existing_provenance_ids(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "legacy_actor":
                    self.assertEqual(node.attr, "id")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "begin_idempotent_operation":
                    values = {k.arg: ast.unparse(k.value) for k in node.keywords}
                    self.assertEqual(values["company_id"], "access.company_id")
                    self.assertEqual(values["actor_id"], "legacy_actor.id")
                if node.func.id == "_audit":
                    self.assertEqual([ast.unparse(a) for a in node.args[:3]],
                                     ["db", "access", "legacy_actor"])
        audit = ast.unparse(self.functions["_audit"])
        self.assertIn("company_id=access.company_id", audit)
        self.assertIn("admin_id=legacy_actor.id", audit)

    def test_archive_adapters_receive_same_canonical_access_and_recall_scope_is_retained(self):
        archive = self.functions["variant_archive_preflight"]
        calls = [n for n in ast.walk(archive) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id.endswith("_archive_targets")]
        self.assertEqual({c.func.id for c in calls},
                         {"inventory_archive_targets", "dispatch_archive_targets",
                          "operations_archive_targets"})
        for call in calls:
            self.assertEqual([ast.unparse(a) for a in call.args],
                             ["db", "access", "variant_id", "blockers"])
        recall = ast.unparse(self.functions["variant_recall_readiness"])
        self.assertIn("access.allows('inventory.read', any_location=True)", recall)
        self.assertIn("readable_location_filter=access.location_filter('inventory.read')", recall)

    def test_complete_baseline_business_sql_locking_idempotency_and_contract_parity(self):
        self.assertEqual(business_digest(self.tree), BUSINESS_DIGEST)


class CatalogLocalBoundaryExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_require_maps_rejection_without_transaction_or_identity_reads(self):
        class Rejected(Exception):
            pass
        class HTTPError(Exception):
            def __init__(self, *, status_code, detail):
                self.status_code, self.detail = status_code, detail
        require = extract("_require", {"BackofficeCapabilityAccessRejected": Rejected,
                                      "HTTPException": HTTPError})
        access = SimpleNamespace(require=AsyncMock(side_effect=Rejected("internal DB detail")))
        with self.assertRaises(HTTPError) as failure:
            await require(access, "catalog.manage")
        self.assertEqual(failure.exception.status_code, 403)
        self.assertEqual(failure.exception.detail,
                         "لا تملك صلاحية تنفيذ هذه العملية ضمن الموقع المحدد.")
        access.require.assert_awaited_once_with("catalog.manage", any_location=True)

    async def test_audit_uses_only_mapped_id_and_canonical_tenant(self):
        class OperationalActor:
            id = 303
            def __getattr__(self, name):
                raise AssertionError("Unexpected operational actor read: " + name)
        audit = extract("_audit", {"SystemAuditLog": lambda **values: values, "json": json})
        db = SimpleNamespace(add=Mock())
        audit(db, SimpleNamespace(company_id=7), OperationalActor(), "Product_42",
              "CATALOG_PRODUCT_UPDATED", {"version": 1}, {"version": 2})
        values = db.add.call_args.args[0]
        self.assertEqual((values["company_id"], values["admin_id"]), (7, 303))
        self.assertEqual(json.loads(values["old_value"]), {"version": 1})
        self.assertEqual(json.loads(values["new_value"]), {"version": 2})


if __name__ == "__main__":
    unittest.main()
