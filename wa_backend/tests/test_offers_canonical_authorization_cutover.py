"""Focused Offers canonical authorization cutover acceptance."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

SOURCE = Path(__file__).resolve().parents[1] / "api" / "offers.py"

ROUTE_CAPABILITIES = {
    "get_policy": "offers.view",
    "list_reference_variants": "catalog.read",
    "resolve_reference_variants": "catalog.read",
    "list_definitions": "offers.view",
    "add_definition": "offers.manage",
    "edit_definition": "offers.manage",
    "remove_definition": "offers.manage",
    "list_versions": "offers.view",
    "get_version": "offers.view",
    "add_version": "offers.manage",
    "edit_version": "offers.manage",
    "remove_version": "offers.manage",
    "preview_basket": "offers.view",
    "validate_offer_version": "offers.view",
    "submit": "offers.manage",
    "publish": "offers.manage",
    "approve": "offers.approve",
    "cancel": "offers.manage",
}

PROVENANCE_ROUTES = {
    "add_definition", "edit_definition", "remove_definition",
    "add_version", "edit_version", "remove_version",
    "submit", "publish", "approve", "cancel",
}

ROUTE_CONTRACTS = {
    "get_policy": ("get", "/policy", None),
    "list_reference_variants": ("get", "/references/variants", None),
    "resolve_reference_variants": ("post", "/references/variants/resolve", None),
    "list_definitions": ("get", "/definitions", None),
    "add_definition": ("post", "/definitions", 201),
    "edit_definition": ("patch", "/definitions/{definition_id}", None),
    "remove_definition": ("delete", "/definitions/{definition_id}", None),
    "list_versions": ("get", "/definitions/{definition_id}/versions", None),
    "get_version": ("get", "/versions/{version_id}", None),
    "add_version": ("post", "/definitions/{definition_id}/versions", 201),
    "edit_version": ("put", "/versions/{version_id}", None),
    "remove_version": ("delete", "/versions/{version_id}", None),
    "preview_basket": ("post", "/preview", None),
    "validate_offer_version": ("post", "/versions/{version_id}/validate", None),
    "submit": ("post", "/versions/{version_id}/submit", None),
    "publish": ("post", "/versions/{version_id}/publish", None),
    "approve": ("post", "/versions/{version_id}/approve", None),
    "cancel": ("post", "/versions/{version_id}/cancel", None),
}

OPERATIONS = {
    "OFFER_DEFINITION_CREATE", "OFFER_DEFINITION_UPDATE", "OFFER_DEFINITION_DELETE",
    "OFFER_VERSION_CREATE", "OFFER_VERSION_UPDATE", "OFFER_VERSION_DELETE",
    "OFFER_VERSION_SUBMIT", "OFFER_VERSION_PUBLISH", "OFFER_VERSION_APPROVE",
    "OFFER_VERSION_CANCEL",
}


def _functions(tree):
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _route_decorator(node):
    for decorator in node.decorator_list:
        if (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.value.id == "router"
        ):
            return decorator
    return None


def _defaults(node):
    names = [arg.arg for arg in node.args.args]
    if not node.args.defaults:
        return {}
    return dict(zip(names[-len(node.args.defaults):], node.args.defaults))


def _keyword(call, name):
    return next(keyword.value for keyword in call.keywords if keyword.arg == name)


def _authorization(node):
    first = node.body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Await):
        call = first.value.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "_require":
            return ast.literal_eval(call.args[1])
    if isinstance(first, ast.Return) and isinstance(first.value, ast.Await):
        call = first.value.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "_command":
            return ast.literal_eval(_keyword(call, "permission"))
    raise AssertionError(f"No canonical authorization call at start of route {node.name}")


def _extract_require(namespace):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_require")
    node.decorator_list = []
    node.returns = None
    for arg in node.args.args:
        arg.annotation = None
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace["_require"]


class OffersCanonicalAuthorizationCutoverTests(unittest.TestCase):
    def setUp(self):
        self.source = SOURCE.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.functions = _functions(self.tree)
        self.routes = {
            name: node for name, node in self.functions.items()
            if _route_decorator(node) is not None
        }

    def test_zero_legacy_request_authority_and_no_manual_owner_shortcut(self):
        for forbidden in (
            "get_current_driver", "get_current_admin", "InventoryAccess", ".is_admin",
            "actor.company_id", "legacy_actor.company_id",
        ):
            self.assertNotIn(forbidden, self.source)
        self.assertNotIn("is_company_owner", self.source)
        self.assertIn("get_current_backoffice_capability_access", self.source)
        self.assertIn("get_current_backoffice_legacy_driver", self.source)

    def test_every_route_uses_cached_canonical_access_and_only_provenance_routes_load_driver(self):
        self.assertEqual(set(self.routes), set(ROUTE_CAPABILITIES))
        for name, node in self.routes.items():
            with self.subTest(route=name):
                args = {arg.arg: arg for arg in node.args.args}
                defaults = _defaults(node)
                self.assertNotIn("actor", args)
                self.assertEqual(ast.unparse(args["access"].annotation), "BackofficeCapabilityAccess")
                self.assertEqual(
                    ast.unparse(defaults["access"]),
                    "Depends(get_current_backoffice_capability_access)",
                )
                self.assertEqual("legacy_actor" in args, name in PROVENANCE_ROUTES)
                if name in PROVENANCE_ROUTES:
                    self.assertEqual(ast.unparse(args["legacy_actor"].annotation), "Driver")
                    self.assertEqual(
                        ast.unparse(defaults["legacy_actor"]),
                        "Depends(get_current_backoffice_legacy_driver)",
                    )

    def test_exact_route_capabilities_are_preserved(self):
        actual = {name: _authorization(node) for name, node in self.routes.items()}
        self.assertEqual(actual, ROUTE_CAPABILITIES)

    def test_http_route_methods_paths_and_status_codes_are_unchanged(self):
        for name, expected in ROUTE_CONTRACTS.items():
            with self.subTest(route=name):
                decorator = _route_decorator(self.routes[name])
                method = decorator.func.attr
                path = ast.literal_eval(decorator.args[0])
                status = None
                for keyword in decorator.keywords:
                    if keyword.arg == "status_code":
                        status = ast.literal_eval(keyword.value)
                self.assertEqual((method, path, status), expected)

    def test_tenant_authority_is_canonical_and_driver_is_provenance_id_only(self):
        for node in ast.walk(self.tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "legacy_actor"
            ):
                self.assertEqual(node.attr, "id")
        mutation = ast.unparse(self.functions["_mutation"])
        self.assertIn("company_id=access.company_id", mutation)
        self.assertIn("actor_id=legacy_actor.id", mutation)
        self.assertIn("_audit(db, access, legacy_actor", mutation)
        audit = ast.unparse(self.functions["_audit"])
        self.assertIn("company_id=access.company_id", audit)
        self.assertIn("admin_id=legacy_actor.id", audit)
        command = ast.unparse(self.functions["_command"])
        self.assertIn("'company_id': access.company_id", command)
        self.assertIn("kwargs['actor_id'] = legacy_actor.id", command)

    def test_existing_idempotency_transaction_and_command_behavior_is_retained(self):
        mutation = ast.unparse(self.functions["_mutation"])
        self.assertIn("begin_idempotent_operation", mutation)
        self.assertIn("complete_idempotent_operation(record, response)", mutation)
        self.assertEqual(mutation.count("await db.commit()"), 1)
        self.assertEqual(mutation.count("await db.rollback()"), 4)
        command = ast.unparse(self.functions["_command"])
        self.assertIn(
            "operation in {'OFFER_VERSION_PUBLISH', 'OFFER_VERSION_APPROVE', 'OFFER_VERSION_CANCEL'}",
            command,
        )
        self.assertIn("if operation == 'OFFER_VERSION_CANCEL'", command)
        present = {
            node.value for node in ast.walk(self.tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node.value in OPERATIONS
        }
        self.assertEqual(present, OPERATIONS)

    def test_existing_query_ordering_and_offer_service_calls_are_retained(self):
        source = self.source
        for fragment in (
            ".order_by(ProductVariant.id)",
            ".order_by(OfferDefinition.id)",
            ".order_by(OfferVersion.id)",
            ".order_by(OfferVersionScope.offer_version_id, OfferVersionScope.id)",
            ".order_by(OfferVersionProduct.offer_version_id, OfferVersionProduct.id)",
            "create_definition(", "update_definition(", "delete_definition(",
            "create_draft_version(", "update_draft_version(", "delete_draft_version(",
            "preview_offer_basket(", "validate_version(",
            "fn=submit_version", "fn=publish_version", "fn=approve_version", "fn=cancel_version",
        ):
            self.assertIn(fragment, source)


class OffersAuthorizationBoundaryExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejection_preserves_existing_403_contract(self):
        class Rejected(Exception):
            pass

        class HTTPError(Exception):
            def __init__(self, *, status_code, detail):
                self.status_code = status_code
                self.detail = detail

        require = _extract_require({
            "BackofficeCapabilityAccessRejected": Rejected,
            "HTTPException": HTTPError,
        })
        access = SimpleNamespace(require=AsyncMock(side_effect=Rejected("internal detail")))
        with self.assertRaises(HTTPError) as failure:
            await require(access, "offers.manage")
        self.assertEqual(failure.exception.status_code, 403)
        self.assertEqual(
            failure.exception.detail,
            "لا تملك صلاحية تنفيذ هذه العملية ضمن الموقع المحدد.",
        )
        access.require.assert_awaited_once_with("offers.manage", any_location=True)


if __name__ == "__main__":
    unittest.main()
