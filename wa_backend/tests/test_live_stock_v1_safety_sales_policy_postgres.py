from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api import catalog, dispatch
from api.driver import end_work_session, start_work_session, update_visit
from api.inventory_stock_policy import get_effective_shelf_life_policy
from api.representative_settlement import (
    CustodyConfirm,
    read_representative_custody,
    receive_representative_custody,
)
from api.warehouse import live_stock, transfers
from domains.inventory_vehicle_load.service import VehicleError, mutate_vehicle_load
from models import (
    Company,
    DispatchRoute,
    InventoryBalance,
    InventoryCostEvent,
    InventoryCostState,
    InventoryMovement,
    InventoryStockPolicy,
    ProductBatch,
    ProductVariant,
    Shop,
    Visit,
    WorkSession,
)
from schemas import (
    AuthorizeSessionRequest,
    DispatchRouteRequest,
    InventoryStatusChangeRequest,
    SessionStartRequest,
    UpdateRouteStatusRequest,
    UpgradedInboundRequest,
    VisitUpdateRequest,
)
from services import get_company_local_date
from tests.test_inbound_no_lot_frozen_postgres import pg
from tests.test_live_stock_v1_quantity_reconciliation_postgres import (
    _create_vehicle_with_historical_attribution,
    _seed_carton_conversion,
)
from tests.test_live_stock_v1_route_sale_unload_postgres import (
    _seed_commercial_master,
    _seed_mobile_uom_and_field,
)


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_NO_LOT_PG_GATE") != "1",
        reason="Explicit disposable PostgreSQL 16 acceptance only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


# Independent expectations: fixed before endpoint reads.
CARTON_TO_BASE = Decimal("8")
SAFETY_INBOUND_CARTONS = Decimal("20")
SAFETY_INBOUND_BASE = Decimal("160")
DIRECT_VEHICLE_LOAD = Decimal("80")
WAREHOUSE_AFTER_LOAD = Decimal("80")
VEHICLE_AFTER_LOAD = Decimal("80")
STATUS_BUCKET = Decimal("10")
WAREHOUSE_AVAILABLE_AFTER_STATUS = Decimal("50")
FIELD_CARTONS = Decimal("1")
FIELD_PACKS = Decimal("3")
FIELD_SALE_BASE = FIELD_CARTONS * CARTON_TO_BASE + FIELD_PACKS
DAMAGED_EXCHANGE_BASE = Decimal("3")
COMPANY_AFTER_SALE = SAFETY_INBOUND_BASE - FIELD_SALE_BASE
VEHICLE_AVAILABLE_AFTER_SALE = VEHICLE_AFTER_LOAD - FIELD_SALE_BASE
VEHICLE_AVAILABLE_AFTER_EXCHANGE = (
    VEHICLE_AVAILABLE_AFTER_SALE - DAMAGED_EXCHANGE_BASE
)
FINAL_COMPANY_PHYSICAL = COMPANY_AFTER_SALE
PURCHASE_UNIT_COST = Decimal("2")
PURCHASE_VALUE = SAFETY_INBOUND_BASE * PURCHASE_UNIT_COST
SALE_COGS = FIELD_SALE_BASE * PURCHASE_UNIT_COST
FINAL_COST_VALUE = PURCHASE_VALUE - SALE_COGS

assert SAFETY_INBOUND_BASE == Decimal("160")
assert WAREHOUSE_AFTER_LOAD == VEHICLE_AFTER_LOAD == Decimal("80")
assert WAREHOUSE_AVAILABLE_AFTER_STATUS == Decimal("50")
assert FIELD_SALE_BASE == Decimal("11")
assert COMPANY_AFTER_SALE == Decimal("149")
assert VEHICLE_AVAILABLE_AFTER_SALE == Decimal("69")
assert VEHICLE_AVAILABLE_AFTER_EXCHANGE == Decimal("66")
assert FINAL_COST_VALUE == Decimal("298")


async def _set_company_timezone(pg_gate, tenant, timezone_name: str) -> None:
    """Reference/config fixture only; never mutates inventory, ledger or costing."""
    async with AsyncSession(pg_gate.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": str(tenant.company_id)},
        )
        company = await seed.scalar(
            select(Company).where(Company.id == tenant.company_id)
        )
        assert company is not None
        company.timezone = timezone_name
        await seed.commit()


async def _company_date(pg_gate, tenant) -> date:
    async with pg_gate.session() as db:
        return await get_company_local_date(db, tenant.company_id)


async def _set_shelf_policy(pg_gate, tenant, *, minimum_days: int | None) -> None:
    """Shelf-life management is READ_ONLY_V1; seed only this reference policy."""
    async with AsyncSession(pg_gate.admin_engine, expire_on_commit=False) as seed:
        await seed.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": str(tenant.company_id)},
        )
        policy = await seed.scalar(
            select(InventoryStockPolicy).where(
                InventoryStockPolicy.company_id == tenant.company_id,
                InventoryStockPolicy.location_id == tenant.location_id,
                InventoryStockPolicy.product_variant_id == tenant.variant_id,
            )
        )
        if minimum_days is None:
            if policy is not None:
                policy.is_active = False
        elif policy is None:
            seed.add(
                InventoryStockPolicy(
                    company_id=tenant.company_id,
                    location_id=tenant.location_id,
                    product_variant_id=tenant.variant_id,
                    minimum_quantity=Decimal("0"),
                    target_quantity=None,
                    minimum_remaining_shelf_life_days=minimum_days,
                    is_active=True,
                )
            )
        else:
            policy.minimum_remaining_shelf_life_days = minimum_days
            policy.is_active = True
        await seed.commit()


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


