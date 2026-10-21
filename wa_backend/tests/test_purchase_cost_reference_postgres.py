"""Real commits, independent PostgreSQL sessions, canonical grants and FORCE RLS."""
import asyncio
from decimal import Decimal
import os
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from domains.inventory_costing.purchase_reference import repository
from domains.inventory_costing.purchase_reference.models import PurchaseReferenceChange, PurchaseReferenceCommand
from domains.inventory_costing.purchase_reference.public import (
    MANAGE, READ, ManualReferenceWrite, PurchaseReferenceError, read_reference, write_manual_reference,
)
from models import Permission, UserLocationAccess
from tests.purchase_reference_pg_support import pg  # noqa: F401

pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_PURCHASE_REFERENCE_DB_GATE") != "1",
                       reason="Disposable GitHub PostgreSQL gate only"),
    pytest.mark.asyncio,
]


def command(tenant, revision=0, amount="24", **changes):
    values = dict(request_id=uuid4(), expected_revision=revision, amount=amount,
                  purchase_uom_id=tenant.carton_id, currency_code="JOD")
    values.update(changes)
    return ManualReferenceWrite(**values)


async def test_committed_reference_audit_and_exact_uom_quote(pg):
    t = pg.a
    result = await pg.write(t, command(t))
    assert result["reference"]["amount"] == "24.000000"
    assert result["reference"]["revision"] == 1
    async with pg.session(t) as db:
        read = await read_reference(db, access=t.owner.access(db), product_variant_id=t.variant_id,
                                    quote_uom_id=t.each_id)
        assert read["reference"]["quote"]["amount"] == "2.000000"
        history = await db.scalar(select(PurchaseReferenceChange).where(
            PurchaseReferenceChange.company_id == t.company_id))
        actor = await db.scalar(select(PurchaseReferenceCommand).where(
            PurchaseReferenceCommand.company_id == t.company_id))
        assert history.before_snapshot is None
        assert (history.factor_numerator, history.factor_denominator) == (Decimal("12"), Decimal("1"))
        assert actor.actor_principal_id == t.owner.context.principal_id
        assert actor.actor_backoffice_user_id == t.owner.context.backoffice_user_id
        assert actor.actor_principal_id != actor.actor_backoffice_user_id != t.owner.driver_id


async def test_old_replay_never_overwrites_new_reference(pg):
    t = pg.a
    original = command(t)
    first = await pg.write(t, original)
    second = await pg.write(t, command(t, revision=1, amount="36"))
    assert second["reference"]["revision"] == 2
    assert await pg.write(t, original) == first
    with pytest.raises(PurchaseReferenceError, match="reused") as error:
        await pg.write(t, original.model_copy(update={"amount": Decimal("25")}))
    assert error.value.code == "PURCHASE_REFERENCE_REPLAY_CONFLICT"
    async with pg.session(t) as db:
        current = await read_reference(db, access=t.owner.access(db), product_variant_id=t.variant_id)
        assert current["reference"]["amount"] == "36.000000"
        assert await db.scalar(text("SELECT count(*) FROM purchase_cost_reference_changes")) == 2
        assert await db.scalar(text("SELECT count(*) FROM purchase_cost_reference_commands")) == 2


async def test_stale_revision_rejects_without_evidence(pg):
    t = pg.a
    await pg.write(t, command(t))
    with pytest.raises(PurchaseReferenceError) as error:
        await pg.write(t, command(t, revision=0, amount="48"))
    assert error.value.code == "PURCHASE_REFERENCE_REVISION_CONFLICT"
    assert error.value.context == {"current_revision": 1}
    async with pg.session(t) as db:
        assert await db.scalar(text("SELECT count(*) FROM purchase_cost_reference_commands")) == 1


async def test_first_insert_race_and_identical_request_race(pg):
    t = pg.a
    first, second = command(t), command(t, amount="36")
    async with pg.session(t) as left:
        result = await write_manual_reference(left, access=t.owner.access(left),
                                              product_variant_id=t.variant_id, payload=first)
        started = asyncio.Event()
        async def compete():
            started.set()
            return await pg.write(t, second)
        contender = asyncio.create_task(compete())
        try:
            await started.wait()
            await asyncio.sleep(0.15)
            assert not contender.done()
            await left.commit()
            with pytest.raises(PurchaseReferenceError) as error:
                await asyncio.wait_for(contender, 5)
            assert error.value.code == "PURCHASE_REFERENCE_REVISION_CONFLICT"
        finally:
            if not contender.done():
                contender.cancel()
                await asyncio.gather(contender, return_exceptions=True)
    same = command(t, revision=1, amount="60")
    a, b = await asyncio.gather(pg.write(t, same), pg.write(t, same))
    assert a == b
    assert a["reference"]["revision"] == 2
    assert result["reference"]["revision"] == 1


