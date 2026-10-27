"""Regression: Dispatch Route Launch must never silently unload a UOM remainder."""
from decimal import Decimal
from fractions import Fraction
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from domains.dispatch_route_load import (
    allocate_route_base_batches, canonical_route_delta,
    route_vehicle_base_totals,
    route_load_uom_metadata,
)
from domains.uom_authority import UomAuthorityError, _build_authority
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

@pytest.mark.asyncio
async def test_metadata_resolves_one_exact_pack_and_keeps_base_name():
    variant = SimpleNamespace(
        id=701, base_uom_id=1, quantity_scale=0, quantity_step=Decimal("1"),
    )
    conversion = SimpleNamespace(
        product_variant_id=701, from_uom_id=2, to_uom_id=1,
        numerator=Decimal("8"), denominator=Decimal("1"),
    )
    responses = iter([
        [(701, 1, 0, Decimal("1"), "piece", "PCS")],
        [(2, "packet")],
    ])
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=lambda _: SimpleNamespace(all=lambda: next(responses))),
        scalars=AsyncMock(side_effect=[
            SimpleNamespace(all=lambda: [variant]),
            SimpleNamespace(all=lambda: [conversion]),
        ]),
    )
    metadata = await route_load_uom_metadata(db, company_id=1, variant_ids=[701])
    assert metadata[701]["base_uom_name"] == "piece"
    assert metadata[701]["display_uom_name"] == "packet"
    assert metadata[701]["display_factor_to_base"] == "8"


@pytest.mark.asyncio
@pytest.mark.parametrize("edges,expected", [
    ([], None),
    ([(2, 1, "8")], (2, "PACK", "8")),
    ([(2, 1, "8"), (3, 1, "96"), (4, 1, "4800")], (4, "PALLET", "4800")),
    ([(2, 1, "8"), (3, 2, "12"), (4, 3, "50")], (4, "PALLET", "4800")),
    ([(2, 1, "8"), (3, 1, "96"), (4, 1, "96")], None),
    ([(2, 1, "1.5"), (3, 1, "0.5"), (4, 1, "1"), (5, 6, "4800")], None),
])
async def test_metadata_uses_largest_exact_display_or_safe_base_fallback(edges, expected):
    variant = SimpleNamespace(
        id=701, base_uom_id=1, quantity_scale=0, quantity_step=Decimal("1"),
    )
    conversions = [_conversion(*edge) for edge in edges]
    responses = iter([[(701, 1, 0, Decimal("1"), "EACH", "EACH")]] +
                     ([[(expected[0], expected[1])]] if expected else []))
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=lambda _: SimpleNamespace(all=lambda: next(responses))),
        scalars=AsyncMock(side_effect=[
            SimpleNamespace(all=lambda: [variant]),
            SimpleNamespace(all=lambda: conversions),
        ]),
    )
    metadata = await route_load_uom_metadata(db, company_id=1, variant_ids=[701])
    assert metadata[701]["base_uom_name"] == "EACH"
    assert metadata[701]["display_uom_name"] == (expected[1] if expected else None)
    assert metadata[701]["display_factor_to_base"] == (expected[2] if expected else None)
    assert db.execute.await_count == (2 if expected else 1)


def _conversion(source, target, ratio):
    return SimpleNamespace(product_variant_id=701, from_uom_id=source, to_uom_id=target,
                           numerator=Decimal(ratio), denominator=Decimal("1"))


@pytest.mark.parametrize("edges,expected", [
    ([(2, 1, "8"), (3, 1, "96"), (4, 1, "4800")], (4, Fraction(4800))),
    ([(2, 1, "8"), (3, 2, "12"), (4, 3, "50")], (4, Fraction(4800))),
    ([(2, 1, "8"), (3, 1, "4800"), (4, 1, "4800")], None),
    ([(2, 1, "8"), (3, 1, "8"), (4, 1, "96")], (4, Fraction(96))),
])
def test_display_selection_is_independent_of_graph_insertion_order(edges, expected):
    variant = SimpleNamespace(id=701, base_uom_id=1, quantity_scale=0, quantity_step=Decimal("1"))
    for order in permutations(edges):
        authority = _build_authority(variant, [_conversion(*edge) for edge in order])
        assert authority.largest_display_uom() == expected
        assert authority.factor_to_base(1) == 1


@pytest.mark.asyncio
async def test_conflicting_graph_still_fails_before_display_selection():
    variant = SimpleNamespace(id=701, base_uom_id=1, quantity_scale=0, quantity_step=Decimal("1"))
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(701, 1, 0, Decimal("1"), "EACH", "EACH")])),
        scalars=AsyncMock(side_effect=[SimpleNamespace(all=lambda: [variant]),
            SimpleNamespace(all=lambda: [_conversion(2, 1, "8"), _conversion(3, 2, "12"), _conversion(3, 1, "95")])]),
    )
    with pytest.raises(UomAuthorityError) as caught:
        await route_load_uom_metadata(db, company_id=1, variant_ids=[701])
    assert caught.value.code == "UOM_CONVERSION_GRAPH_AMBIGUOUS"
