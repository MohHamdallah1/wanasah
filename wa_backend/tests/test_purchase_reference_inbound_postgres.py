"""Exact-HEAD PostgreSQL acceptance through the real Supplier Inbound adapter."""
import asyncio
from decimal import Decimal
import os
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.warehouse import inbound
from api.warehouse._shared import _stable_request_hash
from domains.inventory_costing.purchase_reference.models import PurchaseCostReference, PurchaseReferenceChange
from domains.inventory_costing.purchase_reference.public import (
    READ, PurchaseReferenceError, read_reference, write_manual_reference,
)
from domains.inventory_costing.service import set_cost_policy
from domains.suppliers.models import Supplier
from models import UserLocationAccess
from schemas import InboundOptionsRequest, UpgradedInboundRequest
from services import begin_idempotent_operation, complete_idempotent_operation
from tests.purchase_reference_pg_support import pg  # noqa: F401
from tests.test_purchase_cost_reference_postgres import command

pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_PURCHASE_REFERENCE_DB_GATE") != "1",
                       reason="Disposable GitHub PostgreSQL gate only"),
    pytest.mark.asyncio,
]


async def prepare(pg, t, method="FIFO"):
    async with pg.session(t) as db:
        supplier = Supplier(company_id=t.company_id, name="Atomic receipt supplier",
                            created_by=t.owner.driver_id, updated_by=t.owner.driver_id)
        db.add(supplier)
        await db.flush()
        supplier_id = supplier.id
        await set_cost_policy(db, company_id=t.company_id, actor_id=t.owner.driver_id,
                              method=method, expected_version=0)
        await db.commit()
        return supplier_id


def receipt(t, supplier, **changes):
    body = dict(request_id=uuid4(), supplier_id=supplier, location_id=t.location_id,
                items=[dict(product_variant_id=t.variant_id, quantity="1",
                            uom_id=t.carton_id, unit_cost="24")])
    body.update(changes)
    return UpgradedInboundRequest(**body)


async def post(pg, t, payload, actor=None):
    actor = actor or t.owner
    async with pg.session(t) as db:
        return await inbound.warehouse_inbound(
            payload, db=db, access=actor.access(db),
            legacy_actor=SimpleNamespace(id=actor.driver_id),
        )


async def reference(pg, t):
    async with pg.session(t) as db:
        return (await read_reference(db, access=t.owner.access(db),
                                     product_variant_id=t.variant_id))["reference"]


TABLES = (
    "operation_idempotency", "inventory_movements", "inventory_supplier_evidence",
    "inventory_cost_events", "inventory_cost_layers", "inventory_cost_allocations",
    "inventory_cost_states", "inventory_cost_policies", "inventory_balances",
    "product_batches", "product_locations", "domain_audit_events", "transactional_outbox",
    "purchase_cost_references", "purchase_cost_reference_changes", "purchase_cost_reference_commands",
    "price_books", "price_book_entries", "price_publications",
)


async def snapshot(pg, t, tables=TABLES):
    async with pg.session(t) as db:
        return {table: list((await db.scalars(text(
            f"SELECT to_jsonb(t)::text FROM {table} t WHERE company_id=:c ORDER BY to_jsonb(t)::text"
        ), {"c": t.company_id})).all()) for table in tables}


