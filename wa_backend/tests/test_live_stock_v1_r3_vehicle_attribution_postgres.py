from __future__ import annotations

import json
import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api import dispatch
from api.warehouse import live_stock
from domains.inventory_vehicle_load.service import mutate_vehicle_load
from domains.live_stock_projection.service import (
    get_live_stock_vehicle_sources,
    rebuild_live_stock_company,
)
from domains.vehicles.contracts import CreateVehicleCommand, VehicleError
from domains.vehicles.management import create_vehicle
from models import (
    DispatchRoute,
    InventoryBalance,
    InventoryCostEvent,
    InventoryCostState,
    InventoryLocation,
    InventoryMovement,
    Permission,
    ProductBatch,
    ProductLocation,
    Role,
    UserLocationAccess,
    role_permissions,
)
from schemas import DispatchRouteRequest, UpdateRouteStatusRequest
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_live_stock_v1_route_sale_unload_postgres import (
    _seed_commercial_master,
    _seed_mobile_uom_and_field,
)


D = Decimal

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_R3_VEHICLE_ATTRIBUTION_PG_GATE") != "1",
        reason="Explicit disposable PostgreSQL 16 R3 vehicle-attribution gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _enable_second_warehouse(pg_gate, tenant) -> None:
    """Master-data readiness only; never writes inventory quantity."""
    async with AsyncSession(pg_gate.admin_engine, expire_on_commit=False) as db:
        await db.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": str(tenant.company_id)},
        )
        existing = await db.scalar(
            select(ProductLocation).where(
                ProductLocation.company_id == tenant.company_id,
                ProductLocation.location_id == tenant.other_location_id,
                ProductLocation.product_variant_id == tenant.variant_id,
            )
        )
        if existing is None:
            db.add(
                ProductLocation(
                    company_id=tenant.company_id,
                    location_id=tenant.other_location_id,
                    product_variant_id=tenant.variant_id,
                    created_by=tenant.owner.driver_id,
                    operational_flags={
                        "inbound_enabled": True,
                        "outbound_enabled": True,
                    },
                )
            )
            await db.flush()
        await rebuild_live_stock_company(db, company_id=tenant.company_id)
        await db.commit()


async def _grant_restricted_reader(
    pg_gate,
    tenant,
    *,
    vehicle_location_id: int,
) -> int:
    """Give one ordinary Backoffice subject inventory.read on W1/W2/Vehicle."""
    async with AsyncSession(pg_gate.admin_engine, expire_on_commit=False) as db:
        await db.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": str(tenant.company_id)},
        )
        permission = await db.scalar(
            select(Permission).where(Permission.code == "inventory.read")
        )
        assert permission is not None
        role = Role(
            company_id=tenant.company_id,
            name="R3 vehicle attribution reader " + uuid4().hex[:10],
        )
        db.add(role)
        await db.flush()
        await db.execute(
            role_permissions.insert().values(
                company_id=tenant.company_id,
                role_id=int(role.id),
                permission_id=int(permission.id),
            )
        )
        for location_id in (
            tenant.location_id,
            tenant.other_location_id,
            vehicle_location_id,
        ):
            db.add(
                UserLocationAccess(
                    company_id=tenant.company_id,
                    driver_id=tenant.ordinary.driver_id,
                    location_id=int(location_id),
                    role_id=int(role.id),
                )
            )
        await db.commit()
        return int(role.id)


async def _batch_id(pg_gate, tenant, batch_number: str) -> int:
    async with pg_gate.session() as db:
        value = await db.scalar(
            select(ProductBatch.id).where(
                ProductBatch.company_id == tenant.company_id,
                ProductBatch.product_variant_id == tenant.variant_id,
                ProductBatch.batch_number == batch_number,
            )
        )
        assert value is not None
        return int(value)


def _cursor_kwargs(location_id: int, db, access, *, has_vehicle: bool = False):
    return dict(
        location_id=int(location_id),
        cursor=None,
        limit=50,
        search=None,
        only_alerts=False,
        stock_state="all",
        family_id=None,
        has_reserved=False,
        has_unavailable=False,
        has_damaged=False,
        has_recalled=False,
        has_vehicle=has_vehicle,
        minimum_unset=False,
        sort="name_asc",
        db=db,
        access=access,
    )


