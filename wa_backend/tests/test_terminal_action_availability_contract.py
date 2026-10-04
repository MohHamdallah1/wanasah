from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stock_sources_terminal_actions_are_backend_derived_and_bounded():
    api = (ROOT / "api" / "warehouse" / "live_stock.py").read_text(encoding="utf-8")
    provenance = (ROOT / "domains" / "inventory_terminal_provenance.py").read_text(encoding="utf-8")
    assert "read_terminal_origin_availability(" in api
    assert '"inventory.disposal.confirm", InventoryLocation.id' in api
    assert '"inventory.vendor_return.confirm", InventoryLocation.id' in api
    assert '"CONFIRM_DISPOSAL"' in api
    assert '"CONFIRM_VENDOR_HANDOVER"' in api
    assert 'min(movable, disposal_evidence)' in api
    assert 'min(movable, vendor_evidence)' in api
    assert 'len(location_ids) > 500' in provenance
    assert 'InventoryTransferHeader.status == "POSTED"' in provenance
    assert 'InventoryMovement.reference_type.in_(' in provenance


def test_terminal_action_read_contract_is_advisory_not_mutation_authority():
    api = (ROOT / "api" / "warehouse" / "live_stock.py").read_text(encoding="utf-8")
    start = api.index("async def get_batch_stock_sources(")
    endpoint = api[start:]
    assert "apply_inventory_movements_batch(" not in endpoint
    assert "confirm_final_disposal(" not in endpoint
    assert "confirm_vendor_handover(" not in endpoint