async def _live_list_row(pg_gate, tenant):
    async with pg_gate.session() as db:
        page = await live_stock.get_warehouse_inventory(
            location_id=tenant.location_id,
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
            has_vehicle=False,
            minimum_unset=False,
            sort="name_asc",
            db=db,
            access=tenant.owner.access(db),
        )
        return next(row for row in page["items"] if row["id"] == tenant.variant_id)


async def _batch_detail_row(pg_gate, tenant, batch_id: int):
    async with pg_gate.session() as db:
        detail = await live_stock.get_warehouse_inventory_batches(
            product_variant_id=tenant.variant_id,
            location_id=tenant.location_id,
            cursor=None,
            limit=100,
            db=db,
            access=tenant.owner.access(db),
        )
        return next(row for row in detail["batches"] if row["batch_id"] == batch_id)


async def _source_evidence(pg_gate, tenant, batch_id: int):
    async with pg_gate.session() as db:
        return await live_stock.get_batch_stock_sources(
            batch_id=batch_id,
            db=db,
            access=tenant.owner.access(db),
        )


def _source_status_quantities(source_payload) -> dict[int, dict[str, Decimal]]:
    out: dict[int, dict[str, Decimal]] = {}
    for source in source_payload["sources"]:
        out[int(source["location_id"])] = {
            str(status["stock_status"]): Decimal(status["on_hand_quantity"])
            for status in source["statuses"]
            if Decimal(status["on_hand_quantity"]) != 0
        }
    return out


async def _variant_truth(pg_gate, tenant) -> dict:
    async with pg_gate.session() as db:
        balances = (
            await db.execute(
                select(
                    InventoryBalance.location_id,
                    InventoryBalance.stock_status,
                    func.sum(InventoryBalance.on_hand_quantity),
                    func.sum(InventoryBalance.reserved_quantity),
                )
                .where(
                    InventoryBalance.company_id == tenant.company_id,
                    InventoryBalance.product_variant_id == tenant.variant_id,
                )
                .group_by(
                    InventoryBalance.location_id,
                    InventoryBalance.stock_status,
                )
                .order_by(
                    InventoryBalance.location_id,
                    InventoryBalance.stock_status,
                )
            )
        ).all()
        state = await db.scalar(
            select(InventoryCostState).where(
                InventoryCostState.company_id == tenant.company_id,
                InventoryCostState.product_variant_id == tenant.variant_id,
            )
        )
        return {
            "balances": tuple(
                (
                    int(row[0]),
                    str(row[1]),
                    Decimal(row[2]),
                    Decimal(row[3]),
                )
                for row in balances
            ),
            "physical": Decimal(
                await db.scalar(
                    select(
                        func.coalesce(
                            func.sum(InventoryBalance.on_hand_quantity), 0
                        )
                    ).where(
                        InventoryBalance.company_id == tenant.company_id,
                        InventoryBalance.product_variant_id == tenant.variant_id,
                    )
                )
            ),
            "movement_count": int(
                await db.scalar(
                    select(func.count())
                    .select_from(InventoryMovement)
                    .where(
                        InventoryMovement.company_id == tenant.company_id,
                        InventoryMovement.product_variant_id == tenant.variant_id,
                    )
                )
                or 0
            ),
            "cost_event_count": int(
                await db.scalar(
                    select(func.count())
                    .select_from(InventoryCostEvent)
                    .where(
                        InventoryCostEvent.company_id == tenant.company_id,
                        InventoryCostEvent.product_variant_id == tenant.variant_id,
                    )
                )
                or 0
            ),
            "cost_quantity": (
                Decimal(state.quantity) if state is not None else Decimal("0")
            ),
            "cost_value": (
                Decimal(state.inventory_value)
                if state is not None
                else Decimal("0")
            ),
            "average_cost": (
                Decimal(state.average_unit_cost)
                if state is not None
                else Decimal("0")
            ),
        }


async def _assert_no_negative(pg_gate, tenant) -> None:
    async with pg_gate.session() as db:
        bad = await db.scalar(
            select(func.count())
            .select_from(InventoryBalance)
            .where(
                InventoryBalance.company_id == tenant.company_id,
                InventoryBalance.product_variant_id == tenant.variant_id,
                (
                    (InventoryBalance.on_hand_quantity < 0)
                    | (InventoryBalance.reserved_quantity < 0)
                    | (
                        InventoryBalance.reserved_quantity
                        > InventoryBalance.on_hand_quantity
                    )
                ),
            )
        )
        assert int(bad or 0) == 0


async def _variant_version(pg_gate, tenant) -> int:
    async with pg_gate.session() as db:
        value = await db.scalar(
            select(ProductVariant.version).where(
                ProductVariant.company_id == tenant.company_id,
                ProductVariant.id == tenant.variant_id,
            )
        )
        assert value is not None
        return int(value)


def _lifecycle_command(version: int, reason: str):
    return catalog.LifecycleCommand(
        request_id=uuid4(),
        expected_version=version,
        reason=reason,
    )