def _variant_row(response: dict, variant_id: int) -> dict | None:
    return next(
        (
            row
            for row in response["items"]
            if int(row["id"]) == int(variant_id)
        ),
        None,
    )


def _available_sources(response: dict) -> dict[int, tuple[str, Decimal]]:
    result: dict[int, tuple[str, Decimal]] = {}
    for source in response["sources"]:
        available = next(
            (
                status
                for status in source["statuses"]
                if status["stock_status"] == "AVAILABLE"
            ),
            None,
        )
        if available is not None:
            result[int(source["location_id"])] = (
                str(source["location_type"]),
                D(available["on_hand_quantity"]),
            )
    return result


async def _physical(pg_gate, tenant, *, vehicle_location_id: int) -> dict[str, Decimal]:
    async with pg_gate.session() as db:
        rows = (
            await db.execute(
                select(
                    InventoryBalance.location_id,
                    func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0),
                    func.coalesce(func.sum(InventoryBalance.reserved_quantity), 0),
                )
                .where(
                    InventoryBalance.company_id == tenant.company_id,
                    InventoryBalance.product_variant_id == tenant.variant_id,
                    InventoryBalance.stock_status == "AVAILABLE",
                    InventoryBalance.location_id.in_(
                        [
                            tenant.location_id,
                            tenant.other_location_id,
                            int(vehicle_location_id),
                        ]
                    ),
                )
                .group_by(InventoryBalance.location_id)
            )
        ).all()
    by_id = {
        int(location_id): (D(on_hand), D(reserved))
        for location_id, on_hand, reserved in rows
    }
    for _location_id, (_on_hand, reserved) in by_id.items():
        assert reserved == D("0")
    return {
        "w1": by_id.get(int(tenant.location_id), (D("0"), D("0")))[0],
        "w2": by_id.get(int(tenant.other_location_id), (D("0"), D("0")))[0],
        "vehicle": by_id.get(int(vehicle_location_id), (D("0"), D("0")))[0],
    }


async def _financial(pg_gate, tenant) -> dict:
    async with pg_gate.session() as db:
        state = await db.scalar(
            select(InventoryCostState).where(
                InventoryCostState.company_id == tenant.company_id,
                InventoryCostState.product_variant_id == tenant.variant_id,
            )
        )
        assert state is not None
        events = (
            await db.scalars(
                select(InventoryCostEvent)
                .where(
                    InventoryCostEvent.company_id == tenant.company_id,
                    InventoryCostEvent.product_variant_id == tenant.variant_id,
                )
                .order_by(InventoryCostEvent.id.asc())
            )
        ).all()
    return {
        "quantity": D(state.quantity),
        "value": D(state.inventory_value),
        "events": [
            (
                str(event.event_type),
                D(event.quantity),
                D(event.total_cost),
            )
            for event in events
        ],
    }


async def _movement_count(pg_gate, tenant) -> int:
    async with pg_gate.session() as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(InventoryMovement.company_id == tenant.company_id)
            )
            or 0
        )


