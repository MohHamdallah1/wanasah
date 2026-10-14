from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api import dispatch as dispatch_api
from api import driver as driver_api
from domains.vehicles.contracts import (
    CreateVehicleCommand,
    VehicleLifecycleCommand,
)
from domains.vehicles.lifecycle import deactivate_vehicle, reactivate_vehicle
from domains.vehicles.management import create_vehicle
from models import (
    Base,
    Company,
    DispatchRoute,
    Driver,
    InventoryBalance,
    InventoryLocation,
    Product,
    ProductVariant,
    RouteCommercialContext,
    UOM,
    Vehicle,
    WorkSession,
    Zone,
    utc_now,
)
from schemas import (
    AdjustRouteInventoryRequest,
    DispatchRouteRequest,
    InventoryAdjustmentDelta,
    SessionStartRequest,
    UpdateRouteStatusRequest,
)
from tests.canonical_actor_fixtures import (
    seed_company_owner_fixture,
    seed_field_fixture,
)


GATE_ENV = "WANASAH_VEHICLE_DISPATCH_DB_GATE"


def _gate_enabled() -> bool:
    return os.getenv(GATE_ENV) == "1"


async def _count(db: AsyncSession, model, *criteria) -> int:
    return int(await db.scalar(select(func.count()).select_from(model).where(*criteria)) or 0)


async def _create_vehicle(db: AsyncSession, fixture, company_id: int, *, plate: str = "V-100") -> dict:
    return await create_vehicle(
        db,
        company_id=company_id,
        actor_id=fixture.driver_id,
        command=CreateVehicleCommand(
            request_id=str(uuid4()),
            plate_number=plate,
            vehicle_type="Van",
            maintenance_status="Active",
        ),
    )


async def _vehicle_and_custody(db: AsyncSession, company_id: int, vehicle_id: int):
    vehicle = await db.scalar(
        select(Vehicle).where(Vehicle.company_id == company_id, Vehicle.id == vehicle_id)
    )
    custody = (
        await db.execute(
            select(InventoryLocation).where(
                InventoryLocation.company_id == company_id,
                InventoryLocation.vehicle_id == vehicle_id,
                InventoryLocation.location_type == "VEHICLE",
            )
        )
    ).scalars().all()
    return vehicle, custody


async def _seed_route_context(db: AsyncSession, company_id: int, route: DispatchRoute) -> RouteCommercialContext:
    context = RouteCommercialContext(
        company_id=company_id,
        dispatch_route_id=route.id,
        pricing_locked_at=datetime.now(timezone.utc),
        price_publication_revision=1,
        assignment_revision=1,
        offer_ruleset_version=0,
        tax_ruleset_version=1,
        transaction_currency_code="JOD",
        functional_currency_code="JOD",
        rounding_policy_version=1,
        tenant_policy_revision=1,
    )
    db.add(context)
    await db.flush()
    return context


