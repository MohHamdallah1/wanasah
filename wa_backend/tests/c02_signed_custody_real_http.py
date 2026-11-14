"""C02 real signed prerequisite for pre-existing M05/D08 PG16 fixtures.

Only the *dedicated* M05/D08 acceptance tests call this helper, AFTER their
canonical D07 stock movement. No M01 synthetic epoch, monkeypatch, fake
Bearer/JWT, inventory mutation or general _prepared_route behavior change.
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import and_, func, select

from domains.identity.migration.models import IdentityLegacyDriverMap
from domains.identity.models import CompanyPrincipal
from models import Company, InventoryBalance, InventoryMovement


async def _real_vehicle_stock(gate, tenant, location):
    async with gate.session() as db:
        stock = (await db.execute(select(
            InventoryBalance.product_variant_id, InventoryBalance.batch_id,
            InventoryBalance.stock_status, InventoryBalance.on_hand_quantity,
            InventoryBalance.reserved_quantity,
        ).where(
            InventoryBalance.company_id == tenant.company_id,
            InventoryBalance.location_id == location,
        ).order_by(
            InventoryBalance.product_variant_id,
            InventoryBalance.batch_id,
            InventoryBalance.stock_status,
        ))).all()
        movement_count = int(await db.scalar(
            select(func.count(InventoryMovement.id)).where(
                InventoryMovement.company_id == tenant.company_id
            ),
        ) or 0)
        return tuple(tuple(str(value) for value in row) for row in stock), movement_count


async def accept_prepared_vehicle_by_real_http(
    gate, tenant, http, owner_headers, launch_body, vehicle_location,
):
    """Signed first acceptance of the already-stocked vehicle via real two actors."""
    company_id = int(tenant.company_id)
    vehicle_id = int(launch_body["vehicle_id"])
    driver_id = int(launch_body["driver_id"])
    before = await _real_vehicle_stock(gate, tenant, vehicle_location)
    assert before[0] and sum(float(row[3]) for row in before[0]) == 25.0

    readiness_path = f"/vehicles/{vehicle_id}/custody/readiness"
    initial = await http.get(readiness_path, headers=owner_headers)
    assert initial.status_code == 200, initial.text
    original = initial.json()
    assert original["state"] == "NO_EPOCH" and original["context_revision"] == 0
    assert original["stocked"] is True and original["vehicle_location_id"] == vehicle_location

    resources = "/dispatch/launch/resource-availability"
    blocked = await http.get(resources, headers=owner_headers, params={
        "selected_driver_id": driver_id, "selected_vehicle_id": vehicle_id,
    })
    assert blocked.status_code == 200, blocked.text
    matches = [x for x in blocked.json()["vehicles"] if x["id"] == str(vehicle_id)]
    assert len(matches) == 1 and not matches[0]["available"]
    assert matches[0]["code"] == "CUSTODY_STOCK_WITHOUT_EPOCH"

    async with gate.session() as db:
        credentials = (await db.execute(select(
            Company.company_code, CompanyPrincipal.username,
        ).select_from(IdentityLegacyDriverMap).join(
            Company, Company.id == IdentityLegacyDriverMap.company_id,
        ).join(
            CompanyPrincipal,
            and_(
                CompanyPrincipal.company_id == IdentityLegacyDriverMap.company_id,
                CompanyPrincipal.id == IdentityLegacyDriverMap.field_principal_id,
                CompanyPrincipal.principal_type == "FIELD_REPRESENTATIVE",
                CompanyPrincipal.is_active.is_(True),
            ),
        ).where(
            IdentityLegacyDriverMap.company_id == company_id,
            IdentityLegacyDriverMap.legacy_driver_id == driver_id,
            IdentityLegacyDriverMap.classification == "FIELD_ONLY",
        ))).one()

    field_login = await http.post("/driver/login", json={
        "company_code": credentials[0], "username": credentials[1],
        "password": "SyntheticFixture123",  # canonical synthetic FIELD fixture
    })
    assert field_login.status_code == 200, field_login.text
    field_headers = {"Authorization": "Bearer " + field_login.json()["token"]}

    offer = await http.post(
        f"/vehicles/{vehicle_id}/custody/offer",
        headers=owner_headers, json={
            "target_driver_id": driver_id,
            "expected_context_revision": original["context_revision"],
            "expected_stock_snapshot": original["stock_snapshot"],
        },
    )
    assert offer.status_code == 200, offer.text
    offered = offer.json()
    assert offered["action"] == "FIRST_ACCEPT" and offered["stock_lines"]
    assert offered["stock_snapshot"] == original["stock_snapshot"]
    assert offered["vehicle_location_id"] == vehicle_location

    receipt = await http.post(
        f"/driver/vehicles/{vehicle_id}/custody/confirm",
        headers=field_headers, json={
            "offer_token": offered["offer_token"],
            "confirmed_stock_snapshot": original["stock_snapshot"],
            "receiver_confirms_physical_count": True,
        },
    )
    assert receipt.status_code == 200 and receipt.json()["confirmed"], receipt.text

    accept_body = {
        "request_id": str(uuid4()),
        "receiver_proof": receipt.json()["receiver_proof"],
    }
    accepted = await http.post(
        f"/vehicles/{vehicle_id}/custody/accept",
        headers=owner_headers, json=accept_body,
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["state"] == "ACCEPTED"
    assert accepted.json()["stock_movements"] == 0
    assert accepted.json()["context_revision"] == original["context_revision"] + 1
    replay = await http.post(
        f"/vehicles/{vehicle_id}/custody/accept",
        headers=owner_headers, json=accept_body,
    )
    assert replay.status_code == 201 and replay.json()["replayed"] is True, replay.text
    assert replay.json()["epoch_id"] == accepted.json()["epoch_id"]
    assert await _real_vehicle_stock(gate, tenant, vehicle_location) == before

    available = await http.get(resources, headers=owner_headers, params={
        "selected_driver_id": driver_id, "selected_vehicle_id": vehicle_id,
    })
    assert available.status_code == 200, available.text
    matches = [x for x in available.json()["vehicles"] if x["id"] == str(vehicle_id)]
    assert len(matches) == 1 and matches[0]["available"] is True
    assert matches[0]["code"] == "AVAILABLE"
    print("C02_PREPARED_REAL_FIRST_ACCEPT_BLOCKED_TO_AVAILABLE_WITHOUT_STOCK_MOVE=PASS", flush=True)
    return int(accepted.json()["context_revision"])
