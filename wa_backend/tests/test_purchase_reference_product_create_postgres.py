"""Real Product quick-create transaction, restricted PostgreSQL runtime and durable replay."""
import asyncio
import hashlib
import json
import os
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api import simple_products as products
from domains.inventory_costing.purchase_reference.models import PurchaseReferenceChange, PurchaseReferenceCommand
from domains.inventory_costing.purchase_reference.public import (
    MANAGE, READ, ManualReferenceWrite, PurchaseReferenceError, read_reference, write_manual_reference,
)
from models import UserLocationAccess
from tests.purchase_reference_pg_support import pg  # noqa: F401

pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_PURCHASE_REFERENCE_DB_GATE") != "1",
                       reason="Disposable GitHub PostgreSQL gate only"),
    pytest.mark.asyncio,
]
CREATE = ["catalog.manage", "catalog.publish", "pricing.manage"]


def command(t, *, with_reference=True, **changes):
    body = dict(request_id=uuid4(), name="Atomic quick create", family_mode="none",
                package_uom_code="CARTON", units_per_package=12, package_price="60",
                lot_control_mode="NONE", expiry_control_mode="NONE")
    if with_reference:
        body["purchase_cost_reference"] = dict(amount="24", purchase_uom_id=t.carton_id, currency_code="JOD")
    body.update(changes)
    return products.SimpleProductCreate(**body)


async def create(pg, t, payload, actor=None):
    actor = actor or t.owner
    async with pg.session(t) as db:
        return await products.create_simple_product(payload, db=db, access=actor.access(db),
                                                    legacy_actor=SimpleNamespace(id=actor.driver_id))


async def read(pg, t, variant, quote=None):
    async with pg.session(t) as db:
        return (await read_reference(db, access=t.owner.access(db), product_variant_id=variant,
                                     quote_uom_id=quote))["reference"]


TABLES = (
    "products", "product_variants", "product_uom_conversions", "product_barcodes",
    "domain_audit_events", "transactional_outbox", "system_audit_logs", "operation_idempotency",
    "inventory_live_stock_company_summaries", "price_books", "price_book_assignments",
    "price_publications", "price_book_entries",
    "purchase_cost_references", "purchase_cost_reference_changes", "purchase_cost_reference_commands",
)
ACCOUNTING = ("inventory_movements", "inventory_balances", "inventory_cost_events",
              "inventory_cost_states", "inventory_cost_layers", "inventory_cost_allocations")


async def snapshot(pg, t, tables=TABLES):
    async with pg.session(t) as db:
        return {table: list((await db.scalars(text(
            f"SELECT to_jsonb(t)::text FROM {table} t WHERE company_id=:c ORDER BY to_jsonb(t)::text"
        ), {"c": t.company_id})).all()) for table in tables}


@pytest.mark.parametrize("method", ["FIFO", "MOVING_AVERAGE"])
async def test_product_and_reference_commit_together_with_exact_uom_and_canonical_audit(pg, method):
    t = pg.a
    from decimal import Decimal
    from domains.inventory_costing.service import (
        set_cost_policy, activate_costing_for_first_receipt, build_purchase_cost_input,
    )
    from models import ProductBatch
    from services import apply_inventory_movements_batch
    async with pg.session(t) as db:
        await set_cost_policy(db, company_id=t.company_id, actor_id=t.owner.driver_id,
                              method=method, expected_version=0)
        batch = ProductBatch(company_id=t.company_id, product_variant_id=t.variant_id,
                             batch_number="PRODUCT-CREATE-HISTORY")
        db.add(batch)
        await db.flush()
        await activate_costing_for_first_receipt(db, company_id=t.company_id, actor_id=t.owner.driver_id)
        await apply_inventory_movements_batch(db, company_id=t.company_id, performed_by=t.owner.driver_id,
            movements=[dict(product_variant_id=t.variant_id, batch_id=batch.id, quantity=Decimal("10"),
                movement_kind="PHYSICAL", reference_type="INBOUND_SUPPLIER", reference_id="HISTORY",
                idempotency_key="HISTORY-" + uuid4().hex, source_location_id=None, source_stock_status=None,
                destination_location_id=t.location_id, destination_stock_status="AVAILABLE",
                inventory_cost_input=build_purchase_cost_input(input_uom_id=t.each_id,
                    input_quantity=Decimal("10"), input_unit_cost=Decimal("2"), base_quantity=Decimal("10")))])
        await apply_inventory_movements_batch(db, company_id=t.company_id, performed_by=t.owner.driver_id,
            movements=[dict(product_variant_id=t.variant_id, batch_id=batch.id, quantity=Decimal("3"),
                movement_kind="PHYSICAL", reference_type="PRODUCT_CREATE_TEST_EXIT", reference_id="HISTORY-COGS",
                idempotency_key="HISTORY-" + uuid4().hex, source_location_id=t.location_id,
                source_stock_status="AVAILABLE", destination_location_id=None, destination_stock_status=None)])
        await db.commit()
    before = await snapshot(pg, t, ACCOUNTING)
    assert len(before["inventory_cost_events"]) == 2
    result = await create(pg, t, command(t))
    variant = result["product_variant_id"]
    assert result["package_price"] == "60.000000" and result["unit_price"] == "5.000000"
    # Reference amount is not copied into ordinary catalog audit or sale prices.
    assert "purchase_cost_reference" not in result
    ref = await read(pg, t, variant, t.each_id)
    assert (ref["amount"], ref["purchase_uom_id"], ref["currency_code"], ref["revision"]) == (
        "24.000000", t.carton_id, "JOD", 1)
    assert ref["quote"]["amount"] == "2.000000"
    async with pg.session(t) as db:
        audit = await db.scalar(select(PurchaseReferenceChange).where(
            PurchaseReferenceChange.company_id == t.company_id,
            PurchaseReferenceChange.product_variant_id == variant))
        actor = await db.scalar(select(PurchaseReferenceCommand).where(
            PurchaseReferenceCommand.company_id == t.company_id))
        assert audit.before_snapshot is None and audit.provenance["reason"] == "PRODUCT_CREATE"
        assert (actor.actor_principal_id, actor.actor_backoffice_user_id) == (
            t.owner.context.principal_id, t.owner.context.backoffice_user_id)
        assert actor.actor_principal_id != actor.actor_backoffice_user_id != t.owner.driver_id
        assert await db.scalar(text("SELECT version FROM product_variants WHERE id=:v"), {"v": variant}) == 2
    assert await snapshot(pg, t, ACCOUNTING) == before