async def test_rollback_releases_first_insert_and_request_identity(pg):
    t, request = pg.a, command(pg.a)
    async with pg.session(t) as db:
        await write_manual_reference(db, access=t.owner.access(db), product_variant_id=t.variant_id, payload=request)
        await db.rollback()  # forced caller failure after all reference writes
    async with pg.session(t) as db:
        assert await db.scalar(text("SELECT count(*) FROM purchase_cost_references")) == 0
        assert await db.scalar(text("SELECT count(*) FROM purchase_cost_reference_changes")) == 0
        assert await db.scalar(text("SELECT count(*) FROM purchase_cost_reference_commands")) == 0
    assert (await pg.write(t, request))["reference"]["revision"] == 1


async def test_catalog_and_pricing_permissions_do_not_grant_reference_access(pg):
    t = pg.a
    await pg.grant(t, ["catalog.manage", "catalog.read", "pricing.manage", "pricing.view", "inventory.costing.manage"])
    with pytest.raises(PurchaseReferenceError) as error:
        await pg.write(t, command(t), actor=t.ordinary)
    assert error.value.status_code == 403
    async with pg.session(t) as db:
        with pytest.raises(PurchaseReferenceError):
            await read_reference(db, access=t.ordinary.access(db), product_variant_id=t.variant_id)
    await pg.grant(t, [READ])
    async with pg.session(t) as db:
        assert await read_reference(db, access=t.ordinary.access(db), product_variant_id=t.variant_id) == {"reference": None}
    with pytest.raises(PurchaseReferenceError):
        await pg.write(t, command(t), actor=t.ordinary)
    role_id = await pg.grant(t, [MANAGE])
    await pg.write(t, command(t), actor=t.ordinary)
    async with AsyncSession(pg.admin) as db:
        await db.execute(text("DELETE FROM role_permissions WHERE company_id=:c AND role_id=:r"),
                         {"c": t.company_id, "r": role_id})
        await db.commit()
    with pytest.raises(PurchaseReferenceError):
        await pg.write(t, command(t, revision=1), actor=t.ordinary)


async def test_location_only_grant_does_not_grant_company_reference(pg):
    t = pg.a
    # Create a role then move its grant from company to one warehouse.
    role_id = await pg.grant(t, [MANAGE, READ])
    async with AsyncSession(pg.admin) as db:
        await db.execute(text("DELETE FROM user_roles WHERE company_id=:c AND role_id=:r"),
                         {"c": t.company_id, "r": role_id})
        db.add(UserLocationAccess(company_id=t.company_id, driver_id=t.ordinary.driver_id,
                                 location_id=t.location_id, role_id=role_id))
        await db.commit()
    with pytest.raises(PurchaseReferenceError):
        await pg.write(t, command(t), actor=t.ordinary)