@pytest.mark.parametrize("method", ["FIFO", "MOVING_AVERAGE"])
async def test_atomic_receipt_keeps_normal_accounting_and_native_cost(pg, method):
    t = pg.a
    supplier = await prepare(pg, t, method)
    first = receipt(t, supplier)
    assert await post(pg, t, first) == {"message": "INBOUND_POSTED"}
    ref = await reference(pg, t)
    assert (ref["amount"], ref["purchase_uom_id"], ref["currency_code"], ref["revision"]) == (
        "24.000000", t.carton_id, "JOD", 1)
    assert ref["source"] == "SUPPLIER_INBOUND"
    assert (ref["factor_numerator"], ref["factor_denominator"]) == ("12", "1")
    before = await snapshot(pg, t)
    second = receipt(t, supplier, items=[
        dict(product_variant_id=t.variant_id, quantity="2", uom_id=t.each_id, unit_cost="3")
    ])
    await post(pg, t, second)
    after = await snapshot(pg, t)
    assert len(after["inventory_cost_events"]) == 2
    assert set(before["inventory_cost_events"]) <= set(after["inventory_cost_events"])
    assert set(before["inventory_movements"]) <= set(after["inventory_movements"])
    assert set(before["inventory_supplier_evidence"]) <= set(after["inventory_supplier_evidence"])
    assert set(before["inventory_cost_layers"]) <= set(after["inventory_cost_layers"])
    assert after["inventory_cost_allocations"] == before["inventory_cost_allocations"] == []
    for table in ("price_books", "price_book_entries", "price_publications"):
        assert after[table] == before[table]
    async with pg.session(t) as db:
        state = (await db.execute(text(
            "SELECT quantity,inventory_value,average_unit_cost FROM inventory_cost_states WHERE company_id=:c"
        ), {"c": t.company_id})).one()
        assert state.quantity == Decimal("14") and state.inventory_value == Decimal("30")
        assert state.average_unit_cost == Decimal("2.142857")
        audit = (await db.scalars(select(PurchaseReferenceChange).where(
            PurchaseReferenceChange.company_id == t.company_id
        ).order_by(PurchaseReferenceChange.revision))).all()
        assert len(audit) == 2 and audit[1].before_snapshot["amount"] == "24.000000"
        row = await db.scalar(select(PurchaseCostReference).where(PurchaseCostReference.company_id == t.company_id))
        event = (await db.execute(text(
            "SELECT e.company_id,e.product_variant_id,e.input_uom_id,e.input_unit_cost,s.request_id "
            "FROM inventory_cost_events e JOIN inventory_supplier_evidence s "
            "ON s.company_id=e.company_id AND s.movement_id=e.inventory_movement_id WHERE e.id=:id"
        ), {"id": row.source_cost_event_id})).one()
        assert tuple(event) == (t.company_id, t.variant_id, t.each_id, Decimal("3"), second.request_id)
        assert len(after["inventory_cost_layers"]) == (2 if method == "FIFO" else 0)


async def test_forced_failure_rolls_back_receipt_reference_and_audit(pg, monkeypatch):
    t = pg.a
    supplier = await prepare(pg, t)
    request = receipt(t, supplier)
    before = await snapshot(pg, t)
    original = inbound.write_receipt_references
    reached = False

    async def fail_after_reference(*args, **kwargs):
        nonlocal reached
        result = await original(*args, **kwargs)
        assert result["references"][0]["revision"] == 1
        reached = True
        raise RuntimeError("forced failure after receipt and reference writes")

    with monkeypatch.context() as patch:
        patch.setattr(inbound, "write_receipt_references", fail_after_reference)
        with pytest.raises(HTTPException) as error:
            await post(pg, t, request)
        assert error.value.status_code == 500 and reached
    assert await snapshot(pg, t) == before
    await post(pg, t, request)
    assert (await reference(pg, t))["revision"] == 1


async def test_lost_response_and_replay_after_newer_manual_never_rewrite(pg):
    t = pg.a
    supplier = await prepare(pg, t)
    request = receipt(t, supplier)
    await post(pg, t, request)  # response deliberately discarded
    committed = await snapshot(pg, t)
    assert await post(pg, t, request) == {"message": "INBOUND_POSTED"}
    assert await snapshot(pg, t) == committed
    await pg.write(t, command(t, revision=1, amount="72"))
    newer = await snapshot(pg, t)
    assert await post(pg, t, request) == {"message": "INBOUND_POSTED"}
    assert await snapshot(pg, t) == newer
    assert (await reference(pg, t))["amount"] == "72.000000"
    changed = request.model_copy(update={"items": [
        request.items[0].model_copy(update={"unit_cost": Decimal("25")})
    ]})
    with pytest.raises(HTTPException) as error:
        await post(pg, t, changed)
    assert error.value.status_code == 409
    assert await snapshot(pg, t) == newer


async def test_mixed_native_uoms_require_explicit_order_independent_selection(pg):
    t = pg.a
    supplier = await prepare(pg, t)
    items = [
        dict(product_variant_id=t.variant_id, quantity="2", uom_id=t.each_id, unit_cost="3"),
        dict(product_variant_id=t.variant_id, quantity="1", uom_id=t.carton_id, unit_cost="24"),
    ]
    request = receipt(t, supplier, items=items)
    before = await snapshot(pg, t)
    with pytest.raises(HTTPException) as error:
        await post(pg, t, request)
    assert error.value.detail["code"] == "INBOUND_REFERENCE_SELECTION_REQUIRED"
    assert await snapshot(pg, t) == before
    selected = receipt(t, supplier, request_id=request.request_id, items=list(reversed(items)),
                       purchase_reference_selections=[
                           dict(product_variant_id=t.variant_id, uom_id=t.each_id, unit_cost="3")
                       ])
    await post(pg, t, selected)
    ref = await reference(pg, t)
    assert ref["amount"] == "3.000000" and ref["purchase_uom_id"] == t.each_id
    assert ref["provenance"]["selection"] == "EXPLICIT"
    committed = await snapshot(pg, t)
    reversed_request = selected.model_copy(update={"items": list(reversed(selected.items))})
    await post(pg, t, reversed_request)
    assert await snapshot(pg, t) == committed
    changed = receipt(t, supplier, request_id=selected.request_id, items=items,
                      purchase_reference_selections=[
                          dict(product_variant_id=t.variant_id, uom_id=t.carton_id, unit_cost="24")
                      ])
    with pytest.raises(HTTPException) as error:
        await post(pg, t, changed)
    assert error.value.status_code == 409
    assert await snapshot(pg, t) == committed


