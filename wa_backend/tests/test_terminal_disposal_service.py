from decimal import Decimal
import os
from types import SimpleNamespace
from uuid import UUID

os.environ.setdefault("SECRET_KEY", "TerminalDisposalTestSecretKeyAa1234567890")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest

from domains import inventory_terminal_quality as terminal
from services import InventoryRuleError


class _Result:
    def __init__(self, *, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = [] if rows is None else rows

    def scalar_one_or_none(self):
        return self._scalar

    def all(self):
        return list(self._rows)


class _Db:
    def __init__(self, results):
        self.results = list(results)

    async def execute(self, _stmt):
        if not self.results:
            raise AssertionError("unexpected execute")
        return self.results.pop(0)


def _fixtures(*, reserved="0", origins=True):
    location = SimpleNamespace(id=5, is_active=True, location_type="SCRAP")
    batch = SimpleNamespace(id=11, product_variant_id=7)
    balance = SimpleNamespace(
        on_hand_quantity=Decimal("9"),
        reserved_quantity=Decimal(reserved),
    )
    origin_rows = (
        [SimpleNamespace(header_id=41, reference_number="SPTR-41", quantity=Decimal("9"))]
        if origins
        else []
    )
    return [_Result(scalar=location), _Result(scalar=batch), _Result(scalar=balance), _Result(rows=origin_rows)]


@pytest.mark.asyncio
async def test_confirm_final_disposal_uses_source_only_unified_movement(monkeypatch):
    db = _Db(_fixtures())
    calls = {}
    events = []

    async def _apply(_db, **kwargs):
        calls.update(kwargs)
        # Simulate the authoritative engine mutating the identity-mapped balance.
        db.results.append(_Result(scalar=SimpleNamespace(
            on_hand_quantity=Decimal("5"),
            reserved_quantity=Decimal("0"),
        )))
        return SimpleNamespace(id=91)

    monkeypatch.setattr(terminal, "apply_inventory_movement", _apply)
    monkeypatch.setattr(terminal, "record_domain_event", lambda *_a, **kw: events.append(kw))

    result = await terminal.confirm_final_disposal(
        db,
        company_id=3,
        actor_id=4,
        request_id=UUID("00000000-0000-0000-0000-000000000123"),
        source_location_id=5,
        product_variant_id=7,
        batch_id=11,
        quantity=Decimal("4"),
        reason="Destroyed under supervision",
        method="licensed-contractor",
        evidence_reference="DOC-22",
    )

    assert calls["movement_kind"] == "PHYSICAL"
    assert calls["source_location_id"] == 5
    assert calls["destination_location_id"] is None
    assert calls["source_stock_status"] == "DISPOSAL_PENDING"
    assert calls["destination_stock_status"] is None
    assert calls["transfer_header_id"] == 41
    assert result["disposed_quantity"] == "4"
    assert result["remaining_quantity"] == "5"
    assert result["origin_transfer_header_ids"] == [41]
    assert events[0]["event_type"] == terminal.FINAL_DISPOSAL_EVENT
    assert events[0]["emit_outbox"] is True
    assert events[0]["after"]["evidence_reference"] == "DOC-22"


@pytest.mark.asyncio
async def test_confirm_final_disposal_rejects_reserved_pending_stock(monkeypatch):
    db = _Db(_fixtures(reserved="1")[:3])
    with pytest.raises(InventoryRuleError) as exc:
        await terminal.confirm_final_disposal(
            db,
            company_id=3,
            actor_id=4,
            request_id=UUID("00000000-0000-0000-0000-000000000124"),
            source_location_id=5,
            product_variant_id=7,
            batch_id=11,
            quantity=Decimal("1"),
            reason="Destroy",
        )
    assert exc.value.code == "DISPOSAL_PENDING_STOCK_RESERVED"


@pytest.mark.asyncio
async def test_confirm_final_disposal_requires_posted_disposal_origin(monkeypatch):
    db = _Db(_fixtures(origins=False))
    with pytest.raises(InventoryRuleError) as exc:
        await terminal.confirm_final_disposal(
            db,
            company_id=3,
            actor_id=4,
            request_id=UUID("00000000-0000-0000-0000-000000000125"),
            source_location_id=5,
            product_variant_id=7,
            batch_id=11,
            quantity=Decimal("1"),
            reason="Destroy",
        )
    assert exc.value.code == "DISPOSAL_ORIGIN_EVIDENCE_MISSING"



