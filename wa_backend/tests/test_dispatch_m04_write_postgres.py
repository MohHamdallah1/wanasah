"""Signed M04 HTTP acceptance; enable only after the ordered merged migration.

These fixtures isolate custody/financial commands. They do not substitute for
the separate real M02/M03 FIELD sale/switch/end/S2 journey acceptance.
No dependency overrides, ORM create_all, manual checkpoint rows or fake grants.
"""
import asyncio
from decimal import Decimal
import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from database import engine as http_engine
from main import app
from models import InventoryBalance, InventoryLocation, InventoryMovement, SystemAuditLog, WorkSession
from services import apply_inventory_movement
from tests.test_cp14c_stocktake_lifecycle_postgres import _ensure_permissions, _grant_location, _runtime_session
from tests.test_dispatch_m04_read_postgres import checked_urls, fingerprint, seed, token

pytestmark = [pytest.mark.skipif(os.getenv("RUN_M04_WRITES_PG16") != "1",
                                reason="Requires merged M03 + ordered M04 Alembic migration"),
              pytest.mark.asyncio(loop_scope="function")]


async def prepared(admin, runtime):
    state = await seed(admin)
    async with _runtime_session(runtime, state["company"]) as db:
        from domains.representative_settlement_multi_vehicle.activation import require_m04_schema
        await require_m04_schema(db)  # Failure is a test failure, never a skipped acceptance.
        for i, quantity in ((0, "83"), (1, "53")):
            await apply_inventory_movement(
                db, company_id=state["company"], performed_by=state["receiver"].driver_id,
                product_variant_id=state["variant"], batch_id=state["batch"], quantity=Decimal(quantity),
                movement_kind="PHYSICAL", reference_type="M04_WRITER_FIXTURE", reference_id=str(state["session"]),
                idempotency_key="M04-WRITE-" + uuid4().hex,
                destination_location_id=state["locations"][i], destination_stock_status="AVAILABLE")
        await db.commit()
    return state


async def command(http, path, headers, **changes):
    sheet = await http.get(path, headers=headers)
    assert sheet.status_code == 200, sheet.text
    return {"request_id": str(uuid4()), "mode": "COUNT_IN_PLACE", "receiver_confirms_count": True,
            "snapshot_token": sheet.json()["snapshot_token"],
            "items": [{"line_key": r["line_key"], "actual_quantity": r["expected_quantity"]}
                      for r in sheet.json()["lines"]], **changes}


async def test_signed_two_vehicle_zero_movement_concurrent_replay_and_once_only_finance():
    runtime_url, admin_url = checked_urls()
    runtime, admin = (create_async_engine(url, poolclass=NullPool) for url in (runtime_url, admin_url))
    try:
        state = await prepared(admin, runtime)
        company, session = state["company"], state["session"]
        async with _runtime_session(runtime, company) as db:
            before = await fingerprint(db, company)
        assert not app.dependency_overrides
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                     base_url="http://m04-writer.test", timeout=30) as http:
            headers = await token(http, admin, state, state["receiver"])
            paths = [f'/admin/sessions/{session}/inventory-custody/vehicles/{v}' for v in state["cars"]]
            a, b = [await command(http, path, headers) for path in paths]
            replies = await asyncio.gather(*[http.post(paths[0] + "/count", headers=headers, json=a)
                                             for _ in range(2)])
            assert all(r.status_code == 200 for r in replies), [r.text for r in replies]
            assert replies[0].json() == replies[1].json()
            assert replies[0].json()["movement_count"] == 0
            assert replies[0].json()["inventory_reconciled"] is False
            financial = {"request_id": str(uuid4()), "actual_cash": "0.000"}
            settle_path = f"/admin/sessions/{session}/settle"
            premature = await http.put(settle_path, headers=headers, json=financial)
            assert premature.status_code == 409, premature.text
            changed = await http.post(paths[0] + "/count", headers=headers, json={**a, "notes": "changed"})
            assert changed.status_code == 409, changed.text
            duplicate = await http.post(paths[0] + "/count", headers=headers,
                                        json={**a, "request_id": str(uuid4())})
            assert duplicate.status_code == 409, duplicate.text
            second = await http.post(paths[1] + "/count", headers=headers, json=b)
            assert second.status_code == 200, second.text
            assert second.json()["movement_count"] == 0 and second.json()["inventory_reconciled"] is True
            settled = await asyncio.gather(*[http.put(settle_path, headers=headers, json=financial)
                                             for _ in range(2)])
            assert all(r.status_code == 200 for r in settled), [r.text for r in settled]
            assert settled[0].json() == settled[1].json()
            replay = await http.post(paths[0] + "/count", headers=headers, json=a)
            assert replay.status_code == 200 and replay.json() == replies[0].json()
            again = await http.put(settle_path, headers=headers,
                                    json={**financial, "request_id": str(uuid4())})
            assert again.status_code == 409, again.text
        async with _runtime_session(runtime, company) as db:
            from domains.representative_settlement_multi_vehicle.models import VehicleCustodyCheckpoint as Checkpoint
            assert await fingerprint(db, company) == before
            assert await db.scalar(select(func.count()).select_from(Checkpoint).where(
                Checkpoint.company_id == company, Checkpoint.work_session_id == session)) == 2
            assert await db.scalar(select(WorkSession.is_settled).where(WorkSession.id == session)) is True
            assert await db.scalar(select(func.count()).select_from(SystemAuditLog).where(
                SystemAuditLog.company_id == company, SystemAuditLog.action_type == "FINANCIAL_SETTLEMENT")) == 1
            assert await db.scalar(select(func.count()).select_from(SystemAuditLog).where(
                SystemAuditLog.company_id == company,
                SystemAuditLog.action_type == "REPRESENTATIVE_CUSTODY_RECEIVED")) == 0
            # The same restricted runtime cannot recode or delete signed history.
            for mutation in ("UPDATE representative_vehicle_custody_checkpoints SET notes='changed' WHERE company_id=:c",
                             "DELETE FROM representative_vehicle_custody_checkpoint_lines WHERE company_id=:c"):
                from sqlalchemy.exc import DBAPIError
                with pytest.raises(DBAPIError):
                    async with db.begin_nested():
                        await db.execute(text(mutation), {"c": company})
        async with AsyncSession(admin) as db:
            # Even migration-owner privileges cannot rewrite signed evidence.
            from sqlalchemy.exc import DBAPIError
            with pytest.raises(DBAPIError):
                await db.execute(text("UPDATE representative_vehicle_custody_checkpoints SET notes='changed' WHERE company_id=:c"),
                                 {"c": company})
            await db.rollback()
    finally:
        await runtime.dispose()
        await admin.dispose()
        await http_engine.dispose()


