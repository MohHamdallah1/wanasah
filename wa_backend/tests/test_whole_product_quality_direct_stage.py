from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_whole_product_quality_stage_is_direct_posted_without_transit_receipt():
    domain = (ROOT / "domains" / "inventory_quality_handling.py").read_text(encoding="utf-8")
    transfers = (ROOT / "api" / "warehouse" / "transfers.py").read_text(encoding="utf-8")
    assert '"/warehouse/quality/stage"' in transfers
    assert 'quality_issue_stage=True' in transfers
    assert 'workflow_type="DIRECT"' in domain
    assert 'status="POSTED"' in domain
    assert '"movement_kind": "STATUS_CHANGE"' in domain
    assert '"source_location_id": source_location_id' in domain
    assert '"destination_location_id": source_location_id' in domain
    assert "created_at=now_utc" in domain
    assert "updated_at=now_utc" in domain
    assert "posted_at=now_utc" in domain
    assert "ensure_system_transit_location" not in domain


def test_direct_stage_preserves_legacy_transit_provenance_and_final_commands():
    domain = (ROOT / "domains" / "inventory_quality_handling.py").read_text(encoding="utf-8")
    provenance = (ROOT / "domains" / "inventory_terminal_provenance.py").read_text(encoding="utf-8")
    transfers = (ROOT / "api" / "warehouse" / "transfers.py").read_text(encoding="utf-8")
    assert 'QUALITY_STAGE_REFERENCE_PREFIX = "QSTG-"' in domain
    assert 'InventoryTransferHeader.reference_number.like("QSTG-%")' in provenance
    assert 'InventoryTransferHeader.workflow_type == "DIRECT"' in provenance
    assert 'InventoryTransferHeader.workflow_type == "TRANSIT"' in provenance
    assert '"/warehouse/quality/disposal/confirm"' in transfers
    assert '"/warehouse/quality/vendor-return/confirm"' in transfers


def test_vendor_stage_recall_exception_is_scoped_to_whole_product_quality_workflow():
    transfers = (ROOT / "api" / "warehouse" / "transfers.py").read_text(encoding="utf-8")
    services = (ROOT / "services.py").read_text(encoding="utf-8")
    assert 'PRODUCT_QUALITY_ISSUE_NOT_ACTIVE' in transfers
    assert 'quality_issue_stage: bool = False' in services
    assert '(quality_issue_stage and hold == "RECALL")' in services
