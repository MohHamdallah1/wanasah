from decimal import Decimal
import os
from types import SimpleNamespace
from uuid import UUID

os.environ.setdefault("SECRET_KEY", "TerminalDisposalTestSecretKeyAa1234567890")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest

from domains import inventory_terminal_quality as terminal
from domains.inventory_terminal_provenance import TerminalOriginAllocation
from services import InventoryRuleError


class _Result:
    def __init__(self, *, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _Db:
    def __init__(self, results):
        self.results = list(results)

    async def execute(self, _stmt):
        if not self.results:
            raise AssertionError("unexpected execute")
        return self.results.pop(0)


def _balance(*, on_hand="9", reserved="0"):
    return SimpleNamespace(
        on_hand_quantity=Decimal(on_hand),
        reserved_quantity=Decimal(reserved),
    )


@pytest.mark.asyncio
async def test_confirm_final_disposal_uses_source_only_unified_movements(monkeypatch):
    db = _Db([_Result(scalar=_balance()), _Result(scalar=_balance(on_hand="5"))])
    calls = {}
    events = []

    async def _origins(*_args, **_kwargs):
        return [
            TerminalOriginAllocation(41, "SPTR-41", Decimal("3")),
            TerminalOriginAllocation(42, "SPTR-42", Decimal("1")),
        ]

    async def _apply(_db, **kwargs):
        calls.update(kwargs)
        return [SimpleNamespace(id=91), SimpleNamespace(id=92)]

    monkeypatch.setattr(terminal, "allocate_terminal_origin_quantity", _origins)
    monkeypatch.setattr(terminal, "apply_inventory_movements_batch", _apply)
    monkeypatch.setattr(terminal, "record_domain_event", lambda *_a, **kw: events.append(kw))

    result = await terminal.confirm_final_disposal(
        db, company_id=3, actor_id=4,
        request_id=UUID("00000000-0000-0000-0000-000000000123"),
        source_location_id=5, product_variant_id=7, batch_id=11,
        quantity=Decimal("4"), reason="Destroyed under supervision",
        method="licensed-contractor", evidence_reference="DOC-22",
    )

    specs = calls["movements"]
    assert [spec["quantity"] for spec in specs] == [Decimal("3"), Decimal("1")]
    assert [spec["transfer_header_id"] for spec in specs] == [41, 42]
    assert all(spec["movement_kind"] == "PHYSICAL" for spec in specs)
    assert all(spec["source_location_id"] == 5 for spec in specs)
    assert all(spec["destination_location_id"] is None for spec in specs)
    assert all(spec["source_stock_status"] == "DISPOSAL_PENDING" for spec in specs)
    assert result["movement_ids"] == [91, 92]
    assert result["disposed_quantity"] == "4"
    assert result["remaining_quantity"] == "5"
    assert result["origin_transfer_header_ids"] == [41, 42]
    assert events[0]["event_type"] == terminal.FINAL_DISPOSAL_EVENT
    assert events[0]["emit_outbox"] is True
    assert events[0]["after"]["evidence_reference"] == "DOC-22"


@pytest.mark.asyncio
async def test_confirm_final_disposal_rejects_quantity_over_movable_stock(monkeypatch):
    db = _Db([_Result(scalar=_balance(on_hand="2", reserved="1"))])
    async def _unexpected(*_args, **_kwargs):
        raise AssertionError("origin allocation must not run")
    monkeypatch.setattr(terminal, "allocate_terminal_origin_quantity", _unexpected)
    with pytest.raises(InventoryRuleError) as exc:
        await terminal.confirm_final_disposal(
            db, company_id=3, actor_id=4,
            request_id=UUID("00000000-0000-0000-0000-000000000124"),
            source_location_id=5, product_variant_id=7, batch_id=11,
            quantity=Decimal("2"), reason="Destroy",
        )
    assert exc.value.code == "DISPOSAL_QUANTITY_EXCEEDS_MOVABLE"


@pytest.mark.asyncio
async def test_confirm_final_disposal_rejects_quantity_over_pending(monkeypatch):
    db = _Db([_Result(scalar=_balance(on_hand="2"))])
    async def _unexpected(*_args, **_kwargs):
        raise AssertionError("origin allocation must not run")
    monkeypatch.setattr(terminal, "allocate_terminal_origin_quantity", _unexpected)
    with pytest.raises(InventoryRuleError) as exc:
        await terminal.confirm_final_disposal(
            db, company_id=3, actor_id=4,
            request_id=UUID("00000000-0000-0000-0000-000000000125"),
            source_location_id=5, product_variant_id=7, batch_id=11,
            quantity=Decimal("3"), reason="Destroy",
        )
    assert exc.value.code == "DISPOSAL_QUANTITY_EXCEEDS_MOVABLE"
