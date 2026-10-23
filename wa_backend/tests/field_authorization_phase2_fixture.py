"""Synthetic migrated HTTP/DB fixture; never connects outside its CI database."""
import os
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest_asyncio
from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.exceptions import HTTPException

from api.auth import router as auth_router
from api.representatives import router as representative_router
from api.authentication.field_authorization import require_field_capability
from database import engine as runtime_engine, get_db
from domains.identity.models import CompanyPrincipal, FieldRepresentative
from domains.identity.migration.models import IdentityLegacyDriverMap
from domains.authorization.capabilities import PERMISSIONS
from main import WanasahRawASGIMiddleware, custom_http_exception_handler, validation_exception_handler
from models import Company, Permission, Role, UserRole, role_permissions
from tests.canonical_actor_fixtures import seed_company_owner_fixture, seed_ordinary_backoffice_fixture

PASSWORD = "FieldPhase2Synthetic123"


def auth(token):
    return {"Authorization":"Bearer " + token}


async def role(g, tenant, codes, name=None):
    async with AsyncSession(g.admin, expire_on_commit=False) as db:
        value = Role(company_id=tenant, name=name or "P2-" + uuid4().hex, is_system_role=False)
        db.add(value)
        await db.flush()
        ids = (await db.scalars(select(Permission.id).where(Permission.code.in_(codes)))).all()
        if ids:
            await db.execute(role_permissions.insert(), [
                {"company_id":tenant,"role_id":value.id,"permission_id":i} for i in ids])
        await db.commit()
        return value.id


async def request(g, path, token, body):
    return await g.client.post(path, json=body, headers=auth(token))


async def grant(g, rep, role_id, *, token=None, request_id=None):
    return await request(g, f"/representatives/{rep}/field-roles", token or g.owner_token,
                         {"role_id":role_id,"request_id":request_id or str(uuid4())})


async def revoke(g, rep, role_id, *, token=None, request_id=None):
    return await request(g, f"/representatives/{rep}/field-roles/{role_id}/revoke",
                         token or g.owner_token, {"request_id":request_id or str(uuid4())})


async def snapshot(g):
    from sqlalchemy import text
    async with g.admin.connect() as db:
        return tuple([(await db.execute(text("SELECT count(*) FROM " + name))).scalar_one()
                      for name in ("field_representative_roles","operation_idempotency","system_audit_logs")])


def error(response, status, code):
    assert response.status_code == status, response.text
    payload = response.json()["error"]
    assert payload["code"] == code, payload
    assert payload["request_id"]
    assert isinstance(payload["context"],dict)


@pytest_asyncio.fixture(scope="module")
async def gate():
    for name in ("DATABASE_URL","DATABASE_URL_MIGRATION"):
        assert make_url(os.environ[name]).database == "field_auth_phase2_gate"
    admin = create_async_engine(os.environ["DATABASE_URL_MIGRATION"],poolclass=NullPool)
    async with AsyncSession(admin, expire_on_commit=False) as db:
        suffix = uuid4().hex[:10]
        companies = [Company(name="Phase2 " + x,company_code="P2-" + x + suffix) for x in ("A","B")]
        db.add_all(companies)
        await db.flush()
        a,b = [c.id for c in companies]
        owners = [await seed_company_owner_fixture(db,c.id,password=PASSWORD) for c in companies]
        ordinary = await seed_ordinary_backoffice_fixture(db,a,password=PASSWORD)
        # Two independent principals/profiles sharing one old operational locator.
        driver = await db.get(__import__("models").Driver,ordinary.driver_id)
        identity_suffix = uuid4().int % 100000000
        principal = CompanyPrincipal(id=700000000+identity_suffix,company_id=a,username="field-dual",password_hash=driver.password_hash,
            full_name="Field dual",principal_type="FIELD_REPRESENTATIVE",is_active=True,auth_revision=1)
        db.add(principal)
        await db.flush()
        rep = FieldRepresentative(id=800000000+identity_suffix,company_id=a,principal_id=principal.id)
        db.add(rep)
        await db.flush()
        bridge = await db.get(IdentityLegacyDriverMap,(a,ordinary.driver_id))
        bridge.classification="DUAL_SPLIT"
        bridge.field_principal_id=principal.id
        bridge.field_representative_id=rep.id
        await db.commit()
        names = [await db.scalar(select(CompanyPrincipal.username).where(CompanyPrincipal.id==o.context.principal_id)) for o in owners]
        ordinary_name = await db.scalar(select(CompanyPrincipal.username).where(CompanyPrincipal.id==ordinary.context.principal_id))
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(representative_router)
    app.add_exception_handler(HTTPException,custom_http_exception_handler)
    app.add_exception_handler(RequestValidationError,validation_exception_handler)
    app.add_middleware(WanasahRawASGIMiddleware)
    async def db_dependency():
        async with AsyncSession(runtime_engine,expire_on_commit=False) as db:
            yield db
    app.dependency_overrides[get_db] = db_dependency
    # Test-only endpoint: Phase 3 production routes remain untouched.
    @app.get("/__test/field-probe")
    async def probe(access=Depends(require_field_capability("visit.execute"))):
        return {"company_id":access.company_id,"codes":sorted(await access.codes())}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),
                                 base_url="http://field-phase2") as client:
        g = SimpleNamespace(admin=admin,client=client,a=a,b=b,rep=rep.id,principal=principal.id,
            owners=owners,ordinary=ordinary,companies=companies)
        privileged = await role(g,a,sorted(PERMISSIONS))
        async with AsyncSession(admin) as db:
            db.add(UserRole(company_id=a,driver_id=ordinary.driver_id,role_id=privileged))
            await db.commit()
        owner_tokens=[]
        for company,name in zip(companies,names):
            response=await client.post("/login",json={"company_code":company.company_code,"username":name,"password":PASSWORD})
            assert response.status_code==200,response.text
            owner_tokens.append(response.json()["token"])
        g.owner_token,g.foreign_owner_token=owner_tokens
        response=await client.post("/login",json={"company_code":companies[0].company_code,"username":ordinary_name,"password":PASSWORD})
        assert response.status_code==200,response.text
        g.ordinary_token=response.json()["token"]
        response=await client.post("/driver/login",json={"company_code":companies[0].company_code,"username":"field-dual","password":PASSWORD})
        assert response.status_code==200,response.text
        g.field_login=response.json()
        g.field_token=g.field_login["token"]
        yield g
    await runtime_engine.dispose()
    await admin.dispose()
