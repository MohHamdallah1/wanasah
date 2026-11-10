"""D14: one real signed Backoffice HTTP financial close after confirmed physical custody.

Reuse the accepted CP15 PG16 fixture, field/backoffice principals, and canonical
receiver, without rerunning the existing 800-line settlement matrix. No mocks.
"""
from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from database import engine as runtime_engine
from domains.identity.models import CompanyPrincipal
from main import app
from models import (
    Company, InventoryCostEvent, InventoryMovement, OperationIdempotency,
    SystemAuditLog, Visit, WorkSession,
)
from services import apply_inventory_movement
from tests.canonical_actor_fixtures import seed_company_owner_fixture, seed_field_fixture
from tests.test_representative_settlement_custody_postgres import (
    ACTOR_PASSWORD, _checked_urls, _financial_inventory_fingerprint,
    _runtime_session, _seed, _qty, settlement,
)

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_DISPATCH_D14_HTTP_GATE") != "1",
        reason="Disposable PG16 D14 signed settlement HTTP acceptance only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _login(http, admin, company_id, principal_id, password, path):
    async with AsyncSession(admin) as db:
        company = await db.scalar(select(Company).where(Company.id == company_id))
        username = await db.scalar(
            select(CompanyPrincipal.username).where(CompanyPrincipal.id == principal_id)
        )
    response = await http.post(path, json={
        "company_code": company.company_code,
        "username": username,
        "password": password,
    })
    assert response.status_code == 200, (path, response.text)
    return {"Authorization": "Bearer " + response.json()["token"]}


async def _count(db, model, company_id, **filters):
    return int(await db.scalar(
        select(func.count()).select_from(model).filter_by(company_id=company_id, **filters)
    ) or 0)