async def _catalog_command(pg_gate, tenant, fn, reason: str):
    version = await _variant_version(pg_gate, tenant)
    async with pg_gate.session() as db:
        return await fn(
            tenant.variant_id,
            _lifecycle_command(version, reason),
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )


async def _status_change(
    pg_gate,
    tenant,
    *,
    batch_id: int,
    location_id: int,
    source: str,
    destination: str,
    quantity: Decimal,
):
    payload = InventoryStatusChangeRequest(
        request_id=uuid4(),
        location_id=location_id,
        product_variant_id=tenant.variant_id,
        batch_id=batch_id,
        uom_id=tenant.uom_id,
        source_status=source,
        destination_status=destination,
        quantity=quantity,
        reason=f"Safety acceptance {source}->{destination}",
    )
    async with pg_gate.session() as db:
        return await transfers.change_inventory_status(
            payload,
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )


async def _add_second_shop(pg_gate, tenant, zone_id: int, first_shop_id: int) -> int:
    async with pg_gate.session() as db:
        first = await db.scalar(
            select(Shop).where(
                Shop.company_id == tenant.company_id,
                Shop.id == first_shop_id,
            )
        )
        assert first is not None
        shop = Shop(
            company_id=tenant.company_id,
            name="Safety second shop " + uuid4().hex[:10],
            zone_id=zone_id,
            tax_jurisdiction_id=first.tax_jurisdiction_id,
            current_balance=Decimal("0"),
            max_debt_limit=Decimal("1000"),
            is_active=True,
        )
        db.add(shop)
        await db.commit()
        return int(shop.id)


async def _sale_attempt(
    pg_gate,
    *,
    visit_id: int,
    field,
    cartons: int = 0,
    packs: int = 1,
    cash: Decimal | None = None,
    request_id=None,
):
    payload = VisitUpdateRequest(
        request_id=request_id or uuid4(),
        outcome="Sale",
        cart_items=[
            {
                "product_variant_id": field_variant_id(field),
                "quantity": cartons,
                "packs_quantity": packs,
            }
        ],
        returns=[],
        cash_collected=(
            cash
            if cash is not None
            else Decimal(cartons * 8 + packs)
        ),
    )
    async with pg_gate.session() as db:
        return await update_visit(
            visit_id,
            payload,
            db,
            field.context,
            field.driver,
        )


def field_variant_id(field) -> int:
    # Filled on the test fixture object only to keep sale helpers explicit.
    return int(field._safety_variant_id)


