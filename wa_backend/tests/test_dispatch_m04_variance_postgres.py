"""Real M04 reviewed variance on separate synthetic PG16 tenant, overlay only."""
from decimal import Decimal
from uuid import uuid4
import os

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from database import engine as http_engine
from main import app
from models import InventoryBalance, InventoryMovement, StocktakeSession, WorkSession
from domains.representative_settlement_multi_vehicle.models import VehicleCustodyCheckpoint
from tests.test_cp14c_stocktake_lifecycle_postgres import (
    _ensure_permissions, _grant_location, _runtime_session,
)
from tests.test_dispatch_m04_read_postgres import checked_urls, token
from tests.test_dispatch_m04_write_postgres import prepared, command

pytestmark = [
    pytest.mark.skipif(
        os.getenv("RUN_M04_WRITES_PG16") != "1",
        reason="Full M04 migrations on isolated PG16 required",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def test_real_surplus_variance_requires_review_before_signed_car_count_and_finance():
    runtime_url, admin_url = checked_urls()
    runtime, admin = (create_async_engine(url, poolclass=NullPool)
                      for url in (runtime_url, admin_url))
    try:
        state = await prepared(admin, runtime)
        cid, session = state["company"], state["session"]
        a, b = state["cars"]
        async with AsyncSession(admin) as db:
            await _ensure_permissions(db, {
                "stocktake.review", "stocktake.approve", "stocktake.recount", "stocktake.start",
            })
            for location in state["locations"]:
                await _grant_location(
                    db, company_id=cid, driver_id=state["receiver"].driver_id,
                    location_id=location,
                    codes=("stocktake.review", "stocktake.approve",
                           "stocktake.recount", "stocktake.start"),
                )
            await db.commit()
        async with _runtime_session(runtime, cid) as db:
            before = await db.scalar(select(func.count()).select_from(InventoryMovement).where(
                InventoryMovement.company_id == cid,
            ))
        assert not app.dependency_overrides
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://m04-review-real", timeout=30,
        ) as http:
            headers = await token(http, admin, state, state["receiver"])
            path = f"/admin/sessions/{session}/inventory-custody/vehicles/{a}"
            wrong_count = await command(http, path, headers)
            assert len(wrong_count["items"]) == 1
            wrong_count["items"][0]["actual_quantity"] = "84"
            reported = await http.post(path + "/count", json=wrong_count, headers=headers)
            assert reported.status_code == 200, reported.text
            assert reported.json()["review_required"] is True
            assert reported.json()["movement_count"] == 0
            async with _runtime_session(runtime, cid) as db:
                assert await db.scalar(select(func.count()).select_from(InventoryMovement).where(
                    InventoryMovement.company_id == cid)) == before
                assert await db.scalar(select(func.count()).select_from(VehicleCustodyCheckpoint).where(
                    VehicleCustodyCheckpoint.company_id == cid,
                    VehicleCustodyCheckpoint.work_session_id == session)) == 0

            review = await http.get(path + "/variance", headers=headers)
            assert review.status_code == 200, review.text
            assert review.json()["status"] == "PENDING_REVIEW"
            decision = {
                "request_id": str(uuid4()),
                "review_token": review.json()["review_token"],
                "password": "M04ReceiverSynthetic123",
            }
            bad_password = await http.post(
                path + "/variance/approve", headers=headers,
                json={**decision, "request_id": str(uuid4()), "password": "wrong"},
            )
            assert bad_password.status_code == 403, bad_password.text
            async with _runtime_session(runtime, cid) as db:
                assert await db.scalar(select(func.count()).select_from(InventoryMovement).where(
                    InventoryMovement.company_id == cid)) == before
            approval = await http.post(path + "/variance/approve",
                                       headers=headers, json=decision)
            assert approval.status_code == 200, approval.text
            assert approval.json()["status"] == "RECONCILED_AWAITING_SIGNED_COUNT"
            assert approval.json()["movement_count"] == 1
            again = await http.post(path + "/variance/approve",
                                    headers=headers, json=decision)
            assert again.status_code == 200 and again.json() == approval.json()

            with_reconciliation = await http.get(path, headers=headers)
            assert with_reconciliation.status_code == 200, with_reconciliation.text
            assert with_reconciliation.json()["lines"][0]["expected_quantity"] == "84"
            signed_a = await command(http, path, headers)
            reply = await http.post(path + "/count", headers=headers, json=signed_a)
            assert reply.status_code == 200 and reply.json()["movement_count"] == 0, reply.text
            other_path = f"/admin/sessions/{session}/inventory-custody/vehicles/{b}"
            signed_b = await command(http, other_path, headers)
            reply_b = await http.post(other_path + "/count", headers=headers, json=signed_b)
            assert reply_b.status_code == 200 and reply_b.json()["movement_count"] == 0, reply_b.text
            financial = {"request_id": str(uuid4()), "actual_cash": "0.000"}
            close = await http.put(f"/admin/sessions/{session}/settle", headers=headers, json=financial)
            assert close.status_code == 200 and close.json()["is_settled"], close.text

        async with _runtime_session(runtime, cid) as db:
            assert await db.scalar(select(func.count()).select_from(InventoryMovement).where(
                InventoryMovement.company_id == cid)) == before + 1
            assert await db.scalar(select(func.count()).select_from(VehicleCustodyCheckpoint).where(
                VehicleCustodyCheckpoint.company_id == cid,
                VehicleCustodyCheckpoint.work_session_id == session)) == 2
            assert await db.scalar(select(WorkSession.is_settled).where(
                WorkSession.company_id == cid, WorkSession.id == session)) is True
            assert await db.scalar(select(InventoryBalance.on_hand_quantity).where(
                InventoryBalance.company_id == cid,
                InventoryBalance.location_id == state["locations"][0],
                InventoryBalance.product_variant_id == state["variant"],
                InventoryBalance.stock_status == "AVAILABLE",
            )) == Decimal("84")
    finally:
        await runtime.dispose()
        await admin.dispose()
        await http_engine.dispose()
