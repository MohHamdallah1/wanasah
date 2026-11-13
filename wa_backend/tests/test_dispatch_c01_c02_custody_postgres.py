"""C01/C02: real restricted PG16/Bearer signed two-party custody recovery.

No mocks, no source fixture alteration, no admin RLS bypass at runtime.
Setup physical stock is written through canonical movement service BEFORE the
custody operation. The operation must add exactly zero inventory movements.
"""
from __future__ import annotations
import asyncio
import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from context import tenant_context
from models import (
    DispatchRoute, InventoryLocation, InventoryMovement, ProductLocation,
    SystemAuditLog, Vehicle, Zone,
)
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from product_lifecycle import DEFAULT_PRODUCT_LOCATION_FLAGS
from services import apply_inventory_movements_batch
from tests.field_authorization_phase3_fixture import PASSWORD
from tests.test_dispatch_m03_period_postgres import gate, _headers

pytestmark = [
    pytest.mark.skipif(os.getenv("RUN_C01_C02_CUSTODY_PG16") != "1",
                       reason="Explicit disposable signed custody PG16 gate only"),
    pytest.mark.asyncio(loop_scope="module"),
]


async def _setup_cars(g):
    tenant = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin, expire_on_commit=False) as db:
            numbers = []
            for stage, amount in (("UNKNOWN", 12), ("OTHER", 8), ("EMPTY", 0)):
                tag = uuid4().hex[:10]
                car = Vehicle(
                    company_id=g.tenant, plate_number="C02"+tag,
                    is_active=True, maintenance_status="Active",
                )
                db.add(car)
                await db.flush()
                loc = InventoryLocation(
                    company_id=g.tenant, vehicle_id=car.id,
                    name="C02-"+stage+" "+tag, code="C02-"+tag,
                    location_type="VEHICLE", is_active=True,
                    is_system_managed=False,
                )
                db.add(loc)
                await db.flush()
                db.add(ProductLocation(
                    company_id=g.tenant, location_id=loc.id,
                    product_variant_id=g.variant["id"],
                    operational_flags=dict(DEFAULT_PRODUCT_LOCATION_FLAGS),
                    created_by=g.actor.id,
                ))
                await db.flush()
                if stage == "UNKNOWN":
                    db.add(VehicleCustodyEpoch(
                        company_id=g.tenant, vehicle_id=car.id,
                        vehicle_location_id=loc.id,
                        custodian_kind="UNCONFIRMED", state="NEEDS_REVIEW",
                        context_revision=1,
                        reason="LEGACY_STOCK_CUSTODIAN_UNKNOWN",
                        evidence_origin="M01_BACKFILL",
                    ))
                if stage == "OTHER":
                    db.add(VehicleCustodyEpoch(
                        company_id=g.tenant, vehicle_id=car.id,
                        vehicle_location_id=loc.id,
                        custodian_kind="FIELD_REPRESENTATIVE",
                        custodian_principal_id=g.other.context.principal_id,
                        field_representative_id=g.other.context.representative_id,
                        accepted_by_principal_id=g.owner.context.principal_id,
                        state="ACCEPTED", context_revision=1,
                        started_at=__import__("models").utc_now(),
                        request_id=str(uuid4()), payload_hash="e"*64,
                    ))
                numbers.append((int(car.id), int(loc.id), stage, amount))
            await db.commit()
        async with AsyncSession(g.admin, expire_on_commit=False) as db:
            for vehicle_id, location_id, stage, quantity in numbers:
                if quantity <= 0:
                    continue
                await apply_inventory_movements_batch(
                    db, company_id=g.tenant, performed_by=g.actor.id,
                    movements=[{
                        "product_variant_id":g.variant["id"],
                        "batch_id":g.batch, "quantity":Decimal(quantity),
                        "movement_kind":"PHYSICAL",
                        "reference_type":"C02_ACCEPTANCE_FIXTURE",
                        "reference_id":"C02-"+uuid4().hex[:15],
                        "idempotency_key":"C02-LOAD-"+uuid4().hex[:15],
                        "source_location_id":g.location,
                        "destination_location_id":location_id,
                        "source_stock_status":"AVAILABLE",
                        "destination_stock_status":"AVAILABLE",
                        "work_session_id":None,
                    }],
                )
            await db.commit()
        return numbers
    finally:
        tenant_context.reset(tenant)


async def _login_owner(g, company=None):
    company = company or g
    r = await g.client.post("/login", json={
        "company_code": company.company_code,
        "username": company.owner_name, "password": PASSWORD,
    })
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


async def _offer(g, manager, car, driver_id, ready):
    r = await g.client.post(f"/vehicles/{car}/custody/offer",
        headers=manager, json={
            "target_driver_id":driver_id,
            "expected_context_revision":ready["context_revision"],
            "expected_stock_snapshot":ready["stock_snapshot"],
        })
    assert r.status_code == 200, r.text
    return r.json()