async def test_company_date_expiry_future_production_and_shelf_life_truth(pg):
    tenant = pg.tenants[0]

    # The database clock is authoritative; these two real zones are chosen so
    # this acceptance run observes adjacent commercial dates.
    await _set_company_timezone(pg, tenant, "Etc/GMT+12")
    early_date = await _company_date(pg, tenant)
    await _set_company_timezone(pg, tenant, "UTC")
    later_date = await _company_date(pg, tenant)
    assert later_date == early_date + timedelta(days=1)

    # Create an expires-today batch through real supplier inbound on the early
    # company date. Default V1 shelf-life policy is zero days.
    await _set_company_timezone(pg, tenant, "Etc/GMT+12")
    batch_number = "SAFETY-EXP-" + uuid4().hex[:12]
    request = pg.request(
        lot=batch_number,
        quantity="8",
        cost="2",
        production=early_date - timedelta(days=7),
        expiry=early_date,
    )
    async with pg.session() as db:
        assert await pg.post(db, request) == {"message": "INBOUND_POSTED"}
    batch_id = await _batch_id(pg, tenant, batch_number)

    async with pg.session() as db:
        effective = await get_effective_shelf_life_policy(
            tenant.location_id,
            tenant.variant_id,
            db,
            tenant.owner.access(db),
        )
    assert effective.management_mode == "READ_ONLY_V1"
    assert effective.minimum_remaining_shelf_life_days == 0
    assert effective.requirement_applies is False
    assert effective.source == "NO_ACTIVE_POLICY"

    today = await _batch_detail_row(pg, tenant, batch_id)
    assert today["days_to_expiry"] == 0
    assert Decimal(today["on_hand_quantity"]) == Decimal("8")
    assert Decimal(today["available_for_sale_quantity"]) == Decimal("8")
    assert Decimal(today["restricted_quantity"]) == Decimal("0")
    assert Decimal(today["expiry_unavailable_quantity"]) == Decimal("0")

    # V1 exposes shelf-life management read-only. Seed an exact active policy
    # as reference configuration and prove the same expires-today batch fails
    # the one-day requirement without moving any stock.
    before_policy = await _variant_truth(pg, tenant)
    await _set_shelf_policy(pg, tenant, minimum_days=1)
    async with pg.session() as db:
        effective = await get_effective_shelf_life_policy(
            tenant.location_id,
            tenant.variant_id,
            db,
            tenant.owner.access(db),
        )
    assert effective.minimum_remaining_shelf_life_days == 1
    assert effective.requirement_applies is True
    assert effective.source == "EXACT_ACTIVE_POLICY"
    short = await _batch_detail_row(pg, tenant, batch_id)
    assert Decimal(short["available_for_sale_quantity"]) == Decimal("0")
    assert Decimal(short["restricted_quantity"]) == Decimal("8")
    assert Decimal(short["expiry_unavailable_quantity"]) == Decimal("8")
    after_policy = await _variant_truth(pg, tenant)
    assert after_policy == before_policy

    # Disable the reference policy and advance only the company timezone.
    # The same real batch is now expired-yesterday and remains physical stock,
    # but is not saleable.
    await _set_shelf_policy(pg, tenant, minimum_days=None)
    await _set_company_timezone(pg, tenant, "UTC")
    assert await _company_date(pg, tenant) == later_date
    expired = await _batch_detail_row(pg, tenant, batch_id)
    assert expired["days_to_expiry"] == -1
    assert Decimal(expired["on_hand_quantity"]) == Decimal("8")
    assert Decimal(expired["available_for_sale_quantity"]) == Decimal("0")
    assert Decimal(expired["restricted_quantity"]) == Decimal("8")
    assert Decimal(expired["expiry_unavailable_quantity"]) == Decimal("8")

    # A second real batch is received while its production date is legal.
    future_number = "SAFETY-FUT-" + uuid4().hex[:12]
    future_request = pg.request(
        lot=future_number,
        quantity="8",
        cost="2",
        production=later_date,
        expiry=later_date + timedelta(days=30),
    )
    async with pg.session() as db:
        assert await pg.post(db, future_request) == {"message": "INBOUND_POSTED"}
    future_batch_id = await _batch_id(pg, tenant, future_number)

    # Move the company date back by timezone only. This does not touch batch
    # metadata or inventory; the same batch is now future-production.
    await _set_company_timezone(pg, tenant, "Etc/GMT+12")
    assert await _company_date(pg, tenant) == early_date
    future = await _batch_detail_row(pg, tenant, future_batch_id)
    assert future["production_date"] == later_date
    assert Decimal(future["on_hand_quantity"]) == Decimal("8")
    assert Decimal(future["available_for_sale_quantity"]) == Decimal("0")
    assert Decimal(future["restricted_quantity"]) == Decimal("8")
    assert Decimal(future["expiry_unavailable_quantity"]) == Decimal("0")

    list_row = await _live_list_row(pg, tenant)
    assert Decimal(list_row["on_hand_quantity"]) == Decimal("16")
    evidence = _source_status_quantities(
        await _source_evidence(pg, tenant, future_batch_id)
    )
    assert evidence[tenant.location_id]["AVAILABLE"] == Decimal("8")

    # Canonical inbound itself rejects dates already invalid on the current
    # company date, with full rollback and no inventory/cost evidence.
    before_rejections = await _variant_truth(pg, tenant)
    invalid_future = pg.request(
        lot="SAFETY-REJECT-FUT-" + uuid4().hex[:8],
        quantity="1",
        cost="2",
        production=early_date + timedelta(days=1),
        expiry=early_date + timedelta(days=30),
    )
    async with pg.session() as db:
        with pytest.raises(HTTPException) as caught:
            await pg.post(db, invalid_future)
        assert caught.value.status_code == 422
        assert caught.value.detail["code"] == "INBOUND_PRODUCTION_DATE_FUTURE"
    assert await _variant_truth(pg, tenant) == before_rejections

    await _set_company_timezone(pg, tenant, "UTC")
    invalid_expired = pg.request(
        lot="SAFETY-REJECT-EXP-" + uuid4().hex[:8],
        quantity="1",
        cost="2",
        production=later_date - timedelta(days=10),
        expiry=later_date - timedelta(days=1),
    )
    async with pg.session() as db:
        with pytest.raises(HTTPException) as caught:
            await pg.post(db, invalid_expired)
        assert caught.value.status_code == 422
        assert caught.value.detail["code"] == "INBOUND_BATCH_EXPIRED"
    assert await _variant_truth(pg, tenant) == before_rejections
    await _assert_no_negative(pg, tenant)


