"""Real PostgreSQL acceptance for PR #317 strict Vehicle custody projections.

Manual gate (from wa_backend):
  WANASAH_VEHICLE_DISPATCH_ACCESS_DB_GATE=1 python tests/test_vehicle_dispatch_access_postgres_acceptance.py

The gate creates and drops its own schema. It never reads development rows.
"""
from __future__ import annotations

import asyncio
import os
import traceback
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.warehouse import live_stock as live_stock_api
from dispatch_access import require_any_location, require_vehicle, route_filter, vehicle_filter
from domains.live_stock_projection import service as projection_service
from domains.vehicles.contracts import CreateVehicleCommand
from domains.vehicles.management import create_vehicle
from models import (
    Base,
    Company,
    DispatchRoute,
    InventoryBalance,
    InventoryLiveStockProjection,
    InventoryLocation,
    Product,
    ProductBatch,
    ProductVariant,
    UOM,
    Vehicle,
    Zone,
    utc_now,
)
from tests.canonical_actor_fixtures import (
    seed_company_owner_fixture,
    seed_ordinary_backoffice_fixture,
)

GATE_ENV = "WANASAH_VEHICLE_DISPATCH_ACCESS_DB_GATE"
SCHEMA_PREFIX = "vehicle_dispatch_access_accept_"
EVIDENCE: dict[str, object] = {}


async def _count(db: AsyncSession, model, *criteria) -> int:
    return int(await db.scalar(select(func.count()).select_from(model).where(*criteria)) or 0)


async def _create_vehicle(db: AsyncSession, owner, company_id: int, plate: str) -> tuple[int, int]:
    payload = await create_vehicle(
        db,
        company_id=company_id,
        actor_id=owner.driver_id,
        command=CreateVehicleCommand(
            request_id=str(uuid4()),
            plate_number=plate,
            vehicle_type="Van",
            maintenance_status="Active",
        ),
    )
    vehicle_id = int(payload["id"])
    custody = (
        await db.execute(
            select(InventoryLocation).where(
                InventoryLocation.company_id == company_id,
                InventoryLocation.vehicle_id == vehicle_id,
                InventoryLocation.location_type == "VEHICLE",
            )
        )
    ).scalars().all()
    assert len(custody) == 1
    return vehicle_id, int(custody[0].id)


async def _add_historical_custody(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
    suffix: str,
    active: bool = False,
) -> int:
    row = InventoryLocation(
        company_id=company_id,
        name=f"Historical custody {suffix}",
        code=f"VH-{suffix}-{uuid4().hex[:8]}",
        location_type="VEHICLE",
        vehicle_id=vehicle_id,
        is_active=active,
        version=1,
    )
    db.add(row)
    await db.flush()
    return int(row.id)


async def _expect_vehicle_rejected(access, vehicle_id: int) -> int:
    try:
        await require_vehicle(access, "dispatch.read", vehicle_id)
    except HTTPException as exc:
        assert exc.status_code in {403, 404, 409}
        return int(exc.status_code)
    raise AssertionError(f"require_vehicle authorized noncanonical vehicle {vehicle_id}")


async def _grant_role(
    db: AsyncSession,
    *,
    company_id: int,
    driver_id: int,
    codes: tuple[str, ...],
    company_level: bool = False,
    location_ids: tuple[int, ...] = (),
) -> None:
    role_id = (
        await db.execute(
            text("INSERT INTO roles(company_id,name,is_system_role) VALUES (:c,:n,false) RETURNING id"),
            {"c": company_id, "n": f"accept-{uuid4().hex[:12]}"},
        )
    ).scalar_one()
    for code in codes:
        permission_id = (
            await db.execute(
                text(
                    "INSERT INTO permissions(code) VALUES (:code) "
                    "ON CONFLICT(code) DO UPDATE SET code=EXCLUDED.code RETURNING id"
                ),
                {"code": code},
            )
        ).scalar_one()
        await db.execute(
            text(
                "INSERT INTO role_permissions(company_id,role_id,permission_id) "
                "VALUES (:c,:r,:p)"
            ),
            {"c": company_id, "r": role_id, "p": permission_id},
        )
    if company_level:
        await db.execute(
            text("INSERT INTO user_roles(company_id,driver_id,role_id) VALUES (:c,:d,:r)"),
            {"c": company_id, "d": driver_id, "r": role_id},
        )
    for location_id in location_ids:
        await db.execute(
            text(
                "INSERT INTO user_location_access(company_id,driver_id,location_id,role_id) "
                "VALUES (:c,:d,:l,:r)"
            ),
            {"c": company_id, "d": driver_id, "l": location_id, "r": role_id},
        )
    await db.flush()