async def test_signed_backoffice_financial_close_after_field_custody_has_one_effect():
    runtime_url, admin_url = _checked_urls()
    assert str(runtime_engine.url) == str(runtime_url), "HTTP must use same restricted PG16"
    assert not app.dependency_overrides, "No auth or business override"
    admin = create_async_engine(admin_url, poolclass=NullPool, connect_args={"timeout": 15})
    try:
        (
            company, foreign_company, actor, denied, _counter, _counter_password,
            warehouse, variant, batch, records, _foreign_work,
        ) = await _seed(admin)
        session_id, vehicle_location = records[0]

        # FIELD and DASHBOARD have different persisted principals and login endpoints.
        async with AsyncSession(admin, expire_on_commit=False) as db:
            await db.execute(
                text("SELECT set_config('app.current_tenant',:c,true)"),
                {"c": str(company)},
            )
            field = await seed_field_fixture(
                db, company, password="D14FieldSyntheticLogin123",
            )
            await db.commit()
            field_principal = field.context.principal_id
            await db.execute(
                text("SELECT set_config('app.current_tenant',:c,true)"),
                {"c": str(foreign_company)},
            )
            foreign_owner = await seed_company_owner_fixture(
                db, foreign_company, password="D14ForeignSyntheticOwner123",
            )
            await db.commit()
            foreign_principal = foreign_owner.context.principal_id

        async with _runtime_session(create_async_engine(runtime_url, poolclass=NullPool), company) as db:
            # A real physical event is posted through the canonical movement authority.
            await apply_inventory_movement(
                db, company_id=company, performed_by=actor.driver_id,
                product_variant_id=variant, batch_id=batch, quantity=Decimal("6.250"),
                movement_kind="PHYSICAL", reference_type="D14_ACTUAL_CUSTODY",
                reference_id=str(session_id), idempotency_key="D14-" + uuid4().hex,
                destination_location_id=vehicle_location, destination_stock_status="AVAILABLE",
            )
            await db.commit()
            preview = await settlement.read_representative_custody(
                session_id, db=db, access=actor.access(db),
            )
            assert len(preview["lines"]) == 1
            confirmation = settlement.CustodyConfirm(
                request_id=uuid4(), destination_location_id=warehouse,
                receiver_confirms_handoff=True,
                items=[settlement.CustodyCount(
                    line_key=preview["lines"][0]["line_key"],
                    actual_quantity=preview["lines"][0]["expected_quantity"],
                )],
            )
            received = await settlement.receive_representative_custody(
                session_id, confirmation, db=db, access=actor.access(db),
                legacy_actor=actor.operational_driver,
            )
            assert received["status"] == "CUSTODY_RECEIVED"
            assert received["movement_count"] == 1
            assert await _qty(db, company, vehicle_location, batch, "AVAILABLE") == 0
            assert await _qty(db, company, warehouse, batch, "AVAILABLE") == Decimal("6.250")

        # The HTTP path uses live signed tokens and the actual restricted runtime DB.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://dispatch-d14-real-pg16.test", timeout=30,
        ) as http:
            owner = await _login(
                http, admin, company, actor.context.principal_id, ACTOR_PASSWORD, "/login",
            )
            no_grant = await _login(
                http, admin, company, denied.context.principal_id,
                "CP15DeniedSynthetic123", "/login",
            )
            field_token = await _login(
                http, admin, company, field_principal,
                "D14FieldSyntheticLogin123", "/driver/login",
            )
            foreign = await _login(
                http, admin, foreign_company, foreign_principal,
                "D14ForeignSyntheticOwner123", "/login",
            )
            assert len({
                owner["Authorization"], no_grant["Authorization"],
                field_token["Authorization"], foreign["Authorization"],
            }) == 4

            path = f"/admin/sessions/{session_id}/settle"
            payload = {
                "request_id": str(uuid4()), "actual_cash": "1.000",
                "notes": "D14 authorized actual HTTP settlement",
                "inventory_jard": [],
            }
            async with _runtime_session(
                create_async_engine(runtime_url, poolclass=NullPool), company,
            ) as db:
                before_stock = await _financial_inventory_fingerprint(
                    db, company, session_id, vehicle_location, warehouse,
                )
                before_cost = await _count(db, InventoryCostEvent, company)
                before_visits = (await db.execute(
                    select(Visit.id, Visit.cash_collected, Visit.debt_paid, Visit.status)
                    .where(Visit.company_id == company)
                    .order_by(Visit.id)
                )).all()

            for title, headers in (
                ("ungranted DASHBOARD principal", no_grant),
                ("separate FIELD Flutter principal", field_token),
                ("foreign-company owner", foreign),
            ):
                denied_reply = await http.put(path, json=payload, headers=headers)
                assert denied_reply.status_code in (401, 403, 404), (
                    title, denied_reply.status_code, denied_reply.text[:500],
                )
            without_token = await http.put(path, json=payload)
            assert without_token.status_code == 401, without_token.text

            with_notes_missing = dict(payload, request_id=str(uuid4()), notes=None)
            missing = await http.put(path, json=with_notes_missing, headers=owner)
            assert missing.status_code == 400, missing.text
            completed = await http.put(path, json=payload, headers=owner)
            assert completed.status_code == 200, completed.text
            result = completed.json()
            assert result["is_settled"] is True
            assert Decimal(result["cash_difference"]) == Decimal("1.000")
            replay = await http.put(path, json=payload, headers=owner)
            assert replay.status_code == 200 and replay.json() == result, replay.text
            changed = await http.put(
                path, json=dict(payload, actual_cash="2.000"), headers=owner,
            )
            assert changed.status_code == 409, changed.text
            fresh = await http.put(
                path, json=dict(payload, request_id=str(uuid4())), headers=owner,
            )
            assert fresh.status_code == 409, fresh.text

            async with _runtime_session(
                create_async_engine(runtime_url, poolclass=NullPool), company,
            ) as db:
                assert await _financial_inventory_fingerprint(
                    db, company, session_id, vehicle_location, warehouse,
                ) == before_stock, "Financial POST must never mutate sealed physical custody"
                assert await _count(db, InventoryCostEvent, company) == before_cost
                assert (await db.execute(
                    select(Visit.id, Visit.cash_collected, Visit.debt_paid, Visit.status)
                    .where(Visit.company_id == company).order_by(Visit.id)
                )).all() == before_visits
                settled = await db.scalar(select(WorkSession).where(
                    WorkSession.company_id == company, WorkSession.id == session_id,
                ))
                assert settled.is_settled is True
                assert await _count(
                    db, SystemAuditLog, company,
                    action_type="FINANCIAL_SETTLEMENT",
                    target_id=f"Session_{session_id}_Driver_{actor.driver_id}",
                ) == 1
                assert await _count(
                    db, OperationIdempotency, company,
                    operation="DISPATCH_FINANCIAL_SETTLEMENT",
                    request_id=payload["request_id"],
                ) == 1
        print("D14_REAL_SIGNED_HTTP=PASS; DASHBOARD_AUTHORIZED=200; FIELD_DENIED; "
              "UNGRANTED_DENIED; FOREIGN_DENIED; REPLAY_SAME_UUID=200; "
              "CHANGED_BODY=409; STOCK_COST_VISITS_UNCHANGED; ONE_AUDIT")
    finally:
        await admin.dispose()
        await runtime_engine.dispose()
