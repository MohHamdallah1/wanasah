"""#812: genuine restricted PG16 and production Bearer correction-cycle regression.

The initial commit intentionally proves the pre-fix 10→12→10→12 defect.
Never run against developer/production databases: imports CP10's strict disposable gate.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api import auth
from api.warehouse import inbound_adjustments, ledger
from domains.inventory_costing.service import (
    activate_costing_for_first_receipt, build_purchase_cost_input, set_cost_policy,
)
from domains.ledger import inbound_adjustment as adjustment_domain
from domains.identity.models import CompanyPrincipal
from models import (
    Company, InventoryBalance, InventoryCostEvent, InventoryCostState,
    InventoryLocation, InventoryMovement, Product, ProductBatch, ProductVariant,
    SystemAuditLog, UOM, utc_now,
)
from services import apply_inventory_movements_batch
from tests.canonical_actor_fixtures import seed_company_owner_fixture
from tests.test_cp10_ledger_postgres import _seed_movement, pg


@pytest.mark.asyncio
async def test_812_real_bearer_repeated_correction_cycle_and_authority(pg):
    # The fixture checks cp10_app is NOSUPERUSER/NOBYPASSRLS, and creates two
    # independent company identities. The original Supplier movement is canonical.
    reference = "INV-812-" + uuid4().hex[:12]
    async with pg.session(pg.a) as db:
        batch = ProductBatch(
            company_id=pg.a.company_id,
            product_variant_id=pg.a.variant_id,
            batch_number="LOT-812-" + uuid4().hex[:12],
        )
        db.add(batch)
        await db.flush()
        batch_id = int(batch.id)
        original = await _seed_movement(
            db, pg.a, location_id=pg.a.locations[0],
            reference_type="INBOUND_SUPPLIER", reference=reference,
            quantity="10", batch_id=batch_id,
        )
        original_id = int(original.id)
        original_signature = (
            original.reference_type, original.reference_id, int(original.batch_id),
            Decimal(original.quantity), original.source_location_id,
            int(original.destination_location_id),
        )
        await db.commit()

    async with pg.session(pg.a) as db:
        a_company_code = (await db.get(Company, pg.a.company_id)).company_code
        a_owner_name = await db.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.company_id == pg.a.company_id,
            CompanyPrincipal.id == pg.a.owner.context.principal_id,
        ))
        a_ordinary_name = await db.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.company_id == pg.a.company_id,
            CompanyPrincipal.id == pg.a.ordinary.context.principal_id,
        ))
    async with pg.session(pg.b) as db:
        b_company_code = (await db.get(Company, pg.b.company_id)).company_code
        b_owner_name = await db.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.company_id == pg.b.company_id,
            CompanyPrincipal.id == pg.b.owner.context.principal_id,
        ))

    # Real authentication; no dependency override for login, bearer,
    # canonical operational driver, capability guard, or database.
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(inbound_adjustments.router)
    app.include_router(ledger.router)
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://ledger-812.test", timeout=30) as client:
        async def login(company_code, username, password):
            response = await client.post("/login", json={
                "company_code": company_code, "username": username, "password": password,
            })
            assert response.status_code == 200, response.text
            return {"Authorization": "Bearer " + response.json()["token"]}

        owner = await login(a_company_code, a_owner_name, "CP10FixturePassword123")
        ordinary = await login(a_company_code, a_ordinary_name, "SyntheticFixture123")
        foreign = await login(b_company_code, b_owner_name, "CP10FixturePassword123")
        source = f"/warehouse/ledger/{original_id}"

        assert (await client.get(source + "/adjustment-state")).status_code == 401
        assert (await client.get(source + "/adjustment-state",
                                 headers=foreign)).status_code in (403, 404)
        assert (await client.get(
            f"/warehouse/ledger/{pg.a.a2_inbound}/adjustment-state",
            headers=ordinary,
        )).status_code == 403
        assert (await client.post(
            f"/warehouse/ledger/{pg.a.a2_inbound}/adjust",
            headers=ordinary, json={
                "password": "SyntheticFixture123",
                "new_total_quantity": "12",
                "uom_id": pg.a.uom_id,
                "notes": "denied warehouse",
            },
        )).status_code == 403

        async def read():
            response = await client.get(source + "/adjustment-state", headers=owner)
            assert response.status_code == 200, response.text
            return Decimal(response.json()["current_total_quantity"])

        async def counts():
            async with pg.session(pg.a) as db:
                physical = Decimal(await db.scalar(select(func.coalesce(
                    func.sum(InventoryBalance.on_hand_quantity), 0,
                )).where(
                    InventoryBalance.company_id == pg.a.company_id,
                    InventoryBalance.location_id == pg.a.locations[0],
                    InventoryBalance.product_variant_id == pg.a.variant_id,
                    InventoryBalance.batch_id == batch_id,
                )))
                movements = (await db.scalars(select(InventoryMovement).where(
                    InventoryMovement.company_id == pg.a.company_id,
                    InventoryMovement.batch_id == batch_id,
                    InventoryMovement.reference_type == "INBOUND_CORRECTION",
                    InventoryMovement.reference_id == reference,
                ).order_by(InventoryMovement.id))).all()
                return physical, [int(m.id) for m in movements]

        async def correct(total, *, note="cycle-X", password="CP10FixturePassword123"):
            return await client.post(source + "/adjust", headers=owner, json={
                "password": password, "new_total_quantity": str(total),
                "uom_id": pg.a.uom_id, "notes": note,
            })

        assert await read() == Decimal("10")
        assert await counts() == (Decimal("10"), [])
        denied_password = await correct(12, password="IncorrectSynthetic")
        assert denied_password.status_code == 403
        assert await counts() == (Decimal("10"), [])
        print("LEDGER_812_REJECTED_PASSWORD_NO_STOCK_EFFECT=PASS")

        first = await correct(12)
        assert first.status_code == 200, first.text
        p1, ids1 = await counts()
        assert (p1, await read(), len(ids1)) == (Decimal("12"), Decimal("12"), 1)
        print(f"LEDGER_812_FIRST_10_TO_12=PASS movement={ids1[0]}")

        retry_first = await correct(12)
        assert retry_first.status_code == 200
        assert await counts() == (p1, ids1)
        print("LEDGER_812_LOST_RESPONSE_RETRY_NO_DUP=PASS")

        second = await correct(10)
        assert second.status_code == 200, second.text
        p2, ids2 = await counts()
        assert (p2, await read(), len(ids2)) == (Decimal("10"), Decimal("10"), 2)
        assert len(set(ids2)) == 2
        print(f"LEDGER_812_SECOND_12_TO_10=PASS movement={ids2[-1]}")

        third = await correct(12)
        assert third.status_code == 200, third.text
        p3, ids3 = await counts()
        # Deliberately fails on the original source: previously used 10->12
        # key silently replays its ancient movement, with no new on-hand delta.
        assert (p3, await read(), len(ids3)) == (
            Decimal("12"), Decimal("12"), 3
        ), f"REPRODUCED_812_STALE_KEY_REPLAY physical={p3}, ids={ids3}"
        assert len(set(ids3)) == 3
        print(f"LEDGER_812_CYCLE_10_12_10_12=PASS movement={ids3[-1]}")

        # Concurrent identical retries target the state already reached; no
        # further movement may be posted by either HTTP request.
        replicas = await asyncio.gather(correct(12), correct(12))
        assert all(r.status_code == 200 for r in replicas)
        assert await counts() == (Decimal("12"), ids3)

        ledger_page = await client.get("/warehouse/ledger/cursor", headers=owner,
                                       params={"location_id": pg.a.locations[0],
                                               "reference_type": "INBOUND_CORRECTION",
                                               "reference_id": reference})
        assert ledger_page.status_code == 200, ledger_page.text
        displayed = ledger_page.json()["items"]
        assert {r["id"] for r in displayed} == set(ids3)
        assert [Decimal(r["quantity"]) for r in reversed(displayed)] == [
            Decimal("2"), Decimal("-2"), Decimal("2"),
        ]
        assert all(r["batch_id"] == batch_id for r in displayed)
        async with pg.session(pg.a) as db:
            original_again = await db.get(InventoryMovement, original_id)
            assert (original_again.reference_type, original_again.reference_id,
                    int(original_again.batch_id), Decimal(original_again.quantity),
                    original_again.source_location_id,
                    int(original_again.destination_location_id)) == original_signature
            audit_count = int(await db.scalar(select(func.count(SystemAuditLog.id)).where(
                SystemAuditLog.company_id == pg.a.company_id,
                SystemAuditLog.action_type == "INBOUND_ADJUSTMENT",
                SystemAuditLog.target_id.in_(["InventoryMovement_" + str(i) for i in ids3]),
            )))
            assert audit_count == 3
        print("LEDGER_812_REAL_BEARER_RLS_APPEND_ONLY_EXACT_READBACK=PASS")

        # A second legitimate 10->12 cycle with a DIFFERENT authorized actor
        # and different note must never compare against the old owner/notes
        # idempotency key; both identities are admitted at this warehouse.
        back_to_ten = await correct(10)
        assert back_to_ten.status_code == 200
        p4, ids4 = await counts()
        assert (p4, await read(), len(ids4)) == (Decimal("10"), Decimal("10"), 4)
        new_actor_correction = await client.post(
            source + "/adjust", headers=ordinary, json={
                "password": "SyntheticFixture123",
                "new_total_quantity": "12",
                "uom_id": pg.a.uom_id,
                "notes": "different authorized actor and note on second cycle",
            },
        )
        assert new_actor_correction.status_code == 200, new_actor_correction.text
        p5, ids5 = await counts()
        assert (p5, await read(), len(ids5)) == (Decimal("12"), Decimal("12"), 5)
        assert len(set(ids5)) == 5
        print("LEDGER_812_SECOND_CYCLE_CHANGED_AUTHORIZED_ACTOR_AND_NOTES=PASS")


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ("FIFO", "MOVING_AVERAGE"))
async def test_812_costed_correction_cycle_concurrency_and_rollback(pg, method):
    """Use real selected cost method, real PG16 cost state, and real Bearer endpoints.

    Catalog and canonical identities are seeded into an *empty synthetic tenant*
    by the migration role; all inventory and cost effects use cp10_app/forced RLS.
    """
    reference = "COST812-" + uuid4().hex[:15]
    company_code = "C812-" + uuid4().hex
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as seed:
        company = Company(
            name="Ledger 812 Cost " + method,
            company_code=company_code,
            timezone="Asia/Amman", currency_code="JOD",
        )
        seed.add(company)
        await seed.flush()
        company_id = int(company.id)
        await seed.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": str(company_id)},
        )
        owner = await seed_company_owner_fixture(
            seed, company_id, password="CP812CostedFixturePassword123",
        )
        owner_name = await seed.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.company_id == company_id,
            CompanyPrincipal.id == owner.context.principal_id,
        ))
        uom_id = int(await seed.scalar(select(UOM.id).where(UOM.code == "EACH")))
        product = Product(company_id=company_id, code="P812", name="Ledger 812 cost product")
        seed.add(product)
        await seed.flush()
        variant = ProductVariant(
            company_id=company_id, product_id=product.id,
            name="Ledger 812 cost product", sku="C812-COST-SKU",
            base_uom_id=uom_id, quantity_scale=6, quantity_step=Decimal("0.000001"),
            lot_control_mode="REQUIRED", expiry_control_mode="OPTIONAL",
            lifecycle_status="ACTIVE", published_at=utc_now(),
        )
        warehouse = InventoryLocation(
            company_id=company_id, code="WH-C812", name="Costed warehouse",
            location_type="WAREHOUSE",
        )
        seed.add_all([variant, warehouse])
        await seed.flush()
        batch = ProductBatch(
            company_id=company_id, product_variant_id=variant.id,
            batch_number="C812-COST-LOT",
        )
        seed.add(batch)
        await seed.flush()
        variant_id, batch_id, warehouse_id = int(variant.id), int(batch.id), int(warehouse.id)
        await seed.commit()

    tenant = NS(company_id=company_id, owner=owner)
    async with pg.session(tenant) as db:
        await set_cost_policy(
            db, company_id=company_id, actor_id=owner.driver_id,
            method=method, expected_version=0,
        )
        await activate_costing_for_first_receipt(
            db, company_id=company_id, actor_id=owner.driver_id,
        )
        await db.commit()
        created = await apply_inventory_movements_batch(
            db, company_id=company_id, performed_by=owner.driver_id,
            movements=[{
                "product_variant_id": variant_id,
                "batch_id": batch_id,
                "quantity": Decimal("10"),
                "movement_kind": "PHYSICAL",
                "reference_type": "INBOUND_SUPPLIER",
                "reference_id": reference,
                "idempotency_key": "C812-PURCHASE-" + uuid4().hex,
                "source_location_id": None, "destination_location_id": warehouse_id,
                "source_stock_status": None, "destination_stock_status": "AVAILABLE",
                "inventory_cost_input": build_purchase_cost_input(
                    input_uom_id=uom_id, input_quantity=Decimal("10"),
                    input_unit_cost=Decimal("2.5"), base_quantity=Decimal("10"),
                ),
                "notes": "canonical actual-price purchase",
            }],
        )
        original_id = int(created[0].id)
        await db.commit()

    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(inbound_adjustments.router)
    app.include_router(ledger.router)

    async def truth():
        async with pg.session(tenant) as db:
            balance = Decimal(await db.scalar(select(func.coalesce(
                func.sum(InventoryBalance.on_hand_quantity), 0,
            )).where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == warehouse_id,
                InventoryBalance.product_variant_id == variant_id,
                InventoryBalance.batch_id == batch_id,
            )))
            cost = await db.scalar(select(InventoryCostState).where(
                InventoryCostState.company_id == company_id,
                InventoryCostState.product_variant_id == variant_id,
            ))
            events = (await db.scalars(select(InventoryCostEvent).where(
                InventoryCostEvent.company_id == company_id,
                InventoryCostEvent.product_variant_id == variant_id,
            ).order_by(InventoryCostEvent.id))).all()
            corrections = (await db.scalars(select(InventoryMovement).where(
                InventoryMovement.company_id == company_id,
                InventoryMovement.product_variant_id == variant_id,
                InventoryMovement.reference_type == "INBOUND_CORRECTION",
            ).order_by(InventoryMovement.id))).all()
            return {
                "balance": balance,
                "quantity": Decimal(cost.quantity),
                "value": Decimal(cost.inventory_value),
                "events": [(int(e.inventory_movement_id), e.event_type,
                            Decimal(e.total_cost), str(e.method)) for e in events],
                "corrections": [(int(m.id), m.idempotency_key) for m in corrections],
            }

    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://ledger-812-costed.test", timeout=30) as client:
        logged = await client.post("/login", json={
            "company_code": company_code, "username": owner_name,
            "password": "CP812CostedFixturePassword123",
        })
        assert logged.status_code == 200, logged.text
        headers = {"Authorization": "Bearer " + logged.json()["token"]}
        source = f"/warehouse/ledger/{original_id}"

        async def correct(total, notes="cost-cycle"):
            response = await client.post(source + "/adjust", headers=headers, json={
                "password": "CP812CostedFixturePassword123",
                "new_total_quantity": str(total), "uom_id": uom_id,
                "notes": notes,
            })
            assert response.status_code == 200, response.text
            return response

        state = await truth()
        assert (state["balance"], state["quantity"], state["value"]) == (
            Decimal("10"), Decimal("10"), Decimal("25"),
        )
        assert len(state["events"]) == 1
        assert state["events"][0][1:] == ("PURCHASE_IN", Decimal("25"), method)

        for target, expected_total, expected_num in (
            (12, Decimal("30"), 1), (10, Decimal("25"), 2), (12, Decimal("30"), 3),
        ):
            await correct(target)
            state = await truth()
            assert (state["balance"], state["quantity"], state["value"]) == (
                Decimal(target), Decimal(target), expected_total,
            )
            assert len(state["corrections"]) == expected_num
            assert len(state["events"]) == expected_num + 1
        assert state["corrections"][0][1].startswith("ADJ-")
        assert all(key.startswith("ADJ2-") for _, key in state["corrections"][1:])
        assert [ev[1] for ev in state["events"]] == [
            "PURCHASE_IN", "ADJUSTMENT_IN", "OUTBOUND", "ADJUSTMENT_IN",
        ]
        assert [ev[2] for ev in state["events"]] == [
            Decimal("25"), Decimal("5"), Decimal("5"), Decimal("5"),
        ]
        assert {ev[3] for ev in state["events"]} == {method}
        print(f"LEDGER_812_{method}_COSTED_CYCLE_25_30_25_30=PASS")

        ids3 = [movement_id for movement_id, _ in state["corrections"]]
        await correct(12)
        assert [movement_id for movement_id, _ in (await truth())["corrections"]] == ids3
        # True concurrent *new* command: two workers race on 12->11, only one
        # movement and its associated cost event may commit.
        results = await asyncio.gather(correct(11), correct(11))
        assert all(response.status_code == 200 for response in results)
        after_race = await truth()
        assert (after_race["balance"], after_race["quantity"], after_race["value"]) == (
            Decimal("11"), Decimal("11"), Decimal("27.5"),
        )
        assert len(after_race["corrections"]) == 4
        assert len(after_race["events"]) == 5
        await correct(12, notes="fresh changed note after previous cycle")
        after_note = await truth()
        assert (after_note["balance"], after_note["quantity"], after_note["value"]) == (
            Decimal("12"), Decimal("12"), Decimal("30"),
        )
        assert len(after_note["corrections"]) == 5
        assert len(after_note["events"]) == 6
        print(f"LEDGER_812_{method}_CONCURRENT_ONE_COMMIT_NOTE_FRESH=PASS")

        # Inject failure after the real physical + financial mutation but
        # before the Ledger adjustment audit. Transaction rollback must
        # remove movement, cost event, value change, and audit together.
        async with pg.session(tenant) as db:
            real_movement = adjustment_domain.apply_inventory_movement

            async def fail_after_actual_movement(*args, **kwargs):
                await real_movement(*args, **kwargs)
                raise RuntimeError("synthetic failure after canonical posting")

            with patch.object(adjustment_domain, "apply_inventory_movement",
                              side_effect=fail_after_actual_movement):
                with pytest.raises(RuntimeError, match="synthetic failure"):
                    await adjustment_domain.apply_inbound_adjustment(
                        db, company_id=company_id, entry_id=original_id,
                        actor_id=owner.driver_id,
                        new_total_quantity=Decimal("11"),
                        uom_id=uom_id, notes="rollback synthetic",
                    )
                await db.rollback()
        assert await truth() == after_note
        print(f"LEDGER_812_{method}_COST_AND_PHYSICAL_ROLLBACK=PASS")

        ledger_response = await client.get(
            "/warehouse/ledger/cursor", headers=headers,
            params={
                "location_id": warehouse_id,
                "reference_type": "INBOUND_CORRECTION", "reference_id": reference,
            },
        )
        assert ledger_response.status_code == 200, ledger_response.text
        ledger_items = ledger_response.json()["items"]
        assert {int(row["id"]) for row in ledger_items} == {
            movement_id for movement_id, _ in after_note["corrections"]
        }
        assert all(row["cost_method"] == method for row in ledger_items)
        assert all(row["input_unit_cost"] is None for row in ledger_items)
        assert [Decimal(row["quantity"]) for row in reversed(ledger_items)] == [
            Decimal("2"), Decimal("-2"), Decimal("2"),
            Decimal("-1"), Decimal("1"),
        ]
        assert [Decimal(row["total_cost"]) for row in reversed(ledger_items)] == [
            Decimal("5"), Decimal("5"), Decimal("5"),
            Decimal("2.5"), Decimal("2.5"),
        ]
        assert all(Decimal(row["average_cost_after"]) == Decimal("2.5")
                   and row["average_cost_uom_code"] == "EACH"
                   and row["batch_id"] == batch_id for row in ledger_items)
        print(f"LEDGER_812_{method}_REAL_BEARER_COST_LEDGER_READBACK=PASS")
