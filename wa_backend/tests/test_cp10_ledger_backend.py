from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api.warehouse import inbound_adjustments, ledger
from domains.ledger import inbound_adjustment as adjustment_domain
from domains.ledger import read as ledger_read
from domains.ledger.inbound_adjustment import InboundAdjustmentState, LedgerAdjustmentError
from domains.ledger.read import LedgerReadError


pytestmark = pytest.mark.asyncio


def _scope(**overrides):
    values = {
        "company_id": 7,
        "location_id": 11,
        "search": "alpha%_\\",
        "reference_type": "TRANSFER",
        "reference_id": "REF-1",
        "limit": 50,
    }
    values.update(overrides)
    return ledger_read._ledger_scope(**values)


async def test_signed_cursor_rejects_tamper_and_all_scope_changes():
    created_at = datetime(2026, 10, 16, 12, 30, 0)
    scope = _scope()
    cursor = ledger_read.encode_ledger_cursor(created_at, 91, scope=scope)
    assert ledger_read.decode_ledger_cursor(cursor, expected_scope=scope) == (created_at, 91)

    payload, signature = cursor.split(".", 1)
    replacement = "A" if payload[-1] != "A" else "B"
    tampered = f"{payload[:-1]}{replacement}.{signature}"
    with pytest.raises(LedgerReadError) as caught:
        ledger_read.decode_ledger_cursor(tampered, expected_scope=scope)
    assert caught.value.code == "LEDGER_CURSOR_INVALID"

    for changed in (
        _scope(company_id=8),
        _scope(location_id=12),
        _scope(search="other"),
        _scope(reference_type="STOCKTAKE"),
        _scope(reference_id="REF-2"),
        _scope(limit=100),
    ):
        with pytest.raises(LedgerReadError) as mismatch:
            ledger_read.decode_ledger_cursor(cursor, expected_scope=changed)
        assert mismatch.value.code == "LEDGER_CURSOR_INVALID"


async def test_ledger_read_guard_requires_exact_location_capability():
    db = NS(scalar=AsyncMock(return_value=44))
    access = NS(company_id=9, db=db, require=AsyncMock(return_value=None))
    await ledger._require_ledger_access(access, location_id=44)
    access.require.assert_awaited_once_with("ledger.read", 44)


async def test_ledger_read_guard_is_opaque_for_foreign_location():
    access = NS(company_id=9, db=NS(scalar=AsyncMock(return_value=None)), require=AsyncMock())
    with pytest.raises(HTTPException) as caught:
        await ledger._require_ledger_access(access, location_id=777)
    assert caught.value.status_code == 404
    assert caught.value.detail["code"] == "LEDGER_LOCATION_NOT_FOUND"
    access.require.assert_not_awaited()


async def test_adjustment_guard_delegates_only_to_canonical_inbound_guard():
    access = NS(company_id=5)
    with patch.object(inbound_adjustments, "require_inbound_adjustment", new=AsyncMock()) as guard:
        await inbound_adjustments._require_inbound_adjustment_access(access, 51)
    guard.assert_awaited_once_with(access, 51)


async def test_append_only_command_uses_canonical_movement_path_and_exact_delta():
    state = InboundAdjustmentState(
        entry_id=51,
        reference="INV-1",
        normalized_reference="inv-1",
        product_variant_id=81,
        batch_id=91,
        warehouse_location_id=101,
        current_total_quantity=Decimal("10.250001"),
        base_uom_id=3,
        base_uom_code="EACH",
    )
    db = NS(add=lambda value: None)
    movement = NS(id=700)
    with (
        patch.object(adjustment_domain, "load_inbound_adjustment_state", new=AsyncMock(return_value=state)),
        patch.object(adjustment_domain, "apply_inventory_movement", new=AsyncMock(return_value=movement)) as apply,
    ):
        returned, delta, correction_id = await adjustment_domain.apply_inbound_adjustment(
            db,
            company_id=5,
            entry_id=51,
            actor_id=61,
            new_total_quantity=Decimal("8.000001"),
            uom_id=3,
            notes="counted",
        )
    assert returned == state
    assert delta == Decimal("-2.250000")
    assert correction_id == 700
    kwargs = apply.await_args.kwargs
    assert kwargs["reference_type"] == "INBOUND_CORRECTION"
    assert kwargs["quantity"] == Decimal("2.250000")
    assert kwargs["source_location_id"] == 101
    assert kwargs["destination_location_id"] is None
    assert kwargs["source_stock_status"] == "AVAILABLE"
    assert kwargs["destination_stock_status"] is None


async def test_uom_mismatch_fails_before_any_inventory_mutation():
    state = InboundAdjustmentState(
        entry_id=51,
        reference="INV-1",
        normalized_reference="inv-1",
        product_variant_id=81,
        batch_id=91,
        warehouse_location_id=101,
        current_total_quantity=Decimal("10"),
        base_uom_id=3,
        base_uom_code="EACH",
    )
    with (
        patch.object(adjustment_domain, "load_inbound_adjustment_state", new=AsyncMock(return_value=state)),
        patch.object(adjustment_domain, "apply_inventory_movement", new=AsyncMock()) as apply,
    ):
        with pytest.raises(LedgerAdjustmentError) as caught:
            await adjustment_domain.apply_inbound_adjustment(
                NS(add=lambda value: None),
                company_id=5,
                entry_id=51,
                actor_id=61,
                new_total_quantity=Decimal("12"),
                uom_id=99,
                notes=None,
            )
    assert caught.value.code == "UOM_MISMATCH"
    apply.assert_not_awaited()


def test_cp10_runtime_has_no_legacy_authority_or_historical_rewrite_paths():
    root = Path(__file__).parents[1]
    api_source = (root / "api" / "warehouse" / "inbound_adjustments.py").read_text(encoding="utf-8")
    domain_source = (root / "domains" / "ledger" / "inbound_adjustment.py").read_text(encoding="utf-8")
    ledger_source = (root / "api" / "warehouse" / "ledger.py").read_text(encoding="utf-8")
    combined = api_source + domain_source + ledger_source
    for forbidden in (".is_admin", "legacy_actor.company_id", "actor.company_id", "inventory.read"):
        assert forbidden not in combined
    assert "apply_inventory_movement(" in domain_source
    assert "InventoryMovement.__table__.update" not in domain_source
    assert "InventoryMovement.__table__.delete" not in domain_source
    assert "InventoryBalance.__table__.update" not in domain_source
