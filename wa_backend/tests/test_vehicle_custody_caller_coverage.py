from __future__ import annotations

import ast
from pathlib import Path
import textwrap
import unittest


BACKEND = Path(__file__).resolve().parents[1]
DISPATCH = BACKEND / "api" / "dispatch.py"
DRIVER = BACKEND / "api" / "driver.py"

STRICT_IDENTITY_SEAMS = {
    "resolve_vehicle_custody_location_id",
    "resolve_vehicle_custody_location_ids",
    "_dispatch_vehicle_location_id",
    "_driver_vehicle_custody_location_id",
}
STRICT_PUBLIC_RESOLVER = "resolve_vehicle_custody_location_id"
STRICT_BULK_RESOLVER = "resolve_vehicle_custody_location_ids"
STRICT_DISPATCH_ADAPTER = "_dispatch_vehicle_location_id"
STRICT_DRIVER_ADAPTER = "_driver_vehicle_custody_location_id"
READINESS_PREDICATE = "vehicle_custody_ready_predicate"
ONE_ROW_METHODS = {"limit", "first", "scalar_one_or_none", "one_or_none", "scalar"}


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _function(path: Path, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    for node in _module(path).body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found in {path}")


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _calls(node: ast.AST) -> list[ast.Call]:
    return [item for item in ast.walk(node) if isinstance(item, ast.Call)]


def _call_names(node: ast.AST) -> set[str]:
    return {name for call in _calls(node) if (name := _called_name(call))}


def _calls_named(node: ast.AST, callee: str) -> list[ast.Call]:
    return [call for call in _calls(node) if _called_name(call) == callee]


def _keyword_names(call: ast.Call) -> set[str]:
    return {keyword.arg for keyword in call.keywords if keyword.arg is not None}


def _assignment_value(node: ast.AST, target_name: str) -> ast.AST:
    for item in ast.walk(node):
        if not isinstance(item, (ast.Assign, ast.AnnAssign)):
            continue
        targets = item.targets if isinstance(item, ast.Assign) else [item.target]
        if any(isinstance(target, ast.Name) and target.id == target_name for target in targets):
            return item.value
    raise AssertionError(f"assignment for {target_name!r} not found")


def _has_name(node: ast.AST, name: str) -> bool:
    return any(isinstance(item, ast.Name) and item.id == name for item in ast.walk(node))


def _has_attribute(node: ast.AST, attr: str) -> bool:
    return any(isinstance(item, ast.Attribute) and item.attr == attr for item in ast.walk(node))


def _has_keyword(node: ast.AST, keyword_name: str) -> bool:
    return any(
        isinstance(item, ast.keyword) and item.arg == keyword_name
        for item in ast.walk(node)
    )


def _has_vehicle_marker(node: ast.AST) -> bool:
    for item in ast.walk(node):
        if isinstance(item, ast.Constant) and item.value == "VEHICLE":
            return True
        if isinstance(item, ast.Name) and item.id == "VEHICLE":
            return True
        if isinstance(item, ast.Attribute) and item.attr == "VEHICLE":
            return True
    return False


def _is_vehicle_custody_query(node: ast.AST) -> bool:
    return (
        _has_name(node, "InventoryLocation")
        and (_has_attribute(node, "vehicle_id") or _has_keyword(node, "vehicle_id"))
        and (_has_attribute(node, "location_type") or _has_keyword(node, "location_type"))
        and _has_vehicle_marker(node)
    )


def _is_inventory_location_id_attribute(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "id"
        and isinstance(node.value, ast.Name)
        and node.value.id == "InventoryLocation"
    )


def _has_exact_location_predicate(node: ast.AST) -> bool:
    for item in ast.walk(node):
        if isinstance(item, ast.keyword) and item.arg == "id":
            return True
        if isinstance(item, ast.Compare):
            if _is_inventory_location_id_attribute(item.left):
                return True
            if any(_is_inventory_location_id_attribute(part) for part in item.comparators):
                return True
    return False


def _has_inventory_location_active_predicate(node: ast.AST) -> bool:
    for item in ast.walk(node):
        if isinstance(item, ast.keyword) and item.arg == "is_active":
            return True
        if isinstance(item, ast.Attribute) and item.attr == "is_active":
            if isinstance(item.value, ast.Name) and item.value.id == "InventoryLocation":
                return True
    return False


def _target_names(node: ast.Assign | ast.AnnAssign) -> set[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return {target.id for target in targets if isinstance(target, ast.Name)}


def _uses_names(node: ast.AST, names: set[str]) -> bool:
    return any(isinstance(item, ast.Name) and item.id in names for item in ast.walk(node))


def _query_flow(function: ast.AsyncFunctionDef | ast.FunctionDef) -> tuple[set[str], set[str]]:
    assignments = [
        item for item in ast.walk(function)
        if isinstance(item, (ast.Assign, ast.AnnAssign))
    ]
    custody_names: set[str] = set()
    exact_names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for assignment in assignments:
            value = assignment.value
            names = _target_names(assignment)
            if not names:
                continue
            custody = _is_vehicle_custody_query(value) or _uses_names(value, custody_names)
            exact = (
                (_is_vehicle_custody_query(value) and _has_exact_location_predicate(value))
                or _uses_names(value, exact_names)
            )
            if custody and not names.issubset(custody_names):
                custody_names.update(names)
                changed = True
            if exact and not names.issubset(exact_names):
                exact_names.update(names)
                changed = True
    return custody_names, exact_names


def _expression_uses_custody(
    node: ast.AST,
    custody_names: set[str],
) -> bool:
    return _is_vehicle_custody_query(node) or _uses_names(node, custody_names)


def _expression_is_exact_known_location(
    node: ast.AST,
    exact_names: set[str],
) -> bool:
    return (
        (_is_vehicle_custody_query(node) and _has_exact_location_predicate(node))
        or _uses_names(node, exact_names)
    )


def _direct_custody_bypasses(
    function: ast.AsyncFunctionDef | ast.FunctionDef,
) -> list[str]:
    custody_names, exact_names = _query_flow(function)
    violations: list[str] = []

    for call in _calls(function):
        called = _called_name(call)
        if called not in ONE_ROW_METHODS:
            continue
        if not _expression_uses_custody(call, custody_names):
            continue
        if _expression_is_exact_known_location(call, exact_names):
            continue
        violations.append(f"{function.name}:{called}@{call.lineno}")

    for item in ast.walk(function):
        if isinstance(item, ast.Subscript):
            zero_index = isinstance(item.slice, ast.Constant) and item.slice.value == 0
            if zero_index and _expression_uses_custody(item.value, custody_names):
                if not _expression_is_exact_known_location(item.value, exact_names):
                    violations.append(f"{function.name}:rows[0]@{item.lineno}")

        if isinstance(item, ast.Call) and _called_name(item) == "next" and item.args:
            candidate = item.args[0]
            if (
                isinstance(candidate, ast.Call)
                and _called_name(candidate) == "iter"
                and candidate.args
                and _expression_uses_custody(candidate.args[0], custody_names)
                and not _expression_is_exact_known_location(candidate.args[0], exact_names)
            ):
                violations.append(f"{function.name}:next(iter(...))@{item.lineno}")

        if isinstance(item, (ast.For, ast.AsyncFor)):
            if not _expression_uses_custody(item.iter, custody_names):
                continue
            if _expression_is_exact_known_location(item.iter, exact_names):
                continue
            if any(_called_name(call) == "setdefault" for call in _calls(item)):
                violations.append(f"{function.name}:setdefault@{item.lineno}")

    return sorted(set(violations))


def _scan_source(source: str) -> list[str]:
    tree = ast.parse(textwrap.dedent(source))
    violations: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            violations.extend(_direct_custody_bypasses(node))
    return violations


def _assert_identity_delegate(
    test: unittest.TestCase,
    path: Path,
    function_name: str,
    *,
    allowed: set[str] | None = None,
) -> None:
    function = _function(path, function_name)
    seams = STRICT_IDENTITY_SEAMS if allowed is None else allowed
    test.assertTrue(
        seams & _call_names(function),
        f"{path.name}:{function_name} must delegate Vehicle custody identity to a strict seam",
    )


class VehicleCustodyCallerArchitectureGate(unittest.TestCase):
    def test_no_hidden_direct_canonical_vehicle_location_selector_bypasses_strict_seams(self):
        offenders: list[str] = []
        for path in (DISPATCH, DRIVER):
            for node in _module(path).body:
                if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    continue
                for violation in _direct_custody_bypasses(node):
                    offenders.append(f"{path.name}:{violation}")
        self.assertEqual(offenders, [])

    def test_driver_canonical_vehicle_callers_use_driver_strict_adapter(self):
        for function_name in (
            "update_visit",
            "_load_active_driver_route_and_vehicle_location",
            "_load_vehicle_inventory_projection",
        ):
            with self.subTest(function=function_name):
                _assert_identity_delegate(
                    self,
                    DRIVER,
                    function_name,
                    allowed={STRICT_DRIVER_ADAPTER},
                )

    def test_driver_adapter_delegates_to_public_strict_resolver_and_has_no_direct_selector(self):
        adapter = _function(DRIVER, STRICT_DRIVER_ADAPTER)
        self.assertIn(STRICT_PUBLIC_RESOLVER, _call_names(adapter))
        self.assertEqual(_direct_custody_bypasses(adapter), [])

    def test_handshake_acceptance_routes_through_classified_vehicle_locator(self):
        helper = "_load_active_driver_route_and_vehicle_location"
        for function_name in ("respond_to_transfer", "batch_respond_to_transfers"):
            with self.subTest(function=function_name):
                self.assertIn(helper, _call_names(_function(DRIVER, function_name)))

    def test_dispatch_session_projection_uses_strict_bulk_identity_without_first_row_reduction(self):
        function = _function(DISPATCH, "_dispatch_session_inventory_projection")
        self.assertIn(STRICT_BULK_RESOLVER, _call_names(function))
        self.assertEqual(_direct_custody_bypasses(function), [])

    def test_dispatch_init_applies_custody_readiness_to_visible_and_executable_vehicle_queries(self):
        function = _function(DISPATCH, "dispatch_init")
        for target in ("vehicles", "executable_vehicles"):
            with self.subTest(target=target):
                expression = _assignment_value(function, target)
                calls = _calls_named(expression, READINESS_PREDICATE)
                self.assertGreaterEqual(len(calls), 1)
                self.assertTrue(
                    any(
                        call.args
                        and isinstance(call.args[0], ast.Name)
                        and call.args[0].id == "Vehicle"
                        for call in calls
                    ),
                    f"dispatch_init:{target} must apply {READINESS_PREDICATE}(Vehicle)",
                )

    def test_start_work_session_resolves_then_guards_then_revalidates_expected_location(self):
        function = _function(DRIVER, "start_work_session")
        strict_calls = _calls_named(function, STRICT_PUBLIC_RESOLVER)
        guards = _calls_named(function, "acquire_inventory_location_guard")
        self.assertGreaterEqual(len(strict_calls), 2)
        self.assertGreaterEqual(len(guards), 1)
        first_resolution = min(call.lineno for call in strict_calls)
        guard_line = min(call.lineno for call in guards)
        expected_revalidations = [
            call for call in strict_calls
            if "expected_location_id" in _keyword_names(call)
        ]
        self.assertTrue(expected_revalidations)
        self.assertLess(first_resolution, guard_line)
        self.assertTrue(any(guard_line < call.lineno for call in expected_revalidations))
        self.assertEqual(_direct_custody_bypasses(function), [])

    def test_dispatch_route_create_uses_dispatch_strict_adapter(self):
        _assert_identity_delegate(
            self,
            DISPATCH,
            "dispatch_route",
            allowed={STRICT_DISPATCH_ADAPTER},
        )

    def test_route_inventory_adjustment_revalidates_expected_custody_through_dispatch_adapter(self):
        function = _function(DISPATCH, "adjust_route_inventory")
        calls = _calls_named(function, STRICT_DISPATCH_ADAPTER)
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(
            any("expected_location_id" in _keyword_names(call) for call in calls),
            "route inventory adjustment must revalidate the same canonical custody location",
        )

    def test_historical_vehicle_location_helper_enumerates_all_history_without_active_filter_or_reduction(self):
        function = _function(DISPATCH, "_dispatch_vehicle_location_ids")
        custody_queries = [
            item for item in ast.walk(function)
            if isinstance(item, ast.Call) and _is_vehicle_custody_query(item)
        ]
        self.assertTrue(custody_queries)
        self.assertIn("scalars", _call_names(function))
        self.assertIn("all", _call_names(function))
        self.assertFalse(any(_has_inventory_location_active_predicate(query) for query in custody_queries))
        self.assertEqual(_direct_custody_bypasses(function), [])

    def test_scanner_rejects_common_direct_custody_bypasses(self):
        fixtures = {
            "active_only": """
                async def candidate(db, company_id, vehicle_id):
                    return (await db.execute(
                        select(InventoryLocation.id).filter_by(
                            company_id=company_id,
                            vehicle_id=vehicle_id,
                            location_type='VEHICLE',
                            is_active=True,
                        )
                    )).scalar_one_or_none()
            """,
            "limit_one": """
                async def candidate(db, company_id, vehicle_id):
                    stmt = select(InventoryLocation.id).where(
                        InventoryLocation.company_id == company_id,
                        InventoryLocation.vehicle_id == vehicle_id,
                        InventoryLocation.location_type == 'VEHICLE',
                    )
                    return (await db.execute(stmt.limit(1))).scalars().first()
            """,
            "rows_zero": """
                async def candidate(db, company_id, vehicle_id):
                    rows = (await db.execute(
                        select(InventoryLocation.id).where(
                            InventoryLocation.company_id == company_id,
                            InventoryLocation.vehicle_id == vehicle_id,
                            InventoryLocation.location_type == 'VEHICLE',
                        )
                    )).scalars().all()
                    return rows[0]
            """,
            "next_iter": """
                async def candidate(db, company_id, vehicle_id):
                    rows = (await db.execute(
                        select(InventoryLocation.id).where(
                            InventoryLocation.company_id == company_id,
                            InventoryLocation.vehicle_id == vehicle_id,
                            InventoryLocation.location_type == 'VEHICLE',
                        )
                    )).scalars().all()
                    return next(iter(rows))
            """,
            "setdefault": """
                async def candidate(db, company_id, vehicle_ids):
                    rows = (await db.execute(
                        select(InventoryLocation.vehicle_id, InventoryLocation.id).where(
                            InventoryLocation.company_id == company_id,
                            InventoryLocation.vehicle_id.in_(vehicle_ids),
                            InventoryLocation.location_type == 'VEHICLE',
                        )
                    )).all()
                    result = {}
                    for vehicle_id, location_id in rows:
                        result.setdefault(vehicle_id, location_id)
                    return result
            """,
        }
        for name, source in fixtures.items():
            with self.subTest(name=name):
                self.assertTrue(_scan_source(source), name)

    def test_scanner_allows_strict_readiness_historical_and_unrelated_patterns(self):
        fixtures = {
            "unrelated_limit": """
                async def candidate(db, company_id):
                    stmt = select(WorkSession).where(WorkSession.company_id == company_id).limit(1)
                    return (await db.execute(stmt)).scalars().first()
            """,
            "historical_all": """
                async def candidate(db, company_id, vehicle_id):
                    return (await db.execute(
                        select(InventoryLocation.id).where(
                            InventoryLocation.company_id == company_id,
                            InventoryLocation.vehicle_id == vehicle_id,
                            InventoryLocation.location_type == 'VEHICLE',
                        )
                    )).scalars().all()
            """,
            "strict_singular": """
                async def candidate(db, company_id, vehicle_id):
                    return await resolve_vehicle_custody_location_id(
                        db, company_id=company_id, vehicle_id=vehicle_id, require_active=True
                    )
            """,
            "strict_bulk": """
                async def candidate(db, company_id, vehicle_ids):
                    return await resolve_vehicle_custody_location_ids(
                        db, company_id=company_id, vehicle_ids=vehicle_ids, require_active=False
                    )
            """,
            "readiness_predicate": """
                async def candidate(db, company_id):
                    return (await db.execute(
                        select(Vehicle).where(
                            Vehicle.company_id == company_id,
                            vehicle_custody_ready_predicate(Vehicle),
                        )
                    )).scalars().all()
            """,
            "known_location_revalidation": """
                async def candidate(db, company_id, vehicle_id, known_location_id):
                    return (await db.execute(
                        select(InventoryLocation.id).where(
                            InventoryLocation.company_id == company_id,
                            InventoryLocation.id == known_location_id,
                            InventoryLocation.vehicle_id == vehicle_id,
                            InventoryLocation.location_type == 'VEHICLE',
                        )
                    )).scalar_one_or_none()
            """,
            "historical_snapshot": """
                async def candidate(db, company_id, work_session_id):
                    return (await db.execute(
                        select(SessionInventorySnapshot.location_id).where(
                            SessionInventorySnapshot.company_id == company_id,
                            SessionInventorySnapshot.work_session_id == work_session_id,
                        ).limit(1)
                    )).scalar_one_or_none()
            """,
        }
        for name, source in fixtures.items():
            with self.subTest(name=name):
                self.assertEqual(_scan_source(source), [], name)


if __name__ == "__main__":
    unittest.main()