async def _field_proof(g, car, offer, field_token):
    result = await g.client.post(
        f"/driver/vehicles/{car}/custody/confirm",
        headers=_headers(field_token), json={
            "offer_token": offer["offer_token"],
            "confirmed_stock_snapshot": offer["stock_snapshot"],
            "receiver_confirms_physical_count":True,
        })
    assert result.status_code == 200, result.text
    return result.json()["receiver_proof"]


async def _movement_count(g):
    async with AsyncSession(g.admin) as db:
        return int(await db.scalar(select(func.count(InventoryMovement.id)).where(
            InventoryMovement.company_id == g.tenant,
        )) or 0)


async def _ledger_signature(g):
    """Every persisted movement identity, batch, status and quantity: exact ledger."""
    async with AsyncSession(g.admin) as db:
        rows = (await db.execute(select(
            InventoryMovement.id, InventoryMovement.product_variant_id,
            InventoryMovement.batch_id, InventoryMovement.quantity,
            InventoryMovement.movement_kind, InventoryMovement.source_location_id,
            InventoryMovement.destination_location_id,
            InventoryMovement.reference_type, InventoryMovement.reference_id,
            InventoryMovement.source_stock_status, InventoryMovement.destination_stock_status,
        ).where(InventoryMovement.company_id == g.tenant).order_by(
            InventoryMovement.id,
        ))).all()
        return tuple(tuple(str(v) for v in row) for row in rows)


