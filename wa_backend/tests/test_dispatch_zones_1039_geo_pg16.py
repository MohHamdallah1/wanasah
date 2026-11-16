"""#1039 — real PG16 + two Backoffice Bearer: no invented V1 zone geography.

Strictly disposable PostgreSQL16 on loopback 56639, no mocked auth/DB,
no existing user/company writes, no schema changes in the test.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from context import tenant_context
from database import engine as runtime_engine
from domains.identity.models import CompanyPrincipal
from main import app
from models import Company, Country, Governorate, Zone, Shop, Role, Permission, UserRole, role_permissions
from schemas import AddZoneRequest
from tests.canonical_actor_fixtures import (
    seed_company_owner_fixture,
    seed_ordinary_backoffice_fixture,
)

_GUARD = "WANASAH_DISPATCH_ZONES_1039_PG_GATE"
_DB = "m03_941_zone_1039"
_PORT = 56639
_ADMIN = "zone1039_migrator"
_RUNTIME = "zone1039_app"
_PASSWORD = "Zone1039SyntheticPasswordOnly123"

pytestmark = [
    pytest.mark.skipif(os.environ.get(_GUARD) != "1",
                       reason="Explicit unique disposable #1039 PG16 only"),
    pytest.mark.asyncio(loop_scope="function"),
]


def _checked_urls():
    runtime = make_url(os.environ["DATABASE_URL"])
    migration = make_url(os.environ["DATABASE_URL_MIGRATION"])
    expected = ("postgresql+asyncpg", "127.0.0.1", _PORT, _DB)
    for url in (runtime, migration):
        assert (url.drivername, url.host, url.port, url.database) == expected
    assert runtime.username == _RUNTIME and migration.username == _ADMIN
    return runtime, migration


async def _read_truth(admin):
    async with AsyncSession(admin) as db:
        countries = int(await db.scalar(select(func.count()).select_from(Country)))
        governorates = int(await db.scalar(select(func.count()).select_from(Governorate)))
        rows = (await db.execute(
            select(Zone.id, Zone.company_id, Zone.name, Zone.governorate_id, Zone.is_active)
            .order_by(Zone.id)
        )).all()
        return countries, governorates, tuple(rows)


@asynccontextmanager
async def _scene():
    runtime_url, admin_url = _checked_urls()
    assert not app.dependency_overrides
    assert (
        runtime_engine.url.username,
        runtime_engine.url.database,
        runtime_engine.url.port,
    ) == (_RUNTIME, _DB, _PORT)
    admin = create_async_engine(admin_url, poolclass=NullPool)
    try:
        async with runtime_engine.connect() as connection:
            role = (await connection.execute(text(
                "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ))).one()
            assert tuple(role) == (False, False)
            for table in ("zones", "shops", "visits"):
                flags = (await connection.execute(text(
                    "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                    "WHERE oid=to_regclass(:table)"
                ), {"table": table})).one()
                assert tuple(flags) == (True, True), table
        async with AsyncSession(admin, expire_on_commit=False) as db:
            identities = []
            for label, timezone in (("Qatar", "Asia/Qatar"), ("Jordan", "Asia/Amman")):
                company = Company(
                    name="Z1039 Synthetic " + label,
                    company_code="Z1039-" + uuid4().hex[:14],
                    timezone=timezone,
                )
                db.add(company)
                await db.flush()
                token = tenant_context.set(company.id)
                try:
                    await db.execute(text(
                        "SELECT set_config('app.current_tenant',:c,true)"
                    ), {"c": str(company.id)})
                    owner = await seed_company_owner_fixture(
                        db, company.id, password=_PASSWORD,
                    )
                    ordinary = await seed_ordinary_backoffice_fixture(
                        db, company.id, password=_PASSWORD,
                    )
                    # Ordinary Backoffice login requires one persisted capability;
                    # grant unrelated catalog.read, never dispatch.execute.
                    catalog = await db.scalar(select(Permission.id).where(
                        Permission.code == "catalog.read"
                    ))
                    assert catalog is not None
                    role = Role(company_id=company.id, name="Z1039 Catalog Only " + uuid4().hex[:6])
                    db.add(role)
                    await db.flush()
                    await db.execute(role_permissions.insert().values(
                        company_id=company.id, role_id=role.id, permission_id=catalog,
                    ))
                    db.add(UserRole(
                        company_id=company.id, driver_id=ordinary.driver_id,
                        role_id=role.id,
                    ))
                    usernames = (
                        await db.scalar(select(CompanyPrincipal.username).where(
                            CompanyPrincipal.company_id == company.id,
                            CompanyPrincipal.id == owner.context.principal_id,
                        )),
                        await db.scalar(select(CompanyPrincipal.username).where(
                            CompanyPrincipal.company_id == company.id,
                            CompanyPrincipal.id == ordinary.context.principal_id,
                        )),
                    )
                    identities.append((company.id, company.company_code, usernames))
                finally:
                    tenant_context.reset(token)
            await db.commit()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://zone-1039-disposable-pg16.test", timeout=30,
        ) as client:
            async def login(index, ordinary=False):
                _cid, code, usernames = identities[index]
                response = await client.post("/login", json={
                    "company_code": code, "username": usernames[1 if ordinary else 0],
                    "password": _PASSWORD,
                })
                assert response.status_code == 200, response.text
                return {"Authorization": "Bearer " + response.json()["token"]}

            yield client, admin, identities, (
                await login(0), await login(1), await login(0, ordinary=True),
            )
    finally:
        await admin.dispose()
        await runtime_engine.dispose()


async def test_no_country_or_global_governorate_guess_and_company_name_uniqueness():
    async with _scene() as (http, admin, identities, auth):
        owner_qatar, owner_jordan, _ordinary = auth
        baseline = await _read_truth(admin)
        same_name = "Synthetic Region " + uuid4().hex[:10]

        async def create(headers, name, **extra):
            return await http.post("/dispatch/zones", headers=headers,
                                   json={"name": name, **extra})

        # Two companies must create the same zone name independently with NULL
        # governorate, even when the geography catalog starts completely empty.
        q = await create(owner_qatar, same_name)
        j = await create(owner_jordan, same_name)
        assert q.status_code == 201 and j.status_code == 201, (q.text, j.text)
        qid, jid = int(q.json()["zone_id"]), int(j.json()["zone_id"])
        assert qid != jid
        counts = await _read_truth(admin)
        assert counts[:2] == baseline[:2], counts
        assert {(r[1], r[2], r[3]) for r in counts[2]
                if r[0] in {qid, jid}} == {
            (identities[0][0], same_name, None),
            (identities[1][0], same_name, None),
        }

        # Global catalog entries of TWO different countries must not become
        # implicit company geography based on their IDs, timezone, or currency.
        async with AsyncSession(admin, expire_on_commit=False) as db:
            countries = [Country(name="Z1039 Jordan " + uuid4().hex[:7]),
                         Country(name="Z1039 Qatar " + uuid4().hex[:7])]
            db.add_all(countries)
            await db.flush()
            governorates = [
                Governorate(name="Z1039 Amman", country_id=countries[0].id),
                Governorate(name="Z1039 Doha", country_id=countries[1].id),
            ]
            db.add_all(governorates)
            await db.commit()
            before_ids = [(c.id, c.name) for c in countries], [
                (g.id, g.country_id) for g in governorates
            ]

        q_next = await create(owner_qatar, "Z1039 Qatar No Inference", intervalDays=7,
                              startDate="2026-11-20")
        j_next = await create(owner_jordan, "Z1039 Jordan No Inference")
        assert q_next.status_code == 201 and j_next.status_code == 201, (
            q_next.text, j_next.text)
        after = await _read_truth(admin)
        assert after[:2] == (baseline[0] + 2, baseline[1] + 2)
        new_zone_ids = {qid, jid, int(q_next.json()["zone_id"]),
                        int(j_next.json()["zone_id"])}
        assert len(after[2]) == len(baseline[2]) + 4
        assert all(row[3] is None for row in after[2]
                   if row[0] in new_zone_ids), after
        async with AsyncSession(admin) as db:
            actual = (
                (await db.execute(select(Country.id, Country.name)
                                  .order_by(Country.id))).all(),
                (await db.execute(select(Governorate.id, Governorate.country_id)
                                  .order_by(Governorate.id))).all(),
            )
            assert all((cid, name) in actual[0] for cid, name in before_ids[0])
            assert all((gid, cid) in actual[1] for gid, cid in before_ids[1])

        active_duplicate = await create(owner_qatar, same_name)
        assert active_duplicate.status_code == 409, active_duplicate.text
        assert "نشطة" in active_duplicate.text
        # Omitted geography remains valid. The existing request forbids hidden
        # operator-selected IDs, preventing a client-side scope bypass.
        invented_id = await create(owner_qatar, "Z1039 Inject", governorate_id=governorates[0].id)
        assert invented_id.status_code == 422
        assert len((await _read_truth(admin))[2]) == len(baseline[2]) + 4

        # Previous valid schedule remains representable under NULL geography.
        async with AsyncSession(admin) as db:
            scheduled = await db.get(Zone, int(q_next.json()["zone_id"]))
            assert scheduled.governorate_id is None
            assert scheduled.interval_days == 7
            assert scheduled.start_date.isoformat() == "2026-11-20"


async def test_cross_company_authorization_archive_restore_and_legacy_geo_unmodified():
    async with _scene() as (http, admin, identities, auth):
        owner_a, owner_b, ordinary = auth
        a_id, b_id = identities[0][0], identities[1][0]
        baseline_catalog = (await _read_truth(admin))[:2]
        async with AsyncSession(admin, expire_on_commit=False) as db:
            country = Country(name="Z1039 Historical " + uuid4().hex[:8])
            db.add(country)
            await db.flush()
            gov = Governorate(name="Z1039 Historical Governorate", country_id=country.id)
            db.add(gov)
            await db.flush()
            historic = Zone(company_id=a_id, name="Historical Zone", governorate_id=gov.id)
            db.add(historic)
            await db.commit()
            historic_id, historic_gov_id = historic.id, gov.id

        response = await http.post("/dispatch/zones", headers=owner_a, json={
            "name": "1039 Archive & Restore Region",
        })
        assert response.status_code == 201, response.text
        zid = int(response.json()["zone_id"])
        shop = await http.post("/dispatch/shops", headers=owner_a, json={
            "name": "Z1039 Provenance Shop", "zoneId": zid,
            "phone": "Z1039-" + uuid4().hex[:12],
            "initialDebt": "0", "maxDebtLimit": "0",
            "request_id": str(uuid4()),
        })
        assert shop.status_code == 201, shop.text
        shop_id = int(shop.json()["shop_id"])

        # Reject cross-company ID probing, including archive/restore.
        for method, path, body in (
            ("PUT", f"/dispatch/zones/{zid}", {"name":"Wrong tenant"}),
            ("DELETE", f"/dispatch/zones/{zid}", None),
            ("PUT", f"/dispatch/zones/{zid}/restore", {"mode":"zone_only"}),
        ):
            denied = await http.request(method, path, json=body, headers=owner_b)
            assert denied.status_code in (403, 404), (method, denied.text)

        # Unprivileged BO must not acquire dispatch.manage from membership.
        for method, path, body in (
            ("POST", "/dispatch/zones", {"name": "No permission"}),
            ("PUT", f"/dispatch/zones/{zid}", {"name": "No permission"}),
            ("DELETE", f"/dispatch/zones/{zid}", None),
            ("PUT", f"/dispatch/zones/{zid}/restore", {"mode": "zone_only"}),
        ):
            denied = await http.request(method, path, json=body, headers=ordinary)
            assert denied.status_code == 403, (method, denied.text)
        anonymous = await http.post("/dispatch/zones", json={"name":"Anonymous"})
        assert anonymous.status_code == 401

        archive = await http.delete(f"/dispatch/zones/{zid}", headers=owner_a)
        assert archive.status_code == 200, archive.text
        async with AsyncSession(admin) as db:
            archived_shop = await db.get(Shop, shop_id)
            assert archived_shop.is_archived is True
            assert archived_shop.archived_due_to_zone_id == zid
        archived_duplicate = await http.post("/dispatch/zones", headers=owner_a, json={
            "name": "1039 Archive & Restore Region",
        })
        assert archived_duplicate.status_code == 409, archived_duplicate.text
        assert "الأرشيف" in archived_duplicate.text
        restore = await http.put(f"/dispatch/zones/{zid}/restore", headers=owner_a,
                                 json={"mode": "shops_archived_by_same_zone"})
        assert restore.status_code == 200, restore.text
        assert restore.json()["restored_shops"] == 1
        rename = await http.put(f"/dispatch/zones/{zid}", headers=owner_a, json={
            "name": "1039 Renamed Region",
        })
        assert rename.status_code == 200, rename.text

        async with AsyncSession(admin) as db:
            archived_zone = await db.get(Zone, zid)
            history = await db.get(Zone, historic_id)
            assert archived_zone.company_id == a_id
            assert archived_zone.is_active is True
            assert archived_zone.governorate_id is None
            assert archived_zone.name == "1039 Renamed Region"
            restored_shop = await db.get(Shop, shop_id)
            assert restored_shop.is_archived is False
            assert restored_shop.archived_due_to_zone_id is None
            assert restored_shop.zone_id == zid
            assert history.company_id == a_id
            assert history.governorate_id == historic_gov_id
            assert history.name == "Historical Zone"
            assert history.is_active is True
        assert (await _read_truth(admin))[0:2] == (
            baseline_catalog[0] + 1, baseline_catalog[1] + 1,
        )


async def test_frozen_zone_model_and_request_represent_no_geography_without_inference():
    assert Zone.__table__.c.governorate_id.nullable
    assert "governorate_id" not in AddZoneRequest.model_fields
    assert "country_id" not in AddZoneRequest.model_fields
    assert any(index.name == "idx_uq_zone_company_name_null_gov"
               and index.unique for index in Zone.__table__.indexes)
