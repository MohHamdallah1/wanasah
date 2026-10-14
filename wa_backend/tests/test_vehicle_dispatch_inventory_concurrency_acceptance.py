from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from asyncpg import Range
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api import dispatch as dispatch_api
from api import driver as driver_api
from domains.pricing.context import lock_route_commercial_context
from domains.sales_calculation.policy import publish_commercial_rounding_policy
from domains.taxation.models import (
    TaxJurisdiction,
    TaxRuleComponent,
    TaxRuleScope,
    TaxRuleSet,
    TaxRuleSetVersion,
)
from domains.taxation.publishing import publish_version as publish_tax_version
from domains.vehicles.contracts import (
    CreateVehicleCommand,
    UpdateVehicleCommand,
    VehicleError,
    VehicleLifecycleCommand,
)
from domains.vehicles.lifecycle import deactivate_vehicle
from domains.vehicles.management import create_vehicle, update_vehicle
from models import (
    Base,
    Company,
    DispatchRoute,
    InventoryBalance,
    InventoryLocation,
    InventoryMovement,
    PriceBook,
    PriceBookAssignment,
    PriceBookEntry,
    PricePublication,
    Product,
    ProductBatch,
    ProductLocation,
    ProductVariant,
    RouteCommercialContext,
    SessionInventorySnapshot,
    UOM,
    Vehicle,
    WorkSession,
    Zone,
)
from product_lifecycle import DEFAULT_PRODUCT_LOCATION_FLAGS
from schemas import (
    AdjustRouteInventoryRequest,
    DispatchRouteRequest,
    InventoryAdjustmentDelta,
    SessionStartRequest,
)
from tests.canonical_actor_fixtures import (
    seed_company_owner_fixture,
    seed_field_fixture,
)


GATE_ENV = "WANASAH_VEHICLE_DISPATCH_CONCURRENCY_DB_GATE"
LOCK_TIMEOUT_MS = 3000
STATEMENT_TIMEOUT_MS = 10000


@dataclass(frozen=True)
class OperationOutcome:
    name: str
    ok: bool
    kind: str
    status: int | None = None
    code: str | None = None
    detail: str = ""


class PairBarrier:
    def __init__(self) -> None:
        self._ready = 0
        self._lock = asyncio.Lock()
        self._event = asyncio.Event()

    async def wait(self) -> None:
        async with self._lock:
            self._ready += 1
            if self._ready == 2:
                self._event.set()
        await self._event.wait()


def _gate_enabled() -> bool:
    return os.getenv(GATE_ENV) == "1"


def _sqlstate(exc: BaseException) -> str | None:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if code:
            return str(code)
        current = getattr(current, "orig", None) or getattr(current, "__cause__", None)
    return None


def _classify(name: str, exc: BaseException) -> OperationOutcome:
    code = _sqlstate(exc)
    if code == "40P01":
        return OperationOutcome(name, False, "deadlock", code=code, detail=str(exc))
    if code == "55P03":
        return OperationOutcome(name, False, "lock_timeout", code=code, detail=str(exc))
    if code == "57014":
        return OperationOutcome(name, False, "statement_timeout", code=code, detail=str(exc))
    if isinstance(exc, VehicleError):
        return OperationOutcome(
            name,
            False,
            "business_conflict",
            status=int(exc.status_code),
            code=str(exc.code),
            detail=str(exc.message),
        )
    if isinstance(exc, HTTPException):
        app_code = None
        if isinstance(exc.detail, dict):
            app_code = exc.detail.get("code")
        return OperationOutcome(
            name,
            False,
            "business_conflict" if int(exc.status_code) < 500 else "http_error",
            status=int(exc.status_code),
            code=str(app_code) if app_code is not None else None,
            detail=str(exc.detail),
        )
    if isinstance(exc, IntegrityError):
        return OperationOutcome(name, False, "integrity_conflict", code=code, detail=str(exc))
    if isinstance(exc, DBAPIError):
        return OperationOutcome(name, False, "database_error", code=code, detail=str(exc))
    return OperationOutcome(name, False, "error", code=code, detail=f"{type(exc).__name__}: {exc}")


async def _set_timeouts(db: AsyncSession) -> None:
    await db.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT_MS}ms'"))
    await db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'"))


async def _run_concurrent_operation(Session, barrier: PairBarrier, name: str, operation) -> OperationOutcome:
    async with Session() as db:
        await _set_timeouts(db)
        await barrier.wait()
        try:
            await operation(db)
            return OperationOutcome(name, True, "success")
        except BaseException as exc:  # explicit evidence classification for concurrency failures
            try:
                await db.rollback()
            except Exception:
                pass
            return _classify(name, exc)


