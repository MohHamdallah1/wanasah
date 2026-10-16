"""CP14-A3 real PostgreSQL 16 inbound operational acceptance.

Tests + workflow only. Executes canonical Supplier inbound against a disposable,
Alembic-migrated PostgreSQL database with restricted runtime authority. It does
not exercise Batch/Quality/Transfers/Stocktake lifecycle closure owned elsewhere.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
import inspect
import os
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api import product_locations
from api.warehouse import inbound, ledger, live_stock
from context import tenant_context
from domains.authorization.backoffice_access import BackofficeCapabilityAccessRejected
from domains.inventory_supplier_evidence import InventorySupplierEvidence
from domains.live_stock_projection.service import rebuild_live_stock_company
from domains.product_tracking import public_batch_number
from domains.suppliers.models import Supplier
from models import (
    Company,
    InventoryBalance,
    InventoryCostEvent,
    InventoryCostLayer,
    InventoryCostPolicy,
    InventoryLocation,
    InventoryMovement,
    OperationIdempotency,
    Permission,
    Product,
    ProductBatch,
    ProductLocation,
    ProductUomConversion,
    ProductVariant,
    Role,
    UOM,
    UserLocationAccess,
    UserRole,
    role_permissions,
    utc_now,
)
from product_lifecycle import DEFAULT_PRODUCT_LOCATION_FLAGS
from schemas import InventoryCostPolicyUpdateRequest, UpgradedInboundRequest
from services import get_company_local_date
from tests import test_inbound_no_lot_frozen_contract as frozen_contract
from tests.canonical_actor_fixtures import (
    seed_company_owner_fixture,
    seed_ordinary_backoffice_fixture,
)


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CP14A3_PG_GATE") != "1",
        reason="Explicit disposable CP14-A3 PostgreSQL gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]

INTERNAL_NOLOT = "__WANASAH_NOLOT__"
SCOPED = (
    "inbound.create",
    "inventory.read",
    "ledger.read",
    "product_location.read",
    "product_location.manage",
    "location.read",
)
TRACKING = (
    ("NONE", "NONE"),
    ("OPTIONAL", "OPTIONAL"),
    ("REQUIRED", "REQUIRED"),
    ("OPTIONAL", "REQUIRED"),
)


def _checked_urls():
    runtime = make_url(os.environ["WANASAH_CP14A3_PG_URL"])
    admin = make_url(os.environ["WANASAH_CP14A3_PG_ADMIN_URL"])
    for url in (runtime, admin):
        if (
            url.drivername != "postgresql+asyncpg"
            or url.host != "127.0.0.1"
            or url.port != 55439
            or url.database != "wanasah_no_lot_contract_test"
        ):
            raise RuntimeError("Refusing any database outside disposable CP14-A3 PostgreSQL")
    if runtime.username != "wanasah_app" or admin.username == runtime.username:
        raise RuntimeError("CP14-A3 requires restricted runtime and distinct migration role")
    return runtime, admin


def _code(exc: HTTPException) -> str:
    if isinstance(exc.detail, dict):
        return str(exc.detail.get("code"))
    return ""


def _assert_no_internal(value) -> None:
    rendered = repr(value)
    assert INTERNAL_NOLOT not in rendered
    assert "WANASAH_NOLOT" not in rendered


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
                await db.execute(text("SET statement_timeout='20000ms'"))
                yield db
            finally:
                await db.close()
    finally:
        tenant_context.reset(token)


async def _grant_role(
    db,
    *,
    company_id: int,
    driver_id: int,
    codes: tuple[str, ...],
    location_id: int | None,
    name: str,
):
    role = Role(company_id=company_id, name=name)
    db.add(role)
    await db.flush()
    for code in codes:
        permission = await db.scalar(select(Permission).where(Permission.code == code))
        assert permission is not None, f"Migrated permission missing: {code}"
        await db.execute(
            role_permissions.insert().values(
                company_id=company_id,
                role_id=role.id,
                permission_id=permission.id,
            )
        )
    if location_id is None:
        db.add(UserRole(company_id=company_id, driver_id=driver_id, role_id=role.id))
    else:
        db.add(
            UserLocationAccess(
                company_id=company_id,
                driver_id=driver_id,
                role_id=role.id,
                location_id=location_id,
            )
        )
    await db.flush()


async def _seed_variants(db, *, company_id: int, base_uom_id: int):
    result = []
    for index, (lot_mode, expiry_mode) in enumerate(TRACKING, start=1):
        product = Product(
            company_id=company_id,
            code=f"P{index}",
            name=f"Shared Product {index}",
        )
        db.add(product)
        await db.flush()
        variant = ProductVariant(
            company_id=company_id,
            product_id=product.id,
            name=f"Shared SKU {index}",
            sku=f"SKU-P{index}",
            base_uom_id=base_uom_id,
            quantity_scale=6,
            quantity_step=Decimal("0.000001"),
            lot_control_mode=lot_mode,
            expiry_control_mode=expiry_mode,
            lifecycle_status="ACTIVE",
            operational_hold="NONE",
            published_at=utc_now(),
        )
        db.add(variant)
        await db.flush()
        result.append(variant)

    for suffix, lifecycle in (("DRAFT", "DRAFT"), ("RETIRING", "RETIRING")):
        product = Product(
            company_id=company_id,
            code=f"P-{suffix}",
            name=f"Inbound lifecycle {suffix}",
        )
        db.add(product)
        await db.flush()
        variant = ProductVariant(
            company_id=company_id,
            product_id=product.id,
            name=f"Inbound lifecycle {suffix}",
            sku=f"SKU-{suffix}",
            base_uom_id=base_uom_id,
            quantity_scale=6,
            quantity_step=Decimal("0.000001"),
            lot_control_mode="OPTIONAL",
            expiry_control_mode="OPTIONAL",
            lifecycle_status=lifecycle,
            operational_hold="NONE",
            published_at=None if lifecycle == "DRAFT" else utc_now(),
            retired_at=utc_now() if lifecycle == "RETIRING" else None,
        )
        db.add(variant)
        await db.flush()
        result.append(variant)
    return result


async def _snapshot(engine, company_id: int):
    async with _runtime_session(engine, company_id) as db:
        counts = {}
        for model in (
            ProductBatch,
            InventoryBalance,
            InventoryMovement,
            InventoryCostEvent,
            InventoryCostLayer,
            InventorySupplierEvidence,
            OperationIdempotency,
            ProductLocation,
        ):
            counts[model.__tablename__] = int(
                await db.scalar(
                    select(func.count()).select_from(model).where(model.company_id == company_id)
                )
            )
        counts["quantity"] = Decimal(
            await db.scalar(
                select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0)).where(
                    InventoryBalance.company_id == company_id
                )
            )
        )
        return counts


class Gate:
    def __init__(self, runtime_engine, admin_engine, method: str, ids, owner, operator, denied, no_supplier):
        self.runtime_engine = runtime_engine
        self.admin_engine = admin_engine
        self.method = method
        self.ids = ids
        self.owner = owner
        self.operator = operator
        self.denied = denied
        self.no_supplier = no_supplier
        self.actor = NS(id=operator.driver_id)
        self.denied_actor = NS(id=denied.driver_id)
        self.no_supplier_actor = NS(id=no_supplier.driver_id)

    @asynccontextmanager
    async def session(self, company_id=None):
        async with _runtime_session(
            self.runtime_engine,
            company_id if company_id is not None else self.ids.company_a,
        ) as db:
            yield db

    def request(
        self,
        variant_id: int,
        *,
        request_id: UUID | None = None,
        supplier_id: int | None = None,
        location_id: int | None = None,
        uom_id: int | None = None,
        quantity: str = "1",
        cost: str = "2.000000",
        lot: str | None = None,
        production=None,
        expiry=None,
        reference_id: str | None = None,
        items=None,
    ):
        if items is None:
            items = [
                {
                    "product_variant_id": variant_id,
                    "uom_id": uom_id or self.ids.each,
                    "quantity": quantity,
                    "unit_cost": cost,
                    "batch_number": lot,
                    "production_date": production,
                    "expiry_date": expiry,
                }
            ]
        return UpgradedInboundRequest(
            request_id=request_id or uuid4(),
            supplier_id=self.ids.supplier_a if supplier_id is None else supplier_id,
            location_id=location_id or self.ids.a1,
            reference_id=reference_id,
            items=items,
        )

    async def post(self, payload, *, identity=None):
        identity = identity or self.operator
        actor = (
            self.actor
            if identity is self.operator
            else self.denied_actor
            if identity is self.denied
            else self.no_supplier_actor
            if identity is self.no_supplier
            else identity.operational_driver
        )
        async with self.session() as db:
            return await inbound.warehouse_inbound(payload, db, identity.access(db), actor)


@pytest.fixture(params=["MOVING_AVERAGE", "FIFO"])
def costing_method(request):
    return request.param


@pytest.mark.asyncio
async def test_cp14a3_real_inbound_operational_journey(costing_method):
    runtime_url, admin_url = _checked_urls()
    runtime_engine = create_async_engine(runtime_url, poolclass=NullPool)
    admin_engine = create_async_engine(admin_url, poolclass=NullPool)
    try:
        async with runtime_engine.connect() as connection:
            identity = (
                await connection.execute(
                    text(
                        "SELECT current_database(), current_user, inet_server_port(), "
                        "current_setting('server_version_num')::int, r.rolsuper, r.rolbypassrls "
                        "FROM pg_roles r WHERE r.rolname=current_user"
                    )
                )
            ).one()
            assert identity[0:3] == ("wanasah_no_lot_contract_test", "wanasah_app", 55439)
            assert 160000 <= int(identity[3]) < 170000
            assert tuple(identity[4:]) == (False, False)
            for table_name in (
                "product_batches",
                "inventory_balances",
                "inventory_movements",
                "product_locations",
                "suppliers",
                "inventory_supplier_evidence",
                "operation_idempotency",
                "inventory_cost_events",
            ):
                flags = (
                    await connection.execute(
                        text(
                            "SELECT relrowsecurity, relforcerowsecurity "
                            "FROM pg_class WHERE oid=to_regclass(:table_name)"
                        ),
                        {"table_name": table_name},
                    )
                ).one()
                assert tuple(flags) == (True, True), table_name

        config = AlembicConfig(str(Path(__file__).parents[1] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
        expected_heads = set(ScriptDirectory.from_config(config).get_heads())
        async with AsyncSession(admin_engine, expire_on_commit=False) as db:
            actual_heads = set(
                (await db.execute(text("SELECT version_num FROM alembic_version"))).scalars()
            )
            assert actual_heads == expected_heads

        async with AsyncSession(admin_engine, expire_on_commit=False) as seed:
            each = await seed.scalar(select(UOM).where(UOM.code == "EACH"))
            if each is None:
                each = UOM(code="EACH", name="Each")
                seed.add(each)
                await seed.flush()
            case = await seed.scalar(select(UOM).where(UOM.code == "CASE12A3"))
            if case is None:
                case = UOM(code="CASE12A3", name="Case 12")
                seed.add(case)
            unsupported = await seed.scalar(select(UOM).where(UOM.code == "BOXA3"))
            if unsupported is None:
                unsupported = UOM(code="BOXA3", name="Unsupported box")
                seed.add(unsupported)
            await seed.flush()

            company_a = Company(
                name=f"CP14-A3 Company A {costing_method}",
                company_code="CP14A3-A-" + uuid4().hex,
                timezone="Asia/Amman",
            )
            company_b = Company(
                name=f"CP14-A3 Company B {costing_method}",
                company_code="CP14A3-B-" + uuid4().hex,
                timezone="Asia/Amman",
            )
            seed.add_all([company_a, company_b])
            await seed.flush()

            await seed.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(company_a.id)},
            )
            owner = await seed_company_owner_fixture(seed, company_a.id, password="Cp14A3OwnerSynthetic123")
            operator = await seed_ordinary_backoffice_fixture(seed, company_a.id)
            denied = await seed_ordinary_backoffice_fixture(seed, company_a.id)
            no_supplier = await seed_ordinary_backoffice_fixture(seed, company_a.id)
            a1 = InventoryLocation(
                company_id=company_a.id,
                code="CP14A3-WH1",
                name="Shared Warehouse",
                location_type="WAREHOUSE",
                is_active=True,
                is_system_managed=False,
            )
            a2 = InventoryLocation(
                company_id=company_a.id,
                code="CP14A3-WH2",
                name="Warehouse A2",
                location_type="WAREHOUSE",
                is_active=True,
                is_system_managed=False,
            )
            seed.add_all([a1, a2])
            await seed.flush()
            variants_a = await _seed_variants(seed, company_id=company_a.id, base_uom_id=each.id)
            supplier_a = Supplier(
                company_id=company_a.id,
                name="Shared Supplier",
                code="SUP-SHARED",
                created_by=owner.driver_id,
                updated_by=owner.driver_id,
            )
            seed.add(supplier_a)
            await seed.flush()
            seed.add(
                ProductUomConversion(
                    company_id=company_a.id,
                    product_variant_id=variants_a[1].id,
                    from_uom_id=case.id,
                    to_uom_id=each.id,
                    numerator=Decimal("12"),
                    denominator=Decimal("1"),
                    quantity_scale=6,
                )
            )
            await _grant_role(
                seed,
                company_id=company_a.id,
                driver_id=operator.driver_id,
                codes=SCOPED,
                location_id=a1.id,
                name="CP14-A3 A1 inbound operator",
            )
            await _grant_role(
                seed,
                company_id=company_a.id,
                driver_id=operator.driver_id,
                codes=("supplier.read",),
                location_id=None,
                name="CP14-A3 supplier reader",
            )
            await _grant_role(
                seed,
                company_id=company_a.id,
                driver_id=no_supplier.driver_id,
                codes=("inbound.create",),
                location_id=a1.id,
                name="CP14-A3 inbound without Supplier",
            )

            await seed.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(company_b.id)},
            )
            owner_b = await seed_company_owner_fixture(seed, company_b.id, password="Cp14A3OwnerBSynthetic123")
            b1 = InventoryLocation(
                company_id=company_b.id,
                code="CP14A3-WH1",
                name="Shared Warehouse",
                location_type="WAREHOUSE",
                is_active=True,
                is_system_managed=False,
            )
            seed.add(b1)
            await seed.flush()
            variants_b = await _seed_variants(seed, company_id=company_b.id, base_uom_id=each.id)
            supplier_b = Supplier(
                company_id=company_b.id,
                name="Shared Supplier",
                code="SUP-SHARED",
                created_by=owner_b.driver_id,
                updated_by=owner_b.driver_id,
            )
            seed.add(supplier_b)
            await seed.flush()
            for variant in variants_b[:4]:
                seed.add(
                    ProductLocation(
                        company_id=company_b.id,
                        location_id=b1.id,
                        product_variant_id=variant.id,
                        created_by=owner_b.driver_id,
                        operational_flags=dict(DEFAULT_PRODUCT_LOCATION_FLAGS),
                    )
                )
            await seed.flush()
            await rebuild_live_stock_company(seed, company_id=company_b.id)
            await seed.commit()

            ids = NS(
                company_a=company_a.id,
                company_b=company_b.id,
                a1=a1.id,
                a2=a2.id,
                b1=b1.id,
                each=each.id,
                case=case.id,
                unsupported=unsupported.id,
                p1=variants_a[0].id,
                p2=variants_a[1].id,
                p3=variants_a[2].id,
                p4=variants_a[3].id,
                draft=variants_a[4].id,
                retiring=variants_a[5].id,
                b_p1=variants_b[0].id,
                supplier_a=supplier_a.id,
                supplier_b=supplier_b.id,
                supplier_b_name=supplier_b.name,
                supplier_b_code=supplier_b.code,
            )

        gate = Gate(runtime_engine, admin_engine, costing_method, ids, owner, operator, denied, no_supplier)
        assert operator.context.is_company_owner is False
        assert denied.context.is_company_owner is False
        assert len({operator.context.principal_id, operator.context.backoffice_user_id, operator.driver_id}) == 3
        assert not hasattr(gate.actor, "company_id") and not hasattr(gate.actor, "is_admin")

        assignment_ids = {}
        async with gate.session() as db:
            access = operator.access(db)
            assert access.company_id == ids.company_a
            for code in SCOPED:
                await access.require(code, ids.a1)
            for code in ("inbound.create", "inventory.read", "ledger.read", "product_location.manage"):
                with pytest.raises(BackofficeCapabilityAccessRejected):
                    await access.require(code, ids.a2)
            for variant_id in (ids.p1, ids.p2, ids.p3, ids.p4):
                response = await product_locations.create_product_location(
                    product_locations.ProductLocationCreate(
                        request_id=uuid4(),
                        location_id=ids.a1,
                        product_variant_id=variant_id,
                        operational_flags={"inbound_enabled": True, "outbound_enabled": True},
                    ),
                    db,
                    access,
                    gate.actor,
                )
                row = response["product_location"]
                assert row["operational_flags"] == {"inbound_enabled": True, "outbound_enabled": True}
                assignment_ids[variant_id] = int(row["id"])

        # Bootstrap the projection only after canonical ProductLocation readiness exists.
        async with AsyncSession(admin_engine, expire_on_commit=False) as projection_seed:
            await projection_seed.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(ids.company_a)},
            )
            await rebuild_live_stock_company(projection_seed, company_id=ids.company_a)
            await projection_seed.commit()

        async with gate.session() as db:
            selected = await inbound.update_warehouse_costing_policy(
                InventoryCostPolicyUpdateRequest(
                    request_id=uuid4(), method=costing_method, expected_version=0
                ),
                db,
                owner.access(db),
                owner.operational_driver,
            )
            assert selected["method"] == costing_method
            assert selected["is_selected"] is True
            assert selected["is_active"] is False
            assert selected["is_locked"] is False

        async with gate.session() as db:
            today = await get_company_local_date(db, ids.company_a)
        valid_expiry = today + timedelta(days=30)

        missing_supplier = gate.request(ids.p2).model_copy(update={"supplier_id": None})
        with pytest.raises(HTTPException) as caught:
            await gate.post(missing_supplier)
        assert caught.value.status_code == 422 and _code(caught.value) == "SUPPLIER_REQUIRED"

        with pytest.raises(HTTPException) as caught:
            await gate.post(gate.request(ids.p2), identity=no_supplier)
        assert caught.value.status_code == 403 and _code(caught.value) == "SUPPLIER_PERMISSION_DENIED"

        with pytest.raises(HTTPException) as caught:
            await gate.post(gate.request(ids.p2), identity=denied)
        assert caught.value.status_code == 403

        foreign_supplier_payload = gate.request(ids.p2, supplier_id=ids.supplier_b)
        with pytest.raises(HTTPException) as caught:
            await gate.post(foreign_supplier_payload)
        assert caught.value.status_code == 404 and _code(caught.value) == "SUPPLIER_NOT_FOUND"
        assert ids.supplier_b_name not in repr(caught.value.detail)
        assert ids.supplier_b_code not in repr(caught.value.detail)

        before_isolation = await _snapshot(runtime_engine, ids.company_a)
        with pytest.raises(HTTPException) as caught:
            await gate.post(gate.request(ids.p2, location_id=ids.a2))
        assert caught.value.status_code == 403
        with pytest.raises(HTTPException) as caught:
            await gate.post(gate.request(ids.p2, location_id=ids.b1))
        assert caught.value.status_code == 404
        _assert_no_internal(caught.value.detail)
        with pytest.raises(HTTPException) as caught:
            await gate.post(gate.request(ids.b_p1))
        assert caught.value.status_code == 409 and _code(caught.value) == "INBOUND_VARIANT_UNAVAILABLE"
        assert "Shared SKU" not in repr(caught.value.detail)
        after_isolation = await _snapshot(runtime_engine, ids.company_a)
        assert after_isolation == before_isolation

        for variant_id in (ids.draft, ids.retiring):
            before = await _snapshot(runtime_engine, ids.company_a)
            with pytest.raises(HTTPException) as caught:
                await gate.post(gate.request(variant_id))
            assert caught.value.status_code == 409
            assert "INBOUND_NEW_BLOCKED" in _code(caught.value)
            assert await _snapshot(runtime_engine, ids.company_a) == before

        async with gate.session() as db:
            access = operator.access(db)
            disabled = await product_locations.update_product_location(
                assignment_ids[ids.p4],
                product_locations.ProductLocationUpdate(
                    request_id=uuid4(),
                    expected_version=1,
                    operational_flags={"inbound_enabled": False, "outbound_enabled": True},
                ),
                db,
                access,
                gate.actor,
            )
            assert disabled["product_location"]["version"] == 2
        with pytest.raises(HTTPException) as caught:
            await gate.post(gate.request(ids.p4, expiry=valid_expiry))
        assert _code(caught.value) == "PRODUCT_LOCATION_INBOUND_DISABLED"
        async with gate.session() as db:
            await product_locations.update_product_location(
                assignment_ids[ids.p4],
                product_locations.ProductLocationUpdate(
                    request_id=uuid4(),
                    expected_version=2,
                    operational_flags={"inbound_enabled": True, "outbound_enabled": True},
                ),
                db,
                operator.access(db),
                gate.actor,
            )

        p1_request = gate.request(ids.p1, quantity="2.500001", cost="0.123456")
        p1_response = await gate.post(p1_request)
        assert p1_response == {"message": "INBOUND_POSTED"}
        _assert_no_internal(p1_response)
        async with gate.session() as db:
            p1_batch = await db.scalar(
                select(ProductBatch).where(
                    ProductBatch.company_id == ids.company_a,
                    ProductBatch.product_variant_id == ids.p1,
                )
            )
            assert p1_batch is not None
            assert p1_batch.expiry_date is None
            assert public_batch_number(p1_batch.batch_number) is None
            assert str(p1_batch.batch_number).startswith(INTERNAL_NOLOT)
        with pytest.raises(HTTPException) as caught:
            await gate.post(gate.request(ids.p1, expiry=valid_expiry))
        assert _code(caught.value) == "INBOUND_EXPIRY_NOT_ALLOWED"
        _assert_no_internal(caught.value.detail)

        async with gate.session() as db:
            policy = await inbound.warehouse_costing_policy(db, operator.access(db))
            assert policy["method"] == costing_method
            assert policy["is_active"] is True and policy["is_locked"] is True
            current_version = int(policy["version"])
        async with gate.session() as db:
            with pytest.raises(HTTPException) as caught:
                await inbound.update_warehouse_costing_policy(
                    InventoryCostPolicyUpdateRequest(
                        request_id=uuid4(),
                        method="FIFO" if costing_method == "MOVING_AVERAGE" else "MOVING_AVERAGE",
                        expected_version=current_version,
                    ),
                    db,
                    owner.access(db),
                    owner.operational_driver,
                )
            assert _code(caught.value) == "INVENTORY_COST_POLICY_LOCKED"

        p2_anon_request = gate.request(ids.p2, quantity="1.250000", cost="1.111111")
        assert await gate.post(p2_anon_request) == {"message": "INBOUND_POSTED"}
        p2_real_lot = "A3-REAL-P2"
        p2_real_request = gate.request(
            ids.p2,
            quantity="3.000000",
            cost="2.250000",
            lot=p2_real_lot,
            production=today,
            expiry=valid_expiry,
        )
        await gate.post(p2_real_request)
        async with gate.session() as db:
            real = await db.scalar(
                select(ProductBatch).where(
                    ProductBatch.company_id == ids.company_a,
                    ProductBatch.product_variant_id == ids.p2,
                    ProductBatch.batch_number == p2_real_lot,
                )
            )
            assert real is not None and real.batch_number == p2_real_lot
            assert real.production_date == today and real.expiry_date == valid_expiry

        with pytest.raises(HTTPException) as caught:
            await gate.post(gate.request(ids.p3, expiry=valid_expiry))
        assert _code(caught.value) == "INBOUND_LOT_REQUIRED"
        with pytest.raises(HTTPException) as caught:
            await gate.post(gate.request(ids.p3, lot="A3-P3-MISSING-EXP"))
        assert _code(caught.value) == "INBOUND_EXPIRY_REQUIRED"
        await gate.post(gate.request(ids.p3, lot="A3-P3-REAL", production=today, expiry=valid_expiry))
        with pytest.raises(HTTPException) as caught:
            await gate.post(gate.request(ids.p4))
        assert _code(caught.value) == "INBOUND_EXPIRY_REQUIRED"
        await gate.post(gate.request(ids.p4, expiry=valid_expiry))

        for payload, code in (
            (
                gate.request(
                    ids.p2,
                    lot="A3-PROD-AFTER-EXP",
                    production=today + timedelta(days=2),
                    expiry=today + timedelta(days=1),
                ),
                "INBOUND_BATCH_DATES_INVALID",
            ),
            (
                gate.request(
                    ids.p2,
                    lot="A3-FUTURE-PROD",
                    production=today + timedelta(days=1),
                    expiry=today + timedelta(days=10),
                ),
                "INBOUND_PRODUCTION_DATE_FUTURE",
            ),
            (
                gate.request(ids.p2, lot="A3-EXPIRED", expiry=today - timedelta(days=1)),
                "INBOUND_BATCH_EXPIRED",
            ),
        ):
            before = await _snapshot(runtime_engine, ids.company_a)
            with pytest.raises(HTTPException) as caught:
                await gate.post(payload)
            assert _code(caught.value) == code
            _assert_no_internal(caught.value.detail)
            assert await _snapshot(runtime_engine, ids.company_a) == before

        meta_lot = "A3-METADATA"
        await gate.post(
            gate.request(
                ids.p2,
                lot=meta_lot,
                production=today,
                expiry=today + timedelta(days=20),
            )
        )
        before_meta = await _snapshot(runtime_engine, ids.company_a)
        with pytest.raises(HTTPException) as caught:
            await gate.post(
                gate.request(
                    ids.p2,
                    lot=meta_lot,
                    production=today,
                    expiry=today + timedelta(days=21),
                )
            )
        assert _code(caught.value) == "INBOUND_BATCH_METADATA_CONFLICT"
        assert await _snapshot(runtime_engine, ids.company_a) == before_meta

        uom_request = gate.request(
            ids.p2,
            uom_id=ids.case,
            quantity="1.500000",
            cost="2.250000",
            lot="A3-UOM-LOT",
        )
        await gate.post(uom_request)
        async with gate.session() as db:
            uom_batch = await db.scalar(
                select(ProductBatch).where(
                    ProductBatch.company_id == ids.company_a,
                    ProductBatch.product_variant_id == ids.p2,
                    ProductBatch.batch_number == "A3-UOM-LOT",
                )
            )
            balance = await db.scalar(
                select(InventoryBalance).where(
                    InventoryBalance.company_id == ids.company_a,
                    InventoryBalance.location_id == ids.a1,
                    InventoryBalance.product_variant_id == ids.p2,
                    InventoryBalance.batch_id == uom_batch.id,
                    InventoryBalance.stock_status == "AVAILABLE",
                )
            )
            movement = await db.scalar(
                select(InventoryMovement).where(
                    InventoryMovement.company_id == ids.company_a,
                    InventoryMovement.batch_id == uom_batch.id,
                    InventoryMovement.reference_type == "INBOUND_SUPPLIER",
                )
            )
            event = await db.scalar(
                select(InventoryCostEvent).where(
                    InventoryCostEvent.company_id == ids.company_a,
                    InventoryCostEvent.inventory_movement_id == movement.id,
                )
            )
            evidence = await db.scalar(
                select(InventorySupplierEvidence).where(
                    InventorySupplierEvidence.company_id == ids.company_a,
                    InventorySupplierEvidence.movement_id == movement.id,
                )
            )
            assert Decimal(balance.on_hand_quantity) == Decimal("18.000000")
            assert Decimal(movement.quantity) == Decimal("18.000000")
            assert event.method == costing_method
            assert Decimal(event.input_quantity) == Decimal("1.500000")
            assert Decimal(event.input_unit_cost) == Decimal("2.250000")
            assert Decimal(event.total_cost) == Decimal("3.375000")
            assert evidence.supplier_id == ids.supplier_a
            assert evidence.request_id == uom_request.request_id
            original_movement = (
                movement.id,
                Decimal(movement.quantity),
                movement.batch_id,
                movement.reference_type,
                movement.reference_id,
                movement.destination_location_id,
                movement.created_at,
            )

        before_bad_uom = await _snapshot(runtime_engine, ids.company_a)
        with pytest.raises(HTTPException) as caught:
            await gate.post(gate.request(ids.p2, uom_id=ids.unsupported, lot="A3-BAD-UOM"))
        assert _code(caught.value) == "INBOUND_UOM_UNSUPPORTED"
        assert await _snapshot(runtime_engine, ids.company_a) == before_bad_uom

        duplicate = gate.request(
            ids.p2,
            items=[
                {
                    "product_variant_id": ids.p2,
                    "uom_id": ids.each,
                    "quantity": "1",
                    "unit_cost": "1",
                    "batch_number": "A3-DUP",
                },
                {
                    "product_variant_id": ids.p2,
                    "uom_id": ids.each,
                    "quantity": "2",
                    "unit_cost": "1",
                    "batch_number": "A3-DUP",
                },
            ],
        )
        with pytest.raises(HTTPException) as caught:
            await gate.post(duplicate)
        assert _code(caught.value) == "INBOUND_DUPLICATE_BATCH_UOM_LINE"

        source = inspect.getsource(inbound.warehouse_inbound)
        assert "apply_inventory_movements_batch" in source
        assert "InventoryBalance" not in source
        assert "Decimal(item.quantity)" in source and "Decimal(item.unit_cost)" in source
        assert "float(" not in source

        async with gate.session() as db:
            access = operator.access(db)
            live = await live_stock.get_warehouse_inventory(
                location_id=ids.a1,
                cursor=None,
                limit=100,
                search="Shared SKU 2",
                only_alerts=False,
                stock_state="all",
                family_id=None,
                has_reserved=False,
                has_unavailable=False,
                has_damaged=False,
                has_recalled=False,
                has_vehicle=False,
                minimum_unset=False,
                sort="name_asc",
                db=db,
                access=access,
            )
            live_p2 = next(row for row in live["items"] if int(row["id"]) == ids.p2)
            batches = await live_stock.get_warehouse_inventory_batches(
                ids.p2, ids.a1, None, 100, db, access
            )
            uom_public = next(row for row in batches["batches"] if row["batch_number"] == "A3-UOM-LOT")
            ledger_page = await ledger.get_warehouse_ledger_cursor(
                location_id=ids.a1,
                cursor=None,
                limit=200,
                search=None,
                reference_type="INBOUND_SUPPLIER",
                reference_id=movement.reference_id,
                db=db,
                access=access,
            )
            ledger_row = ledger_page["items"][0]
            assert Decimal(str(uom_public["on_hand_quantity"])) == Decimal("18.000000")
            assert Decimal(str(ledger_row["quantity"])) == Decimal("18.000000")
            assert Decimal(str(live_p2["on_hand_quantity"])) >= Decimal("18.000000")
            assert ledger_row["batch_number"] == "A3-UOM-LOT"
            assert ledger_row["supplier_id"] == ids.supplier_a
            assert ledger_row["cost_method"] == costing_method
            assert Decimal(ledger_row["total_cost"]) == Decimal("3.375000")

        async with gate.session() as db:
            access = operator.access(db)
            p1_batches = await live_stock.get_warehouse_inventory_batches(ids.p1, ids.a1, None, 100, db, access)
            assert p1_batches["batches"][0]["batch_number"] is None
            p1_batch_id = int(p1_batches["batches"][0]["batch_id"])
            sources = await live_stock.get_batch_stock_sources(p1_batch_id, db, access)
            anon_ledger = await ledger.get_warehouse_ledger_cursor(
                ids.a1, None, 200, None, "INBOUND_SUPPLIER", None, db, access
            )
            anon_row = next(row for row in anon_ledger["items"] if row["batch_id"] == p1_batch_id)
            assert anon_row["batch_number"] is None
            assert sources["batch_number"] is None
            batch_search = await live_stock.get_warehouse_inventory_batch_products(
                ids.a1, None, 100, INTERNAL_NOLOT, db, access
            )
            ledger_search = await ledger.get_warehouse_ledger_cursor(
                ids.a1, None, 100, INTERNAL_NOLOT, None, None, db, access
            )
            assert batch_search["items"] == []
            assert ledger_search["items"] == []
            for public_value in (p1_batches, sources, anon_ledger, batch_search, ledger_search):
                _assert_no_internal(public_value)

        replay_request = gate.request(ids.p3, lot="A3-REPLAY", expiry=valid_expiry, quantity="4", cost="1.5")
        first = await gate.post(replay_request)
        before_replay = await _snapshot(runtime_engine, ids.company_a)
        second = await gate.post(replay_request)
        assert second == first == {"message": "INBOUND_POSTED"}
        assert await _snapshot(runtime_engine, ids.company_a) == before_replay
        changed = replay_request.model_copy(
            update={
                "items": [replay_request.items[0].model_copy(update={"quantity": Decimal("5")})]
            }
        )
        with pytest.raises(HTTPException) as caught:
            await gate.post(changed)
        assert caught.value.status_code == 409
        assert await _snapshot(runtime_engine, ids.company_a) == before_replay

        async with gate.session() as db:
            persisted = await db.get(InventoryMovement, original_movement[0])
            assert (
                persisted.id,
                Decimal(persisted.quantity),
                persisted.batch_id,
                persisted.reference_type,
                persisted.reference_id,
                persisted.destination_location_id,
                persisted.created_at,
            ) == original_movement

        race_lot = "A3-SAME-BATCH-RACE"
        left = gate.request(ids.p2, lot=race_lot, production=today, expiry=valid_expiry, quantity="1", cost="1")
        right = gate.request(ids.p2, lot=race_lot, production=today, expiry=valid_expiry, quantity="2", cost="1")
        async with gate.session() as left_db, gate.session() as right_db:
            results = await asyncio.wait_for(
                asyncio.gather(
                    inbound.warehouse_inbound(left, left_db, operator.access(left_db), gate.actor),
                    inbound.warehouse_inbound(right, right_db, operator.access(right_db), gate.actor),
                ),
                20,
            )
        assert results == [{"message": "INBOUND_POSTED"}, {"message": "INBOUND_POSTED"}]
        async with gate.session() as db:
            race_batch = await db.scalar(
                select(ProductBatch).where(
                    ProductBatch.company_id == ids.company_a,
                    ProductBatch.product_variant_id == ids.p2,
                    ProductBatch.batch_number == race_lot,
                )
            )
            race_moves = int(
                await db.scalar(
                    select(func.count()).select_from(InventoryMovement).where(
                        InventoryMovement.company_id == ids.company_a,
                        InventoryMovement.batch_id == race_batch.id,
                    )
                )
            )
            race_balance = await db.scalar(
                select(InventoryBalance).where(
                    InventoryBalance.company_id == ids.company_a,
                    InventoryBalance.location_id == ids.a1,
                    InventoryBalance.batch_id == race_batch.id,
                    InventoryBalance.stock_status == "AVAILABLE",
                )
            )
            assert race_moves == 2
            assert Decimal(race_balance.on_hand_quantity) == Decimal("3.000000")

        same_request = gate.request(ids.p3, lot="A3-IDEM-RACE", expiry=valid_expiry)
        reached, release = asyncio.Event(), asyncio.Event()
        real_apply = inbound.apply_inventory_movements_batch
        async with gate.session() as first_db, gate.session() as second_db:
            await second_db.execute(text("SET lock_timeout='500ms'"))

            async def pause(db, **kwargs):
                result = await real_apply(db, **kwargs)
                if db is first_db:
                    reached.set()
                    await release.wait()
                return result

            first_task = None
            with patch.object(inbound, "apply_inventory_movements_batch", side_effect=pause):
                try:
                    first_task = asyncio.create_task(
                        inbound.warehouse_inbound(
                            same_request, first_db, operator.access(first_db), gate.actor
                        )
                    )
                    await asyncio.wait_for(reached.wait(), 10)
                    with pytest.raises(HTTPException) as caught:
                        await asyncio.wait_for(
                            inbound.warehouse_inbound(
                                same_request, second_db, operator.access(second_db), gate.actor
                            ),
                            5,
                        )
                    assert caught.value.status_code == 409
                    assert _code(caught.value) == "INBOUND_CONCURRENT_CONFLICT"
                finally:
                    release.set()
                    if first_task is not None:
                        assert await asyncio.wait_for(first_task, 10) == {"message": "INBOUND_POSTED"}
        assert await gate.post(same_request) == {"message": "INBOUND_POSTED"}

        metadata_race_lot = "A3-META-RACE"
        base_meta = gate.request(
            ids.p3,
            lot=metadata_race_lot,
            production=today,
            expiry=today + timedelta(days=40),
        )
        await gate.post(base_meta)
        same_meta = gate.request(
            ids.p3,
            lot=metadata_race_lot,
            production=today,
            expiry=today + timedelta(days=40),
            quantity="2",
        )
        conflict_meta = gate.request(
            ids.p3,
            lot=metadata_race_lot,
            production=today,
            expiry=today + timedelta(days=41),
            quantity="3",
        )
        async with gate.session() as good_db, gate.session() as bad_db:
            race_results = await asyncio.gather(
                inbound.warehouse_inbound(same_meta, good_db, operator.access(good_db), gate.actor),
                inbound.warehouse_inbound(conflict_meta, bad_db, operator.access(bad_db), gate.actor),
                return_exceptions=True,
            )
        assert sum(isinstance(value, dict) for value in race_results) == 1
        errors = [value for value in race_results if isinstance(value, HTTPException)]
        assert len(errors) == 1 and _code(errors[0]) == "INBOUND_BATCH_METADATA_CONFLICT"
        async with gate.session() as db:
            meta_batch = await db.scalar(
                select(ProductBatch).where(
                    ProductBatch.company_id == ids.company_a,
                    ProductBatch.product_variant_id == ids.p3,
                    ProductBatch.batch_number == metadata_race_lot,
                )
            )
            assert meta_batch.production_date == today
            assert meta_batch.expiry_date == today + timedelta(days=40)

        rollback_request = gate.request(ids.p3, lot="A3-ROLLBACK", expiry=valid_expiry)
        before_rollback = await _snapshot(runtime_engine, ids.company_a)
        async with gate.session() as db:
            with patch.object(
                inbound,
                "complete_idempotent_operation",
                side_effect=RuntimeError("CP14-A3 synthetic pre-commit failure"),
            ):
                with pytest.raises(HTTPException) as caught:
                    await inbound.warehouse_inbound(
                        rollback_request, db, operator.access(db), gate.actor
                    )
                assert caught.value.status_code == 500
                _assert_no_internal(caught.value.detail)
        assert await _snapshot(runtime_engine, ids.company_a) == before_rollback

        async with gate.session() as db:
            assert await db.scalar(select(Supplier).where(Supplier.id == ids.supplier_b)) is None
            assert await db.scalar(select(InventoryLocation).where(InventoryLocation.id == ids.b1)) is None
            assert await db.scalar(select(ProductVariant).where(ProductVariant.id == ids.b_p1)) is None
            balances = (
                await db.scalars(
                    select(InventoryBalance).where(InventoryBalance.company_id == ids.company_a)
                )
            ).all()
            assert all(Decimal(row.on_hand_quantity) >= 0 for row in balances)

        async with gate.session() as db:
            policy_row = await db.scalar(
                select(InventoryCostPolicy).where(InventoryCostPolicy.company_id == ids.company_a)
            )
            assert policy_row.method == costing_method
            assert policy_row.is_active is True and policy_row.locked_at is not None
            layer_count = int(
                await db.scalar(
                    select(func.count()).select_from(InventoryCostLayer).where(
                        InventoryCostLayer.company_id == ids.company_a
                    )
                )
            )
            if costing_method == "FIFO":
                assert layer_count > 0
            else:
                assert layer_count == 0

    finally:
        await runtime_engine.dispose()
        await admin_engine.dispose()
