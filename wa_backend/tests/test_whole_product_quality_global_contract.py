from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_SOURCE = (ROOT / "api" / "warehouse" / "whole_product_quality.py").read_text(encoding="utf-8")
POLICY_SOURCE = (ROOT / "domains" / "inventory_whole_product_quality_policy.py").read_text(encoding="utf-8")
HANDLING_SOURCE = (ROOT / "domains" / "inventory_quality_handling.py").read_text(encoding="utf-8")


def test_client_cannot_choose_locations_batches_or_internal_destinations():
    request_block = API_SOURCE.split("class WholeProductQualityResolveRequest", 1)[1].split(
        "class WholeProductQualityLocationResult", 1
    )[0]
    assert "source_location_id" not in request_block
    assert "destination_location_id" not in request_block
    assert "batch_id" not in request_block
    assert "items:" not in request_block
    assert 'extra="forbid"' in request_block


def test_backend_discovers_all_company_stock_and_fails_closed_on_partial_ownership():
    assert "InventoryBalance.product_variant_id == int(product_variant_id)" in API_SOURCE
    assert "InventoryBalance.on_hand_quantity > 0" in API_SOURCE
    assert 'str(location_type).upper() != "WAREHOUSE"' in API_SOURCE
    assert "WHOLE_PRODUCT_QUALITY_CUSTODY_BLOCKER" in API_SOURCE
    assert "WHOLE_PRODUCT_QUALITY_RESERVED_STOCK" in API_SOURCE
    assert "codes_by_location(location_ids)" in API_SOURCE
    assert '"inventory.read", "transfer.send", terminal_permission' in API_SOURCE


def test_whole_product_action_is_one_transaction_with_backend_owned_batch_detail():
    assert "validate_special_transfer_source_items_locked" in API_SOURCE
    assert "quality_issue_stage=True" in API_SOURCE
    assert "stage_quality_handling_direct" in API_SOURCE
    assert "confirm_final_disposal" in API_SOURCE
    assert "confirm_vendor_handover" in API_SOURCE
    assert "complete_idempotent_operation(idem, response_payload)" in API_SOURCE
    assert "await db.commit()" in API_SOURCE
    assert "await db.rollback()" in API_SOURCE


def test_whole_product_policy_is_system_managed_in_place_evidence():
    assert 'WHOLE_PRODUCT_QUALITY_POLICY_CODE = "INVENTORY_WHOLE_PRODUCT_QUALITY_IN_PLACE"' in POLICY_SOURCE
    assert '"mode": "IN_PLACE"' in POLICY_SOURCE
    assert '"scope": "WHOLE_PRODUCT_QUALITY"' in POLICY_SOURCE
    assert "pg_advisory_xact_lock" in POLICY_SOURCE
    assert "destination_location_id=location_id" in API_SOURCE
    assert "stock remains at" in HANDLING_SOURCE


def test_global_action_keeps_per_batch_terminal_audit_but_never_exposes_batch_choice():
    assert "uuid5(" in API_SOURCE
    assert "SystemAuditLog(" in API_SOURCE
    assert '"WHOLE_PRODUCT_QUALITY_DISPOSED"' in API_SOURCE
    assert '"WHOLE_PRODUCT_QUALITY_RETURNED_TO_VENDOR"' in API_SOURCE
    assert '"locations": response_locations' in API_SOURCE