def _assert_no_lock_failure(*outcomes: OperationOutcome) -> None:
    for outcome in outcomes:
        assert outcome.kind != "deadlock", f"PostgreSQL deadlock: {outcome}"
        assert outcome.kind != "lock_timeout", f"PostgreSQL lock timeout: {outcome}"
        assert outcome.kind != "statement_timeout", f"PostgreSQL statement timeout: {outcome}"


async def _seed_commercial_authority(db: AsyncSession, *, company_id: int, actor_id: int, variant_id: int, uom_id: int) -> None:
    now = datetime.now(timezone.utc)
    earlier = now - timedelta(days=5)
    suffix = uuid4().hex[:10].upper()
    book = PriceBook(
        company_id=company_id,
        code=f"VCBOOK{suffix}",
        name="Vehicle concurrency price book",
        currency_code="JOD",
        status="ACTIVE",
        created_by=actor_id,
    )
    db.add(book)
    await db.flush()
    publication = PricePublication(
        company_id=company_id,
        price_book_id=book.id,
        revision=1,
        status="PUBLISHED",
        effective_at=earlier,
        published_at=earlier,
        approved_at=earlier,
        approved_by=actor_id,
        created_by=actor_id,
        request_id=uuid4(),
    )
    db.add(publication)
    await db.flush()
    window = Range(lower=earlier, upper=None, lower_inc=True)
    db.add_all([
        PriceBookEntry(
            company_id=company_id,
            price_book_id=book.id,
            publication_id=publication.id,
            product_variant_id=variant_id,
            uom_id=uom_id,
            amount=Decimal("5.000000"),
            effectivity=window,
            is_published=True,
            priority=0,
            entry_metadata={},
        ),
        PriceBookAssignment(
            company_id=company_id,
            price_book_id=book.id,
            scope_type="COMPANY_DEFAULT",
            scope_id=None,
            revision=1,
            priority=0,
            allow_offers=False,
            effectivity=window,
            created_by=actor_id,
        ),
    ])
    jurisdiction = TaxJurisdiction(
        company_id=company_id,
        code=f"VCJO{suffix}",
        name="Vehicle concurrency zero tax",
        jurisdiction_type="COUNTRY",
        country_code="JO",
        created_by=actor_id,
        is_active=True,
    )
    rule = TaxRuleSet(
        company_id=company_id,
        code=f"VCTAX{suffix}",
        name="Vehicle concurrency tax",
        created_by=actor_id,
    )
    db.add_all([jurisdiction, rule])
    await db.flush()
    tax_revision = TaxRuleSetVersion(
        company_id=company_id,
        tax_rule_set_id=rule.id,
        revision=1,
        definition_version=1,
        status="DRAFT",
        price_mode="EXCLUSIVE",
        priority=0,
        effective_from=earlier,
        effective_to=None,
        created_by=actor_id,
        request_id=uuid4(),
    )
    db.add(tax_revision)
    await db.flush()
    db.add_all([
        TaxRuleComponent(
            company_id=company_id,
            tax_rule_set_version_id=tax_revision.id,
            component_code="ZERO",
            name="Zero tax",
            sequence=1,
            rate=Decimal("0"),
            basis_mode="TAXABLE_BASE",
        ),
        TaxRuleScope(
            company_id=company_id,
            tax_rule_set_version_id=tax_revision.id,
            scope_type="JURISDICTION",
            jurisdiction_id=jurisdiction.id,
        ),
    ])
    await db.flush()
    published = await publish_tax_version(
        db,
        company_id=company_id,
        actor_id=actor_id,
        version_id=tax_revision.id,
        expected_version=tax_revision.version,
    )
    assert published.status == "PUBLISHED"
    rounding = await publish_commercial_rounding_policy(
        db,
        company_id=company_id,
        actor_id=actor_id,
        expected_revision=0,
        precision=3,
        mode="HALF_UP",
    )
    assert rounding.rounding_policy.currency_code == "JOD"


