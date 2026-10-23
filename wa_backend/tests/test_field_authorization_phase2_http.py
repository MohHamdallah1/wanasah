"""Real runtime-role HTTP proof for FIELD authorization Phase 2."""
import os
from uuid import uuid4
from unittest.mock import patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from domains.authorization.capabilities import FIELD_ASSIGNABLE_PERMISSIONS
from domains.authorization.field_models import FieldRepresentativeRole
from domains.authorization.field_role_policy import role_codes
from domains.identity.models import CompanyPrincipal
from models import Role
from tests.field_authorization_phase2_fixture import (
    PASSWORD, auth, error, gate, grant, request, revoke, role, snapshot,
)

pytestmark=pytest.mark.skipif(os.getenv("WANASAH_FIELD_AUTH_PHASE2_GATE")!="1",reason="isolated migrated Phase 2 gate")


@pytest.mark.asyncio
async def test_owner_grant_list_revoke_same_token_and_replay_never_regrants(gate):
    g=gate
    denied=await g.client.get("/__test/field-probe",headers=auth(g.field_token))
    error(denied,403,"FIELD_CAPABILITY_DENIED") # Backoffice ALL grants cannot leak through DUAL_SPLIT.
    safe=await role(g,g.a,["visit.execute"])
    command=str(uuid4())
    initial=await grant(g,g.rep,safe,request_id=command)
    assert initial.status_code==200,initial.text
    assert initial.json()["changed"] is True
    replay=await grant(g,g.rep,safe,request_id=command)
    assert replay.json()==initial.json()
    assert (await g.client.get("/__test/field-probe",headers=auth(g.field_token))).status_code==200
    listing=await g.client.get(f"/representatives/{g.rep}/field-roles?limit=1",headers=auth(g.owner_token))
    assert listing.status_code==200
    assert listing.json()["items"][0]["role_id"]==safe
    assert (await revoke(g,g.rep,safe)).json()["changed"] is True
    error(await g.client.get("/__test/field-probe",headers=auth(g.field_token)),403,"FIELD_CAPABILITY_DENIED")
    before=await snapshot(g)
    assert (await grant(g,g.rep,safe,request_id=command)).json()==initial.json()
    assert await snapshot(g)==before
    error(await g.client.get("/__test/field-probe",headers=auth(g.field_token)),403,"FIELD_CAPABILITY_DENIED")
    other=await role(g,g.a,["visit.execute"])
    error(await grant(g,g.rep,other,request_id=command),409,"FIELD_ROLE_REQUEST_CONFLICT")
    error(await revoke(g,g.rep,safe,request_id=command),409,"FIELD_ROLE_REQUEST_CONFLICT")
    # Neither fresh authentication nor refresh recovers revoked assignments.
    login=await g.client.post("/driver/login",json={"company_code":g.companies[0].company_code,
        "username":"field-dual","password":PASSWORD})
    assert login.status_code==200,login.text
    refreshed=await g.client.post("/refresh",json={"refresh_token":login.json()["refresh_token"]})
    assert refreshed.status_code==200,refreshed.text
    token=refreshed.json().get("access_token") or refreshed.json().get("token")
    error(await g.client.get("/__test/field-probe",headers=auth(token)),403,"FIELD_CAPABILITY_DENIED")


@pytest.mark.asyncio
async def test_management_owner_only_company_and_principal_negative_matrix(gate):
    g=gate
    safe=await role(g,g.a,["visit.execute"])
    foreign=await role(g,g.b,["visit.execute"])
    for token,status in [(g.ordinary_token,403),(g.field_token,401)]:
        before=await snapshot(g)
        assert (await grant(g,g.rep,safe,token=token)).status_code==status
        assert (await revoke(g,g.rep,safe,token=token)).status_code==status
        assert (await g.client.get(f"/representatives/{g.rep}/field-roles",headers=auth(token))).status_code==status
        assert await snapshot(g)==before
    for rep,r,token in [(g.rep,foreign,g.owner_token),(999999,safe,g.owner_token),
                         (g.principal,safe,g.owner_token),(g.rep,safe,g.foreign_owner_token)]:
        before=await snapshot(g)
        error(await grant(g,rep,r,token=token),404,"FIELD_ROLE_TARGET_NOT_FOUND")
        assert await snapshot(g)==before
    async with AsyncSession(g.admin) as db:
        await db.execute(text("UPDATE company_principals SET is_active=false WHERE id=:id"),{"id":g.principal})
        await db.commit()
    before=await snapshot(g)
    error(await grant(g,g.rep,safe),404,"FIELD_ROLE_TARGET_NOT_FOUND")
    assert (await g.client.get("/__test/field-probe",headers=auth(g.field_token))).status_code==401
    assert await snapshot(g)==before
    async with AsyncSession(g.admin) as db:
        await db.execute(text("UPDATE company_principals SET is_active=true WHERE id=:id"),{"id":g.principal})
        await db.commit()