async def test_two_different_costs_same_uom_select_value_without_lot_order(pg):
    t = pg.a
    supplier = await prepare(pg, t)
    async with AsyncSession(pg.admin) as db:
        await db.execute(text("UPDATE product_variants SET lot_control_mode='REQUIRED' WHERE company_id=:c"),
                         {"c": t.company_id})
        await db.commit()
    request = receipt(t, supplier, items=[
        dict(product_variant_id=t.variant_id, quantity="1", uom_id=t.each_id, unit_cost="9", batch_number="A"),
        dict(product_variant_id=t.variant_id, quantity="1", uom_id=t.each_id, unit_cost="2", batch_number="Z"),
    ], purchase_reference_selections=[
        dict(product_variant_id=t.variant_id, uom_id=t.each_id, unit_cost="9")
    ])
    await post(pg, t, request)
    assert (await reference(pg, t))["amount"] == "9.000000"


@pytest.mark.parametrize("supplier_present", [True, False])
async def test_old_completed_request_hash_replays_before_new_reference_guards(pg, monkeypatch, supplier_present):
    t = pg.a
    supplier = await prepare(pg, t)
    request = receipt(t, supplier if supplier_present else None)
    # Exact old transport dump, including pre-Supplier exclusion where applicable.
    old_body = request.model_dump(mode="json", exclude={"purchase_reference_selections"})
    old = SimpleNamespace(model_dump=lambda **kw: {
        key: value for key, value in old_body.items() if key not in kw["exclude"]
    })
    old_hash = _stable_request_hash(old, exclude_fields={"supplier_id"} if not supplier_present else None)
    async with pg.session(t) as db:
        operation, replay = await begin_idempotent_operation(
            db, company_id=t.company_id, actor_id=t.owner.driver_id, operation="WAREHOUSE_INBOUND",
            request_id=str(request.request_id), request_hash=old_hash,
        )
        assert replay is None
        complete_idempotent_operation(operation, {"message": "INBOUND_POSTED"})
        await db.commit()

    async def forbidden(*args, **kwargs):
        raise AssertionError("Committed legacy replay reached a reference writer")
    monkeypatch.setattr(inbound, "begin_receipt_reference", forbidden)
    before = await snapshot(pg, t)
    await post(pg, t, request)
    assert await snapshot(pg, t) == before
    assert await reference(pg, t) is None
    await pg.write(t, command(t, amount="96"))
    newer = await snapshot(pg, t)
    await post(pg, t, request)
    assert await snapshot(pg, t) == newer


async def test_inbound_scope_posts_side_effect_but_cannot_read_or_manage_reference(pg):
    t = pg.a
    supplier = await prepare(pg, t)
    await pg.write(t, command(t, amount="120"))
    # Inbound grant only at the exact warehouse; supplier.read remains company scope.
    role = await pg.grant(t, ["inbound.create"])
    await pg.grant(t, ["supplier.read"])
    async with AsyncSession(pg.admin) as db:
        await db.execute(text("DELETE FROM user_roles WHERE company_id=:c AND role_id=:r"),
                         {"c": t.company_id, "r": role})
        db.add(UserLocationAccess(company_id=t.company_id, driver_id=t.ordinary.driver_id,
                                 location_id=t.location_id, role_id=role))
        await db.commit()
    async with pg.session(t) as db:
        options = await inbound.warehouse_inbound_options(InboundOptionsRequest(ids=[t.variant_id]),
                                                         db=db, access=t.ordinary.access(db))
        assert options["items"][0]["purchase_cost_reference"] is None
    request = receipt(t, supplier, items=[
        dict(product_variant_id=t.variant_id, quantity="1", uom_id=t.carton_id, unit_cost="42")
    ])
    await post(pg, t, request, actor=t.ordinary)
    assert (await reference(pg, t))["amount"] == "42.000000"  # never old prefill 120
    with pytest.raises(PurchaseReferenceError) as error:
        await pg.write(t, command(t, revision=2), actor=t.ordinary)
    assert error.value.status_code == 403
    await pg.grant(t, [READ])
    before = await snapshot(pg, t)
    async with pg.session(t) as db:
        options = await inbound.warehouse_inbound_options(InboundOptionsRequest(ids=[t.variant_id]),
                                                         db=db, access=t.ordinary.access(db))
        native = options["items"][0]["purchase_cost_reference"]
        assert (native["amount"], native["purchase_uom_id"], native["currency_code"]) == (
            "42.000000", t.carton_id, "JOD")
    assert await snapshot(pg, t) == before


