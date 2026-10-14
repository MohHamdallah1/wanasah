from __future__ import annotations

import os
from datetime import date, datetime, timezone
from uuid import uuid4
from decimal import Decimal
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
    InventoryMovement,
    InventoryTransferHeader,
    InventoryTransferLine,
    Product,
    ProductBatch,
    ProductLocation,
    ProductVariant,
    RouteCommercialContext,
    Shop,
    SystemAuditLog,
    UOM,
    Vehicle,
    Visit,
    WorkSession,
    Zone,
    utc_now,
)
from schemas import (
    AdjustRouteInventoryRequest,
    BatchTransferResponseRequest,
    DispatchRouteRequest,
    InventoryAdjustmentDelta,
    SessionStartRequest,
    TransferResponseRequest,
    UpdateRouteStatusRequest,
    VisitUpdateRequest,
)
from product_lifecycle import DEFAULT_PRODUCT_LOCATION_FLAGS

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
    assert duplicate_exc.value.detail["code"] == "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS"
    assert duplicate_exc.value.detail["context"]["location_count"] == 2

    single = await _create_vehicle(db, owner, company_id, plate="ACC-SINGLE-CUSTODY")
    single_id = int(single["id"])
    single_location_id = await dispatch_api._dispatch_vehicle_location_id(
        db, company_id=company_id, vehicle_id=single_id, require_active=True
    )
    assert await _count(
        db, InventoryLocation,
        InventoryLocation.company_id == company_id,
        InventoryLocation.vehicle_id == single_id,
        InventoryLocation.location_type == "VEHICLE",
    ) == 1
    single_location = await db.get(InventoryLocation, single_location_id)
    single_location.is_active = False
    await db.commit()
    with pytest.raises(HTTPException) as inactive_exc:
        await dispatch_api._dispatch_vehicle_location_id(
            db, company_id=company_id, vehicle_id=single_id, require_active=True
        )
    assert inactive_exc.value.status_code == 409
    assert inactive_exc.value.detail["code"] == "VEHICLE_CUSTODY_LOCATION_INACTIVE"
    assert int(await dispatch_api._dispatch_vehicle_location_id(
        db, company_id=company_id, vehicle_id=single_id, require_active=False
    )) == single_location_id

    multiple = await _create_vehicle(db, owner, company_id, plate="ACC-MULTI-INACTIVE")
    multiple_id = int(multiple["id"])
    canonical = await db.scalar(select(InventoryLocation).where(
        InventoryLocation.company_id == company_id,
        InventoryLocation.vehicle_id == multiple_id,
        InventoryLocation.location_type == "VEHICLE",
    ))
    canonical.is_active = False
    db.add_all([
        InventoryLocation(
            company_id=company_id, name="Historical inactive duplicate A",
            code=f"VEH-HIST-A-{multiple_id}", location_type="VEHICLE",
            vehicle_id=multiple_id, is_active=False, version=1,
        ),
        InventoryLocation(
            company_id=company_id, name="Historical inactive duplicate B",
            code=f"VEH-HIST-B-{multiple_id}", location_type="VEHICLE",
            vehicle_id=multiple_id, is_active=False, version=1,
        ),
    ])
    await db.commit()
    assert await _count(
        db, InventoryLocation,
        InventoryLocation.company_id == company_id,
        InventoryLocation.vehicle_id == multiple_id,
        InventoryLocation.location_type == "VEHICLE",
    ) == 3
    for require_active in (False, True):
        with pytest.raises(HTTPException) as multiple_exc:
            await dispatch_api._dispatch_vehicle_location_id(
                db, company_id=company_id, vehicle_id=multiple_id,
                require_active=require_active,
            )
        assert multiple_exc.value.status_code == 409
        assert multiple_exc.value.detail["code"] == "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS"
        assert multiple_exc.value.detail["context"]["location_count"] == 3


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
    assert exc.value.detail["code"] == "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS"