@pytest.mark.asyncio
async def test_any_forbidden_code_rejected_and_later_role_edit_cannot_escalate(gate):
    g=gate
    unsafe=await role(g,g.a,["visit.execute","catalog.manage"])
    before=await snapshot(g)
    error(await grant(g,g.rep,unsafe),409,"FIELD_ROLE_FORBIDDEN_CAPABILITY")
    assert await snapshot(g)==before
    safe=await role(g,g.a,["visit.execute"])
    assert (await grant(g,g.rep,safe)).status_code==200
    response=await g.client.put(f"/inventory/access/roles/{safe}",headers=auth(g.owner_token),
        json={"name":"escalation-attempt","permissions":["visit.execute","catalog.manage"]})
    error(response,409,"FIELD_ROLE_FORBIDDEN_CAPABILITY")
    async with AsyncSession(g.admin) as db:
        assert await db.scalar(select(Role.name).where(Role.id==safe))!="escalation-attempt"
    # A role with no FIELD assignment retains ordinary Backoffice edit behavior.
    office=await role(g,g.a,["visit.execute"])
    changed=await g.client.put(f"/inventory/access/roles/{office}",headers=auth(g.owner_token),
        json={"name":"office-edit","permissions":["catalog.manage"]})
    assert changed.status_code==200,changed.text
    error(await grant(g,g.rep,office),409,"FIELD_ROLE_FORBIDDEN_CAPABILITY")
    assert (await revoke(g,g.rep,safe)).status_code==200


def body():
    return {"request_id":str(uuid4()),"full_name":"Phase2 new representative",
        "username":"new-"+uuid4().hex[:14],"phone_number":"+962790000123","password":PASSWORD}


@pytest.mark.asyncio
async def test_new_company_representative_default_atomicity_and_no_regrant_on_lifecycle_or_retry(gate):
    g=gate
    payload=body()
    response=await request(g,"/representatives",g.owner_token,payload)
    assert response.status_code==201,response.text
    rep=response.json()["id"]
    async with AsyncSession(g.admin) as db:
        default=await db.scalar(select(Role).where(Role.company_id==g.a,Role.system_key=="FIELD_REPRESENTATIVE_V1"))
        assert default is not None
        assert await role_codes(db,g.a,default.id)==FIELD_ASSIGNABLE_PERMISSIONS
        assert await db.scalar(select(FieldRepresentativeRole.role_id).where(
            FieldRepresentativeRole.company_id==g.a,FieldRepresentativeRole.field_representative_id==rep))==default.id
    listed=await g.client.get(f"/representatives/{rep}/field-roles",headers=auth(g.owner_token))
    assert listed.json()["items"][0]["system_key"]=="FIELD_REPRESENTATIVE_V1"
    async with AsyncSession(g.admin) as db:
        assert await db.scalar(select(FieldRepresentativeRole.role_id).where(
            FieldRepresentativeRole.company_id==g.a,FieldRepresentativeRole.field_representative_id==g.rep,
            FieldRepresentativeRole.role_id==default.id)) is None
    assert (await revoke(g,rep,default.id)).status_code==200
    replay=await request(g,"/representatives",g.owner_token,payload)
    assert replay.json()==response.json()
    for action in ("deactivate","reactivate"):
        lifecycle=await request(g,f"/representatives/{rep}/{action}",g.owner_token,{"request_id":str(uuid4())})
        assert lifecycle.status_code==204,lifecycle.text
    updated=await g.client.patch(f"/representatives/{rep}",headers=auth(g.owner_token),
        json={"request_id":str(uuid4()),"full_name":"Still revoked"})
    assert updated.status_code==200,updated.text
    assert (await g.client.get(f"/representatives/{rep}/field-roles",headers=auth(g.owner_token))).json()["items"]==[]
    protected=await g.client.put(f"/inventory/access/roles/{default.id}",headers=auth(g.owner_token),
        json={"name":"illegal","permissions":["catalog.manage"]})
    assert protected.status_code==409,protected.text
    from domains.representatives import repository
    original=repository.assign_new_representative_default
    async def fail_after_assignment(*args,**kwargs):
        await original(*args,**kwargs)
        raise RuntimeError("synthetic rollback probe")
    before=await snapshot(g)
    failed=body()
    with patch.object(repository,"assign_new_representative_default",new=fail_after_assignment):
        response=await request(g,"/representatives",g.owner_token,failed)
    assert response.status_code==500,response.text
    assert await snapshot(g)==before
    async with AsyncSession(g.admin) as db:
        assert await db.scalar(select(CompanyPrincipal.id).where(CompanyPrincipal.username==failed["username"])) is None


@pytest.mark.asyncio
async def test_runtime_default_name_collision_fails_without_identity_or_command_effects(gate):
    g=gate
    await role(g,g.b,["catalog.manage"],name="FIELD_REPRESENTATIVE_V1")
    before=await snapshot(g)
    payload=body()
    response=await request(g,"/representatives",g.foreign_owner_token,payload)
    error(response,409,"FIELD_DEFAULT_ROLE_NAME_CONFLICT")
    assert await snapshot(g)==before
    async with AsyncSession(g.admin) as db:
        assert await db.scalar(select(CompanyPrincipal.id).where(CompanyPrincipal.username==payload["username"])) is None