async def test_c01_c02_real_first_accept_and_transfer_signed_snapshot_replay(gate):
    g = gate
    unknown, different, empty = await _setup_cars(g)
    car, location, _, _ = unknown
    other_car, other_loc, _, _ = different
    empty_car, empty_loc, _, _ = empty
    manager = await _login_owner(g)
    outsider = await _login_owner(g, g.foreign)
    path = f"/vehicles/{car}/custody/readiness"
    assert (await g.client.get(path)).status_code == 401
    assert (await g.client.get(path, headers=_headers(g.token))).status_code in (401, 403)
    assert (await g.client.get(path, headers=outsider)).status_code in (403, 404)
    foreign_offer = await g.client.post(
        f"/vehicles/{car}/custody/offer", headers=outsider, json={
            "target_driver_id": g.field.driver.id,
            "expected_context_revision": 1,
            "expected_stock_snapshot": "a" * 64,
        },
    )
    assert foreign_offer.status_code in (403, 404)
    before = await _movement_count(g)
    ledger_before = await _ledger_signature(g)
    old = await g.client.get(path, headers=manager)
    assert old.status_code == 200, old.text
    assert old.json()["state"] == "NEEDS_REVIEW"
    assert old.json()["stocked"] is True
    assert old.json()["context_revision"] == 1

    option = "/dispatch/launch/resource-availability"
    choices = await g.client.get(option, headers=manager, params={
        "selected_driver_id":g.field.driver.id,
        "selected_vehicle_id":car,
    })
    assert choices.status_code == 200, choices.text
    row = next(x for x in choices.json()["vehicles"] if x["id"] == str(car))
    assert row["code"] == "CUSTODY_NEEDS_REVIEW"
    other_row = next(x for x in choices.json()["vehicles"] if x["id"] == str(other_car))
    assert other_row["code"] == "CUSTODY_REQUIRES_REASSIGNMENT"

    offer = await _offer(g, manager, car, g.field.driver.id, old.json())
    denied = await g.client.post(
        f"/driver/vehicles/{car}/custody/confirm",
        headers=_headers(g.other_token),
        json={"offer_token":offer["offer_token"],
              "confirmed_stock_snapshot":offer["stock_snapshot"],
              "receiver_confirms_physical_count":True})
    assert denied.status_code == 403, denied.text
    proof = await _field_proof(g, car, offer, g.token)
    accepted_body = {"request_id":str(uuid4()),"receiver_proof":proof}
    result = await g.client.post(f"/vehicles/{car}/custody/accept",
                                 headers=manager, json=accepted_body)
    assert result.status_code == 201, result.text
    assert result.json()["state"] == "ACCEPTED"
    assert result.json()["context_revision"] == 2
    assert result.json()["stock_movements"] == 0
    replay = await g.client.post(f"/vehicles/{car}/custody/accept",
                                 headers=manager, json=accepted_body)
    assert replay.status_code == 201 and replay.json()["replayed"] is True
    stale_accept = await g.client.post(
        f"/vehicles/{car}/custody/accept", headers=manager,
        json={"request_id": str(uuid4()), "receiver_proof": proof},
    )
    assert stale_accept.status_code == 409, stale_accept.text
    assert stale_accept.json()["error"]["code"] == "CUSTODY_REVISION_STALE"
    collision = await g.client.post(f"/vehicles/{car}/custody/accept",
        headers=manager, json={**accepted_body, "receiver_proof":proof+"garbage"})
    assert collision.status_code == 409
    assert collision.json()["error"]["code"] == "CUSTODY_REQUEST_ID_REUSED_WITH_DIFFERENT_BODY"
    assert await _movement_count(g) == before
    assert await _ledger_signature(g) == ledger_before
    after = await g.client.get(option, headers=manager, params={
        "selected_driver_id":g.field.driver.id, "selected_vehicle_id":car})
    assert next(x for x in after.json()["vehicles"] if x["id"] == str(car))["code"] == "AVAILABLE"
    accepted_readiness = await g.client.get(path, headers=manager)
    same_holder = await g.client.post(
        f"/vehicles/{car}/custody/offer", headers=manager, json={
            "target_driver_id": g.field.driver.id,
            "expected_context_revision": accepted_readiness.json()["context_revision"],
            "expected_stock_snapshot": accepted_readiness.json()["stock_snapshot"],
        },
    )
    assert same_holder.status_code == 409, same_holder.text
    assert same_holder.json()["error"]["code"] == "CUSTODY_ALREADY_ACCEPTED_BY_TARGET"

    # Current OTHER accepted custody can ONLY be transferred with a new FIELD
    # confirmation and the manager's unique signed, snapshot-fenced receipt.
    other_ready = await g.client.get(
        f"/vehicles/{other_car}/custody/readiness", headers=manager)
    assert other_ready.status_code == 200
    offer2 = await _offer(g, manager, other_car, g.field.driver.id, other_ready.json())
    proof2 = await _field_proof(g, other_car, offer2, g.token)
    transfer_body = {"request_id":str(uuid4()),"receiver_proof":proof2}
    transferred = await g.client.post(
        f"/vehicles/{other_car}/custody/accept",
        headers=manager, json=transfer_body)
    assert transferred.status_code == 201, transferred.text
    assert transferred.json()["context_revision"] == 2
    assert await _movement_count(g) == before

    # Fresh EMPTY vehicle has no epoch; explicit manager+FIELD first handoff,
    # never automatic acceptance or historical fake stock movement.
    free = await g.client.get(
        f"/vehicles/{empty_car}/custody/readiness",headers=manager)
    assert free.status_code == 200
    assert free.json()["state"] == "NO_EPOCH" and not free.json()["stocked"]
    offer3 = await _offer(g, manager, empty_car, g.field.driver.id, free.json())
    proof3 = await _field_proof(g, empty_car, offer3, g.token)
    fresh = await g.client.post(
        f"/vehicles/{empty_car}/custody/accept", headers=manager,
        json={"request_id":str(uuid4()), "receiver_proof":proof3})
    assert fresh.status_code == 201, fresh.text
    assert await _movement_count(g) == before
    assert await _ledger_signature(g) == ledger_before

    async with AsyncSession(g.admin) as db:
        epochs = (await db.scalars(select(VehicleCustodyEpoch).where(
            VehicleCustodyEpoch.company_id == g.tenant,
            VehicleCustodyEpoch.vehicle_id.in_([car, other_car, empty_car]),
        ))).all()
        assert len(epochs) == 5
        assert len([x for x in epochs if x.ended_at is None]) == 3
        assert len([x for x in epochs if x.state == "ACCEPTED"]) == 4
        assert all(x.accepted_by_principal_id is None for x in epochs if x.state == "NEEDS_REVIEW")
        audits = await db.scalar(select(func.count(SystemAuditLog.id)).where(
            SystemAuditLog.company_id == g.tenant,
            SystemAuditLog.action_type.in_((
                "VEHICLE_CUSTODY_FIRST_ACCEPT", "VEHICLE_CUSTODY_REASSIGN",
            )),
        ))
        assert int(audits) == 3
    print("C01_C02_SIGNED_FIRST_AND_TRANSFER_PG16_BEARER_RLS=PASS", flush=True)


async def test_c02_parallel_distinct_requests_only_one_epoch(gate):
    g = gate
    manager = await _login_owner(g)
    car_id, loc, _, _ = (await _setup_cars(g))[0]
    ready = await g.client.get(
        f"/vehicles/{car_id}/custody/readiness", headers=manager)
    offer = await _offer(g,manager,car_id,g.field.driver.id,ready.json())
    proof = await _field_proof(g,car_id,offer,g.token)
    before = await _movement_count(g)
    async def post():
        return await g.client.post(f"/vehicles/{car_id}/custody/accept",
            headers=manager,json={
                "request_id":str(uuid4()),"receiver_proof":proof,
            })
    first, second = await asyncio.gather(post(),post())
    assert sorted((first.status_code,second.status_code)) == [201,409], (
        first.text,second.text)
    assert await _movement_count(g) == before