async def _new_access(
    gate,
    *,
    codes: tuple[str, ...],
    company_level: bool = False,
    location_ids: tuple[int, ...] = (),
):
    db = gate["db"]
    ordinary = await seed_ordinary_backoffice_fixture(db, gate["company_id"])
    await _grant_role(
        db,
        company_id=gate["company_id"],
        driver_id=ordinary.driver_id,
        codes=codes,
        company_level=company_level,
        location_ids=location_ids,
    )
    await db.commit()
    return ordinary.access(db)


async def _seed_balance(
    gate,
    *,
    location_id: int,
    variant_id: int,
    quantity: int,
    suffix: str,
) -> int:
    db = gate["db"]
    batch = ProductBatch(
        company_id=gate["company_id"],
        product_variant_id=variant_id,
        batch_number=f"PA-{suffix}-{uuid4().hex[:8]}",
        disposition="RELEASED",
        is_active=True,
    )
    db.add(batch)
    await db.flush()
    db.add(
        InventoryBalance(
            company_id=gate["company_id"],
            location_id=location_id,
            product_variant_id=variant_id,
            batch_id=int(batch.id),
            stock_status="AVAILABLE",
            on_hand_quantity=Decimal(quantity),
            reserved_quantity=Decimal(0),
        )
    )
    await db.flush()
    return int(batch.id)


async def _balance_total(db: AsyncSession, *, company_id: int, location_ids: list[int]) -> Decimal:
    value = await db.scalar(
        select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0)).where(
            InventoryBalance.company_id == company_id,
            InventoryBalance.location_id.in_(location_ids),
        )
    )
    return Decimal(value or 0)


async def _seed_route(gate, *, vehicle_id: int, source_location_id: int, suffix: str) -> int:
    db = gate["db"]
    zone = Zone(company_id=gate["company_id"], name=f"Access {suffix} Zone")
    db.add(zone)
    await db.flush()
    route = DispatchRoute(
        company_id=gate["company_id"],
        zone_id=int(zone.id),
        driver_id=gate["owner"].driver_id,
        vehicle_id=vehicle_id,
        source_location_id=source_location_id,
        dispatch_date=date.today(),
        status="closed",
    )
    db.add(route)
    await db.flush()
    return int(route.id)


@asynccontextmanager
async def isolated_gate():
    if os.getenv(GATE_ENV) != "1":
        raise RuntimeError(f"set {GATE_ENV}=1")
    raw_url = os.environ.get("DATABASE_URL_MIGRATION") or os.environ.get("DATABASE_URL")
    if not raw_url:
        raise RuntimeError("DATABASE_URL[_MIGRATION] is required")
    url = make_url(raw_url)
    if not str(url.drivername).startswith("postgresql"):
        raise RuntimeError("PostgreSQL is required")

    schema = SCHEMA_PREFIX + uuid4().hex
    admin_engine = create_async_engine(raw_url, poolclass=NullPool)
    async with admin_engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))

    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={
            "server_settings": {
                "search_path": f'"{schema}",public',
                "lock_timeout": "3000ms",
                "statement_timeout": "10000ms",
            }
        },
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with Session() as db:
            suffix = uuid4().hex[:8]
            company = Company(name=f"PR317 Acceptance {suffix}", company_code=f"P7-{suffix}")
            other = Company(name=f"PR317 Other {suffix}", company_code=f"Q7-{suffix}")
            db.add_all([company, other])
            await db.flush()
            owner = await seed_company_owner_fixture(db, int(company.id), password="SyntheticOwner317")
            other_owner = await seed_company_owner_fixture(db, int(other.id), password="SyntheticOther317")
            wh_a = InventoryLocation(
                company_id=int(company.id), name="Warehouse A", code="WH-A",
                location_type="WAREHOUSE", is_active=True,
            )
            wh_b = InventoryLocation(
                company_id=int(company.id), name="Warehouse B", code="WH-B",
                location_type="WAREHOUSE", is_active=True,
            )
            other_wh = InventoryLocation(
                company_id=int(other.id), name="Other Warehouse", code="WH-X",
                location_type="WAREHOUSE", is_active=True,
            )
            db.add_all([wh_a, wh_b, other_wh])
            await db.flush()
            uom = UOM(name=f"Each {suffix}", code=f"E{suffix[:6].upper()}")
            db.add(uom)
            await db.flush()
            product = Product(company_id=int(company.id), code=f"P-{suffix}", name="Acceptance Product")
            db.add(product)
            await db.flush()
            variants = []
            for index, name in enumerate(("Access Variant", "Live Variant"), start=1):
                variant = ProductVariant(
                    company_id=int(company.id), product_id=int(product.id), base_uom_id=int(uom.id),
                    name=name, sku=f"SKU-{index}-{suffix}", quantity_scale=0, quantity_step=1,
                    lot_control_mode="NONE", expiry_control_mode="NONE", lifecycle_status="ACTIVE",
                    operational_hold="NONE", lifecycle_revision=1, version=1,
                    published_at=utc_now(), packs_per_carton=10,
                )
                db.add(variant)
                variants.append(variant)
            await db.commit()

            company_dispatch_user = await seed_ordinary_backoffice_fixture(db, int(company.id))
            await _grant_role(
                db, company_id=int(company.id), driver_id=company_dispatch_user.driver_id,
                codes=("dispatch.read",), company_level=True,
            )
            company_inventory_user = await seed_ordinary_backoffice_fixture(db, int(company.id))
            await _grant_role(
                db, company_id=int(company.id), driver_id=company_inventory_user.driver_id,
                codes=("inventory.read",), company_level=True,
            )
            await db.commit()

            yield {
                "db": db,
                "engine": engine,
                "schema": schema,
                "company_id": int(company.id),
                "other_company_id": int(other.id),
                "owner": owner,
                "other_owner": other_owner,
                "wh_a_id": int(wh_a.id),
                "wh_b_id": int(wh_b.id),
                "other_wh_id": int(other_wh.id),
                "variant_id": int(variants[0].id),
                "live_variant_id": int(variants[1].id),
                "company_dispatch_access": company_dispatch_user.access(db),
                "company_inventory_access": company_inventory_user.access(db),
            }
    finally:
        await engine.dispose()
        async with admin_engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