@pytest_asyncio.fixture(scope="module")
async def gate():
    if not _gate_enabled():
        pytest.skip(f"set {GATE_ENV}=1 to run the isolated PostgreSQL concurrency gate")

    raw_url = os.environ.get("DATABASE_URL_MIGRATION") or os.environ.get("DATABASE_URL")
    if not raw_url:
        pytest.skip("DATABASE_URL[_MIGRATION] is required")
    url = make_url(raw_url)
    if not str(url.drivername).startswith("postgresql"):
        pytest.skip("PostgreSQL is required")

    schema = "vehicle_dispatch_concurrency_" + uuid4().hex
    admin_engine = create_async_engine(raw_url, poolclass=NullPool)
    async with admin_engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))

    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": f'"{schema}",public'}},
    )
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with Session() as db:
            suffix = uuid4().hex[:8]
            company = Company(
                name=f"Vehicle Concurrency {suffix}",
                company_code=f"VC-{suffix}",
                currency_code="JOD",
                timezone="Asia/Amman",
            )
            db.add(company)
            await db.flush()
            owner = await seed_company_owner_fixture(
                db, int(company.id), password="SyntheticConcurrencyOwner123"
            )
            uom = UOM(name=f"Concurrency Each {suffix}", code=f"CE{suffix[:5].upper()}")
            db.add(uom)
            await db.flush()
            product = Product(
                company_id=int(company.id),
                code=f"VCP-{suffix}",
                name="Vehicle Concurrency Product",
            )
            db.add(product)
            await db.flush()
            variant = ProductVariant(
                company_id=int(company.id),
                product_id=int(product.id),
                base_uom_id=int(uom.id),
                name="Vehicle Concurrency Variant",
                sku=f"VCSKU-{suffix}",
                quantity_scale=0,
                quantity_step=1,
                lot_control_mode="NONE",
                expiry_control_mode="NONE",
                lifecycle_status="ACTIVE",
                operational_hold="NONE",
                lifecycle_revision=1,
                version=1,
                published_at=datetime.now(timezone.utc).replace(tzinfo=None),
                packs_per_carton=10,
            )
            db.add(variant)
            await db.flush()
            batch = ProductBatch(
                company_id=int(company.id),
                product_variant_id=int(variant.id),
                batch_number=f"VC-BATCH-{suffix}",
                disposition="RELEASED",
                disposition_revision=1,
                is_active=True,
            )
            db.add(batch)
            await db.flush()
            await _seed_commercial_authority(
                db,
                company_id=int(company.id),
                actor_id=int(owner.driver_id),
                variant_id=int(variant.id),
                uom_id=int(uom.id),
            )
            await db.commit()

            gate_data = {
                "Session": Session,
                "company_id": int(company.id),
                "owner": owner,
                "variant_id": int(variant.id),
                "uom_id": int(uom.id),
                "batch_id": int(batch.id),
                "schema": schema,
            }

        yield gate_data
    finally:
        await engine.dispose()
        async with admin_engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


async def _create_vehicle_record(db: AsyncSession, gate, *, plate: str):
    payload = await create_vehicle(
        db,
        company_id=gate["company_id"],
        actor_id=gate["owner"].driver_id,
        command=CreateVehicleCommand(
            request_id=str(uuid4()),
            plate_number=plate,
            vehicle_type="Van",
            maintenance_status="Active",
        ),
    )
    vehicle_id = int(payload["id"])
    vehicle = await db.get(Vehicle, vehicle_id)
    custody_rows = (
        await db.execute(
            select(InventoryLocation)
            .where(
                InventoryLocation.company_id == gate["company_id"],
                InventoryLocation.vehicle_id == vehicle_id,
                InventoryLocation.location_type == "VEHICLE",
            )
            .order_by(InventoryLocation.id.asc())
        )
    ).scalars().all()
    assert len(custody_rows) == 1
    return vehicle, custody_rows[0]