@pytest_asyncio.fixture(scope="module")
async def gate():
    if not _gate_enabled():
        pytest.skip(f"set {GATE_ENV}=1 to run the isolated PostgreSQL acceptance gate")

    raw_url = os.environ.get("DATABASE_URL_MIGRATION") or os.environ.get("DATABASE_URL")
    if not raw_url:
        pytest.skip("DATABASE_URL[_MIGRATION] is required")
    url = make_url(raw_url)
    if not str(url.drivername).startswith("postgresql"):
        pytest.skip("PostgreSQL is required")

    schema = "vehicle_dispatch_accept_" + uuid4().hex
    admin_engine = create_async_engine(raw_url, poolclass=NullPool)
    async with admin_engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))

    scoped_url = url.set(query={**dict(url.query), "server_settings": f"search_path={schema},public"})
    # asyncpg does not accept server_settings in the URL query; use connect_args explicitly.
    scoped_url = url
    engine = create_async_engine(
        scoped_url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": f'"{schema}",public'}},
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with Session() as db:
            suffix = uuid4().hex[:8]
            company = Company(name=f"Vehicle Acceptance {suffix}", company_code=f"VA-{suffix}")
            other_company = Company(name=f"Vehicle Acceptance Other {suffix}", company_code=f"VB-{suffix}")
            db.add_all([company, other_company])
            await db.flush()

            owner = await seed_company_owner_fixture(db, company.id, password="SyntheticOwner123")
            field = await seed_field_fixture(db, company.id, password="SyntheticField123")
            second_field = await seed_field_fixture(db, company.id, password="SyntheticField456")
            other_owner = await seed_company_owner_fixture(db, other_company.id, password="SyntheticOwner789")

            zone = Zone(company_id=company.id, name="Acceptance Zone")
            second_zone = Zone(company_id=company.id, name="Acceptance Zone 2")
            wh_a = InventoryLocation(
                company_id=company.id,
                name="Warehouse A",
                code="WH-A",
                location_type="WAREHOUSE",
                is_active=True,
            )
            wh_b = InventoryLocation(
                company_id=company.id,
                name="Warehouse B",
                code="WH-B",
                location_type="WAREHOUSE",
                is_active=True,
            )
            other_wh = InventoryLocation(
                company_id=other_company.id,
                name="Other Warehouse",
                code="WH-X",
                location_type="WAREHOUSE",
                is_active=True,
            )
            db.add_all([zone, second_zone, wh_a, wh_b, other_wh])
            await db.flush()

            uom = UOM(name=f"Acceptance Each {suffix}", code=f"EA{suffix[:5].upper()}")
            db.add(uom)
            await db.flush()
            product = Product(company_id=company.id, code=f"P-{suffix}", name="Acceptance Product")
            db.add(product)
            await db.flush()
            variant = ProductVariant(
                company_id=company.id,
                product_id=product.id,
                base_uom_id=uom.id,
                name="Acceptance Variant",
                sku=f"SKU-{suffix}",
                quantity_scale=0,
                quantity_step=1,
                lot_control_mode="NONE",
                expiry_control_mode="NONE",
                lifecycle_status="ACTIVE",
                operational_hold="NONE",
                lifecycle_revision=1,
                version=1,
                published_at=utc_now(),
                packs_per_carton=10,
            )
            db.add(variant)
            await db.commit()

            yield {
                "db": db,
                "company_id": int(company.id),
                "other_company_id": int(other_company.id),
                "owner": owner,
                "other_owner": other_owner,
                "field_context": field.context,
                "field_driver": SimpleNamespace(id=int(field.driver.id), company_id=int(company.id)),
                "field_driver_id": int(field.driver.id),
                "second_field_context": second_field.context,
                "second_field_driver": SimpleNamespace(id=int(second_field.driver.id), company_id=int(company.id)),
                "second_field_driver_id": int(second_field.driver.id),
                "zone_id": int(zone.id),
                "second_zone_id": int(second_zone.id),
                "wh_a_id": int(wh_a.id),
                "wh_b_id": int(wh_b.id),
                "other_wh_id": int(other_wh.id),
                "variant_id": int(variant.id),
                "schema": schema,
            }
    finally:
        await engine.dispose()
        async with admin_engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


@pytest.mark.asyncio
async def test_01_create_idempotency_lifecycle_and_no_balance_writes(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    owner = gate["owner"]
    before_balances = await _count(db, InventoryBalance, InventoryBalance.company_id == company_id)

    request_id = str(uuid4())
    command = CreateVehicleCommand(request_id=request_id, plate_number="ACC-100", vehicle_type="Van")
    first = await create_vehicle(db, company_id=company_id, actor_id=owner.driver_id, command=command)
    replay = await create_vehicle(db, company_id=company_id, actor_id=owner.driver_id, command=command)
    vehicle_id = int(first["id"])

    assert replay == first
    assert await _count(db, Vehicle, Vehicle.company_id == company_id, Vehicle.id == vehicle_id) == 1
    vehicle, custody = await _vehicle_and_custody(db, company_id, vehicle_id)
    assert vehicle is not None and len(custody) == 1
    custody_id = int(custody[0].id)
    assert custody[0].is_active is True

    deactivated = await deactivate_vehicle(
        db,
        company_id=company_id,
        actor_id=owner.driver_id,
        vehicle_id=vehicle_id,
        command=VehicleLifecycleCommand(request_id=str(uuid4()), expected_version=int(vehicle.version)),
    )
    assert deactivated["state"] == "INACTIVE"
    _, custody_after_deactivate = await _vehicle_and_custody(db, company_id, vehicle_id)
    assert [int(row.id) for row in custody_after_deactivate] == [custody_id]
    assert custody_after_deactivate[0].is_active is False

    reactivated = await reactivate_vehicle(
        db,
        company_id=company_id,
        actor_id=owner.driver_id,
        vehicle_id=vehicle_id,
        command=VehicleLifecycleCommand(
            request_id=str(uuid4()), expected_version=int(deactivated["version"])
        ),
    )
    assert reactivated["state"] == "ACTIVE"
    _, custody_after_reactivate = await _vehicle_and_custody(db, company_id, vehicle_id)
    assert [int(row.id) for row in custody_after_reactivate] == [custody_id]
    assert custody_after_reactivate[0].is_active is True
    assert await _count(db, InventoryBalance, InventoryBalance.company_id == company_id) == before_balances


@pytest.mark.asyncio
async def test_02_dispatch_init_eligibility_and_source_warehouse_independence(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    owner = gate["owner"]
    payload = await _create_vehicle(db, owner, company_id, plate="ACC-200")
    vehicle_id = int(payload["id"])
    _, custody = await _vehicle_and_custody(db, company_id, vehicle_id)
    custody_id = int(custody[0].id)

    init = await dispatch_api.dispatch_init(db=db, access=owner.access(db))
    assert str(vehicle_id) in {item["id"] for item in init["vehicles"]}
    selected = next(item for item in init["vehicles"] if item["id"] == str(vehicle_id))
    assert selected["can_execute"] is True
    assert "warehouse_id" not in Vehicle.__table__.columns
    assert "location_id" not in Vehicle.__table__.columns

    route = DispatchRoute(
        company_id=company_id,
        zone_id=gate["zone_id"],
        driver_id=gate["field_driver_id"],
        vehicle_id=vehicle_id,
        source_location_id=gate["wh_a_id"],
        dispatch_date=await dispatch_api.get_company_local_date(db, company_id),
        status="closed",
    )
    db.add(route)
    await db.flush()
    original_vehicle_company = int((await db.get(Vehicle, vehicle_id)).company_id)
    original_custody_id = custody_id
    route.source_location_id = gate["wh_b_id"]
    await db.commit()
    await db.refresh(route)
    _, custody_after = await _vehicle_and_custody(db, company_id, vehicle_id)
    assert route.source_location_id == gate["wh_b_id"]
    assert int((await db.get(Vehicle, vehicle_id)).company_id) == original_vehicle_company
    assert [int(row.id) for row in custody_after] == [original_custody_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["inactive", "maintenance"])
async def test_03_route_create_rejects_non_operational_vehicle(gate, state):
    db = gate["db"]
    company_id = gate["company_id"]
    owner = gate["owner"]
    created = await _create_vehicle(db, owner, company_id, plate=f"ACC-R-{state}")
    vehicle_id = int(created["id"])
    vehicle = await db.get(Vehicle, vehicle_id)
    if state == "inactive":
        vehicle.is_active = False
        custody = await db.scalar(select(InventoryLocation).where(InventoryLocation.vehicle_id == vehicle_id))
        custody.is_active = False
    else:
        vehicle.maintenance_status = "In_Maintenance"
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await dispatch_api.dispatch_route(
            DispatchRouteRequest(
                zone_id=gate["zone_id"],
                driver_id=gate["field_driver_id"],
                vehicle_id=vehicle_id,
                source_location_id=gate["wh_a_id"],
                inventory={},
            ),
            db=db,
            access=owner.access(db),
            legacy_actor=owner.operational_driver,
        )
    assert 400 <= exc.value.status_code < 500
    assert await _count(db, DispatchRoute, DispatchRoute.company_id == company_id, DispatchRoute.vehicle_id == vehicle_id) == 0


@pytest.mark.asyncio
async def test_03c_driver_start_rejects_inactive_vehicle(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    owner = gate["owner"]
    field = await seed_field_fixture(db, company_id, password="SyntheticFieldInactive123")
    field_context = field.context
    field_driver_id = int(field.driver.id)
    field_driver = SimpleNamespace(id=field_driver_id, company_id=company_id)
    zone = Zone(company_id=company_id, name="Inactive Vehicle Start Zone")
    db.add(zone)
    await db.flush()
    zone_id = int(zone.id)
    await db.commit()

    created = await _create_vehicle(db, owner, company_id, plate="ACC-INACTIVE-START")
    vehicle_id = int(created["id"])
    route = DispatchRoute(
        company_id=company_id,
        zone_id=zone_id,
        driver_id=field_driver_id,
        vehicle_id=vehicle_id,
        source_location_id=gate["wh_a_id"],
        dispatch_date=await dispatch_api.get_company_local_date(db, company_id),
        status="active",
    )
    db.add(route)
    await db.flush()
    await _seed_route_context(db, company_id, route)
    vehicle = await db.get(Vehicle, vehicle_id)
    vehicle.is_active = False
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await driver_api.start_work_session(
            SessionStartRequest(), db=db, field_context=field_context, legacy_actor=field_driver
        )
    assert exc.value.status_code == 409
    assert await _count(db, WorkSession, WorkSession.company_id == company_id, WorkSession.driver_id == field_driver_id, WorkSession.end_time.is_(None)) == 0


@pytest.mark.asyncio
async def test_04_maintenance_blocks_operational_transition_adjust_undo_and_driver_start(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    owner = gate["owner"]
    field_context = gate["field_context"]
    field_driver = gate["field_driver"]
    created = await _create_vehicle(db, owner, company_id, plate="ACC-MAINT")
    vehicle = await db.get(Vehicle, int(created["id"]))

    route = DispatchRoute(
        company_id=company_id,
        zone_id=gate["zone_id"],
        driver_id=gate["field_driver_id"],
        vehicle_id=vehicle.id,
        source_location_id=gate["wh_a_id"],
        dispatch_date=await dispatch_api.get_company_local_date(db, company_id),
        status="closed",
    )
    db.add(route)
    await db.flush()
    context = await _seed_route_context(db, company_id, route)
    route_id = int(route.id)
    route_date = route.dispatch_date
    context_id = int(context.id)
    await db.commit()

    vehicle.maintenance_status = "In_Maintenance"
    await db.commit()

    with pytest.raises(HTTPException) as transition_exc:
        await dispatch_api.update_route_status(
            route_id,
            UpdateRouteStatusRequest(status="active"),
            db=db,
            access=owner.access(db),
            legacy_actor=owner.operational_driver,
        )
    assert transition_exc.value.status_code == 409

    route = await db.get(DispatchRoute, route_id)
    route.status = "active"
    await db.commit()
    with pytest.raises(HTTPException) as adjust_exc:
        await dispatch_api.adjust_route_inventory(
            route_id,
            AdjustRouteInventoryRequest(
                request_id=uuid4(),
                deltas=[InventoryAdjustmentDelta(product_id=gate["variant_id"], delta_cartons=1)],
            ),
            db=db,
            access=owner.access(db),
            legacy_actor=owner.operational_driver,
        )
    assert adjust_exc.value.status_code == 409

    with pytest.raises(HTTPException) as start_exc:
        await driver_api.start_work_session(
            SessionStartRequest(),
            db=db,
            field_context=field_context,
            legacy_actor=field_driver,
        )
    assert start_exc.value.status_code == 409

    session = WorkSession(
        company_id=company_id,
        driver_id=gate["field_driver_id"],
        commercial_context_id=context_id,
        session_date=route_date,
        start_time=utc_now(),
        end_time=utc_now(),
        is_settled=False,
    )
    db.add(session)
    await db.flush()
    session_id = int(session.id)
    route = await db.get(DispatchRoute, route_id)
    route.work_session_id = session_id
    await db.commit()
    with pytest.raises(HTTPException) as undo_exc:
        await dispatch_api.undo_end_work(
            session_id,
            db=db,
            access=owner.access(db),
            legacy_actor=owner.operational_driver,
        )
    assert undo_exc.value.status_code == 409
    route = await db.get(DispatchRoute, route_id)
    route.status = "closed"
    await db.commit()


@pytest.mark.asyncio
async def test_05_plain_route_close_is_not_blocked_only_by_maintenance(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    owner = gate["owner"]
    created = await _create_vehicle(db, owner, company_id, plate="ACC-CLOSE")
    vehicle = await db.get(Vehicle, int(created["id"]))
    route = DispatchRoute(
        company_id=company_id,
        zone_id=gate["second_zone_id"],
        driver_id=gate["second_field_driver_id"],
        vehicle_id=vehicle.id,
        source_location_id=gate["wh_a_id"],
        dispatch_date=await dispatch_api.get_company_local_date(db, company_id),
        status="active",
    )
    db.add(route)
    await db.flush()
    await _seed_route_context(db, company_id, route)
    vehicle.maintenance_status = "In_Maintenance"
    await db.commit()

    result = await dispatch_api.update_route_status(
        route.id,
        UpdateRouteStatusRequest(status="closed"),
        db=db,
        access=owner.access(db),
        legacy_actor=owner.operational_driver,
    )
    assert result["message"]
    await db.refresh(route)
    assert route.status == "closed"


@pytest.mark.asyncio
async def test_06_work_session_requires_route_vehicle_and_canonical_custody(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    owner = gate["owner"]
    field = await seed_field_fixture(db, company_id, password="SyntheticFieldRoute123")
    field_context = field.context
    field_driver_id = int(field.driver.id)
    field_driver = SimpleNamespace(id=field_driver_id, company_id=company_id)
    await db.commit()

    with pytest.raises(HTTPException) as no_route:
        await driver_api.start_work_session(
            SessionStartRequest(), db=db, field_context=field_context, legacy_actor=field_driver
        )
    assert no_route.value.status_code == 400

    created = await _create_vehicle(db, owner, company_id, plate="ACC-SESSION")
    vehicle_id = int(created["id"])
    route = DispatchRoute(
        company_id=company_id,
        zone_id=gate["second_zone_id"],
        driver_id=field_driver_id,
        vehicle_id=vehicle_id,
        source_location_id=gate["wh_a_id"],
        dispatch_date=await dispatch_api.get_company_local_date(db, company_id),
        status="active",
    )
    db.add(route)
    await db.flush()
    await _seed_route_context(db, company_id, route)
    await db.execute(
        delete(InventoryLocation).where(
            InventoryLocation.company_id == company_id,
            InventoryLocation.vehicle_id == vehicle_id,
            InventoryLocation.location_type == "VEHICLE",
        )
    )
    await db.commit()

    with pytest.raises(HTTPException) as missing_custody:
        await driver_api.start_work_session(
            SessionStartRequest(), db=db, field_context=field_context, legacy_actor=field_driver
        )
    assert missing_custody.value.status_code == 409


@pytest.mark.asyncio
async def test_06b_valid_canonical_custody_starts_and_binds_work_session(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    owner = gate["owner"]
    field = await seed_field_fixture(db, company_id, password="SyntheticFieldValid123")
    field_context = field.context
    field_driver_id = int(field.driver.id)
    field_driver = SimpleNamespace(id=field_driver_id, company_id=company_id)
    zone = Zone(company_id=company_id, name="Valid Canonical Custody Zone")
    db.add(zone)
    await db.flush()
    zone_id = int(zone.id)
    await db.commit()

    created = await _create_vehicle(db, owner, company_id, plate="ACC-VALID-SESSION")
    vehicle_id = int(created["id"])
    custody_id = await dispatch_api._dispatch_vehicle_location_id(
        db, company_id=company_id, vehicle_id=vehicle_id, require_active=True
    )
    route = DispatchRoute(
        company_id=company_id,
        zone_id=zone_id,
        driver_id=field_driver_id,
        vehicle_id=vehicle_id,
        source_location_id=gate["wh_a_id"],
        dispatch_date=await dispatch_api.get_company_local_date(db, company_id),
        status="active",
    )
    db.add(route)
    await db.flush()
    route_id = int(route.id)
    await _seed_route_context(db, company_id, route)
    await db.commit()

    result = await driver_api.start_work_session(
        SessionStartRequest(), db=db, field_context=field_context, legacy_actor=field_driver
    )
    assert result["message"]
    active_session = await db.scalar(
        select(WorkSession).where(
            WorkSession.company_id == company_id,
            WorkSession.driver_id == field_driver_id,
            WorkSession.end_time.is_(None),
        )
    )
    assert active_session is not None
    bound_route = await db.get(DispatchRoute, route_id)
    assert int(bound_route.work_session_id) == int(active_session.id)
    assert await _count(
        db, InventoryLocation,
        InventoryLocation.company_id == company_id,
        InventoryLocation.vehicle_id == vehicle_id,
        InventoryLocation.location_type == "VEHICLE",
    ) == 1
    assert int(custody_id) == int(await dispatch_api._dispatch_vehicle_location_id(
        db, company_id=company_id, vehicle_id=vehicle_id, require_active=True
    ))


@pytest.mark.asyncio
async def test_07_strict_custody_zero_and_historical_duplicate_fail_closed(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    owner = gate["owner"]

    zero = await _create_vehicle(db, owner, company_id, plate="ACC-ZERO")
    zero_id = int(zero["id"])
    await db.execute(delete(InventoryLocation).where(InventoryLocation.vehicle_id == zero_id))
    await db.commit()
    with pytest.raises(HTTPException) as zero_exc:
        await dispatch_api._dispatch_vehicle_location_id(
            db, company_id=company_id, vehicle_id=zero_id, require_active=True
        )
    assert zero_exc.value.status_code == 409

    dup = await _create_vehicle(db, owner, company_id, plate="ACC-DUP")
    dup_id = int(dup["id"])
    db.add(
        InventoryLocation(
            company_id=company_id,
            branch_id=None,
            name="Historical duplicate vehicle custody",
            code=f"VEH-HIST-{dup_id}",
            location_type="VEHICLE",
            vehicle_id=dup_id,
            is_active=False,
            version=1,
        )
    )
    await db.commit()
    assert await _count(
        db,
        InventoryLocation,
        InventoryLocation.company_id == company_id,
        InventoryLocation.vehicle_id == dup_id,
        InventoryLocation.location_type == "VEHICLE",
    ) == 2

    # Strict contract: historical inactive duplicates are still ambiguity; never first-row-wins.
    with pytest.raises(HTTPException) as duplicate_exc:
        await dispatch_api._dispatch_vehicle_location_id(
            db, company_id=company_id, vehicle_id=dup_id, require_active=True
        )
    assert duplicate_exc.value.status_code == 409


@pytest.mark.asyncio
async def test_08_driver_start_rejects_historical_duplicate_custody(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    owner = gate["owner"]
    field = await seed_field_fixture(db, company_id, password="SyntheticFieldDup123")
    field_context = field.context
    field_driver_id = int(field.driver.id)
    field_driver = SimpleNamespace(id=field_driver_id, company_id=company_id)
    await db.commit()
    created = await _create_vehicle(db, owner, company_id, plate="ACC-DUP-SESSION")
    vehicle_id = int(created["id"])
    db.add(
        InventoryLocation(
            company_id=company_id,
            name="Historical duplicate for session",
            code=f"VEH-HIST-SESSION-{vehicle_id}",
            location_type="VEHICLE",
            vehicle_id=vehicle_id,
            is_active=False,
            version=1,
        )
    )
    isolated_zone = Zone(company_id=company_id, name="Duplicate Custody Zone")
    db.add(isolated_zone)
    await db.flush()
    route = DispatchRoute(
        company_id=company_id,
        zone_id=isolated_zone.id,
        driver_id=field_driver_id,
        vehicle_id=vehicle_id,
        source_location_id=gate["wh_a_id"],
        dispatch_date=await dispatch_api.get_company_local_date(db, company_id),
        status="active",
    )
    db.add(route)
    await db.flush()
    await _seed_route_context(db, company_id, route)
    await db.commit()

    # Must fail because canonical custody cardinality is >1 even though only one row is active.
    with pytest.raises(HTTPException) as exc:
        await driver_api.start_work_session(
            SessionStartRequest(), db=db, field_context=field_context, legacy_actor=field_driver
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_09_active_route_vehicle_uniqueness_remains_database_enforced(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    owner = gate["owner"]
    created = await _create_vehicle(db, owner, company_id, plate="ACC-UNIQ")
    vehicle_id = int(created["id"])
    field_a = await seed_field_fixture(db, company_id, password="SyntheticFieldU1")
    field_b = await seed_field_fixture(db, company_id, password="SyntheticFieldU2")
    zone_a = Zone(company_id=company_id, name="Uniq A")
    zone_b = Zone(company_id=company_id, name="Uniq B")
    db.add_all([zone_a, zone_b])
    await db.flush()
    today = await dispatch_api.get_company_local_date(db, company_id)
    db.add(
        DispatchRoute(
            company_id=company_id,
            zone_id=zone_a.id,
            driver_id=field_a.driver.id,
            vehicle_id=vehicle_id,
            source_location_id=gate["wh_a_id"],
            dispatch_date=today,
            status="waiting",
        )
    )
    await db.commit()
    db.add(
        DispatchRoute(
            company_id=company_id,
            zone_id=zone_b.id,
            driver_id=field_b.driver.id,
            vehicle_id=vehicle_id,
            source_location_id=gate["wh_b_id"],
            dispatch_date=today,
            status="active",
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


@pytest.mark.asyncio
async def test_10_cross_company_vehicle_custody_combinations_fail_closed(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    other_company_id = gate["other_company_id"]
    owner = gate["owner"]
    created = await _create_vehicle(db, owner, company_id, plate="ACC-XTENANT")
    vehicle_id = int(created["id"])

    with pytest.raises(HTTPException) as lookup_exc:
        await dispatch_api._dispatch_vehicle_location_id(
            db, company_id=other_company_id, vehicle_id=vehicle_id, require_active=True
        )
    assert lookup_exc.value.status_code == 409

    db.add(
        InventoryLocation(
            company_id=other_company_id,
            name="Invalid cross-tenant vehicle custody",
            code=f"X-{vehicle_id}",
            location_type="VEHICLE",
            vehicle_id=vehicle_id,
            is_active=True,
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


@pytest.mark.asyncio
async def test_11_custody_is_inventory_location_only_and_vehicle_crud_never_creates_balances(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    owner = gate["owner"]
    before = await _count(db, InventoryBalance, InventoryBalance.company_id == company_id)
    created = await _create_vehicle(db, owner, company_id, plate="ACC-STOCK")
    vehicle_id = int(created["id"])
    location_id = await dispatch_api._dispatch_vehicle_location_id(
        db, company_id=company_id, vehicle_id=vehicle_id, require_active=True
    )
    location = await db.get(InventoryLocation, location_id)
    assert location.location_type == "VEHICLE" and int(location.vehicle_id) == vehicle_id
    assert await _count(db, InventoryBalance, InventoryBalance.company_id == company_id) == before
