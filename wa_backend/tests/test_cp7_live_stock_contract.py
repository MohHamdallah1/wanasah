from __future__ import annotations

import inspect
from pathlib import Path

from api.warehouse import live_stock, live_stock_source_detail


ROOT = Path(__file__).parents[1]


def test_live_stock_source_route_has_no_client_company_authority():
    signature = inspect.signature(live_stock_source_detail.get_live_stock_batch_source)
    assert "company_id" not in signature.parameters
    source = inspect.getsource(live_stock_source_detail.get_live_stock_batch_source)
    assert "company_id = access.company_id" in source
    assert "_require_live_stock_warehouse_read(" in source
    assert "InventoryBalance.location_id == location_id" in source
    assert "InventoryLocation.id == location_id" in source
    assert 'InventoryLocation.location_type == "WAREHOUSE"' in source


def test_live_stock_source_route_uses_canonical_inventory_read_without_shortcuts():
    source = (ROOT / "api" / "warehouse" / "live_stock_source_detail.py").read_text(
        encoding="utf-8"
    )
    assert ".is_admin" not in source
    assert "get_current_driver" not in source
    assert "get_current_admin" not in source
    assert "is_company_owner" not in source
    assert "access.company_id" in source
    assert "reservation_owner_projection(" in source
    assert "ProductVariant.lifecycle_status" in source
    assert "ProductVariant.operational_hold" in source
    assert '"lifecycle_status": str(metadata.lifecycle_status)' in source
    assert '"operational_hold": str(metadata.operational_hold)' in source


def test_live_stock_source_route_is_read_only_and_does_not_duplicate_business_truth():
    source = inspect.getsource(live_stock_source_detail.get_live_stock_batch_source)
    for forbidden in (
        "apply_inventory_movements",
        "allowed_batch_disposition_targets",
        "batch_metadata_is_sellable",
        "batch_sellability_predicate",
        "commit()",
        "delete(",
        "update(",
    ):
        assert forbidden not in source


def test_live_stock_cursor_binds_authoritative_filters_to_cursor_scope_before_page_query():
    source = inspect.getsource(live_stock.get_warehouse_inventory)
    scope_at = source.index('f"inventory|{company_id}|{location_id}|{clean_search}|"')
    page_at = source.index(".limit(limit + 1)")
    assert scope_at < page_at
    for token in (
        "effective_stock_state",
        "family_id or 0",
        "int(has_reserved)",
        "int(has_unavailable)",
        "int(has_damaged)",
        "int(has_recalled)",
        "int(has_vehicle)",
        "int(minimum_unset)",
        "|{sort}",
    ):
        assert token in source[scope_at:page_at]
    assert "expected_scope=scope" in source


def test_live_stock_batch_detail_is_exact_location_and_public_lot_only():
    source = inspect.getsource(live_stock.get_warehouse_inventory_batches)
    assert "InventoryBalance.location_id == location_id" in source
    assert "ProductBatch.company_id == company_id" in source
    assert '"batch_number": public_batch_number(row.batch_number)' in source
    assert "allowed_batch_disposition_targets" in source
    assert '"available_for_sale_quantity"' in source
    assert '"disposal_pending_quantity"' in source


def test_cp7_does_not_reintroduce_cp2_batch_index_into_live_stock():
    source = (ROOT / "api" / "warehouse" / "live_stock.py").read_text(encoding="utf-8")
    cp7 = (ROOT / "api" / "warehouse" / "live_stock_source_detail.py").read_text(
        encoding="utf-8"
    )
    assert "batch_index" not in cp7
    assert "get_warehouse_inventory_batch_index_cursor" not in source
