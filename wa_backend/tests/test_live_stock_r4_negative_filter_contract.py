"""Structural contract for the R4 negative-filter anti-join path."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess


SOURCE_PATH = "wa_backend/api/warehouse/live_stock.py"
SOURCE = Path(__file__).resolve().parents[1] / "api" / "warehouse" / "live_stock.py"
BASE_SHA = os.getenv(
    "R4_NEGATIVE_BASE_SHA",
    "c3687f49e2424d783fa3f7a91598ab232b176793",
)


def _function(source: str, name: str):
    return next(
        node
        for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )


def test_negative_filters_use_correlated_anti_exists_only_when_projection_is_not_guaranteed():
    source = SOURCE.read_text(encoding="utf-8")
    body = ast.unparse(_function(source, "get_warehouse_inventory"))

    assert "positive_projection_filter_active" in body
    assert "use_negative_projection_antijoin" in body
    assert "effective_stock_state in {'all', 'out_of_stock'}" in body
    assert "effective_stock_state == 'out_of_stock' or minimum_unset" in body
    assert "live_stock_negative_projection" in body
    assert "positive_sellable_projection" in body
    assert "configured_minimum_projection" in body
    assert "negative_projection.warehouse_sellable_on_hand > negative_projection.warehouse_sellable_reserved" in body
    assert "negative_projection.minimum_quantity > 0" in body
    assert "ProductVariant.lifecycle_status != 'ACTIVE'" in body
    assert "ProductVariant.operational_hold != 'NONE'" in body
    assert "~positive_sellable_projection" in body
    assert "~configured_minimum_projection" in body

    # Positive projection predicates keep the accepted #675 projection-driven
    # path; this change must not route them through negative anti-joins.
    assert "not positive_projection_filter_active" in body
    assert "not use_negative_projection_antijoin" in body
    assert "_live_stock_filtered_variant_ids_stmt(" in body


def _normalize_r3_vehicle_filter_contract(function):
    """Ignore only the owner-approved R3 Vehicle-custody semantic delta.

    R4 still owns every Warehouse projection/negative-filter decision. R3 is
    allowed to remove has_vehicle from the projection-guaranteed shortcut and
    replace only the has_vehicle branch with a canonical physical-location read.
    """
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name)
            and target.id == "projection_guaranteed"
            for target in node.targets
        ):
            if not isinstance(node.value, ast.BoolOp):
                raise AssertionError(
                    "projection_guaranteed shape changed outside R3 scope"
                )
            node.value.values = [
                value
                for value in node.value.values
                if not (
                    isinstance(value, ast.Name)
                    and value.id == "has_vehicle"
                )
            ]
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "has_vehicle"
        ):
            node.body = [ast.Pass()]
    return function


def test_existing_warehouse_projection_filter_authority_is_unchanged_from_exact_base():
    current = SOURCE.read_text(encoding="utf-8")
    base = subprocess.check_output(
        ["git", "show", f"{BASE_SHA}:{SOURCE_PATH}"],
        text=True,
    )
    current_filter = _function(
        current, "_live_stock_filtered_variant_ids_stmt"
    )
    base_filter = _function(
        base, "_live_stock_filtered_variant_ids_stmt"
    )
    assert ast.dump(
        _normalize_r3_vehicle_filter_contract(current_filter),
        include_attributes=False,
    ) == ast.dump(
        _normalize_r3_vehicle_filter_contract(base_filter),
        include_attributes=False,
    )

    rendered = ast.unparse(
        _function(current, "_live_stock_filtered_variant_ids_stmt")
    )
    assert "_readable_vehicle_locations_subquery" in rendered
    assert "InventoryBalance.on_hand_quantity > 0" in rendered
    assert "_latest_readable_vehicle_sources_subquery" not in rendered
    assert "DispatchRoute" not in rendered
    assert "projection.vehicle_packs" not in rendered