async def _observe(
    pg_gate,
    tenant,
    *,
    stage: str,
    vehicle_id: int,
    vehicle_location_id: int,
    batch_id: int,
    access_kind: str = "owner",
) -> dict:
    physical = await _physical(
        pg_gate,
        tenant,
        vehicle_location_id=vehicle_location_id,
    )
    async with pg_gate.session() as db:
        access = (
            tenant.owner.access(db)
            if access_kind == "owner"
            else tenant.ordinary.access(db)
        )
        w1_page = await live_stock.get_warehouse_inventory(
            **_cursor_kwargs(tenant.location_id, db, access)
        )
        w2_page = await live_stock.get_warehouse_inventory(
            **_cursor_kwargs(tenant.other_location_id, db, access)
        )
        w1_filter = await live_stock.get_warehouse_inventory(
            **_cursor_kwargs(
                tenant.location_id,
                db,
                access,
                has_vehicle=True,
            )
        )
        w2_filter = await live_stock.get_warehouse_inventory(
            **_cursor_kwargs(
                tenant.other_location_id,
                db,
                access,
                has_vehicle=True,
            )
        )
        w1_summary = await live_stock.get_warehouse_inventory_summary(
            tenant.location_id,
            db,
            access,
        )
        w2_summary = await live_stock.get_warehouse_inventory_summary(
            tenant.other_location_id,
            db,
            access,
        )
        sources = await live_stock.get_batch_stock_sources(
            batch_id,
            db,
            access,
        )
        attribution = await get_live_stock_vehicle_sources(
            db,
            company_id=tenant.company_id,
            vehicle_ids=[vehicle_id],
        )

    def display(row: dict | None) -> dict[str, Decimal]:
        if row is None:
            return {
                "warehouse": D("0"),
                "vehicle": D("0"),
                "total": D("0"),
            }
        return {
            "warehouse": D(row["on_hand_quantity"]),
            "vehicle": D(row["vehicle_quantity"]),
            "total": D(row["total_quantity"]),
        }

    observation = {
        "stage": stage,
        "reader": access_kind,
        "physical": physical,
        "physical_total": sum(physical.values(), D("0")),
        "latest_route_source": attribution.get(vehicle_id),
        "w1": display(_variant_row(w1_page, tenant.variant_id)),
        "w2": display(_variant_row(w2_page, tenant.variant_id)),
        "w1_vehicle_filter": _variant_row(
            w1_filter, tenant.variant_id
        ) is not None,
        "w2_vehicle_filter": _variant_row(
            w2_filter, tenant.variant_id
        ) is not None,
        "sources": _available_sources(sources),
        "w1_summary": {
            "stock_total": int(w1_summary["stock_total"]),
            "alert_count": int(w1_summary["alert_count"]),
        },
        "w2_summary": {
            "stock_total": int(w2_summary["stock_total"]),
            "alert_count": int(w2_summary["alert_count"]),
        },
    }
    print(
        "R3_VEHICLE_ATTRIBUTION_STAGE "
        + json.dumps(
            observation,
            default=str,
            sort_keys=True,
        ),
        flush=True,
    )
    return observation


