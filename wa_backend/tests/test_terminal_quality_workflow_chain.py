import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]

class RuleError(Exception):
    pass

class MutationError(Exception):
    pass

def _strict_int(value, _field, minimum=1):
    parsed = int(value)
    if parsed < minimum:
        raise ValueError
    return parsed


def terminal_status_authority():
    path = ROOT / "services.py"
    node = next(
        n for n in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "resolve_special_transfer_terminal_statuses"
    )
    async def safe_statuses(_db, **kwargs):
        return {int(line.id): str(line.source_stock_status).upper() for line in kwargs["lines"]}
    namespace = {
        "AsyncSession": object, "List": list, "Any": object, "Dict": dict,
        "SPECIAL_TRANSFER_PURPOSES": {"QUARANTINE", "RECALL_RETURN", "RETURN_TO_VENDOR", "DISPOSAL"},
        "InventoryRuleError": RuleError, "InventoryMutationError": MutationError,
        "_INVENTORY_STOCK_STATUSES": {"AVAILABLE", "QUARANTINED", "BLOCKED", "RECALLED", "DAMAGED", "DISPOSAL_PENDING"},
        "_strict_int": _strict_int, "resolve_inflight_transfer_destination_statuses": safe_statuses,
        "_special_return_to_source_status": lambda source, safe: safe,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["resolve_special_transfer_terminal_statuses"]


@pytest.mark.asyncio
async def test_special_receipt_creates_terminal_staging_states_without_pretending_completion():
    resolve = terminal_status_authority()
    disposal = await resolve(
        object(), company_id=1, destination_location_id=30, transfer_purpose="DISPOSAL",
        terminal_action="RECEIVE", lines=[SimpleNamespace(id=1, source_stock_status="BLOCKED")],
    )
    vendor = await resolve(
        object(), company_id=1, destination_location_id=40, transfer_purpose="RETURN_TO_VENDOR",
        terminal_action="RECEIVE", lines=[SimpleNamespace(id=2, source_stock_status="QUARANTINED")],
    )
    assert disposal == {1: "DISPOSAL_PENDING"}
    assert vendor == {2: "QUARANTINED"}


def test_transfer_receipt_and_terminal_commands_form_one_authoritative_chain():
    transfers = (ROOT / "api" / "warehouse" / "transfers.py").read_text(encoding="utf-8")
    assert '"/warehouse/unified/transfer/special/dispatch"' in transfers
    assert '"/warehouse/unified/transfer/receive"' in transfers
    assert "resolve_special_transfer_terminal_statuses(" in transfers
    assert '"/warehouse/quality/disposal/confirm"' in transfers
    assert '"/warehouse/quality/vendor-return/confirm"' in transfers
    assert 'operation="INVENTORY_FINAL_DISPOSAL"' in transfers
    assert 'operation="INVENTORY_FINAL_VENDOR_HANDOVER"' in transfers
    assert transfers.count("complete_idempotent_operation(idempotency_record, response_payload)") >= 2


def test_terminal_exit_uses_canonical_source_only_inventory_engine_and_immutable_evidence():
    disposal = (ROOT / "domains" / "inventory_terminal_quality.py").read_text(encoding="utf-8")
    vendor = (ROOT / "domains" / "inventory_terminal_vendor.py").read_text(encoding="utf-8")
    provenance = (ROOT / "domains" / "inventory_terminal_provenance.py").read_text(encoding="utf-8")
    engine = (ROOT / "services.py").read_text(encoding="utf-8")

    assert '"source_stock_status": "DISPOSAL_PENDING"' in disposal
    assert 'transfer_purpose="DISPOSAL"' in disposal
    assert 'transfer_purpose="RETURN_TO_VENDOR"' in vendor
    for source in (disposal, vendor):
        assert '"movement_kind": "PHYSICAL"' in source
        assert '"destination_location_id": None' in source
        assert "apply_inventory_movements_batch(" in source
        assert "record_domain_event(" in source and "emit_outbox=True" in source
        assert "balance.on_hand_quantity =" not in source

    assert 'InventoryTransferHeader.status == "POSTED"' in provenance
    assert 'InventoryMovement.transfer_header_id.in_(header_ids)' in provenance
    assert "source_balance.on_hand_quantity = after_on_hand" in engine
    assert "InventoryMovementImpact(" in engine
    assert "apply_inventory_costing_for_movements(" in engine
    assert "apply_live_stock_balance_impacts(" in engine


def test_terminal_replay_boundary_is_request_idempotent_for_both_outcomes():
    transfers = (ROOT / "api" / "warehouse" / "transfers.py").read_text(encoding="utf-8")
    for operation in ("INVENTORY_FINAL_DISPOSAL", "INVENTORY_FINAL_VENDOR_HANDOVER"):
        assert f'operation="{operation}"' in transfers
    assert "if replay_response is not None:" in transfers
    assert "return replay_response" in transfers