async def _seed_route_context(db: AsyncSession, gate, route: DispatchRoute) -> RouteCommercialContext:
    context = RouteCommercialContext(
        company_id=gate["company_id"],
        dispatch_route_id=int(route.id),
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


async def _seed_source_inventory(db: AsyncSession, gate, *, suffix: str, quantity: int = 100) -> int:
    source = InventoryLocation(
        company_id=gate["company_id"],
        name=f"Concurrency Warehouse {suffix}",
        code=f"VC-WH-{suffix}-{uuid4().hex[:6]}",
        location_type="WAREHOUSE",
        is_active=True,
    )
    db.add(source)
    await db.flush()
    db.add(ProductLocation(
        company_id=gate["company_id"],
        location_id=int(source.id),
        product_variant_id=gate["variant_id"],
        operational_flags=dict(DEFAULT_PRODUCT_LOCATION_FLAGS),
        created_by=gate["owner"].driver_id,
    ))
    db.add(InventoryBalance(
        company_id=gate["company_id"],
        location_id=int(source.id),
        product_variant_id=gate["variant_id"],
        batch_id=gate["batch_id"],
        stock_status="AVAILABLE",
        on_hand_quantity=Decimal(quantity),
        reserved_quantity=Decimal("0"),
    ))
    await db.flush()
    return int(source.id)


async def _seed_vehicle_balance(db: AsyncSession, gate, *, custody_id: int, quantity: int) -> None:
    db.add(InventoryBalance(
        company_id=gate["company_id"],
        location_id=custody_id,
        product_variant_id=gate["variant_id"],
        batch_id=gate["batch_id"],
        stock_status="AVAILABLE",
        on_hand_quantity=Decimal(quantity),
        reserved_quantity=Decimal("0"),
    ))
    await db.flush()


async def _seed_operational_route(
    gate,
    *,
    suffix: str,
    source_inventory: int = 0,
    vehicle_inventory: int = 0,
):
    Session = gate["Session"]
    async with Session() as db:
        field = await seed_field_fixture(
            db,
            gate["company_id"],
            password=f"SyntheticConcurrency{suffix}{uuid4().hex[:6]}",
        )
        field_context = field.context
        field_driver_id = int(field.driver.id)
        vehicle, custody = await _create_vehicle_record(
            db, gate, plate=f"VC{uuid4().hex[:14].upper()}"
        )
        source_id = await _seed_source_inventory(
            db,
            gate,
            suffix=suffix,
            quantity=max(source_inventory, 1),
        )
        if source_inventory <= 0:
            balance = await db.scalar(select(InventoryBalance).where(
                InventoryBalance.company_id == gate["company_id"],
                InventoryBalance.location_id == source_id,
                InventoryBalance.product_variant_id == gate["variant_id"],
            ))
            await db.delete(balance)
        if vehicle_inventory > 0:
            await _seed_vehicle_balance(
                db,
                gate,
                custody_id=int(custody.id),
                quantity=vehicle_inventory,
            )
        zone = Zone(
            company_id=gate["company_id"],
            name=f"Concurrency Zone {suffix} {uuid4().hex[:6]}",
        )
        db.add(zone)
        await db.flush()
        route = DispatchRoute(
            company_id=gate["company_id"],
            zone_id=int(zone.id),
            driver_id=field_driver_id,
            vehicle_id=int(vehicle.id),
            source_location_id=source_id,
            dispatch_date=await dispatch_api.get_company_local_date(db, gate["company_id"]),
            status="active",
        )
        db.add(route)
        await db.flush()
        await _seed_route_context(db, gate, route)
        await db.commit()
        return SimpleNamespace(
            field_context=field_context,
            field_driver=SimpleNamespace(id=field_driver_id, company_id=gate["company_id"]),
            driver_id=field_driver_id,
            vehicle_id=int(vehicle.id),
            vehicle_version=int(vehicle.version),
            custody_id=int(custody.id),
            source_id=source_id,
            zone_id=int(zone.id),
            route_id=int(route.id),
        )


async def _vehicle_state(db: AsyncSession, gate, vehicle_id: int):
    vehicle = await db.get(Vehicle, vehicle_id)
    custody = (
        await db.execute(
            select(InventoryLocation)
            .where(
                InventoryLocation.company_id == gate["company_id"],
                InventoryLocation.vehicle_id == vehicle_id,
                InventoryLocation.location_type == "VEHICLE",
            )
            .order_by(InventoryLocation.id.asc())
        )
    ).scalars().all()
    routes = (
        await db.execute(
            select(DispatchRoute)
            .where(
                DispatchRoute.company_id == gate["company_id"],
                DispatchRoute.vehicle_id == vehicle_id,
            )
            .order_by(DispatchRoute.id.asc())
        )
    ).scalars().all()
    return vehicle, custody, routes


async def _available_total(db: AsyncSession, gate, location_id: int) -> Decimal:
    value = await db.scalar(select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0)).where(
        InventoryBalance.company_id == gate["company_id"],
        InventoryBalance.location_id == location_id,
        InventoryBalance.product_variant_id == gate["variant_id"],
        InventoryBalance.stock_status == "AVAILABLE",
    ))
    return Decimal(value or 0)