async def test_r3_latest_route_source_is_display_attribution_not_physical_ownership(pg):
    tenant = pg.tenants[0]
    w1, w2 = int(tenant.location_id), int(tenant.other_location_id)

    await _enable_second_warehouse(pg, tenant)
    field = await _seed_mobile_uom_and_field(pg, tenant)
    zone_id, _shop_id = await _seed_commercial_master(pg, tenant, field)

    # Real supplier receipts establish independent W1/W2 physical and financial
    # truth. No balance is manufactured by the test.
    w1_lot = "R3-W1-" + uuid4().hex[:12]
    w2_lot = "R3-W2-" + uuid4().hex[:12]
    w1_receipt = pg.request(lot=w1_lot, quantity="100", cost="2")
    w2_receipt = pg.request(lot=w2_lot, quantity="100", cost="4").model_copy(
        update={"location_id": w2}
    )
    async with pg.session() as db:
        assert await pg.post(db, w1_receipt) == {"message": "INBOUND_POSTED"}
    async with pg.session() as db:
        assert await pg.post(db, w2_receipt) == {"message": "INBOUND_POSTED"}

    w2_batch_id = await _batch_id(pg, tenant, w2_lot)

    # Canonical Vehicle master command creates exactly one custody location.
    async with pg.session() as db:
        vehicle = await create_vehicle(
            db,
            company_id=tenant.company_id,
            actor_id=int(tenant.owner.operational_driver.id),
            command=CreateVehicleCommand(
                request_id=str(uuid4()),
                plate_number="R3-" + uuid4().hex[:12],
                vehicle_type="Van",
                maintenance_status="Active",
            ),
        )
        vehicle_id = int(vehicle["id"])
        vehicle_location_id = int(
            await db.scalar(
                select(InventoryLocation.id).where(
                    InventoryLocation.company_id == tenant.company_id,
                    InventoryLocation.vehicle_id == vehicle_id,
                    InventoryLocation.location_type == "VEHICLE",
                    InventoryLocation.is_active.is_(True),
                )
            )
        )

    reader_role_id = await _grant_restricted_reader(
        pg,
        tenant,
        vehicle_location_id=vehicle_location_id,
    )

    financial = await _financial(pg, tenant)
    assert financial == {
        "quantity": D("200"),
        "value": D("600"),
        "events": [
            ("PURCHASE_IN", D("100"), D("200")),
            ("PURCHASE_IN", D("100"), D("400")),
        ],
    }

    # A. Direct W2 -> Vehicle load with no Route. Physical custody is real but
    # there is no route-source warehouse to which Live Stock can attribute it.
    async with pg.session() as db:
        direct = await mutate_vehicle_load(
            db,
            access=tenant.owner.access(db),
            actor_id=tenant.owner.driver_id,
            vehicle_id=vehicle_id,
            warehouse_id=w2,
            direction="ADD",
            request_id=uuid4(),
            items=[{
                "product_variant_id": tenant.variant_id,
                "quantity": D("30"),
            }],
        )
        assert direct["direction"] == "ADD"
        assert direct["movement_count"] == 1

    stage_a = await _observe(
        pg,
        tenant,
        stage="direct_w2_no_route",
        vehicle_id=vehicle_id,
        vehicle_location_id=vehicle_location_id,
        batch_id=w2_batch_id,
    )
    assert stage_a["physical"] == {
        "w1": D("100"),
        "w2": D("70"),
        "vehicle": D("30"),
    }
    assert stage_a["latest_route_source"] is None
    assert stage_a["w1"] == {
        "warehouse": D("100"),
        "vehicle": D("0"),
        "total": D("100"),
    }
    assert stage_a["w2"] == {
        "warehouse": D("70"),
        "vehicle": D("0"),
        "total": D("70"),
    }
    assert not stage_a["w1_vehicle_filter"]
    assert not stage_a["w2_vehicle_filter"]
    assert stage_a["sources"] == {
        w2: ("WAREHOUSE", D("70")),
        vehicle_location_id: ("VEHICLE", D("30")),
    }
    assert stage_a["w1_summary"]["stock_total"] == 1
    assert stage_a["w2_summary"]["stock_total"] == 1
    # The missing 30 is not lost stock: it exists physically but is simply not
    # warehouse-attributed without a qualifying route.
    assert stage_a["w1"]["total"] + stage_a["w2"]["total"] == D("170")
    assert stage_a["physical_total"] == D("200")

    # B. Launch a canonical Route sourced from W1 with target equal to current
    # Vehicle custody. Route creation must change attribution only, not stock.
    before_route1_movements = await _movement_count(pg, tenant)
    route1_payload = DispatchRouteRequest(
        zone_id=zone_id,
        driver_id=field.driver.id,
        vehicle_id=vehicle_id,
        source_location_id=w1,
        inventory_base={str(tenant.variant_id): D("30")},
        expected_inventory_base={str(tenant.variant_id): D("30")},
    )
    async with pg.session() as db:
        route1 = await dispatch.dispatch_route(
            route1_payload,
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )
        route1_id = int(route1["route_id"])
    assert await _movement_count(pg, tenant) == before_route1_movements

    stage_b = await _observe(
        pg,
        tenant,
        stage="active_route_w1",
        vehicle_id=vehicle_id,
        vehicle_location_id=vehicle_location_id,
        batch_id=w2_batch_id,
    )
    assert stage_b["physical"] == stage_a["physical"]
    assert stage_b["latest_route_source"] == w1
    assert stage_b["w1"] == {
        "warehouse": D("100"),
        "vehicle": D("30"),
        "total": D("130"),
    }
    assert stage_b["w2"] == {
        "warehouse": D("70"),
        "vehicle": D("0"),
        "total": D("70"),
    }
    assert stage_b["w1_vehicle_filter"]
    assert not stage_b["w2_vehicle_filter"]
    # The W2 batch still says W2 + VEHICLE physically, even while Live Stock's
    # warehouse view attributes that Vehicle quantity to W1.
    assert stage_b["sources"] == stage_a["sources"]
    assert stage_b["w1"]["total"] + stage_b["w2"]["total"] == D("200")

    # Direct W2 load while W1 Route owns custody is canonically blocked.
    movements_before_block = await _movement_count(pg, tenant)
    async with pg.session() as db:
        with pytest.raises(VehicleError) as blocked:
            await mutate_vehicle_load(
                db,
                access=tenant.owner.access(db),
                actor_id=tenant.owner.driver_id,
                vehicle_id=vehicle_id,
                warehouse_id=w2,
                direction="ADD",
                request_id=uuid4(),
                items=[{
                    "product_variant_id": tenant.variant_id,
                    "quantity": D("10"),
                }],
            )
        assert blocked.value.code == "VEHICLE_LOAD_OWNED_BY_WORKFLOW"
        assert blocked.value.status_code == 409
        assert blocked.value.context["route_id"] == route1_id
    assert await _movement_count(pg, tenant) == movements_before_block
    assert await _physical(
        pg, tenant, vehicle_location_id=vehicle_location_id
    ) == stage_b["physical"]

    # C. Close W1 Route. Direct W2 movement becomes legal again, but the latest
    # Route row still points at W1, so all Vehicle custody remains attributed W1.
    async with pg.session() as db:
        closed = await dispatch.update_route_status(
            route1_id,
            UpdateRouteStatusRequest(status="closed"),
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )
        assert closed["message"] == "تم تحديث خط السير بنجاح"
    async with pg.session() as db:
        route = await db.scalar(
            select(DispatchRoute).where(
                DispatchRoute.company_id == tenant.company_id,
                DispatchRoute.id == route1_id,
            )
        )
        assert route is not None and route.status == "closed"

    async with pg.session() as db:
        added = await mutate_vehicle_load(
            db,
            access=tenant.owner.access(db),
            actor_id=tenant.owner.driver_id,
            vehicle_id=vehicle_id,
            warehouse_id=w2,
            direction="ADD",
            request_id=uuid4(),
            items=[{
                "product_variant_id": tenant.variant_id,
                "quantity": D("20"),
            }],
        )
        assert added["movement_count"] == 1

    stage_c_add = await _observe(
        pg,
        tenant,
        stage="closed_w1_route_then_direct_w2_add",
        vehicle_id=vehicle_id,
        vehicle_location_id=vehicle_location_id,
        batch_id=w2_batch_id,
    )
    assert stage_c_add["physical"] == {
        "w1": D("100"),
        "w2": D("50"),
        "vehicle": D("50"),
    }
    assert stage_c_add["latest_route_source"] == w1
    assert stage_c_add["w1"] == {
        "warehouse": D("100"),
        "vehicle": D("50"),
        "total": D("150"),
    }
    assert stage_c_add["w2"] == {
        "warehouse": D("50"),
        "vehicle": D("0"),
        "total": D("50"),
    }
    assert stage_c_add["sources"] == {
        w2: ("WAREHOUSE", D("50")),
        vehicle_location_id: ("VEHICLE", D("50")),
    }
    assert stage_c_add["w1"]["total"] + stage_c_add["w2"]["total"] == D("200")

    async with pg.session() as db:
        unloaded = await mutate_vehicle_load(
            db,
            access=tenant.owner.access(db),
            actor_id=tenant.owner.driver_id,
            vehicle_id=vehicle_id,
            warehouse_id=w2,
            direction="UNLOAD",
            request_id=uuid4(),
            items=[{
                "product_variant_id": tenant.variant_id,
                "quantity": D("10"),
                "stock_status": "AVAILABLE",
            }],
        )
        assert unloaded["movement_count"] == 1

    stage_c_unload = await _observe(
        pg,
        tenant,
        stage="closed_w1_route_then_direct_w2_unload",
        vehicle_id=vehicle_id,
        vehicle_location_id=vehicle_location_id,
        batch_id=w2_batch_id,
    )
    assert stage_c_unload["physical"] == {
        "w1": D("100"),
        "w2": D("60"),
        "vehicle": D("40"),
    }
    assert stage_c_unload["latest_route_source"] == w1
    assert stage_c_unload["w1"]["vehicle"] == D("40")
    assert stage_c_unload["w2"]["vehicle"] == D("0")
    assert stage_c_unload["sources"] == {
        w2: ("WAREHOUSE", D("60")),
        vehicle_location_id: ("VEHICLE", D("40")),
    }

    # D. A newer Route sourced from W2 flips the entire displayed Vehicle
    # attribution to W2 without any physical or financial movement.
    before_route2_movements = await _movement_count(pg, tenant)
    route2_payload = DispatchRouteRequest(
        zone_id=zone_id,
        driver_id=field.driver.id,
        vehicle_id=vehicle_id,
        source_location_id=w2,
        inventory_base={str(tenant.variant_id): D("40")},
        expected_inventory_base={str(tenant.variant_id): D("40")},
    )
    async with pg.session() as db:
        route2 = await dispatch.dispatch_route(
            route2_payload,
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )
        route2_id = int(route2["route_id"])
    assert route2_id > route1_id
    assert await _movement_count(pg, tenant) == before_route2_movements

    stage_d = await _observe(
        pg,
        tenant,
        stage="newer_route_w2",
        vehicle_id=vehicle_id,
        vehicle_location_id=vehicle_location_id,
        batch_id=w2_batch_id,
    )
    assert stage_d["physical"] == stage_c_unload["physical"]
    assert stage_d["latest_route_source"] == w2
    assert stage_d["w1"] == {
        "warehouse": D("100"),
        "vehicle": D("0"),
        "total": D("100"),
    }
    assert stage_d["w2"] == {
        "warehouse": D("60"),
        "vehicle": D("40"),
        "total": D("100"),
    }
    assert not stage_d["w1_vehicle_filter"]
    assert stage_d["w2_vehicle_filter"]
    assert stage_d["sources"] == stage_c_unload["sources"]
    assert stage_d["w1"]["total"] + stage_d["w2"]["total"] == D("200")

    # E. A restricted reader initially sees the same W2 attribution because it
    # can read W1, W2 and the concrete VEHICLE custody location.
    restricted_before = await _observe(
        pg,
        tenant,
        stage="restricted_reader_before_vehicle_revoke",
        vehicle_id=vehicle_id,
        vehicle_location_id=vehicle_location_id,
        batch_id=w2_batch_id,
        access_kind="ordinary",
    )
    assert restricted_before["w2"]["vehicle"] == D("40")
    assert restricted_before["w2_vehicle_filter"]
    assert restricted_before["sources"] == stage_d["sources"]

    # Revoke only the Vehicle location grant. Presentation hides Vehicle stock;
    # physical balances and owner truth must remain exactly unchanged.
    async with pg.session() as db:
        await db.execute(
            delete(UserLocationAccess).where(
                UserLocationAccess.company_id == tenant.company_id,
                UserLocationAccess.driver_id == tenant.ordinary.driver_id,
                UserLocationAccess.location_id == vehicle_location_id,
                UserLocationAccess.role_id == reader_role_id,
            )
        )
        await db.commit()

    restricted_after = await _observe(
        pg,
        tenant,
        stage="restricted_reader_after_vehicle_revoke",
        vehicle_id=vehicle_id,
        vehicle_location_id=vehicle_location_id,
        batch_id=w2_batch_id,
        access_kind="ordinary",
    )
    assert restricted_after["physical"] == stage_d["physical"]
    assert restricted_after["latest_route_source"] == w2
    assert restricted_after["w2"]["warehouse"] == D("60")
    assert restricted_after["w2"]["vehicle"] == D("0")
    assert not restricted_after["w2_vehicle_filter"]
    assert restricted_after["sources"] == {
        w2: ("WAREHOUSE", D("60")),
    }

    owner_after_revoke = await _observe(
        pg,
        tenant,
        stage="owner_truth_after_reader_vehicle_revoke",
        vehicle_id=vehicle_id,
        vehicle_location_id=vehicle_location_id,
        batch_id=w2_batch_id,
    )
    assert owner_after_revoke["w2"]["vehicle"] == D("40")
    assert owner_after_revoke["sources"] == stage_d["sources"]

    # Every route/direct movement above is internal physical custody only.
    # No duplicate stock and no extra financial ownership/COGS posting exists.
    final_financial = await _financial(pg, tenant)
    assert final_financial == financial
    assert final_financial["quantity"] == owner_after_revoke["physical_total"]
    assert owner_after_revoke["physical_total"] == D("200")

    print(
        "R3_VEHICLE_ATTRIBUTION_PASS "
        + json.dumps(
            {
                "method": pg.method,
                "physical_final": owner_after_revoke["physical"],
                "latest_route_source": w2,
                "financial_quantity": str(final_financial["quantity"]),
                "financial_value": str(final_financial["value"]),
                "cost_events": [
                    [kind, str(quantity), str(value)]
                    for kind, quantity, value in final_financial["events"]
                ],
                "direct_without_route_unattributed": True,
                "closed_w1_route_kept_w1_attribution_for_later_w2_load": True,
                "newer_w2_route_flipped_display_without_stock_move": True,
                "vehicle_permission_revoke_changed_visibility_not_stock": True,
            },
            default=str,
            sort_keys=True,
        ),
        flush=True,
    )
