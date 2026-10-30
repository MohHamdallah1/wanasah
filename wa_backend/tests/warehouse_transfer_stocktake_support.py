"""Canonical-command helpers and independent reconciliation; no stock fixture writes."""
from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.warehouse import ledger, live_stock
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import resolve_backoffice_authorization_subject
from domains.uom_authority import load_variant_uom_authorities
from models import (
    Driver, InventoryBalance, InventoryCostAllocation, InventoryCostEvent,
    InventoryCostLayer, InventoryCostPolicy, InventoryCostState,
    InventoryLock, InventoryMovement, InventoryMovementImpact, InventoryTransferHeader,
    Permission, ProductBatch, ProductUomConversion, Role, StocktakeCountAttempt,
    StocktakeSession, UOM, UserLocationAccess, role_permissions,
)
from scripts.profile_live_stock_explain import inventory_page_kwargs
from tests.canonical_actor_fixtures import seed_ordinary_backoffice_fixture

D = Decimal
PASSWORD = "WarehouseCountSynthetic123"
OWNER_PASSWORD = "NoLotSyntheticFixture123"


async def canonical_access(db, actor):
    subject = await resolve_backoffice_authorization_subject(db, actor.context)
    return BackofficeCapabilityAccess(db, subject)


async def command(pg, actor, operation, party=0):
    async with pg.session(party) as db:
        access = await canonical_access(db, actor)
        return await operation(db, access, actor.operational_driver)


async def prepare(pg):
    """Only catalog/UOM/identities/grants; no batch, balance or cost fixture data."""
    t = pg.tenants[0]
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as db:
        await db.execute(text("SELECT set_config('app.current_tenant',:c,true)"), {"c": str(t.company_id)})
        carton = await db.scalar(select(UOM).where(UOM.code == "CARTON"))
        if carton is None:
            carton = UOM(code="CARTON", name="Carton")
            db.add(carton)
            await db.flush()
        db.add(ProductUomConversion(
            company_id=t.company_id, product_variant_id=t.variant_id,
            from_uom_id=carton.id, to_uom_id=t.uom_id,
            numerator=D("8"), denominator=D("1"), quantity_scale=0))
        receiver = await seed_ordinary_backoffice_fixture(db, t.company_id, password=PASSWORD)
        recounter = await seed_ordinary_backoffice_fixture(db, t.company_id, password=PASSWORD)
        recounter_username = await db.scalar(select(Driver.username).where(
            Driver.company_id == t.company_id, Driver.id == recounter.driver_id))
        grants = [
            (t.ordinary, t.location_id, {"inventory.read", "ledger.read", "transfer.read", "transfer.send", "transfer.cancel"}),
            (t.ordinary, t.other_location_id, {"transfer.destination"}),
            (receiver, t.other_location_id, {"inventory.read", "ledger.read", "transfer.read", "transfer.receive",
                "transfer.reject", "stocktake.read", "stocktake.start", "stocktake.count",
                "stocktake.review", "stocktake.recount"}),
            (recounter, t.other_location_id, {"inventory.read", "stocktake.read", "stocktake.count",
                "stocktake.review", "stocktake.recount"}),
        ]
        from domains.authorization.capabilities import PERMISSIONS
        needed = set().union(*(codes for _, _, codes in grants))
        assert needed <= PERMISSIONS
        existing = set((await db.scalars(select(Permission.code).where(Permission.code.in_(needed)))).all())
        db.add_all([Permission(code=c) for c in sorted(needed - existing)])
        await db.flush()
        for actor, location_id, codes in grants:
            role = Role(company_id=t.company_id, name="Warehouse E2E " + uuid4().hex)
            db.add(role)
            await db.flush()
            ids = (await db.scalars(select(Permission.id).where(Permission.code.in_(codes)))).all()
            await db.execute(role_permissions.insert(), [
                {"company_id": t.company_id, "role_id": role.id, "permission_id": i} for i in ids])
            db.add(UserLocationAccess(company_id=t.company_id, driver_id=actor.driver_id,
                                      location_id=location_id, role_id=role.id))
        await db.commit()
        carton_id = int(carton.id)
        authority = (await load_variant_uom_authorities(
            db, company_id=t.company_id, variant_ids=[t.variant_id]))[t.variant_id]
        assert authority.to_base(D("15"), uom_id=carton_id, validate_step=True) == D("120")
    return NS(pg=pg, tenant=t, sender=t.ordinary, receiver=receiver, recounter=recounter,
              recounter_username=recounter_username, carton_id=carton_id, authority=authority,
              batches={}, session_id=None, purchases=None, supplier_history=None,
              successful_requests=set(), negative_requests=set())


