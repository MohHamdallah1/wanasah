"""Backend-only structural contract for the R4 adaptive search path."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess


SOURCE_PATH = "wa_backend/api/warehouse/live_stock.py"
SOURCE = Path(__file__).resolve().parents[1] / "api" / "warehouse" / "live_stock.py"
BASE_SHA = os.getenv(
    "R4_OPT_BASE_SHA",
    "8a74834fc80e434c15eec99de45cb1c96cdeed56",
)


def _function(source: str, name: str):
    tree = ast.parse(source)
    return next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )


def test_r4_search_path_is_page_adaptive_without_frontend_authority():
    source = SOURCE.read_text(encoding="utf-8")
    node = _function(source, "get_warehouse_inventory")
    body = ast.unparse(node)

    assert "live_stock_search_variant_ids" in body
    assert "inventory_search_probe" in body
    assert ".limit(limit + 1)" in body
    assert "search_probe_count <= limit" in body
    assert "search_probe_count > limit" in body
    assert "ProductVariant.id.in_(search_probe_ids)" in body
    assert "strpos(searchable_text, token) > 0" in body
    literal_calls = [
        part
        for part in ast.walk(node)
        if isinstance(part, ast.Call)
        and isinstance(part.func, ast.Name)
        and part.func.id == "literal_column"
    ]
    assert len(literal_calls) == 1
    assert isinstance(literal_calls[0].args[0], ast.Constant)
    assert literal_calls[0].args[0].value == "' '"
    assert "union_all(sparse_stmt, broad_stmt)" in body
    assert "inventory_single_search_probe" not in body

    # R1 remains one candidate/detail SQL statement; no second search response
    # or Python-side membership/filtering is introduced.
    assert "inventory_page_candidates" in body
    assert "inventory_detail_keys" in body
    assert "await db.execute(detail_stmt)" in body



def test_positive_stock_filters_drive_from_sparse_projection():
    source = SOURCE.read_text(encoding="utf-8")
    node = _function(source, "_live_stock_filtered_variant_ids_stmt")
    body = ast.unparse(node)

    assert "projection_guaranteed" in body
    for token in (
        "stock_state in {'on_hand', 'sellable', 'low_stock'}",
        "has_reserved",
        "has_unavailable",
        "has_damaged",
        "has_recalled",
        "has_vehicle",
    ):
        assert token in body
    assert "select(projection.product_variant_id.label('id'))" in body
    assert "projection.warehouse_location_id == location_id" in body
    assert "variant.company_id == projection.company_id" in body
    assert "variant.id == projection.product_variant_id" in body
    assert "variant.lifecycle_status == 'ACTIVE'" in body
    assert "variant.operational_hold == 'NONE'" in body

    # Missing projection rows are meaningful for these two filters, so the
    # outer-join fallback must remain instead of changing their membership.
    assert "stock_state == 'out_of_stock'" in body
    assert "minimum_unset" in body
    assert ".outerjoin(projection" in body



def test_vehicle_and_recall_filters_drive_the_page_from_materialized_ids():
    source = SOURCE.read_text(encoding="utf-8")
    node = _function(source, "get_warehouse_inventory")
    body = ast.unparse(node)

    assert "if has_vehicle or has_recalled" in body
    assert "inventory_selective_filtered_ids" in body
    assert "selective_filtered_ids.c.id == ProductVariant.id" in body
    assert "ProductVariant.id.in_(filtered_ids)" in body
    # Only measured selective filters bypass the ordinary membership path;
    # other stock filters retain the existing candidate strategy.
    assert "else:\n                candidate_filters.append(ProductVariant.id.in_(filtered_ids))" in body

def test_unmodified_live_stock_query_families_stay_exact_base():
    current = SOURCE.read_text(encoding="utf-8")
    base = subprocess.check_output(
        ["git", "show", f"{BASE_SHA}:{SOURCE_PATH}"],
        text=True,
    )
    for name in (
        "get_warehouse_inventory_summary",
        "get_warehouse_inventory_alert_summary",
        "get_warehouse_inventory_families",
        "get_warehouse_inventory_batches",
        "get_batch_stock_sources",
    ):
        assert ast.dump(
            _function(current, name), include_attributes=False
        ) == ast.dump(
            _function(base, name), include_attributes=False
        ), name
