from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_SOURCE = (
    ROOT / "api" / "warehouse" / "whole_product_quality_preview.py"
).read_text(encoding="utf-8")
COSTING_SOURCE = (
    ROOT / "domains" / "inventory_costing" / "service.py"
).read_text(encoding="utf-8")


def test_preview_is_read_only_and_discovers_only_positive_current_physical_batches():
    assert '@router.get(' in PREVIEW_SOURCE
    assert '"/warehouse/quality/products/{product_variant_id}/resolve-preview"' in PREVIEW_SOURCE
    assert "InventoryBalance.product_variant_id == int(product_variant_id)" in PREVIEW_SOURCE
    assert "InventoryBalance.on_hand_quantity > 0" in PREVIEW_SOURCE
    assert 'ProductBatch.batch_number.label("batch_number")' in PREVIEW_SOURCE
    assert "batch_quantities[batch_id] += quantity" in PREVIEW_SOURCE
    assert '"batch_number": batch_numbers[batch_id]' in PREVIEW_SOURCE
    assert "for batch_id in sorted(batch_quantities)" in PREVIEW_SOURCE
    assert "Historical ProductBatch rows with zero on-hand never enter this list." in PREVIEW_SOURCE
    assert "InventoryLocation.code" not in PREVIEW_SOURCE


def test_preview_reads_the_reason_from_the_current_recall_audit_event():
    assert 'DomainAuditEvent.event_type == "ProductRecallIssued"' in PREVIEW_SOURCE
    assert 'DomainAuditEvent.entity_type == "ProductVariant"' in PREVIEW_SOURCE
    assert "event.after_snapshot" in PREVIEW_SOURCE
    assert 'snapshot.get("lifecycle_revision")' in PREVIEW_SOURCE
    assert "event_revision != lifecycle_revision" in PREVIEW_SOURCE
    assert "event.reason_text" in PREVIEW_SOURCE
    assert '"issue_reason": issue_reason' in PREVIEW_SOURCE


def test_preview_preserves_non_warehouse_custody_as_visible_information_and_blocker():
    assert 'Literal["WAREHOUSE", "VEHICLE", "IN_TRANSIT", "SCRAP"]' in PREVIEW_SOURCE
    assert 'if location_type != "WAREHOUSE" or not bool(row.location_active):' in PREVIEW_SOURCE
    assert 'blocker_codes.add("WHOLE_PRODUCT_QUALITY_CUSTODY_BLOCKER")' in PREVIEW_SOURCE
    assert 'blocker_codes.add("WHOLE_PRODUCT_QUALITY_RESERVED_STOCK")' in PREVIEW_SOURCE


def test_preview_exposes_exact_reserved_quantity_for_operator_blocker_explanation():
    assert 'total_reserved_quantity = Decimal("0")' in PREVIEW_SOURCE
    assert 'total_reserved_quantity += Decimal(row.reserved_quantity or 0)' in PREVIEW_SOURCE
    assert '"total_reserved_quantity": canonical_quantity(total_reserved_quantity)' in PREVIEW_SOURCE


def test_moving_average_preview_uses_authoritative_cost_state_not_sale_or_last_purchase_price():
    assert "select(InventoryCostState)" in PREVIEW_SOURCE
    assert "state.average_unit_cost" in PREVIEW_SOURCE
    assert "state.inventory_value" in PREVIEW_SOURCE
    assert 'costing_method == "MOVING_AVERAGE"' in PREVIEW_SOURCE
    assert "last_purchase" not in PREVIEW_SOURCE
    assert "sale_price" not in PREVIEW_SOURCE
    assert "unit_price" not in PREVIEW_SOURCE


def test_fifo_preview_uses_remaining_financial_layers_and_refuses_mismatched_valuation():
    assert 'costing_method == "FIFO"' in PREVIEW_SOURCE
    assert "InventoryCostLayer.remaining_quantity" in PREVIEW_SOURCE
    assert "InventoryCostLayer.remaining_value" in PREVIEW_SOURCE
    assert 'valuation_reason = "FIFO_LAYER_QUANTITY_MISMATCH"' in PREVIEW_SOURCE
    assert 'valuation_reason = "FIFO_LAYER_VALUE_MISMATCH"' in PREVIEW_SOURCE
    assert "financial cost-flow are deliberately independent authorities" in COSTING_SOURCE


def test_preview_never_invents_book_value_when_costing_is_not_authoritative():
    assert 'valuation_reason = "COSTING_NOT_ACTIVE"' in PREVIEW_SOURCE
    assert 'valuation_reason = "COST_STATE_MISSING"' in PREVIEW_SOURCE
    assert 'valuation_reason = "COST_STATE_QUANTITY_MISMATCH"' in PREVIEW_SOURCE
    assert '"valuation_available": valuation_available' in PREVIEW_SOURCE
    assert '"total_book_value": total_book_value' in PREVIEW_SOURCE
