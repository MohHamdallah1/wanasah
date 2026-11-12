"""Focused tests for the two LEAD-approved shared helpers and price ambiguity."""
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

import services
from domains.representative_settlement_multi_vehicle import activation, inventory_integration as boundary
from domains.representative_settlement_multi_vehicle.contracts import CustodyRejected
from domains.representative_settlement_multi_vehicle.period_pricing import unambiguous_shortage_prices
from tests.test_dispatch_m04_domain import vehicles


@pytest.mark.asyncio
async def test_shared_validator_accepts_explicit_second_car_but_rejects_unrelated_car(monkeypatch):
    work = NS(id=71, company_id=1, is_settled=False, inventory_reconciled_at=None)
    db = NS()
    monkeypatch.setattr(boundary, "canonical_session", AsyncMock(return_value=True))
    monkeypatch.setattr(activation, "require_m04_schema", AsyncMock())
    monkeypatch.setattr(boundary, "session_responsibilities", AsyncMock(return_value=(work, vehicles())))
    from domains.representative_settlement_multi_vehicle import snapshots
    check = AsyncMock()
    monkeypatch.setattr(snapshots, "load_vehicle_snapshot", check)
    assert await services.validate_vehicle_recon_work_session(
        db, company_id=1, work_session_id=71, vehicle_id=20) is work
    assert check.await_args.kwargs["responsibility"].location_id == 120
    with pytest.raises(services.InventoryMutationError, match="SESSION_VEHICLE_NOT_FOUND"):
        await services.validate_vehicle_recon_work_session(db, company_id=1, work_session_id=71, vehicle_id=30)


@pytest.mark.asyncio
async def test_shared_seal_only_closes_selected_location_without_global_day_seal(monkeypatch):
    work = NS(id=71, company_id=1, is_settled=False,
              inventory_reconciled_at=None, inventory_reconciled_by=None)
    a = NS(location_id=110, product_variant_id=12, stock_status="DAMAGED",
           ending_quantity=None, settled_at=None, settled_by=None)
    b = NS(location_id=120, ending_quantity=None, settled_at=None, settled_by=None)
    balance = NS(product_variant_id=12, stock_status="DAMAGED",
                 on_hand_quantity=Decimal("2.125"), reserved_quantity=Decimal(0))
    db = NS(scalars=AsyncMock(side_effect=[NS(all=lambda: [balance]), NS(all=lambda: [a])]),
            flush=AsyncMock(), add=lambda row: pytest.fail("Unexpected new snapshot"))
    monkeypatch.setattr(boundary, "canonical_session", AsyncMock(return_value=True))
    monkeypatch.setattr(activation, "require_m04_schema", AsyncMock())
    monkeypatch.setattr(boundary, "session_responsibilities", AsyncMock(return_value=(work, vehicles())))
    monkeypatch.setattr(services, "acquire_inventory_location_guard", AsyncMock())
    movements = AsyncMock()
    monkeypatch.setattr(services, "apply_inventory_movements_batch", movements)
    assert await services._seal_vehicle_inventory_reconciliation(
        db, company_id=1, work_session=work, vehicle_location_id=110, settled_by=900) is work
    assert a.ending_quantity == Decimal("2.125") and a.settled_by == 900
    assert b.ending_quantity is None and b.settled_by is None
    assert work.inventory_reconciled_at is None and work.inventory_reconciled_by is None
    movements.assert_not_awaited()


def test_different_frozen_period_prices_fail_closed_instead_of_using_first_or_last():
    with pytest.raises(CustodyRejected, match="SHORTAGE_PERIOD_PRICE_REVIEW_REQUIRED"):
        unambiguous_shortage_prices([{12: Decimal("5.000")}, {12: Decimal("9.000")}], [12])
    assert unambiguous_shortage_prices(
        [{12: Decimal("5.000")}, {12: Decimal("5.000")}], [12]) == {12: Decimal("5.000")}
    # Distinct vehicles can legitimately have different deterministic contexts.
    assert unambiguous_shortage_prices([{12: Decimal("9.000")}], [12]) == {12: Decimal("9.000")}


@pytest.mark.parametrize("prices", [[], [{}], [{12: Decimal("NaN")}], [{12: Decimal("1.0001")}]])
def test_missing_or_invalid_price_provenance_requires_review(prices):
    with pytest.raises(CustodyRejected):
        unambiguous_shortage_prices(prices, [12])


@pytest.mark.parametrize("prices", [
    [{12: None}],
    [{12: "5.000"}],
])
def test_malformed_frozen_price_evidence_never_becomes_unhandled_server_error(prices):
    with pytest.raises(CustodyRejected, match="SHORTAGE_PERIOD_PRICE_REVIEW_REQUIRED"):
        unambiguous_shortage_prices(prices, [12])