@pytest.mark.asyncio
async def test_08b_dispatch_route_and_load_adjustment_reject_ambiguous_custody(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    owner = gate["owner"]
    variant_id = gate["variant_id"]
    before_balances = await _count(db, InventoryBalance, InventoryBalance.company_id == company_id)

    route_field = await seed_field_fixture(db, company_id, password="SyntheticFieldAmbRoute123")
    route_field_id = int(route_field.driver.id)
    route_zone = Zone(company_id=company_id, name="Ambiguous Route Create Zone")
    db.add(route_zone)
    await db.flush()
    route_zone_id = int(route_zone.id)
    await db.commit()
    created = await _create_vehicle(db, owner, company_id, plate="ACC-AMB-ROUTE")
    vehicle_id = int(created["id"])
    db.add(InventoryLocation(
        company_id=company_id, name="Ambiguous route historical custody",
        code=f"VEH-HIST-ROUTE-{vehicle_id}", location_type="VEHICLE",
        vehicle_id=vehicle_id, is_active=False, version=1,
    ))
    await db.commit()
    with pytest.raises(HTTPException) as route_exc:
        await dispatch_api.dispatch_route(
            DispatchRouteRequest(
                zone_id=route_zone_id, driver_id=route_field_id, vehicle_id=vehicle_id,
                source_location_id=gate["wh_a_id"], inventory={},
            ),
            db=db, access=owner.access(db), legacy_actor=owner.operational_driver,
        )
    assert route_exc.value.status_code == 409
    assert route_exc.value.detail["code"] == "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS"
    assert await _count(
        db, DispatchRoute, DispatchRoute.company_id == company_id,
        DispatchRoute.vehicle_id == vehicle_id,
    ) == 0

    adjust_field = await seed_field_fixture(db, company_id, password="SyntheticFieldAmbAdjust123")
    adjust_field_id = int(adjust_field.driver.id)
    adjust_zone = Zone(company_id=company_id, name="Ambiguous Load Adjustment Zone")
    db.add(adjust_zone)
    await db.flush()
    adjust_zone_id = int(adjust_zone.id)
    await db.commit()
    adjusted = await _create_vehicle(db, owner, company_id, plate="ACC-AMB-ADJUST")
    adjusted_vehicle_id = int(adjusted["id"])
    db.add(InventoryLocation(
        company_id=company_id, name="Ambiguous adjustment historical custody",
        code=f"VEH-HIST-ADJUST-{adjusted_vehicle_id}", location_type="VEHICLE",
        vehicle_id=adjusted_vehicle_id, is_active=False, version=1,
    ))
    adjust_route = DispatchRoute(
        company_id=company_id, zone_id=adjust_zone_id, driver_id=adjust_field_id,
        vehicle_id=adjusted_vehicle_id, source_location_id=gate["wh_a_id"],
        dispatch_date=await dispatch_api.get_company_local_date(db, company_id),
        status="active",
    )
    db.add(adjust_route)
    await db.commit()
    adjust_route_id = int(adjust_route.id)
    with pytest.raises(HTTPException) as adjust_exc:
        await dispatch_api.adjust_route_inventory(
            adjust_route_id,
            AdjustRouteInventoryRequest(
                request_id=uuid4(),
                deltas=[InventoryAdjustmentDelta(product_id=variant_id, delta_cartons=1)],
            ),
            db=db, access=owner.access(db), legacy_actor=owner.operational_driver,
        )
    assert adjust_exc.value.status_code == 409
    assert adjust_exc.value.detail["code"] == "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS"
    assert await _count(db, InventoryBalance, InventoryBalance.company_id == company_id) == before_balances


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


async def _seed_driver_operational_context(gate, *, plate: str, password: str, with_visit: bool = False):
    db = gate["db"]
    company_id = gate["company_id"]
    field = await seed_field_fixture(db, company_id, password=password)
    driver_id = int(field.driver.id)
    vehicle = await _create_vehicle(db, gate["owner"], company_id, plate=plate)
    vehicle_id = int(vehicle["id"])
    custody_id = int(await dispatch_api._dispatch_vehicle_location_id(
        db, company_id=company_id, vehicle_id=vehicle_id, require_active=True
    ))
    zone = Zone(company_id=company_id, name=f"{plate} Zone")
    db.add(zone)
    await db.flush()
    session = WorkSession(
        company_id=company_id,
        driver_id=driver_id,
        session_date=date.today(),
        is_authorized_to_sell=True,
        is_settled=False,
    )
    db.add(session)
    await db.flush()
    route = DispatchRoute(
        company_id=company_id,
        zone_id=int(zone.id),
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        work_session_id=int(session.id),
        source_location_id=gate["wh_a_id"],
        dispatch_date=await dispatch_api.get_company_local_date(db, company_id),
        status="active",
    )
    db.add(route)
    await db.flush()
    visit = None
    shop = None
    if with_visit:
        shop = Shop(
            company_id=company_id,
            name=f"{plate} Shop",
            zone_id=int(zone.id),
            current_balance=Decimal("0"),
            max_debt_limit=Decimal("0"),
            is_active=True,
        )
        db.add(shop)
        await db.flush()
        visit = Visit(
            id=1_800_000_000 + int(uuid4().hex[:7], 16) % 250_000_000,
            company_id=company_id,
            driver_id=driver_id,
            shop_id=int(shop.id),
            work_session_id=int(session.id),
            operational_date=date.today(),
            status="Pending",
            outcome="Pending",
        )
        db.add(visit)
        await db.flush()
    await db.commit()
    return SimpleNamespace(
        field=field,
        driver=SimpleNamespace(id=driver_id, company_id=company_id),
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        custody_id=custody_id,
        zone_id=int(zone.id),
        session_id=int(session.id),
        route_id=int(route.id),
        visit_id=(int(visit.id) if visit is not None else None),
        shop_id=(int(shop.id) if shop is not None else None),
    )


async def _add_historical_custody(db, *, company_id: int, vehicle_id: int, suffix: str, active: bool = False):
    row = InventoryLocation(
        company_id=company_id,
        name=f"Historical custody {suffix}",
        code=f"VEH-HIST-{suffix}-{vehicle_id}",
        location_type="VEHICLE",
        vehicle_id=vehicle_id,
        is_active=active,
        version=1,
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_batch_and_balance(gate, *, location_id: int, quantity: int, suffix: str, reserved: int = 0):
    db = gate["db"]
    company_id = gate["company_id"]
    variant_id = gate["variant_id"]
    batch = ProductBatch(
        company_id=company_id,
        product_variant_id=variant_id,
        batch_number=f"ACC-{suffix}-{uuid4().hex[:10]}",
        disposition="RELEASED",
        is_active=True,
    )
    db.add(batch)
    await db.flush()
    balance = InventoryBalance(
        company_id=company_id,
        location_id=location_id,
        product_variant_id=variant_id,
        batch_id=int(batch.id),
        stock_status="AVAILABLE",
        on_hand_quantity=quantity,
        reserved_quantity=reserved,
    )
    db.add(balance)
    await db.flush()
    return int(batch.id)


async def _seed_handshake(gate, ctx, *, suffix: str, quantity: int = 1):
    db = gate["db"]
    company_id = gate["company_id"]
    batch_id = await _seed_batch_and_balance(
        gate, location_id=ctx.custody_id, quantity=max(quantity, 2), suffix=suffix, reserved=quantity
    )
    header = InventoryTransferHeader(
        company_id=company_id,
        reference_number=f"HS-ACC-{suffix}-{uuid4().hex[:10]}",
        source_location_id=ctx.custody_id,
        destination_location_id=gate["wh_a_id"],
        workflow_type="HANDSHAKE",
        status="PENDING",
        transfer_purpose="ROUTE_RETURN",
        commercial_context={"schema_version": 1, "route_id": ctx.route_id},
        work_session_id=ctx.session_id,
        expected_receiver_id=ctx.driver_id,
        dispatched_by=gate["owner"].driver_id,
    )
    db.add(header)
    await db.flush()
    variant = await db.get(ProductVariant, gate["variant_id"])
    db.add(InventoryTransferLine(
        company_id=company_id,
        transfer_header_id=int(header.id),
        product_variant_id=gate["variant_id"],
        batch_id=batch_id,
        quantity=quantity,
        source_stock_status="AVAILABLE",
        lifecycle_revision_snapshot=int(variant.lifecycle_revision),
        lifecycle_status_snapshot=str(variant.lifecycle_status),
        operational_hold_snapshot=str(variant.operational_hold),
    ))
    await db.commit()
    return int(header.id), batch_id


@pytest.mark.asyncio
async def test_12a_driver_update_visit_canonical_active_positive(gate):
    db = gate["db"]
    positive = await _seed_driver_operational_context(
        gate, plate="ACC-VISIT-POS", password="SyntheticVisitPositive123", with_visit=True
    )
    result = await driver_api.update_visit(
        visit_id=positive.visit_id,
        payload=VisitUpdateRequest(
            request_id=uuid4(), outcome="NoSale", notes="Acceptance no sale", cart_items=[], returns=[]
        ),
        db=db, field_context=positive.field.context, legacy_actor=positive.driver,
    )
    assert result["message"] == "Visit updated successfully"
    visit = await db.get(Visit, positive.visit_id)
    assert visit.status == "Completed" and visit.outcome == "NoSale"


@pytest.mark.asyncio
async def test_12b_driver_update_visit_ambiguous_custody_precedes_mutation(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    ctx = await _seed_driver_operational_context(
        gate, plate="ACC-VISIT-AMB", password="SyntheticVisitAmbiguous123", with_visit=True
    )
    await _add_historical_custody(
        db, company_id=company_id, vehicle_id=ctx.vehicle_id, suffix="VISIT-AMB", active=False
    )
    await db.commit()
    before_movements = await _count(
        db, InventoryMovement,
        InventoryMovement.company_id == company_id,
        InventoryMovement.work_session_id == ctx.session_id,
    )
    caught = None
    try:
        await driver_api.update_visit(
            visit_id=ctx.visit_id,
            payload=VisitUpdateRequest(
                request_id=uuid4(), outcome="NoSale", notes="Acceptance no sale", cart_items=[], returns=[]
            ),
            db=db, field_context=ctx.field.context, legacy_actor=ctx.driver,
        )
    except HTTPException as exc:
        caught = exc
    after_movements = await _count(
        db, InventoryMovement,
        InventoryMovement.company_id == company_id,
        InventoryMovement.work_session_id == ctx.session_id,
    )
    visit = await db.get(Visit, ctx.visit_id)
    assert caught is not None and caught.status_code == 409, (
        f"update_visit accepted ambiguous custody; visit={visit.status}/{visit.outcome}; "
        f"movements_before={before_movements}; movements_after={after_movements}"
    )
    assert after_movements == before_movements
    assert visit.status == "Pending" and visit.outcome == "Pending"


@pytest.mark.asyncio
async def test_13a_single_handshake_canonical_active_positive(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    ctx = await _seed_driver_operational_context(
        gate, plate="ACC-HS-SINGLE-POS", password="SyntheticHsSinglePositive123"
    )
    header_id, _ = await _seed_handshake(gate, ctx, suffix="SINGLE-POS")
    result = await driver_api.respond_to_transfer(
        transfer_id=header_id, payload=TransferResponseRequest(response="accepted"),
        db=db, field_context=ctx.field.context, legacy_actor=ctx.driver,
    )
    assert result["message"]
    header = await db.get(InventoryTransferHeader, header_id)
    assert header.status == "POSTED" and int(header.received_by) == ctx.driver_id
    assert await _count(
        db, InventoryMovement,
        InventoryMovement.company_id == company_id,
        InventoryMovement.transfer_header_id == header_id,
    ) == 2


@pytest.mark.asyncio
async def test_13b_single_handshake_active_plus_inactive_duplicate_fails_closed(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    ctx = await _seed_driver_operational_context(
        gate, plate="ACC-HS-SINGLE-AMB", password="SyntheticHsSingleAmb123"
    )
    header_id, _ = await _seed_handshake(gate, ctx, suffix="SINGLE-AMB")
    await _add_historical_custody(
        db, company_id=company_id, vehicle_id=ctx.vehicle_id, suffix="HS-SINGLE-AMB", active=False
    )
    await db.commit()
    before = await _count(
        db, InventoryMovement,
        InventoryMovement.company_id == company_id,
        InventoryMovement.transfer_header_id == header_id,
    )
    caught = None
    try:
        await driver_api.respond_to_transfer(
            transfer_id=header_id, payload=TransferResponseRequest(response="accepted"),
            db=db, field_context=ctx.field.context, legacy_actor=ctx.driver,
        )
    except HTTPException as exc:
        caught = exc
    after = await _count(
        db, InventoryMovement,
        InventoryMovement.company_id == company_id,
        InventoryMovement.transfer_header_id == header_id,
    )
    header = await db.get(InventoryTransferHeader, header_id)
    assert caught is not None and caught.status_code == 409, (
        f"single handshake accepted ambiguous custody; status={header.status}; "
        f"movements_before={before}; movements_after={after}"
    )
    assert after == before and header.status == "PENDING"


@pytest.mark.asyncio
async def test_13c_single_handshake_multiple_inactive_fails_closed(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    ctx = await _seed_driver_operational_context(
        gate, plate="ACC-HS-SINGLE-INACT", password="SyntheticHsSingleInactive123"
    )
    header_id, _ = await _seed_handshake(gate, ctx, suffix="SINGLE-INACT")
    canonical = await db.get(InventoryLocation, ctx.custody_id)
    canonical.is_active = False
    await _add_historical_custody(db, company_id=company_id, vehicle_id=ctx.vehicle_id, suffix="HS-SINGLE-I1")
    await _add_historical_custody(db, company_id=company_id, vehicle_id=ctx.vehicle_id, suffix="HS-SINGLE-I2")
    await db.commit()
    before = await _count(db, InventoryMovement, InventoryMovement.transfer_header_id == header_id)
    with pytest.raises(HTTPException) as exc:
        await driver_api.respond_to_transfer(
            transfer_id=header_id, payload=TransferResponseRequest(response="accepted"),
            db=db, field_context=ctx.field.context, legacy_actor=ctx.driver,
        )
    assert exc.value.status_code == 409
    assert await _count(db, InventoryMovement, InventoryMovement.transfer_header_id == header_id) == before


@pytest.mark.asyncio
async def test_14a_batch_handshake_canonical_active_positive(gate):
    db = gate["db"]
    ctx = await _seed_driver_operational_context(
        gate, plate="ACC-HS-BATCH-POS", password="SyntheticHsBatchPositive123"
    )
    header_id, _ = await _seed_handshake(gate, ctx, suffix="BATCH-POS")
    result = await driver_api.batch_respond_to_transfers(
        payload=BatchTransferResponseRequest(transfers=[{"transfer_id": header_id, "status": "accepted"}]),
        db=db, field_context=ctx.field.context, legacy_actor=ctx.driver,
    )
    assert result["message"]
    header = await db.get(InventoryTransferHeader, header_id)
    assert header.status == "POSTED" and int(header.received_by) == ctx.driver_id


@pytest.mark.asyncio
async def test_14b_batch_handshake_active_plus_inactive_duplicate_fails_closed(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    ctx = await _seed_driver_operational_context(
        gate, plate="ACC-HS-BATCH-AMB", password="SyntheticHsBatchAmb123"
    )
    header_id, _ = await _seed_handshake(gate, ctx, suffix="BATCH-AMB")
    await _add_historical_custody(
        db, company_id=company_id, vehicle_id=ctx.vehicle_id, suffix="HS-BATCH-AMB", active=False
    )
    await db.commit()
    before = await _count(db, InventoryMovement, InventoryMovement.transfer_header_id == header_id)
    caught = None
    try:
        await driver_api.batch_respond_to_transfers(
            payload=BatchTransferResponseRequest(transfers=[{"transfer_id": header_id, "status": "accepted"}]),
            db=db, field_context=ctx.field.context, legacy_actor=ctx.driver,
        )
    except HTTPException as exc:
        caught = exc
    after = await _count(db, InventoryMovement, InventoryMovement.transfer_header_id == header_id)
    header = await db.get(InventoryTransferHeader, header_id)
    assert caught is not None and caught.status_code == 409, (
        f"batch handshake accepted ambiguous custody; status={header.status}; "
        f"movements_before={before}; movements_after={after}"
    )
    assert after == before and header.status == "PENDING"


@pytest.mark.asyncio
async def test_14c_batch_handshake_multiple_inactive_fails_closed(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    ctx = await _seed_driver_operational_context(
        gate, plate="ACC-HS-BATCH-INACT", password="SyntheticHsBatchInactive123"
    )
    header_id, _ = await _seed_handshake(gate, ctx, suffix="BATCH-INACT")
    canonical = await db.get(InventoryLocation, ctx.custody_id)
    canonical.is_active = False
    await _add_historical_custody(db, company_id=company_id, vehicle_id=ctx.vehicle_id, suffix="HS-BATCH-I1")
    await _add_historical_custody(db, company_id=company_id, vehicle_id=ctx.vehicle_id, suffix="HS-BATCH-I2")
    await db.commit()
    before = await _count(db, InventoryMovement, InventoryMovement.transfer_header_id == header_id)
    with pytest.raises(HTTPException) as exc:
        await driver_api.batch_respond_to_transfers(
            payload=BatchTransferResponseRequest(transfers=[{"transfer_id": header_id, "status": "accepted"}]),
            db=db, field_context=ctx.field.context, legacy_actor=ctx.driver,
        )
    assert exc.value.status_code == 409
    assert await _count(db, InventoryMovement, InventoryMovement.transfer_header_id == header_id) == before


@pytest.mark.asyncio
async def test_15_driver_inventory_projection_rejects_ambiguous_custody(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    ctx = await _seed_driver_operational_context(
        gate, plate="ACC-DRIVER-PROJ", password="SyntheticDriverProjection123"
    )
    await _add_historical_custody(
        db, company_id=company_id, vehicle_id=ctx.vehicle_id, suffix="DRIVER-PROJ", active=False
    )
    await db.commit()
    caught = None
    try:
        await driver_api._load_vehicle_inventory_projection(
            db,
            company_id=company_id,
            vehicle_id=ctx.vehicle_id,
            work_session_id=ctx.session_id,
        )
    except HTTPException as exc:
        caught = exc
    assert caught is not None and caught.status_code == 409, (
        "_load_vehicle_inventory_projection silently selected one active custody from an ambiguous mapping"
    )


@pytest.mark.asyncio
async def test_16_dispatch_session_projection_no_snapshot_rejects_first_row_wins(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    ctx = await _seed_driver_operational_context(
        gate, plate="ACC-DSP-PROJ", password="SyntheticDispatchProjection123"
    )
    await _add_historical_custody(
        db, company_id=company_id, vehicle_id=ctx.vehicle_id, suffix="DSP-PROJ", active=False
    )
    await db.commit()
    session = await db.get(WorkSession, ctx.session_id)
    caught = None
    try:
        await dispatch_api._dispatch_session_inventory_projection(
            db,
            company_id=company_id,
            sessions=[session],
        )
    except HTTPException as exc:
        caught = exc
    assert caught is not None and caught.status_code == 409, (
        "dispatch no-snapshot projection silently used first historical VEHICLE location"
    )


@pytest.mark.asyncio
async def test_17_dispatch_init_selector_requires_strict_operational_custody(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    owner = gate["owner"]

    active = await _create_vehicle(db, owner, company_id, plate="ACC-INIT-A")
    missing = await _create_vehicle(db, owner, company_id, plate="ACC-INIT-B")
    duplicate = await _create_vehicle(db, owner, company_id, plate="ACC-INIT-C")
    inactive = await _create_vehicle(db, owner, company_id, plate="ACC-INIT-D")
    maintenance = await _create_vehicle(db, owner, company_id, plate="ACC-INIT-E")

    missing_id = int(missing["id"])
    duplicate_id = int(duplicate["id"])
    inactive_id = int(inactive["id"])
    maintenance_id = int(maintenance["id"])
    await db.execute(delete(InventoryLocation).where(
        InventoryLocation.company_id == company_id,
        InventoryLocation.vehicle_id == missing_id,
        InventoryLocation.location_type == "VEHICLE",
    ))
    await _add_historical_custody(
        db, company_id=company_id, vehicle_id=duplicate_id, suffix="INIT-C", active=False
    )
    inactive_custody = await db.scalar(select(InventoryLocation).where(
        InventoryLocation.company_id == company_id,
        InventoryLocation.vehicle_id == inactive_id,
        InventoryLocation.location_type == "VEHICLE",
    ))
    inactive_custody.is_active = False
    maintenance_vehicle = await db.get(Vehicle, maintenance_id)
    maintenance_vehicle.maintenance_status = "In_Maintenance"
    await db.commit()

    init = await dispatch_api.dispatch_init(db=db, access=owner.access(db))
    selector = {int(item["id"]): bool(item["can_execute"]) for item in init["vehicles"]}
    assert selector.get(int(active["id"])) is True
    observed = {
        "missing": selector.get(missing_id),
        "duplicate": selector.get(duplicate_id),
        "inactive": selector.get(inactive_id),
        "maintenance": selector.get(maintenance_id),
    }
    wrongly_selectable = {name: value for name, value in observed.items() if value is True}
    assert not wrongly_selectable, f"noncanonical/not-operational vehicles selectable: {wrongly_selectable}"


async def _seed_route_status_inventory_context(gate, *, suffix: str, with_session: bool):
    db = gate["db"]
    company_id = gate["company_id"]
    owner = gate["owner"]
    field = await seed_field_fixture(db, company_id, password=f"SyntheticStatus{suffix}123")
    vehicle = await _create_vehicle(db, owner, company_id, plate=f"ACC-STATUS-{suffix}")
    vehicle_id = int(vehicle["id"])
    custody_id = int(await dispatch_api._dispatch_vehicle_location_id(
        db, company_id=company_id, vehicle_id=vehicle_id, require_active=True
    ))
    zone = Zone(company_id=company_id, name=f"Status {suffix} Zone")
    db.add(zone)
    await db.flush()
    session = None
    route = DispatchRoute(
        company_id=company_id,
        zone_id=int(zone.id),
        driver_id=int(field.driver.id),
        vehicle_id=vehicle_id,
        work_session_id=None,
        source_location_id=gate["wh_a_id"],
        dispatch_date=await dispatch_api.get_company_local_date(db, company_id),
        status=("active" if with_session else "waiting"),
    )
    db.add(route)
    await db.flush()
    if with_session:
        commercial_context = await _seed_route_context(db, company_id, route)
        session = WorkSession(
            company_id=company_id,
            driver_id=int(field.driver.id),
            commercial_context_id=int(commercial_context.id),
            session_date=date.today(),
            is_authorized_to_sell=True,
            is_settled=False,
        )
        db.add(session)
        await db.flush()
        route.work_session_id = int(session.id)
        await db.flush()
    batch_id = await _seed_batch_and_balance(
        gate, location_id=gate["wh_a_id"], quantity=50, suffix=f"STATUS-{suffix}"
    )
    existing_assignment = await db.scalar(select(ProductLocation).where(
        ProductLocation.company_id == company_id,
        ProductLocation.location_id == gate["wh_a_id"],
        ProductLocation.product_variant_id == gate["variant_id"],
    ))
    if existing_assignment is None:
        db.add(ProductLocation(
            company_id=company_id,
            location_id=gate["wh_a_id"],
            product_variant_id=gate["variant_id"],
            operational_flags=dict(DEFAULT_PRODUCT_LOCATION_FLAGS),
            created_by=owner.driver_id,
        ))
    await db.commit()
    return SimpleNamespace(
        route_id=int(route.id),
        vehicle_id=vehicle_id,
        custody_id=custody_id,
        driver_id=int(field.driver.id),
        session_id=(int(session.id) if session is not None else None),
        batch_id=batch_id,
    )


@pytest.mark.asyncio
async def test_18_route_status_inventory_direct_path_consequence_provenance_retry_and_rollback(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    owner = gate["owner"]
    ctx = await _seed_route_status_inventory_context(gate, suffix="DIRECT", with_session=False)
    variant = await db.get(ProductVariant, gate["variant_id"])
    packs_per_carton = int(variant.packs_per_carton)

    caught = None
    try:
        await dispatch_api.update_route_status(
            ctx.route_id,
            UpdateRouteStatusRequest(status="waiting", inventory={str(gate["variant_id"]): 1}),
            db=db,
            access=owner.access(db),
            legacy_actor=owner.operational_driver,
        )
    except HTTPException as exc:
        caught = exc
    assert caught is None or caught.status_code != 500, (
        f"route status inventory DIRECT raised HTTP {caught.status_code if caught else None}: {caught.detail if caught else None}"
    )
    assert caught is None
    movements = (
        await db.execute(select(InventoryMovement).where(
            InventoryMovement.company_id == company_id,
            InventoryMovement.reference_type == "DISPATCH_LOAD",
            InventoryMovement.reference_id == str(ctx.route_id),
        ))
    ).scalars().all()
    assert sum(int(m.quantity) for m in movements) == packs_per_carton
    assert {int(m.performed_by) for m in movements} == {int(owner.operational_driver.id)}

    movement_count = len(movements)
    await dispatch_api.update_route_status(
        ctx.route_id,
        UpdateRouteStatusRequest(status="waiting", inventory={str(gate["variant_id"]): 1}),
        db=db,
        access=owner.access(db),
        legacy_actor=owner.operational_driver,
    )
    assert await _count(
        db, InventoryMovement,
        InventoryMovement.company_id == company_id,
        InventoryMovement.reference_type == "DISPATCH_LOAD",
        InventoryMovement.reference_id == str(ctx.route_id),
    ) == movement_count

    before_bad = await _count(db, InventoryMovement, InventoryMovement.company_id == company_id)
    with pytest.raises(HTTPException):
        await dispatch_api.update_route_status(
            ctx.route_id,
            UpdateRouteStatusRequest(status="waiting", inventory={str(gate["variant_id"]): 999999}),
            db=db,
            access=owner.access(db),
            legacy_actor=owner.operational_driver,
        )
    assert await _count(db, InventoryMovement, InventoryMovement.company_id == company_id) == before_bad


@pytest.mark.asyncio
async def test_19_route_status_inventory_active_session_handshake_path(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    owner = gate["owner"]
    ctx = await _seed_route_status_inventory_context(gate, suffix="HANDSHAKE", with_session=True)
    caught = None
    try:
        await dispatch_api.update_route_status(
            ctx.route_id,
            UpdateRouteStatusRequest(status="active", inventory={str(gate["variant_id"]): 1}),
            db=db,
            access=owner.access(db),
            legacy_actor=owner.operational_driver,
        )
    except HTTPException as exc:
        caught = exc
    assert caught is None or caught.status_code != 500, (
        f"route status inventory HANDSHAKE raised HTTP {caught.status_code if caught else None}: {caught.detail if caught else None}"
    )
    assert caught is None
    headers = (
        await db.execute(select(InventoryTransferHeader).where(
            InventoryTransferHeader.company_id == company_id,
            InventoryTransferHeader.work_session_id == ctx.session_id,
            InventoryTransferHeader.workflow_type == "HANDSHAKE",
        ))
    ).scalars().all()
    assert len(headers) == 1
    header = headers[0]
    assert header.status == "PENDING"
    assert int(header.dispatched_by) == int(owner.operational_driver.id)
    assert int(header.expected_receiver_id) == ctx.driver_id
    reservation_movements = (
        await db.execute(select(InventoryMovement).where(
            InventoryMovement.company_id == company_id,
            InventoryMovement.transfer_header_id == int(header.id),
            InventoryMovement.movement_kind == "RESERVATION",
        ))
    ).scalars().all()
    assert reservation_movements
    assert {int(m.performed_by) for m in reservation_movements} == {int(owner.operational_driver.id)}
