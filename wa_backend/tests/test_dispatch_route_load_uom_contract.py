"""Regression: Dispatch Route Launch must never silently unload a UOM remainder."""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from domains.dispatch_route_load import (
    allocate_route_base_batches, canonical_route_delta,
    route_vehicle_base_totals,
)
from domains.uom_authority import _build_authority
from schemas import DispatchRouteRequest


def _authority():
    variant = SimpleNamespace(
        id=701, base_uom_id=1, quantity_scale=0, quantity_step=Decimal("1"),
    )
    conversion = SimpleNamespace(
        from_uom_id=2, to_uom_id=1,
        numerator=Decimal("8"), denominator=Decimal("1"),
    )
    return _build_authority(variant, [conversion])


def test_pack_of_eight_never_truncates_twenty_base_units():
    authority = _authority()
    assert authority.factor_to_base(2) == 8
    assert canonical_route_delta(
        current=Decimal("20"), target=Decimal("20"), authority=authority,
    ) == Decimal("0")
    assert canonical_route_delta(
        current=Decimal("20"), target=Decimal("24"), authority=authority,
    ) == Decimal("4")
    assert canonical_route_delta(
        current=Decimal("20"), target=Decimal("16"), authority=authority,
    ) == Decimal("-4")


def test_legacy_contract_and_new_exact_contract_are_separate():
    args = dict(zone_id=1, driver_id=1, vehicle_id=1, source_location_id=1)
    legacy = DispatchRouteRequest.model_validate({**args, "inventory": {"701": 2}})
    assert legacy.inventory_base is None
    assert legacy.inventory["701"] == 2
    exact = DispatchRouteRequest.model_validate({
        **args, "inventory_base": {"701": "20"},
    })
    assert exact.inventory == {}
    assert exact.inventory_base == {"701": Decimal("20")}


@pytest.mark.asyncio
async def test_exact_vehicle_total_retains_decimal_remainder():
    db = SimpleNamespace(execute=AsyncMock(
        return_value=SimpleNamespace(all=lambda: [(701, Decimal("20.25"), Decimal("0"))])
    ))
    totals = await route_vehicle_base_totals(db, company_id=4, location_id=8)
    assert totals == {701: (Decimal("20.25"), Decimal("0"))}


@pytest.mark.asyncio
async def test_unload_uses_exact_locked_batch_quantity():
    db = SimpleNamespace(execute=AsyncMock(
        return_value=SimpleNamespace(all=lambda: [
            (91, Decimal("3.25"), Decimal("0")),
            (92, Decimal("9.5"), Decimal("0")),
        ])
    ))
    segments = await allocate_route_base_batches(
        db, company_id=4, location_id=8, product_variant_id=701,
        quantity=Decimal("4.25"), as_of_date=None, require_sellable=False,
    )
    assert segments == [(91, Decimal("3.25")), (92, Decimal("1.00"))]


def test_route_launch_uses_base_contract_and_preserves_legacy_keys():
    source = (Path(__file__).resolve().parents[1] / "api/dispatch.py").read_text(encoding="utf-8")
    route = source[source.index('async def dispatch_route('):source.index('async def get_vehicle_inventory(')]
    assert 'use_canonical_base = payload.inventory_base is not None' in route
    assert "delta_packs = canonical_route_delta(" in route
    assert "if delta_packs == 0:" in route
    assert "if movement_specs:" in route
    assert "require_location(access, 'dispatch.execute', int(source_location.id))" in route
    assert "check_inventory_lock(" in route
    assert "apply_inventory_movements_batch(" in route