# =========================
# A. require_vehicle
# =========================
async def case_a1_require_vehicle_canonical(gate):
    db = gate["db"]
    vehicle_id, _ = await _create_vehicle(db, gate["owner"], gate["company_id"], "PR317-A1")
    await db.commit()
    await require_vehicle(gate["company_dispatch_access"], "dispatch.read", vehicle_id)


async def case_a2_require_vehicle_active_plus_history(gate):
    db = gate["db"]
    vehicle_id, _ = await _create_vehicle(db, gate["owner"], gate["company_id"], "PR317-A2")
    await _add_historical_custody(
        db, company_id=gate["company_id"], vehicle_id=vehicle_id, suffix="A2", active=False
    )
    await db.commit()
    assert await _count(
        db, InventoryLocation,
        InventoryLocation.company_id == gate["company_id"],
        InventoryLocation.vehicle_id == vehicle_id,
        InventoryLocation.location_type == "VEHICLE",
    ) == 2
    await _expect_vehicle_rejected(gate["company_dispatch_access"], vehicle_id)


async def case_a3_require_vehicle_two_inactive(gate):
    db = gate["db"]
    vehicle_id, custody_id = await _create_vehicle(
        db, gate["owner"], gate["company_id"], "PR317-A3"
    )
    custody = await db.get(InventoryLocation, custody_id)
    custody.is_active = False
    await _add_historical_custody(
        db, company_id=gate["company_id"], vehicle_id=vehicle_id, suffix="A3", active=False
    )
    await db.commit()
    rows = (
        await db.scalars(
            select(InventoryLocation).where(
                InventoryLocation.company_id == gate["company_id"],
                InventoryLocation.vehicle_id == vehicle_id,
                InventoryLocation.location_type == "VEHICLE",
            )
        )
    ).all()
    assert len(rows) == 2 and all(row.is_active is False for row in rows)
    await _expect_vehicle_rejected(gate["company_dispatch_access"], vehicle_id)


async def case_a4_require_vehicle_single_inactive(gate):
    db = gate["db"]
    vehicle_id, custody_id = await _create_vehicle(
        db, gate["owner"], gate["company_id"], "PR317-A4"
    )
    custody = await db.get(InventoryLocation, custody_id)
    custody.is_active = False
    await db.commit()
    await _expect_vehicle_rejected(gate["company_dispatch_access"], vehicle_id)


async def case_a5_require_vehicle_missing(gate):
    db = gate["db"]
    vehicle_id, custody_id = await _create_vehicle(
        db, gate["owner"], gate["company_id"], "PR317-A5"
    )
    await db.execute(delete(InventoryLocation).where(InventoryLocation.id == custody_id))
    await db.commit()
    await _expect_vehicle_rejected(gate["company_dispatch_access"], vehicle_id)