async def history(db, company_id):
    purchases = (await db.execute(select(InventoryCostEvent.__table__).where(
        InventoryCostEvent.company_id == company_id,
        InventoryCostEvent.event_type == "PURCHASE_IN").order_by(InventoryCostEvent.id))).mappings().all()
    # Preserve every original receipt/supplier field, including timestamps.
    supplier = (await db.execute(text("""
        SELECT to_jsonb(e) FROM inventory_supplier_evidence e
        WHERE company_id=:c ORDER BY movement_id
    """), {"c": company_id})).scalars().all()
    return [dict(row) for row in purchases], supplier


async def checkpoint(case, expected, report):
    pg, t = case.pg, case.tenant
    async with pg.session() as db:
        access = await canonical_access(db, t.owner)
        batch_rows = (await db.scalars(select(ProductBatch).where(
            ProductBatch.company_id == t.company_id, ProductBatch.product_variant_id == t.variant_id))).all()
        case.batches.update({b.batch_number: int(b.id) for b in batch_rows})
        assert set(case.batches) == ({"E2E-FIRST"} if expected.cost_events == 1 else {"E2E-FIRST", "E2E-SECOND"})
        assert all(b.disposition == "RELEASED" and b.is_active for b in batch_rows)
        first, second = case.batches["E2E-FIRST"], case.batches.get("E2E-SECOND")
        balances = (await db.scalars(select(InventoryBalance).where(
            InventoryBalance.company_id == t.company_id))).all()
        headers = (await db.scalars(select(InventoryTransferHeader).where(
            InventoryTransferHeader.company_id == t.company_id))).all()
        transit_ids = {int(h.transit_location_id) for h in headers}
        actual, reserved = defaultdict(lambda: D("0")), defaultdict(lambda: D("0"))
        for b in balances:
            assert b.product_variant_id == t.variant_id and b.stock_status == "AVAILABLE"
            actual[(b.location_id, b.batch_id)] += D(b.on_hand_quantity)
            reserved[(b.location_id, b.batch_id)] += D(b.reserved_quantity)
        wanted = {
            (t.location_id, first): expected.a_first,
            (t.other_location_id, first): expected.b_first,
        }
        if second is not None:
            wanted[(t.location_id, second)] = expected.a_second
        assert sum((v for (loc, batch), v in actual.items() if loc in transit_ids), D("0")) == expected.transit_first
        assert all(batch == first for (loc, batch), q in actual.items() if loc in transit_ids and q)
        assert {k: v for k, v in actual.items() if v and k[0] not in transit_ids} == {k: v for k, v in wanted.items() if v}
        assert {k: v for k, v in reserved.items() if v} == (
            {(t.location_id, first): expected.reserved_a} if expected.reserved_a else {})
        assert sum(actual.values(), D("0")) == expected.cost_quantity
        movements = (await db.scalars(select(InventoryMovement).where(
            InventoryMovement.company_id == t.company_id).order_by(InventoryMovement.id))).all()
        assert len(movements) == expected.movements
        assert len({m.idempotency_key for m in movements}) == expected.movements

        # Independently reconstruct physical and reservation ledgers from zero.
        physical, held = defaultdict(lambda: D("0")), defaultdict(lambda: D("0"))
        for m in movements:
            q = D(m.quantity)
            source, dest = (m.source_location_id, m.batch_id), (m.destination_location_id, m.batch_id)
            if m.movement_kind == "RESERVATION":
                held[source] += q if m.reservation_action == "RESERVE" else -q
            else:
                assert m.movement_kind == "PHYSICAL"
                if m.source_location_id is not None:
                    physical[source] -= q
                if m.destination_location_id is not None:
                    physical[dest] += q
        assert {k: v for k, v in physical.items() if v} == {k: v for k, v in actual.items() if v}
        assert {k: v for k, v in held.items() if v} == {k: v for k, v in reserved.items() if v}
        impacts = (await db.execute(select(InventoryMovementImpact, InventoryBalance)
            .join(InventoryBalance, InventoryBalance.id == InventoryMovementImpact.inventory_balance_id)
            .where(InventoryMovementImpact.company_id == t.company_id)
            .order_by(InventoryMovementImpact.movement_id, InventoryMovementImpact.id))).all()
        replayed = defaultdict(lambda: (D("0"), D("0")))
        impact_by_movement = defaultdict(list)
        for impact, b in impacts:
            key = (b.location_id, b.batch_id)
            assert replayed[key] == (D(impact.on_hand_before), D(impact.reserved_before))
            replayed[key] = (D(impact.on_hand_after), D(impact.reserved_after))
            impact_by_movement[impact.movement_id].append(impact)
        assert set(impact_by_movement) == {m.id for m in movements}
        assert all(replayed[k] == (v, reserved[k]) for k, v in actual.items())
        for m in movements:
            entries = impact_by_movement[m.id]
            physical_delta = sum((D(i.on_hand_after)-D(i.on_hand_before) for i in entries), D("0"))
            expected_delta = (D(m.quantity) if m.source_location_id is None else
                              -D(m.quantity) if m.destination_location_id is None else D("0"))
            if m.movement_kind == "RESERVATION":
                expected_delta = D("0")
            assert physical_delta == expected_delta
        state = await db.scalar(select(InventoryCostState).where(
            InventoryCostState.company_id == t.company_id, InventoryCostState.product_variant_id == t.variant_id))
        assert (D(state.quantity), D(state.inventory_value), D(state.average_unit_cost)) == (
            expected.cost_quantity, expected.inventory_value, expected.average_cost)
        policy = await db.scalar(select(InventoryCostPolicy).where(InventoryCostPolicy.company_id == t.company_id))
        assert policy.method == pg.method and policy.is_active and policy.locked_at and policy.selected_at
        events = (await db.scalars(select(InventoryCostEvent).where(
            InventoryCostEvent.company_id == t.company_id).order_by(InventoryCostEvent.id))).all()
        assert len(events) == expected.cost_events
        purchase_rows, supplier_rows = await history(db, t.company_id)
        if expected.stage == "inbound_first":
            case.purchases, case.supplier_history = purchase_rows, supplier_rows
        elif expected.stage == "inbound_second":
            assert purchase_rows[:1] == case.purchases
            assert supplier_rows[:1] == case.supplier_history
            case.purchases, case.supplier_history = purchase_rows, supplier_rows
        else:
            assert purchase_rows == case.purchases
            assert supplier_rows == case.supplier_history
        assert [(D(e.quantity), D(e.input_quantity), D(e.input_unit_cost), D(e.total_cost), e.input_uom_id)
                for e in events if e.event_type == "PURCHASE_IN"] == (
            [(D("800"), D("100"), D("16"), D("1600"), case.carton_id)]
            if expected.cost_events == 1 else
            [(D("800"), D("100"), D("16"), D("1600"), case.carton_id),
             (D("400"), D("50"), D("40"), D("2000"), case.carton_id)])
        outbound = [e for e in events if e.event_type == "OUTBOUND"]
        if expected.stage == "stocktake_posted":
            assert len(outbound) == 1
            e = outbound[0]
            assert (D(e.quantity), D(e.total_cost), D(e.quantity_before), D(e.quantity_after),
                    D(e.value_before), D(e.value_after)) == (
                D("16"), D("32") if pg.method == "FIFO" else D("48"),
                D("1200"), D("1184"), D("3600"), expected.inventory_value)
        else:
            assert not outbound
        cost_movement_ids = {e.inventory_movement_id for e in events}
        assert not any(m.id in cost_movement_ids for m in movements
                       if m.transfer_header_id is not None or m.movement_kind == "RESERVATION")
        layers = (await db.scalars(select(InventoryCostLayer).where(
            InventoryCostLayer.company_id == t.company_id).order_by(InventoryCostLayer.id))).all()
        allocations = (await db.scalars(select(InventoryCostAllocation).where(
            InventoryCostAllocation.company_id == t.company_id))).all()
        if pg.method == "FIFO":
            pairs = [(D(l.remaining_quantity), D(l.remaining_value)) for l in layers]
            assert pairs == ([(D("800"), D("1600"))] if expected.cost_events == 1 else
                [(D("784"), D("1568")), (D("400"), D("2000"))] if expected.stage == "stocktake_posted" else
                [(D("800"), D("1600")), (D("400"), D("2000"))])
            assert sum((D(l.remaining_value) for l in layers), D("0")) == expected.inventory_value
            assert [(D(a.quantity), D(a.amount), a.allocation_type) for a in allocations] == (
                [(D("16"), D("32"), "CONSUME")] if expected.stage == "stocktake_posted" else [])
        else:
            assert layers == [] and allocations == []
        assert await db.scalar(select(func.count()).select_from(StocktakeCountAttempt).where(
            StocktakeCountAttempt.company_id == t.company_id)) == expected.attempts
        assert await db.scalar(select(func.count()).select_from(InventoryLock).where(
            InventoryLock.company_id == t.company_id, InventoryLock.released_at.is_(None))) == expected.locks
        if expected.stocktake_status:
            assert (await db.get(StocktakeSession, case.session_id)).status == expected.stocktake_status

        for location, total, reserved_total in (
            (t.location_id, expected.a_first + expected.a_second, expected.reserved_a),
            (t.other_location_id, expected.b_first, D("0")),
        ):
            page = await live_stock.get_warehouse_inventory(**inventory_page_kwargs(
                db=db, access=access, location_id=location, limit=50, cursor=None, search=None, only_alerts=False))
            assert len(page["items"]) == 1
            item = page["items"][0]
            assert item["id"] == t.variant_id
            assert (D(item["on_hand_quantity"]), D(item["reserved_quantity"]),
                    D(item["available_for_sale_quantity"])) == (total, reserved_total, total-reserved_total)
            assert item["currency_code"] == "JOD" and item["display_uom_code"] == "CARTON"
            assert D(item["display_factor_to_base"]) == 8
            if total:
                assert D(item["average_cost_display"]) == expected.average_cost * 8
                assert D(item["last_purchase_cost"]) == (16 if expected.cost_events == 1 else 40)
            else:
                assert item["average_cost_display"] is None
                assert item["last_purchase_cost"] is None
            detail = await live_stock.get_warehouse_inventory_batches(t.variant_id, location, None, 100, db, access)
            detail_actual = {b["batch_id"]: D(b["on_hand_quantity"]) for b in detail["batches"] if D(b["on_hand_quantity"])}
            detail_wanted = {batch: qty for (loc, batch), qty in wanted.items() if loc == location and qty}
            assert detail_actual == detail_wanted
            assert sum((D(b["reserved_quantity"]) for b in detail["batches"]), D("0")) == reserved_total
            for b in detail["batches"]:
                assert D(b["latest_purchase_cost"]) == (16 if b["batch_id"] == first else 40)
                assert b["latest_purchase_uom_code"] == "CARTON" and b["purchase_event_count"] == 1
            rows = await ledger.get_warehouse_ledger_cursor(location, None, 50, None, None, None, db, access)
            relevant = [m for m in movements if location in (m.source_location_id, m.destination_location_id)]
            assert {r["id"] for r in rows["items"]} == {m.id for m in relevant}
            assert len(rows["items"]) == len(relevant) and not rows["has_more"]
            assert sum((D(r["quantity"]) for r in rows["items"] if r["movement_kind"] == "PHYSICAL"), D("0")) == total
            assert sum((D(r["quantity"]) for r in rows["items"] if r["movement_kind"] == "RESERVATION"), D("0")) == -reserved_total
    from dataclasses import asdict
    proof = {"method": pg.method, **asdict(expected), "batch_ids": case.batches,
             "transit_ids": sorted(transit_ids), "ledger_impacts": len(impacts),
             "valuation": str(state.inventory_value)}
    report["stages"].append(proof)
    print("WAREHOUSE_JOURNEY_STAGE " + json.dumps(proof, default=str), flush=True)
    save_report(report, pg.method)


def save_report(report, method):
    root = Path("/tmp/warehouse-transfer-stocktake-evidence")
    root.mkdir(parents=True, exist_ok=True)
    (root / (method.lower() + ".json")).write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8")
