"""Real PostgreSQL 16 acceptance for CP8 Ledger and append-only inbound correction."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
import os
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import event, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api.warehouse import transfers, transfer_policy, locations
from context import tenant_context
from models import (
    Company,
    Driver,
    InventoryBalance,
    InventoryLocation,
    InventoryMovement,
    Permission,
    Product,
    ProductBatch,
    ProductUomConversion,
    ProductVariant,
    ProductLocation,
    InventoryTransferHeader,
    InventoryTransferLine,
    OverrideReason,
    TenantOperationalPolicy,
    Vehicle,
    Role,
    SystemAuditLog,
    UOM,
    UserLocationAccess,
    role_permissions,
    utc_now,
)
from services import apply_inventory_movement, read_special_transfer_destinations
from schemas import (UnifiedDispatchRequest, UnifiedReceiveRequest, UnifiedTransferDecisionRequest,
    TransferDestinationPolicySaveRequest, TransferDestinationPolicyPublishRequest,
    WarehouseLocationStateRequest, SpecialTransferDispatchRequest)
from datetime import date, timedelta
from tests.canonical_actor_fixtures import (
    seed_company_owner_fixture,
    seed_ordinary_backoffice_fixture,
)


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CP8_PG_GATE") != "1",
        reason="Explicit disposable CP8 PostgreSQL gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


def _checked_urls():
    names = ("WANASAH_CP8_PG_URL", "WANASAH_CP8_PG_ADMIN_URL")
    urls = [make_url(os.environ[name]) for name in names]
    for url in urls:
        if (
            url.drivername != "postgresql+asyncpg"
            or url.host != "127.0.0.1"
            or url.port != 55448
            or url.database != "wanasah_cp8_test"
        ):
            raise RuntimeError("Refusing any database outside the disposable CP8 PostgreSQL gate")
    if urls[0].username != "cp8_app" or urls[1].username == urls[0].username:
        raise RuntimeError("CP8 requires distinct restricted runtime and migration roles")
    return urls


class Gate:
    def __init__(self, runtime_engine, admin_engine):
        self.runtime_engine = runtime_engine
        self.admin_engine = admin_engine
        self.a = None
        self.b = None

    @asynccontextmanager
    async def session(self, tenant):
        token = tenant_context.set(tenant.company_id)
        try:
            async with self.runtime_engine.connect() as connection:
                db = AsyncSession(bind=connection, expire_on_commit=False)
                try:
                    await db.execute(
                        text("SELECT set_config('app.current_tenant',:tenant,false)"),
                        {"tenant": str(tenant.company_id)},
                    )
                    await db.execute(text("SET statement_timeout='15000ms'"))
                    yield db
                finally:
                    await db.close()
        finally:
            tenant_context.reset(token)


async def _grant_location(seed: AsyncSession, tenant, location_id: int, *codes: str) -> None:
    for code in codes:
        permission = await seed.scalar(select(Permission).where(Permission.code == code))
        assert permission is not None, f"Missing canonical fixture permission {code}"
        role = Role(company_id=tenant.company_id, name=f"CP8 {code} {uuid4().hex}")
        seed.add(role)
        await seed.flush()
        await seed.execute(
            role_permissions.insert().values(
                company_id=tenant.company_id,
                role_id=role.id,
                permission_id=permission.id,
            )
        )
        seed.add(
            UserLocationAccess(
                company_id=tenant.company_id,
                role_id=role.id,
                driver_id=tenant.ordinary.driver_id,
                location_id=location_id,
            )
        )


async def _seed_movement(db, tenant, *, location_id, reference_type, reference, quantity="10", batch_id=None):
    movement = await apply_inventory_movement(
        db,
        company_id=tenant.company_id,
        performed_by=tenant.owner.driver_id,
        product_variant_id=tenant.variant_id,
        batch_id=batch_id if batch_id is not None else tenant.batch_id,
        quantity=Decimal(quantity),
        movement_kind="PHYSICAL",
        reference_type=reference_type,
        reference_id=reference,
        idempotency_key=f"CP8-{tenant.company_id}-{location_id}-{reference_type}-{reference}-{uuid4().hex}",
        source_location_id=None,
        destination_location_id=location_id,
        source_stock_status=None,
        destination_stock_status="AVAILABLE",
        notes="overlap evidence",
    )
    return movement


@pytest_asyncio.fixture(loop_scope="function")
async def pg():
    runtime_url, admin_url = _checked_urls()
    runtime_engine = create_async_engine(runtime_url, poolclass=NullPool)
    admin_engine = create_async_engine(admin_url, poolclass=NullPool)
    gate = Gate(runtime_engine, admin_engine)
    try:
        async with runtime_engine.connect() as connection:
            identity = (
                await connection.execute(
                    text(
                        "SELECT current_database(),current_user,inet_server_port(),r.rolsuper,r.rolbypassrls "
                        "FROM pg_roles r WHERE r.rolname=current_user"
                    )
                )
            ).one()
            assert tuple(identity) == ("wanasah_cp8_test", "cp8_app", 55448, False, False)

        config = AlembicConfig(str(Path(__file__).parents[1] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
        expected_heads = set(ScriptDirectory.from_config(config).get_heads())
        async with AsyncSession(admin_engine, expire_on_commit=False) as seed:
            assert set((await seed.execute(text("SELECT version_num FROM alembic_version"))).scalars()) == expected_heads
            # Permission rows are provisioning data; use only the canonical
            # catalog for this synthetic least-privilege fixture.
            from domains.authorization.capabilities import PERMISSIONS
            needed = {code for code in PERMISSIONS if code.startswith("transfer.")} | {
                "inventory.fefo_override", "inventory.transfer_policy.manage", "location.read"}
            present = set((await seed.scalars(select(Permission.code).where(Permission.code.in_(needed)))).all())
            seed.add_all([Permission(code=code) for code in sorted(needed - present)])
            await seed.flush()
            uom = await seed.scalar(select(UOM).where(UOM.code == "EACH"))
            if uom is None:
                uom = UOM(code="EACH", name="Each")
                seed.add(uom)
                await seed.flush()
            carton_uom = await seed.scalar(select(UOM).where(UOM.code == "CARTON"))
            if carton_uom is None:
                carton_uom = UOM(code="CARTON", name="Carton")
                seed.add(carton_uom)
                await seed.flush()

            companies = [
                Company(name="CP8 Company A", company_code="CP8A-" + uuid4().hex, timezone="Asia/Amman", currency_code="JOD"),
                Company(name="CP8 Company B", company_code="CP8B-" + uuid4().hex, timezone="Asia/Amman", currency_code="JOD"),
            ]
            seed.add_all(companies)
            await seed.flush()

            tenants = []
            for index, company in enumerate(companies):
                await seed.execute(
                    text("SELECT set_config('app.current_tenant',:tenant,true)"),
                    {"tenant": str(company.id)},
                )
                owner = await seed_company_owner_fixture(seed, company.id, password="CP8FixturePassword123")
                ordinary = await seed_ordinary_backoffice_fixture(seed, company.id)
                receiver = await seed_ordinary_backoffice_fixture(seed, company.id)
                product = Product(company_id=company.id, code="OVERLAP", name="Overlap Product")
                seed.add(product)
                await seed.flush()
                variant = ProductVariant(
                    company_id=company.id,
                    product_id=product.id,
                    name="Overlap Product",
                    sku="OVERLAP-SKU",
                    base_uom_id=uom.id,
                    quantity_scale=0,
                    quantity_step=Decimal("1"),
                    lot_control_mode="REQUIRED",
                    expiry_control_mode="OPTIONAL",
                    lifecycle_status="ACTIVE",
                    published_at=utc_now(),
                )
                seed.add(variant)
                locations = [
                    InventoryLocation(company_id=company.id, code=f"WH-{index}-{i}", name="Overlap Warehouse", location_type="WAREHOUSE")
                    for i in range(2 if index == 0 else 1)
                ]
                seed.add_all(locations)
                await seed.flush()
                if index == 0:
                    seed.add(
                        ProductUomConversion(
                            company_id=company.id,
                            product_variant_id=variant.id,
                            from_uom_id=carton_uom.id,
                            to_uom_id=uom.id,
                            numerator=Decimal("50"),
                            denominator=Decimal("1"),
                            quantity_scale=0,
                        )
                    )
                    await seed.flush()
                vehicle = Vehicle(id=locations[0].id, company_id=company.id, plate_number="OVERLAP", is_active=True, maintenance_status="Active")
                seed.add(vehicle)
                await seed.flush()
                vehicle_location = InventoryLocation(company_id=company.id, code="VA", name="Overlap Warehouse", location_type="VEHICLE", vehicle_id=vehicle.id)
                quarantine = (
                    InventoryLocation(
                        company_id=company.id,
                        code="Q",
                        name="Policy Warehouse",
                        location_type="WAREHOUSE",
                    )
                    if index == 0
                    else locations[0]
                )
                seed.add(vehicle_location)
                if index == 0:
                    seed.add(quarantine)
                await seed.flush()
                reason = OverrideReason(company_id=company.id, code="APPROVED", description="Synthetic override")
                seed.add(reason)
                batch = ProductBatch(
                    company_id=company.id,
                    product_variant_id=variant.id,
                    batch_number="LOT-OVERLAP",
                    expiry_date=date.today() + timedelta(days=30),
                )
                seed.add(batch)
                await seed.flush()
                later = ProductBatch(company_id=company.id, product_variant_id=variant.id, batch_number="LOT-LATER", expiry_date=date.today() + timedelta(days=60))
                expired = ProductBatch(company_id=company.id, product_variant_id=variant.id, batch_number="LOT-EXPIRED", expiry_date=date.today() - timedelta(days=1))
                seed.add_all([later, expired])
                product_locations = {
                    int(location.id): location
                    for location in [*locations, quarantine]
                }
                for location in product_locations.values():
                    seed.add(ProductLocation(company_id=company.id, location_id=location.id, product_variant_id=variant.id, created_by=owner.driver_id))
                await seed.flush()
                tenants.append(
                    NS(
                        company_id=company.id,
                        owner=owner,
                        ordinary=ordinary,
                        receiver=receiver,
                        vehicle_id=vehicle.id,
                        vehicle_location_id=vehicle_location.id,
                        quarantine_id=quarantine.id,
                        reason_id=reason.id,
                        later_batch_id=later.id,
                        expired_batch_id=expired.id,
                        variant_id=variant.id,
                        uom_id=uom.id,
                        batch_id=batch.id,
                        locations=[location.id for location in locations],
                    )
                )

            gate.a, gate.b = tenants
            await _grant_location(seed, gate.a, gate.a.locations[0], "transfer.read", "transfer.send", "transfer.cancel", "inventory.fefo_override")
            await _grant_location(seed, gate.a, gate.a.locations[1], "transfer.destination")
            original = gate.a.ordinary
            gate.a.ordinary = gate.a.receiver
            await _grant_location(seed, gate.a, gate.a.locations[1], "transfer.read", "transfer.receive", "transfer.reject")
            gate.a.ordinary = original
            await seed.commit()

        for tenant in (gate.a, gate.b):
            async with gate.session(tenant) as db:
                for location_id in [*tenant.locations, tenant.vehicle_location_id]:
                    for batch_id in [tenant.batch_id, tenant.later_batch_id, tenant.expired_batch_id]:
                        await _seed_movement(db, tenant, location_id=location_id, reference_type="INBOUND_SUPPLIER", reference="INV-OVERLAP", quantity="20", batch_id=batch_id)
                await db.commit()

        yield gate
    finally:
        await runtime_engine.dispose()
        await admin_engine.dispose()



def dispatch_payload(tenant, *, request_id=None, **changes):
    values = dict(request_id=request_id or uuid4(), source_location_id=tenant.locations[0],
        destination_location_id=tenant.locations[1], transfer_purpose="WAREHOUSE_BALANCING",
        items=[dict(product_variant_id=tenant.variant_id, quantity="4", uom_id=tenant.uom_id)])
    values.update(changes)
    return UnifiedDispatchRequest(**values)


async def send(pg, payload=None, actor=None):
    tenant = pg.a
    actor = actor or tenant.ordinary
    async with pg.session(tenant) as db:
        return await transfers.unified_transfer_dispatch(payload or dispatch_payload(tenant), db, actor.access(db), actor.operational_driver)


async def source_page(db, access, location_id, *, cursor=None, limit=50, search=None):
    return await transfers.get_unified_transfer_source_inventory(location_id, cursor, limit, search, db, access,
        destination_location_id=None, transfer_purpose="WAREHOUSE_BALANCING")


async def list_page(db, access, location_id, *, cursor=None, limit=50, search=None):
    return await transfers.list_unified_transfers(None, location_id, "all", search, cursor, limit, db, access)


async def test_transfer_integrity_messages_distinguish_stale_schema_from_data_conflict():
    stale = transfers._transfer_integrity_conflict_detail(
        Exception(
            "violates check constraint "
            "ck_inventory_transfer_headers_chk_transfer_header_separation_of_duties"
        ),
        action_label="استلام",
        header_id=44,
    )
    assert stale["code"] == "TRANSFER_SCHEMA_UPDATE_REQUIRED"
    assert stale["context"]["required_revision"] == "c3e7a5d9b214"
    assert "تحديث قاعدة البيانات" in stale["message"]

    generic = transfers._transfer_integrity_conflict_detail(
        Exception("synthetic integrity conflict"),
        action_label="رفض",
        header_id=45,
    )
    assert generic["code"] == "TRANSFER_INTEGRITY_CONFLICT"
    assert generic["context"]["transfer_header_id"] == 45
    assert "تعذر رفض الحوالة" in generic["message"]


async def test_company_source_destination_vehicle_discovery_and_forged_ids(pg):
    async with pg.session(pg.a) as db:
        access = pg.a.ordinary.access(db)
        for purpose, expected in [("source", {pg.a.locations[0]}), ("destination", {pg.a.locations[1]})]:
            rows = await transfers.list_unified_transfer_locations(purpose, None, 100, db, access)
            assert {row["id"] for row in rows} == expected
            assert pg.a.vehicle_location_id not in expected
            assert pg.b.locations[0] not in expected
        page = await source_page(db, access, pg.a.locations[0], search="Overlap")
        assert page["total"] == 1 and [r["id"] for r in page["items"]] == [pg.a.variant_id]
        assert Decimal(page["items"][0]["available_quantity"]) == 40
        assert page["items"][0]["display_uom_code"] == "CARTON"
        assert Decimal(page["items"][0]["display_factor_to_base"]) == 50
        assert page["items"][0]["display_quantity_scale"] == 0
        assert page["items"][0]["lot_control_mode"] == "REQUIRED"
        assert page["items"][0]["has_user_visible_lot"] is True
        for forbidden in [pg.a.locations[1], pg.a.vehicle_location_id, pg.b.locations[0], pg.b.vehicle_location_id]:
            with pytest.raises(HTTPException) as denied:
                await source_page(db, access, forbidden)
            assert denied.value.status_code in {403, 404}
    for payload in [
        dispatch_payload(pg.a, source_location_id=pg.a.locations[1], destination_location_id=pg.a.locations[0]),
        dispatch_payload(pg.a, destination_location_id=pg.a.vehicle_location_id),
        dispatch_payload(pg.a, destination_location_id=pg.b.locations[0]),
        dispatch_payload(pg.a, destination_location_id=pg.b.vehicle_location_id),
    ]:
        with pytest.raises(HTTPException) as denied:
            await send(pg, payload)
        assert denied.value.status_code in {403, 404}
    # A vehicle master ID intentionally equals a warehouse location ID.
    assert pg.a.vehicle_id == pg.a.locations[0]
    assert pg.a.vehicle_location_id != pg.a.vehicle_id
    async with pg.session(pg.a) as db:
        assert (await source_page(db, pg.a.ordinary.access(db), pg.a.vehicle_id))["total"] == 1
        with pytest.raises(HTTPException):
            await source_page(db, pg.a.ordinary.access(db), pg.a.vehicle_location_id)


@pytest.mark.parametrize("action,terminal", [("receive", "POSTED"), ("cancel", "CANCELLED"), ("reject", "REJECTED")])
async def test_lifecycle_replay_scope_movement_and_reserved_stock(pg, action, terminal):
    async with pg.session(pg.a) as db:
        await apply_inventory_movement(db, company_id=pg.a.company_id, performed_by=pg.a.owner.driver_id,
            product_variant_id=pg.a.variant_id, batch_id=pg.a.batch_id, quantity=Decimal("3"),
            movement_kind="RESERVATION", reservation_action="RESERVE", reference_type="CP8_RESERVE",
            reference_id="reserved-other-command", idempotency_key=str(uuid4()),
            source_location_id=pg.a.locations[0], destination_location_id=pg.a.locations[0],
            source_stock_status="AVAILABLE", destination_stock_status="AVAILABLE")
        await db.commit()
    payload = dispatch_payload(pg.a)
    sent = await send(pg, payload)
    assert await send(pg, payload) == sent
    actor = pg.a.ordinary if action == "cancel" else pg.a.receiver
    command_id = uuid4()
    async def decision():
        async with pg.session(pg.a) as db:
            if action == "receive":
                return await transfers.unified_transfer_receive(UnifiedReceiveRequest(
                    request_id=command_id, transfer_header_id=sent["header_id"], destination_location_id=pg.a.locations[1]),
                    db, actor.access(db), actor.operational_driver)
            return await getattr(transfers, "unified_transfer_" + action)(sent["header_id"],
                UnifiedTransferDecisionRequest(request_id=command_id, decision_reason="CP8 decision"),
                db, actor.access(db), actor.operational_driver)
    from services import apply_inventory_movements_batch as real_apply
    async def fail_after_terminal_movement(*args, **kwargs):
        await real_apply(*args, **kwargs)
        raise RuntimeError("Synthetic terminal failure")
    with patch.object(transfers, "apply_inventory_movements_batch", fail_after_terminal_movement):
        with pytest.raises(HTTPException) as failed:
            await decision()
        assert failed.value.status_code == 500
    async with pg.session(pg.a) as db:
        rolled_back = await db.get(InventoryTransferHeader, sent["header_id"])
        assert rolled_back.status == "IN_TRANSIT"
        assert await db.scalar(select(func.count()).select_from(InventoryMovement).where(
            InventoryMovement.company_id == pg.a.company_id, InventoryMovement.transfer_header_id == rolled_back.id)) == 1
    result, duplicate = await asyncio.gather(decision(), decision())
    assert result == duplicate
    assert result["status"] == terminal and await decision() == result
    async with pg.session(pg.a) as db:
        header = await db.get(InventoryTransferHeader, sent["header_id"])
        assert header.status == terminal
        assert await db.scalar(select(func.count()).select_from(InventoryMovement).where(
            InventoryMovement.company_id == pg.a.company_id, InventoryMovement.transfer_header_id == header.id)) == 2
        balance = await db.scalar(select(InventoryBalance).where(
            InventoryBalance.company_id == pg.a.company_id, InventoryBalance.location_id == pg.a.locations[0],
            InventoryBalance.batch_id == pg.a.batch_id, InventoryBalance.stock_status == "AVAILABLE"))
        assert balance.reserved_quantity == 3
        assert balance.on_hand_quantity == (16 if action == "receive" else 20)
        transit = await db.scalar(select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0)).where(
            InventoryBalance.company_id == pg.a.company_id, InventoryBalance.location_id == header.transit_location_id))
        assert transit == 0
        await apply_inventory_movement(db, company_id=pg.a.company_id, performed_by=pg.a.owner.driver_id,
            product_variant_id=pg.a.variant_id, batch_id=pg.a.batch_id, quantity=Decimal("3"),
            movement_kind="RESERVATION", reservation_action="RELEASE", reference_type="CP8_RELEASE",
            reference_id="reserved-other-command", idempotency_key=str(uuid4()),
            source_location_id=pg.a.locations[0], destination_location_id=pg.a.locations[0],
            source_stock_status="AVAILABLE", destination_stock_status="AVAILABLE")
        await db.commit()
    async with pg.session(pg.b) as db:
        for header_id in [sent["header_id"], 2147483647]:
            with pytest.raises(HTTPException) as denied:
                await transfers.get_unified_transfer_detail(header_id, db, pg.b.owner.access(db))
            assert denied.value.status_code == 404


async def test_fefo_order_override_exact_capability_and_audit(pg):
    async with pg.session(pg.a) as db:
        options = await transfers.get_unified_transfer_override_options(pg.a.locations[0], pg.a.variant_id, db, pg.a.ordinary.access(db))
        assert options["fefo_batch_id"] == pg.a.batch_id
        assert [row["id"] for row in options["batches"]] == [pg.a.batch_id, pg.a.later_batch_id]
        with pytest.raises(HTTPException):
            await transfers.get_unified_transfer_override_options(pg.a.locations[1], pg.a.variant_id, db, pg.a.receiver.access(db))
    payload = dispatch_payload(pg.a, items=[dict(product_variant_id=pg.a.variant_id, quantity="2", uom_id=pg.a.uom_id,
        is_fefo_override=True, override_batch_id=pg.a.later_batch_id, override_reason_id=pg.a.reason_id)])
    sent = await send(pg, payload)
    async with pg.session(pg.a) as db:
        line = await db.scalar(select(InventoryTransferLine).where(InventoryTransferLine.company_id == pg.a.company_id,
            InventoryTransferLine.transfer_header_id == sent["header_id"]))
        assert line.batch_id == pg.a.later_batch_id and line.fefo_override_reason_id == pg.a.reason_id
        assert line.fefo_overridden_by == pg.a.ordinary.driver_id and line.fefo_override_note
        assert await db.scalar(select(func.count()).select_from(SystemAuditLog).where(
            SystemAuditLog.company_id == pg.a.company_id, SystemAuditLog.target_id == f'Transfer_{sent["header_id"]}',
            SystemAuditLog.action_type == "FEFO_OVERRIDE")) == 1
    async with AsyncSession(pg.admin_engine) as db:
        permission = await db.scalar(select(Permission.id).where(Permission.code == "inventory.fefo_override"))
        await db.execute(role_permissions.delete().where(role_permissions.c.company_id == pg.a.company_id,
            role_permissions.c.permission_id == permission))
        await db.commit()
    with pytest.raises(HTTPException) as denied:
        await send(pg, payload)
    assert denied.value.status_code == 403

    # Ordinary warehouse transfers may record the exact physical source batch
    # without FEFO-override permission or an override reason.
    exact_payload = dispatch_payload(
        pg.a,
        items=[dict(
            product_variant_id=pg.a.variant_id,
            quantity="3",
            uom_id=pg.a.uom_id,
            batch_id=pg.a.later_batch_id,
        )],
    )
    exact_sent = await send(pg, exact_payload)
    async with pg.session(pg.a) as db:
        exact_line = await db.scalar(
            select(InventoryTransferLine).where(
                InventoryTransferLine.company_id == pg.a.company_id,
                InventoryTransferLine.transfer_header_id
                == exact_sent["header_id"],
            )
        )
        assert exact_line.batch_id == pg.a.later_batch_id
        assert exact_line.fefo_override_reason_id is None
        assert exact_line.fefo_overridden_by is None

        internal_no_lot = ProductBatch(
            company_id=pg.a.company_id,
            product_variant_id=pg.a.variant_id,
            batch_number="__WANASAH_NOLOT__:CP8-HIDDEN",
        )
        db.add(internal_no_lot)
        await db.flush()
        await _seed_movement(
            db,
            pg.a,
            location_id=pg.a.locations[0],
            reference_type="INBOUND_SUPPLIER",
            reference="INV-HIDDEN-NOLOT",
            quantity="2",
            batch_id=internal_no_lot.id,
        )
        await db.flush()

        batch_options = await transfers.get_unified_transfer_batch_options(
            pg.a.locations[0],
            pg.a.variant_id,
            db,
            pg.a.ordinary.access(db),
        )
        assert batch_options["recommended_batch_id"] == pg.a.batch_id
        assert {
            row["id"] for row in batch_options["batches"]
        } == {pg.a.batch_id, pg.a.later_batch_id}
        assert all(
            row["batch_number"] is not None
            for row in batch_options["batches"]
        )


async def test_same_actor_can_dispatch_split_exact_batches_and_receive(pg):
    async with AsyncSession(pg.admin_engine) as seed:
        await _grant_location(
            seed,
            pg.a,
            pg.a.locations[1],
            "transfer.destination",
            "transfer.read",
            "transfer.receive",
            "transfer.reject",
        )
        await seed.commit()

    actor = pg.a.ordinary
    payload = dispatch_payload(
        pg.a,
        items=[
            dict(
                product_variant_id=pg.a.variant_id,
                quantity="2",
                uom_id=pg.a.uom_id,
                batch_id=pg.a.batch_id,
            ),
            dict(
                product_variant_id=pg.a.variant_id,
                quantity="3",
                uom_id=pg.a.uom_id,
                batch_id=pg.a.later_batch_id,
            ),
        ],
    )
    sent = await send(pg, payload, actor)

    async with pg.session(pg.a) as db:
        found = await list_page(
            db,
            actor.access(db),
            pg.a.locations[0],
            search=str(sent["header_id"]),
        )
        assert [row["id"] for row in found["items"]] == [sent["header_id"]]

        result = await transfers.unified_transfer_receive(
            UnifiedReceiveRequest(
                request_id=uuid4(),
                transfer_header_id=sent["header_id"],
                destination_location_id=pg.a.locations[1],
            ),
            db,
            actor.access(db),
            actor.operational_driver,
        )
        assert result["status"] == "POSTED"
        header = await db.get(InventoryTransferHeader, sent["header_id"])
        assert header.dispatched_by == actor.driver_id
        assert header.received_by == actor.driver_id
        assert await db.scalar(
            select(func.count()).select_from(InventoryTransferLine).where(
                InventoryTransferLine.company_id == pg.a.company_id,
                InventoryTransferLine.transfer_header_id == sent["header_id"],
            )
        ) == 2
        assert await db.scalar(
            select(func.count()).select_from(InventoryMovement).where(
                InventoryMovement.company_id == pg.a.company_id,
                InventoryMovement.transfer_header_id == sent["header_id"],
            )
        ) == 4


async def test_same_actor_can_reject_own_generic_transfer(pg):
    async with AsyncSession(pg.admin_engine) as seed:
        await _grant_location(
            seed,
            pg.a,
            pg.a.locations[1],
            "transfer.destination",
            "transfer.read",
            "transfer.receive",
            "transfer.reject",
        )
        await seed.commit()

    actor = pg.a.ordinary
    sent = await send(pg, actor=actor)
    async with pg.session(pg.a) as db:
        result = await transfers.unified_transfer_reject(
            sent["header_id"],
            UnifiedTransferDecisionRequest(
                request_id=uuid4(),
                decision_reason="same authorized operator",
            ),
            db,
            actor.access(db),
            actor.operational_driver,
        )
        assert result["status"] == "REJECTED"
        header = await db.get(InventoryTransferHeader, sent["header_id"])
        assert header.dispatched_by == actor.driver_id
        assert header.received_by == actor.driver_id
        assert header.decision_reason == "same authorized operator"


async def test_concurrent_duplicates_mismatch_and_transaction_rollback(pg):
    payload = dispatch_payload(pg.a)
    one, two = await asyncio.gather(send(pg, payload), send(pg, payload))
    assert one == two
    with pytest.raises(HTTPException) as mismatch:
        await send(pg, payload.model_copy(update={"notes": "changed input"}))
    assert mismatch.value.status_code == 409
    async with pg.session(pg.a) as db:
        count = await db.scalar(select(func.count()).select_from(InventoryTransferHeader).where(
            InventoryTransferHeader.company_id == pg.a.company_id))
        assert count == 1
    from services import apply_inventory_movements_batch as real_apply
    async def fail_after_apply(*args, **kwargs):
        await real_apply(*args, **kwargs)
        raise RuntimeError("Synthetic failure after authoritative movement")
    with patch.object(transfers, "apply_inventory_movements_batch", fail_after_apply):
        with pytest.raises(HTTPException) as rollback:
            await send(pg)
        assert rollback.value.status_code == 500
    async with pg.session(pg.a) as db:
        assert await db.scalar(select(func.count()).select_from(InventoryTransferHeader).where(
            InventoryTransferHeader.company_id == pg.a.company_id)) == 1
        assert await db.scalar(select(func.count()).select_from(InventoryMovement).where(
            InventoryMovement.company_id == pg.a.company_id, InventoryMovement.reference_type == "TRANSFER_DISPATCH")) == 1


@pytest.mark.parametrize("guard", ["source", "destination", "lifecycle"])
async def test_product_location_and_lifecycle_guards(pg, guard):
    async with pg.session(pg.a) as db:
        if guard == "lifecycle":
            variant = await db.get(ProductVariant, pg.a.variant_id)
            variant.operational_hold = "RECALL"
        else:
            location_id = pg.a.locations[0 if guard == "source" else 1]
            assignment = await db.scalar(select(ProductLocation).where(ProductLocation.company_id == pg.a.company_id,
                ProductLocation.location_id == location_id, ProductLocation.product_variant_id == pg.a.variant_id))
            assignment.operational_flags = {"inbound_enabled": guard != "destination", "outbound_enabled": guard != "source"}
        await db.commit()
    with pytest.raises(HTTPException) as rejected:
        await send(pg)
    assert rejected.value.status_code == 409
    async with pg.session(pg.a) as db:
        assert await db.scalar(select(func.count()).select_from(InventoryTransferHeader).where(
            InventoryTransferHeader.company_id == pg.a.company_id)) == 0


async def test_policy_draft_publish_replay_revocation_and_deactivation_blocker(pg):
    actor = pg.a.owner
    draft_request = TransferDestinationPolicySaveRequest(request_id=uuid4(), payload=dict(
        quarantine_location_id=pg.a.quarantine_id, disposal_location_id=pg.a.quarantine_id,
        vendor_return_staging_location_id=pg.a.quarantine_id))
    async with pg.session(pg.a) as db:
        denied = pg.a.ordinary.access(db)
        with pytest.raises(HTTPException) as absent:
            await transfer_policy.get_transfer_destination_policy(db, denied)
        assert absent.value.status_code == 403
    async with pg.session(pg.a) as db:
        draft = await transfer_policy.save_transfer_destination_policy(draft_request, db, actor.access(db), actor.operational_driver)
        assert await transfer_policy.save_transfer_destination_policy(draft_request, db, actor.access(db), actor.operational_driver) == draft
        publish = TransferDestinationPolicyPublishRequest(request_id=uuid4(), expected_revision=draft["policy"]["revision"])
        result = await transfer_policy.publish_transfer_destination_policy_endpoint(draft["policy"]["id"], publish, db, actor.access(db), actor.operational_driver)
        assert await transfer_policy.publish_transfer_destination_policy_endpoint(draft["policy"]["id"], publish, db, actor.access(db), actor.operational_driver) == result
        state = await transfer_policy.get_transfer_destination_policy(db, actor.access(db))
        assert state["published"]["id"] == draft["policy"]["id"] and state["draft"] is None
        with pytest.raises(HTTPException) as blocked:
            await locations.deactivate_warehouse_location(pg.a.quarantine_id,
                WarehouseLocationStateRequest(request_id=uuid4(), expected_version=1, reason="CP8 policy regression"),
                db, actor.access(db), actor.operational_driver)
        assert blocked.value.status_code == 409
        assert blocked.value.detail["context"]["blocker_type"] == "PUBLISHED_OPERATIONAL_POLICY"
    async with pg.session(pg.a) as db:
        foreign = draft_request.model_copy(update={"request_id": uuid4(), "payload": draft_request.payload.model_copy(update={"quarantine_location_id": pg.b.locations[0]})})
        with pytest.raises(HTTPException) as rejected:
            await transfer_policy.save_transfer_destination_policy(foreign, db, actor.access(db), actor.operational_driver)
        assert rejected.value.status_code in {400, 404}
    # Grant exact policy capability to an ordinary actor, revoke only location.read,
    # and prove cached read/save/publish results cannot bypass current location ACLs.
    async with AsyncSession(pg.admin_engine) as db:
        from models import UserRole
        permission = await db.scalar(select(Permission).where(Permission.code == "inventory.transfer_policy.manage"))
        role = Role(company_id=pg.a.company_id, name="CP8 policy " + uuid4().hex)
        db.add(role)
        await db.flush()
        await db.execute(role_permissions.insert().values(company_id=pg.a.company_id, role_id=role.id, permission_id=permission.id))
        db.add(UserRole(company_id=pg.a.company_id, role_id=role.id, driver_id=pg.a.ordinary.driver_id))
        await _grant_location(db, pg.a, pg.a.quarantine_id, "location.read")
        await db.commit()
    request = draft_request.model_copy(update={"request_id": uuid4()})
    async with pg.session(pg.a) as db:
        ordinary = pg.a.ordinary
        draft = await transfer_policy.save_transfer_destination_policy(request, db, ordinary.access(db), ordinary.operational_driver)
        publish = TransferDestinationPolicyPublishRequest(request_id=uuid4(), expected_revision=draft["policy"]["revision"])
        await transfer_policy.publish_transfer_destination_policy_endpoint(draft["policy"]["id"], publish, db, ordinary.access(db), ordinary.operational_driver)
    async with AsyncSession(pg.admin_engine) as db:
        await db.execute(UserLocationAccess.__table__.delete().where(UserLocationAccess.company_id == pg.a.company_id,
            UserLocationAccess.driver_id == pg.a.ordinary.driver_id, UserLocationAccess.location_id == pg.a.quarantine_id))
        await db.commit()
    for operation in ["read", "draft", "publish"]:
        async with pg.session(pg.a) as db:
            with pytest.raises(HTTPException) as revoked:
                if operation == "read": await transfer_policy.get_transfer_destination_policy(db, ordinary.access(db))
                elif operation == "draft": await transfer_policy.save_transfer_destination_policy(request, db, ordinary.access(db), ordinary.operational_driver)
                else: await transfer_policy.publish_transfer_destination_policy_endpoint(draft["policy"]["id"], publish, db, ordinary.access(db), ordinary.operational_driver)
            assert revoked.value.status_code == 403


async def test_zero_policy_one_warehouse_uses_effective_default_and_materializes_once(pg):
    tenant = pg.b
    actor = tenant.owner
    source_location_id = tenant.locations[0]
    request_id = uuid4()
    command = SpecialTransferDispatchRequest(
        request_id=request_id,
        source_location_id=source_location_id,
        transfer_purpose="DISPOSAL",
        notes="CP8 lazy same-location default",
        items=[dict(
            product_variant_id=tenant.variant_id,
            batch_id=tenant.expired_batch_id,
            source_status="AVAILABLE",
            quantity="2",
            uom_id=tenant.uom_id,
        )],
    )

    async with pg.session(tenant) as db:
        active_warehouses = await db.scalar(
            select(func.count()).select_from(InventoryLocation).where(
                InventoryLocation.company_id == tenant.company_id,
                InventoryLocation.location_type == "WAREHOUSE",
                InventoryLocation.is_active.is_(True),
            )
        )
        assert active_warehouses == 1
        assert await db.scalar(
            select(func.count()).select_from(TenantOperationalPolicy).where(
                TenantOperationalPolicy.company_id == tenant.company_id,
                TenantOperationalPolicy.policy_code == "INVENTORY_TRANSFER_DESTINATIONS",
            )
        ) == 0

        # Read authority exposes the effective default but does not materialize it.
        assert await read_special_transfer_destinations(
            db, company_id=tenant.company_id
        ) == {
            "RETURN_TO_VENDOR": None,
            "QUARANTINE": None,
            "RECALL_RETURN": None,
            "DISPOSAL": None,
        }
        assert await db.scalar(
            select(func.count()).select_from(TenantOperationalPolicy).where(
                TenantOperationalPolicy.company_id == tenant.company_id,
                TenantOperationalPolicy.policy_code == "INVENTORY_TRANSFER_DESTINATIONS",
            )
        ) == 0

    async with pg.session(tenant) as db:
        first = await transfers.special_transfer_dispatch(
            command,
            db,
            actor.access(db),
            actor.operational_driver,
        )
        assert first["source_location_id"] == source_location_id
        assert first["destination_location_id"] == source_location_id

        policies = (
            await db.execute(
                select(TenantOperationalPolicy).where(
                    TenantOperationalPolicy.company_id == tenant.company_id,
                    TenantOperationalPolicy.policy_code == "INVENTORY_TRANSFER_DESTINATIONS",
                )
            )
        ).scalars().all()
        assert len(policies) == 1
        policy = policies[0]
        assert policy.status == "PUBLISHED"
        assert dict(policy.validated_payload) == {
            "quarantine_location_id": None,
            "disposal_location_id": None,
            "vendor_return_staging_location_id": None,
            "allow_retiring_warehouse_balancing": False,
        }

        header = await db.get(InventoryTransferHeader, first["header_id"])
        assert header.tenant_policy_id == policy.id
        assert header.tenant_policy_revision == policy.revision
        assert header.workflow_type == "DIRECT"
        assert header.status == "POSTED"

        movement = await db.scalar(
            select(InventoryMovement).where(
                InventoryMovement.company_id == tenant.company_id,
                InventoryMovement.transfer_header_id == first["header_id"],
            )
        )
        assert movement.movement_kind == "STATUS_CHANGE"
        assert movement.source_location_id == source_location_id
        assert movement.destination_location_id == source_location_id

        # Exact retry returns the committed result before attempting another
        # lazy materialization or creating duplicate movement evidence.
        replay = await transfers.special_transfer_dispatch(
            command,
            db,
            actor.access(db),
            actor.operational_driver,
        )
        assert replay == first
        assert await db.scalar(
            select(func.count()).select_from(TenantOperationalPolicy).where(
                TenantOperationalPolicy.company_id == tenant.company_id,
                TenantOperationalPolicy.policy_code == "INVENTORY_TRANSFER_DESTINATIONS",
            )
        ) == 1
        assert await db.scalar(
            select(func.count()).select_from(InventoryTransferHeader).where(
                InventoryTransferHeader.company_id == tenant.company_id,
                InventoryTransferHeader.id == first["header_id"],
            )
        ) == 1

        # Lazy evidence may create the canonical system transit location, but it
        # must never invent another operational warehouse.
        assert await db.scalar(
            select(func.count()).select_from(InventoryLocation).where(
                InventoryLocation.company_id == tenant.company_id,
                InventoryLocation.location_type == "WAREHOUSE",
                InventoryLocation.is_active.is_(True),
            )
        ) == 1


async def test_explicit_legacy_published_policy_still_routes_to_explicit_destination(pg):
    actor = pg.a.owner
    explicit_destination = pg.a.quarantine_id

    async with pg.session(pg.a) as db:
        draft = await transfer_policy.save_transfer_destination_policy(
            TransferDestinationPolicySaveRequest(
                request_id=uuid4(),
                payload=dict(
                    quarantine_location_id=explicit_destination,
                    disposal_location_id=explicit_destination,
                    vendor_return_staging_location_id=explicit_destination,
                ),
            ),
            db,
            actor.access(db),
            actor.operational_driver,
        )
        published = await transfer_policy.publish_transfer_destination_policy_endpoint(
            draft["policy"]["id"],
            TransferDestinationPolicyPublishRequest(
                request_id=uuid4(),
                expected_revision=draft["policy"]["revision"],
            ),
            db,
            actor.access(db),
            actor.operational_driver,
        )
        published_payload = dict(published["policy"]["validated_payload"])

    command = SpecialTransferDispatchRequest(
        request_id=uuid4(),
        source_location_id=pg.a.locations[0],
        transfer_purpose="DISPOSAL",
        notes="CP8 explicit legacy route",
        items=[dict(
            product_variant_id=pg.a.variant_id,
            batch_id=pg.a.expired_batch_id,
            source_status="AVAILABLE",
            quantity="2",
            uom_id=pg.a.uom_id,
        )],
    )
    async with pg.session(pg.a) as db:
        result = await transfers.special_transfer_dispatch(
            command,
            db,
            actor.access(db),
            actor.operational_driver,
        )
        assert result["destination_location_id"] == explicit_destination
        assert result["source_location_id"] != result["destination_location_id"]
        header = await db.get(InventoryTransferHeader, result["header_id"])
        assert header.workflow_type == "TRANSIT"
        assert header.status == "IN_TRANSIT"
        assert await transfers.special_transfer_dispatch(
            command,
            db,
            actor.access(db),
            actor.operational_driver,
        ) == result

        current = await db.scalar(
            select(TenantOperationalPolicy).where(
                TenantOperationalPolicy.company_id == pg.a.company_id,
                TenantOperationalPolicy.policy_code == "INVENTORY_TRANSFER_DESTINATIONS",
                TenantOperationalPolicy.status == "PUBLISHED",
            )
        )
        assert dict(current.validated_payload) == published_payload
        assert current.id == published["policy"]["id"]


async def test_in_place_quality_policy_stages_status_without_physical_transfer(pg):
    actor = pg.a.owner
    source_location_id = pg.a.locations[0]
    command = SpecialTransferDispatchRequest(
        request_id=uuid4(),
        source_location_id=source_location_id,
        transfer_purpose="DISPOSAL",
        notes="CP8 in-place quality default",
        items=[dict(
            product_variant_id=pg.a.variant_id,
            batch_id=pg.a.expired_batch_id,
            source_status="AVAILABLE",
            quantity="2",
            uom_id=pg.a.uom_id,
        )],
    )

    async with pg.session(pg.a) as db:
        before_total = await db.scalar(
            select(func.sum(InventoryBalance.on_hand_quantity)).where(
                InventoryBalance.company_id == pg.a.company_id,
                InventoryBalance.location_id == source_location_id,
            )
        )
        draft = await transfer_policy.save_transfer_destination_policy(
            TransferDestinationPolicySaveRequest(
                request_id=uuid4(),
                payload=dict(
                    quarantine_location_id=None,
                    disposal_location_id=None,
                    vendor_return_staging_location_id=None,
                ),
            ),
            db,
            actor.access(db),
            actor.operational_driver,
        )
        assert draft["policy"]["validated_payload"]["quarantine_location_id"] is None
        publish_request = TransferDestinationPolicyPublishRequest(
            request_id=uuid4(),
            expected_revision=draft["policy"]["revision"],
        )
        published = await transfer_policy.publish_transfer_destination_policy_endpoint(
            draft["policy"]["id"],
            publish_request,
            db,
            actor.access(db),
            actor.operational_driver,
        )
        assert published["policy"]["validated_payload"] == {
            "quarantine_location_id": None,
            "disposal_location_id": None,
            "vendor_return_staging_location_id": None,
            "allow_retiring_warehouse_balancing": False,
        }

    async with pg.session(pg.a) as db:
        result = await transfers.special_transfer_dispatch(
            command,
            db,
            actor.access(db),
            actor.operational_driver,
        )
        assert result["source_location_id"] == source_location_id
        assert result["destination_location_id"] == source_location_id
        assert await transfers.special_transfer_dispatch(
            command,
            db,
            actor.access(db),
            actor.operational_driver,
        ) == result

        header = await db.get(InventoryTransferHeader, result["header_id"])
        assert header.workflow_type == "DIRECT"
        assert header.status == "POSTED"
        assert header.source_location_id == source_location_id
        assert header.destination_location_id == source_location_id
        assert header.commercial_context["quality_stage_v1"] is True

        movement = await db.scalar(
            select(InventoryMovement).where(
                InventoryMovement.company_id == pg.a.company_id,
                InventoryMovement.transfer_header_id == result["header_id"],
            )
        )
        assert movement.movement_kind == "STATUS_CHANGE"
        assert movement.source_location_id == source_location_id
        assert movement.destination_location_id == source_location_id
        assert movement.source_stock_status == "AVAILABLE"
        assert movement.destination_stock_status == "DISPOSAL_PENDING"

        # The other V1 quality destinations use the same direct status-only
        # evidence path; this also proves the expanded PostgreSQL constraint.
        for purpose, target_status in (
            ("QUARANTINE", "QUARANTINED"),
            ("RETURN_TO_VENDOR", "QUARANTINED"),
        ):
            same_location = SpecialTransferDispatchRequest(
                request_id=uuid4(),
                source_location_id=source_location_id,
                transfer_purpose=purpose,
                notes=f"CP8 in-place {purpose.lower()}",
                items=[dict(
                    product_variant_id=pg.a.variant_id,
                    batch_id=pg.a.expired_batch_id,
                    source_status="AVAILABLE",
                    quantity="1",
                    uom_id=pg.a.uom_id,
                )],
            )
            staged = await transfers.special_transfer_dispatch(
                same_location,
                db,
                actor.access(db),
                actor.operational_driver,
            )
            assert staged["destination_location_id"] == source_location_id
            staged_header = await db.get(InventoryTransferHeader, staged["header_id"])
            assert staged_header.workflow_type == "DIRECT"
            assert staged_header.status == "POSTED"
            staged_movement = await db.scalar(
                select(InventoryMovement).where(
                    InventoryMovement.company_id == pg.a.company_id,
                    InventoryMovement.transfer_header_id == staged["header_id"],
                )
            )
            assert staged_movement.movement_kind == "STATUS_CHANGE"
            assert staged_movement.source_location_id == source_location_id
            assert staged_movement.destination_location_id == source_location_id
            assert staged_movement.source_stock_status == "AVAILABLE"
            assert staged_movement.destination_stock_status == target_status

        after_total = await db.scalar(
            select(func.sum(InventoryBalance.on_hand_quantity)).where(
                InventoryBalance.company_id == pg.a.company_id,
                InventoryBalance.location_id == source_location_id,
            )
        )
        assert after_total == before_total


async def test_query_counts_are_bounded_by_page_not_rows(pg):
    for _ in range(6): await send(pg)
    async with pg.session(pg.a) as db:
        product_id = (await db.get(ProductVariant, pg.a.variant_id)).product_id
        for index in range(8):
            variant = ProductVariant(company_id=pg.a.company_id, product_id=product_id, name=f"Scale {index}",
                sku=f"CP8-SCALE-{index}", base_uom_id=pg.a.uom_id, quantity_scale=0, quantity_step=Decimal("1"),
                lot_control_mode="REQUIRED", expiry_control_mode="OPTIONAL", lifecycle_status="ACTIVE", published_at=utc_now())
            db.add(variant)
            await db.flush()
            batch = ProductBatch(company_id=pg.a.company_id, product_variant_id=variant.id, batch_number="OVERLAP")
            db.add(batch)
            db.add(ProductLocation(company_id=pg.a.company_id, location_id=pg.a.locations[0], product_variant_id=variant.id, created_by=pg.a.owner.driver_id))
            await db.flush()
            await apply_inventory_movement(db, company_id=pg.a.company_id, performed_by=pg.a.owner.driver_id,
                product_variant_id=variant.id, batch_id=batch.id, quantity=Decimal("10"), movement_kind="PHYSICAL",
                reference_type="INBOUND_SUPPLIER", reference_id="SCALE", idempotency_key=str(uuid4()),
                source_location_id=None, destination_location_id=pg.a.locations[0], source_stock_status=None, destination_stock_status="AVAILABLE")
        await db.commit()
    async with pg.session(pg.a) as db:
        first = await source_page(db, pg.a.ordinary.access(db), pg.a.locations[0], limit=1)
        assert first["total"] == 9 and first["has_more"] and first["next_cursor"]
        second = await source_page(db, pg.a.ordinary.access(db), pg.a.locations[0], limit=1, cursor=first["next_cursor"])
        assert second["total"] is None and second["items"][0]["id"] != first["items"][0]["id"]
        with pytest.raises(HTTPException) as changed_search:
            await source_page(db, pg.a.ordinary.access(db), pg.a.locations[0], limit=1, search="Scale", cursor=first["next_cursor"])
        assert changed_search.value.status_code == 400
        first_list = await list_page(db, pg.a.ordinary.access(db), pg.a.locations[0], limit=1)
        assert first_list["total"] == 6 and first_list["next_cursor"]
        with pytest.raises(HTTPException) as changed_location:
            await list_page(db, pg.a.owner.access(db), pg.a.locations[1], limit=1, cursor=first_list["next_cursor"])
        assert changed_location.value.status_code == 400
    counts = {}
    async with pg.session(pg.a) as db:
        for name, size in [("source-small", 1), ("source-larger", 100), ("list-small", 1), ("list-larger", 100)]:
            statements = []
            def record(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)
            event.listen(pg.runtime_engine.sync_engine, "before_cursor_execute", record)
            try:
                if name.startswith("source"):
                    result = await source_page(db, pg.a.ordinary.access(db), pg.a.locations[0], limit=size)
                else:
                    result = await list_page(db, pg.a.ordinary.access(db), pg.a.locations[0], limit=size)
                assert result["items"]
            finally: event.remove(pg.runtime_engine.sync_engine, "before_cursor_execute", record)
            counts[name] = len(statements)
    print("CP8_QUERY_COUNTS=" + str(counts))
    assert counts["list-larger"] <= counts["list-small"] + 1
    assert counts["source-larger"] <= counts["source-small"] + 1


async def test_wrong_side_stale_state_and_forged_receipt_fail_closed(pg):
    sent = await send(pg)
    sender, receiver = pg.a.ordinary, pg.a.receiver
    # Each HTTP-equivalent request owns a fresh tenant-scoped transaction.
    async with pg.session(pg.a) as db:
        with pytest.raises(HTTPException) as wrong_cancel:
            await transfers.unified_transfer_cancel(sent["header_id"], UnifiedTransferDecisionRequest(request_id=uuid4(), decision_reason="wrong side"),
                db, receiver.access(db), receiver.operational_driver)
        assert wrong_cancel.value.status_code == 403
    async with pg.session(pg.a) as db:
        with pytest.raises(HTTPException) as wrong_receive:
            await transfers.unified_transfer_receive(UnifiedReceiveRequest(request_id=uuid4(), transfer_header_id=sent["header_id"],
                destination_location_id=pg.a.locations[1]), db, sender.access(db), sender.operational_driver)
        assert wrong_receive.value.status_code == 403
    async with pg.session(pg.a) as db:
        with pytest.raises(HTTPException) as forged:
            await transfers.unified_transfer_receive(UnifiedReceiveRequest(request_id=uuid4(), transfer_header_id=sent["header_id"],
                destination_location_id=pg.a.locations[0]), db, receiver.access(db), receiver.operational_driver)
        assert forged.value.status_code == 409
    async with pg.session(pg.a) as db:
        await transfers.unified_transfer_cancel(sent["header_id"], UnifiedTransferDecisionRequest(request_id=uuid4(), decision_reason="cancel"),
                db, sender.access(db), sender.operational_driver)
    async with pg.session(pg.a) as db:
        with pytest.raises(HTTPException) as stale:
            await transfers.unified_transfer_reject(sent["header_id"], UnifiedTransferDecisionRequest(request_id=uuid4(), decision_reason="stale"),
                db, receiver.access(db), receiver.operational_driver)
        assert stale.value.status_code == 409


async def test_vehicle_special_transfer_and_generic_direction_contract(pg):
    actor = pg.a.owner
    async with pg.session(pg.a) as db:
        draft = await transfer_policy.save_transfer_destination_policy(TransferDestinationPolicySaveRequest(request_id=uuid4(), payload=dict(
            quarantine_location_id=pg.a.quarantine_id, disposal_location_id=pg.a.quarantine_id,
            vendor_return_staging_location_id=pg.a.quarantine_id)), db, actor.access(db), actor.operational_driver)
        await transfer_policy.publish_transfer_destination_policy_endpoint(draft["policy"]["id"], TransferDestinationPolicyPublishRequest(
            request_id=uuid4(), expected_revision=draft["policy"]["revision"]), db, actor.access(db), actor.operational_driver)
        # Ordinary generic purposes have never authorized WAREHOUSE/VEHICLE direction.
        with pytest.raises(HTTPException) as direction:
            await transfers.unified_transfer_dispatch(dispatch_payload(pg.a, destination_location_id=pg.a.vehicle_location_id),
                db, actor.access(db), actor.operational_driver)
        assert direction.value.status_code == 403  # Existing structural Warehouse-only rejection precedes dispatch.
        # The existing dedicated vehicle -> warehouse quality path remains supported.
        command = SpecialTransferDispatchRequest(request_id=uuid4(), source_location_id=pg.a.vehicle_location_id,
            transfer_purpose="QUARANTINE", notes="CP8 vehicle collection", items=[dict(product_variant_id=pg.a.variant_id,
                batch_id=pg.a.expired_batch_id, source_status="AVAILABLE", quantity="2", uom_id=pg.a.uom_id)])
        sent = await transfers.special_transfer_dispatch(command, db, actor.access(db), actor.operational_driver)
        assert sent["destination_location_id"] == pg.a.quarantine_id
        assert await transfers.special_transfer_dispatch(command, db, actor.access(db), actor.operational_driver) == sent
        result = await transfers.unified_transfer_cancel(sent["header_id"], UnifiedTransferDecisionRequest(
            request_id=uuid4(), decision_reason="return vehicle custody"), db, actor.access(db), actor.operational_driver)
        assert result["status"] == "CANCELLED"


async def test_opposite_dispatches_preserve_sorted_lock_order(pg):
    outbound = dispatch_payload(pg.a, items=[dict(product_variant_id=pg.a.variant_id, quantity="3", uom_id=pg.a.uom_id)])
    inbound = dispatch_payload(pg.a, source_location_id=pg.a.locations[1], destination_location_id=pg.a.locations[0],
        items=[dict(product_variant_id=pg.a.variant_id, quantity="3", uom_id=pg.a.uom_id)])
    one, two = await asyncio.wait_for(asyncio.gather(send(pg, outbound, pg.a.owner), send(pg, inbound, pg.a.owner)), timeout=20)
    assert one["header_id"] != two["header_id"]
    async with pg.session(pg.a) as db:
        total = await db.scalar(select(func.sum(InventoryBalance.on_hand_quantity)).where(InventoryBalance.company_id == pg.a.company_id))
        assert total == 180


async def test_competing_receive_and_cancel_have_one_terminal_effect(pg):
    sent = await send(pg)
    async def receive():
        async with pg.session(pg.a) as db:
            return await transfers.unified_transfer_receive(UnifiedReceiveRequest(request_id=uuid4(), transfer_header_id=sent["header_id"],
                destination_location_id=pg.a.locations[1]), db, pg.a.receiver.access(db), pg.a.receiver.operational_driver)
    async def cancel():
        async with pg.session(pg.a) as db:
            return await transfers.unified_transfer_cancel(sent["header_id"], UnifiedTransferDecisionRequest(request_id=uuid4(), decision_reason="race"),
                db, pg.a.ordinary.access(db), pg.a.ordinary.operational_driver)
    results = await asyncio.wait_for(asyncio.gather(receive(), cancel(), return_exceptions=True), timeout=20)
    assert sum(isinstance(result, dict) for result in results) == 1
    failure = next(result for result in results if not isinstance(result, dict))
    assert isinstance(failure, HTTPException) and failure.status_code == 409
    async with pg.session(pg.a) as db:
        assert await db.scalar(select(func.count()).select_from(InventoryMovement).where(
            InventoryMovement.company_id == pg.a.company_id, InventoryMovement.transfer_header_id == sent["header_id"])) == 2


async def test_generic_fefo_rejects_stocked_vehicle_even_with_both_capabilities(pg):
    async with AsyncSession(pg.admin_engine) as seed:
        await _grant_location(seed, pg.a, pg.a.vehicle_location_id, "transfer.send", "inventory.fefo_override")
        await seed.commit()
    async with pg.session(pg.a) as db:
        access = pg.a.ordinary.access(db)
        await access.require("transfer.send", pg.a.vehicle_location_id)
        await access.require("inventory.fefo_override", pg.a.vehicle_location_id)
        assert await db.scalar(select(func.sum(InventoryBalance.on_hand_quantity)).where(
            InventoryBalance.company_id == pg.a.company_id, InventoryBalance.location_id == pg.a.vehicle_location_id)) > 0
        with pytest.raises(HTTPException) as denied:
            await transfers.get_unified_transfer_override_options(pg.a.vehicle_location_id, pg.a.variant_id, db, access)
        assert denied.value.status_code == 404


@pytest.mark.parametrize("purpose", ["REPLENISHMENT", "WAREHOUSE_BALANCING"])
@pytest.mark.parametrize("bad_side", ["source", "destination"])
@pytest.mark.parametrize("action", ["receive", "reject", "cancel"])
async def test_historical_generic_vehicle_endpoint_cannot_finish_transit(pg, purpose, bad_side, action):
    sent = await send(pg, dispatch_payload(pg.a, transfer_purpose=purpose))
    # Synthetic historical corruption only, in the disposable fixture DB.
    async with AsyncSession(pg.admin_engine) as seed:
        await seed.execute(update(InventoryTransferHeader).where(InventoryTransferHeader.company_id == pg.a.company_id,
            InventoryTransferHeader.id == sent["header_id"]).values(**{bad_side + "_location_id": pg.a.vehicle_location_id}))
        await seed.commit()
    async def evidence(db):
        balances = (await db.execute(select(InventoryBalance.location_id, InventoryBalance.batch_id, InventoryBalance.stock_status,
            InventoryBalance.on_hand_quantity, InventoryBalance.reserved_quantity).where(InventoryBalance.company_id == pg.a.company_id)
            .order_by(InventoryBalance.id))).all()
        movements = await db.scalar(select(func.count()).select_from(InventoryMovement).where(InventoryMovement.company_id == pg.a.company_id))
        return balances, movements
    async with pg.session(pg.a) as db:
        before = await evidence(db)
    request_id = uuid4()
    actor = pg.a.owner  # Not the dispatcher; full capability cannot bypass structure.
    async with pg.session(pg.a) as db:
        with patch.object(transfers, "_move_transfer_lines_from_transit", wraps=transfers._move_transfer_lines_from_transit) as terminal:
            with pytest.raises(HTTPException) as denied:
                if action == "receive":
                    await transfers.unified_transfer_receive(UnifiedReceiveRequest(request_id=request_id, transfer_header_id=sent["header_id"],
                        destination_location_id=pg.a.vehicle_location_id if bad_side == "destination" else pg.a.locations[1]), db, actor.access(db), actor.operational_driver)
                else:
                    endpoint = transfers.unified_transfer_reject if action == "reject" else transfers.unified_transfer_cancel
                    await endpoint(sent["header_id"], UnifiedTransferDecisionRequest(request_id=request_id, decision_reason="invalid historical direction"),
                        db, actor.access(db), actor.operational_driver)
            assert denied.value.status_code == 403
            terminal.assert_awaited_once()
    async with pg.session(pg.a) as db:
        assert await evidence(db) == before
        header = await db.get(InventoryTransferHeader, sent["header_id"])
        assert header.status == "IN_TRANSIT" and header.accepted_at is None and header.cancelled_at is None and header.rejected_at is None
        assert await db.scalar(text("SELECT count(*) FROM operation_idempotency WHERE company_id=:company AND request_id=:request"),
            {"company": pg.a.company_id, "request": str(request_id)}) == 0


@pytest.mark.parametrize("action", ["list", "receive", "reject", "cancel"])
async def test_cross_company_generic_list_and_terminal_are_opaque_and_side_effect_free(pg, action):
    sent = await send(pg)
    actor = pg.b.owner
    request_id = uuid4()
    async with pg.session(pg.b) as db:
        before_b = await db.scalar(select(func.count()).select_from(InventoryMovement).where(InventoryMovement.company_id == pg.b.company_id))
        balances_b = (await db.execute(select(InventoryBalance.location_id, InventoryBalance.on_hand_quantity,
            InventoryBalance.reserved_quantity).where(InventoryBalance.company_id == pg.b.company_id).order_by(InventoryBalance.id))).all()
    async with pg.session(pg.b) as db:
        if action == "list":
            rows = await list_page(db, actor.access(db), pg.b.locations[0])
            assert sent["header_id"] not in {row["id"] for row in rows["items"]}
            try:
                rows = await list_page(db, actor.access(db), pg.a.locations[0])
                assert rows["items"] == []
            except HTTPException as denied:
                assert denied.status_code in {403, 404}
        else:
            with pytest.raises(HTTPException) as denied:
                if action == "receive":
                    await transfers.unified_transfer_receive(UnifiedReceiveRequest(request_id=request_id, transfer_header_id=sent["header_id"],
                        destination_location_id=pg.a.locations[1]), db, actor.access(db), actor.operational_driver)
                else:
                    endpoint = transfers.unified_transfer_reject if action == "reject" else transfers.unified_transfer_cancel
                    await endpoint(sent["header_id"], UnifiedTransferDecisionRequest(request_id=request_id, decision_reason="foreign attempt"),
                        db, actor.access(db), actor.operational_driver)
            assert denied.value.status_code in {403, 404}
    async with pg.session(pg.a) as db:
        header = await db.get(InventoryTransferHeader, sent["header_id"])
        assert header.status == "IN_TRANSIT" and header.received_by is None and header.cancelled_by is None
        assert await db.scalar(select(func.count()).select_from(InventoryMovement).where(
            InventoryMovement.company_id == pg.a.company_id, InventoryMovement.transfer_header_id == sent["header_id"])) == 1
    async with pg.session(pg.b) as db:
        assert await db.scalar(select(func.count()).select_from(InventoryMovement).where(InventoryMovement.company_id == pg.b.company_id)) == before_b
        assert (await db.execute(select(InventoryBalance.location_id, InventoryBalance.on_hand_quantity,
            InventoryBalance.reserved_quantity).where(InventoryBalance.company_id == pg.b.company_id).order_by(InventoryBalance.id))).all() == balances_b
        assert await db.scalar(text("SELECT count(*) FROM operation_idempotency WHERE company_id=:company AND request_id=:request"),
            {"company": pg.b.company_id, "request": str(request_id)}) == 0