async def test_product_policies_stock_states_field_sales_and_active_unload(pg):
    tenant = pg.tenants[0]
    field = await _seed_mobile_uom_and_field(pg, tenant)
    field._safety_variant_id = tenant.variant_id
    carton_uom_id = await _seed_carton_conversion(pg, tenant)
    zone_id, first_shop_id = await _seed_commercial_master(pg, tenant, field)
    second_shop_id = await _add_second_shop(
        pg, tenant, zone_id, first_shop_id
    )

    inbound_id = uuid4()
    batch_number = "SAFETY-SALE-" + inbound_id.hex[:12]
    inbound = UpgradedInboundRequest(
        request_id=inbound_id,
        supplier_id=tenant.supplier_id,
        location_id=tenant.location_id,
        reference_id="SAFETY-SALE-IN-" + inbound_id.hex,
        items=[
            {
                "product_variant_id": tenant.variant_id,
                "uom_id": carton_uom_id,
                "quantity": SAFETY_INBOUND_CARTONS,
                "unit_cost": Decimal("16"),
                "batch_number": batch_number,
            }
        ],
    )
    async with pg.session() as db:
        assert await pg.post(db, inbound) == {"message": "INBOUND_POSTED"}
    batch_id = await _batch_id(pg, tenant, batch_number)

    vehicle_id, vehicle_location_id = await _create_vehicle_with_historical_attribution(
        pg, tenant
    )
    load_id = uuid4()
    async with pg.session() as db:
        loaded = await mutate_vehicle_load(
            db,
            access=tenant.owner.access(db),
            actor_id=tenant.owner.driver_id,
            vehicle_id=vehicle_id,
            warehouse_id=tenant.location_id,
            direction="ADD",
            request_id=load_id,
            items=[
                {
                    "product_variant_id": tenant.variant_id,
                    "quantity": DIRECT_VEHICLE_LOAD,
                }
            ],
        )
    assert loaded["movement_count"] == 1

    # Real quantity-level safety reclassification; product hold/disposition is
    # deliberately left untouched to prove these are separate axes.
    for destination in ("QUARANTINED", "BLOCKED", "RECALLED"):
        changed = await _status_change(
            pg,
            tenant,
            batch_id=batch_id,
            location_id=tenant.location_id,
            source="AVAILABLE",
            destination=destination,
            quantity=STATUS_BUCKET,
        )
        assert changed["source_status"] == "AVAILABLE"
        assert changed["destination_status"] == destination

    after_status = await _variant_truth(pg, tenant)
    assert after_status["physical"] == SAFETY_INBOUND_BASE
    assert after_status["cost_quantity"] == SAFETY_INBOUND_BASE
    assert after_status["cost_value"] == PURCHASE_VALUE
    assert after_status["cost_event_count"] == 1

    detail = await _batch_detail_row(pg, tenant, batch_id)
    assert Decimal(detail["on_hand_quantity"]) == WAREHOUSE_AFTER_LOAD
    assert Decimal(detail["available_for_sale_quantity"]) == WAREHOUSE_AVAILABLE_AFTER_STATUS
    assert Decimal(detail["quarantined_quantity"]) == STATUS_BUCKET
    assert Decimal(detail["blocked_quantity"]) == STATUS_BUCKET
    assert Decimal(detail["recalled_quantity"]) == STATUS_BUCKET
    assert Decimal(detail["damaged_quantity"]) == Decimal("0")

    sources = _source_status_quantities(
        await _source_evidence(pg, tenant, batch_id)
    )
    assert sources[tenant.location_id] == {
        "AVAILABLE": WAREHOUSE_AVAILABLE_AFTER_STATUS,
        "BLOCKED": STATUS_BUCKET,
        "QUARANTINED": STATUS_BUCKET,
        "RECALLED": STATUS_BUCKET,
    }
    assert sources[vehicle_location_id] == {"AVAILABLE": VEHICLE_AFTER_LOAD}

    # Restricted-location and cross-tenant reads fail closed.
    async with pg.session() as db:
        with pytest.raises(HTTPException) as denied:
            await live_stock.get_warehouse_inventory(
                location_id=tenant.other_location_id,
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
                has_vehicle=False,
                minimum_unset=False,
                sort="name_asc",
                db=db,
                access=tenant.ordinary.access(db),
            )
        assert denied.value.status_code == 403

    foreign = pg.tenants[1]
    async with pg.session(1) as db:
        with pytest.raises(HTTPException) as isolated:
            await live_stock.get_warehouse_inventory(
                location_id=tenant.location_id,
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
                has_vehicle=False,
                minimum_unset=False,
                sort="name_asc",
                db=db,
                access=foreign.owner.access(db),
            )
        assert isolated.value.status_code == 404

    route_payload = DispatchRouteRequest(
        zone_id=zone_id,
        driver_id=field.driver.id,
        vehicle_id=vehicle_id,
        source_location_id=tenant.location_id,
        inventory_base={str(tenant.variant_id): DIRECT_VEHICLE_LOAD},
        expected_inventory_base={str(tenant.variant_id): DIRECT_VEHICLE_LOAD},
    )
    async with pg.session() as db:
        launched = await dispatch.dispatch_route(
            route_payload,
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )
        route_id = int(launched["route_id"])

    async with pg.session() as db:
        started = await start_work_session(
            SessionStartRequest(), db, field.context, field.driver
        )
        session_id = int(started["session_id"])
    async with pg.session() as db:
        await dispatch.authorize_session(
            session_id,
            AuthorizeSessionRequest(is_authorized=True),
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )
        visits = (
            await db.scalars(
                select(Visit)
                .where(
                    Visit.company_id == tenant.company_id,
                    Visit.work_session_id == session_id,
                    Visit.status == "Pending",
                    Visit.shop_id.in_([first_shop_id, second_shop_id]),
                )
                .order_by(Visit.id)
            )
        ).all()
        assert len(visits) == 2
        policy_visit_id = int(visits[0].id)
        damage_visit_id = int(visits[1].id)

    # Remaining Section 5.A rule: direct vehicle UNLOAD cannot bypass route
    # ownership while the route/session is active.
    before_unload = await _variant_truth(pg, tenant)
    async with pg.session() as db:
        with pytest.raises(VehicleError) as blocked:
            await mutate_vehicle_load(
                db,
                access=tenant.owner.access(db),
                actor_id=tenant.owner.driver_id,
                vehicle_id=vehicle_id,
                warehouse_id=tenant.location_id,
                direction="UNLOAD",
                request_id=uuid4(),
                items=[
                    {
                        "product_variant_id": tenant.variant_id,
                        "quantity": Decimal("1"),
                    }
                ],
            )
        assert blocked.value.code == "VEHICLE_LOAD_OWNED_BY_WORKFLOW"
        assert blocked.value.status_code == 409
        assert blocked.value.context["route_id"] == route_id
        assert blocked.value.context["work_session_id"] == session_id
        await db.rollback()
    assert await _variant_truth(pg, tenant) == before_unload

    # Same-company insufficient authority and cross-tenant mutation isolation
    # both leave tenant A stock untouched.
    async with pg.session() as db:
        with pytest.raises(VehicleError) as denied:
            await mutate_vehicle_load(
                db,
                access=tenant.ordinary.access(db),
                actor_id=tenant.ordinary.driver_id,
                vehicle_id=vehicle_id,
                warehouse_id=tenant.location_id,
                direction="UNLOAD",
                request_id=uuid4(),
                items=[{"product_variant_id": tenant.variant_id, "quantity": Decimal("1")}],
            )
        assert denied.value.status_code == 403
        await db.rollback()
    assert await _variant_truth(pg, tenant) == before_unload

    async with pg.session(1) as db:
        with pytest.raises(VehicleError) as foreign_denied:
            await mutate_vehicle_load(
                db,
                access=foreign.owner.access(db),
                actor_id=foreign.owner.driver_id,
                vehicle_id=vehicle_id,
                warehouse_id=tenant.location_id,
                direction="UNLOAD",
                request_id=uuid4(),
                items=[{"product_variant_id": tenant.variant_id, "quantity": Decimal("1")}],
            )
        assert foreign_denied.value.code == "VEHICLE_LOAD_VEHICLE_NOT_FOUND"
        assert foreign_denied.value.status_code == 404
        await db.rollback()
    assert await _variant_truth(pg, tenant) == before_unload

    async def rejected_sale(expected_code: str):
        before = await _variant_truth(pg, tenant)
        request = VisitUpdateRequest(
            request_id=uuid4(),
            outcome="Sale",
            cart_items=[
                {
                    "product_variant_id": tenant.variant_id,
                    "quantity": 0,
                    "packs_quantity": 1,
                }
            ],
            returns=[],
            cash_collected=Decimal("1"),
        )
        async with pg.session() as db:
            with pytest.raises(HTTPException) as caught:
                await update_visit(
                    policy_visit_id,
                    request,
                    db,
                    field.context,
                    field.driver,
                )
            assert caught.value.status_code == 409
            assert caught.value.detail["code"] == expected_code
        assert await _variant_truth(pg, tenant) == before
        await _assert_no_negative(pg, tenant)

    # RETIRING is a lifecycle policy; it blocks sale without becoming a hold.
    await _catalog_command(pg, tenant, catalog.retire_variant, "Safety retiring proof")
    await rejected_sale("PRODUCT_RETIRING_ROUTE_SALE_OPEN_BLOCKED")
    retiring_detail = await _batch_detail_row(pg, tenant, batch_id)
    assert Decimal(retiring_detail["available_for_sale_quantity"]) == Decimal("0")

    await _catalog_command(pg, tenant, catalog.restore_variant, "Restore for hold proof")
    await _catalog_command(
        pg, tenant, catalog.place_variant_sales_hold, "Safety sales hold proof"
    )
    await rejected_sale("PRODUCT_SALES_HOLD_ROUTE_SALE_OPEN_BLOCKED")
    hold_detail = await _batch_detail_row(pg, tenant, batch_id)
    assert Decimal(hold_detail["available_for_sale_quantity"]) == Decimal("0")

    await _catalog_command(
        pg, tenant, catalog.release_variant_sales_hold, "Release sales hold proof"
    )
    await _catalog_command(pg, tenant, catalog.recall_variant, "Safety recall proof")
    await rejected_sale("PRODUCT_RECALL_ROUTE_SALE_OPEN_BLOCKED")
    recall_detail = await _batch_detail_row(pg, tenant, batch_id)
    assert Decimal(recall_detail["available_for_sale_quantity"]) == Decimal("0")

    await _catalog_command(
        pg, tenant, catalog.cancel_variant_recall, "Cancel recall for active proof"
    )

    # ACTIVE/NONE sale is permitted. Mobile carton+pack math is 1*8+3=11 base.
    sale_request = VisitUpdateRequest(
        request_id=uuid4(),
        outcome="Sale",
        cart_items=[
            {
                "product_variant_id": tenant.variant_id,
                "quantity": int(FIELD_CARTONS),
                "packs_quantity": int(FIELD_PACKS),
            }
        ],
        returns=[],
        cash_collected=FIELD_SALE_BASE,
    )
    async with pg.session() as db:
        sold = await update_visit(
            policy_visit_id,
            sale_request,
            db,
            field.context,
            field.driver,
        )
        assert sold["message"] == "Visit updated successfully"

    after_sale = await _variant_truth(pg, tenant)
    assert after_sale["physical"] == COMPANY_AFTER_SALE
    assert after_sale["cost_quantity"] == COMPANY_AFTER_SALE
    assert after_sale["cost_value"] == FINAL_COST_VALUE
    assert after_sale["average_cost"] == PURCHASE_UNIT_COST
    assert after_sale["cost_event_count"] == 2

    async with pg.session() as db:
        sale_move = await db.scalar(
            select(InventoryMovement).where(
                InventoryMovement.company_id == tenant.company_id,
                InventoryMovement.reference_type == "VISIT_ITEM_OUT",
                InventoryMovement.reference_id == str(policy_visit_id),
            )
        )
        assert sale_move is not None
        assert Decimal(sale_move.quantity) == FIELD_SALE_BASE
        assert int(sale_move.source_location_id) == vehicle_location_id
        sale_cost = await db.scalar(
            select(InventoryCostEvent).where(
                InventoryCostEvent.company_id == tenant.company_id,
                InventoryCostEvent.inventory_movement_id == sale_move.id,
            )
        )
        assert sale_cost is not None
        assert sale_cost.event_type == "OUTBOUND"
        assert Decimal(sale_cost.quantity) == FIELD_SALE_BASE
        assert Decimal(sale_cost.total_cost) == SALE_COGS

    # Canonical customer damaged exchange creates DAMAGED custody and a 1:1
    # AVAILABLE replacement movement; it is not a generic status change.
    damage_request = VisitUpdateRequest(
        request_id=uuid4(),
        outcome="NoSale",
        notes="Safety damaged exchange",
        cart_items=[],
        returns=[
            {
                "product_variant_id": tenant.variant_id,
                "batch_id": batch_id,
                "quantity": 0,
                "packs_quantity": int(DAMAGED_EXCHANGE_BASE),
                "return_type": "Damaged",
                "reason": "Safety acceptance damaged return",
            }
        ],
    )
    async with pg.session() as db:
        returned = await update_visit(
            damage_visit_id,
            damage_request,
            db,
            field.context,
            field.driver,
        )
        assert returned["message"] == "Visit updated successfully"

    after_damage = await _variant_truth(pg, tenant)
    assert after_damage["physical"] == COMPANY_AFTER_SALE
    assert after_damage["cost_quantity"] == COMPANY_AFTER_SALE
    assert after_damage["cost_value"] == FINAL_COST_VALUE
    assert after_damage["cost_event_count"] == 4
    sources = _source_status_quantities(
        await _source_evidence(pg, tenant, batch_id)
    )
    assert sources[vehicle_location_id] == {
        "AVAILABLE": VEHICLE_AVAILABLE_AFTER_EXCHANGE,
        "DAMAGED": DAMAGED_EXCHANGE_BASE,
    }

    async with pg.session() as db:
        exchange_rows = (
            await db.scalars(
                select(InventoryMovement).where(
                    InventoryMovement.company_id == tenant.company_id,
                    InventoryMovement.reference_id == str(damage_visit_id),
                    InventoryMovement.reference_type.in_(
                        ["VISIT_EXCHANGE_OUT", "VISIT_RETURN_IN"]
                    ),
                )
            )
        ).all()
        assert {
            row.reference_type: (
                Decimal(row.quantity),
                row.source_stock_status,
                row.destination_stock_status,
            )
            for row in exchange_rows
        } == {
            "VISIT_EXCHANGE_OUT": (
                DAMAGED_EXCHANGE_BASE,
                "AVAILABLE",
                None,
            ),
            "VISIT_RETURN_IN": (
                DAMAGED_EXCHANGE_BASE,
                None,
                "DAMAGED",
            ),
        }

    await _assert_no_negative(pg, tenant)

    # End and close first; the only permitted unload is receiver-confirmed
    # custody receipt, which must preserve AVAILABLE and DAMAGED separately.
    async with pg.session() as db:
        ended = await end_work_session(db, field.context, field.driver)
        assert ended["message"] == "تم إنهاء الجلسة بنجاح."
    async with pg.session() as db:
        closed = await dispatch.update_route_status(
            route_id,
            UpdateRouteStatusRequest(status="closed"),
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )
        assert closed["message"] == "تم تحديث خط السير بنجاح"

    async with pg.session() as db:
        custody = await read_representative_custody(
            session_id, db, tenant.owner.access(db)
        )
        expected_by_status = {
            str(line["stock_status"]): Decimal(line["expected_quantity"])
            for line in custody["lines"]
        }
        assert expected_by_status == {
            "AVAILABLE": VEHICLE_AVAILABLE_AFTER_EXCHANGE,
            "DAMAGED": DAMAGED_EXCHANGE_BASE,
        }
        payload = CustodyConfirm(
            request_id=uuid4(),
            destination_location_id=tenant.location_id,
            receiver_confirms_handoff=True,
            items=[
                {
                    "line_key": line["line_key"],
                    "actual_quantity": line["expected_quantity"],
                }
                for line in custody["lines"]
            ],
            notes="Safety policy exact custody receipt",
        )
        receipt = await receive_representative_custody(
            session_id,
            payload,
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )
        assert receipt["status"] == "CUSTODY_RECEIVED"
        assert receipt["inventory_reconciled"] is True
        assert receipt["movement_count"] == 2

    final_truth = await _variant_truth(pg, tenant)
    assert final_truth["physical"] == FINAL_COMPANY_PHYSICAL
    assert final_truth["cost_quantity"] == FINAL_COMPANY_PHYSICAL
    assert final_truth["cost_value"] == FINAL_COST_VALUE
    assert final_truth["cost_event_count"] == 4

    final_detail = await _batch_detail_row(pg, tenant, batch_id)
    assert Decimal(final_detail["on_hand_quantity"]) == FINAL_COMPANY_PHYSICAL
    assert Decimal(final_detail["available_for_sale_quantity"]) == Decimal("116")
    assert Decimal(final_detail["quarantined_quantity"]) == STATUS_BUCKET
    assert Decimal(final_detail["blocked_quantity"]) == STATUS_BUCKET
    assert Decimal(final_detail["recalled_quantity"]) == STATUS_BUCKET
    assert Decimal(final_detail["damaged_quantity"]) == DAMAGED_EXCHANGE_BASE

    final_sources = _source_status_quantities(
        await _source_evidence(pg, tenant, batch_id)
    )
    assert final_sources[tenant.location_id] == {
        "AVAILABLE": Decimal("116"),
        "BLOCKED": STATUS_BUCKET,
        "DAMAGED": DAMAGED_EXCHANGE_BASE,
        "QUARANTINED": STATUS_BUCKET,
        "RECALLED": STATUS_BUCKET,
    }
    assert vehicle_location_id not in final_sources
    await _assert_no_negative(pg, tenant)