@pytest.mark.asyncio
async def test_01_vehicle_deactivate_vs_driver_session_start(gate):
    ctx = await _seed_operational_route(gate, suffix="DEACT-START")
    barrier = PairBarrier()

    async def deactivate(db):
        await deactivate_vehicle(
            db,
            company_id=gate["company_id"],
            actor_id=gate["owner"].driver_id,
            vehicle_id=ctx.vehicle_id,
            command=VehicleLifecycleCommand(
                request_id=str(uuid4()), expected_version=ctx.vehicle_version
            ),
        )

    async def start_session(db):
        await driver_api.start_work_session(
            SessionStartRequest(),
            db=db,
            field_context=ctx.field_context,
            legacy_actor=ctx.field_driver,
        )

    deactivate_outcome, session_outcome = await asyncio.gather(
        _run_concurrent_operation(gate["Session"], barrier, "deactivate", deactivate),
        _run_concurrent_operation(gate["Session"], barrier, "session_start", start_session),
    )
    _assert_no_lock_failure(deactivate_outcome, session_outcome)
    assert int(deactivate_outcome.ok) + int(session_outcome.ok) == 1, (
        deactivate_outcome,
        session_outcome,
    )

    async with gate["Session"]() as db:
        vehicle, custody, routes = await _vehicle_state(db, gate, ctx.vehicle_id)
        route = next(row for row in routes if int(row.id) == ctx.route_id)
        active_sessions = (
            await db.execute(
                select(WorkSession)
                .join(
                    DispatchRoute,
                    (DispatchRoute.company_id == WorkSession.company_id)
                    & (DispatchRoute.work_session_id == WorkSession.id),
                )
                .where(
                    WorkSession.company_id == gate["company_id"],
                    DispatchRoute.vehicle_id == ctx.vehicle_id,
                    WorkSession.end_time.is_(None),
                )
            )
        ).scalars().all()
        assert len(custody) == 1
        assert int(custody[0].id) == ctx.custody_id
        assert not (vehicle.is_active is False and active_sessions), (
            "inactive Vehicle retained an active WorkSession",
            [int(item.id) for item in active_sessions],
        )
        if session_outcome.ok:
            assert vehicle.is_active is True
            assert custody[0].is_active is True
            assert len(active_sessions) == 1
            assert int(route.work_session_id) == int(active_sessions[0].id)
        else:
            assert deactivate_outcome.ok
            assert vehicle.is_active is False
            assert custody[0].is_active is False
            assert route.work_session_id is None
            assert not active_sessions
        print(
            "CONCURRENCY_EVIDENCE scenario=deactivate_vs_session_start "
            f"deactivate={deactivate_outcome.kind}:{deactivate_outcome.code} "
            f"session={session_outcome.kind}:{session_outcome.code} "
            f"vehicle_active={vehicle.is_active} custody_active={custody[0].is_active} "
            f"route_session={route.work_session_id}"
        )


@pytest.mark.asyncio
async def test_02_vehicle_maintenance_vs_driver_session_start(gate):
    ctx = await _seed_operational_route(
        gate,
        suffix="MAINT-START",
        vehicle_inventory=7,
    )
    barrier = PairBarrier()

    async def maintenance(db):
        await update_vehicle(
            db,
            company_id=gate["company_id"],
            actor_id=gate["owner"].driver_id,
            vehicle_id=ctx.vehicle_id,
            command=UpdateVehicleCommand(
                request_id=str(uuid4()),
                expected_version=ctx.vehicle_version,
                fields={"maintenance_status": "In_Maintenance"},
            ),
        )

    async def start_session(db):
        await driver_api.start_work_session(
            SessionStartRequest(),
            db=db,
            field_context=ctx.field_context,
            legacy_actor=ctx.field_driver,
        )

    maintenance_outcome, session_outcome = await asyncio.gather(
        _run_concurrent_operation(gate["Session"], barrier, "maintenance", maintenance),
        _run_concurrent_operation(gate["Session"], barrier, "session_start", start_session),
    )
    _assert_no_lock_failure(maintenance_outcome, session_outcome)
    assert int(maintenance_outcome.ok) + int(session_outcome.ok) == 1, (
        maintenance_outcome,
        session_outcome,
    )

    async with gate["Session"]() as db:
        vehicle, custody, routes = await _vehicle_state(db, gate, ctx.vehicle_id)
        route = next(row for row in routes if int(row.id) == ctx.route_id)
        sessions = (
            await db.execute(
                select(WorkSession).where(
                    WorkSession.company_id == gate["company_id"],
                    WorkSession.driver_id == ctx.driver_id,
                    WorkSession.end_time.is_(None),
                )
            )
        ).scalars().all()
        assert len(custody) == 1 and int(custody[0].id) == ctx.custody_id
        assert custody[0].is_active is True
        if maintenance_outcome.ok:
            assert vehicle.maintenance_status == "In_Maintenance"
            assert not sessions
            assert route.work_session_id is None
        else:
            assert session_outcome.ok
            assert vehicle.maintenance_status == "Active"
            assert len(sessions) == 1
            assert int(route.work_session_id) == int(sessions[0].id)
            snapshots = (
                await db.execute(
                    select(SessionInventorySnapshot).where(
                        SessionInventorySnapshot.company_id == gate["company_id"],
                        SessionInventorySnapshot.work_session_id == int(sessions[0].id),
                    )
                )
            ).scalars().all()
            assert len(snapshots) == 1
            assert int(snapshots[0].location_id) == ctx.custody_id
            assert int(snapshots[0].product_variant_id) == gate["variant_id"]
            assert Decimal(snapshots[0].starting_quantity) == Decimal("7")
        print(
            "CONCURRENCY_EVIDENCE scenario=maintenance_vs_session_start "
            f"maintenance={maintenance_outcome.kind}:{maintenance_outcome.code} "
            f"session={session_outcome.kind}:{session_outcome.code} "
            f"maintenance_status={vehicle.maintenance_status} route_session={route.work_session_id}"
        )


