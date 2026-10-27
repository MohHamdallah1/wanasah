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
# Approved narrow batch error-identity wave; all other workflows stay frozen.
BATCH_ERROR_SHA = "5d36daf3f096937e8af045fc62452c63408e6419"
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
        "field_transfer_batch_route(router)"
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


FIELD_ROUTE_CAPABILITIES = {
    "start_work_session": ("work_session.execute",),
    "end_work_session": ("work_session.execute",),
    "toggle_break": ("work_session.execute",),
    "update_visit": ("visit.execute",),
    "get_driver_dashboard": ("work_session.read","visit.read","inventory.read"),
    "get_pending_transfers": ("transfer.read",),
    "add_new_shop": ("shop.create",),
    "get_products": ("catalog.read","pricing.view"),
    "get_driver_visits": ("visit.read","inventory.read","transfer.read","pricing.view"),
    "get_active_session": ("work_session.read",),
}


def without_capability_decorator(node):
    """Normalize only the exact approved D7 dependency; keep URL/status/model frozen."""
    node=copy.deepcopy(node)
    if node.name=="get_active_session":
        assert node.args.args[-1].arg=="_capability_access"
        assert ast.dump(node.args.defaults[-1])==ast.dump(ast.parse(
            'Depends(require_field_capability("work_session.read"))',mode="eval").body)
        return node
    for decorator in node.decorator_list:
        dependencies=[k for k in decorator.keywords if k.arg=="dependencies"]
        if node.name in FIELD_ROUTE_CAPABILITIES:
            codes=FIELD_ROUTE_CAPABILITIES[node.name]
            call=("require_field_capability("+repr(codes[0])+")" if len(codes)==1
                  else "require_field_capabilities("+repr(codes)+")")
        elif node.name=="respond_to_transfer":
            call="require_transfer_decision_capability"
        else:
            assert not dependencies
            continue
        assert len(dependencies)==1
        assert ast.dump(dependencies[0].value)==ast.dump(ast.parse("[Depends("+call+")]",mode="eval").body)
        decorator.keywords=[k for k in decorator.keywords if k.arg!="dependencies"]
    return node


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


