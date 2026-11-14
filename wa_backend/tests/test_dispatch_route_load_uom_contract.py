"""Regression: Dispatch Route Launch must never silently unload a UOM remainder."""
from decimal import Decimal
from fractions import Fraction
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401 - genuine PG16 fixture

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


# U03: REAL local PostgreSQL16 (FORCE RLS, runtime NOBYPASSRLS) and
# canonical Bearer HTTP. UI's U01 codec sends BASE only; never reinterpret it.
@pytest.mark.skipif(
    __import__("os").getenv("WANASAH_DISPATCH_D07_PG_GATE") != "1",
    reason="Requires own isolated U03 PG16 signed test port",
)
@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
@pytest.mark.parametrize("display_name,factor,target", [
    ("CARTON", 50, "1250"),
    ("CARTON", 50, "1253"),
    ("PALLET", 4800, "9607"),
    ("PACK", 8, "25"),
    ("BASE_ONLY", None, "20"),
    ("FULL_UNLOAD", None, "0"),
])
async def test_u03_real_signed_base_load_and_reverse_unload_exactly_once(
    pg, display_name, factor, target,
):
    from uuid import uuid4

    import httpx
    from sqlalchemy import select
    from models import ProductUomConversion, UOM
    from tests.test_dispatch_route_launch_d07_postgres import (
        _prepared_route, LoseRoute201,
    )
    from tests.test_dispatch_p0_route_stock_safety_postgres import _snapshot, _total
    from tests.test_dispatch_shop_finance_edit_v1_postgres import _owner, _real_http

    home, foreign = pg.tenants
    op_id, payload, vehicle_location = await _prepared_route(pg, home)
    variant_id = str(home.variant_id)
    if Decimal(target) > Decimal("80"):
        async with pg.session() as db:
            receipt = pg.request(
                lot="U03-" + uuid4().hex[:10],
                quantity="11000", cost="2",
            )
            assert await pg.post(db, receipt) == {"message": "INBOUND_POSTED"}
    async with pg.session() as db:
        if factor:
            uom = UOM(
                name=f"U03 {display_name} {uuid4().hex[:10]}",
                code=f"U03{uuid4().hex[:10]}",
            )
            db.add(uom)
            await db.flush()
            db.add(ProductUomConversion(
                company_id=home.company_id, product_variant_id=home.variant_id,
                from_uom_id=uom.id, to_uom_id=home.uom_id,
                numerator=Decimal(factor), denominator=Decimal("1"),
                quantity_scale=0,
            ))
            await db.commit()
    async with pg.session() as db:
        metadata = (await route_load_uom_metadata(
            db, company_id=home.company_id, variant_ids=[home.variant_id],
        ))[home.variant_id]
        assert metadata["display_factor_to_base"] == (str(factor) if factor else None)
        assert (display_name == "BASE_ONLY" or display_name == "FULL_UNLOAD") == (metadata["display_uom_name"] is None)
        if factor:
            assert metadata["display_uom_name"].startswith("U03 " + display_name)

    desired = Decimal(target)
    current = Decimal("25")
    before = await _snapshot(pg, home, [vehicle_location])
    assert _total(before, vehicle_location) == current
    assert _total(before, home.location_id) >= max(Decimal("0"), desired - current)
    # The user's editing action has NOT moved stock. Only signed POST may mutate.
    assert await _snapshot(pg, home, [vehicle_location]) == before

    payload["inventory_base"] = {variant_id: target} if desired else {}
    payload["expected_inventory_base"] = {variant_id: "25"}
    payload["request_id"] = str(op_id)
    async with _real_http() as client:
        user = await _owner(client, pg, home)
        outsider = await _owner(client, pg, foreign)
        leaked = await client.post("/dispatch/route", json=payload, headers=outsider)
        assert leaked.status_code in (400, 403, 404, 409, 422), leaked.text
        unauthenticated = await client.post("/dispatch/route", json=payload)
        assert unauthenticated.status_code == 401
        assert await _snapshot(pg, home, [vehicle_location]) == before

        stale = await client.post("/dispatch/route", headers=user, json={
            **payload, "request_id": str(uuid4()),
            "expected_inventory_base": {variant_id: "24"},
        })
        assert stale.status_code in (400, 409, 422), stale.text
        assert await _snapshot(pg, home, [vehicle_location]) == before

        if target == "1250":
            # One deliberately dropped *committed* HTTP 201, not a fake success.
            lost = LoseRoute201()
            async with httpx.AsyncClient(transport=lost,
                                         base_url="http://u03-lost-201.test",
                                         timeout=30) as unreliable:
                with pytest.raises(httpx.ReadError):
                    await unreliable.post("/dispatch/route", json=payload, headers=user)
            assert lost.dropped
        else:
            success = await client.post("/dispatch/route", json=payload, headers=user)
            assert success.status_code == 201, success.text

        after = await _snapshot(pg, home, [vehicle_location])
        assert _total(after, vehicle_location) == desired
        assert _total(after, home.location_id) == (
            _total(before, home.location_id) - (desired - current)
        )
        assert after["cost_events"] == before["cost_events"]
        assert (after["movements"] > before["movements"]) == (desired != current)
        lookup = await client.get(
            f"/dispatch/route/create-operations/{op_id}", headers=user,
        )
        assert lookup.status_code == 200, lookup.text
        assert lookup.json()["state"] == "COMMITTED", lookup.text

        # Replaying the original immutable signed intent must NEVER move stock twice.
        replay = await client.post("/dispatch/route", json=payload, headers=user)
        assert replay.status_code == 201, replay.text
        assert await _snapshot(pg, home, [vehicle_location]) == after
        conflict = await client.post("/dispatch/route", headers=user, json={
            **payload,
            "inventory_base": {variant_id: "26"},
        })
        assert conflict.status_code == 409, conflict.text
        assert await _snapshot(pg, home, [vehicle_location]) == after

    print("U03_PG16_SIGNED_BASE_MOVEMENT_PASS", {
        "display": display_name, "factor": factor, "expected_base": target,
        "direction": "LOAD" if desired > current else (
            "UNLOAD" if desired < current else "UNCHANGED"
        ),
        "warehouse_before": str(_total(before, home.location_id)),
        "warehouse_after": str(_total(after, home.location_id)),
        "vehicle_before": str(current), "vehicle_after": str(desired),
        "movement_count_delta": after["movements"] - before["movements"],
    }, flush=True)
