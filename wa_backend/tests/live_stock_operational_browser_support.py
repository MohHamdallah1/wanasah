"""Operational browser setup: reuse #660 sessions/PG fixture; production stock commands only."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from api import catalog
from api.inventory_stock_policy import MinimumStockUpdateRequest, update_minimum_stock
from api.warehouse import transfers
from domains.live_stock_projection.service import rebuild_live_stock_company
from models import (
    Company, InventoryBalance, InventoryCostEvent, InventoryCostState, InventoryLocation,
    Permission, Product, ProductBatch, ProductLocation, ProductUomConversion, ProductVariant,
    Role, UOM, UserLocationAccess, role_permissions, utc_now,
)
from schemas import InventoryStatusChangeRequest
from services import apply_inventory_movement
from tests.canonical_actor_fixtures import load_company_owner_fixture
from tests.live_stock_real_browser_support import _engines, _runtime_session
from tests.test_inbound_no_lot_frozen_postgres import pg

STATE = Path(os.environ.get("WANASAH_OPERATIONAL_BROWSER_STATE", "/tmp/live-stock-operational-state.json"))
D = Decimal
# Independent input/expected truth; no API response is used to derive these.
EXPECTED = {"onHand": "1000", "value": "2200", "reserved": "16", "available": "976",
            "blocked": "8", "afterReserved": "24", "afterAvailable": "968",
            "purchaseCarton": "24", "averageCarton": "17.600", "factor": "8",
            "stockTotal": 109, "alerts": 1, "pagingRows": 105,
            "batchOne": "800", "batchTwo": "200", "movableOne": "784", "afterMovableOne": "776"}


async def reserve(db, a, batch, qty, key):
    await apply_inventory_movement(db, company_id=a.company_id, performed_by=a.owner.driver_id,
        product_variant_id=a.variant_id, batch_id=batch, quantity=D(qty),
        movement_kind="RESERVATION", reservation_action="RESERVE",
        source_location_id=a.location_id, destination_location_id=a.location_id,
        source_stock_status="AVAILABLE", destination_stock_status="AVAILABLE",
        reference_type="OPERATIONAL_BROWSER_HOLD", reference_id=key, idempotency_key=key)
    await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_prepare_operational_browser(pg):
    assert os.environ.get("WANASAH_REAL_BROWSER_GATE") == "1"
    assert not STATE.exists(), "One disposable operational fixture only"
    a, b = pg.tenants
    ids, names, families = [], [], []
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as db:
        await db.execute(text("SELECT set_config('app.current_tenant',:c,true)"), {"c": str(a.company_id)})
        company = await db.get(Company, a.company_id)
        company.timezone = "Pacific/Kiritimati"
        variant = await db.get(ProductVariant, a.variant_id)
        variant.name, variant.sku = "A Operational Multi Batch", "OP-MULTI"
        wa, wb = await db.get(InventoryLocation, a.location_id), await db.get(InventoryLocation, a.other_location_id)
        wa.name, wb.name = "Zulu Authorized Warehouse", "A Second Warehouse"
        db.add_all([InventoryLocation(company_id=a.company_id, name=f"Hidden Depot {n:03d}",
                    code=f"OP-HIDDEN-{n:03d}", location_type="WAREHOUSE") for n in range(209)])
        carton = await db.scalar(select(UOM).where(UOM.code == "CARTON"))
        if carton is None:
            carton = UOM(code="CARTON", name="Carton")
            db.add(carton)
            await db.flush()
        carton_id = int(carton.id)
        db.add(ProductUomConversion(company_id=a.company_id, product_variant_id=a.variant_id,
            from_uom_id=carton_id, to_uom_id=a.uom_id, numerator=D("8"), denominator=D("1"), quantity_scale=0))
        role = Role(company_id=a.company_id, name="Operational inventory-only reader")
        db.add(role)
        await db.flush()
        permission = await db.scalar(select(Permission.id).where(Permission.code == "inventory.read"))
        await db.execute(role_permissions.insert().values(company_id=a.company_id, role_id=role.id, permission_id=permission))
        db.add(UserLocationAccess(company_id=a.company_id, driver_id=a.ordinary.driver_id,
                                  location_id=a.location_id, role_id=role.id))
        for n in range(1, 56):
            family = Product(company_id=a.company_id, code=f"OP-F-{n:03d}", name=f"Journey Family {n:03d}")
            db.add(family)
            await db.flush()
            families.append(family.id)
        original_product = variant.product_id
        for label in ("RETIRING", "SALES_HOLD", "RECALL"):
            item = ProductVariant(company_id=a.company_id, product_id=original_product, base_uom_id=a.uom_id,
                name=f"B Policy {label}", sku=f"OP-{label}", lifecycle_status="ACTIVE", published_at=utc_now(),
                lot_control_mode="OPTIONAL", expiry_control_mode="OPTIONAL", quantity_scale=6, quantity_step=D("0.000001"))
            db.add(item)
            await db.flush()
            ids.append(item.id)
            names.append(item.name)
        paging = []
        for n in range(1, 106):
            item = ProductVariant(company_id=a.company_id, product_id=families[50] if n == 105 else families[0],
                base_uom_id=a.uom_id, name=f"Paging Item {n:03d}", sku=f"OP-PAGE-{n:03d}",
                lifecycle_status="ACTIVE", published_at=utc_now(), lot_control_mode="OPTIONAL",
                expiry_control_mode="OPTIONAL", quantity_scale=6, quantity_step=D("0.000001"))
            db.add(item)
            await db.flush()
            paging.append(item.id)
        for vid in ids + paging:
            db.add(ProductLocation(company_id=a.company_id, product_variant_id=vid, location_id=a.location_id,
                created_by=a.owner.driver_id, operational_flags={"inbound_enabled": True, "outbound_enabled": True}))
        db.add(ProductLocation(company_id=a.company_id, product_variant_id=paging[0], location_id=a.other_location_id,
            created_by=a.owner.driver_id, operational_flags={"inbound_enabled": True, "outbound_enabled": True}))
        await db.flush()
        await rebuild_live_stock_company(db, company_id=a.company_id)
        await db.commit()

    # Two real supplier receipts with exact purchase UOM/cost, preserving each history.
    for qty, cost, lot in (("100", "16", "OP-FIRST"), ("25", "24", "OP-SECOND")):
        payload = pg.request(quantity=qty, cost=cost, lot=lot, expiry=date(2099, 1, 1))
        payload.items[0].uom_id = carton_id
        async with pg.session() as db:
            await pg.post(db, payload)
    async with pg.session() as db:
        base = pg.request(quantity="10", cost="2", lot="OP-POLICY", expiry=date(2099, 1, 1))
        await pg.post(db, base.model_copy(update={"items": [
            base.items[0].model_copy(update={"product_variant_id": vid}) for vid in ids]}))
    async with pg.session() as db:
        base = pg.request(quantity="1", cost="1", lot="OP-PAGING", expiry=date(2099, 1, 1))
        await pg.post(db, base.model_copy(update={"items": [
            base.items[0].model_copy(update={"product_variant_id": vid}) for vid in paging]}))
    async with pg.session() as db:
        base = pg.request(quantity="2", cost="1", lot="OP-OTHER", expiry=date(2099, 1, 1))
        await pg.post(db, base.model_copy(update={"location_id": a.other_location_id,
            "items": [base.items[0].model_copy(update={"product_variant_id": paging[0]})]}))
    async with pg.session(1) as db:
        await pg.post(db, pg.request(party=1, quantity="7", cost="9.75", lot="OP-FOREIGN", expiry=date(2099, 1, 1)), party=1)

    async with pg.session() as db:
        batches = {number: bid for number, bid in (await db.execute(
            select(ProductBatch.batch_number, ProductBatch.id).where(
                ProductBatch.company_id == a.company_id, ProductBatch.product_variant_id == a.variant_id))).all()}
        await reserve(db, a, batches["OP-FIRST"], "16", "OP-INITIAL-RESERVE")
    async with pg.session() as db:
        await transfers.change_inventory_status(InventoryStatusChangeRequest(request_id=uuid4(),
            location_id=a.location_id, product_variant_id=a.variant_id, batch_id=batches["OP-SECOND"],
            uom_id=a.uom_id, source_status="AVAILABLE", destination_status="BLOCKED",
            quantity=D("8"), reason="Operational browser source status"), db, a.owner.access(db), a.owner.operational_driver)
    for vid in [a.variant_id] + ids:
        async with pg.session() as db:
            await update_minimum_stock(vid, MinimumStockUpdateRequest(request_id=uuid4(),
                location_id=a.location_id, uom_id=a.uom_id, minimum_quantity=D("1000") if vid == a.variant_id else D("10"),
                expected_minimum_quantity=D("0")), db, a.owner.access(db), a.owner.operational_driver)
    for vid, operation in zip(ids, (catalog.retire_variant, catalog.place_variant_sales_hold, catalog.recall_variant)):
        async with pg.session() as db:
            version = await db.scalar(select(ProductVariant.version).where(ProductVariant.id == vid))
            await operation(vid, catalog.LifecycleCommand(request_id=uuid4(), expected_version=version,
                reason="Operational browser policy acceptance"), db, a.owner.access(db), a.owner.operational_driver)
    async with pg.session() as db:
        state = await db.scalar(select(InventoryCostState).where(InventoryCostState.product_variant_id == a.variant_id))
        assert (D(state.quantity), D(state.inventory_value), D(state.average_unit_cost)) == (D("1000"), D("2200"), D("2.2"))
        purchases = list((await db.scalars(select(InventoryCostEvent).where(
            InventoryCostEvent.product_variant_id == a.variant_id).order_by(InventoryCostEvent.id))).all())
        assert len(purchases) == 2 and [D(e.total_cost) for e in purchases] == [D("1600"), D("600")]
        stamp = purchases[-1].created_at.replace(tzinfo=timezone.utc)
        expected_date = stamp.astimezone(ZoneInfo("Pacific/Kiritimati")).date().isoformat()
        browser_date = stamp.astimezone(ZoneInfo("Pacific/Honolulu")).date().isoformat()
        assert expected_date != browser_date
        assert await db.scalar(select(func.count()).select_from(InventoryLocation).where(
            InventoryLocation.company_id == a.company_id, InventoryLocation.location_type == "WAREHOUSE")) == 211
        credentials = {}
        for key, tenant, actor, password in (
            ("reader", a, a.ordinary, "SyntheticFixture123"),
            ("owner", a, a.owner, "NoLotSyntheticFixture123")):
            from domains.identity.models import CompanyPrincipal
            credentials[key] = {"code": await db.scalar(select(Company.company_code).where(Company.id == tenant.company_id)),
                "username": await db.scalar(select(CompanyPrincipal.username).where(CompanyPrincipal.id == actor.context.principal_id)),
                "password": password}
        # Foreign credential reads use the admin fixture role under its proper tenant.
    async with AsyncSession(pg.admin_engine) as db:
        await db.execute(text("SELECT set_config('app.current_tenant',:c,true)"), {"c": str(b.company_id)})
        from domains.identity.models import CompanyPrincipal
        credentials["foreign"] = {"code": await db.scalar(select(Company.company_code).where(Company.id == b.company_id)),
            "username": await db.scalar(select(CompanyPrincipal.username).where(CompanyPrincipal.id == b.owner.context.principal_id)),
            "password": "NoLotSyntheticFixture123"}
    state = {"companyId": a.company_id, "warehouse": a.location_id, "otherWarehouse": a.other_location_id,
             "foreignWarehouse": b.location_id, "readerDriver": a.ordinary.driver_id, "mainId": a.variant_id,
             "mainName": "A Operational Multi Batch", "policyNames": names, "policyIds": ids,
             "firstBatch": batches["OP-FIRST"], "secondBatch": batches["OP-SECOND"],
             "pagingIds": paging, "family51": families[50], "expected": EXPECTED,
             "date": expected_date, "browserDate": browser_date, "credentials": credentials}
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print("OPERATIONAL_SEED PASS: canonical receipts, stock status, reservation and four minimum policies", flush=True)


async def command(action):
    state = json.loads(STATE.read_text())
    runtime, admin = await _engines()
    try:
        async with _runtime_session(runtime, state["companyId"]) as db:
            owner = await load_company_owner_fixture(db, state["companyId"])
            a = NS(company_id=state["companyId"], variant_id=state["mainId"],
                   location_id=state["warehouse"], owner=owner)
            if action == "reserve":
                await reserve(db, a, state["firstBatch"], "8", "OP-REFRESH-RESERVE")
                q = await db.scalar(select(InventoryBalance.reserved_quantity).where(
                    InventoryBalance.company_id == a.company_id, InventoryBalance.location_id == a.location_id,
                    InventoryBalance.batch_id == state["firstBatch"], InventoryBalance.stock_status == "AVAILABLE"))
                assert D(q) == D("24")
                cost = await db.scalar(select(InventoryCostState).where(InventoryCostState.product_variant_id == a.variant_id))
                assert (D(cost.quantity), D(cost.inventory_value)) == (D("1000"), D("2200"))
            elif action == "race-threshold":
                uom_id = await db.scalar(select(ProductVariant.base_uom_id).where(
                    ProductVariant.company_id == a.company_id,
                    ProductVariant.id == a.variant_id,
                ))
                configured = await update_minimum_stock(
                    a.variant_id,
                    MinimumStockUpdateRequest(
                        request_id=uuid4(),
                        location_id=a.location_id,
                        uom_id=int(uom_id),
                        minimum_quantity=D("950"),
                        expected_minimum_quantity=D("1000"),
                    ),
                    db,
                    a.owner.access(db),
                    a.owner.operational_driver,
                )
                assert D(configured["minimum_quantity"]) == D("950")
            elif action == "revoke":
                result = await db.execute(delete(UserLocationAccess).where(
                    UserLocationAccess.company_id == a.company_id,
                    UserLocationAccess.driver_id == state["readerDriver"], UserLocationAccess.location_id == a.location_id))
                assert result.rowcount == 1
                await db.commit()
            else:
                raise ValueError(action)
        print("OPERATIONAL_COMMAND PASS " + action, flush=True)
    finally:
        await runtime.dispose()
        await admin.dispose()


if __name__ == "__main__":
    import sys
    asyncio.run(command(sys.argv[1]))