async def test_tenant_filters_rls_and_tenant_safe_fk(pg):
    t = pg.a
    await pg.write(t, command(t))
    async with pg.session(pg.b) as db:
        assert await db.scalar(text("SELECT count(*) FROM purchase_cost_references")) == 0
        assert await db.scalar(text("SELECT count(*) FROM purchase_cost_reference_commands")) == 0
        with pytest.raises(PurchaseReferenceError) as error:
            await read_reference(db, access=pg.b.owner.access(db), product_variant_id=t.variant_id)
        assert error.value.status_code == 404
        with pytest.raises(DBAPIError):
            async with db.begin_nested():
                await db.execute(text("""
                    INSERT INTO purchase_cost_references
                    SELECT :foreign_company, product_variant_id, revision, amount, purchase_uom_id, base_uom_id,
                           factor_numerator, factor_denominator, currency_code, source, source_cost_event_id,
                           provenance, changed_at
                    FROM purchase_cost_references
                """), {"foreign_company": t.company_id})
                # No rows are visible, so explicitly attempt foreign tenant write.
                await db.execute(text("""
                    INSERT INTO purchase_cost_reference_commands VALUES
                    (:c,:rid,'MANUAL_PRODUCT_SET',:p,:u,:hash,'{}'::jsonb,now())
                """), {"c": t.company_id, "rid": uuid4(), "p": t.owner.context.principal_id,
                       "u": t.owner.context.backoffice_user_id, "hash": "a" * 64})
    async with pg.session(t) as db:
        with pytest.raises(DBAPIError):
            async with db.begin_nested():
                await db.execute(text("""
                    INSERT INTO purchase_cost_reference_changes
                    SELECT company_id,:foreign_variant,revision,request_id,before_snapshot,
                           amount,purchase_uom_id,base_uom_id,factor_numerator,factor_denominator,
                           currency_code,source,source_cost_event_id,provenance,changed_at
                    FROM purchase_cost_reference_changes
                """), {"foreign_variant": pg.b.variant_id})
    async with pg.session(t) as db:
        await db.execute(text("SELECT set_config('app.current_tenant','',false)"))
        assert await db.scalar(text("SELECT count(*) FROM purchase_cost_references")) == 0
        with pytest.raises(PurchaseReferenceError):
            await read_reference(db, access=t.owner.access(db), product_variant_id=t.variant_id)


async def test_audit_append_only_and_unaudited_state_update_rejected(pg):
    t = pg.a
    await pg.write(t, command(t))
    async with pg.session(t) as db:
        for table in ("purchase_cost_reference_changes", "purchase_cost_reference_commands"):
            with pytest.raises(DBAPIError):
                async with db.begin_nested():
                    await db.execute(text(f"UPDATE {table} SET company_id=company_id"))
        with pytest.raises(DBAPIError):
            async with db.begin_nested():
                await db.execute(text("UPDATE purchase_cost_references SET amount=999,revision=revision+1"))
                await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    # Migration role also cannot rewrite immutable evidence.
    async with AsyncSession(pg.admin) as db:
        with pytest.raises(DBAPIError):
            await db.execute(text("UPDATE purchase_cost_reference_changes SET amount=amount WHERE company_id=:c"),
                             {"c": t.company_id})


async def test_currency_is_explicit_and_global_currency_is_not_changed(pg):
    t = pg.a
    with pytest.raises(PurchaseReferenceError) as error:
        await pg.write(t, command(t, currency_code="USD"))
    assert error.value.code == "PURCHASE_REFERENCE_CURRENCY_MISMATCH"
    await pg.write(t, command(t))
    async with AsyncSession(pg.admin) as db:
        # Company currency is now immutable at the PostgreSQL boundary.
        # An attempted direct SQL rewrite must fail even for this admin role.
        with pytest.raises(DBAPIError, match="COMPANY_CURRENCY_IMMUTABLE"):
            await db.execute(text("UPDATE companies SET currency_code='USD' WHERE id=:c"), {"c": t.company_id})
        await db.rollback()
    async with pg.session(t) as db:
        assert await db.scalar(text("SELECT currency_code FROM purchase_cost_references")) == "JOD"
        assert await db.scalar(text("SELECT currency_code FROM companies WHERE id=:c"), {"c": t.company_id}) == "JOD"
        reference = await read_reference(db, access=t.owner.access(db), product_variant_id=t.variant_id)
        assert reference.reference is not None
        assert reference.reference.currency_code == "JOD"


async def test_exact_conversion_rejects_rounding_and_unmapped_uom(pg):
    t = pg.a
    await pg.write(t, command(t, amount="1"))
    async with pg.session(t) as db:
        with pytest.raises(PurchaseReferenceError) as error:
            await read_reference(db, access=t.owner.access(db), product_variant_id=t.variant_id, quote_uom_id=t.each_id)
        assert error.value.code == "PURCHASE_REFERENCE_PRECISION_LOSS"
    with pytest.raises(PurchaseReferenceError) as error:
        await pg.write(t, command(t, revision=1, purchase_uom_id=2_000_000_001))
    assert error.value.code == "UOM_NOT_REACHABLE"


