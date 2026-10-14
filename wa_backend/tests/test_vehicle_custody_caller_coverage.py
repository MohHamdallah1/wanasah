from __future__ import annotations

import ast
from pathlib import Path
import unittest


BACKEND = Path(__file__).resolve().parents[1]
DISPATCH = BACKEND / "api" / "dispatch.py"
DRIVER = BACKEND / "api" / "driver.py"

STRICT_PUBLIC_RESOLVER = "resolve_vehicle_custody_location_id"
STRICT_DISPATCH_ADAPTER = "_dispatch_vehicle_location_id"


def _module(path: Path) -> tuple[str, ast.Module]:
    source = path.read_text(encoding="utf-8")
    return source, ast.parse(source)


def _function(path: Path, name: str) -> tuple[str, ast.AsyncFunctionDef | ast.FunctionDef]:
    source, tree = _module(path)
    for node in tree.body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return source, node
    raise AssertionError(f"function {name!r} not found in {path}")


def _function_source(path: Path, name: str) -> str:
    source, node = _function(path, name)
    segment = ast.get_source_segment(source, node)
    assert segment is not None
    return segment


def _called_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _calls(path: Path, name: str) -> list[ast.Call]:
    _, node = _function(path, name)
    return [item for item in ast.walk(node) if isinstance(item, ast.Call)]


def _call_names(path: Path, name: str) -> set[str]:
    return {called for call in _calls(path, name) if (called := _called_name(call))}


def _calls_named(path: Path, name: str, callee: str) -> list[ast.Call]:
    return [call for call in _calls(path, name) if _called_name(call) == callee]


def _keyword_names(call: ast.Call) -> set[str]:
    return {keyword.arg for keyword in call.keywords if keyword.arg is not None}


def _assert_strict_delegate(test: unittest.TestCase, path: Path, function: str) -> None:
    names = _call_names(path, function)
    test.assertTrue(
        {STRICT_PUBLIC_RESOLVER, STRICT_DISPATCH_ADAPTER} & names,
        f"{path.name}:{function} selects canonical Vehicle custody without delegating "
        "to the strict Vehicles custody seam",
    )


