"""Cross-channel authority and object scope against real HTTP/PostgreSQL."""
from datetime import datetime, timezone
from uuid import uuid4

import jwt
import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import Config
from domains.authorization.capabilities import FIELD_ASSIGNABLE_PERMISSIONS, PERMISSIONS
from domains.identity.models import CompanyPrincipal
from models import (
    DispatchRoute, InventoryLocation, InventoryTransferHeader, Shop, UserRole, UserLocationAccess,
    Vehicle, Visit, WorkSession, Zone,
)
from tests.field_phase4_fixture import (
    scene, call, new_transfers, no_effect, revoke_default,
)

pytestmark = pytest.mark.asyncio


async def test_canonical_owner_employee_field_are_distinct_persisted_subjects(scene):
    g = scene
    field = jwt.decode(g.token, Config.SECRET_KEY, algorithms=["HS256"])
    owner = jwt.decode(g.owner_token, Config.SECRET_KEY, algorithms=["HS256"])
    office = jwt.decode(g.bo_token, Config.SECRET_KEY, algorithms=["HS256"])
    assert len({field["sub"], owner["sub"], office["sub"]}) == 3
    assert field["channel"] == "FIELD" and field["principal_type"] == "FIELD_REPRESENTATIVE"
    assert all(c["channel"] == "DASHBOARD" and c["principal_type"] == "BACKOFFICE"
               for c in (owner, office))
    assert len({g.field.context.principal_id, g.field.context.representative_id, g.field.driver.id}) == 3
    assert int(field["sub"]) == g.field.context.principal_id
    assert {c["company_id"] for c in (field, owner, office)} == {g.tenant}
    owner_me = await call(g, "GET", "/inventory/access/me", token=g.owner_token)
    office_me = await call(g, "GET", "/inventory/access/me", token=g.bo_token)
    assert owner_me.status_code == office_me.status_code == 200
    assert owner_me.json()["is_company_owner"] is True
    assert office_me.json()["is_company_owner"] is False
    assert set(office_me.json()["permissions"]) == PERMISSIONS
    # Even ALL Backoffice capabilities are not Owner authority.
    path = f"/representatives/{g.field.context.representative_id}/field-roles"
    await no_effect(g, "GET", path, token=g.bo_token, statuses=(403,))
    await no_effect(g, "GET", path, statuses=(401,))
    async with g.admin.connect() as db:
        row = (await db.execute(text(
            "SELECT backoffice_principal_id,field_principal_id,backoffice_user_id,"
            "field_representative_id,classification FROM identity_legacy_driver_map "
            "WHERE company_id=:c AND legacy_driver_id=:d"),
            {"c": g.tenant, "d": g.field.driver.id})).one()
        assert row[0] == int(office["sub"]) and row[1] == int(field["sub"])
        assert row[2] != row[3] and row[4] == "DUAL_SPLIT"


async def test_removing_backoffice_grants_never_removes_or_inherits_field_grants(scene):
    g = scene
    async with AsyncSession(g.admin) as db:
        await db.execute(delete(UserRole).where(
            UserRole.company_id == g.tenant, UserRole.driver_id == g.field.driver.id))
        await db.commit()
    office = await call(g, "GET", "/inventory/access/me", token=g.bo_token)
    assert office.status_code == 200, office.text
    assert office.json()["permissions"] == [] and office.json()["any_permissions"] == []
    await no_effect(g, "GET", f"/visits/{g.visit}", token=g.bo_token, statuses=(403,))
    response = await call(g, "GET", f"/visits/{g.visit}/commercial-state")
    assert response.status_code == 200, response.text
    assert response.json()["commercial_readiness"]["sale_ready"] is True


async def test_removing_field_grants_never_removes_or_inherits_backoffice_grants(scene):
    g = scene
    office_before = (await call(g, "GET", "/inventory/access/me", token=g.bo_token)).json()
    await revoke_default(g)
    await no_effect(g, "GET", f"/visits/{g.visit}", statuses=(403,), code="FIELD_CAPABILITY_DENIED")
    assert (await call(g, "GET", "/inventory/access/me", token=g.bo_token)).json() == office_before
    response = await call(g, "GET", f"/visits/{g.visit}", token=g.bo_token)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("patch", [
    {"channel": "DASHBOARD", "principal_type": "BACKOFFICE"},
    {"channel": "DASHBOARD"},
    {"sub": "legacy"},
    {"company_id": "foreign"},
    {"auth_revision": 2},
])
async def test_signed_claims_cannot_substitute_canonical_persisted_identity(scene, patch):
    g = scene
    foreign = await g.foreign_scene()
    payload = jwt.decode(g.token, Config.SECRET_KEY, algorithms=["HS256"])
    patch = dict(patch)
    if patch.get("sub") == "legacy":
        patch["sub"] = str(g.field.driver.id)
    if patch.get("company_id") == "foreign":
        patch["company_id"] = foreign.tenant
    payload.update(patch)
    synthetic = jwt.encode(payload, Config.SECRET_KEY, algorithm="HS256")
    await no_effect(g, "GET", "/driver/custody", token=synthetic, statuses=(401,), foreign=foreign)