def _normalize_dashboard_inventory_identity(node):
    if node.name != "get_driver_dashboard":
        return node

    matches = []
    for part in ast.walk(node):
        if not (
            isinstance(part, ast.Call)
            and isinstance(part.func, ast.Attribute)
            and isinstance(part.func.value, ast.Name)
            and part.func.value.id == "inventory_list"
            and part.func.attr == "append"
            and len(part.args) == 1
            and isinstance(part.args[0], ast.Dict)
        ):
            continue
        payload = part.args[0]
        entries = {
            key.value: (index, value)
            for index, (key, value) in enumerate(zip(payload.keys, payload.values))
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        if "product_variant_id" in entries:
            matches.append((payload, entries))

    if len(matches) != 1:
        raise AssertionError("Expected exactly one canonical dashboard inventory payload")

    payload, entries = matches[0]
    variant_index, variant_value = entries["product_variant_id"]
    packs_index, packs_value = entries.get("packs_per_carton", (None, None))
    if (
        ast.unparse(variant_value) != "int(variant.id)"
        or packs_index is None
        or ast.unparse(packs_value) != "int(packs)"
        or "product_id" in entries
    ):
        raise AssertionError("Unexpected dashboard inventory identity contract")

    payload.keys[variant_index] = ast.Constant(value="product_id")
    payload.values[variant_index] = ast.Attribute(
        value=ast.Name(id="variant", ctx=ast.Load()),
        attr="id",
        ctx=ast.Load(),
    )
    del payload.keys[packs_index]
    del payload.values[packs_index]
    return node


def without_field_additions(node):
    node = _normalize_dashboard_inventory_identity(copy.deepcopy(node))
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


def without_load_plan_reconciliation(node):
    """Allow only the owner-approved terminal plan hooks; freeze all old FIELD AST."""
    node = copy.deepcopy(node)
    if node.name not in {"respond_to_transfer", "batch_respond_to_transfers"}:
        return node
    single = node.name == "respond_to_transfer"
    session = "header.work_session_id" if single else "work_session_id"
    snippets = (
        f"await lock_session_load_plan(db, company_id=company_id, work_session_id={session})",
        f"await synchronize_session_load_plans(db, company_id=company_id, work_session_id={session}, actor_id=driver_id)",
    )
    expected = {ast.dump(ast.parse(source).body[0], include_attributes=False): 0 for source in snippets}
    hook_shapes = list(expected)
    if single:
        block = next(part.body for part in node.body if isinstance(part, ast.Try))
        session_index = next(i for i, part in enumerate(block) if isinstance(part, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "work_session" for target in part.targets))
        commit_index = next(i for i, part in enumerate(block) if ast.unparse(part) == "await db.commit()")
        assert ast.dump(block[session_index - 1], include_attributes=False) == hook_shapes[0]
        assert ast.dump(block[commit_index - 1], include_attributes=False) == hook_shapes[1]
    else:
        block = next(part.body for part in ast.walk(node) if isinstance(part, ast.If)
            and any(isinstance(statement, ast.Assign) and any(isinstance(target, ast.Name)
                and target.id == "work_session_id" for target in statement.targets) for statement in part.body))
        session_index = next(i for i, part in enumerate(block) if isinstance(part, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "work_session_id" for target in part.targets))
        assert ast.dump(block[session_index + 1], include_attributes=False) == hook_shapes[0]
        assert ast.dump(block[-1], include_attributes=False) == hook_shapes[1]

    class RemoveExactHooks(ast.NodeTransformer):
        def visit(self, part):
            shape = ast.dump(part, include_attributes=False)
            if shape in expected:
                expected[shape] += 1
                return None
            return super().visit(part)

    node = RemoveExactHooks().visit(node)
    assert all(count == 1 for count in expected.values()), "Plan hooks must occur exactly once"
    return node


def without_canonical_projection_source(source):
    """Whitelist exact owner-approved read adaptations; fingerprint everything else."""
    replacements = (
        ("from domains.dispatch_transfer_quantity import is_canonical_base_handshake, canonical_field_base_quantity, canonical_handshake_uom_metadata, canonical_handshake_evidence\n", ""),
        ("from domains.uom_authority import UomAuthorityError\n", ""),
        ('''    try:
        pending_uom = await canonical_handshake_uom_metadata(db, company_id=company_id, headers=headers, totals=totals)
    except UomAuthorityError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message, "context": exc.context}) from exc
''', ""),
        ('''            try:
                pending_uom = await canonical_handshake_uom_metadata(db, company_id=company_id, headers=pending_headers, totals=totals)
            except UomAuthorityError as exc:
                raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message, "context": exc.context}) from exc
''', ""),
        ('            **canonical_handshake_evidence(header, signed_quantity, pending_uom.get(product["product_variant_id"], {})),\n', ""),
        ('''                    **({"product_name": product["variant_name"], "delta_cartons": 0,
                        "delta_packs": _handshake_signed_quantity(header, vehicle_location_id=vehicle_location_id, quantity=product["quantity"]),
                        **canonical_handshake_evidence(header, _handshake_signed_quantity(header, vehicle_location_id=vehicle_location_id, quantity=product["quantity"]), pending_uom[product["product_variant_id"]])}
                       if is_canonical_base_handshake(header) else {}),
''', ""),
        ("    canonical_header_ids: Optional[set[int]] = None,\n", ""),
        ("        if products[0][\"quantity\"] <= 0 or (\n"
         "            int(header_id) not in (canonical_header_ids or ()) and products[0][\"packs_per_carton\"] <= 0\n"
         "        ):\n", "        if products[0][\"quantity\"] <= 0 or products[0][\"packs_per_carton\"] <= 0:\n"),
        ("        canonical_header_ids={int(header.id) for header in headers if is_canonical_base_handshake(header)},\n", ""),
        ("                canonical_header_ids={int(header.id) for header in pending_headers if is_canonical_base_handshake(header)},\n", ""),
        ("        canonical_base = is_canonical_base_handshake(header)\n", ""),
        ('"delta_cartons": 0 if canonical_base else (abs_packs // packs) * sign,',
         '"delta_cartons": (abs_packs // packs) * sign,'),
        ('"delta_packs": canonical_field_base_quantity(signed_quantity) if canonical_base else (abs_packs % packs) * sign,',
         '"delta_packs": (abs_packs % packs) * sign,'),
    )
    for approved, legacy in replacements:
        assert source.count(approved) == 1, "Canonical projection must match the exact approved adaptation once"
        source = source.replace(approved, legacy, 1)
    return source


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
        self.current_source = SOURCE.read_text(encoding="utf-8")
        self.tree = ast.parse(without_canonical_projection_source(self.current_source))
        baseline = subprocess.check_output(
            ["git", "show", BASELINE_SHA + ":wa_backend/api/driver.py"],
            cwd=BACKEND.parent, text=True, encoding="utf-8",
        )
        approved = subprocess.check_output(
            ["git", "show", BATCH_ERROR_SHA + ":wa_backend/api/driver.py"],
            cwd=BACKEND.parent, text=True, encoding="utf-8",
        )
        self.approved_functions = {
            node.name: node for node in ast.parse(approved).body
            if isinstance(node, ast.AsyncFunctionDef)
        }
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

    def test_canonical_projection_allowlist_rejects_missing_duplicate_or_changed_adaptations(self):
        marker = "        canonical_base = is_canonical_base_handshake(header)\n"
        for replacement in ("", marker + marker, marker.replace("header", "product")):
            with self.subTest(replacement=replacement), self.assertRaises(AssertionError):
                without_canonical_projection_source(self.current_source.replace(marker, replacement, 1))

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
            approved_batch = name == "batch_respond_to_transfers"
            expected = digest((self.approved_functions if approved_batch else self.baseline_functions)[name].body)
            with self.subTest(endpoint=name):
                normalized = without_load_plan_reconciliation(self.functions[name])
                actual = normalized.body if approved_batch else without_field_additions(normalized)
                self.assertEqual(digest(actual), expected)
                self.assertEqual([ast.unparse(item) for item in without_capability_decorator(self.functions[name]).decorator_list],
                                 ROUTES[name])

    def test_helpers_mixed_visit_details_and_all_unrelated_module_code_are_unchanged(self):
        remainder = []
        for node in self.tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "domains.dispatch_load_plan":
                self.assertEqual(ast.dump(node, include_attributes=False), ast.dump(ast.parse(
                    "from domains.dispatch_load_plan import lock_session_load_plan, synchronize_session_load_plans"
                ).body[0], include_attributes=False))
                continue
            if isinstance(node, ast.ImportFrom) and node.module in {
                "api.authentication.field_authorization",
                "api.authentication.field_transfer_authorization",
            }:
                expected = (
                    ["get_current_field_capability_access","require_field_capability","require_field_capabilities"]
                    if node.module.endswith(".field_authorization") else
                    ["require_transfer_decision_capability","require_transfer_batch_capabilities"]
                )
                self.assertEqual([alias.name for alias in node.names],expected)
                continue
            if isinstance(node, ast.AsyncFunctionDef) and node.name=="get_visit_details":
                node=copy.deepcopy(node)
                branch=next(p for p in node.body if isinstance(p,ast.If))
                approved=ast.parse(
                    'access = await get_current_field_capability_access(current=current, db=db)\n'
                    'await require_field_capability("visit.read")(access=access)'
                ).body
                self.assertEqual(digest(branch.body[:2]),digest(approved))
                branch.body=branch.body[2:]
            if isinstance(node, ast.AsyncFunctionDef) and node.name in FROZEN_FUNCTIONS:
                continue
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_load_handshake_lines_for_update":
                self.assertEqual(digest([node]), digest([self.approved_functions[node.name]]))
                continue
            if isinstance(node, ast.ImportFrom) and node.module == "api.field_transfer_contracts":
                self.assertEqual([alias.name for alias in node.names],
                    ["field_transfer_batch_route", "transfer_batch_error", "attributed_transfer_error"])
                continue
            if isinstance(node, ast.ImportFrom) and node.module == "api.field_visit_contracts":
                self.assertEqual([alias.name for alias in node.names], FIELD_IMPORTS)
                continue
            remainder.append(node)
        baseline = [
            node for node in self.baseline_tree.body
            if not (isinstance(node, ast.AsyncFunctionDef) and
                    (node.name in FROZEN_FUNCTIONS or node.name == "_load_handshake_lines_for_update"))
        ]
        self.assertEqual(digest(remainder), digest(baseline))

    def test_terminal_plan_normalization_rejects_missing_duplicate_or_reordered_hooks(self):
        for name in ("respond_to_transfer", "batch_respond_to_transfers"):
            original = self.functions[name]
            for mode in ("missing", "duplicate", "reordered"):
                node = copy.deepcopy(original)
                block = next(part.body for part in ast.walk(node) if isinstance(part, (ast.Try, ast.If))
                    and any(isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Await)
                        and isinstance(statement.value.value, ast.Call)
                        and isinstance(statement.value.value.func, ast.Name)
                        and statement.value.value.func.id == "lock_session_load_plan" for statement in part.body))
                index = next(i for i, part in enumerate(block) if isinstance(part, ast.Expr)
                    and isinstance(part.value, ast.Await) and isinstance(part.value.value, ast.Call)
                    and isinstance(part.value.value.func, ast.Name) and part.value.value.func.id == "lock_session_load_plan")
                if mode == "missing":
                    block.pop(index)
                elif mode == "duplicate":
                    block.insert(index, copy.deepcopy(block[index]))
                else:
                    block[index], block[index + 1] = block[index + 1], block[index]
                with self.subTest(endpoint=name, mutation=mode), self.assertRaises(AssertionError):
                    without_load_plan_reconciliation(node)

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