async def test_forced_failure_after_reference_audit_rolls_back_entire_product_create(pg, monkeypatch):
    t, request = pg.a, command(pg.a)
    before = await snapshot(pg, t)
    original = products.write_manual_reference
    reached = False

    async def fail(*args, **kwargs):
        nonlocal reached
        value = await original(*args, **kwargs)
        assert value["reference"]["revision"] == 1
        reached = True
        raise RuntimeError("forced failure after reference and product flush")

    with monkeypatch.context() as patch:
        patch.setattr(products, "write_manual_reference", fail)
        with pytest.raises(RuntimeError):
            await create(pg, t, request)
    assert reached and await snapshot(pg, t) == before
    assert (await read(pg, t, (await create(pg, t, request))["product_variant_id"]))["revision"] == 1


async def test_lost_response_and_old_create_replay_do_not_override_newer_reference(pg):
    t, request = pg.a, command(pg.a)
    first = await create(pg, t, request)
    committed = await snapshot(pg, t)
    assert await create(pg, t, request) == first
    assert await snapshot(pg, t) == committed
    variant = first["product_variant_id"]
    async with pg.session(t) as db:
        await write_manual_reference(db, access=t.owner.access(db), product_variant_id=variant,
                                     payload=ManualReferenceWrite(
                                         request_id=uuid4(), expected_revision=1, amount="36",
                                         purchase_uom_id=t.carton_id, currency_code="JOD"))
        await db.commit()
    newer = await snapshot(pg, t)
    assert await create(pg, t, request) == first
    assert await snapshot(pg, t) == newer
    assert (await read(pg, t, variant))["amount"] == "36.000000"
    changed = request.model_copy(update={"purchase_cost_reference":
        products.ProductCreatePurchaseReference(amount="48", purchase_uom_id=t.carton_id, currency_code="JOD")})
    with pytest.raises(HTTPException) as error:
        await create(pg, t, changed)
    assert error.value.status_code == 409
    assert await snapshot(pg, t) == newer


@pytest.mark.parametrize("family_mode", [None, "none"])
async def test_absent_reference_preserves_exact_historical_hash_and_replay(pg, monkeypatch, family_mode):
    t = pg.a
    request = command(t, with_reference=False, family_mode=family_mode)
    old = request.model_dump(mode="json", exclude={"request_id", "purchase_cost_reference"}
                             | ({"family_mode"} if family_mode is None else set()))
    expected = hashlib.sha256(json.dumps(old, sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=False).encode()).hexdigest()
    assert products._request_hash(request) == expected
    first = await create(pg, t, request)
    assert await read(pg, t, first["product_variant_id"]) is None

    async def forbidden(*args, **kwargs):
        raise AssertionError("Legacy replay reached reference writer")
    monkeypatch.setattr(products, "acquire_reference_writer_guard", forbidden)
    monkeypatch.setattr(products, "write_manual_reference", forbidden)
    await pg.grant(t, CREATE)
    # Old Product create needs only its established capabilities.
    second = await create(pg, t, command(t, with_reference=False), actor=t.ordinary)
    assert await read(pg, t, second["product_variant_id"]) is None
    before = await snapshot(pg, t)
    assert await create(pg, t, request) == first
    assert await snapshot(pg, t) == before


