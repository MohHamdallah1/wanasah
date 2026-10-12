"""Executable Catalog-input, cursor and source parity checks for Simple Products."""
import ast
import base64
import copy
import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
from uuid import UUID

SOURCE = Path(__file__).resolve().parents[1] / "api" / "simple_products.py"
# Independently transformed from 27a35f0df39558667e3066e08389c036270dc3a6.
# Only identity wiring changes: canonical tenant/access, mapped provenance IDs,
# canonical Inventory read inputs and explicit company_id for mutation services.
# All schemas, route defaults/decorators, SQL, business helpers, pagination,
# cursor signatures, hashes, audit values, locks and transaction nodes remain.
BUSINESS_DIGEST = "296f62d5902145da492856b186f4a9b8e0a74ac5a41effc9a93d4572cc08be66"
MANAGE = ("catalog.manage", "catalog.publish", "pricing.manage")
CAPABILITIES = {
    "package_uoms": ("catalog.read",), "families": ("catalog.read",),
    "catalog_summary": ("catalog.read",), "list_simple_products": ("catalog.read",),
    "create_product_family": ("catalog.manage",),
    "update_product_family": ("catalog.manage",),
    "delete_product_family": ("catalog.manage",),
    "create_simple_product": MANAGE, "update_simple_product_price": ("pricing.manage",),
}
MUTATIONS = {"create_product_family", "update_product_family", "delete_product_family",
             "create_simple_product", "update_simple_product_price"}


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
                node.decorator_list or node.name in {"_audit", "_require_manage"}):
            defaults = dict(zip([a.arg for a in node.args.args][-len(node.args.defaults):],
                                node.args.defaults)) if node.args.defaults else {}
            node.args.args = [a for a in node.args.args if a.arg not in {"access", "legacy_actor"}]
            node.args.defaults = [defaults[a.arg] for a in node.args.args if a.arg in defaults]
    for node in ast.walk(tree):
        if getattr(node, "type_params", None) == []:
            del node.type_params
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


