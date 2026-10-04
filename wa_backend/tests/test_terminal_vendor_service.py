from decimal import Decimal
import os
from types import SimpleNamespace
from uuid import UUID

os.environ.setdefault("SECRET_KEY", "TerminalVendorTestSecretKeyAa1234567890")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest

from domains import inventory_terminal_vendor as terminal
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
async def test_confirm_vendor_handover_uses_staging_provenance_and_source_only_movements(monkeypatch):
    db = _Db([_Result(scalar=_balance()), _Result(scalar=_balance(on_hand="5"))])
    calls = {}
    events = []

    async def _origins(*_args, **kwargs):
        assert kwargs["transfer_purpose"] == "RETURN_TO_VENDOR"
        assert kwargs["terminal_reference_type"] == terminal.FINAL_VENDOR_HANDOVER_REFERENCE_TYPE
        return [
            TerminalOriginAllocation(51, "SPTR-51", Decimal("3")),
            TerminalOriginAllocation(52, "SPTR-52", Decimal("1")),
        ]

    async def _apply(_db, **kwargs):
        calls.update(kwargs)
        return [SimpleNamespace(id=101), SimpleNamespace(id=102)]

    monkeypatch.setattr(terminal, "allocate_terminal_origin_quantity", _origins)
    monkeypatch.setattr(terminal, "apply_inventory_movements_batch", _apply)
    monkeypatch.setattr(terminal, "record_domain_event", lambda *_a, **kw: events.append(kw))

    request_id = UUID("00000000-0000-0000-0000-000000000223")
    result = await terminal.confirm_vendor_handover(
        db, company_id=3, actor_id=4, request_id=request_id,
        source_location_id=6, product_variant_id=7, batch_id=11,
        source_status="QUARANTINED", quantity=Decimal("4"),
        vendor_name="Supplier A", vendor_reference="RMA-44",
        handover_reference="RECEIPT-2026-001",
    )

    specs = calls["movements"]
    assert [spec["quantity"] for spec in specs] == [Decimal("3"), Decimal("1")]
    assert [spec["transfer_header_id"] for spec in specs] == [51, 52]
    assert all(spec["movement_kind"] == "PHYSICAL" for spec in specs)
    assert all(spec["source_location_id"] == 6 for spec in specs)
    assert all(spec["destination_location_id"] is None for spec in specs)
    assert all(spec["source_stock_status"] == "QUARANTINED" for spec in specs)
    assert all(spec["reference_id"] == str(request_id) for spec in specs)
    assert result["movement_ids"] == [101, 102]
    assert result["handed_over_quantity"] == "4"
    assert result["remaining_quantity"] == "5"
    assert result["origin_transfer_header_ids"] == [51, 52]
    assert events[0]["event_type"] == terminal.FINAL_VENDOR_HANDOVER_EVENT
    assert events[0]["emit_outbox"] is True
    assert events[0]["after"]["vendor_name"] == "Supplier A"
    assert events[0]["after"]["vendor_reference"] == "RMA-44"
    assert events[0]["after"]["handover_reference"] == "RECEIPT-2026-001"


@pytest.mark.asyncio
async def test_confirm_vendor_handover_rejects_quantity_over_unreserved_staged_stock(monkeypatch):
    db = _Db([_Result(scalar=_balance(on_hand="4", reserved="2"))])
    async def _unexpected(*_args, **_kwargs):
        raise AssertionError("origin allocation must not run")
    monkeypatch.setattr(terminal, "allocate_terminal_origin_quantity", _unexpected)
    with pytest.raises(InventoryRuleError) as exc:
        await terminal.confirm_vendor_handover(
            db, company_id=3, actor_id=4,
            request_id=UUID("00000000-0000-0000-0000-000000000224"),
            source_location_id=6, product_variant_id=7, batch_id=11,
            source_status="QUARANTINED", quantity=Decimal("3"),
            vendor_name="Supplier A", vendor_reference="RMA-44",
            handover_reference="RECEIPT-2",
        )
    assert exc.value.code == "VENDOR_HANDOVER_QUANTITY_EXCEEDS_MOVABLE"


@pytest.mark.asyncio
async def test_confirm_vendor_handover_rejects_non_staging_status(monkeypatch):
    db = _Db([])
    with pytest.raises(InventoryRuleError) as exc:
        await terminal.confirm_vendor_handover(
            db, company_id=3, actor_id=4,
            request_id=UUID("00000000-0000-0000-0000-000000000225"),
            source_location_id=6, product_variant_id=7, batch_id=11,
            source_status="AVAILABLE", quantity=Decimal("1"),
            vendor_name="Supplier A", vendor_reference="RMA-44",
            handover_reference="RECEIPT-3",
        )
    assert exc.value.code == "VENDOR_HANDOVER_STATUS_INVALID"