async def test_fractional_decimal_inventory_is_exact_and_field_fails_closed(pg):
    tenant = pg.tenants[0]

    # Existing PG16 fixture variant is fraction-capable:
    # scale=6, step=0.000001. Use real inbound/costing and real vehicle load.
    async with pg.session() as db:
        variant = await db.scalar(
            select(ProductVariant).where(
                ProductVariant.company_id == tenant.company_id,
                ProductVariant.id == tenant.variant_id,
            )
        )
        assert variant is not None
        assert int(variant.quantity_scale) == 6
        assert Decimal(variant.quantity_step) == Decimal("0.000001")

    request = pg.request(
        lot="SAFETY-FRAC-" + uuid4().hex[:12],
        quantity="2.500001",
        cost="0.123456",
    )
    async with pg.session() as db:
        assert await pg.post(db, request) == {"message": "INBOUND_POSTED"}
    batch_id = await _batch_id(pg, tenant, request.items[0].batch_number)

    initial = await _variant_truth(pg, tenant)
    assert initial["physical"] == Decimal("2.500001")
    assert initial["cost_quantity"] == Decimal("2.500001")
    assert initial["cost_value"] == Decimal("0.308640")

    vehicle_id, vehicle_location_id = await _create_vehicle_with_historical_attribution(
        pg, tenant
    )
    fractional_load = Decimal("1.250001")
    async with pg.session() as db:
        loaded = await mutate_vehicle_load(
            db,
            access=tenant.owner.access(db),
            actor_id=tenant.owner.driver_id,
            vehicle_id=vehicle_id,
            warehouse_id=tenant.location_id,
            direction="ADD",
            request_id=uuid4(),
            items=[
                {
                    "product_variant_id": tenant.variant_id,
                    "quantity": fractional_load,
                }
            ],
        )
        assert loaded["movement_count"] == 1

    exact = await _variant_truth(pg, tenant)
    assert exact["physical"] == Decimal("2.500001")
    assert exact["cost_quantity"] == Decimal("2.500001")
    assert exact["cost_value"] == Decimal("0.308640")
    sources = _source_status_quantities(
        await _source_evidence(pg, tenant, batch_id)
    )
    assert sources[tenant.location_id]["AVAILABLE"] == Decimal("1.250000")
    assert sources[vehicle_location_id]["AVAILABLE"] == Decimal("1.250001")

    # FIELD current mobile contract is integer-base only. Prove it rejects this
    # exact custody rather than silently truncating/rounding it.
    field = await _seed_mobile_uom_and_field(pg, tenant)
    zone_id, _shop_id = await _seed_commercial_master(pg, tenant, field)
    route_payload = DispatchRouteRequest(
        zone_id=zone_id,
        driver_id=field.driver.id,
        vehicle_id=vehicle_id,
        source_location_id=tenant.location_id,
        inventory_base={str(tenant.variant_id): fractional_load},
        expected_inventory_base={str(tenant.variant_id): fractional_load},
    )
    async with pg.session() as db:
        launched = await dispatch.dispatch_route(
            route_payload,
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )
        route_id = int(launched["route_id"])

    before_field = await _variant_truth(pg, tenant)
    async with pg.session() as db:
        with pytest.raises(HTTPException) as caught:
            await start_work_session(
                SessionStartRequest(), db, field.context, field.driver
            )
        assert caught.value.status_code == 409
        assert (
            caught.value.detail["code"]
            == "DRIVER_MOBILE_QUANTITY_PRECISION_UNSUPPORTED"
        )
        assert Decimal(caught.value.detail["context"]["quantity"]) == fractional_load
    assert await _variant_truth(pg, tenant) == before_field

    # Active route also owns this fractional custody; direct unload cannot be
    # used as an escape hatch around the FIELD precision failure.
    async with pg.session() as db:
        with pytest.raises(VehicleError) as blocked:
            await mutate_vehicle_load(
                db,
                access=tenant.owner.access(db),
                actor_id=tenant.owner.driver_id,
                vehicle_id=vehicle_id,
                warehouse_id=tenant.location_id,
                direction="UNLOAD",
                request_id=uuid4(),
                items=[
                    {
                        "product_variant_id": tenant.variant_id,
                        "quantity": Decimal("0.000001"),
                    }
                ],
            )
        assert blocked.value.code == "VEHICLE_LOAD_OWNED_BY_WORKFLOW"
        assert blocked.value.context["route_id"] == route_id
        assert blocked.value.context["work_session_id"] is None
        await db.rollback()
    assert await _variant_truth(pg, tenant) == before_field
    await _assert_no_negative(pg, tenant)