async def test_manual_first_insert_and_receipt_serialize_without_deadlock(pg):
    t = pg.a
    supplier = await prepare(pg, t)
    async with pg.session(t) as left:
        await write_manual_reference(left, access=t.owner.access(left), product_variant_id=t.variant_id,
                                     payload=command(t, amount="12"))
        contender = asyncio.create_task(post(pg, t, receipt(t, supplier)))
        try:
            await asyncio.sleep(0.15)
            assert not contender.done()
            await left.commit()
            await asyncio.wait_for(contender, 5)
        finally:
            if not contender.done():
                contender.cancel()
                await asyncio.gather(contender, return_exceptions=True)
    current = await reference(pg, t)
    assert current["revision"] == 2 and current["amount"] == "24.000000"


async def test_receipt_first_insert_makes_waiting_manual_revision_stale(pg, monkeypatch):
    t = pg.a
    supplier = await prepare(pg, t)
    entered, release = asyncio.Event(), asyncio.Event()
    original = inbound.write_receipt_references

    async def hold(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result

    monkeypatch.setattr(inbound, "write_receipt_references", hold)
    receipt_task = asyncio.create_task(post(pg, t, receipt(t, supplier)))
    manual = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        manual = asyncio.create_task(pg.write(t, command(t, amount="36")))
        await asyncio.sleep(0.15)
        assert not manual.done()
        release.set()
        await asyncio.wait_for(receipt_task, 5)
        with pytest.raises(PurchaseReferenceError) as error:
            await asyncio.wait_for(manual, 5)
        assert error.value.code == "PURCHASE_REFERENCE_REVISION_CONFLICT"
    finally:
        release.set()
        for task in (receipt_task, manual):
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert (await reference(pg, t))["revision"] == 1


async def test_two_receipts_race_first_insert_and_durable_duplicate_once(pg):
    t = pg.a
    supplier = await prepare(pg, t)
    requests = [receipt(t, supplier), receipt(t, supplier, items=[
        dict(product_variant_id=t.variant_id, quantity="1", uom_id=t.carton_id, unit_cost="36")
    ])]
    await asyncio.wait_for(asyncio.gather(*(post(pg, t, request) for request in requests)), 8)
    current = await reference(pg, t)
    assert current["revision"] == 2
    snap = await snapshot(pg, t)
    assert len(snap["inventory_cost_events"]) == len(snap["purchase_cost_reference_changes"]) == 2
    await asyncio.wait_for(asyncio.gather(*(post(pg, t, requests[0]) for _ in range(2))), 8)
    assert await snapshot(pg, t) == snap


@pytest.mark.parametrize("tamper", ["company", "receipt", "variant"])
async def test_provenance_must_match_exact_posted_receipt(pg, monkeypatch, tamper):
    t = pg.a
    supplier = await prepare(pg, t)
    await post(pg, t, receipt(t, supplier))
    other_supplier = await prepare(pg, pg.b)
    await post(pg, pg.b, receipt(pg.b, other_supplier))
    async with pg.session(t if tamper != "company" else pg.b) as db:
        old_id = await db.scalar(text("SELECT min(id) FROM inventory_movements"))
    before = await snapshot(pg, t)
    original = inbound.write_receipt_references

    async def spoof(db, **kwargs):
        if tamper == "variant":
            from schemas import InboundPurchaseReferenceSelection
            kwargs["selections"] = [InboundPurchaseReferenceSelection(
                product_variant_id=pg.b.variant_id, uom_id=t.carton_id, unit_cost="24")]
        else:
            kwargs["movement_ids"] = [old_id]
        return await original(db, **kwargs)
    monkeypatch.setattr(inbound, "write_receipt_references", spoof)
    with pytest.raises(HTTPException) as error:
        await post(pg, t, receipt(t, supplier))
    assert error.value.detail["code"] in {"INBOUND_REFERENCE_PROVENANCE_INVALID", "INBOUND_REFERENCE_SELECTION_INVALID"}
    assert await snapshot(pg, t) == before
