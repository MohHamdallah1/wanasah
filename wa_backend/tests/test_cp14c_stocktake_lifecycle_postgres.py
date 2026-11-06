"""CP14-C operational acceptance: Stocktake + Warehouse lifecycle blockers.

Runs only against the disposable CP14-C PostgreSQL 16 database provisioned by
inventory-cp14c-stocktake-lifecycle.yml. Runtime requests use a restricted
NOSUPERUSER/NOBYPASSRLS role. Business state is cleared only through canonical
commands; InventoryBalance is never created or patched directly.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
import os
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api import dispatch
from api.warehouse import ledger, locations, stocktake, stocktake_discovery, stocktake_history, transfer_policy, transfers
from context import tenant_context
from domains.authorization.backoffice_access import BackofficeCapabilityAccessRejected
from domains.authorization.capabilities import PERMISSIONS
from domains.stocktake.count_uom_read import read_count_outer_uoms
from domains.uom_authority import build_variant_uom_authority
from domains.stocktake.contracts import (
    StocktakeApprovalCommand,
    StocktakeCancelCommand,
    StocktakeCountCommand,
    StocktakeRecountCommand,
    StocktakeStartCommand,
)
from models import (
    Branch,
    Company,
    DispatchRoute,
    Driver,
    InventoryBalance,
    InventoryLiveStockProjection,
    InventoryLocation,
    InventoryLock,
    InventoryMovement,
    InventoryTransferHeader,
    Permission,
    Product,
    ProductBatch,
    ProductLocation,
    ProductUomConversion,
    ProductVariant,
    Role,
    StocktakeSession,
    StocktakeLine,
    TenantOperationalPolicy,
    UOM,
    UserLocationAccess,
    UserRole,
    Vehicle,
    WorkSession,
    Zone,
    role_permissions,
    utc_now,
)
from schemas import (
    TransferDestinationPolicyPublishRequest,
    TransferDestinationPolicySaveRequest,
    UnifiedDispatchRequest,
    UnifiedReceiveRequest,
    UpdateRouteStatusRequest,
    WarehouseLocationStateRequest,
)
from services import InventoryMutationError, apply_inventory_movement
from tests.canonical_actor_fixtures import seed_field_fixture, seed_ordinary_backoffice_fixture


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CP14C_PG_GATE") != "1",
        reason="Explicit disposable CP14-C PostgreSQL gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]

PORT = 55452
DB_NAME = "wanasah_cp14c_test"
RUNTIME_USER = "cp14c_app"
PASSWORD = "CP14COperatorSynthetic123"
RECOUNT_PASSWORD = "CP14CRecountSynthetic123"

STOCKTAKE_CODES = (
    "stocktake.read",
    "stocktake.start",
    "stocktake.count",
    "stocktake.review",
    "stocktake.approve",
    "stocktake.recount",
    "stocktake.cancel",
)


def _checked_urls():
    runtime = make_url(os.environ["WANASAH_CP14C_PG_URL"])
    admin = make_url(os.environ["WANASAH_CP14C_PG_ADMIN_URL"])
    for url in (runtime, admin):
        if (
            url.drivername != "postgresql+asyncpg"
            or url.host != "127.0.0.1"
            or url.port != PORT
            or url.database != DB_NAME
        ):
            raise RuntimeError("Refusing any database outside disposable CP14-C PostgreSQL")
    if runtime.username != RUNTIME_USER or admin.username == runtime.username:
        raise RuntimeError("CP14-C requires distinct restricted runtime and migration roles")
    return runtime, admin


@asynccontextmanager
async def _runtime_session(engine, company_id: int):
    token = tenant_context.set(company_id)
    try:
        async with engine.connect() as connection:
            db = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                await db.execute(
                    text("SELECT set_config('app.current_tenant', :tenant, false)"),
                    {"tenant": str(company_id)},
                )
                await db.execute(text("SET statement_timeout='15000ms'"))
                # Persist session-scoped RLS tenant context across expected endpoint rollbacks.
                await db.commit()
                yield db
            finally:
                await db.close()
    finally:
        tenant_context.reset(token)


async def _ensure_permissions(db: AsyncSession, codes: set[str]) -> None:
    unknown = codes - set(PERMISSIONS)
    assert not unknown, f"Unknown canonical capability: {sorted(unknown)}"
    present = set(
        (await db.scalars(select(Permission.code).where(Permission.code.in_(codes)))).all()
    )
    db.add_all(Permission(code=code) for code in sorted(codes - present))
    await db.flush()


async def _grant_location(
    db: AsyncSession,
    *,
    company_id: int,
    driver_id: int,
    location_id: int,
    codes: tuple[str, ...],
) -> dict[str, int]:
    assignments = {}
    for code in codes:
        permission = await db.scalar(select(Permission).where(Permission.code == code))
        assert permission is not None, code
        role = Role(company_id=company_id, name=f"CP14C {code} {uuid4().hex}")
        db.add(role)
        await db.flush()
        await db.execute(
            role_permissions.insert().values(
                company_id=company_id,
                role_id=role.id,
                permission_id=permission.id,
            )
        )
        db.add(
            UserLocationAccess(
                company_id=company_id,
                role_id=role.id,
                driver_id=driver_id,
                location_id=location_id,
            )
        )
        await db.flush()
        assignments[code] = role.id
    return assignments


async def _grant_company(
    db: AsyncSession, *, company_id: int, driver_id: int, code: str
) -> int:
    permission = await db.scalar(select(Permission).where(Permission.code == code))
    assert permission is not None, code
    role = Role(company_id=company_id, name=f"CP14C company {code} {uuid4().hex}")
    db.add(role)
    await db.flush()
    await db.execute(
        role_permissions.insert().values(
            company_id=company_id,
            role_id=role.id,
            permission_id=permission.id,
        )
    )
    db.add(UserRole(company_id=company_id, role_id=role.id, driver_id=driver_id))
    await db.flush()
    return role.id


def _opaque(exc: HTTPException, *values: object) -> None:
    rendered = str(exc.detail)
    for value in values:
        assert str(value) not in rendered


def _blocker(exc: HTTPException, blocker_type: str) -> None:
    assert exc.status_code == 409
    assert exc.detail["code"] == "LOCATION_DEACTIVATION_BLOCKED"
    assert exc.detail["context"]["blocker_type"] == blocker_type


async def _balance(
    db: AsyncSession,
    company_id: int,
    location_id: int,
    variant_id: int,
    batch_id: int,
):
    row = await db.scalar(
        select(InventoryBalance).where(
            InventoryBalance.company_id == company_id,
            InventoryBalance.location_id == location_id,
            InventoryBalance.product_variant_id == variant_id,
            InventoryBalance.batch_id == batch_id,
            InventoryBalance.stock_status == "AVAILABLE",
        )
    )
    if row is None:
        return Decimal("0"), Decimal("0")
    return Decimal(row.on_hand_quantity), Decimal(row.reserved_quantity)


async def _count(db, actor, session_id: int, actual: Decimal):
    sheet = await stocktake.get_stocktake_count_sheet(
        session_id,
        db=db,
        access=actor.access(db),
        legacy_actor=actor.operational_driver,
    )
    lines = sheet if isinstance(sheet, list) else sheet["lines"]
    assert len(lines) == 1
    line = lines[0]
    command = StocktakeCountCommand(
        request_id=uuid4(),
        items=[
            {
                "product_variant_id": line["product_variant_id"],
                "batch_id": line["batch_id"],
                "stock_status": line["stock_status"],
                "actual_quantity": actual,
                "uom_id": line["base_uom_id"],
            }
        ],
    )
    return await stocktake.submit_stocktake_count(
        session_id,
        command,
        db=db,
        access=actor.access(db),
        legacy_actor=actor.operational_driver,
    )


async def _count_discovered(
    db,
    actor,
    session_id: int,
    *,
    variant_id: int,
    batch_id: int,
    uom_id: int,
    actual: Decimal,
):
    sheet = await stocktake.get_stocktake_count_sheet(
        session_id,
        db=db,
        access=actor.access(db),
        legacy_actor=actor.operational_driver,
    )
    lines = sheet if isinstance(sheet, list) else sheet["lines"]
    assert lines == []
    return await stocktake.submit_stocktake_count(
        session_id,
        StocktakeCountCommand(
            request_id=uuid4(),
            items=[
                {
                    "product_variant_id": variant_id,
                    "batch_id": batch_id,
                    "stock_status": "AVAILABLE",
                    "actual_quantity": actual,
                    "uom_id": uom_id,
                }
            ],
        ),
        db=db,
        access=actor.access(db),
        legacy_actor=actor.operational_driver,
    )


async def _start(
    db,
    actor,
    location_id: int,
    *,
    stocktake_type="FULL_COUNT",
    work_session_id=None,
):
    command = StocktakeStartCommand(
        request_id=uuid4(),
        location_id=location_id,
        stocktake_type=stocktake_type,
        related_work_session_id=work_session_id,
        notes="CP14-C canonical operational acceptance",
    )
    result = await stocktake.start_unified_stocktake(
        command,
        db=db,
        access=actor.access(db),
        legacy_actor=actor.operational_driver,
    )
    return command, result


async def _deactivate(db, tenant, *, expected_version: int):
    return await locations.deactivate_warehouse_location(
        tenant.a1,
        WarehouseLocationStateRequest(
            request_id=uuid4(),
            expected_version=expected_version,
            reason="CP14-C lifecycle blocker acceptance",
        ),
        db,
        tenant.operator.access(db),
        tenant.operator.operational_driver,
    )



async def test_cp14c_count_outer_uom_exact_graph_fallback_and_bounded_reads():
    """Bounded read must isolate each ambiguous variant; never use legacy cartons."""
    class BulkRead:
        def __init__(self, conversions, units):
            self.calls = []
            self.conversions = conversions
            self.units = units

        async def scalars(self, statement):
            self.calls.append(str(statement))
            if len(self.calls) == 1:
                return NS(all=lambda: self.conversions)
            if len(self.calls) == 2:
                return NS(all=lambda: self.units)
            raise AssertionError("N+1 UOM query")

    def row(variant, source, target, numerator, denominator=1):
        return NS(
            product_variant_id=variant, from_uom_id=source, to_uom_id=target,
            numerator=Decimal(str(numerator)), denominator=Decimal(str(denominator)),
        )

    conversions = [
        row(11, 2, 1, 8), row(11, 3, 1, 50),       # unique largest = 50
        row(12, 4, 1, 25), row(12, 5, 1, 25),       # tie => base-only
        row(13, 6, 1, 10), row(13, 7, 6, 2),
        row(13, 7, 1, 30),                          # conflicting path
        row(14, 8, 1, 3, 2),                       # 1.5 base => not whole
        row(16, 9, 1, 2),                          # decimal base step 0.25
        row(17, 10, 1, 10),                        # step 3 not compatible
    ]
    units = [
        NS(id=3, name="Actual Box", code="BOX"),
        NS(id=9, name="Exact Double", code="DOUBLE"),
    ]
    db = BulkRead(conversions, units)
    variants = {
        11: (1, 3, Decimal("0.001")),
        12: (1, 0, Decimal("1")),
        13: (1, 0, Decimal("1")),
        14: (1, 1, Decimal("0.1")),
        15: (1, 0, Decimal("1")),  # no conversion at all
        16: (1, 2, Decimal("0.25")),
        17: (1, 0, Decimal("3")),
    }
    out = await read_count_outer_uoms(db, company_id=71, variants=variants)
    assert out == {
        11: {
            "count_outer_uom_id": 3,
            "count_outer_uom_code": "BOX",
            "count_outer_uom_name": "Actual Box",
            "count_outer_factor_numerator": 50,
            "count_outer_factor_denominator": 1,
        },
        16: {
            "count_outer_uom_id": 9,
            "count_outer_uom_code": "DOUBLE",
            "count_outer_uom_name": "Exact Double",
            "count_outer_factor_numerator": 2,
            "count_outer_factor_denominator": 1,
        },
    }
    assert len(db.calls) == 2  # independent of number of variants and batches
    assert "product_uom_conversions.company_id" in db.calls[0]
    assert "product_uom_conversions.product_variant_id" in db.calls[0]
    # Exact Decimal values, never JS/Python binary float rounding.
    authority = build_variant_uom_authority(
        NS(id=11, base_uom_id=1, quantity_scale=3, quantity_step=Decimal("0.001")),
        conversions[:2],
    )
    assert authority.validate_canonical_total(
        authority.to_base(Decimal("2"), uom_id=3) + Decimal("7")
    ) == Decimal("107.000")
    assert authority.validate_canonical_total(
        authority.to_base(Decimal("2.125"), uom_id=3) + Decimal("0.750")
    ) == Decimal("107.000")
    assert (await read_count_outer_uoms(db, company_id=71, variants={})) == {}
    assert len(db.calls) == 2
    with pytest.raises(ValueError):
        await read_count_outer_uoms(
            db, company_id=71,
            variants={i: (1, 0, Decimal("1")) for i in range(1, 10002)},
        )
    assert len(db.calls) == 2
    print("CP14C_CANONICAL_COUNT_UOM_EXACT_AMBIGUOUS_MISSING_BOUND=PASS")


async def test_cp14c_stocktake_lifecycle_operational_acceptance():
    runtime_url, admin_url = _checked_urls()
    runtime_engine = create_async_engine(runtime_url, poolclass=NullPool)
    admin_engine = create_async_engine(admin_url, poolclass=NullPool)

    try:
        async with runtime_engine.connect() as connection:
            identity = (
                await connection.execute(
                    text(
                        "SELECT current_database(), current_user, inet_server_port(), "
                        "r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname=current_user"
                    )
                )
            ).one()
            assert tuple(identity) == (DB_NAME, RUNTIME_USER, PORT, False, False)
            for table in (
                "inventory_balances",
                "inventory_movements",
                "stocktake_sessions",
                "inventory_locks",
                "inventory_transfer_headers",
            ):
                flags = (
                    await connection.execute(
                        text(
                            "SELECT relrowsecurity, relforcerowsecurity "
                            "FROM pg_class WHERE oid=to_regclass(:table)"
                        ),
                        {"table": table},
                    )
                ).one()
                assert tuple(flags) == (True, True), table

        config = AlembicConfig(str(Path(__file__).parents[1] / "alembic.ini"))
        config.set_main_option(
            "script_location", str(Path(__file__).parents[1] / "alembic")
        )
        expected_heads = set(ScriptDirectory.from_config(config).get_heads())
        async with AsyncSession(admin_engine, expire_on_commit=False) as db:
            actual_heads = set(
                (await db.execute(text("SELECT version_num FROM alembic_version"))).scalars()
            )
            assert actual_heads == expected_heads

        needed = set(STOCKTAKE_CODES) | {
            "inventory.read",
            "ledger.read",
            "location.read",
            "location.state",
            "transfer.read",
            "transfer.send",
            "transfer.destination",
            "transfer.receive",
            "transfer.cancel",
            "inventory.fefo_override",
            "inventory.transfer_policy.manage",
            "dispatch.execute",
        }

        async with AsyncSession(admin_engine, expire_on_commit=False) as seed:
            await _ensure_permissions(seed, needed)
            uom = await seed.scalar(select(UOM).where(UOM.code == "EACH"))
            if uom is None:
                uom = UOM(code="EACH", name="CP14-C Each")
                seed.add(uom)
                await seed.flush()

            # Explicit canonical registered UOMs: never infer a carton from
            # packs_per_carton on ProductVariant.
            count_pack = await seed.scalar(select(UOM).where(UOM.code == "CP14C_PACK"))
            if count_pack is None:
                count_pack = UOM(code="CP14C_PACK", name="CP14C Pack")
                seed.add(count_pack)
            count_box = await seed.scalar(select(UOM).where(UOM.code == "CP14C_BOX"))
            if count_box is None:
                count_box = UOM(code="CP14C_BOX", name="CP14C Box")
                seed.add(count_box)
            await seed.flush()

            companies = [
                Company(
                    name="CP14-C Shared Company",
                    company_code="CP14C-A-" + uuid4().hex,
                    timezone="Asia/Amman",
                ),
                Company(
                    name="CP14-C Shared Company",
                    company_code="CP14C-B-" + uuid4().hex,
                    timezone="Asia/Amman",
                ),
            ]
            seed.add_all(companies)
            await seed.flush()

            tenants = []
            for index, company in enumerate(companies):
                await seed.execute(
                    text("SELECT set_config('app.current_tenant', :tenant, true)"),
                    {"tenant": str(company.id)},
                )
                operator = await seed_ordinary_backoffice_fixture(
                    seed, company.id, password=PASSWORD
                )
                denied = await seed_ordinary_backoffice_fixture(
                    seed, company.id, password="CP14CDeniedSynthetic123"
                )
                counter = await seed_ordinary_backoffice_fixture(
                    seed, company.id, password=RECOUNT_PASSWORD
                )
                field = await seed_field_fixture(seed, company.id)
                assert operator.context.is_company_owner is False
                assert denied.context.is_company_owner is False
                assert counter.context.is_company_owner is False

                branch = Branch(
                    company_id=company.id,
                    name="Shared Branch",
                    branch_code="CP14C-BR",
                    is_active=True,
                )
                seed.add(branch)
                await seed.flush()
                a1 = InventoryLocation(
                    company_id=company.id,
                    branch_id=branch.id,
                    code="CP14C-WH1",
                    name="Shared Warehouse",
                    location_type="WAREHOUSE",
                    is_active=True,
                    version=1,
                )
                seed.add(a1)
                if index == 0:
                    a2 = InventoryLocation(
                        company_id=company.id,
                        code="CP14C-WH2",
                        name="Warehouse A2",
                        location_type="WAREHOUSE",
                        is_active=True,
                        version=1,
                    )
                    seed.add(a2)
                await seed.flush()

                vehicle = Vehicle(
                    company_id=company.id,
                    plate_number="CP14C-SHARED",
                    is_active=True,
                    maintenance_status="Active",
                )
                seed.add(vehicle)
                await seed.flush()
                vehicle_location = InventoryLocation(
                    company_id=company.id,
                    code="CP14C-VEH",
                    name="Shared Vehicle",
                    location_type="VEHICLE",
                    vehicle_id=vehicle.id,
                    is_active=True,
                )
                seed.add(vehicle_location)

                product = Product(
                    company_id=company.id,
                    code="CP14C-P",
                    name="Shared Product",
                )
                seed.add(product)
                await seed.flush()
                variant = ProductVariant(
                    company_id=company.id,
                    product_id=product.id,
                    name="Shared SKU",
                    sku="CP14C-SKU",
                    base_uom_id=uom.id,
                    quantity_scale=3,
                    quantity_step=Decimal("0.001"),
                    lot_control_mode="REQUIRED",
                    expiry_control_mode="OPTIONAL",
                    lifecycle_status="ACTIVE",
                    published_at=utc_now(),
                )
                seed.add(variant)
                await seed.flush()
                if index == 0:
                    seed.add_all([
                        ProductUomConversion(
                            company_id=company.id, product_variant_id=variant.id,
                            from_uom_id=count_pack.id, to_uom_id=uom.id,
                            numerator=Decimal("8"), denominator=Decimal("1"),
                            quantity_scale=0,
                        ),
                        ProductUomConversion(
                            company_id=company.id, product_variant_id=variant.id,
                            from_uom_id=count_box.id, to_uom_id=uom.id,
                            numerator=Decimal("50"), denominator=Decimal("1"),
                            quantity_scale=0,
                        ),
                    ])
                    await seed.flush()
                batch = ProductBatch(
                    company_id=company.id,
                    product_variant_id=variant.id,
                    batch_number="CP14C-LOT",
                )
                seed.add(batch)
                await seed.flush()
                seed.add(
                    ProductLocation(
                        company_id=company.id,
                        location_id=a1.id,
                        product_variant_id=variant.id,
                        created_by=operator.driver_id,
                    )
                )
                if index == 0:
                    seed.add(
                        ProductLocation(
                            company_id=company.id,
                            location_id=a2.id,
                            product_variant_id=variant.id,
                            created_by=operator.driver_id,
                        )
                    )

                zone = Zone(company_id=company.id, name="Shared Zone", is_active=True)
                seed.add(zone)
                await seed.flush()
                work_started_at = utc_now()
                work = WorkSession(
                    company_id=company.id,
                    driver_id=operator.driver_id,
                    start_time=work_started_at,
                    session_date=date.today(),
                    end_time=work_started_at,
                    is_settled=False,
                )
                seed.add(work)
                await seed.flush()
                route = DispatchRoute(
                    company_id=company.id,
                    zone_id=zone.id,
                    driver_id=operator.driver_id,
                    vehicle_id=vehicle.id,
                    work_session_id=work.id,
                    source_location_id=a1.id,
                    dispatch_date=date.today(),
                    status="closed",
                )
                seed.add(route)
                await seed.flush()

                tenants.append(
                    NS(
                        company_id=company.id,
                        operator=operator,
                        denied=denied,
                        counter=counter,
                        field_driver=field.driver.id,
                        branch=branch.id,
                        a1=a1.id,
                        a2=(a2.id if index == 0 else None),
                        vehicle=vehicle.id,
                        vehicle_location=vehicle_location.id,
                        variant=variant.id,
                        batch=batch.id,
                        uom=uom.id,
                        outer_uom=(count_box.id if index == 0 else None),
                        work_session=work.id,
                        zone=zone.id,
                    )
                )

            a, b = tenants
            common_a1 = STOCKTAKE_CODES + (
                "inventory.read",
                "ledger.read",
                "location.read",
                "location.state",
                "transfer.read",
                "transfer.send",
                "transfer.cancel",
                "inventory.fefo_override",
                "dispatch.execute",
            )
            a.a1_roles = await _grant_location(
                seed,
                company_id=a.company_id,
                driver_id=a.operator.driver_id,
                location_id=a.a1,
                codes=common_a1,
            )
            await _grant_location(
                seed,
                company_id=a.company_id,
                driver_id=a.operator.driver_id,
                location_id=a.a2,
                codes=STOCKTAKE_CODES
                + (
                    "inventory.read",
                    "ledger.read",
                    "location.read",
                    "transfer.destination",
                    "transfer.read",
                    "transfer.receive",
                    "dispatch.execute",
                ),
            )
            await _grant_location(
                seed,
                company_id=a.company_id,
                driver_id=a.operator.driver_id,
                location_id=a.vehicle_location,
                codes=STOCKTAKE_CODES
                + ("inventory.read", "location.read", "dispatch.execute"),
            )
            await _grant_company(
                seed,
                company_id=a.company_id,
                driver_id=a.operator.driver_id,
                code="inventory.transfer_policy.manage",
            )
            await _grant_location(
                seed,
                company_id=a.company_id,
                driver_id=a.counter.driver_id,
                location_id=a.a1,
                codes=(
                    "inventory.read",
                    "location.read",
                    "stocktake.read",
                    "stocktake.count",
                    "stocktake.recount",
                ),
            )
            await _grant_location(
                seed,
                company_id=a.company_id,
                driver_id=a.counter.driver_id,
                location_id=a.a2,
                codes=(
                    "inventory.read",
                    "location.read",
                    "transfer.read",
                    "transfer.receive",
                ),
            )
            await _grant_location(
                seed,
                company_id=b.company_id,
                driver_id=b.operator.driver_id,
                location_id=b.a1,
                codes=STOCKTAKE_CODES + ("inventory.read", "location.read"),
            )
            await _grant_location(
                seed,
                company_id=b.company_id,
                driver_id=b.operator.driver_id,
                location_id=b.vehicle_location,
                codes=STOCKTAKE_CODES + ("inventory.read", "location.read"),
            )
            await seed.commit()

        async with _runtime_session(runtime_engine, a.company_id) as db:
            opening_a1 = await apply_inventory_movement(
                db,
                company_id=a.company_id,
                performed_by=a.operator.driver_id,
                product_variant_id=a.variant,
                batch_id=a.batch,
                quantity=Decimal("10.125"),
                movement_kind="PHYSICAL",
                reference_type="CP14C_OPENING",
                reference_id="A1",
                idempotency_key="CP14C-OPEN-A1-" + uuid4().hex,
                source_location_id=None,
                destination_location_id=a.a1,
                source_stock_status=None,
                destination_stock_status="AVAILABLE",
            )
            opening_va = await apply_inventory_movement(
                db,
                company_id=a.company_id,
                performed_by=a.operator.driver_id,
                product_variant_id=a.variant,
                batch_id=a.batch,
                quantity=Decimal("5.250"),
                movement_kind="PHYSICAL",
                reference_type="CP14C_OPENING",
                reference_id="VA",
                idempotency_key="CP14C-OPEN-VA-" + uuid4().hex,
                source_location_id=None,
                destination_location_id=a.vehicle_location,
                source_stock_status=None,
                destination_stock_status="AVAILABLE",
            )
            await apply_inventory_movement(
                db,
                company_id=a.company_id,
                performed_by=a.operator.driver_id,
                product_variant_id=a.variant,
                batch_id=a.batch,
                quantity=Decimal("1.125"),
                movement_kind="RESERVATION",
                reservation_action="RESERVE",
                reference_type="CP14C_RESERVE",
                reference_id="A1",
                idempotency_key="CP14C-RESERVE-" + uuid4().hex,
                source_location_id=a.a1,
                destination_location_id=a.a1,
                source_stock_status="AVAILABLE",
                destination_stock_status="AVAILABLE",
            )
            await db.commit()
            assert await _balance(db, a.company_id, a.a1, a.variant, a.batch) == (
                Decimal("10.125"),
                Decimal("1.125"),
            )

        async with _runtime_session(runtime_engine, b.company_id) as db:
            await apply_inventory_movement(
                db,
                company_id=b.company_id,
                performed_by=b.operator.driver_id,
                product_variant_id=b.variant,
                batch_id=b.batch,
                quantity=Decimal("9.875"),
                movement_kind="PHYSICAL",
                reference_type="CP14C_OPENING",
                reference_id="B1",
                idempotency_key="CP14C-OPEN-B1-" + uuid4().hex,
                source_location_id=None,
                destination_location_id=b.a1,
                source_stock_status=None,
                destination_stock_status="AVAILABLE",
            )
            await db.commit()
            _, b_session = await _start(db, b.operator, b.a1)
            b_session_id = int(b_session["session_id"])
            b_sheet = await stocktake.get_stocktake_count_sheet(
                b_session_id, db=db,
                access=b.operator.access(db),
                legacy_actor=b.operator.operational_driver,
            )
            assert len(b_sheet) == 1
            assert not any(key.startswith("count_outer_") for key in b_sheet[0])
            assert "expected_quantity" not in b_sheet[0]

        async with _runtime_session(runtime_engine, a.company_id) as db:
            assert a.operator.context.is_company_owner is False
            await a.operator.access(db).require("inventory.read", a.a1)
            await a.counter.access(db).require("inventory.read", a.a1)
            await a.counter.access(db).require("inventory.read", a.a2)
            with pytest.raises(BackofficeCapabilityAccessRejected):
                await a.counter.access(db).require("stocktake.start", a.a2)
            with pytest.raises(HTTPException) as denied_start:
                await _start(db, a.denied, a.a1)
            assert denied_start.value.status_code == 403
            with pytest.raises(HTTPException) as scoped_start:
                await _start(db, a.counter, a.a2)
            assert scoped_start.value.status_code == 403

            with pytest.raises(HTTPException) as foreign_list:
                await stocktake.list_active_stocktake_sessions(
                    location_id=b.a1,
                    cursor=None,
                    limit=50,
                    db=db,
                    access=a.operator.access(db),
                )
            assert foreign_list.value.status_code in {403, 404}
            _opaque(foreign_list.value, b.a1, b_session_id)
            with pytest.raises(HTTPException) as foreign_count:
                await stocktake.get_stocktake_count_sheet(
                    b_session_id,
                    db=db,
                    access=a.operator.access(db),
                    legacy_actor=a.operator.operational_driver,
                )
            assert foreign_count.value.status_code == 404
            _opaque(foreign_count.value, b_session_id)
            with pytest.raises(HTTPException) as foreign_finalize:
                await stocktake.approve_stocktake_session(
                    b_session_id,
                    StocktakeApprovalCommand(
                        request_id=uuid4(), count_attempt_id=1, password=PASSWORD
                    ),
                    db=db,
                    access=a.operator.access(db),
                    legacy_actor=a.operator.operational_driver,
                )
            assert foreign_finalize.value.status_code == 404
            _opaque(foreign_finalize.value, b_session_id)

        async with _runtime_session(runtime_engine, a.company_id) as db:
            start_command, started = await _start(db, a.operator, a.a1)
            session_id = int(started["session_id"])
            assert (
                await stocktake.start_unified_stocktake(
                    start_command,
                    db=db,
                    access=a.operator.access(db),
                    legacy_actor=a.operator.operational_driver,
                )
                == started
            )
            changed = start_command.model_copy(
                update={"notes": "changed payload must not replay"}
            )
            with pytest.raises(HTTPException) as wrong_replay:
                await stocktake.start_unified_stocktake(
                    changed,
                    db=db,
                    access=a.operator.access(db),
                    legacy_actor=a.operator.operational_driver,
                )
            assert wrong_replay.value.status_code == 409
            count_sheet = await stocktake.get_stocktake_count_sheet(
                session_id, db=db,
                access=a.operator.access(db),
                legacy_actor=a.operator.operational_driver,
            )
            assert len(count_sheet) == 1
            assert {
                k: v for k, v in count_sheet[0].items()
                if k.startswith("count_outer_")
            } == {
                "count_outer_uom_id": a.outer_uom,
                "count_outer_uom_name": "CP14C Box",
                "count_outer_uom_code": "CP14C_BOX",
                "count_outer_factor_numerator": 50,
                "count_outer_factor_denominator": 1,
            }
            assert count_sheet[0]["quantity_scale"] == 3
            assert count_sheet[0]["quantity_step"] == "0.001"
            assert "expected_quantity" not in count_sheet[0]
            assert "packs_per_carton" not in count_sheet[0]
            attempt1 = await _count(db, a.operator, session_id, Decimal("9.875"))
            assert attempt1["requires_independent_recount"] is True
            review1 = await stocktake.get_stocktake_review(
                session_id, db, a.operator.access(db)
            )
            assert Decimal(review1["lines"][0]["variance_quantity"]) == Decimal("-0.250")
            assert review1["independent_recount_satisfied"] is False
            with pytest.raises(HTTPException) as premature:
                await stocktake.approve_stocktake_session(
                    session_id,
                    StocktakeApprovalCommand(
                        request_id=uuid4(),
                        count_attempt_id=attempt1["attempt_id"],
                        password=PASSWORD,
                    ),
                    db=db,
                    access=a.operator.access(db),
                    legacy_actor=a.operator.operational_driver,
                )
            assert premature.value.status_code == 409

            counter_driver = await db.get(Driver, a.counter.driver_id)
            assert counter_driver is not None
            recounted = await stocktake.recount_stocktake_session(
                session_id,
                StocktakeRecountCommand(
                    request_id=uuid4(),
                    count_attempt_id=attempt1["attempt_id"],
                    reason="CP14-C independent recount",
                    authorizer_username=counter_driver.username,
                    authorizer_password=RECOUNT_PASSWORD,
                ),
                db=db,
                access=a.operator.access(db),
                legacy_actor=a.operator.operational_driver,
            )
            assert recounted["status"] == "RECOUNT_REQUIRED"

        async with _runtime_session(runtime_engine, a.company_id) as db:
            attempt2 = await _count(db, a.counter, session_id, Decimal("9.875"))
            review2 = await stocktake.get_stocktake_review(
                session_id, db, a.operator.access(db)
            )
            assert attempt2["attempt_number"] == 2
            assert review2["independent_recount_satisfied"] is True
            approval_command = StocktakeApprovalCommand(
                request_id=uuid4(),
                count_attempt_id=attempt2["attempt_id"],
                password=PASSWORD,
            )
            approved = await stocktake.approve_stocktake_session(
                session_id,
                approval_command,
                db=db,
                access=a.operator.access(db),
                legacy_actor=a.operator.operational_driver,
            )
            assert approved["status"] == "POSTED"
            stocktake_movement = await db.scalar(
                select(InventoryMovement).where(
                    InventoryMovement.company_id == a.company_id,
                    InventoryMovement.stocktake_session_id == session_id,
                )
            )
            assert stocktake_movement is not None
            assert stocktake_movement.reference_type == "AUDIT_ADJUSTMENT"
            assert Decimal(stocktake_movement.quantity) == Decimal("0.250")
            stocktake_movement_id = int(stocktake_movement.id)
            stocktake_reference_id = str(stocktake_movement.reference_id)
            movement_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(InventoryMovement)
                    .where(
                        InventoryMovement.company_id == a.company_id,
                        InventoryMovement.stocktake_session_id == session_id,
                    )
                )
            )
            assert movement_count == 1
            assert (
                await stocktake.approve_stocktake_session(
                    session_id,
                    approval_command,
                    db=db,
                    access=a.operator.access(db),
                    legacy_actor=a.operator.operational_driver,
                )
                == approved
            )
            assert int(
                await db.scalar(
                    select(func.count())
                    .select_from(InventoryMovement)
                    .where(
                        InventoryMovement.company_id == a.company_id,
                        InventoryMovement.stocktake_session_id == session_id,
                    )
                )
            ) == movement_count
            changed_approval = approval_command.model_copy(
                update={"notes": "changed approval replay"}
            )
            with pytest.raises(HTTPException) as changed_approval_error:
                await stocktake.approve_stocktake_session(
                    session_id,
                    changed_approval,
                    db=db,
                    access=a.operator.access(db),
                    legacy_actor=a.operator.operational_driver,
                )
            assert changed_approval_error.value.status_code == 409
            assert await _balance(db, a.company_id, a.a1, a.variant, a.batch) == (
                Decimal("9.875"),
                Decimal("1.125"),
            )
            assert int(
                await db.scalar(
                    select(func.count())
                    .select_from(InventoryLock)
                    .where(
                        InventoryLock.company_id == a.company_id,
                        InventoryLock.stocktake_session_id == session_id,
                        InventoryLock.released_at.is_(None),
                    )
                )
            ) == 0

            ledger_page = await ledger.get_warehouse_ledger_cursor(
                location_id=a.a1,
                cursor=None,
                limit=100,
                search=None,
                reference_type="AUDIT_ADJUSTMENT",
                reference_id=stocktake_reference_id,
                db=db,
                access=a.operator.access(db),
            )
            stocktake_evidence = [
                item
                for item in ledger_page["items"]
                if item["id"] == stocktake_movement_id
            ]
            assert len(stocktake_evidence) == 1
            evidence = stocktake_evidence[0]
            assert evidence["reference"] == stocktake_reference_id
            assert Decimal(evidence["quantity"]) == Decimal("-0.250")
            assert evidence["source_location_id"] == a.a1
            assert evidence["destination_location_id"] is None

            # Terminal POSTED is no longer in active sessions, but auditable
            # after review authorization, including BOTH immutable attempts.
            terminal = await stocktake_history.list_stocktake_history(
                location_id=a.a1, cursor=None, limit=20,
                db=db, access=a.operator.access(db),
            )
            posted = next(row for row in terminal["items"] if row["id"] == session_id)
            assert posted["status"] == "POSTED"
            assert posted["attempt_number"] == 2
            assert posted["counted_by_name"]
            detail = await stocktake_history.get_stocktake_history_detail(
                session_id, location_id=a.a1, db=db, access=a.operator.access(db),
            )
            assert detail["session"]["adjustment_movement_count"] == 1
            assert [item["attempt_number"] for item in detail["attempts"]["items"]] == [2, 1]
            assert any(row["action_type"] == "STOCKTAKE_APPROVED_AND_POSTED"
                       for row in detail["audit"]["items"])
            older = detail["attempts"]["items"][-1]
            old_lines = await stocktake_history.get_stocktake_history_attempt_lines(
                session_id, older["id"], location_id=a.a1, cursor=None,
                limit=1, db=db, access=a.operator.access(db),
            )
            assert old_lines["items"][0]["expected_quantity"] == "10.125"
            assert old_lines["items"][0]["actual_quantity"] == "9.875"
            assert old_lines["items"][0]["variance_quantity"] == "-0.25"
            assert old_lines["items"][0]["batch_id"] == a.batch
            assert old_lines["items"][0]["stock_status"] == "AVAILABLE"
            assert old_lines["items"][0]["base_uom_id"] == a.uom
            with pytest.raises(HTTPException) as count_only:
                await stocktake_history.get_stocktake_history_detail(
                    session_id, location_id=a.a1, db=db, access=a.counter.access(db),
                )
            assert count_only.value.status_code == 403
            with pytest.raises(HTTPException) as wrong_warehouse:
                await stocktake_history.get_stocktake_history_detail(
                    session_id, location_id=a.a2, db=db, access=a.operator.access(db),
                )
            assert wrong_warehouse.value.status_code == 404
            with pytest.raises(HTTPException) as foreign_terminal:
                await stocktake_history.get_stocktake_history_detail(
                    b_session_id, location_id=b.a1, db=db, access=a.operator.access(db),
                )
            assert foreign_terminal.value.status_code == 404
            print("CP14C_TERMINAL_POSTED_REVIEW_ATTEMPT_LINES_ROLE_TENANT=PASS")

        async with _runtime_session(runtime_engine, a.company_id) as db:
            _, rollback_started = await _start(db, a.operator, a.a2)
            rollback_session = int(rollback_started["session_id"])
            # 0-onhand discovered stock must be discoverable from this exact
            # authorized Stocktake session, not from the stocked-only picker.
            options = await stocktake_discovery.stocktake_discovery_options(
                rollback_session,
                product_variant_id=None, batch_ids=None, search=None,
                cursor=None, limit=50, db=db,
                access=a.operator.access(db), actor=a.operator.operational_driver,
            )
            assert [x["id"] for x in options["items"]] == [a.variant]
            assert options["items"][0]["quantity_step"] == "0.001"
            assert options["items"][0]["count_outer_uom_id"] == a.outer_uom
            assert options["items"][0]["count_outer_factor_numerator"] == 50
            assert options["items"][0]["count_outer_factor_denominator"] == 1
            lots = await stocktake_discovery.stocktake_discovery_options(
                rollback_session,
                product_variant_id=a.variant, batch_ids=None, search=None,
                cursor=None, limit=50, db=db,
                access=a.operator.access(db), actor=a.operator.operational_driver,
            )
            assert [x["id"] for x in lots["items"]] == [a.batch]
            assert lots["items"][0]["base_uom_id"] == a.uom
            assert lots["items"][0]["count_outer_uom_id"] == a.outer_uom
            assert lots["items"][0]["count_outer_factor_numerator"] == 50
            assert lots["items"][0]["disposition"] == "RELEASED"
            assert lots["items"][0]["expiry_date"] is None
            revalidated = await stocktake_discovery.stocktake_discovery_options(
                rollback_session,
                product_variant_id=None, batch_ids=str(a.batch), search=None,
                cursor=None, limit=50, db=db,
                access=a.operator.access(db), actor=a.operator.operational_driver,
            )
            assert revalidated["items"] == lots["items"]
            with pytest.raises(HTTPException) as forbidden:
                await stocktake_discovery.stocktake_discovery_options(
                    rollback_session,
                    product_variant_id=None, batch_ids=None, search=None,
                    cursor=None, limit=50, db=db,
                    access=a.denied.access(db), actor=a.denied.operational_driver,
                )
            assert forbidden.value.status_code == 403
            with pytest.raises(HTTPException) as foreign:
                await stocktake_discovery.stocktake_discovery_options(
                    b_session_id,
                    product_variant_id=None, batch_ids=None, search=None,
                    cursor=None, limit=50, db=db,
                    access=a.operator.access(db), actor=a.operator.operational_driver,
                )
            assert foreign.value.status_code in {403, 404}
            with pytest.raises(HTTPException) as malformed:
                await stocktake_discovery.stocktake_discovery_options(
                    rollback_session,
                    product_variant_id=None, batch_ids="1,0", search=None,
                    cursor=None, limit=50, db=db,
                    access=a.operator.access(db), actor=a.operator.operational_driver,
                )
            assert malformed.value.status_code == 400
            # Duplicate rows are rejected by the existing public command
            # validator before reaching any stocktake write transaction.
            with pytest.raises(ValueError) as duplicated:
                StocktakeCountCommand(
                    request_id=uuid4(),
                    items=[{
                        "product_variant_id": a.variant,
                        "batch_id": a.batch,
                        "stock_status": "AVAILABLE",
                        "actual_quantity": Decimal("1.000"),
                        "uom_id": a.uom,
                    }] * 2,
                )
            assert "تكرار" in str(duplicated.value)
            assert (await db.get(StocktakeSession, rollback_session)).status == "COUNTING"

            rollback_attempt = await _count_discovered(
                db,
                a.operator,
                rollback_session,
                variant_id=a.variant,
                batch_id=a.batch,
                uom_id=a.uom,
                actual=Decimal("1.000"),
            )
            before_balance = await _balance(
                db, a.company_id, a.a2, a.variant, a.batch
            )
            assert before_balance == (Decimal("0"), Decimal("0"))
            before_movement_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(InventoryMovement)
                    .where(
                        InventoryMovement.company_id == a.company_id,
                        InventoryMovement.stocktake_session_id == rollback_session,
                    )
                )
            )
            with patch.object(
                stocktake,
                "post_approved_stocktake_adjustments",
                side_effect=InventoryMutationError("CP14-C injected posting failure"),
            ):
                with pytest.raises(HTTPException) as failed:
                    await stocktake.approve_stocktake_session(
                        rollback_session,
                        StocktakeApprovalCommand(
                            request_id=uuid4(),
                            count_attempt_id=rollback_attempt["attempt_id"],
                            password=PASSWORD,
                        ),
                        db=db,
                        access=a.operator.access(db),
                        legacy_actor=a.operator.operational_driver,
                    )
            assert failed.value.status_code == 409
            session = await db.get(StocktakeSession, rollback_session)
            assert session is not None and session.status == "PENDING_REVIEW"
            rollback_reference_id = str(session.reference_number)
            assert await _balance(db, a.company_id, a.a2, a.variant, a.batch) == before_balance
            assert int(
                await db.scalar(
                    select(func.count())
                    .select_from(InventoryMovement)
                    .where(
                        InventoryMovement.company_id == a.company_id,
                        InventoryMovement.stocktake_session_id == rollback_session,
                    )
                )
            ) == before_movement_count
            rollback_ledger = await ledger.get_warehouse_ledger_cursor(
                location_id=a.a2,
                cursor=None,
                limit=100,
                search=None,
                reference_type="AUDIT_ADJUSTMENT",
                reference_id=rollback_reference_id,
                db=db,
                access=a.operator.access(db),
            )
            assert rollback_ledger["items"] == []
            cancelled = await stocktake.cancel_stocktake_session(
                rollback_session,
                StocktakeCancelCommand(
                    request_id=uuid4(),
                    password=PASSWORD,
                    reason="resolve injected failure",
                ),
                db=db,
                access=a.operator.access(db),
                legacy_actor=a.operator.operational_driver,
            )
            assert cancelled["status"] == "CANCELLED"
            cancelled_details = await stocktake_history.get_stocktake_history_detail(
                rollback_session, location_id=a.a2, db=db,
                access=a.operator.access(db),
            )
            assert cancelled_details["session"]["cancelled_after_count"] is True
            assert cancelled_details["session"]["cancellation_reason"] == "resolve injected failure"
            assert cancelled_details["session"]["adjustment_movement_count"] == 0
            assert len(cancelled_details["attempts"]["items"]) == 1
            cancelled_lines = await stocktake_history.get_stocktake_history_attempt_lines(
                rollback_session, rollback_attempt["attempt_id"], location_id=a.a2,
                cursor=None, limit=10, db=db, access=a.operator.access(db),
            )
            assert cancelled_lines["items"][0]["expected_quantity"] == "0"
            assert cancelled_lines["items"][0]["actual_quantity"] == "1"
            assert cancelled_lines["items"][0]["variance_quantity"] == "1"
            assert any(ev["action_type"] == "STOCKTAKE_CANCELLED"
                       for ev in cancelled_details["audit"]["items"])
            print("CP14C_TERMINAL_CANCEL_AFTER_COUNT_IMMUTABLE_ZERO_LEDGER=PASS")

        async with _runtime_session(runtime_engine, a.company_id) as db:
            _, cancel_started = await _start(db, a.operator, a.a2)
            cancel_session = int(cancel_started["session_id"])
        async with AsyncSession(admin_engine, expire_on_commit=False) as admin:
            await admin.execute(
                UserLocationAccess.__table__.delete().where(
                    UserLocationAccess.company_id == a.company_id,
                    UserLocationAccess.driver_id == a.operator.driver_id,
                    UserLocationAccess.location_id == a.a1,
                    UserLocationAccess.role_id == a.a1_roles["stocktake.start"],
                )
            )
            await admin.commit()
        async with _runtime_session(runtime_engine, a.company_id) as db:
            with pytest.raises(HTTPException) as revoked:
                await stocktake.start_unified_stocktake(
                    start_command,
                    db=db,
                    access=a.operator.access(db),
                    legacy_actor=a.operator.operational_driver,
                )
            assert revoked.value.status_code == 403
        async with AsyncSession(admin_engine, expire_on_commit=False) as admin:
            admin.add(
                UserLocationAccess(
                    company_id=a.company_id,
                    role_id=a.a1_roles["stocktake.start"],
                    driver_id=a.operator.driver_id,
                    location_id=a.a1,
                )
            )
            await admin.commit()
        async with _runtime_session(runtime_engine, a.company_id) as db:
            cancelled = await stocktake.cancel_stocktake_session(
                cancel_session,
                StocktakeCancelCommand(
                    request_id=uuid4(),
                    password=PASSWORD,
                    reason="CP14-C cancel journey",
                ),
                db=db,
                access=a.operator.access(db),
                legacy_actor=a.operator.operational_driver,
            )
            assert cancelled["status"] == "CANCELLED"
            no_count = await stocktake_history.get_stocktake_history_detail(
                cancel_session, location_id=a.a2, db=db, access=a.operator.access(db),
            )
            assert no_count["attempts"]["items"] == []
            assert no_count["session"]["cancelled_after_count"] is False
            assert no_count["session"]["adjustment_movement_count"] == 0
            terminal_list = await stocktake_history.list_stocktake_history(
                location_id=a.a2, cursor=None, limit=10,
                db=db, access=a.operator.access(db),
            )
            assert {cancel_session, rollback_session}.issubset({
                row["id"] for row in terminal_list["items"]
            })
            assert next(row for row in terminal_list["items"]
                        if row["id"] == rollback_session)["cancelled_after_count"] is True
            print("CP14C_TERMINAL_CANCEL_BEFORE_COUNT_PRESENT=PASS")

        async with _runtime_session(runtime_engine, a.company_id) as db:
            await apply_inventory_movement(
                db,
                company_id=a.company_id,
                performed_by=a.operator.driver_id,
                product_variant_id=a.variant,
                batch_id=a.batch,
                quantity=Decimal("2.000"),
                movement_kind="PHYSICAL",
                reference_type="CP14C_CONCURRENCY_OPENING",
                reference_id="A2",
                idempotency_key="CP14C-A2-OPEN-" + uuid4().hex,
                source_location_id=None,
                destination_location_id=a.a2,
                source_stock_status=None,
                destination_stock_status="AVAILABLE",
            )
            await db.commit()
            _, race_started = await _start(db, a.operator, a.a2)
            race_session = int(race_started["session_id"])
            race_attempt = await _count(
                db, a.operator, race_session, Decimal("2.000")
            )

        async def finalize(request_id):
            async with _runtime_session(runtime_engine, a.company_id) as db:
                return await stocktake.approve_stocktake_session(
                    race_session,
                    StocktakeApprovalCommand(
                        request_id=request_id,
                        count_attempt_id=race_attempt["attempt_id"],
                        password=PASSWORD,
                    ),
                    db=db,
                    access=a.operator.access(db),
                    legacy_actor=a.operator.operational_driver,
                )

        race = await asyncio.wait_for(
            asyncio.gather(
                finalize(uuid4()), finalize(uuid4()), return_exceptions=True
            ),
            timeout=20,
        )
        assert sum(isinstance(result, dict) for result in race) == 1
        loser = next(result for result in race if not isinstance(result, dict))
        assert isinstance(loser, HTTPException) and loser.status_code == 409

        async with _runtime_session(runtime_engine, a.company_id) as db:
            candidates = await stocktake.list_vehicle_recon_candidates(
                a.a1, None, None, 50, db, a.operator.access(db)
            )
            assert {item["vehicle_id"] for item in candidates["items"]} == {a.vehicle}
            assert b.vehicle not in {item["vehicle_id"] for item in candidates["items"]}
            with pytest.raises(HTTPException) as foreign_vehicle:
                await _start(
                    db,
                    a.operator,
                    b.vehicle_location,
                    stocktake_type="VEHICLE_RECON",
                    work_session_id=b.work_session,
                )
            assert foreign_vehicle.value.status_code in {403, 404}
            _opaque(
                foreign_vehicle.value, b.vehicle, b.vehicle_location, b.work_session
            )

            _, vehicle_started = await _start(
                db,
                a.operator,
                a.vehicle_location,
                stocktake_type="VEHICLE_RECON",
                work_session_id=a.work_session,
            )
            vehicle_session = int(vehicle_started["session_id"])
            vehicle_attempt = await _count(
                db, a.operator, vehicle_session, Decimal("5.500")
            )
            vehicle_review = await stocktake.get_stocktake_review(
                vehicle_session, db, a.operator.access(db)
            )
            assert Decimal(vehicle_review["lines"][0]["variance_quantity"]) == Decimal(
                "0.250"
            )
            assert vehicle_attempt["requires_independent_recount"] is False
            vehicle_approved = await stocktake.approve_stocktake_session(
                vehicle_session,
                StocktakeApprovalCommand(
                    request_id=uuid4(),
                    count_attempt_id=vehicle_attempt["attempt_id"],
                    password=PASSWORD,
                ),
                db=db,
                access=a.operator.access(db),
                legacy_actor=a.operator.operational_driver,
            )
            assert vehicle_approved["status"] == "POSTED"
            assert await _balance(
                db, a.company_id, a.vehicle_location, a.variant, a.batch
            ) == (Decimal("5.500"), Decimal("0"))
            work = await db.get(WorkSession, a.work_session)
            assert work is not None and work.inventory_reconciled_at is not None
            vehicle_movement = await db.scalar(
                select(InventoryMovement).where(
                    InventoryMovement.company_id == a.company_id,
                    InventoryMovement.stocktake_session_id == vehicle_session,
                )
            )
            assert vehicle_movement is not None
            assert vehicle_movement.reference_type == "DRIVER_SURPLUS"
            assert Decimal(vehicle_movement.quantity) == Decimal("0.250")

            a1_balance = (
                await _balance(db, a.company_id, a.a1, a.variant, a.batch)
            )[0]
            va_balance = (
                await _balance(
                    db, a.company_id, a.vehicle_location, a.variant, a.batch
                )
            )[0]
            opening_total = Decimal("10.125") + Decimal("5.250")
            expected_total = opening_total + Decimal("-0.250") + Decimal("0.250")
            assert a1_balance + va_balance == expected_total == Decimal("15.375")
            original_rows = (
                await db.scalars(
                    select(InventoryMovement)
                    .where(
                        InventoryMovement.company_id == a.company_id,
                        InventoryMovement.id.in_([opening_a1.id, opening_va.id]),
                    )
                    .order_by(InventoryMovement.id)
                )
            ).all()
            assert [
                (row.reference_type, Decimal(row.quantity)) for row in original_rows
            ] == [
                ("CP14C_OPENING", Decimal("10.125")),
                ("CP14C_OPENING", Decimal("5.250")),
            ]

        async with _runtime_session(runtime_engine, a.company_id) as db:
            with pytest.raises(HTTPException) as stock_blocked:
                await _deactivate(db, a, expected_version=1)
            _blocker(stock_blocked.value, "INVENTORY_BALANCE")

            await apply_inventory_movement(
                db,
                company_id=a.company_id,
                performed_by=a.operator.driver_id,
                product_variant_id=a.variant,
                batch_id=a.batch,
                quantity=Decimal("1.125"),
                movement_kind="RESERVATION",
                reservation_action="RELEASE",
                reference_type="CP14C_RESERVE_RELEASE",
                reference_id="A1",
                idempotency_key="CP14C-RELEASE-" + uuid4().hex,
                source_location_id=a.a1,
                destination_location_id=a.a1,
                source_stock_status="AVAILABLE",
                destination_stock_status="AVAILABLE",
            )
            transfer = await transfers.unified_transfer_dispatch(
                UnifiedDispatchRequest(
                    request_id=uuid4(),
                    source_location_id=a.a1,
                    destination_location_id=a.a2,
                    transfer_purpose="WAREHOUSE_BALANCING",
                    items=[
                        {
                            "product_variant_id": a.variant,
                            "quantity": Decimal("9.875"),
                            "uom_id": a.uom,
                        }
                    ],
                ),
                db,
                a.operator.access(db),
                a.operator.operational_driver,
            )
            with pytest.raises(HTTPException) as transfer_blocked:
                await _deactivate(db, a, expected_version=1)
            _blocker(transfer_blocked.value, "OPEN_TRANSFER")
            received = await transfers.unified_transfer_receive(
                UnifiedReceiveRequest(
                    request_id=uuid4(),
                    transfer_header_id=transfer["header_id"],
                    destination_location_id=a.a2,
                ),
                db,
                a.counter.access(db),
                a.counter.operational_driver,
            )
            assert received["status"] == "POSTED"
            assert await _balance(db, a.company_id, a.a1, a.variant, a.batch) == (
                Decimal("0"),
                Decimal("0"),
            )

        async with _runtime_session(runtime_engine, a.company_id) as db:
            blocker_session = StocktakeSession(
                company_id=a.company_id,
                location_id=a.a1,
                reference_number="CP14C-BLOCKER-" + uuid4().hex[:10],
                stocktake_type="FULL_COUNT",
                status="DRAFT",
                started_by=a.operator.driver_id,
            )
            db.add(blocker_session)
            await db.commit()
            blocker_session_id = int(blocker_session.id)
            with pytest.raises(HTTPException) as stocktake_blocked:
                await _deactivate(db, a, expected_version=1)
            _blocker(stocktake_blocked.value, "OPEN_STOCKTAKE")
            cancelled = await stocktake.cancel_stocktake_session(
                blocker_session_id,
                StocktakeCancelCommand(
                    request_id=uuid4(), password=PASSWORD, reason="resolve blocker"
                ),
                db=db,
                access=a.operator.access(db),
                legacy_actor=a.operator.operational_driver,
            )
            assert cancelled["status"] == "CANCELLED"

        async with _runtime_session(runtime_engine, a.company_id) as db:
            draft = await transfer_policy.save_transfer_destination_policy(
                TransferDestinationPolicySaveRequest(
                    request_id=uuid4(),
                    payload={
                        "quarantine_location_id": a.a1,
                        "disposal_location_id": a.a1,
                        "vendor_return_staging_location_id": a.a1,
                    },
                ),
                db,
                a.operator.access(db),
                a.operator.operational_driver,
            )
            published = await transfer_policy.publish_transfer_destination_policy_endpoint(
                draft["policy"]["id"],
                TransferDestinationPolicyPublishRequest(
                    request_id=uuid4(),
                    expected_revision=draft["policy"]["revision"],
                ),
                db,
                a.operator.access(db),
                a.operator.operational_driver,
            )
            assert published["policy"]["status"] == "PUBLISHED"
            with pytest.raises(HTTPException) as policy_blocked:
                await _deactivate(db, a, expected_version=1)
            _blocker(policy_blocked.value, "PUBLISHED_OPERATIONAL_POLICY")

            replacement = await transfer_policy.save_transfer_destination_policy(
                TransferDestinationPolicySaveRequest(
                    request_id=uuid4(),
                    payload={
                        "quarantine_location_id": a.a2,
                        "disposal_location_id": a.a2,
                        "vendor_return_staging_location_id": a.a2,
                    },
                ),
                db,
                a.operator.access(db),
                a.operator.operational_driver,
            )
            await transfer_policy.publish_transfer_destination_policy_endpoint(
                replacement["policy"]["id"],
                TransferDestinationPolicyPublishRequest(
                    request_id=uuid4(),
                    expected_revision=replacement["policy"]["revision"],
                ),
                db,
                a.operator.access(db),
                a.operator.operational_driver,
            )
            old_policy = await db.get(
                TenantOperationalPolicy, draft["policy"]["id"]
            )
            assert old_policy is not None and old_policy.status == "SUPERSEDED"

        async with _runtime_session(runtime_engine, a.company_id) as db:
            route = DispatchRoute(
                company_id=a.company_id,
                zone_id=a.zone,
                driver_id=a.field_driver,
                vehicle_id=a.vehicle,
                source_location_id=a.a1,
                dispatch_date=date.today(),
                status="active",
            )
            db.add(route)
            await db.commit()
            route_id = int(route.id)
            with pytest.raises(HTTPException) as dispatch_blocked:
                await _deactivate(db, a, expected_version=1)
            _blocker(dispatch_blocked.value, "OPEN_DISPATCH_ROUTE")
            await dispatch.update_route_status(
                route_id,
                UpdateRouteStatusRequest(status="closed"),
                db,
                a.operator.access(db),
                a.operator.operational_driver,
            )
            closed_route = await db.get(DispatchRoute, route_id)
            assert closed_route is not None and closed_route.status == "closed"

        async with _runtime_session(runtime_engine, a.company_id) as db:
            before_branch = await db.get(Branch, a.branch)
            assert before_branch is not None and before_branch.is_active is True
            final = await _deactivate(db, a, expected_version=1)
            assert final["location"]["is_active"] is False
            assert final["location"]["version"] == 2
            a1 = await db.get(InventoryLocation, a.a1)
            branch = await db.get(Branch, a.branch)
            assert a1 is not None and a1.branch_id == a.branch
            assert branch is not None and branch.is_active is True
            assert await _balance(db, a.company_id, a.a1, a.variant, a.batch) == (
                Decimal("0"),
                Decimal("0"),
            )
            assert int(
                await db.scalar(
                    select(func.count())
                    .select_from(InventoryLiveStockProjection)
                    .where(
                        InventoryLiveStockProjection.company_id == a.company_id,
                        InventoryLiveStockProjection.warehouse_location_id == a.a1,
                    )
                )
            ) == 0
            assert int(
                await db.scalar(
                    select(func.count())
                    .select_from(InventoryTransferHeader)
                    .where(
                        InventoryTransferHeader.company_id == a.company_id,
                        InventoryTransferHeader.source_location_id == a.a1,
                        InventoryTransferHeader.status.not_in(
                            ["POSTED", "REJECTED", "CANCELLED"]
                        ),
                    )
                )
            ) == 0
            assert int(
                await db.scalar(
                    select(func.count())
                    .select_from(StocktakeSession)
                    .where(
                        StocktakeSession.company_id == a.company_id,
                        StocktakeSession.location_id == a.a1,
                        StocktakeSession.status.in_(
                            [
                                "DRAFT",
                                "COUNTING",
                                "PENDING_REVIEW",
                                "RECOUNT_REQUIRED",
                                "APPROVED",
                            ]
                        ),
                    )
                )
            ) == 0

        async with AsyncSession(admin_engine, expire_on_commit=False) as verify:
            await verify.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(b.company_id)},
            )
            foreign_location = await verify.get(InventoryLocation, b.a1)
            foreign_vehicle = await verify.get(InventoryLocation, b.vehicle_location)
            assert foreign_location is not None and foreign_location.is_active is True
            assert foreign_vehicle is not None and foreign_vehicle.is_active is True
            assert (
                await _balance(verify, b.company_id, b.a1, b.variant, b.batch)
            )[0] == Decimal("9.875")

        # Successful real zero-onhand -> discovered -> reviewed -> approved
        # physical stock, using the same authoritative posting transaction.
        # Expiry/status is physical evidence, not permission to sell.
        async with _runtime_session(runtime_engine, a.company_id) as db:
            # A registered but never received batch has actual zero stock.
            # Limit this cycle-count snapshot to precisely that genuine Batch;
            # other live warehouse balances must remain untouched.
            new_batch = ProductBatch(
                company_id=a.company_id,
                product_variant_id=a.variant,
                batch_number="CP14C-DISCOVERED-" + uuid4().hex,
                production_date=date(2024, 12, 1),
                expiry_date=date(2025, 1, 1),
            )
            db.add(new_batch)
            await db.flush()
            found_batch_id = new_batch.id
            await db.commit()
            found_start = StocktakeStartCommand(
                request_id=uuid4(),
                location_id=a.a2,
                stocktake_type="CYCLE_COUNT",
                product_variant_id=a.variant,
                batch_id=found_batch_id,
                notes="CP14-C zero-onhand discovered Batch",
            )
            found_started = await stocktake.start_unified_stocktake(
                found_start, db=db, access=a.operator.access(db),
                legacy_actor=a.operator.operational_driver,
            )
            found_id = int(found_started["session_id"])
            before_found = await _balance(db, a.company_id, a.a2, a.variant, found_batch_id)
            assert before_found == (Decimal("0"), Decimal("0"))
            found_options = await stocktake_discovery.stocktake_discovery_options(
                found_id, product_variant_id=a.variant, batch_ids=None,
                search=None, cursor=None, limit=50, db=db,
                access=a.operator.access(db), actor=a.operator.operational_driver,
            )
            found_lot = next(row for row in found_options["items"] if row["id"] == found_batch_id)
            assert found_lot["expiry_date"] == date(2025, 1, 1)
            command = StocktakeCountCommand(
                request_id=uuid4(),
                items=[{
                    "product_variant_id": a.variant,
                    "batch_id": found_batch_id,
                    "stock_status": "QUARANTINED",
                    "actual_quantity": Decimal("1.000"),
                    "uom_id": a.uom,
                }],
            )
            found_count = await stocktake.submit_stocktake_count(
                found_id, command, db=db, access=a.operator.access(db),
                legacy_actor=a.operator.operational_driver,
            )
            assert found_count["status"] == "PENDING_REVIEW"
            assert await _balance(db, a.company_id, a.a2, a.variant, found_batch_id) == before_found
            found_review = await stocktake.get_stocktake_review(
                found_id, db, a.operator.access(db),
            )
            assert len(found_review["lines"]) == 1
            assert found_review["lines"][0]["line_origin"] == "DISCOVERED"
            assert found_review["lines"][0]["stock_status"] == "QUARANTINED"
            assert Decimal(found_review["lines"][0]["expected_quantity"]) == 0
            assert Decimal(found_review["lines"][0]["variance_quantity"]) == Decimal("1.000")
            approval = StocktakeApprovalCommand(
                request_id=uuid4(), count_attempt_id=found_count["attempt_id"],
                password=PASSWORD,
            )
            posted = await stocktake.approve_stocktake_session(
                found_id, approval, db=db, access=a.operator.access(db),
                legacy_actor=a.operator.operational_driver,
            )
            assert posted["status"] == "POSTED" and posted["movement_count"] == 1
            assert await stocktake.approve_stocktake_session(
                found_id, approval, db=db, access=a.operator.access(db),
                legacy_actor=a.operator.operational_driver,
            ) == posted
            status_qty = await db.scalar(select(InventoryBalance.on_hand_quantity).where(
                InventoryBalance.company_id == a.company_id,
                InventoryBalance.location_id == a.a2,
                InventoryBalance.product_variant_id == a.variant,
                InventoryBalance.batch_id == found_batch_id,
                InventoryBalance.stock_status == "QUARANTINED",
            ))
            assert Decimal(status_qty) == Decimal("1.000")
            assert int(await db.scalar(
                select(func.count()).select_from(InventoryMovement).where(
                    InventoryMovement.company_id == a.company_id,
                    InventoryMovement.stocktake_session_id == found_id,
                )
            )) == 1
            assert int(await db.scalar(
                select(func.count()).select_from(StocktakeLine).where(
                    StocktakeLine.company_id == a.company_id,
                    StocktakeLine.stocktake_session_id == found_id,
                    StocktakeLine.line_origin == "DISCOVERED",
                )
            )) == 1
            print("CP14C_DISCOVERED_EXPIRED_QUARANTINE_POSTING=PASS")

        # A separate real HTTP acceptance is deliberately run after the
        # canonical CP14-C fixture. No dependency overrides or fake bearer.
        from tests.stocktake_v1_real_http_pg16_helper import assert_real_http_stocktake
        await assert_real_http_stocktake(
            runtime_engine=runtime_engine,
            admin_engine=admin_engine,
            a=a,
            b=b,
            earlier_discovered_batch_id=found_batch_id,
            runtime_session=_runtime_session,
            grant_location=_grant_location,
            operator_password=PASSWORD,
            recounter_password=RECOUNT_PASSWORD,
        )

        # History cursor regression: synthetic terminal metadata-only fixtures
        # are permissible here to test >200 keyset rows. They are NOT stock
        # movements, approved counts or real accounting evidence.
        async with AsyncSession(admin_engine, expire_on_commit=False) as admin:
            await admin.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(a.company_id)},
            )
            for index in range(205):
                now = utc_now()
                admin.add(StocktakeSession(
                    company_id=a.company_id, location_id=a.a2,
                    reference_number=f"STK-HISTORY-PAGING-{index}-{uuid4().hex[:6]}",
                    stocktake_type="CYCLE_COUNT", status="CANCELLED",
                    scope_product_variant_id=a.variant,
                    started_by=a.operator.driver_id,
                    cancelled_by=a.operator.driver_id,
                    cancellation_reason="Synthetic terminal pagination fixture",
                    created_at=now, updated_at=now, cancelled_at=now,
                ))
            await admin.commit()
        async with _runtime_session(runtime_engine, a.company_id) as db:
            found_ids = set()
            after = None
            pages = 0
            while True:
                result = await stocktake_history.list_stocktake_history(
                    location_id=a.a2, cursor=after, limit=50,
                    db=db, access=a.operator.access(db),
                )
                pages += 1
                for item in result["items"]:
                    assert item["id"] not in found_ids
                    found_ids.add(item["id"])
                    assert item["location_id"] == a.a2
                    assert item["status"] in {"CANCELLED", "POSTED"}
                if not result["has_more"]:
                    assert result["next_cursor"] is None
                    break
                after = result["next_cursor"]
                assert after and pages <= 8
            assert len(found_ids) >= 205 and pages >= 5
            assert {rollback_session, cancel_session}.issubset(found_ids)
            with pytest.raises(HTTPException) as invalid_cursor:
                await stocktake_history.list_stocktake_history(
                    location_id=a.a2, cursor="tampered-history-cursor", limit=50,
                    db=db, access=a.operator.access(db),
                )
            assert invalid_cursor.value.status_code == 400
            print("CP14C_TERMINAL_HISTORY_GT200_PAGED_NO_LEAK=PASS")

        print("CP14C_STOCKTAKE_START_COUNT_REVIEW_APPROVE=PASS")
        print("CP14C_VARIANCE_RECOUNT=PASS")
        print("CP14C_CANCEL=PASS")
        print("CP14C_VEHICLE_RECON=PASS")
        print("CP14C_MOVEMENT_LEDGER_DECIMAL_RECONCILIATION=PASS")
        print("CP14C_IDEMPOTENCY_CONCURRENCY_ROLLBACK=PASS")
        print("CP14C_COMPANY_LOCATION_VEHICLE_ISOLATION=PASS")
        print("CP14C_LIFECYCLE_BLOCKERS_AND_FINAL_DEACTIVATION=PASS")
    finally:
        await runtime_engine.dispose()
        await admin_engine.dispose()