async def test_physical_handoff_is_explicit_preserves_damaged_lot_and_moves_once():
    runtime_url, admin_url = checked_urls()
    runtime, admin = (create_async_engine(url, poolclass=NullPool) for url in (runtime_url, admin_url))
    try:
        state = await prepared(admin, runtime)
        company = state["company"]
        async with AsyncSession(admin, expire_on_commit=False) as db:
            warehouse = InventoryLocation(company_id=company, location_type="WAREHOUSE", is_active=True,
                                          code="M04-WRITER-WH", name="M04 physical receiver")
            db.add(warehouse)
            await db.flush()
            await _ensure_permissions(db, {"transfer.send", "transfer.destination"})
            await _grant_location(db, company_id=company, driver_id=state["receiver"].driver_id,
                                  location_id=state["locations"][1], codes=("transfer.send",))
            await _grant_location(db, company_id=company, driver_id=state["receiver"].driver_id,
                                  location_id=warehouse.id, codes=("transfer.destination", "inventory.read"))
            destination = warehouse.id
            await db.commit()
        async with _runtime_session(runtime, company) as db:
            await apply_inventory_movement(
                db, company_id=company, performed_by=state["receiver"].driver_id,
                product_variant_id=state["variant"], batch_id=state["batch"], quantity=Decimal("2.125"),
                movement_kind="PHYSICAL", reference_type="M04_DAMAGED_FIXTURE", reference_id=str(state["session"]),
                idempotency_key="M04-DAMAGED-" + uuid4().hex,
                destination_location_id=state["locations"][1], destination_stock_status="DAMAGED")
            await db.commit()
            before = await db.scalar(select(func.count()).select_from(InventoryMovement).where(
                InventoryMovement.company_id == company))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                     base_url="http://m04-handoff.test") as http:
            headers = await token(http, admin, state, state["receiver"])
            path = f'/admin/sessions/{state["session"]}/inventory-custody/vehicles/{state["cars"][1]}'
            payload = await command(http, path, headers, mode="PHYSICAL_HANDOFF",
                                    destination_location_id=destination, receiver_confirms_handoff=True)
            first = await http.post(path + "/count", headers=headers, json=payload)
            assert first.status_code == 200, first.text
            assert first.json()["movement_count"] == 2
            replay = await http.post(path + "/count", headers=headers, json=payload)
            assert replay.status_code == 200 and replay.json() == first.json()
        async with _runtime_session(runtime, company) as db:
            moved = (await db.scalars(select(InventoryMovement).where(
                InventoryMovement.company_id == company, InventoryMovement.reference_type == "REPRESENTATIVE_CUSTODY_RECEIPT"))).all()
            assert {(m.batch_id, m.source_stock_status, m.destination_stock_status, m.quantity) for m in moved} == {
                (state["batch"], "AVAILABLE", "AVAILABLE", Decimal("53")),
                (state["batch"], "DAMAGED", "DAMAGED", Decimal("2.125"))}
            assert all(m.source_location_id == state["locations"][1] and m.destination_location_id == destination
                       and m.work_session_id == state["session"] for m in moved)
            assert await db.scalar(select(func.count()).select_from(InventoryMovement).where(
                InventoryMovement.company_id == company)) == before + 2
            assert await db.scalar(select(func.sum(InventoryBalance.on_hand_quantity)).where(
                InventoryBalance.company_id == company, InventoryBalance.location_id == state["locations"][0])) == Decimal("83")
    finally:
        await runtime.dispose()
        await admin.dispose()
        await http_engine.dispose()
