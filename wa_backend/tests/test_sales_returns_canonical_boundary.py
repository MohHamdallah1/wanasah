"""Dependency-free guards and execution of the unchanged Sales Return API bodies."""
import ast
import copy
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "wa_backend/api/sales_returns.py"
MIGRATION = ROOT / "wa_backend/alembic/versions/e6f2a8c9d410_sales_return_create_permission.py"
CAPABILITY = "sales_return.create"
# Main 342dc2f0: only canonical company authority and attribution were normalized.
API_BODIES = {
    "_http": "db1d1280dcdc93be0e0af3a571ba3e6e6201f3b77c35a5719a84a1d8ef2d0bd3",
    "list_returns": "9b261f045884a85ec2ac1f956f8e3ef973203e27d334deb5999b49572309411a",
    "returnable_sales": "6bfb06deb5fec966733a0260a227fdbac36df280a9438ab626a4ad5ba9bf9dfb",
    "return_source": "cd67b220432612e55c33d1fe3ec7d465031319dbdc707dd5d61f085dd6fdd944",
    "return_detail": "cb7fcd846a22ebd972741a943b8cd0daece4dd54f5881c54e0bf7641be249fa1",
    "post_return": "a85ea19af74842ccb0b4e86ffcc98d3209f6dcfab22f1f4f5ec6ea4e6eeeefdf"
}
DOMAIN_FILES = {
    "wa_backend/domains/sales_returns/core.py": "95acf8529ead2d8c66554ae68ceb8c8aea4b7ae0fc91fcbc53c19fcb493f794b",
    "wa_backend/domains/sales_returns/models.py": "00ef7066b918060bff634d69bd9bb0cc9f921885012933ddf5b16a513c1a81b4",
    "wa_backend/domains/sales_returns/schemas.py": "bfc540aac6814611c4b61d3ef1c17704ee9c2fc4f98d3b822ac01b31a8be0d11",
    "wa_backend/domains/sales_returns/service.py": "2322a3d25d06596eba3ec1e19981f5a331f2590c3a960b8624b2784b17ddde16",
    "wa_backend/domains/sales_returns/__init__.py": "7cc2005481ce92ed219869d471f3ad131c0242301483add0d742331baf3e5643"
}
ROUTES = {
    "list_returns": ("get", ""),
    "returnable_sales": ("get", "/sources"),
    "return_source": ("get", "/source/{visit_id}"),
    "return_detail": ("get", "/{return_id}"),
    "post_return": ("post", ""),
}


class HttpRejection(Exception):
    def __init__(self, status_code, detail):
        self.status_code, self.detail = status_code, detail


class AttributionActor:
    id = 903

    @property
    def company_id(self):
        raise AssertionError("Legacy company identity is not business authority")

    @property
    def is_admin(self):
        raise AssertionError("Legacy flags are not business authority")


def compile_functions(source, names, namespace):
    nodes = []
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node = copy.deepcopy(node)
            node.decorator_list = []
            node.args.defaults = []
            node.args.kw_defaults = [None for _ in node.args.kwonlyargs]
            node.returns = None
            for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                arg.annotation = None
            nodes.append(node)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<actual-sales-return-source>", "exec"), namespace)


class SalesReturnsCanonicalBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.source = API.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.functions = {node.name: node for node in self.tree.body
                          if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        namespace = {}
        exec((ROOT / "wa_backend/domains/sales_returns/core.py").read_text(encoding="utf-8"), namespace)
        self.error = namespace["SalesReturnError"]
        self.services = {name: AsyncMock(return_value={"unchanged": name}) for name in (
            "list_sales_returns", "list_returnable_sales", "source_summary",
            "get_sales_return", "create_sales_return",
        )}
        self.namespace = {"HTTPException": HttpRejection, "SalesReturnError": self.error, **self.services}
        compile_functions(self.source, set(API_BODIES), self.namespace)
        self.db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock(), begin=Mock())
        self.access = SimpleNamespace(company_id=77)

    def test_exact_frozen_capability_is_canonical_and_not_company_only(self):
        namespace = {}
        exec((ROOT / "wa_backend/domains/authorization/capabilities.py").read_text(encoding="utf-8"), namespace)
        self.assertEqual({code for code in namespace["PERMISSIONS"] if code.startswith("sales_return.")},
                         {CAPABILITY})
        self.assertNotIn(CAPABILITY, namespace["COMPANY_ONLY"])
        self.assertIn(CAPABILITY, (ROOT / "IDENTITY_PHASE2_CAPABILITY_FREEZE.md").read_text(encoding="utf-8"))

    def test_additive_permission_migration_executes_only_catalog_insert_and_retains_downgrade(self):
        tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
        execute = Mock()
        namespace = {"op": SimpleNamespace(execute=execute)}
        exec(compile(ast.Module(body=[node for node in tree.body if not isinstance(node, ast.ImportFrom)],
                                type_ignores=[]), str(MIGRATION), "exec"), namespace)
        self.assertEqual(namespace["revision"], "e6f2a8c9d410")
        self.assertEqual(namespace["down_revision"], "d3b7e1a4c920")
        namespace["upgrade"]()
        execute.assert_called_once_with(
            "INSERT INTO permissions (code) VALUES ('sales_return.create') ON CONFLICT (code) DO NOTHING"
        )
        namespace["downgrade"]()
        self.assertEqual(execute.call_count, 1)
        self.assertNotIn("role_permissions", ast.unparse(tree))
        self.assertNotIn("description", ast.unparse(tree))
        occurrences = [path for path in MIGRATION.parent.glob("*.py")
                       if CAPABILITY in path.read_text(encoding="utf-8")]
        self.assertEqual(occurrences, [MIGRATION])

    def test_all_five_routes_require_the_same_creation_capability_with_no_read_actor_dependency(self):
        routes = {name: node for name, node in self.functions.items() if node.decorator_list}
        self.assertEqual(set(routes), set(ROUTES))
        factories = [node for node in ast.walk(self.tree) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name)
                     and node.func.id == "require_legacy_transport_backoffice_capability"]
        self.assertEqual(len(factories), 1)
        self.assertEqual(ast.literal_eval(factories[0].args[0]), CAPABILITY)
        for name, node in routes.items():
            self.assertEqual(node.decorator_list[0].func.attr, ROUTES[name][0])
            self.assertEqual(ast.literal_eval(node.decorator_list[0].args[0]), ROUTES[name][1])
            defaults = dict(zip([arg.arg for arg in node.args.args][-len(node.args.defaults):],
                                node.args.defaults))
            self.assertEqual(ast.unparse(defaults["access"]), "Depends(_sales_return_access)")
            if name == "post_return":
                self.assertEqual(ast.unparse(defaults["legacy_actor"]), "Depends(get_current_driver)")
            else:
                self.assertEqual(set(defaults) & {"legacy_actor", "current_admin"}, set())
                self.assertFalse(any(ast.unparse(arg.annotation) == "Driver" for arg in node.args.args
                                     if arg.annotation is not None))

    def test_api_has_no_legacy_authority_token_decode_or_arbitrary_scope(self):
        for forbidden in ("get_current_admin", ".is_admin", "classification", "jwt.decode",
                          "legacy_actor.company_id", "sales_return.read", "sales_return.manage",
                          "sales_return.admin", "location_id", "use_cache=False"):
            self.assertNotIn(forbidden, self.source)
        attributes = [node for node in ast.walk(self.tree) if isinstance(node, ast.Attribute)
                      and isinstance(node.value, ast.Name) and node.value.id == "legacy_actor"]
        self.assertEqual([node.attr for node in attributes], ["id"])

    def test_api_business_bodies_error_mapping_and_transaction_order_are_unchanged(self):
        for name, expected in API_BODIES.items():
            body = ast.Module(body=self.functions[name].body, type_ignores=[])
            actual = hashlib.sha256(ast.dump(body, include_attributes=False).encode()).hexdigest()
            self.assertEqual(actual, expected, name)

    def test_all_sales_return_domain_files_and_structural_invariants_are_unchanged(self):
        for relative, expected in DOMAIN_FILES.items():
            actual = hashlib.sha256((ROOT / relative).read_text(encoding="utf-8").encode()).hexdigest()
            self.assertEqual(actual, expected, relative)
        models = (ROOT / "wa_backend/domains/sales_returns/models.py").read_text(encoding="utf-8")
        self.assertIn('["drivers.company_id", "drivers.id"]', models)
        service = (ROOT / "wa_backend/domains/sales_returns/service.py").read_text(encoding="utf-8")
        self.assertIn("created_by=int(actor_id)", service)
        self.assertIn("admin_id=int(actor_id)", service)

    def read_cases(self):
        return (
            ("list_returns", "list_sales_returns", dict(limit=12, before_id=900)),
            ("returnable_sales", "list_returnable_sales", dict(search="Shop", date_from=date(2026, 1, 1),
                date_to=date(2026, 1, 2), before_revision_id=701, limit=13)),
            ("return_source", "source_summary", dict(visit_id=401)),
            ("return_detail", "get_sales_return", dict(return_id=501)),
        )

    async def test_all_reads_forward_canonical_company_and_existing_filters_without_mutation(self):
        for route, service, kwargs in self.read_cases():
            with self.subTest(route=route):
                response = await self.namespace[route](db=self.db, access=self.access, **kwargs)
                self.assertEqual(response, {"unchanged": service})
                self.services[service].assert_awaited_once_with(self.db, company_id=77, **kwargs)
        self.db.commit.assert_not_awaited()
        self.db.rollback.assert_not_awaited()
        self.db.begin.assert_not_called()

    async def test_read_errors_preserve_domain_status_message_and_remain_read_only(self):
        for route, service, kwargs in self.read_cases():
            with self.subTest(route=route):
                self.services[service].side_effect = self.error("SOURCE_MISSING", "Existing safe message", status_code=404)
                with self.assertRaises(HttpRejection) as caught:
                    await self.namespace[route](db=self.db, access=self.access, **kwargs)
                self.assertEqual((caught.exception.status_code, caught.exception.detail),
                                 (404, "Existing safe message"))
        self.db.commit.assert_not_awaited()
        self.db.rollback.assert_not_awaited()

    async def test_post_uses_only_legacy_attribution_and_commits_after_service_success(self):
        payload = object()
        for legacy_flag in (False, True):
            with self.subTest(legacy_flag=legacy_flag):
                actor = AttributionActor()
                actor._legacy_flag = legacy_flag
                self.db.commit.reset_mock()
                self.services["create_sales_return"].reset_mock()
                response = await self.namespace["post_return"](
                    payload=payload, db=self.db, access=self.access, legacy_actor=actor,
                )
                self.assertEqual(response, {"unchanged": "create_sales_return"})
                self.services["create_sales_return"].assert_awaited_once_with(
                    self.db, company_id=77, actor_id=903, payload=payload,
                )
                self.db.commit.assert_awaited_once_with()
        self.db.rollback.assert_not_awaited()
        self.db.begin.assert_not_called()

    async def test_post_domain_rejection_rolls_back_without_commit(self):
        self.services["create_sales_return"].side_effect = self.error("SOURCE_INVALID", "Source invalid", status_code=409)
        with self.assertRaises(HttpRejection) as caught:
            await self.namespace["post_return"](payload=object(), db=self.db, access=self.access,
                                                legacy_actor=AttributionActor())
        self.assertEqual((caught.exception.status_code, caught.exception.detail), (409, "Source invalid"))
        self.db.rollback.assert_awaited_once_with()
        self.db.commit.assert_not_awaited()
        self.db.begin.assert_not_called()

    async def test_post_unexpected_failure_rolls_back_and_reraises_the_same_exception(self):
        failure = RuntimeError("synthetic persistence failure")
        self.services["create_sales_return"].side_effect = failure
        with self.assertRaises(RuntimeError) as caught:
            await self.namespace["post_return"](payload=object(), db=self.db, access=self.access,
                                                legacy_actor=AttributionActor())
        self.assertIs(caught.exception, failure)
        self.db.rollback.assert_awaited_once_with()
        self.db.commit.assert_not_awaited()

    def pure_service(self):
        namespace = dict(Decimal=Decimal, InvalidOperation=InvalidOperation, ROUND_HALF_UP=ROUND_HALF_UP,
                         MONEY_QUANT=Decimal("0.000001"), MONEY_MAX=Decimal("99999999999999.999999"),
                         SalesReturnError=self.error, hashlib=hashlib, json=json)
        compile_functions((ROOT / "wa_backend/domains/sales_returns/service.py").read_text(encoding="utf-8"),
                          {"_d", "money", "_target_amount", "cumulative_delta", "_request_hash"}, namespace)
        return namespace

    def test_original_cumulative_financial_allocation_consumes_residual_and_rejects_over_return(self):
        delta = self.pure_service()["cumulative_delta"]
        kwargs = dict(original_amount=Decimal("10"), source_quantity=Decimal("3"),
                      prior_returned_quantity=Decimal("0"), requested_quantity=Decimal("1"),
                      prior_reversed_amount=Decimal("0"))
        first = delta(**kwargs)
        second = delta(**{**kwargs, "prior_returned_quantity": Decimal("1"),
                          "requested_quantity": Decimal("2"), "prior_reversed_amount": first})
        self.assertEqual((first, second, first + second),
                         (Decimal("3.333333"), Decimal("6.666667"), Decimal("10.000000")))
        with self.assertRaises(self.error):
            delta(**{**kwargs, "requested_quantity": Decimal("4")})

    def test_request_hash_preserves_reordering_and_detects_changed_return_data(self):
        request_hash = self.pure_service()["_request_hash"]
        components = [SimpleNamespace(original_price_component_id=501, quantity=Decimal("1")),
                      SimpleNamespace(original_price_component_id=502, quantity=Decimal("2"))]
        payload = SimpleNamespace(request_id=uuid4(), original_sales_revision_id=701,
                                  reason="Return reason", components=components)
        original = request_hash(payload)
        payload.components = list(reversed(components))
        payload.request_id = uuid4()
        self.assertEqual(request_hash(payload), original)
        payload.components[0].quantity = Decimal("3")
        self.assertNotEqual(request_hash(payload), original)


if __name__ == "__main__":
    unittest.main()