async def case_a6_require_vehicle_foreign_history_isolated(gate):
    db = gate["db"]
    vehicle_id, _ = await _create_vehicle(db, gate["owner"], gate["company_id"], "PR317-A6")
    other_vehicle_id, other_custody_id = await _create_vehicle(
        db, gate["other_owner"], gate["other_company_id"], "PR317-X6"
    )
    other_custody = await db.get(InventoryLocation, other_custody_id)
    other_custody.is_active = False
    await _add_historical_custody(
        db,
        company_id=gate["other_company_id"],
        vehicle_id=other_vehicle_id,
        suffix="FOREIGN-A6",
        active=False,
    )
    await db.commit()
    assert await _count(
        db, InventoryLocation,
        InventoryLocation.company_id == gate["company_id"],
        InventoryLocation.vehicle_id == vehicle_id,
        InventoryLocation.location_type == "VEHICLE",
    ) == 1
    await require_vehicle(gate["company_dispatch_access"], "dispatch.read", vehicle_id)


# =========================
# B/C. vehicle_filter / route_filter
# =========================
async def _seed_vehicle_filter_matrix(gate, suffix: str):
    db = gate["db"]
    company_id = gate["company_id"]
    v1, l1 = await _create_vehicle(db, gate["owner"], company_id, f"{suffix}-V1")
    v2, l2 = await _create_vehicle(db, gate["owner"], company_id, f"{suffix}-V2")
    v3, l3 = await _create_vehicle(db, gate["owner"], company_id, f"{suffix}-V3")
    v4, l4 = await _create_vehicle(db, gate["owner"], company_id, f"{suffix}-V4")
    v5, l5 = await _create_vehicle(
        db, gate["other_owner"], gate["other_company_id"], f"{suffix}-V5"
    )
    await _add_historical_custody(
        db, company_id=company_id, vehicle_id=v2, suffix=f"{suffix}-V2", active=False
    )
    await db.execute(delete(InventoryLocation).where(InventoryLocation.id == l3))
    inactive = await db.get(InventoryLocation, l4)
    inactive.is_active = False
    await db.commit()
    return {
        "tenant_ids": [v1, v2, v3, v4],
        "all_ids": [v1, v2, v3, v4, v5],
        "v1": v1, "v2": v2, "v3": v3, "v4": v4, "v5": v5,
        "l1": l1, "l2": l2, "l4": l4, "l5": l5,
    }


async def _vehicle_filter_ids(db, access, company_id: int, vehicle_ids: list[int]) -> list[int]:
    return list(
        (
            await db.scalars(
                select(Vehicle.id)
                .where(
                    Vehicle.company_id == company_id,
                    Vehicle.id.in_(vehicle_ids),
                    vehicle_filter(access, "dispatch.read"),
                )
                .order_by(Vehicle.id)
            )
        ).all()
    )


async def case_b1_vehicle_filter_company_scope(gate):
    matrix = await _seed_vehicle_filter_matrix(gate, "PR317-B1")
    observed = await _vehicle_filter_ids(
        gate["db"], gate["company_dispatch_access"], gate["company_id"], matrix["all_ids"]
    )
    assert observed == [matrix["v1"]], observed


async def case_b2_vehicle_filter_exact_location_scope(gate):
    matrix = await _seed_vehicle_filter_matrix(gate, "PR317-B2")
    access = await _new_access(
        gate,
        codes=("dispatch.read",),
        location_ids=(matrix["l1"], matrix["l2"]),
    )
    observed = await _vehicle_filter_ids(
        gate["db"], access, gate["company_id"], matrix["tenant_ids"]
    )
    assert observed == [matrix["v1"]], observed