@pytest.mark.asyncio
async def test_03_vehicle_deactivate_vs_route_inventory_adjustment(gate):
    ctx = await _seed_operational_route(
        gate,
        suffix="DEACT-ADJUST",
        source_inventory=100,
    )
    barrier = PairBarrier()

    async def deactivate(db):
        await deactivate_vehicle(
            db,
            company_id=gate["company_id"],
            actor_id=gate["owner"].driver_id,
            vehicle_id=ctx.vehicle_id,
            command=VehicleLifecycleCommand(
                request_id=str(uuid4()), expected_version=ctx.vehicle_version
            ),
        )

    async def adjust(db):
        await dispatch_api.adjust_route_inventory(
            ctx.route_id,
            AdjustRouteInventoryRequest(
                request_id=uuid4(),
                deltas=[
                    InventoryAdjustmentDelta(
                        product_id=gate["variant_id"],
                        delta_cartons=1,
                    )
                ],
            ),
            db=db,
            access=gate["owner"].access(db),
            legacy_actor=gate["owner"].operational_driver,
        )

    deactivate_outcome, adjust_outcome = await asyncio.gather(
        _run_concurrent_operation(gate["Session"], barrier, "deactivate", deactivate),
        _run_concurrent_operation(gate["Session"], barrier, "route_adjust", adjust),
    )
    _assert_no_lock_failure(deactivate_outcome, adjust_outcome)
    assert int(deactivate_outcome.ok) + int(adjust_outcome.ok) == 1, (
        deactivate_outcome,
        adjust_outcome,
    )

    async with gate["Session"]() as db:
        vehicle, custody, _ = await _vehicle_state(db, gate, ctx.vehicle_id)
        assert len(custody) == 1 and int(custody[0].id) == ctx.custody_id
        source_qty = await _available_total(db, gate, ctx.source_id)
        vehicle_qty = await _available_total(db, gate, ctx.custody_id)
        movement_rows = (
            await db.execute(
                select(InventoryMovement).where(
                    InventoryMovement.company_id == gate["company_id"],
                    InventoryMovement.reference_type == "DISPATCH_LOAD",
                    InventoryMovement.reference_id == str(ctx.route_id),
                    InventoryMovement.movement_kind == "PHYSICAL",
                )
            )
        ).scalars().all()
        movement_qty = sum((Decimal(row.quantity) for row in movement_rows), Decimal("0"))
        assert source_qty + vehicle_qty == Decimal("100")
        if adjust_outcome.ok:
            assert vehicle.is_active is True
            assert custody[0].is_active is True
            assert source_qty == Decimal("90")
            assert vehicle_qty == Decimal("10")
            assert movement_qty == Decimal("10")
        else:
            assert deactivate_outcome.ok
            assert vehicle.is_active is False
            assert custody[0].is_active is False
            assert source_qty == Decimal("100")
            assert vehicle_qty == Decimal("0")
            assert movement_qty == Decimal("0")
        print(
            "CONCURRENCY_EVIDENCE scenario=deactivate_vs_route_adjust "
            f"deactivate={deactivate_outcome.kind}:{deactivate_outcome.code} "
            f"adjust={adjust_outcome.kind}:{adjust_outcome.code} "
            f"vehicle_active={vehicle.is_active} source_qty={source_qty} vehicle_qty={vehicle_qty} "
            f"movement_qty={movement_qty}"
        )


