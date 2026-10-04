from pathlib import Path

import pytest
from pydantic import ValidationError

from schemas import TerminalVendorHandoverRequest

ROOT = Path(__file__).resolve().parents[1]


def _valid_request():
    return {
        "request_id": "00000000-0000-0000-0000-000000000223",
        "source_location_id": 6,
        "product_variant_id": 7,
        "batch_id": 11,
        "source_status": "QUARANTINED",
        "quantity": "2.500000",
        "vendor_name": "Supplier A",
        "vendor_reference": "RMA-44",
        "handover_reference": "RECEIPT-2026-001",
    }


def test_vendor_handover_request_requires_counterparty_evidence_and_positive_quantity():
    valid = _valid_request()
    assert TerminalVendorHandoverRequest.model_validate(valid).quantity > 0
    for field in ("vendor_name", "vendor_reference", "handover_reference"):
        with pytest.raises(ValidationError):
            TerminalVendorHandoverRequest.model_validate({**valid, field: "   "})
    with pytest.raises(ValidationError):
        TerminalVendorHandoverRequest.model_validate({**valid, "quantity": "0"})
    with pytest.raises(ValidationError):
        TerminalVendorHandoverRequest.model_validate({**valid, "source_status": "AVAILABLE"})


def test_vendor_handover_is_exact_location_scoped_and_idempotent():
    access = (ROOT / "inventory_access.py").read_text(encoding="utf-8")
    api = (ROOT / "api" / "warehouse" / "transfers.py").read_text(encoding="utf-8")
    assert "'inventory.vendor_return.confirm'" in access
    company_only = access.split("COMPANY_ONLY = frozenset({", 1)[1].split("})", 1)[0]
    assert "inventory.vendor_return.confirm" not in company_only
    assert 'await access.require("inventory.vendor_return.confirm", payload.source_location_id)' in api
    assert 'operation="INVENTORY_FINAL_VENDOR_HANDOVER"' in api
    assert 'complete_idempotent_operation(idempotency_record, response_payload)' in api


def test_vendor_handover_uses_return_to_vendor_staging_and_immutable_evidence():
    source = (ROOT / "domains" / "inventory_terminal_vendor.py").read_text(encoding="utf-8")
    provenance = (ROOT / "domains" / "inventory_terminal_provenance.py").read_text(encoding="utf-8")
    assert 'transfer_purpose="RETURN_TO_VENDOR"' in source
    assert '"destination_location_id": None' in source
    assert '"movement_kind": "PHYSICAL"' in source
    assert '"reference_type": FINAL_VENDOR_HANDOVER_REFERENCE_TYPE' in source
    assert '"reference_id": str(request_id)' in source
    assert 'record_domain_event(' in source and 'emit_outbox=True' in source
    assert 'InventoryTransferHeader.status == "POSTED"' in provenance
    assert 'InventoryMovement.transfer_header_id.in_(header_ids)' in provenance
    assert 'balance.on_hand_quantity =' not in source
