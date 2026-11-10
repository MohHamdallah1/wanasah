"""D12 first-company Dispatch read benchmark. Disposable PG16 only; never production."""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4
from statistics import median
from time import perf_counter

import httpx
import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import engine as runtime_engine
from domains.identity.models import CompanyPrincipal
from main import app
from domains.vehicles.contracts import CreateVehicleCommand
from domains.vehicles.management import create_vehicle
from models import Company, DispatchRoute, Shop, ShortageRequest, Zone
from tests.test_inbound_no_lot_frozen_postgres import checked_urls, pg  # noqa: F401

pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_DISPATCH_D12_PG_GATE") != "1",
                       reason="Disposable D12 restricted PostgreSQL16 only"),
    pytest.mark.asyncio(loop_scope="function"),
]

STATE = Path(os.getenv("WANASAH_DISPATCH_D12_STATE", "/tmp/dispatch-d12-scale.json"))
RESULTS = Path(os.getenv("WANASAH_DISPATCH_D12_RESULTS", "/tmp/dispatch-d12-results.json"))
SHOP_COUNT, ROUTE_COUNT, SHORTAGE_COUNT = 1000, 100, 300


def percentile(samples, percentile_value=95):
    ordered = sorted(samples)
    return round(ordered[max(0, min(len(ordered) - 1,
                                     int((len(ordered) - 1) * percentile_value / 100)))], 2)


async def credentials(gate, tenant):
    async with AsyncSession(gate.admin_engine) as db:
        code = await db.scalar(select(Company.company_code).where(Company.id == tenant.company_id))
        username = await db.scalar(select(CompanyPrincipal.username).where(
            CompanyPrincipal.id == tenant.owner.context.principal_id))
    return {"code": code, "username": username, "password": "NoLotSyntheticFixture123"}


async def login(client, identity):
    response = await client.post("/login", json={
        "company_code": identity["code"],
        "username": identity["username"],
        "password": identity["password"],
    })
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_measured_first_company_dispatch_reads(pg):
    assert not STATE.exists() and not RESULTS.exists(), "D12 fixture must be disposable and fresh"
    runtime, _ = checked_urls()
    assert (runtime.drivername, runtime.host, runtime.port, runtime.database, runtime.username) == (
        runtime_engine.url.drivername, runtime_engine.url.host, runtime_engine.url.port,
        runtime_engine.url.database, runtime_engine.url.username)
    assert not app.dependency_overrides
    company = pg.tenants[0]
    foreign = pg.tenants[1]
    zone_ids = []
    vehicle_ids = []
    async with pg.session() as db:
        for index in range(ROUTE_COUNT):
            zone = Zone(company_id=company.company_id,
                        name=f"D12 synthetic zone {index:03d}", is_active=True)
            db.add(zone)
            await db.flush()
            zone_ids.append(int(zone.id))
        db.add_all([
            Shop(company_id=company.company_id, zone_id=zone_ids[i % ROUTE_COUNT],
                 name=f"D12 synthetic shop {i:04d}", sequence=i, is_active=True,
                 is_archived=False, current_balance=0, max_debt_limit=0)
            for i in range(SHOP_COUNT)
        ])
        await db.flush()
        shops = (await db.scalars(select(Shop.id).where(
            Shop.company_id == company.company_id,
            Shop.name.like("D12 synthetic shop %")).order_by(Shop.id))).all()
        assert len(shops) == SHOP_COUNT
        for index in range(ROUTE_COUNT):
            vehicle = await create_vehicle(
                db, company_id=company.company_id,
                actor_id=company.owner.operational_driver.id,
                command=CreateVehicleCommand(
                    request_id=str(uuid4()),
                    plate_number=f"D12-{index:04d}",
                    vehicle_type="Van", maintenance_status="Active"))
            vehicle_ids.append(int(vehicle["id"]))
        db.add_all([
            DispatchRoute(company_id=company.company_id, zone_id=z,
                          vehicle_id=vehicle_ids[index],
                          source_location_id=company.location_id,
                          status="waiting")
            for index, z in enumerate(zone_ids)
        ])
        db.add_all([
            ShortageRequest(company_id=company.company_id,
                           zone_id=zone_ids[i % ROUTE_COUNT],
                           shop_id=shops[i], product_variant_id=company.variant_id,
                           quantity=1 + i % 4, status="pending")
            for i in range(SHORTAGE_COUNT)
        ])
        await db.commit()

    identities = await credentials(pg, company), await credentials(pg, foreign)
    samples = {}
    query_count = 0

    def before_cursor(*_args):
        nonlocal query_count
        query_count += 1

    event.listen(runtime_engine.sync_engine, "before_cursor_execute", before_cursor)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://d12-disposable-pg16.test", timeout=60,
        ) as client:
            owner = await login(client, identities[0])
            outsider = await login(client, identities[1])
            for path, minimum in (
                ("/dispatch/init", ROUTE_COUNT),
                ("/dispatch/shops", SHOP_COUNT),
                ("/dispatch/active_routes", ROUTE_COUNT),
                ("/dispatch/shortages", SHORTAGE_COUNT),
            ):
                times, queries, bytes_read = [], [], []
                for index in range(13):
                    query_count = 0
                    started = perf_counter()
                    response = await client.get(path, headers=owner)
                    elapsed = (perf_counter() - started) * 1000
                    assert response.status_code == 200, (path, response.status_code, response.text[:300])
                    payload = response.json()
                    assert isinstance(payload, list if path != "/dispatch/init" else dict)
                    if path == "/dispatch/init":
                        assert len(payload["zones"]) >= minimum
                        assert "products" not in payload
                    else:
                        assert len(payload) >= minimum, (path, len(payload), minimum)
                    if index >= 3:
                        times.append(round(elapsed, 2))
                        queries.append(query_count)
                        bytes_read.append(len(response.content))
                assert max(queries) <= 30, (path, queries)
                assert len(set(bytes_read)) == 1
                samples[path] = {
                    "rows": minimum, "bytes": bytes_read[0], "sql_min": min(queries),
                    "sql_max": max(queries), "p50_ms": round(median(times), 2),
                    "p95_ms": percentile(times), "requests": len(times),
                }
                foreign_response = await client.get(path, headers=outsider)
                assert foreign_response.status_code == 200, (path, foreign_response.text[:300])
                assert "D12 synthetic" not in foreign_response.text, "Cross-company read leaked D12 data"
    finally:
        event.remove(runtime_engine.sync_engine, "before_cursor_execute", before_cursor)
        await runtime_engine.dispose()
    STATE.write_text(json.dumps({
        "credentials": identities[0], "companyId": company.company_id,
        "shops": SHOP_COUNT, "routes": ROUTE_COUNT, "shortages": SHORTAGE_COUNT,
    }), encoding="utf-8")
    RESULTS.write_text(json.dumps({
        "database": "PostgreSQL16 restricted NOBYPASSRLS", "fixture": {
            "shops": SHOP_COUNT, "routes": ROUTE_COUNT, "pendingShortages": SHORTAGE_COUNT,
        }, "reads": samples,
    }, indent=2), encoding="utf-8")
    print("D12_AUTHORIZED_PG16_READ_METRICS=" + RESULTS.read_text(), flush=True)