async def test_reference_manage_required_independently_of_product_and_pricing_authority(pg):
    t = pg.a
    await pg.grant(t, [*CREATE, READ])
    before = await snapshot(pg, t)
    with pytest.raises(HTTPException) as error:
        await create(pg, t, command(t), actor=t.ordinary)
    assert error.value.status_code == 403
    assert error.value.detail["code"] == "PURCHASE_REFERENCE_ACCESS_DENIED"
    assert await snapshot(pg, t) == before
    role = await pg.grant(t, [MANAGE])
    async with AsyncSession(pg.admin) as db:
        await db.execute(text("DELETE FROM user_roles WHERE company_id=:c AND role_id=:r"),
                         {"c": t.company_id, "r": role})
        db.add(UserLocationAccess(company_id=t.company_id, driver_id=t.ordinary.driver_id,
                                 location_id=t.location_id, role_id=role))
        await db.commit()
    with pytest.raises(HTTPException) as error:
        await create(pg, t, command(t), actor=t.ordinary)
    assert error.value.status_code == 403
    await pg.grant(t, [MANAGE])
    request = command(t)
    result = await create(pg, t, request, actor=t.ordinary)
    assert (await read(pg, t, result["product_variant_id"]))["revision"] == 1
    # A forged generic Product permission never bypasses current cost authority.
    async with AsyncSession(pg.admin) as db:
        await db.execute(text(
            "DELETE FROM role_permissions WHERE company_id=:c AND permission_id IN "
            "(SELECT id FROM permissions WHERE code=:code)"),
            {"c": t.company_id, "code": MANAGE})
        await db.commit()
    with pytest.raises(HTTPException) as error:
        await create(pg, t, request, actor=t.ordinary)
    assert error.value.status_code == 403


@pytest.mark.parametrize("invalid", ["currency", "unmapped_uom"])
async def test_reference_validation_failure_rolls_back_product_prices_and_audits(pg, invalid):
    t = pg.a
    payload = dict(amount="24", purchase_uom_id=t.carton_id, currency_code="JOD")
    if invalid == "currency":
        payload["currency_code"] = "USD"
    else:
        payload["purchase_uom_id"] = 2_000_000_001
    before = await snapshot(pg, t)
    with pytest.raises(HTTPException) as error:
        await create(pg, t, command(t, purchase_cost_reference=payload))
    assert error.value.detail["code"] in {"PURCHASE_REFERENCE_CURRENCY_MISMATCH", "UOM_NOT_REACHABLE"}
    assert await snapshot(pg, t) == before


async def test_two_same_commands_commit_one_product_reference_and_audit(pg):
    t, request = pg.a, command(pg.a)
    first, second = await asyncio.wait_for(asyncio.gather(create(pg, t, request), create(pg, t, request)), 8)
    assert first == second
    ref = await read(pg, t, first["product_variant_id"])
    assert ref["revision"] == 1
    async with pg.session(t) as db:
        assert await db.scalar(text("SELECT count(*) FROM purchase_cost_reference_changes")) == 1
        assert await db.scalar(text("SELECT count(*) FROM product_variants WHERE company_id=:c"),
                               {"c": t.company_id}) == 2  # fixture SKU plus one created SKU


async def test_reference_guard_precedes_product_pricing_and_waits_for_manual_writer(pg, monkeypatch):
    from domains.inventory_costing.purchase_reference.public import acquire_writer_guard
    t = pg.a
    entered = asyncio.Event()
    original = products.create_products_and_prices

    async def observed(*args, **kwargs):
        entered.set()
        return await original(*args, **kwargs)
    monkeypatch.setattr(products, "create_products_and_prices", observed)
    async with pg.session(t) as db:
        await acquire_writer_guard(db, company_id=t.company_id)
        task = asyncio.create_task(create(pg, t, command(t)))
        try:
            await asyncio.sleep(0.15)
            assert not entered.is_set() and not task.done()
            await db.commit()
            await asyncio.wait_for(task, 5)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert entered.is_set()


async def test_tenant_isolation_and_options_permission_contract(pg):
    t = pg.a
    first = await create(pg, t, command(t))
    async with pg.session(pg.b) as db:
        assert await db.scalar(text("SELECT count(*) FROM purchase_cost_references")) == 0
        with pytest.raises(PurchaseReferenceError) as error:
            await read_reference(db, access=pg.b.owner.access(db), product_variant_id=first["product_variant_id"])
        assert error.value.status_code == 404
    await pg.grant(t, CREATE)
    async with pg.session(t) as db:
        assert await products.purchase_reference_create_options(db, t.ordinary.access(db)) == {
            "can_manage": False, "currency_code": None, "uoms": []}
    await pg.grant(t, [MANAGE])
    async with pg.session(t) as db:
        options = await products.purchase_reference_create_options(db, t.ordinary.access(db))
        assert options["can_manage"] and options["currency_code"] == "JOD"
        assert {"id": t.each_id, "code": "EACH"} in options["uoms"]
