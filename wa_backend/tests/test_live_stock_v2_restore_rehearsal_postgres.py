"""Real disposable PostgreSQL16 backup/restore rehearsal for Live Stock v2.

This is an opt-in recovery acceptance only. It reuses the canonical #700
v1->v2 rebuild authority and never writes InventoryBalance, movements, costing,
RLS, authorization, or READY state outside those existing test/canonical seams.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal as D
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import pytest
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api import dispatch
from context import tenant_context
from database import engine as http_runtime_engine
from domains.inventory_vehicle_load.service import mutate_vehicle_load
from domains.live_stock_projection import service as projection
from main import app
from models import (
    InventoryBalance,
    InventoryCostEvent,
    InventoryCostLayer,
    InventoryCostState,
    InventoryLiveStockCompanySummary,
    InventoryLiveStockProjection,
    InventoryLiveStockWarehouseSummary,
    InventoryLocation,
    InventoryMovement,
    OperationIdempotency,
    ProductBatch,
)
from schemas import DispatchRouteRequest
from services import apply_inventory_movement, ensure_system_transit_location
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_live_stock_v1_r3_physical_location_truth_postgres import (
    _enable_second_warehouse,
    _grant_restricted_reader,
)
from tests.test_live_stock_v1_route_sale_unload_postgres import (
    _seed_commercial_master,
    _seed_mobile_uom_and_field,
)
from tests.test_live_stock_v2_rollout_readiness_postgres import (
    _accounts,
    _legacy_v1,
    _login,
    _read,
    _vehicle,
)

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_LIVE_STOCK_V2_RESTORE_PG_GATE") != "1",
        reason="Requires the dedicated disposable PostgreSQL16 restore rehearsal",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]

SOURCE_DB = "wanasah_no_lot_contract_test"
RESTORE_DB = "wanasah_live_stock_v2_restore_test"
MANIFEST_PATH = Path("/tmp/live-stock-v2-restore-manifest.json")
AUTHORITY_MODELS = {
    "inventory_locations": InventoryLocation,
    "product_batches": ProductBatch,
    "inventory_balances": InventoryBalance,
    "inventory_movements": InventoryMovement,
    "inventory_cost_events": InventoryCostEvent,
    "inventory_cost_layers": InventoryCostLayer,
    "inventory_cost_states": InventoryCostState,
    "operation_idempotency": OperationIdempotency,
}
PROJECTION_MODELS = {
    "projection": InventoryLiveStockProjection,
    "company_summary": InventoryLiveStockCompanySummary,
    "warehouse_summary": InventoryLiveStockWarehouseSummary,
}


def _strict_urls(expected_database: str):
    runtime = make_url(os.environ["DATABASE_URL"])
    admin = make_url(os.environ["DATABASE_URL_MIGRATION"])
    for url in (runtime, admin):
        if (
            url.host != "127.0.0.1"
            or url.port != 55439
            or url.database != expected_database
            or url.drivername != "postgresql+asyncpg"
        ):
            raise RuntimeError("Refusing database outside the disposable restore rehearsal")
    if runtime.username != "wanasah_app" or admin.username == runtime.username:
        raise RuntimeError("Restore rehearsal requires restricted runtime and distinct admin roles")
    return runtime, admin


def _normalize(value: Any):
    if isinstance(value, D):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


async def _model_digest(db: AsyncSession, model, company_id: int):
    table = model.__table__
    columns = list(table.columns)
    statement = select(*columns).where(table.c.company_id == company_id)
    primary = list(table.primary_key.columns)
    if primary:
        statement = statement.order_by(*primary)
    rows = (await db.execute(statement)).mappings().all()
    payload = [
        {column.name: _normalize(row[column.name]) for column in columns}
        for row in rows
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return {"count": len(payload), "sha256": hashlib.sha256(encoded).hexdigest()}


async def _digests(db: AsyncSession, company_id: int, models):
    return {
        name: await _model_digest(db, model, company_id)
        for name, model in models.items()
    }


async def _physical_snapshot(db: AsyncSession, company_id: int, variant_id: int):
    rows = (await db.execute(
        select(
            InventoryLocation.location_type,
            InventoryLocation.id,
            func.sum(InventoryBalance.on_hand_quantity),
        )
        .join(InventoryLocation, InventoryLocation.id == InventoryBalance.location_id)
        .where(
            InventoryBalance.company_id == company_id,
            InventoryLocation.company_id == company_id,
            InventoryBalance.product_variant_id == variant_id,
        )
        .group_by(InventoryLocation.location_type, InventoryLocation.id)
        .order_by(InventoryLocation.location_type, InventoryLocation.id)
    )).all()
    return {
        f"{kind}:{int(location_id)}": format(D(quantity), "f")
        for kind, location_id, quantity in rows
    }


async def _projection_state(db: AsyncSession, company_id: int):
    company = (await db.execute(
        select(
            InventoryLiveStockCompanySummary.projection_version,
            InventoryLiveStockCompanySummary.projection_state,
        ).where(InventoryLiveStockCompanySummary.company_id == company_id)
    )).one()
    warehouses = (await db.execute(
        select(
            InventoryLiveStockWarehouseSummary.warehouse_location_id,
            InventoryLiveStockWarehouseSummary.projection_version,
            InventoryLiveStockWarehouseSummary.projection_state,
        )
        .where(InventoryLiveStockWarehouseSummary.company_id == company_id)
        .order_by(InventoryLiveStockWarehouseSummary.warehouse_location_id)
    )).all()
    return {
        "company": {"version": int(company[0]), "state": str(company[1])},
        "warehouses": [
            {"location_id": int(row[0]), "version": int(row[1]), "state": str(row[2])}
            for row in warehouses
        ],
    }


@asynccontextmanager
async def _tenant_session(runtime_engine, company_id: int):
    token = tenant_context.set(company_id)
    try:
        async with runtime_engine.connect() as connection:
            db = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                await db.execute(
                    text("SELECT set_config('app.current_tenant', :tenant, false)"),
                    {"tenant": str(company_id)},
                )
                await db.execute(text("SET statement_timeout='15000ms'"))
                yield db
            finally:
                await db.close()
    finally:
        tenant_context.reset(token)


def _manifest():
    configured = Path(os.environ.get("WANASAH_LIVE_STOCK_V2_RESTORE_MANIFEST", ""))
    if configured != MANIFEST_PATH:
        raise RuntimeError(f"Manifest path must be {MANIFEST_PATH}")
    return configured


async def _seed_source(pg_gate):
    tenant, foreign = pg_gate.tenants
    w1, w2 = int(tenant.location_id), int(tenant.other_location_id)
    await _enable_second_warehouse(pg_gate, tenant)
    field = await _seed_mobile_uom_and_field(pg_gate, tenant)
    zone, _ = await _seed_commercial_master(pg_gate, tenant, field)

    w1_lot = "V2-RESTORE-W1-" + uuid4().hex[:9]
    w2_lot = "V2-RESTORE-W2-" + uuid4().hex[:9]
    async with pg_gate.session() as db:
        assert await pg_gate.post(
            db, pg_gate.request(lot=w1_lot, quantity="100", cost="2")
        ) == {"message": "INBOUND_POSTED"}
    async with pg_gate.session() as db:
        assert await pg_gate.post(
            db,
            pg_gate.request(lot=w2_lot, quantity="100", cost="4").model_copy(
                update={"location_id": w2}
            ),
        ) == {"message": "INBOUND_POSTED"}
    async with pg_gate.session(1) as db:
        assert await pg_gate.post(
            db,
            pg_gate.request(
                party=1,
                lot="V2-RESTORE-OTHER-" + uuid4().hex[:9],
                quantity="11",
                cost="9",
            ),
            party=1,
        ) == {"message": "INBOUND_POSTED"}

    car1, loc1 = await _vehicle(pg_gate, tenant)
    car2, loc2 = await _vehicle(pg_gate, tenant)
    await _grant_restricted_reader(pg_gate, tenant, vehicle_location_id=loc1)
    for vehicle_id, warehouse_id, quantity in (
        (car1, w2, "30"),
        (car1, w1, "5"),
        (car2, w2, "7"),
    ):
        async with pg_gate.session() as db:
            result = await mutate_vehicle_load(
                db,
                access=tenant.owner.access(db),
                actor_id=tenant.owner.driver_id,
                vehicle_id=vehicle_id,
                warehouse_id=warehouse_id,
                direction="ADD",
                request_id=uuid4(),
                items=[{"product_variant_id": tenant.variant_id, "quantity": D(quantity)}],
            )
            assert result["movement_count"] >= 1

    async with pg_gate.session() as db:
        transit = await ensure_system_transit_location(db, tenant.company_id)
        transit_id = int(transit.id)
        batch_id = await db.scalar(
            select(ProductBatch.id).where(
                ProductBatch.company_id == tenant.company_id,
                ProductBatch.product_variant_id == tenant.variant_id,
                ProductBatch.batch_number == w1_lot,
            )
        )
        assert batch_id
        await apply_inventory_movement(
            db,
            company_id=tenant.company_id,
            performed_by=tenant.owner.driver_id,
            product_variant_id=tenant.variant_id,
            batch_id=int(batch_id),
            quantity=D("4"),
            movement_kind="PHYSICAL",
            reference_type="V2_RESTORE_REHEARSAL_TRANSIT",
            reference_id="V2-RESTORE-" + uuid4().hex[:12],
            idempotency_key="V2-RESTORE-" + uuid4().hex,
            source_location_id=w1,
            destination_location_id=transit_id,
            source_stock_status="AVAILABLE",
            destination_stock_status="AVAILABLE",
        )
        await db.commit()

    async with pg_gate.session() as db:
        launched = await dispatch.dispatch_route(
            DispatchRouteRequest(
                zone_id=zone,
                driver_id=field.driver.id,
                vehicle_id=car1,
                source_location_id=w1,
                inventory_base={str(tenant.variant_id): D("35")},
                expected_inventory_base={str(tenant.variant_id): D("35")},
            ),
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )
        assert int(launched["route_id"]) > 0

    async with pg_gate.session() as db:
        physical = await _physical_snapshot(db, tenant.company_id, tenant.variant_id)
    assert physical == {
        f"WAREHOUSE:{w1}": "91",
        f"WAREHOUSE:{w2}": "63",
        f"VEHICLE:{loc1}": "35",
        f"VEHICLE:{loc2}": "7",
        f"IN_TRANSIT:{transit_id}": "4",
    }

    await _legacy_v1(pg_gate, tenant, w1)
    identities = await _accounts(pg_gate)
    return tenant, foreign, identities, {
        "w1": w1,
        "w2": w2,
        "vehicle1_location": loc1,
        "vehicle2_location": loc2,
        "transit_location": transit_id,
        "physical": physical,
    }


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_prepare_backup_source(pg):
    _strict_urls(SOURCE_DB)
    tenant, foreign, identities, expected = await _seed_source(pg)

    async with pg.session() as db:
        authority = await _digests(db, tenant.company_id, AUTHORITY_MODELS)
        projection_digest = await _digests(db, tenant.company_id, PROJECTION_MODELS)
        projection_state = await _projection_state(db, tenant.company_id)
    async with pg.session(1) as db:
        foreign_authority = await _digests(db, foreign.company_id, AUTHORITY_MODELS)
        foreign_physical = await _physical_snapshot(db, foreign.company_id, foreign.variant_id)

    assert projection_state["company"] == {"version": 1, "state": "READY"}
    assert all(item["version"] == 1 and item["state"] == "READY"
               for item in projection_state["warehouses"])

    assert not app.dependency_overrides
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://v2-restore-source.test",
    ) as client:
        owner = await _login(client, identities[0][0], identities[0][1], "NoLotSyntheticFixture123")
        reader = await _login(client, identities[0][0], identities[0][2], "SyntheticFixture123")
        foreign_owner = await _login(
            client, identities[1][0], identities[1][1], "NoLotSyntheticFixture123"
        )
        for token in (owner, reader):
            for warehouse in (expected["w1"], expected["w2"]):
                response = await _read(client, token, warehouse)
                assert response.status_code == 503, response.text
                assert response.json()["error"]["code"] == "LIVE_STOCK_PROJECTION_NOT_READY"
                assert response.headers.get("x-request-id")
                assert "items" not in response.json()
        assert (await _read(client, foreign_owner, foreign.location_id)).status_code == 200
        assert (await _read(client, foreign_owner, expected["w1"])).status_code == 404

    manifest = {
        "format": 1,
        "source_database": SOURCE_DB,
        "costing_method": pg.method,
        "tenant": {
            "company_id": tenant.company_id,
            "variant_id": tenant.variant_id,
            "company_code": identities[0][0],
            "owner_username": identities[0][1],
            "reader_username": identities[0][2],
            **expected,
        },
        "foreign": {
            "company_id": foreign.company_id,
            "variant_id": foreign.variant_id,
            "warehouse": int(foreign.location_id),
            "company_code": identities[1][0],
            "owner_username": identities[1][1],
            "physical": foreign_physical,
        },
        "authority": authority,
        "foreign_authority": foreign_authority,
        "projection": projection_digest,
        "projection_state": projection_state,
    }
    _manifest().write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
    await http_runtime_engine.dispose()


async def test_restored_backup_recovers_v1_to_v2_without_authoritative_replay():
    runtime_url, admin_url = _strict_urls(RESTORE_DB)
    runtime_engine = create_async_engine(runtime_url, poolclass=NullPool)
    admin_engine = create_async_engine(admin_url, poolclass=NullPool)
    manifest = json.loads(_manifest().read_text(encoding="utf-8"))
    tenant = manifest["tenant"]
    foreign = manifest["foreign"]
    company_id = int(tenant["company_id"])
    foreign_company_id = int(foreign["company_id"])
    w1, w2 = int(tenant["w1"]), int(tenant["w2"])

    try:
        async with runtime_engine.connect() as connection:
            identity = (await connection.execute(text(
                "SELECT current_database(), current_user, inet_server_port(), "
                "r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname=current_user"
            ))).one()
            assert tuple(identity) == (RESTORE_DB, "wanasah_app", 55439, False, False)
            for table in (
                "inventory_balances",
                "inventory_movements",
                "inventory_cost_events",
                "inventory_cost_layers",
                "inventory_live_stock_projection",
            ):
                flags = (await connection.execute(text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE oid=to_regclass(:table)"
                ), {"table": table})).one()
                assert tuple(flags) == (True, True), f"Missing FORCE RLS after restore: {table}"

        config = AlembicConfig(str(Path(__file__).parents[1] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
        expected_heads = set(ScriptDirectory.from_config(config).get_heads())
        async with AsyncSession(admin_engine, expire_on_commit=False) as admin:
            restored_heads = set(
                (await admin.execute(text("SELECT version_num FROM alembic_version"))).scalars()
            )
            assert restored_heads == expected_heads

        async with _tenant_session(runtime_engine, company_id) as db:
            assert await _digests(db, company_id, AUTHORITY_MODELS) == manifest["authority"]
            assert await _digests(db, company_id, PROJECTION_MODELS) == manifest["projection"]
            assert await _projection_state(db, company_id) == manifest["projection_state"]
            assert await _physical_snapshot(
                db, company_id, int(tenant["variant_id"])
            ) == tenant["physical"]
            foreign_visible = int(await db.scalar(
                select(func.count()).select_from(InventoryBalance).where(
                    InventoryBalance.company_id == foreign_company_id
                )
            ) or 0)
            assert foreign_visible == 0

        async with _tenant_session(runtime_engine, foreign_company_id) as db:
            assert await _digests(
                db, foreign_company_id, AUTHORITY_MODELS
            ) == manifest["foreign_authority"]
            assert await _physical_snapshot(
                db, foreign_company_id, int(foreign["variant_id"])
            ) == foreign["physical"]

        assert not app.dependency_overrides
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://v2-restored-pg16.test",
        ) as client:
            owner = await _login(
                client, tenant["company_code"], tenant["owner_username"], "NoLotSyntheticFixture123"
            )
            reader = await _login(
                client, tenant["company_code"], tenant["reader_username"], "SyntheticFixture123"
            )
            foreign_owner = await _login(
                client,
                foreign["company_code"],
                foreign["owner_username"],
                "NoLotSyntheticFixture123",
            )
            for token in (owner, reader):
                for warehouse in (w1, w2):
                    denied = await _read(client, token, warehouse)
                    assert denied.status_code == 503, denied.text
                    assert denied.json()["error"]["code"] == "LIVE_STOCK_PROJECTION_NOT_READY"
                    assert denied.headers.get("x-request-id")
                    assert "items" not in denied.json()
            assert (await _read(client, foreign_owner, int(foreign["warehouse"]))).status_code == 200
            assert (await _read(client, foreign_owner, w1)).status_code == 404

            original = projection._rebuild_live_stock_warehouse_locked
            built = 0

            async def interrupt(*args, **kwargs):
                nonlocal built
                built += 1
                if built == 2:
                    raise RuntimeError("TEST_INJECTED_RESTORE_RECOVERY_INTERRUPTION")
                return await original(*args, **kwargs)

            with patch.object(projection, "_rebuild_live_stock_warehouse_locked", interrupt):
                async with _tenant_session(runtime_engine, company_id) as db:
                    with pytest.raises(RuntimeError, match="TEST_INJECTED_RESTORE"):
                        await projection.rebuild_live_stock_company(
                            db, company_id=company_id, batch_size=1
                        )
                    await db.rollback()
            assert built == 2

            async with _tenant_session(runtime_engine, company_id) as db:
                assert await _digests(db, company_id, PROJECTION_MODELS) == manifest["projection"]
                assert await _projection_state(db, company_id) == manifest["projection_state"]
                assert await _digests(db, company_id, AUTHORITY_MODELS) == manifest["authority"]
                assert await _physical_snapshot(
                    db, company_id, int(tenant["variant_id"])
                ) == tenant["physical"]
            assert (await _read(client, owner, w1)).status_code == 503

            async with _tenant_session(runtime_engine, company_id) as db:
                report = await projection.rebuild_live_stock_company(
                    db, company_id=company_id, batch_size=1
                )
                assert report.warehouse_count == 2
                assert report.candidate_keys >= 2
                for warehouse in (w1, w2):
                    await projection.assert_live_stock_projection_ready(
                        db,
                        company_id=company_id,
                        warehouse_location_id=warehouse,
                    )
                await db.commit()

            async with _tenant_session(runtime_engine, company_id) as db:
                rows = (await db.execute(
                    select(
                        InventoryLiveStockProjection.warehouse_location_id,
                        InventoryLiveStockProjection.warehouse_on_hand,
                        InventoryLiveStockProjection.vehicle_packs,
                        InventoryLiveStockProjection.has_vehicle_presence,
                    )
                    .where(
                        InventoryLiveStockProjection.company_id == company_id,
                        InventoryLiveStockProjection.product_variant_id == int(tenant["variant_id"]),
                    )
                    .order_by(InventoryLiveStockProjection.warehouse_location_id)
                )).all()
                assert [
                    (int(row[0]), D(row[1]), D(row[2]), bool(row[3])) for row in rows
                ] == [(w1, D("91"), D("0"), False), (w2, D("63"), D("0"), False)]
                state = await _projection_state(db, company_id)
                assert state["company"] == {"version": 2, "state": "READY"}
                assert all(item["version"] == 2 and item["state"] == "READY"
                           for item in state["warehouses"])
                assert await _digests(db, company_id, AUTHORITY_MODELS) == manifest["authority"]
                assert await _physical_snapshot(
                    db, company_id, int(tenant["variant_id"])
                ) == tenant["physical"]

            # Fresh post-recovery bearers must pass through normal auth + FORCE RLS.
            fresh_owner = await _login(
                client, tenant["company_code"], tenant["owner_username"], "NoLotSyntheticFixture123"
            )
            fresh_reader = await _login(
                client, tenant["company_code"], tenant["reader_username"], "SyntheticFixture123"
            )
            fresh_foreign = await _login(
                client,
                foreign["company_code"],
                foreign["owner_username"],
                "NoLotSyntheticFixture123",
            )
            for warehouse, expected in ((w1, D("91")), (w2, D("63"))):
                ready = await _read(client, fresh_owner, warehouse)
                assert ready.status_code == 200, ready.text
                item = next(
                    row for row in ready.json()["items"]
                    if row["id"] == int(tenant["variant_id"])
                )
                assert D(item["on_hand_quantity"]) == expected
                assert D(item["total_quantity"]) == expected
                assert item["total_quantity_scope"] == "WAREHOUSE_PHYSICAL"
                assert D(item["vehicle_quantity"]) == D("42")
                assert item["vehicle_quantity_scope"] == "COMPANY_WIDE"

                scoped = await _read(client, fresh_reader, warehouse)
                assert scoped.status_code == 200, scoped.text
                row = next(
                    value for value in scoped.json()["items"]
                    if value["id"] == int(tenant["variant_id"])
                )
                assert D(row["on_hand_quantity"]) == expected
                assert D(row["vehicle_quantity"]) == D("35")
                assert row["vehicle_quantity_scope"] == "AUTHORIZED_LOCATIONS"
                assert int(foreign["variant_id"]) not in {
                    value["id"] for value in ready.json()["items"]
                }

            assert (await _read(client, fresh_owner, int(foreign["warehouse"]))).status_code == 404
            assert (await _read(client, fresh_foreign, w1)).status_code == 404

            # A second canonical rebuild is a no-op and cannot replay movements/costs.
            async with _tenant_session(runtime_engine, company_id) as db:
                clean = await projection.rebuild_live_stock_company(
                    db, company_id=company_id, batch_size=1
                )
                assert clean.drifted_keys == 0
                assert clean.summary_repairs == 0
                await db.commit()
            async with _tenant_session(runtime_engine, company_id) as db:
                assert await _digests(db, company_id, AUTHORITY_MODELS) == manifest["authority"]
                assert await _physical_snapshot(
                    db, company_id, int(tenant["variant_id"])
                ) == tenant["physical"]
            async with _tenant_session(runtime_engine, foreign_company_id) as db:
                assert await _digests(
                    db, foreign_company_id, AUTHORITY_MODELS
                ) == manifest["foreign_authority"]
                assert await _physical_snapshot(
                    db, foreign_company_id, int(foreign["variant_id"])
                ) == foreign["physical"]
    finally:
        await runtime_engine.dispose()
        await admin_engine.dispose()
        await http_runtime_engine.dispose()
