"""Field transport retirement and parity gates without third-party dependencies."""
import ast
import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
import subprocess


BACKEND = Path(__file__).resolve().parents[1]
SOURCE = BACKEND / "api" / "driver.py"
# Freeze CURRENT main source, rather than stale hashes from an older identity
# cutover. CI fetches this immutable Git object; no network or runtime DB lookup.
BASELINE_SHA = "1f69d2d8946e027aeea64d518152c4c7bf7bcc13"
FROZEN_FUNCTIONS = (
    "start_work_session", "end_work_session", "toggle_break", "update_visit",
    "get_driver_dashboard", "respond_to_transfer", "batch_respond_to_transfers",
    "get_pending_transfers", "add_new_shop", "get_products",
    "get_driver_visits", "get_active_session",
)

ROUTES = {
    "start_work_session": [
        "router.post('/driver/sessions/start', status_code=201)"
    ],
    "end_work_session": [
        "router.put('/driver/sessions/end', status_code=200)"
    ],
    "toggle_break": [
        "router.put('/driver/sessions/break', status_code=200)"
    ],
    "update_visit": [
        "router.put('/visits/{visit_id}', status_code=200)"
    ],
    "get_driver_dashboard": [
        "router.get('/driver/dashboard', status_code=200)"
    ],
    "respond_to_transfer": [
        "router.put('/driver/transfers/{transfer_id}/respond', status_code=200)"
    ],
    "batch_respond_to_transfers": [
        "router.put('/driver/transfers/batch_respond', status_code=200)"
    ],
    "get_pending_transfers": [
        "router.get('/driver/transfers/pending', response_model=List[PendingBatchResponse], status_code=200)"
    ],
    "add_new_shop": [
        "router.post('/shops', status_code=201)"
    ],
    "get_products": [
        "router.get('/product_variants', response_model=List[ProductVariantResponse], status_code=200)"
    ],
    "get_driver_visits": [
        "router.get('/driver/visits', response_model=GetVisitsContract, status_code=200)"
    ],
    "get_active_session": [
        "router.get('/driver/sessions/active', response_model=ActiveSessionResponse, status_code=200)"
    ]
}


def digest(nodes):
    # Python 3.12 adds type_params=[] to declarations that Python 3.11 represents
    # without that field. Remove only the empty field on a copy. Nonempty type
    # parameters and every business AST node remain part of the fingerprint.
    tree = copy.deepcopy(ast.Module(body=nodes, type_ignores=[]))
    for node in ast.walk(tree):
        if getattr(node, "type_params", None) == []:
            del node.type_params
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


# The four approved FIELD additions are removed structurally ONLY for the old
# workflow fingerprint. Each exact statement must exist once; all old business
# statements, locks, ordering and response fields remain fingerprinted.
FIELD_IMPORTS = [
    "begin_field_shop_command", "complete_field_shop_command",
    "canonicalize_visit_returns", "revalidate_return_provenance",
    "revalidate_return_batch_metadata", "invoice_from_calculation",
    "pending_shop_commercial_state",
]
FIELD_VISIT_STATEMENTS = (
    """if return_proofs:
        canonical_payload["return_resolutions"] = sorted(
            return_proofs, key=lambda proof: (
                proof["request"]["product_variant_id"], proof["batch"],
                proof["request"]["return_type"]))""",
    """payload, return_proofs = canonicalize_visit_returns(
        payload, context=field_context, driver_id=driver_id, visit_id=visit_id)""",
    """await revalidate_return_provenance(
        db, context=field_context, driver_id=driver_id,
        visit=visit, session=active_session, proofs=return_proofs)""",
    """await revalidate_return_batch_metadata(
        db, company_id=company_id, proofs=return_proofs)""",
    """response_payload["invoice"] = (
        invoice_from_calculation(resolved_sale.calculation)
        if resolved_sale is not None else None)""",
)
FIELD_SHOP_STATEMENTS = (
    """shop_command, shop_replay = await begin_field_shop_command(
        db, payload=payload, company_id=field_context.company_id, driver_id=driver_id)""",
    """if shop_replay is not None:
        await db.rollback()
        return shop_replay""",
    """complete_field_shop_command(shop_command, response_payload)""",
)