@pytest.mark.asyncio
async def test_04_concurrent_route_create_same_vehicle(gate):
    Session = gate["Session"]
    async with Session() as db:
        field_a = await seed_field_fixture(
            db, gate["company_id"], password=f"SyntheticRouteA{uuid4().hex[:8]}"
        )
        field_b = await seed_field_fixture(
            db, gate["company_id"], password=f"SyntheticRouteB{uuid4().hex[:8]}"
        )
        driver_a = int(field_a.driver.id)
        driver_b = int(field_b.driver.id)
        vehicle, custody = await _create_vehicle_record(
            db, gate, plate=f"VC-ROUTE-RACE-{uuid4().hex[:6]}"
        )
        source = InventoryLocation(
            company_id=gate["company_id"],
            name="Route Race Warehouse",
            code=f"VC-RACE-WH-{uuid4().hex[:8]}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        zone_a = Zone(
            company_id=gate["company_id"],
            name=f"Route Race A {uuid4().hex[:6]}",
        )
        zone_b = Zone(
            company_id=gate["company_id"],
            name=f"Route Race B {uuid4().hex[:6]}",
        )
        db.add_all([source, zone_a, zone_b])
        await db.flush()
        vehicle_id = int(vehicle.id)
        custody_id = int(custody.id)
        source_id = int(source.id)
        zone_a_id = int(zone_a.id)
        zone_b_id = int(zone_b.id)
        before_movements = int(await db.scalar(select(func.count()).select_from(InventoryMovement)) or 0)
        await db.commit()

    barrier = PairBarrier()

    async def create_a(db):
        await dispatch_api.dispatch_route(
            DispatchRouteRequest(
                zone_id=zone_a_id,
                driver_id=driver_a,
                vehicle_id=vehicle_id,
                source_location_id=source_id,
                inventory={},
            ),
            db=db,
            access=gate["owner"].access(db),
            legacy_actor=gate["owner"].operational_driver,
        )

    async def create_b(db):
        await dispatch_api.dispatch_route(
            DispatchRouteRequest(
                zone_id=zone_b_id,
                driver_id=driver_b,
                vehicle_id=vehicle_id,
                source_location_id=source_id,
                inventory={},
            ),
            db=db,
            access=gate["owner"].access(db),
            legacy_actor=gate["owner"].operational_driver,
        )

    outcome_a, outcome_b = await asyncio.gather(
        _run_concurrent_operation(Session, barrier, "route_create_a", create_a),
        _run_concurrent_operation(Session, barrier, "route_create_b", create_b),
    )
    _assert_no_lock_failure(outcome_a, outcome_b)
    assert int(outcome_a.ok) + int(outcome_b.ok) == 1, (outcome_a, outcome_b)
    losing = outcome_b if outcome_a.ok else outcome_a
    assert losing.kind in {"business_conflict", "integrity_conflict"}, losing

    async with Session() as db:
        current_routes = (
            await db.execute(
                select(DispatchRoute).where(
                    DispatchRoute.company_id == gate["company_id"],
                    DispatchRoute.vehicle_id == vehicle_id,
                    DispatchRoute.status.in_(["active", "waiting", "postponed"]),
                )
            )
        ).scalars().all()
        custody_rows = (
            await db.execute(
                select(InventoryLocation).where(
                    InventoryLocation.company_id == gate["company_id"],
                    InventoryLocation.vehicle_id == vehicle_id,
                    InventoryLocation.location_type == "VEHICLE",
                )
            )
        ).scalars().all()
        after_movements = int(await db.scalar(select(func.count()).select_from(InventoryMovement)) or 0)
        assert len(current_routes) == 1
        assert len(custody_rows) == 1 and int(custody_rows[0].id) == custody_id
        assert after_movements == before_movements
        print(
            "CONCURRENCY_EVIDENCE scenario=concurrent_route_create "
            f"a={outcome_a.kind}:{outcome_a.status}:{outcome_a.code} "
            f"b={outcome_b.kind}:{outcome_b.status}:{outcome_b.code} "
            f"current_routes={[int(row.id) for row in current_routes]} custody={custody_id}"
        )


@pytest.mark.asyncio
async def test_05_concurrent_session_start_same_driver_route(gate):
    ctx = await _seed_operational_route(
        gate,
        suffix="DOUBLE-START",
        vehicle_inventory=7,
    )
    barrier = PairBarrier()

    async def start(db):
        await driver_api.start_work_session(
            SessionStartRequest(),
            db=db,
            field_context=ctx.field_context,
            legacy_actor=ctx.field_driver,
        )

    outcome_a, outcome_b = await asyncio.gather(
        _run_concurrent_operation(gate["Session"], barrier, "session_start_a", start),
        _run_concurrent_operation(gate["Session"], barrier, "session_start_b", start),
    )
    _assert_no_lock_failure(outcome_a, outcome_b)
    assert int(outcome_a.ok) + int(outcome_b.ok) == 1, (outcome_a, outcome_b)
    losing = outcome_b if outcome_a.ok else outcome_a
    assert losing.kind == "business_conflict" and losing.status in {400, 409}, losing

    async with gate["Session"]() as db:
        route = await db.get(DispatchRoute, ctx.route_id)
        sessions = (
            await db.execute(
                select(WorkSession).where(
                    WorkSession.company_id == gate["company_id"],
                    WorkSession.driver_id == ctx.driver_id,
                    WorkSession.end_time.is_(None),
                )
            )
        ).scalars().all()
        assert len(sessions) == 1
        session = sessions[0]
        assert int(route.work_session_id) == int(session.id)
        snapshots = (
            await db.execute(
                select(SessionInventorySnapshot).where(
                    SessionInventorySnapshot.company_id == gate["company_id"],
                    SessionInventorySnapshot.work_session_id == int(session.id),
                )
            )
        ).scalars().all()
        assert len(snapshots) == 1
        snapshot = snapshots[0]
        assert int(snapshot.location_id) == ctx.custody_id
        assert int(snapshot.product_variant_id) == gate["variant_id"]
        assert Decimal(snapshot.starting_quantity) == Decimal("7")
        custody_rows = (
            await db.execute(
                select(InventoryLocation).where(
                    InventoryLocation.company_id == gate["company_id"],
                    InventoryLocation.vehicle_id == ctx.vehicle_id,
                    InventoryLocation.location_type == "VEHICLE",
                )
            )
        ).scalars().all()
        assert len(custody_rows) == 1 and int(custody_rows[0].id) == ctx.custody_id
        print(
            "CONCURRENCY_EVIDENCE scenario=concurrent_session_start "
            f"a={outcome_a.kind}:{outcome_a.status}:{outcome_a.code} "
            f"b={outcome_b.kind}:{outcome_b.status}:{outcome_b.code} "
            f"session_id={session.id} route_session={route.work_session_id} snapshots={len(snapshots)}"
        )