async def case_c1_route_filter_inherits_strict_vehicle_scope(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    v1, l1 = await _create_vehicle(db, gate["owner"], company_id, "PR317-C1-V1")
    v2, l2 = await _create_vehicle(db, gate["owner"], company_id, "PR317-C1-V2")
    await _add_historical_custody(
        db, company_id=company_id, vehicle_id=v2, suffix="C1-V2", active=False
    )
    r1 = await _seed_route(gate, vehicle_id=v1, source_location_id=gate["wh_a_id"], suffix="C1-1")
    r2 = await _seed_route(gate, vehicle_id=v2, source_location_id=gate["wh_a_id"], suffix="C1-2")
    await db.commit()

    company_rows = list(
        (
            await db.scalars(
                select(DispatchRoute.id)
                .where(
                    DispatchRoute.company_id == company_id,
                    DispatchRoute.id.in_([r1, r2]),
                    route_filter(gate["company_dispatch_access"], "dispatch.read"),
                )
                .order_by(DispatchRoute.id)
            )
        ).all()
    )
    assert company_rows == [r1], company_rows

    scoped = await _new_access(
        gate,
        codes=("dispatch.read",),
        location_ids=(gate["wh_a_id"], l1, l2),
    )
    scoped_rows = list(
        (
            await db.scalars(
                select(DispatchRoute.id)
                .where(
                    DispatchRoute.company_id == company_id,
                    DispatchRoute.id.in_([r1, r2]),
                    route_filter(scoped, "dispatch.read"),
                )
                .order_by(DispatchRoute.id)
            )
        ).all()
    )
    assert scoped_rows == [r1], scoped_rows


# =========================
# F. authorization invariants
# =========================
async def case_f1_vehicle_capabilities_do_not_grant_dispatch(gate):
    db = gate["db"]
    vehicle_id, _ = await _create_vehicle(db, gate["owner"], gate["company_id"], "PR317-F1")
    vehicle_only = await _new_access(
        gate, codes=("vehicle.read", "vehicle.manage"), company_level=True
    )
    try:
        await require_any_location(vehicle_only, "dispatch.read")
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("vehicle.read/manage granted dispatch.read any-location authority")
    await _expect_vehicle_rejected(vehicle_only, vehicle_id)
    observed = await _vehicle_filter_ids(db, vehicle_only, gate["company_id"], [vehicle_id])
    assert observed == []


async def case_f2_any_location_semantics_preserved(gate):
    await require_any_location(gate["company_dispatch_access"], "dispatch.read")
    vehicle_id, location_id = await _create_vehicle(
        gate["db"], gate["owner"], gate["company_id"], "PR317-F2"
    )
    local = await _new_access(
        gate, codes=("dispatch.read",), location_ids=(location_id,)
    )
    await require_any_location(local, "dispatch.read")
    await require_vehicle(local, "dispatch.read", vehicle_id)


async def case_f3_source_warehouse_independent_from_vehicle_custody(gate):
    db = gate["db"]
    vehicle_id, custody_id = await _create_vehicle(
        db, gate["owner"], gate["company_id"], "PR317-F3"
    )
    route_id = await _seed_route(
        gate, vehicle_id=vehicle_id, source_location_id=gate["wh_a_id"], suffix="F3"
    )
    await db.commit()

    vehicle_only_scope = await _new_access(
        gate, codes=("dispatch.read",), location_ids=(custody_id,)
    )
    vehicle_rows = await _vehicle_filter_ids(
        db, vehicle_only_scope, gate["company_id"], [vehicle_id]
    )
    assert vehicle_rows == [vehicle_id]
    route_rows = list(
        (
            await db.scalars(
                select(DispatchRoute.id).where(
                    DispatchRoute.id == route_id,
                    route_filter(vehicle_only_scope, "dispatch.read"),
                )
            )
        ).all()
    )
    assert route_rows == [], "vehicle custody scope incorrectly implied source warehouse scope"

    full_route_scope = await _new_access(
        gate, codes=("dispatch.read",), location_ids=(custody_id, gate["wh_a_id"])
    )
    route_rows = list(
        (
            await db.scalars(
                select(DispatchRoute.id).where(
                    DispatchRoute.id == route_id,
                    route_filter(full_route_scope, "dispatch.read"),
                )
            )
        ).all()
    )
    assert route_rows == [route_id]


# =========================
# D. Live Stock readable Vehicle locations
# =========================
async def _seed_live_read_matrix(gate, suffix: str):
    db = gate["db"]
    company_id = gate["company_id"]
    v1, l1 = await _create_vehicle(db, gate["owner"], company_id, f"{suffix}-V1")
    v2, l2 = await _create_vehicle(db, gate["owner"], company_id, f"{suffix}-V2")
    v3, l3 = await _create_vehicle(db, gate["owner"], company_id, f"{suffix}-V3")
    v4, l4 = await _create_vehicle(db, gate["owner"], company_id, f"{suffix}-V4")
    v5, l5 = await _create_vehicle(
        db, gate["other_owner"], gate["other_company_id"], f"{suffix}-V5"
    )
    await _add_historical_custody(
        db, company_id=company_id, vehicle_id=v2, suffix=f"{suffix}-V2", active=False
    )
    await db.execute(delete(InventoryLocation).where(InventoryLocation.id == l3))
    inactive = await db.get(InventoryLocation, l4)
    inactive.is_active = False
    await db.commit()
    return {
        "main_ids": [v1, v2, v3, v4],
        "all_ids": [v1, v2, v3, v4, v5],
        "v1": v1, "v2": v2, "v3": v3, "v4": v4, "v5": v5,
        "l1": l1, "l2": l2, "l4": l4, "l5": l5,
    }


async def _readable_vehicle_ids(gate, access, ids: list[int]) -> list[int]:
    readable = live_stock_api._readable_vehicle_locations_subquery(
        company_id=gate["company_id"], access=access
    )
    return list(
        (
            await gate["db"].scalars(
                select(readable.c.vehicle_id)
                .where(readable.c.vehicle_id.in_(ids))
                .order_by(readable.c.vehicle_id)
            )
        ).all()
    )


async def case_d1_live_stock_readable_locations_company_scope(gate):
    matrix = await _seed_live_read_matrix(gate, "PR317-D1")
    observed = await _readable_vehicle_ids(
        gate, gate["company_inventory_access"], matrix["all_ids"]
    )
    assert observed == [matrix["v1"]], observed


async def case_d2_live_stock_readable_locations_exact_scope(gate):
    matrix = await _seed_live_read_matrix(gate, "PR317-D2")
    access = await _new_access(
        gate,
        codes=("inventory.read",),
        location_ids=(matrix["l1"], matrix["l2"]),
    )
    observed = await _readable_vehicle_ids(gate, access, matrix["all_ids"])
    assert observed == [matrix["v1"]], observed


# =========================
# E. Live Stock projection service
# =========================
async def _projection_context(gate):
    if "projection_ctx" in gate:
        return gate["projection_ctx"]
    db = gate["db"]
    company_id = gate["company_id"]
    canonical_vehicle, canonical_location = await _create_vehicle(
        db, gate["owner"], company_id, "PR317-E-CANON"
    )
    ambiguous_vehicle, ambiguous_location = await _create_vehicle(
        db, gate["owner"], company_id, "PR317-E-AMB"
    )
    duplicate_id = await _add_historical_custody(
        db,
        company_id=company_id,
        vehicle_id=ambiguous_vehicle,
        suffix="E-AMB",
        active=False,
    )
    canonical_route = await _seed_route(
        gate,
        vehicle_id=canonical_vehicle,
        source_location_id=gate["wh_a_id"],
        suffix="E-CANON",
    )
    ambiguous_route = await _seed_route(
        gate,
        vehicle_id=ambiguous_vehicle,
        source_location_id=gate["wh_b_id"],
        suffix="E-AMB",
    )
    await _seed_balance(
        gate,
        location_id=canonical_location,
        variant_id=gate["live_variant_id"],
        quantity=5,
        suffix="E-CANON",
    )
    await _seed_balance(
        gate,
        location_id=ambiguous_location,
        variant_id=gate["live_variant_id"],
        quantity=7,
        suffix="E-AMB",
    )
    await db.commit()
    ctx = {
        "canonical_vehicle": canonical_vehicle,
        "canonical_location": canonical_location,
        "ambiguous_vehicle": ambiguous_vehicle,
        "ambiguous_location": ambiguous_location,
        "duplicate_id": duplicate_id,
        "canonical_route": canonical_route,
        "ambiguous_route": ambiguous_route,
        "balance_total": await _balance_total(
            db,
            company_id=company_id,
            location_ids=[canonical_location, ambiguous_location],
        ),
        "balance_rows": await _count(
            db,
            InventoryBalance,
            InventoryBalance.company_id == company_id,
            InventoryBalance.location_id.in_([canonical_location, ambiguous_location]),
        ),
    }
    gate["projection_ctx"] = ctx
    return ctx


async def _projection_row(gate, warehouse_id: int):
    return await gate["db"].scalar(
        select(InventoryLiveStockProjection).where(
            InventoryLiveStockProjection.company_id == gate["company_id"],
            InventoryLiveStockProjection.warehouse_location_id == warehouse_id,
            InventoryLiveStockProjection.product_variant_id == gate["live_variant_id"],
        )
    )


async def _assert_projection_balances_unchanged(gate, ctx):
    db = gate["db"]
    assert await _balance_total(
        db,
        company_id=gate["company_id"],
        location_ids=[ctx["canonical_location"], ctx["ambiguous_location"]],
    ) == ctx["balance_total"]
    assert await _count(
        db,
        InventoryBalance,
        InventoryBalance.company_id == gate["company_id"],
        InventoryBalance.location_id.in_([ctx["canonical_location"], ctx["ambiguous_location"]]),
    ) == ctx["balance_rows"]


async def case_e1_projection_rebuild_and_candidates_exclude_ambiguity(gate):
    db = gate["db"]
    ctx = await _projection_context(gate)
    report = await projection_service.rebuild_live_stock_company(
        db, company_id=gate["company_id"], batch_size=100
    )
    await db.commit()
    projection_a = await _projection_row(gate, gate["wh_a_id"])
    projection_b = await _projection_row(gate, gate["wh_b_id"])
    assert projection_a is not None
    assert Decimal(projection_a.vehicle_packs or 0) == Decimal("5")
    assert projection_b is None or Decimal(projection_b.vehicle_packs or 0) == Decimal("0")

    keys = await projection_service._candidate_keys_for_variants(
        db,
        company_id=gate["company_id"],
        variant_ids=[gate["live_variant_id"]],
    )
    assert (gate["wh_a_id"], gate["live_variant_id"]) in keys
    assert (gate["wh_b_id"], gate["live_variant_id"]) not in keys

    sources = await projection_service.get_live_stock_vehicle_sources(
        db,
        company_id=gate["company_id"],
        vehicle_ids=[ctx["canonical_vehicle"], ctx["ambiguous_vehicle"]],
    )
    assert sources[ctx["canonical_vehicle"]] == gate["wh_a_id"]
    assert sources[ctx["ambiguous_vehicle"]] == gate["wh_b_id"]

    await projection_service.refresh_live_stock_vehicle_attribution(
        db,
        company_id=gate["company_id"],
        vehicle_ids=[ctx["canonical_vehicle"]],
        previous_sources={},
    )
    await db.commit()
    projection_a = await _projection_row(gate, gate["wh_a_id"])
    assert Decimal(projection_a.vehicle_packs or 0) == Decimal("5")
    await _assert_projection_balances_unchanged(gate, ctx)
    EVIDENCE["rebuild_report"] = str(report)


async def case_e2_projection_refresh_does_not_attribute_ambiguous_vehicle(gate):
    db = gate["db"]
    ctx = await _projection_context(gate)
    before_b = await _projection_row(gate, gate["wh_b_id"])
    before_value = Decimal(before_b.vehicle_packs or 0) if before_b is not None else Decimal("0")
    await projection_service.refresh_live_stock_vehicle_attribution(
        db,
        company_id=gate["company_id"],
        vehicle_ids=[ctx["ambiguous_vehicle"]],
        previous_sources={},
    )
    await db.commit()
    after_b = await _projection_row(gate, gate["wh_b_id"])
    after_value = Decimal(after_b.vehicle_packs or 0) if after_b is not None else Decimal("0")
    assert before_value == Decimal("0") and after_value == Decimal("0")
    await _assert_projection_balances_unchanged(gate, ctx)


async def case_e3_projection_resolution_restores_attribution(gate):
    db = gate["db"]
    ctx = await _projection_context(gate)
    await db.execute(
        delete(InventoryLocation).where(
            InventoryLocation.company_id == gate["company_id"],
            InventoryLocation.id == ctx["duplicate_id"],
        )
    )
    await db.commit()

    keys = await projection_service._candidate_keys_for_variants(
        db,
        company_id=gate["company_id"],
        variant_ids=[gate["live_variant_id"]],
    )
    assert (gate["wh_b_id"], gate["live_variant_id"]) in keys

    await projection_service.refresh_live_stock_vehicle_attribution(
        db,
        company_id=gate["company_id"],
        vehicle_ids=[ctx["ambiguous_vehicle"]],
        previous_sources={},
    )
    await db.commit()
    projection_b = await _projection_row(gate, gate["wh_b_id"])
    assert projection_b is not None
    assert Decimal(projection_b.vehicle_packs or 0) == Decimal("7")
    await _assert_projection_balances_unchanged(gate, ctx)
    EVIDENCE["inventory_balance_projection_mutation"] = "0 rows / 0 quantity delta"


# =========================
# G. SQL / performance sanity
# =========================
async def case_g1_vehicle_filter_single_statement_and_explain(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    # Representative cardinality without changing runtime: add more canonical rows.
    for index in range(12):
        await _create_vehicle(
            db, gate["owner"], company_id, f"PR317-G-{index:02d}-{uuid4().hex[:4]}"
        )
    await db.commit()

    stmt = (
        select(Vehicle.id)
        .where(
            Vehicle.company_id == company_id,
            vehicle_filter(gate["company_dispatch_access"], "dispatch.read"),
        )
        .order_by(Vehicle.id)
    )
    statements: list[str] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(gate["engine"].sync_engine, "before_cursor_execute", before_cursor_execute)
    try:
        rows = (await db.execute(stmt)).scalars().all()
    finally:
        event.remove(gate["engine"].sync_engine, "before_cursor_execute", before_cursor_execute)
    assert rows
    assert len(statements) == 1, f"vehicle_filter collection emitted {len(statements)} statements"

    compiled = str(
        stmt.compile(
            dialect=gate["engine"].sync_engine.dialect,
            compile_kwargs={"literal_binds": True},
        )
    )
    explain_rows = (
        await db.execute(text("EXPLAIN (COSTS OFF) " + compiled))
    ).scalars().all()
    plan = "\n".join(str(row) for row in explain_rows)
    assert plan.strip()
    assert "inventory_locations" in plan.lower()
    assert "aggregate" in plan.lower() or "subplan" in plan.lower()
    EVIDENCE["filter_sql_statement_count"] = len(statements)
    EVIDENCE["filter_explain"] = " | ".join(str(row) for row in explain_rows[:8])


CASES = [
    ("require_vehicle", "A1_canonical", case_a1_require_vehicle_canonical),
    ("require_vehicle", "A2_active_plus_history", case_a2_require_vehicle_active_plus_history),
    ("require_vehicle", "A3_two_inactive", case_a3_require_vehicle_two_inactive),
    ("require_vehicle", "A4_single_inactive", case_a4_require_vehicle_single_inactive),
    ("require_vehicle", "A5_missing", case_a5_require_vehicle_missing),
    ("require_vehicle", "A6_foreign_history_isolated", case_a6_require_vehicle_foreign_history_isolated),
    ("filter_route", "B1_vehicle_filter_company", case_b1_vehicle_filter_company_scope),
    ("filter_route", "B2_vehicle_filter_location", case_b2_vehicle_filter_exact_location_scope),
    ("filter_route", "C1_route_filter_inheritance", case_c1_route_filter_inherits_strict_vehicle_scope),
    ("authorization", "F1_vehicle_caps_not_dispatch", case_f1_vehicle_capabilities_do_not_grant_dispatch),
    ("authorization", "F2_any_location", case_f2_any_location_semantics_preserved),
    ("authorization", "F3_source_warehouse_independent", case_f3_source_warehouse_independent_from_vehicle_custody),
    ("live_stock", "D1_readable_company", case_d1_live_stock_readable_locations_company_scope),
    ("live_stock", "D2_readable_location", case_d2_live_stock_readable_locations_exact_scope),
    ("live_stock", "E1_rebuild_candidates_canonical", case_e1_projection_rebuild_and_candidates_exclude_ambiguity),
    ("live_stock", "E2_refresh_ambiguous_excluded", case_e2_projection_refresh_does_not_attribute_ambiguous_vehicle),
    ("live_stock", "E3_resolution_restores", case_e3_projection_resolution_restores_attribution),
    ("sql", "G1_statement_count_explain", case_g1_vehicle_filter_single_statement_and_explain),
]


async def _leftover_schema_count(raw_url: str) -> int:
    engine = create_async_engine(raw_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            return int(
                await conn.scalar(
                    text("SELECT count(*) FROM pg_namespace WHERE nspname LIKE :p"),
                    {"p": SCHEMA_PREFIX + "%"},
                )
                or 0
            )
    finally:
        await engine.dispose()


async def run_acceptance() -> int:
    results: dict[str, list[bool]] = {}
    failures: list[tuple[str, str]] = []
    deadlocks = 0
    timeouts = 0
    async with isolated_gate() as gate:
        for group, name, factory in CASES:
            try:
                await factory(gate)
            except Exception as exc:
                await gate["db"].rollback()
                results.setdefault(group, []).append(False)
                message = f"{type(exc).__name__}: {exc}"
                failures.append((name, message))
                lowered = message.lower()
                if "deadlock" in lowered:
                    deadlocks += 1
                if "lock timeout" in lowered or "statement timeout" in lowered or "querycanceled" in lowered:
                    timeouts += 1
                print(f"FAIL {name}: {message}", flush=True)
                traceback.print_exc()
            else:
                results.setdefault(group, []).append(True)
                print(f"PASS {name}", flush=True)

    raw_url = os.environ.get("DATABASE_URL_MIGRATION") or os.environ.get("DATABASE_URL")
    leftover = await _leftover_schema_count(raw_url)
    EVIDENCE["deadlocks"] = deadlocks
    EVIDENCE["timeouts"] = timeouts
    EVIDENCE["leftover_schemas"] = leftover

    for group, values in results.items():
        print(f"GROUP {group} pass={sum(values)} fail={len(values)-sum(values)} total={len(values)}", flush=True)
    print(f"SQL_STATEMENT_COUNT={EVIDENCE.get('filter_sql_statement_count')}", flush=True)
    print(f"SQL_EXPLAIN={EVIDENCE.get('filter_explain')}", flush=True)
    print(f"INVENTORY_BALANCE_PROJECTION_MUTATION={EVIDENCE.get('inventory_balance_projection_mutation')}", flush=True)
    print(f"DEADLOCKS={deadlocks}", flush=True)
    print(f"TIMEOUTS={timeouts}", flush=True)
    print(f"LEFTOVER_SCHEMA_COUNT={leftover}", flush=True)
    print(f"RESULT pass={len(CASES)-len(failures)} fail={len(failures)} total={len(CASES)}", flush=True)
    if failures or leftover:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_acceptance()))
