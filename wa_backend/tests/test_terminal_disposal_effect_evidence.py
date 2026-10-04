from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from models import DomainAuditEvent, TransactionalOutbox
from product_lifecycle import record_domain_event

ROOT = Path(__file__).resolve().parents[1]


class _Db:
    def __init__(self):
        self.added = []

    def add(self, value):
        self.added.append(value)


def test_record_domain_event_writes_immutable_audit_and_outbox_evidence():
    db = _Db()
    request_id = UUID("00000000-0000-0000-0000-000000000777")
    before = {"on_hand_quantity": "4", "stock_status": "DISPOSAL_PENDING"}
    after = {"disposed_quantity": "4", "remaining_quantity": "0", "movement_ids": [91]}

    record_domain_event(
        db,
        company_id=3,
        actor_id=4,
        request_id=request_id,
        event_type="INVENTORY_FINAL_DISPOSAL_CONFIRMED",
        entity_type="InventoryMovement",
        entity_id=91,
        reason="Destroyed under supervision",
        before=before,
        after=after,
        emit_outbox=True,
    )

    assert len(db.added) == 2
    audit = next(value for value in db.added if isinstance(value, DomainAuditEvent))
    outbox = next(value for value in db.added if isinstance(value, TransactionalOutbox))
    assert audit.company_id == 3
    assert audit.actor_user_id == 4
    assert audit.request_id == request_id
    assert audit.event_type == "INVENTORY_FINAL_DISPOSAL_CONFIRMED"
    assert audit.before_snapshot == before
    assert audit.after_snapshot == after
    assert outbox.company_id == 3
    assert outbox.event_type == audit.event_type
    assert outbox.aggregate_type == "InventoryMovement"
    assert outbox.aggregate_id == "91"
    assert outbox.payload["before"] == before
    assert outbox.payload["after"] == after
    assert outbox.payload["request_id"] == str(request_id)
    assert outbox.status == "PENDING"
    assert outbox.idempotency_key.endswith(str(request_id))


def test_unified_source_only_physical_movement_is_real_inventory_effect():
    source = (ROOT / "services.py").read_text(encoding="utf-8")
    start = source.index("async def apply_inventory_movements_batch(")
    end = source.index("async def apply_inventory_movement(", start)
    engine = source[start:end]

    # Source-only PHYSICAL is not a fake status/document change: it subtracts
    # free on-hand under row locks and persists before/after impact evidence.
    assert 'source_balance.on_hand_quantity = after_on_hand' in engine
    assert 'before_on_hand - spec["quantity"]' in engine
    assert 'db_session.add(InventoryMovementImpact(' in engine
    assert 'await apply_inventory_costing_for_movements(' in engine
    assert 'await apply_live_stock_balance_impacts(' in engine

    terminal = (ROOT / "domains" / "inventory_terminal_quality.py").read_text(encoding="utf-8")
    assert '"movement_kind": "PHYSICAL"' in terminal
    assert '"destination_location_id": None' in terminal
    assert '"source_stock_status": "DISPOSAL_PENDING"' in terminal
    assert 'apply_inventory_movements_batch(' in terminal
    assert 'record_domain_event(' in terminal
    assert 'emit_outbox=True' in terminal
    assert 'balance.on_hand_quantity =' not in terminal