async def test_jwt_role_capability_and_generic_admin_claims_never_supply_grants(scene):
    g = scene
    await revoke_default(g)
    payload = jwt.decode(g.token, Config.SECRET_KEY, algorithms=["HS256"])
    payload.update({"role": "CompanyOwner", "roles": ["FIELD_REPRESENTATIVE_V1"],
                    "capabilities": sorted(PERMISSIONS), "is_admin": True})
    synthetic = jwt.encode(payload, Config.SECRET_KEY, algorithm="HS256")
    await no_effect(g, "GET", f"/visits/{g.visit}/commercial-state", token=synthetic,
                    statuses=(403,), code="FIELD_CAPABILITY_DENIED")


@pytest.mark.parametrize("change", ["inactive", "auth_revision"])
async def test_same_token_principal_lifecycle_rejection_has_no_effect(scene, change):
    g = scene
    async with AsyncSession(g.admin) as db:
        principal = await db.get(CompanyPrincipal, g.field.context.principal_id)
        if change == "inactive":
            principal.is_active = False
        else:
            principal.auth_revision += 1
        await db.commit()
    await no_effect(g, "GET", "/driver/custody", statuses=(401,))


@pytest.mark.parametrize("code", ["catalog.manage", "representative.manage", "inventory.status_change"])
async def test_owner_cannot_assign_arbitrary_backoffice_capability_to_field(scene, code):
    g = scene
    assert code in PERMISSIONS and code not in FIELD_ASSIGNABLE_PERMISSIONS
    created = await call(g, "POST", "/inventory/access/roles",
                         {"name": "P4-office-" + uuid4().hex, "permissions": ["visit.read", code]},
                         token=g.owner_token)
    assert created.status_code == 201, created.text
    await no_effect(g, "POST", f"/representatives/{g.field.context.representative_id}/field-roles",
                    {"request_id": str(uuid4()), "role_id": created.json()["id"]},
                    token=g.owner_token, statuses=(409,), code="FIELD_ROLE_FORBIDDEN_CAPABILITY")


async def test_safe_assigned_custom_role_cannot_escalate_and_system_role_is_protected(scene):
    g = scene
    role = await call(g, "POST", "/inventory/access/roles",
                      {"name": "P4-safe-" + uuid4().hex, "permissions": ["visit.read"]},
                      token=g.owner_token)
    assert role.status_code == 201, role.text
    role_id = role.json()["id"]
    assigned = await call(g, "POST", f"/representatives/{g.field.context.representative_id}/field-roles",
                          {"request_id": str(uuid4()), "role_id": role_id}, token=g.owner_token)
    assert assigned.status_code == 200, assigned.text
    await no_effect(g, "PUT", f"/inventory/access/roles/{role_id}",
                    {"name": "P4-escalated", "permissions": ["visit.read", "catalog.manage"]},
                    token=g.owner_token, statuses=(409,), code="FIELD_ROLE_FORBIDDEN_CAPABILITY")
    await no_effect(g, "PUT", f"/inventory/access/roles/{g.default_role}",
                    {"name": "P4-system-edit", "permissions": ["catalog.manage"]},
                    token=g.owner_token, statuses=(409,))


@pytest.mark.parametrize("scope", ["zone", "route", "session", "vehicle", "location", "visit_owner"])
async def test_full_capability_never_bypasses_visit_operational_scope(scene, scope):
    g = scene
    control = await call(g, "GET", f"/visits/{g.visit}/commercial-state")
    assert control.status_code == 200, control.text
    async with AsyncSession(g.admin) as db:
        if scope == "zone":
            zone = Zone(company_id=g.tenant, name="P4 foreign assignment")
            db.add(zone)
            await db.flush()
            visit = await db.get(Visit, g.visit)
            shop = await db.get(Shop, visit.shop_id)
            shop.zone_id = zone.id
        elif scope == "route":
            (await db.get(DispatchRoute, g.route)).status = "postponed"
        elif scope == "session":
            (await db.get(WorkSession, g.session)).end_time = datetime.now(timezone.utc).replace(tzinfo=None)
        elif scope == "vehicle":
            (await db.get(Vehicle, g.vehicle)).is_active = False
        elif scope == "location":
            (await db.get(InventoryLocation, g.location)).is_active = False
        else:
            visit = await db.get(Visit, g.visit)
            visit.work_session_id = None
            visit.driver_id = g.other.driver.id
        await db.commit()
    await no_effect(g, "PUT", f"/visits/{g.visit}",
                    {"request_id": str(uuid4()), "outcome": "NoSale", "notes": "Synthetic scope proof"},
                    statuses=(403, 404, 409))