def functions(names, namespace, *, route=False):
    selected = []
    for node in ast.parse(SOURCE.read_text(encoding="utf-8-sig")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list = []
            if route:
                node.args.defaults = []
            selected.append(node)
    assert len(selected) == len(names)
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    tree = ast.fix_missing_locations(ast.Module(body=[future, *selected], type_ignores=[]))
    exec(compile(tree, str(SOURCE), "exec"), namespace)
    return namespace


class HTTPError(Exception):
    def __init__(self, status_code, detail=None):
        self.status_code, self.detail = status_code, detail


class Rejected(Exception):
    pass


def cursor_functions():
    return functions({
        "_invalid_cursor", "_search_tokens", "_cursor_signature", "_decode_cursor_part",
        "_family_cursor_scope", "_family_cursor", "_family_next_cursor",
        "_product_cursor_scope", "_product_cursor", "_product_next_cursor",
    }, {"base64": base64, "hashlib": hashlib, "hmac": hmac, "json": json,
        "HTTPException": HTTPError,
        "Config": SimpleNamespace(SECRET_KEY="SimpleCursorSyntheticSecret1234567890")})


class SimpleProductsCanonicalBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.source = SOURCE.read_text(encoding="utf-8-sig")
        self.tree = ast.parse(self.source)
        self.functions = {n.name: n for n in self.tree.body
                          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def test_zero_legacy_request_tenant_flag_or_jwt_authority(self):
        for forbidden in ("get_current_driver", "get_current_admin", "InventoryAccess",
                          ".is_admin", "actor.company_id", "legacy_backoffice_transport",
                          "jwt.decode", "decode_company_token"):
            self.assertFalse(forbidden in self.source, forbidden)
        self.assertFalse(any(isinstance(n, ast.Name) and n.id == "actor" for n in ast.walk(self.tree)))
        self.assertNotIn("is_company_owner", self.source)
        imports = {n.module for n in self.tree.body if isinstance(n, ast.ImportFrom)}
        self.assertNotIn("api.dependencies", imports)

    def test_all_nine_routes_have_canonical_access_and_only_five_have_mapped_driver(self):
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
                self.assertEqual("legacy_actor" in args, name in MUTATIONS)
                if name in MUTATIONS:
                    self.assertEqual(ast.unparse(defaults["legacy_actor"]),
                                     "Depends(get_current_backoffice_legacy_driver)")
                    self.assertEqual(defaults["legacy_actor"].keywords, [])

    def test_exact_capability_mapping_all_three_requirements_and_denial_contract(self):
        for name, expected in CAPABILITIES.items():
            call = self.functions[name].body[0].value.value
            if name == "create_simple_product":
                self.assertEqual(ast.unparse(call), "_require_manage(access)")
            else:
                self.assertEqual([ast.unparse(a) for a in call.args],
                                 ["access", repr(expected[0])])
        manage = self.functions["_require_manage"].body[0]
        self.assertEqual(ast.literal_eval(manage.iter), MANAGE)
        self.assertEqual(ast.unparse(manage.body[0]), "await _require(access, permission)")
        helper = self.functions["_require"].body[0]
        self.assertEqual(ast.unparse(helper.body[0]), "await access.require(permission, any_location=True)")
        self.assertEqual(helper.handlers[0].type.id, "BackofficeCapabilityAccessRejected")
        self.assertIn("status_code=403", ast.unparse(helper))
        self.assertIn("access.allows('pricing.view', any_location=True)",
                      ast.unparse(self.functions["list_simple_products"]))

    def test_inventory_and_mutation_seams_receive_canonical_tenant_inputs(self):
        calls = {n.func.id: n for n in ast.walk(self.tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id in {
                     "variant_ids_present_in_all_warehouses", "load_batch_restrictions",
                     "create_products_and_prices", "update_prices"}}
        for name in ("variant_ids_present_in_all_warehouses", "load_batch_restrictions"):
            kwargs = {k.arg: ast.unparse(k.value) for k in calls[name].keywords}
            self.assertEqual(kwargs["access"], "access")
            self.assertNotIn("actor", kwargs)
            self.assertNotIn("company_id", kwargs)
        for name in ("create_products_and_prices", "update_prices"):
            kwargs = {k.arg: ast.unparse(k.value) for k in calls[name].keywords}
            self.assertEqual(kwargs["actor"], "legacy_actor")
            self.assertEqual(kwargs["company_id"], "access.company_id")
        for name in ("families", "list_simple_products"):
            self.assertIn("company_id = int(access.company_id)", ast.unparse(self.functions[name]))

    def test_operational_actor_reads_and_idempotency_are_only_stored_driver_ids(self):
        begins = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "legacy_actor":
                    self.assertEqual(node.attr, "id")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "begin_idempotent_operation":
                    begins.append(node)
                    kwargs = {k.arg: ast.unparse(k.value) for k in node.keywords}
                    self.assertEqual(kwargs["company_id"], "int(access.company_id)")
                    self.assertEqual(kwargs["actor_id"], "int(legacy_actor.id)")
                if node.func.id == "_audit":
                    self.assertEqual([ast.unparse(a) for a in node.args[:3]],
                                     ["db", "access", "legacy_actor"])
        self.assertEqual(len(begins), 5)
        self.assertIn("company_id=access.company_id", ast.unparse(self.functions["_audit"]))
        self.assertIn("admin_id=legacy_actor.id", ast.unparse(self.functions["_audit"]))

    def test_complete_business_http_cursor_sql_lock_and_transaction_parity(self):
        self.assertEqual(business_digest(self.tree), BUSINESS_DIGEST)

    def test_product_cursor_signature_tenant_warehouse_and_sort_scope(self):
        api = cursor_functions()
        scope = dict(company_id=7, search=" Juice  carton ", family_id=None,
                     lifecycle=None, tracking_type=None, simple_compatible=None,
                     has_barcode=None, has_price=None, lot_tracked=None, expiry_tracked=None,
                     warehouse_ids=(21,), sort_by="id", sort_dir="asc", limit=2)
        cursor = api["_product_next_cursor"](sort_key=42, variant_id=42, **scope)
        self.assertEqual(api["_product_cursor"](cursor, **scope), (42, 42))
        self.assertEqual(api["_product_cursor"](cursor, **{**scope, "search": "juice carton"}), (42, 42))
        for change in ({"company_id": 8}, {"warehouse_ids": (22,)}, {"limit": 3},
                       {"sort_dir": "desc"}, {"family_id": 9}):
            with self.subTest(change=change), self.assertRaises(HTTPError) as failure:
                api["_product_cursor"](cursor, **{**scope, **change})
            self.assertEqual(failure.exception.status_code, 400)
        payload, signature = cursor.split(".")
        forged = base64.urlsafe_b64encode(b'{"v":1}').decode().rstrip("=") + "." + signature
        with self.assertRaises(HTTPError):
            api["_product_cursor"](forged, **scope)


class SimpleProductsLocalExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_canonical_shared_inputs_never_enter_driver_tenant_or_access_fallbacks(self):
        backend = SOURCE.parents[1]
        cases = (
            ("domains/simple_products/service.py", "_resolve_service_company_id"),
            ("domains/inventory_catalog_presence.py", "_resolve_catalog_presence_access"),
            ("domains/inventory_batch_restrictions/queries.py", "_resolve_batch_restriction_access"),
        )
        class OperationalActor:
            id = 303
            def __getattr__(self, name):
                raise AssertionError("Unexpected operational actor read: " + name)
        access = SimpleNamespace(company_id=7)
        for relative, name in cases:
            with self.subTest(seam=name):
                path = backend / relative
                node = next(n for n in ast.parse(path.read_text(encoding="utf-8-sig")).body
                            if isinstance(n, ast.FunctionDef) and n.name == name)
                future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
                namespace = {"InventoryAccess": Mock(side_effect=AssertionError("Legacy authorization constructed"))}
                tree = ast.fix_missing_locations(ast.Module(body=[future, node], type_ignores=[]))
                exec(compile(tree, str(path), "exec"), namespace)
                if name == "_resolve_service_company_id":
                    self.assertEqual(namespace[name](OperationalActor(), 7), 7)
                elif name == "_resolve_catalog_presence_access":
                    self.assertEqual(namespace[name](None, access=access, actor=None, company_id=None), (7, access))
                else:
                    self.assertEqual(namespace[name](None, access=access, actor=None), (7, access))
                namespace["InventoryAccess"].assert_not_called()

    async def test_manage_requires_every_capability_in_order_and_stops_on_denial(self):
        api = functions({"_require", "_require_manage"},
                        {"BackofficeCapabilityAccessRejected": Rejected, "HTTPException": HTTPError})
        for missing in MANAGE:
            calls = []
            async def require(code, **scope):
                calls.append(code)
                self.assertEqual(scope, {"any_location": True})
                if code == missing:
                    raise Rejected("storage detail must not escape")
            with self.subTest(missing=missing), self.assertRaises(HTTPError) as failure:
                await api["_require_manage"](SimpleNamespace(require=require))
            self.assertEqual(failure.exception.status_code, 403)
            self.assertEqual(failure.exception.detail,
                             "لا تملك صلاحية تنفيذ هذه العملية ضمن الموقع المحدد.")
            self.assertEqual(calls, list(MANAGE[:MANAGE.index(missing) + 1]))
        access = SimpleNamespace(require=AsyncMock())
        await api["_require_manage"](access)
        self.assertEqual([c.args[0] for c in access.require.await_args_list], list(MANAGE))

    async def test_family_listing_uses_canonical_cursor_scope_and_keyset_continuation(self):
        api = cursor_functions()
        rows = [{"id": 41, "name": "Alpha", "_sort_name": "alpha", "variant_count": 2},
                {"id": 42, "name": "Beta", "_sort_name": "beta", "variant_count": 1},
                {"id": 43, "name": "Gamma", "_sort_name": "gamma", "variant_count": 0}]
        read = AsyncMock(return_value=rows)
        api.update(_require=AsyncMock(), list_families=read)
        functions({"families"}, api, route=True)
        db, access = object(), SimpleNamespace(company_id=7)
        first = await api["families"](search=None, cursor=None, limit=2, db=db, access=access)
        self.assertEqual([r["id"] for r in first["items"]], [41, 42])
        self.assertTrue(first["has_more"])
        self.assertNotIn("_sort_name", first["items"][0])
        self.assertEqual(read.call_args.kwargs,
                         dict(company_id=7, search=None, after_name=None, after_id=None, limit=3))
        read.return_value = rows[2:]
        last = await api["families"](search=None, cursor=first["next_cursor"], limit=2,
                                     db=db, access=access)
        self.assertEqual((read.call_args.kwargs["after_name"], read.call_args.kwargs["after_id"]),
                         ("beta", 42))
        self.assertFalse(last["has_more"])
        self.assertIsNone(last["next_cursor"])
        with self.assertRaises(HTTPError):
            await api["families"](search=None, cursor=first["next_cursor"], limit=2,
                                  db=db, access=SimpleNamespace(company_id=8))
        self.assertEqual(read.await_count, 2)

    async def test_create_provenance_explicit_tenant_hash_and_commit_order(self):
        class OperationalActor:
            id = 303
            def __getattr__(self, name):
                raise AssertionError("Unexpected operational actor read: " + name)
        events = []
        row = SimpleNamespace(id=42, lot_control_mode="REQUIRED", expiry_control_mode="NONE")
        prices = SimpleNamespace(package_price=None, unit_price=__import__("decimal").Decimal("1.5"))
        actor = OperationalActor()
        async def begin(db, **values):
            events.append("begin")
            self.assertEqual((values["company_id"], values["actor_id"]), (7, 303))
            self.assertEqual(values["request_hash"], "stable-hash")
            return object(), None
        async def create(db, **values):
            events.append("create")
            self.assertIs(values["actor"], actor)
            self.assertEqual(values["company_id"], 7)
            return [(row, prices)]
        async def commit():
            events.append("commit")
        db = SimpleNamespace(add=Mock(side_effect=lambda _: events.append("audit")),
                             commit=AsyncMock(side_effect=commit), rollback=AsyncMock())
        namespace = dict(_require_manage=AsyncMock(), begin_idempotent_operation=begin,
                         _request_hash=Mock(return_value="stable-hash"), create_products_and_prices=create,
                         SimpleProductSpec=lambda **values: values, SystemAuditLog=lambda **values: values,
                         json=json, complete_idempotent_operation=Mock(side_effect=lambda *_: events.append("complete")),
                         HTTPException=HTTPError)
        functions({"_audit", "create_simple_product"}, namespace, route=True)
        payload = SimpleNamespace(request_id=UUID("4e447464-7d22-4880-a0f0-e4549bf90e30"),
            name="Juice", family_id=None, family_name=None, family_mode="none", package_uom_code=None,
            units_per_package=1, package_price=None, unit_price=prices.unit_price,
            unit_barcode=None, package_barcode=None, lot_control_mode="REQUIRED", expiry_control_mode="NONE")
        result = await namespace["create_simple_product"](payload, db, SimpleNamespace(company_id=7), actor)
        self.assertEqual(events, ["begin", "create", "audit", "complete", "commit"])
        self.assertEqual(result["unit_price"], "1.500000")
        audit = db.add.call_args.args[0]
        self.assertEqual((audit["company_id"], audit["admin_id"]), (7, 303))
        self.assertEqual(json.loads(audit["new_value"]), result)
        namespace["_request_hash"].assert_called_once_with(payload)
        db.rollback.assert_not_awaited()

    async def test_family_idempotency_replay_keeps_mapped_id_and_only_rolls_back(self):
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock(), add=Mock())
        begin = AsyncMock(return_value=(object(), {"replayed": True}))
        create = AsyncMock()
        api = functions({"create_product_family"}, {
            "_require": AsyncMock(), "begin_idempotent_operation": begin,
            "_request_hash": Mock(return_value="stable"), "create_family": create,
        }, route=True)
        payload = SimpleNamespace(request_id=UUID("4e447464-7d22-4880-a0f0-e4549bf90e30"))
        result = await api["create_product_family"](payload, db, SimpleNamespace(company_id=7),
                                                    SimpleNamespace(id=303))
        self.assertEqual(result, {"replayed": True})
        self.assertEqual((begin.call_args.kwargs["company_id"], begin.call_args.kwargs["actor_id"]), (7, 303))
        create.assert_not_awaited()
        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()
        db.add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
