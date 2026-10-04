from pathlib import Path

import pytest
from pydantic import ValidationError

from schemas import TerminalDisposalConfirmRequest

ROOT = Path(__file__).resolve().parents[1]


def test_disposal_request_requires_positive_quantity_and_reason():
    valid = {
        "request_id": "00000000-0000-0000-0000-000000000123",
        "source_location_id": 5,
        "product_variant_id": 7,
        "batch_id": 11,
        "quantity": "2.500000",
        "reason": "Damaged stock destroyed under supervision",
    }
    assert TerminalDisposalConfirmRequest.model_validate(valid).quantity > 0

    with pytest.raises(ValidationError):
        TerminalDisposalConfirmRequest.model_validate({**valid, "quantity": "0"})
    with pytest.raises(ValidationError):
        TerminalDisposalConfirmRequest.model_validate({**valid, "reason": "   "})


def test_terminal_disposal_uses_unified_source_only_movement_and_evidence():
    source = (ROOT / "domains" / "inventory_terminal_quality.py").read_text(encoding="utf-8")
    assert '"source_stock_status": "DISPOSAL_PENDING"' in source
    assert '"destination_location_id": None' in source
    assert '"movement_kind": "PHYSICAL"' in source
    assert '"reference_type": FINAL_DISPOSAL_REFERENCE_TYPE' in source
    provenance = (ROOT / "domains" / "inventory_terminal_provenance.py").read_text(encoding="utf-8")
    assert 'InventoryTransferHeader.transfer_purpose == transfer_purpose' in provenance
    assert 'InventoryTransferHeader.status == "POSTED"' in provenance
    assert 'InventoryMovement.transfer_header_id.in_(header_ids)' in provenance
    assert 'record_domain_event(' in source
    assert 'emit_outbox=True' in source
    assert 'balance.on_hand_quantity =' not in source


def test_terminal_disposal_permission_is_exact_location_scoped():
    access = (ROOT / "inventory_access.py").read_text(encoding="utf-8")
    api = (ROOT / "api" / "warehouse" / "transfers.py").read_text(encoding="utf-8")
    assert "'inventory.disposal.confirm'" in access
    company_only = access.split("COMPANY_ONLY = frozenset({", 1)[1].split("})", 1)[0]
    assert "inventory.disposal.confirm" not in company_only
    assert 'await access.require("inventory.disposal.confirm", payload.source_location_id)' in api


def test_terminal_disposal_api_has_operation_idempotency_boundary():
    api = (ROOT / "api" / "warehouse" / "transfers.py").read_text(encoding="utf-8")
    assert 'operation="INVENTORY_FINAL_DISPOSAL"' in api
    assert 'complete_idempotent_operation(idempotency_record, response_payload)' in api