@pytest.mark.asyncio
async def test_06_ambiguous_custody_concurrent_consumers_fail_closed(gate):
    ctx = await _seed_operational_route(
        gate,
        suffix="AMBIG-RACE",
        source_inventory=100,
    )
    async with gate["Session"]() as db:
        db.add(InventoryLocation(
            company_id=gate["company_id"],
            name="Concurrency historical duplicate custody",
            code=f"VC-HIST-{ctx.vehicle_id}-{uuid4().hex[:6]}",
            location_type="VEHICLE",
            vehicle_id=ctx.vehicle_id,
            is_active=False,
            version=1,
        ))
        await db.commit()

    barrier = PairBarrier()

    async def start(db):
        await driver_api.start_work_session(
            SessionStartRequest(),
            db=db,
            field_context=ctx.field_context,
            legacy_actor=ctx.field_driver,
        )

    async def adjust(db):
        await dispatch_api.adjust_route_inventory(
            ctx.route_id,
            AdjustRouteInventoryRequest(
                request_id=uuid4(),
                deltas=[
                    InventoryAdjustmentDelta(
                        product_id=gate["variant_id"],
                        delta_cartons=1,
                    )
                ],
            ),
            db=db,
            access=gate["owner"].access(db),
            legacy_actor=gate["owner"].operational_driver,
        )

    start_outcome, adjust_outcome = await asyncio.gather(
        _run_concurrent_operation(gate["Session"], barrier, "session_start", start),
        _run_concurrent_operation(gate["Session"], barrier, "route_adjust", adjust),
    )
    _assert_no_lock_failure(start_outcome, adjust_outcome)
    assert not start_outcome.ok and not adjust_outcome.ok, (start_outcome, adjust_outcome)
    assert start_outcome.kind == "business_conflict" and start_outcome.status == 409, start_outcome
    assert adjust_outcome.kind == "business_conflict" and adjust_outcome.status == 409, adjust_outcome
    assert start_outcome.code == "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS", start_outcome
    assert adjust_outcome.code == "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS", adjust_outcome

    async with gate["Session"]() as db:
        route = await db.get(DispatchRoute, ctx.route_id)
        sessions = (
            await db.execute(
                select(WorkSession).where(
                    WorkSession.company_id == gate["company_id"],
                    WorkSession.driver_id == ctx.driver_id,
                )
            )
        ).scalars().all()
        movement_rows = (
            await db.execute(
                select(InventoryMovement).where(
                    InventoryMovement.company_id == gate["company_id"],
                    InventoryMovement.reference_id == str(ctx.route_id),
                    InventoryMovement.reference_type.in_(["DISPATCH_LOAD", "DISPATCH_UNLOAD"]),
                )
            )
        ).scalars().all()
        custody_rows = (
            await db.execute(
                select(InventoryLocation).where(
                    InventoryLocation.company_id == gate["company_id"],
                    InventoryLocation.vehicle_id == ctx.vehicle_id,
                    InventoryLocation.location_type == "VEHICLE",
                ).order_by(InventoryLocation.id.asc())
            )
        ).scalars().all()
        source_qty = await _available_total(db, gate, ctx.source_id)
        vehicle_qty = await _available_total(db, gate, ctx.custody_id)
        assert not sessions
        assert route.work_session_id is None
        assert not movement_rows
        assert len(custody_rows) == 2
        assert sum(1 for row in custody_rows if row.is_active) == 1
        assert next(int(row.id) for row in custody_rows if row.is_active) == ctx.custody_id
        assert source_qty == Decimal("100")
        assert vehicle_qty == Decimal("0")
        print(
            "CONCURRENCY_EVIDENCE scenario=ambiguous_concurrent_consumers "
            f"session={start_outcome.kind}:{start_outcome.code} "
            f"adjust={adjust_outcome.kind}:{adjust_outcome.code} "
            f"movements={len(movement_rows)} sessions={len(sessions)} custody_rows={len(custody_rows)}"
        )