def without_field_additions(node):
    node = copy.deepcopy(node)
    snippets = FIELD_VISIT_STATEMENTS if node.name == "update_visit" else (
        FIELD_SHOP_STATEMENTS if node.name == "add_new_shop" else ()
    )
    expected = {ast.dump(ast.parse(source).body[0], include_attributes=False): 0 for source in snippets}
    shop_response = None
    if node.name == "add_new_shop":
        assignments = [part for part in ast.walk(node) if isinstance(part, ast.Assign)
                       and len(part.targets) == 1 and isinstance(part.targets[0], ast.Name)
                       and part.targets[0].id == "response_payload"]
        if len(assignments) != 1 or not isinstance(assignments[0].value, ast.Dict):
            raise AssertionError("Expected exactly the approved shop response addition")
        response = assignments[0].value
        entries = list(zip(response.keys, response.values))
        additions = [(key, value) for key, value in entries
                     if isinstance(key, ast.Constant) and key.value == "commercial_readiness"]
        if len(additions) != 1 or ast.unparse(additions[0][1]) != "pending_shop_commercial_state()":
            raise AssertionError("Unexpected shop commercial readiness authority")
        legacy = [(key, value) for key, value in entries if key is not additions[0][0]]
        shop_response = ast.Dict(keys=[key for key, _ in legacy], values=[value for _, value in legacy])

    class RemoveApproved(ast.NodeTransformer):
        def visit(self, part):
            shape = ast.dump(part, include_attributes=False)
            if shape in expected:
                expected[shape] += 1
                return None
            if shop_response is not None:
                if (isinstance(part, ast.Assign) and any(isinstance(target, ast.Name)
                        and target.id == "response_payload" for target in part.targets)):
                    return None
                if (isinstance(part, ast.Return) and isinstance(part.value, ast.Name)
                        and part.value.id == "response_payload"):
                    return ast.Return(value=copy.deepcopy(shop_response))
            return super().visit(part)

    node = RemoveApproved().visit(node)
    if any(count != 1 for count in expected.values()):
        raise AssertionError(f"Approved FIELD statement changed or duplicated: {expected}")
    return node.body


class OperationalLocator:
    id = 303
    full_name = "Operational display name"

    @property
    def company_id(self):
        raise AssertionError("Company authority must come from FieldRequestContext")

    @property
    def is_admin(self):
        raise AssertionError("Operational flags must never authorize")


class LegacyFieldTransportBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        baseline = subprocess.check_output(
            ["git", "show", BASELINE_SHA + ":wa_backend/api/driver.py"],
            cwd=BACKEND.parent, text=True, encoding="utf-8",
        )
        self.baseline_tree = ast.parse(baseline)
        self.baseline_functions = {
            node.name: node for node in self.baseline_tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name in FROZEN_FUNCTIONS
        }
        self.functions = {node.name: node for node in self.tree.body
                          if isinstance(node, ast.AsyncFunctionDef)
                          and node.name in FROZEN_FUNCTIONS}
        self.assertEqual(set(self.functions), set(FROZEN_FUNCTIONS))

    def test_digest_ignores_only_absent_versus_empty_type_parameter_metadata(self):
        declaration = ast.parse("def nested(): return 1").body[0]
        without = copy.deepcopy(declaration)
        without._fields = tuple(field for field in without._fields if field != "type_params")
        if hasattr(without, "type_params"):
            del without.type_params
        empty = copy.deepcopy(without)
        empty._fields += ("type_params",)
        empty.type_params = []
        populated = copy.deepcopy(empty)
        populated.type_params = [ast.Name(id="T", ctx=ast.Load())]
        self.assertEqual(digest([without]), digest([empty]))
        self.assertNotEqual(digest([empty]), digest([populated]))
        # Fingerprinting must not mutate the source AST used by other gates.
        self.assertEqual(empty.type_params, [])

    def test_digest_still_detects_a_nested_business_statement_change(self):
        original = ast.parse("def nested(): return 1").body
        changed = ast.parse("def nested(): return 2").body
        self.assertNotEqual(digest(original), digest(changed))

    def test_all_twelve_routes_use_cached_canonical_field_and_operational_dependencies(self):
        for name, node in self.functions.items():
            with self.subTest(endpoint=name):
                arguments = {arg.arg: arg for arg in node.args.args}
                defaults = dict(zip(
                    [arg.arg for arg in node.args.args][-len(node.args.defaults):],
                    node.args.defaults,
                ))
                self.assertEqual(arguments["field_context"].annotation.id, "FieldRequestContext")
                self.assertEqual(arguments["legacy_actor"].annotation.id, "Driver")
                for parameter, dependency in (
                    ("field_context", "get_current_field_context"),
                    ("legacy_actor", "get_current_field_legacy_driver"),
                ):
                    self.assertEqual(defaults[parameter].func.id, "Depends")
                    self.assertEqual(defaults[parameter].args[0].id, dependency)
                    self.assertEqual(defaults[parameter].keywords, [])
                self.assertNotIn("current_driver", arguments)

    def test_company_and_operational_ids_are_independent_without_flag_or_decode_authority(self):
        context = SimpleNamespace(principal_id=101, representative_id=202, company_id=7)
        actor = OperationalLocator()
        for name, node in self.functions.items():
            with self.subTest(endpoint=name):
                driver_binding = next(
                    item for item in node.body if isinstance(item, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "driver_id"
                            for target in item.targets)
                )
                namespace = dict(field_context=context, legacy_actor=actor)
                exec(compile(ast.Module(body=[driver_binding], type_ignores=[]),
                             str(SOURCE), "exec"), namespace)
                self.assertEqual(namespace["driver_id"], 303)
                self.assertEqual((context.principal_id, context.representative_id, actor.id),
                                 (101, 202, 303))
                company_reads = []
                for part in ast.walk(node):
                    if isinstance(part, ast.Attribute):
                        self.assertNotIn(part.attr, {"is_admin", "classification", "role", "roles", "decode"})
                        if isinstance(part.value, ast.Name):
                            if part.value.id == "legacy_actor":
                                self.assertIn(part.attr, {"id", "full_name"})
                            if part.value.id == "field_context":
                                self.assertEqual(part.attr, "company_id")
                                company_reads.append(part)
                    if isinstance(part, ast.Name):
                        self.assertNotIn(part.id, {"current_driver", "jwt", "decode_company_token",
                                                   "get_current_driver", "get_legacy_transport_field_context"})
                self.assertTrue(company_reads)
                for expression in company_reads:
                    self.assertEqual(eval(compile(ast.Expression(expression), str(SOURCE), "eval"),
                                          namespace), 7)

    def test_entire_workflows_locks_transactions_idempotency_and_responses_preserved(self):
        for name in FROZEN_FUNCTIONS:
            expected = digest(self.baseline_functions[name].body)
            with self.subTest(endpoint=name):
                self.assertEqual(digest(without_field_additions(self.functions[name])), expected)
                self.assertEqual([ast.unparse(item) for item in self.functions[name].decorator_list],
                                 ROUTES[name])

    def test_helpers_mixed_visit_details_and_all_unrelated_module_code_are_unchanged(self):
        remainder = []
        for node in self.tree.body:
            if isinstance(node, ast.AsyncFunctionDef) and node.name in FROZEN_FUNCTIONS:
                continue
            if isinstance(node, ast.ImportFrom) and node.module == "api.field_visit_contracts":
                self.assertEqual([alias.name for alias in node.names], FIELD_IMPORTS)
                continue
            remainder.append(node)
        baseline = [
            node for node in self.baseline_tree.body
            if not (isinstance(node, ast.AsyncFunctionDef) and node.name in FROZEN_FUNCTIONS)
        ]
        self.assertEqual(digest(remainder), digest(baseline))

    def test_retired_adapter_is_absent_and_has_zero_runtime_consumers(self):
        self.assertFalse((BACKEND / "api" / "authentication" / "legacy_field_transport.py").exists())
        consumers = []
        for path in BACKEND.rglob("*.py"):
            if any(part in {"tests", "alembic", "scripts", "perf_reports", "__pycache__"}
                   for part in path.relative_to(BACKEND).parts):
                continue
            source = path.read_text(encoding="utf-8-sig")
            if "legacy_field_transport" in source or "get_legacy_transport_field_context" in source:
                consumers.append(str(path.relative_to(BACKEND)))
        self.assertEqual(consumers, [])
        for filename in ("field_compatibility.py", "dependencies.py"):
            self.assertTrue((BACKEND / "api" / "authentication" / filename).is_file())
        self.assertTrue((BACKEND / "domains" / "authorization" / "field_subject.py").is_file())


if __name__ == "__main__":
    unittest.main()
