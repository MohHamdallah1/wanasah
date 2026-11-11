"""D14 browser *fixture only*: real PG16 route and independent DASHBOARD/FIELD actors.

Run with pytest in isolated disposable D06-compatible DB. Commands only change
synthetic backoffice role assignments between actual Playwright browser events.
No mock JWT, API overrides, or production changes.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from domains.identity.models import CompanyPrincipal
from models import Company, Shop, UserRole, Zone
from tests.canonical_actor_fixtures import seed_ordinary_backoffice_fixture
from tests.test_dispatch_d06_secure_shop_reads_postgres import (
    _location_read, _second_zone_shops,
)
from tests.test_dispatch_route_launch_d07_postgres import _prepared_route
from tests.test_dispatch_shop_finance_edit_v1_postgres import (
    _grant_company_dispatch_capability, _owner, _real_http, _token,
)
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401

STATE = Path(os.environ.get("WANASAH_DISPATCH_D14_BROWSER_STATE",
                            "/tmp/dispatch-d14-browser-private.json"))
READER_PASSWORD = "D14SyntheticCompanyReader123"
FIELD_PASSWORD = "SyntheticFixture123"
OWNER_PASSWORD = "NoLotSyntheticFixture123"

pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_DISPATCH_D14_BROWSER_GATE") != "1",
                       reason="Run only in isolated D14 PostgreSQL16 browser gate"),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _username(db, principal_id):
    value = await db.scalar(
        select(CompanyPrincipal.username).where(CompanyPrincipal.id == principal_id)
    )
    assert value
    return str(value)


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_seed_actual_authorized_shops_for_chromium(pg):
    assert not STATE.exists(), "Expected a fresh isolated D14 fixture"
    home, foreign = pg.tenants
    _operation, route_request, vehicle_location = await _prepared_route(pg, home)
    async with pg.session() as db:
        assigned = await db.scalar(select(Shop).where(
            Shop.company_id == home.company_id, Shop.zone_id == route_request["zone_id"],
        ))
        assert assigned is not None
        # Synthetic opening balance makes 181.125 visibly different from a
        # redacted/unknown value. Only fixture state is changed here.
        assigned.current_balance = Decimal("181.125")
        assigned.max_debt_limit = Decimal("680.375")
        assigned_id, assigned_name = int(assigned.id), assigned.name
        zone_name = await db.scalar(select(Zone.name).where(Zone.id == assigned.zone_id))
        await db.commit()
    async with pg.session() as db:
        reader = await seed_ordinary_backoffice_fixture(
            db, home.company_id, password=READER_PASSWORD,
        )
        await db.commit()

    limited_scope_role = await _location_read(
        pg, home, warehouse=home.location_id, vehicle_custody=vehicle_location,
    )
    await _grant_company_dispatch_capability(
        pg, home, reader, "dispatch.read",
    )
    company_finance_role = await _grant_company_dispatch_capability(
        pg, home, reader, "shop.financial.read",
    )
    limited_finance_role = await _grant_company_dispatch_capability(
        pg, home, home.ordinary, "shop.financial.read",
    )

    async with pg.session() as db:
        await db.execute(delete(UserRole).where(
            UserRole.company_id == home.company_id,
            UserRole.role_id.in_((company_finance_role, limited_finance_role)),
        ))
        await db.commit()

    async with _real_http() as client:
        owner_headers = await _owner(client, pg, home)
        limited_headers = await _token(
            client, pg, home, home.ordinary, "SyntheticFixture123",
        )
        reader_headers = await _token(client, pg, home, reader, READER_PASSWORD)
        launch = await client.post("/dispatch/route", json=route_request, headers=owner_headers)
        assert launch.status_code == 201, launch.text
        # D06 exact fixture rule: Shops created AFTER launch have no active Visit.
        second_zone, unassigned, a2 = await _second_zone_shops(
            pg, home, route_request["zone_id"],
        )
        assert (await client.get("/dispatch/shops", headers=owner_headers)).status_code == 200
        limited = await client.get("/dispatch/shops", headers=limited_headers)
        assert limited.status_code == 200
        limited_rows = limited.json()
        assert {str(r["id"]) for r in limited_rows} == {str(assigned_id)}
        assert limited_rows[0]["initialDebt"] is None
        company_rows = await client.get("/dispatch/shops", headers=reader_headers)
        assert company_rows.status_code == 200
        assert {str(assigned_id), str(unassigned), str(a2)} <= {
            str(r["id"]) for r in company_rows.json()
        }
        assert all(r["financeRedacted"] and r["initialDebt"] is None
                   for r in company_rows.json())

    # Tenant B identity must be read only under Tenant B's RLS context.
    async with pg.session(1) as foreign_db:
        foreign_code = await foreign_db.scalar(select(Company.company_code).where(
            Company.id == foreign.company_id,
        ))
        foreign_username = await _username(foreign_db, foreign.owner.context.principal_id)
    async with pg.session() as db:
        a2_name = await db.scalar(select(Shop.name).where(Shop.id == a2))
        unassigned_name = await db.scalar(select(Shop.name).where(Shop.id == unassigned))
        a2_zone_name = await db.scalar(select(Zone.name).where(Zone.id == second_zone))
        code = await db.scalar(select(Company.company_code).where(
            Company.id == home.company_id,
        ))
        field_username = await db.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.company_id == home.company_id,
            CompanyPrincipal.principal_type == "FIELD_REPRESENTATIVE",
        ))
        assert field_username
        payload = {
            "companyId": int(home.company_id),
            "shops": {
                "assigned": {"id": assigned_id, "name": assigned_name, "balance": "181.125"},
                "unassigned": {"id": unassigned, "name": unassigned_name},
                "a2": {"id": a2, "name": a2_name, "balance": "901.125"},
            },
            "zones": {"a1": zone_name, "a2": a2_zone_name},
            "roles": {
                "reader": {"driver": reader.driver_id, "finance": company_finance_role},
                "limited": {"driver": home.ordinary.driver_id,
                            "finance": limited_finance_role, "warehouse": limited_scope_role},
            },
            "credentials": {
                "owner": {"code": code, "username": await _username(
                    db, home.owner.context.principal_id), "password": OWNER_PASSWORD},
                "reader": {"code": code, "username": await _username(
                    db, reader.context.principal_id), "password": READER_PASSWORD},
                "limited": {"code": code, "username": await _username(
                    db, home.ordinary.context.principal_id), "password": "SyntheticFixture123"},
                "foreign": {"code": foreign_code, "username": foreign_username,
                            "password": OWNER_PASSWORD},
                "field": {"code": code, "username": field_username,
                          "password": FIELD_PASSWORD},
            },
        }
    STATE.write_text(json.dumps(payload), encoding="utf-8")
    STATE.chmod(0o600)
    print("D14_BROWSER_SEED=PASS: route, three distinct Shops, "
          "Owner, company-reader, A1-reader, foreign Owner and FIELD identities")


async def _toggle(role_name: str, enable: bool):
    if not STATE.is_file():
        raise RuntimeError("Cannot alter permissions without seeded disposable state")
    data = json.loads(STATE.read_text())
    if role_name not in ("reader", "limited"):
        raise ValueError("Only two known synthetic Backoffice finance roles are permitted")
    role = data["roles"][role_name]
    engine = create_async_engine(os.environ["DATABASE_URL_MIGRATION"])
    try:
        async with AsyncSession(engine) as db:
            await db.execute(text("SELECT set_config('app.current_tenant',:c,true)"),
                             {"c": str(data["companyId"])})
            await db.execute(delete(UserRole).where(
                UserRole.company_id == data["companyId"],
                UserRole.role_id == role["finance"],
                UserRole.driver_id == role["driver"],
            ))
            if enable:
                db.add(UserRole(
                    company_id=data["companyId"],
                    driver_id=role["driver"], role_id=role["finance"],
                ))
            await db.commit()
    finally:
        await engine.dispose()
    print("D14_SYNTHETIC_FINANCE_ROLE_UPDATE=PASS", role_name, "enabled" if enable else "denied")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "reset":
        asyncio.run(_toggle("reader", False))
        asyncio.run(_toggle("limited", False))
    elif len(sys.argv) == 3 and sys.argv[1] in ("reader", "limited") and sys.argv[2] in ("on", "off"):
        asyncio.run(_toggle(sys.argv[1], sys.argv[2] == "on"))
    else:
        raise SystemExit("Usage: python -m tests.test_dispatch_d14_browser_fixture reset|reader on|off|limited on|off")