async def test_foreign_company_objects_and_work_session_reject_without_either_tenant_effect(scene):
    g = scene
    foreign = await g.foreign_scene()
    requests = [
        ("GET", f"/visits/{foreign.visit}", None),
        ("GET", f"/visits/{foreign.visit}/commercial-state", None),
        ("POST", f"/visits/{foreign.visit}/invoice-preview",
         {"cart_items": [{"product_variant_id": foreign.variant["id"], "packs_quantity": 1}]}),
        ("POST", f"/driver/session/{foreign.session}/reconcile", {"counts": []}),
        ("GET", f"/inventory/access/me?location_id={foreign.location}", None),
        ("GET", f"/dispatch/inventory/{foreign.vehicle}", None),
    ]
    for method, path, body in requests:
        await no_effect(g, method, path, body, foreign=foreign,
                        token=g.owner_token if path.startswith(("/inventory/", "/dispatch/")) else None)
    await no_effect(g, "POST", f"/driver/session/{g.session}/reconcile", {"counts": []},
                    token=g.other_token, statuses=(404,))


@pytest.mark.parametrize("invalid", ["receiver", "session", "destination"])
async def test_mixed_batch_scope_failure_is_atomic_even_after_valid_first_item(scene, invalid):
    g = scene
    ids = await new_transfers(g)
    async with AsyncSession(g.admin) as db:
        header = await db.get(InventoryTransferHeader, ids[1])
        if invalid in ("receiver", "session"):
            # Keep composite session/receiver FKs valid: foreign receiver has
            # their own session; wrong session is this receiver's closed session.
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            session = WorkSession(company_id=g.tenant,
                driver_id=g.other.driver.id if invalid == "receiver" else g.field.driver.id,
                start_time=now, end_time=None if invalid == "receiver" else now)
            db.add(session)
            await db.flush()
            header.work_session_id = session.id
            if invalid == "receiver":
                header.expected_receiver_id = g.other.driver.id
        else:
            vehicle = Vehicle(company_id=g.tenant, plate_number="P4-" + uuid4().hex[:10],
                              maintenance_status="Active", is_active=True)
            db.add(vehicle)
            await db.flush()
            location = InventoryLocation(company_id=g.tenant, code="P4-" + uuid4().hex[:16],
                name="Other vehicle", location_type="VEHICLE", vehicle_id=vehicle.id,
                is_active=True, is_system_managed=False)
            db.add(location)
            await db.flush()
            header.destination_location_id = location.id
        await db.commit()
    # accepted first + rejected second uses both capabilities. A rejected decision
    # intentionally need not have an operational destination, so destination uses accepted.
    second = "accepted" if invalid == "destination" else "rejected"
    body = {"transfers": [
        {"transfer_id": ids[0], "status": "accepted"},
        {"transfer_id": ids[1], "status": second, "reason": "Synthetic mixed decision"},
    ]}
    await no_effect(g, "PUT", "/driver/transfers/batch_respond", body,
                    statuses=(400,) if invalid == "session" else (403, 404, 409))


async def test_dual_split_field_inventory_grant_cannot_expand_backoffice_location_scope(scene):
    g = scene
    created = await call(g, "POST", "/inventory/access/roles",
        {"name": "P4-location-" + uuid4().hex, "permissions": ["inventory.read"]},
        token=g.owner_token)
    assert created.status_code == 201, created.text
    async with AsyncSession(g.admin) as db:
        await db.execute(delete(UserRole).where(
            UserRole.company_id == g.tenant, UserRole.driver_id == g.field.driver.id))
        db.add(UserLocationAccess(company_id=g.tenant, driver_id=g.field.driver.id,
            location_id=g.warehouse_id, role_id=created.json()["id"]))
        await db.commit()
    path = f"/warehouse/inventory/{g.variant['id']}/batches?location_id="
    allowed = await call(g, "GET", path + str(g.warehouse_id), token=g.bo_token)
    assert allowed.status_code == 200, allowed.text
    await no_effect(g, "GET", path + str(g.location), token=g.bo_token, statuses=(403,))
    field = await call(g, "GET", "/driver/custody")
    assert field.status_code == 200, field.text
