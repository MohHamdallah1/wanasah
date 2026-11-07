"""#812: genuine restricted PG16 and production Bearer correction-cycle regression.

The initial commit intentionally proves the pre-fix 10→12→10→12 defect.
Never run against developer/production databases: imports CP10's strict disposable gate.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from api import auth
from api.warehouse import inbound_adjustments, ledger
from domains.identity.models import CompanyPrincipal
from models import Company, InventoryBalance, InventoryMovement, ProductBatch, SystemAuditLog
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
