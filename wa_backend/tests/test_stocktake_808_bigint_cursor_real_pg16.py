"""Issue #808: three real restricted-PG16/Bearer Stocktake page cursors.

Run ONLY in the disposable local st808_* database. All writes below seed
synthetic test identities/catalogue/session snapshots; production endpoints
under test remain read-only, with no patched dependencies or forced grants.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api import auth
from config import Config
from domains.auth_sessions.codec import issue_access_token
from api.warehouse import stocktake
from domains.identity.models import CompanyPrincipal
from domains.authorization.capabilities import PERMISSIONS
from models import (
    Company, InventoryBalance, InventoryLocation, Permission, Product,
    ProductBatch, ProductVariant, Role, StocktakeSession, UOM,
    UserLocationAccess, role_permissions,
)
from tests.canonical_actor_fixtures import seed_ordinary_backoffice_fixture

pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_STOCKTAKE_808_GATE") != "1",
                       reason="Disposable real PG16 st808 Stocktake gate only"),
    pytest.mark.asyncio,
]
PORT = 56599
DB = "st808_cursor_pg16"
APP_USER = "st808_app"
PASSWORD = "ST808StrictSyntheticBearerPassword"
MAX_BIGINT = (1 << 63) - 1


def _check_urls():
    runtime = make_url(os.environ["DATABASE_URL"])
    admin = make_url(os.environ["DATABASE_URL_MIGRATION"])
    for url in (runtime, admin):
        assert url.drivername == "postgresql+asyncpg"
        assert url.host == "127.0.0.1" and url.port == PORT and url.database == DB
    assert runtime.username == APP_USER
    assert admin.username != runtime.username
    return runtime, admin


async def _grant(db, *, company, actor, locations, codes):
    for code in codes:
        assert code in PERMISSIONS
        permission = await db.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(code=code)
            db.add(permission)
            await db.flush()
        role = Role(company_id=company, name="ST808-" + code + "-" + uuid4().hex)
        db.add(role)
        await db.flush()
        await db.execute(role_permissions.insert().values(
            company_id=company, role_id=role.id, permission_id=permission.id,
        ))
        for location in locations:
            db.add(UserLocationAccess(
                company_id=company, role_id=role.id,
                driver_id=actor.driver_id, location_id=location,
            ))
        await db.flush()


def _payload(kind: str, *, scope: str, identity, discovery=False):
    payload = {"v": 1, "id": identity}
    if discovery:
        payload["s"] = hashlib.sha256(scope.encode()).hexdigest()[:24]
    else:
        payload["kind"] = kind
        payload["scope"] = hashlib.sha256(scope.encode()).hexdigest()[:24]
    return base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).decode("ascii").rstrip("=")


async def _seed(admin_engine):
    """All fixture data belongs exclusively to the isolated PG16 cluster."""
    async with AsyncSession(admin_engine, expire_on_commit=False) as db:
        uom = await db.scalar(select(UOM).where(UOM.code == "ST808_EACH"))
        if uom is None:
            uom = UOM(code="ST808_EACH", name="Stocktake Cursor Each")
            db.add(uom)
            await db.flush()
        tenants = []
        for suffix in ("A", "B"):
            company = Company(name="ST808 Synthetic "+suffix,
                              company_code="ST808-"+suffix+"-"+uuid4().hex[:12],
                              timezone="UTC")
            db.add(company)
            await db.flush()
            await db.execute(text("SELECT set_config('app.current_tenant',:x,true)"),
                             {"x":str(company.id)})
            operator = await seed_ordinary_backoffice_fixture(
                db, company.id, password=PASSWORD,
            )
            denied = await seed_ordinary_backoffice_fixture(
                db, company.id, password=PASSWORD,
            ) if suffix == "A" else None
            locations = []
            for j in range(2 if suffix == "A" else 1):
                loc = InventoryLocation(company_id=company.id, name="ST808 WH "+str(j),
                    code="ST808-"+suffix+"-"+str(j), location_type="WAREHOUSE",
                    is_active=True, version=1)
                db.add(loc)
                await db.flush()
                locations.append(int(loc.id))
            await _grant(db, company=company.id, actor=operator,
                         locations=locations,
                         codes=("stocktake.read","stocktake.start","stocktake.count"))
            tenants.append(dict(
                cid=int(company.id), code=company.company_code,
                user=str((await db.scalar(select(CompanyPrincipal.username).where(
                    CompanyPrincipal.id == operator.context.principal_id)))),
                denied_principal=denied.context.principal_id if denied else None,
                denied_revision=denied.context.auth_revision if denied else None,
                loc=locations,
                operator=int(operator.driver_id),
            ))
            if suffix != "A":
                continue

            product = Product(company_id=company.id, code="ST808-P",
                              name="Stocktake Cursor Product")
            db.add(product)
            await db.flush()
            variants = []
            for i in range(2):
                variant = ProductVariant(
                    company_id=company.id, product_id=product.id,
                    sku="ST808-SKU-"+str(i), name="ST808-Product-"+str(i),
                    base_uom_id=uom.id, quantity_scale=0,
                    quantity_step=Decimal("1"), lot_control_mode="REQUIRED",
                    expiry_control_mode="NONE", lifecycle_status="ACTIVE",
                    published_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
                db.add(variant)
                await db.flush()
                variants.append(int(variant.id))
            batches = []
            for i in range(205):
                batch = ProductBatch(
                    company_id=company.id, product_variant_id=variants[0],
                    batch_number="ST808-B-"+str(i),
                )
                db.add(batch)
                await db.flush()
                batches.append(int(batch.id))
            extra = ProductBatch(company_id=company.id,
                                 product_variant_id=variants[1],
                                 batch_number="ST808-EXTRA")
            db.add(extra)
            await db.flush()
            # Synthetic inventory establishes two valid PAGE 1+2 cycle batches.
            # No stocktake production command is invoked and no movement is posted.
            for bid in batches[:2]:
                db.add(InventoryBalance(
                    company_id=company.id, location_id=locations[0],
                    product_variant_id=variants[0], batch_id=bid,
                    stock_status="AVAILABLE", on_hand_quantity=Decimal("2"),
                    reserved_quantity=Decimal("0"),
                ))
            for i, bid in enumerate(batches):
                db.add(StocktakeSession(
                    company_id=company.id, location_id=locations[0],
                    reference_number="ST808-CYCLE-"+str(i),
                    stocktake_type="CYCLE_COUNT", status="COUNTING",
                    scope_product_variant_id=variants[0], scope_batch_id=bid,
                    started_by=operator.driver_id,
                    snapshot_cutoff_at=datetime.now(timezone.utc).replace(tzinfo=None),
                ))
            full = StocktakeSession(
                company_id=company.id, location_id=locations[1],
                reference_number="ST808-FULL", stocktake_type="FULL_COUNT",
                status="COUNTING", started_by=operator.driver_id,
                snapshot_cutoff_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(full)
            await db.flush()
            tenants[0].update(
                variant=variants[0], full_sid=int(full.id),
                cycle_sid=int((await db.scalar(select(StocktakeSession.id).where(
                    StocktakeSession.reference_number=="ST808-CYCLE-0",
                    StocktakeSession.company_id==company.id)))),
            )
        await db.commit()
        return tenants


@pytest.mark.asyncio
async def test_stocktake_all_three_bigint_cursors_real_pg16_bearer():
    runtime_url, admin_url = _check_urls()
    runtime = create_async_engine(runtime_url, poolclass=NullPool)
    admin = create_async_engine(admin_url, poolclass=NullPool)
    try:
        async with runtime.connect() as db:
            identity = (await db.execute(text(
                "SELECT current_database(), current_user, inet_server_port(),"
                " rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ))).one()
            assert tuple(identity) == (DB, APP_USER, PORT, False, False)
            for table in ("stocktake_sessions","inventory_balances","product_batches"):
                rls = (await db.execute(text(
                    "SELECT relrowsecurity,relforcerowsecurity FROM pg_class"
                    " WHERE oid=to_regclass(:table)"
                ), {"table":table})).one()
                assert tuple(rls)==(True,True), (table, rls)

        a,b = await _seed(admin)
        app=FastAPI()
        app.include_router(auth.router)
        app.include_router(stocktake.router)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://st808.test", timeout=35,
        ) as client:
            async def login(tenant, username):
                resp=await client.post("/login", json={
                    "company_code":tenant["code"],"username":username,
                    "password":PASSWORD,
                })
                assert resp.status_code==200, (resp.status_code, resp.text[:600])
                return {"Authorization":"Bearer "+resp.json()["token"]}

            auth_a=await login(a,a["user"])
            # Real canonical signed bearer; a no-grant actor cannot login.
            # Authenticate the persisted identity independently, then prove
            # the actual HTTP capability guard denies all three read endpoints.
            denied_token=issue_access_token(
                principal_id=a["denied_principal"],company_id=a["cid"],
                channel="DASHBOARD",principal_type="BACKOFFICE",
                auth_revision=a["denied_revision"],secret=Config.SECRET_KEY,
            )
            deny_a={"Authorization":"Bearer "+denied_token}
            auth_b=await login(b,b["user"])
            base="/warehouse/unified"
            endpoints=[
                ("active", f"{base}/stocktakes/active",{"location_id":a["loc"][0]},
                 f'{a["cid"]}|{a["loc"][0]}|active', "stocktake-active-session"),
                ("cycle", f"{base}/stocktake/cycle-batches",
                 {"location_id":a["loc"][0],"product_variant_id":a["variant"]},
                 f'{a["cid"]}|{a["loc"][0]}|{a["variant"]}|', "stocktake-cycle-batch"),
                ("discovery", f'{base}/stocktake/{a["full_sid"]}/discovery-options',
                 {}, f'{a["cid"]}|{a["full_sid"]}|products|', ""),
                ("discovery-batches", f'{base}/stocktake/{a["full_sid"]}/discovery-options',
                 {"product_variant_id":a["variant"]},
                 f'{a["cid"]}|{a["full_sid"]}|batches|{a["variant"]}|', ""),
            ]
            results={}
            for label,url,params,scope,kind in endpoints:
                # Preserve actual auth and cross-company/scope barriers.
                unauth=await client.get(url,params=params)
                assert unauth.status_code==401,(label,"no bearer",unauth.text)
                denied=await client.get(url,params=params,headers=deny_a)
                assert denied.status_code==403,(label,"no grants",denied.text)
                foreign=await client.get(url,params=params,headers=auth_b)
                assert foreign.status_code in (403,404),(label,"foreign",foreign.text)
                if label in ("active","cycle"):
                    wrong_loc={**params,"location_id":b["loc"][0]}
                    wrong=await client.get(url,params=wrong_loc,headers=auth_a)
                    assert wrong.status_code in (403,404),(label,"foreign location",wrong.text)
                initial=await client.get(url,params={**params,"limit":1},
                                         headers=auth_a)
                assert initial.status_code==200,(label,"first",initial.text[:800])
                first=initial.json()
                assert len(first["items"])==1 and first["has_more"]
                assert first["next_cursor"]
                follow=await client.get(url,params={**params,"limit":1,
                                                   "cursor":first["next_cursor"]},
                                        headers=auth_a)
                assert follow.status_code==200,(label,"next",follow.text[:800])
                next_=follow.json()
                assert len(next_["items"])==1
                assert next_["items"][0]["id"] != first["items"][0]["id"]
                assert int(next_["items"][0]["id"]) < int(first["items"][0]["id"])
                results[label]="PAGE_1_AND_PAGE_2_PASS"

                make=lambda identity, scope=scope: _payload(
                    kind, scope=scope, identity=identity,
                    discovery=label.startswith("discovery"),
                )
                for value in (0,-1,True,1.5,"1",2**63,10**70):
                    blocked=await client.get(url,params={**params,"cursor":make(value)},
                                             headers=auth_a)
                    assert blocked.status_code==400, (
                        label,"invalid id",repr(value),blocked.status_code,blocked.text[:250],
                    )
                for bad in ("%%%", "not@@base64", make(5)+"#", ""):
                    blocked=await client.get(url,params={**params,"cursor":bad},
                                             headers=auth_a)
                    assert blocked.status_code==400,(
                        label,"bad base64",repr(bad),blocked.status_code,blocked.text[:300],
                    )
                wrong_scope=await client.get(
                    url,params={**params,"cursor":make(5,scope=scope+"|foreign")},
                    headers=auth_a,
                )
                assert wrong_scope.status_code==400,(label,"scope",wrong_scope.text)
                valid_max=await client.get(url,params={
                    **params,"cursor":make(MAX_BIGINT),"limit":1,
                }, headers=auth_a)
                assert valid_max.status_code==200,(
                    label,"max PG BIGINT",valid_max.status_code,valid_max.text[:300],
                )
                assert len(valid_max.json()["items"])==1
            # MAX page boundary on actual SQL with 205 live distinct session IDs.
            active=await client.get(endpoints[0][1], params={
                "location_id":a["loc"][0],"limit":200,
            }, headers=auth_a)
            assert active.status_code==200,active.text[:300]
            page=active.json()
            assert len(page["items"])==200 and page["has_more"]
            tail=await client.get(endpoints[0][1],params={
                "location_id":a["loc"][0],"limit":200,
                "cursor":page["next_cursor"],
            },headers=auth_a)
            assert tail.status_code==200,tail.text[:300]
            assert len(tail.json()["items"])==5
            assert tail.json()["has_more"] is False
            assert {x["id"] for x in page["items"]}.isdisjoint(
                {x["id"] for x in tail.json()["items"]},
            )
            results["active_205"]="PAGE_200_PLUS_5_PASS"
            print("ST808_REAL_PG16_BEARER_CURSOR_GATE="+json.dumps(
                results,sort_keys=True,
            ),flush=True)
    finally:
        await runtime.dispose()
        await admin.dispose()