class VehicleCustodyCallerArchitectureGate(unittest.TestCase):
    """Regression gate for canonical VEHICLE custody identity selection.

    This intentionally classifies callers rather than banning every reference to
    InventoryLocation.vehicle_id. Reading all historical custody rows is allowed;
    choosing one row as canonical identity is not allowed outside the strict seam.
    """

    def test_no_hidden_direct_canonical_vehicle_location_selector_bypasses_strict_seam(self):
        # Repository-wide architecture guard for these two legacy operational APIs.
        # We only classify functions that both inspect a VEHICLE mapping and then use
        # a one-row-selection primitive. Pure all-row historical inspection remains
        # outside this ban unless it subsequently chooses one row (for example via
        # setdefault).
        offenders: list[str] = []
        for path in (DISPATCH, DRIVER):
            source, tree = _module(path)
            for node in tree.body:
                if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    continue
                segment = ast.get_source_segment(source, node) or ""
                if not (
                    "InventoryLocation" in segment
                    and "vehicle_id" in segment
                    and '"VEHICLE"' in segment
                ):
                    continue
                names = {
                    called
                    for call in ast.walk(node)
                    if isinstance(call, ast.Call)
                    and (called := _called_name(call)) is not None
                }
                chooses_one = bool(
                    {"scalar_one_or_none", "first", "limit", "setdefault"} & names
                )
                if not chooses_one:
                    continue
                if {STRICT_PUBLIC_RESOLVER, STRICT_DISPATCH_ADAPTER} & names:
                    continue
                offenders.append(f"{path.name}:{node.name}")

        self.assertEqual(
            offenders,
            [],
            "Direct canonical VEHICLE location selection bypasses the strict custody "
            f"seam: {', '.join(offenders)}",
        )
    def test_driver_canonical_vehicle_location_selectors_delegate_to_strict_seam(self):
        # These functions choose/use one Vehicle custody identity for live operations
        # or a live inventory projection, so direct active-row lookup is forbidden.
        for function in (
            "update_visit",
            "_load_active_driver_route_and_vehicle_location",
            "_load_vehicle_inventory_projection",
        ):
            with self.subTest(function=function):
                _assert_strict_delegate(self, DRIVER, function)

    def test_handshake_acceptance_routes_through_the_classified_vehicle_locator(self):
        helper = "_load_active_driver_route_and_vehicle_location"
        for function in ("respond_to_transfer", "batch_respond_to_transfers"):
            with self.subTest(function=function):
                self.assertIn(
                    helper,
                    _call_names(DRIVER, function),
                    f"driver.{function} must resolve accepted HANDSHAKE Vehicle custody "
                    "through the classified locator helper",
                )
        _assert_strict_delegate(self, DRIVER, helper)

    def test_dispatch_session_projection_never_chooses_first_historical_location(self):
        function = "_dispatch_session_inventory_projection"
        source = _function_source(DISPATCH, function)
        names = _call_names(DISPATCH, function)

        self.assertNotIn(
            "setdefault",
            names,
            "Dispatch session projection must not choose the first ordered VEHICLE row "
            "as canonical custody",
        )
        self.assertNotIn(
            "first_location_by_vehicle",
            source,
            "Dispatch session projection still contains first-row-wins custody selection",
        )
        _assert_strict_delegate(self, DISPATCH, function)

    def test_dispatch_init_advertises_only_strict_custody_ready_vehicles(self):
        # Operational state alone is insufficient: an advertised Vehicle must also
        # have exactly one active canonical VEHICLE custody mapping.
        _assert_strict_delegate(self, DISPATCH, "dispatch_init")

    def test_start_work_session_uses_strict_custody_and_revalidates_expected_location(self):
        source = _function_source(DRIVER, "start_work_session")
        calls = _calls_named(DRIVER, "start_work_session", STRICT_PUBLIC_RESOLVER)
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(
            any("expected_location_id" in _keyword_names(call) for call in calls),
            "Driver session start must revalidate the same canonical custody location "
            "after acquiring its location guard",
        )
        self.assertNotIn("limit(1)", source[source.find(STRICT_PUBLIC_RESOLVER):])

    def test_dispatch_route_create_uses_strict_custody_seam(self):
        _assert_strict_delegate(self, DISPATCH, "dispatch_route")

    def test_route_inventory_adjustment_revalidates_strict_custody(self):
        calls = _calls_named(DISPATCH, "adjust_route_inventory", STRICT_DISPATCH_ADAPTER)
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(
            any("expected_location_id" in _keyword_names(call) for call in calls),
            "Route inventory adjustment must revalidate canonical custody after the "
            "exclusive InventoryLocation guard is held",
        )

    def test_historical_all_row_inspection_is_allowed_only_without_canonical_first_row_choice(self):
        # This Dispatch helper intentionally returns every historical VEHICLE location
        # for reconciliation inspection. It is permitted precisely because it does not
        # silently reduce the set to one canonical row.
        function = "_dispatch_vehicle_location_ids"
        source = _function_source(DISPATCH, function)
        names = _call_names(DISPATCH, function)
        self.assertIn("scalars", names)
        self.assertIn("all", names)
        self.assertNotIn("limit", names)
        self.assertNotIn("first", names)
        self.assertNotIn("scalar_one_or_none", names)
        self.assertNotIn("setdefault", names)
        self.assertNotIn("is_active=True", source)

    def test_absolute_targets_passes_legacy_actor_keyword_to_pack_delta_seam(self):
        calls = _calls_named(DISPATCH, "_dispatch_absolute_targets", "_dispatch_apply_pack_deltas")
        self.assertEqual(len(calls), 1)
        keywords = _keyword_names(calls[0])
        self.assertIn(
            "legacy_actor_id",
            keywords,
            "_dispatch_absolute_targets must forward legacy_actor_id to "
            "_dispatch_apply_pack_deltas",
        )
        self.assertNotIn(
            "admin",
            keywords,
            "admin=admin is an invalid/pre-existing keyword contract and would break "
            "the route-status inventory path",
        )


if __name__ == "__main__":
    unittest.main()