@pytest.mark.parametrize("method", ["FIFO", "MOVING_AVERAGE"])
async def test_historical_accounting_is_unchanged_by_manual_reference(pg, method):
    from domains.inventory_costing.service import (
        activate_costing_for_first_receipt, build_purchase_cost_input, set_cost_policy,
    )
    from models import ProductBatch
    from services import apply_inventory_movements_batch

    t = pg.a
    async with pg.session(t) as db:
        await set_cost_policy(db, company_id=t.company_id, actor_id=t.owner.driver_id,
                              method=method, expected_version=0)
        batch = ProductBatch(company_id=t.company_id, product_variant_id=t.variant_id,
                             batch_number="REFERENCE-HISTORY")
        db.add(batch)
        await db.flush()
        await activate_costing_for_first_receipt(db, company_id=t.company_id, actor_id=t.owner.driver_id)
        for quantity, cost in ((10, 2), (5, 4)):
            await apply_inventory_movements_batch(
                db, company_id=t.company_id, performed_by=t.owner.driver_id,
                movements=[dict(
                    product_variant_id=t.variant_id, batch_id=batch.id, quantity=Decimal(quantity),
                    movement_kind="PHYSICAL", reference_type="INBOUND_SUPPLIER",
                    reference_id="PCR-HISTORY-" + uuid4().hex,
                    idempotency_key="PCR-" + uuid4().hex,
                    source_location_id=None, source_stock_status=None,
                    destination_location_id=t.location_id, destination_stock_status="AVAILABLE",
                    inventory_cost_input=build_purchase_cost_input(
                        input_uom_id=t.each_id, input_quantity=Decimal(quantity),
                        input_unit_cost=Decimal(cost), base_quantity=Decimal(quantity),
                    ),
                )],
            )
        await apply_inventory_movements_batch(
            db, company_id=t.company_id, performed_by=t.owner.driver_id,
            movements=[dict(
                product_variant_id=t.variant_id, batch_id=batch.id, quantity=Decimal("3"),
                movement_kind="PHYSICAL", reference_type="PCR_TEST_EXTERNAL_EXIT",
                reference_id="PCR-OUT", idempotency_key="PCR-" + uuid4().hex,
                source_location_id=t.location_id, source_stock_status="AVAILABLE",
                destination_location_id=None, destination_stock_status=None,
            )],
        )
        await db.commit()

    tables = (
        "inventory_movements", "inventory_balances", "inventory_cost_policies",
        "inventory_cost_events", "inventory_cost_states", "inventory_cost_layers",
        "inventory_cost_allocations", "price_books", "price_publications", "price_book_entries",
    )
    async def snapshot():
        async with pg.session(t) as db:
            return {table: list((await db.scalars(text(
                f"SELECT to_jsonb(t)::text FROM {table} t WHERE company_id=:c ORDER BY to_jsonb(t)::text"
            ), {"c": t.company_id})).all()) for table in tables}

    before = await snapshot()
    assert len(before["inventory_cost_events"]) == 3
    assert len(before["inventory_cost_layers"]) == (2 if method == "FIFO" else 0)
    assert len(before["inventory_cost_allocations"]) == (1 if method == "FIFO" else 0)
    assert len(before["price_books"]) == 1
    # Existing inbound is deliberately not integrated with the new reference.
    async with pg.session(t) as db:
        assert await db.scalar(text("SELECT count(*) FROM purchase_cost_references")) == 0
    await pg.write(t, command(t, amount="120"))
    await pg.write(t, command(t, revision=1, amount="240"))
    assert await snapshot() == before


async def test_http_route_uses_canonical_access_and_committed_replay(pg):
    import httpx
    from fastapi import Depends, FastAPI
    from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
    from database import get_db
    from domains.inventory_costing.purchase_reference.api import router

    t, actor = pg.a, pg.a.owner
    app = FastAPI()
    app.include_router(router)

    async def database_override():
        async with pg.session(t) as db:
            yield db

    async def access_override(db=Depends(get_db)):
        return actor.access(db)

    app.dependency_overrides[get_db] = database_override
    app.dependency_overrides[get_current_backoffice_capability_access] = access_override
    request = command(t).model_dump(mode="json")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gate") as client:
        path = f"/purchase-cost-references/{t.variant_id}"
        first = await client.put(path, json=request)
        assert first.status_code == 200, first.text
        assert (await client.put(path, json=request)).json() == first.json()
        read = await client.get(path, params={"quote_uom_id": t.each_id})
        assert read.json()["reference"]["quote"]["amount"] == "2.000000"
        actor = t.ordinary
        rejected = await client.get(path)
        assert rejected.status_code == 403
        assert rejected.json()["detail"]["code"] == "PURCHASE_REFERENCE_ACCESS_DENIED"
