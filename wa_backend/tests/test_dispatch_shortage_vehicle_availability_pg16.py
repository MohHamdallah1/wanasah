"""#1059 — genuine signed Backoffice/FIELD HTTP acceptance on restricted PG16.

Opt-in test.  Uses ONLY migrated synthetic 127.0.0.1:55439/
wanasah_no_lot_contract_test, runtime wanasah_app (NOSUPERUSER/NOBYPASSRLS),
and a separate fixture migrator.  Never runs on production or shared dev DB.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import os
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import engine as http_engine
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from domains.inventory_vehicle_load.service import mutate_vehicle_load
from models import (
    InventoryBalance, InventoryLocation, InventoryMovement, Permission,
    ProductBatch, ProductLocation, ProductVariant, Role, ShortageRequest,
    SystemAuditLog, UserLocationAccess, Vehicle, Visit, role_permissions, utc_now,
)
from product_lifecycle import DEFAULT_PRODUCT_LOCATION_FLAGS
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_dispatch_shop_finance_edit_v1_postgres import (
    _real_http, _token, _owner, _grant_company_dispatch_capability,
)
from tests.test_live_stock_v1_route_sale_unload_postgres import _seed_mobile_uom_and_field

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_SHORTAGE_1059_PG_GATE") != "1",
        reason="Only approved isolated #1059 PG16 signed HTTP acceptance",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]
URL = "/dispatch/shortages/vehicle-availability"


def _params(driver, ids):
    return [("driver_id", str(driver))] + [("product_ids", str(i)) for i in ids]


def _code(response):
    payload = response.json()
    detail = payload.get("error", payload.get("detail", {}))
    return detail.get("code") if isinstance(detail, dict) else None


async def _assert_restricted_pg():
    async with http_engine.connect() as db:
        role = (await db.execute(text(
            "SELECT current_database(),current_user,inet_server_port(),"
            "rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ))).one()
        assert tuple(role) == (
            "wanasah_no_lot_contract_test", "wanasah_app", 55439, False, False,
        )
        for name in (
            "identity_legacy_driver_map", "company_principals",
            "vehicle_custody_epochs", "inventory_balances",
            "inventory_movements", "product_batches", "product_variants",
            "user_location_access",
        ):
            flags = (await db.execute(text(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                "WHERE oid=to_regclass(:table_name)"
            ), {"table_name": name})).one()
            assert tuple(flags) == (True, True), name
    # pytest-asyncio function loops must not reuse pooled asyncpg connections.
    await http_engine.dispose()


async def _vehicle_fixture(gate, tenant):
    """Fixture construction only; every HTTP request is restricted/real."""
    async with AsyncSession(gate.admin_engine, expire_on_commit=False) as db:
        tag = uuid4().hex[:12]
        car = Vehicle(
            company_id=tenant.company_id, plate_number="1059-" + tag,
            is_active=True, maintenance_status="Active",
        )
        db.add(car)
        await db.flush()
        location = InventoryLocation(
            company_id=tenant.company_id, vehicle_id=car.id,
            name="Synthetic availability " + tag, code="1059-" + tag,
            location_type="VEHICLE", is_active=True, is_system_managed=False,
        )
        db.add(location)
        await db.flush()
        db.add(ProductLocation(
            company_id=tenant.company_id, location_id=location.id,
            product_variant_id=tenant.variant_id,
            operational_flags=dict(DEFAULT_PRODUCT_LOCATION_FLAGS),
            created_by=tenant.owner.driver_id,
        ))
        pair = (int(car.id), int(location.id))
        await db.commit()
        return pair


async def _epoch(gate, tenant, field, vehicle, location):
    async with gate.session() as db:
        record = VehicleCustodyEpoch(
            company_id=tenant.company_id,
            vehicle_id=vehicle, vehicle_location_id=location,
            custodian_kind="FIELD_REPRESENTATIVE",
            custodian_principal_id=field.context.principal_id,
            field_representative_id=field.context.representative_id,
            accepted_by_principal_id=tenant.owner.context.principal_id,
            state="ACCEPTED", context_revision=1, started_at=utc_now(),
            request_id=str(uuid4()), payload_hash="a" * 64,
        )
        db.add(record)
        await db.flush()
        identifier = int(record.id)
        await db.commit()
        return identifier


async def _grant_location(gate, tenant, actor, location_id):
    async with gate.session() as db:
        permission = await db.scalar(
            select(Permission).where(Permission.code == "dispatch.read")
        )
        assert permission is not None
        role = Role(
            company_id=tenant.company_id, name="1059 " + uuid4().hex
        )
        db.add(role)
        await db.flush()
        await db.execute(role_permissions.insert().values(
            company_id=tenant.company_id,
            role_id=role.id, permission_id=permission.id,
        ))
        grant = UserLocationAccess(
            company_id=tenant.company_id, driver_id=actor.driver_id,
            location_id=location_id, role_id=role.id,
        )
        db.add(grant)
        await db.flush()
        key = int(grant.id)
        await db.commit()
        return key


async def _state(gate, tenant):
    """Exact persisted stock rows + counts, including visits and audit."""
    async with gate.session() as db:
        rows = (await db.execute(select(
            InventoryBalance.id, InventoryBalance.location_id,
            InventoryBalance.product_variant_id, InventoryBalance.batch_id,
            InventoryBalance.stock_status, InventoryBalance.on_hand_quantity,
            InventoryBalance.reserved_quantity,
        ).where(InventoryBalance.company_id == tenant.company_id)
         .order_by(InventoryBalance.id))).all()
        counts = []
        for model in (InventoryMovement, ShortageRequest, Visit, SystemAuditLog):
            counts.append(int(await db.scalar(select(func.count())
                        .select_from(model)
                        .where(model.company_id == tenant.company_id)) or 0))
        return (
            tuple(tuple(str(x) for x in line) for line in rows),
            tuple(counts),
        )


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_signed_http_capabilities_rls_location_tenant_custody_and_no_mutation(pg):
    await _assert_restricted_pg()
    tenant, foreign = pg.tenants
    representative = await _seed_mobile_uom_and_field(pg, tenant)
    other_rep = await _seed_mobile_uom_and_field(pg, tenant)
    vehicle_id, location_id = await _vehicle_fixture(pg, tenant)
    alternate_vehicle, alternate_location = await _vehicle_fixture(pg, tenant)
    await _vehicle_fixture(pg, foreign)
    product = int(tenant.variant_id)
    # A real ordinary Backoffice login requires at least one persisted role.
    await _grant_company_dispatch_capability(pg, tenant, tenant.ordinary, "shortage.create")
    receipt = pg.request(
        lot="1059-" + uuid4().hex[:18], quantity="30", cost="1",
        expiry=date.today() + timedelta(days=60),
    )
    async with pg.session() as db:
        assert await pg.post(db, receipt) == {"message": "INBOUND_POSTED"}
        result = await mutate_vehicle_load(
            db, access=tenant.owner.access(db),
            actor_id=tenant.owner.driver_id,
            vehicle_id=vehicle_id, warehouse_id=tenant.location_id,
            direction="ADD", request_id=uuid4(),
            items=[{"product_variant_id": product, "quantity": Decimal("12")}],
        )
        assert result["movement_count"] > 0

    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        foreign_owner = await _owner(client, pg, foreign)
        employee = await _token(
            client, pg, tenant, tenant.ordinary, "SyntheticFixture123"
        )
        field = await _token(
            client, pg, tenant, representative, "SyntheticFixture123"
        )
        query = _params(representative.driver.id, [product])
        assert (await client.get(URL, params=query)).status_code == 401
        assert (await client.get(URL, headers=field, params=query)).status_code in (401, 403)
        no_custody = await client.get(URL, headers=owner, params=query)
        assert no_custody.status_code == 200, no_custody.text
        assert no_custody.json() == {
            "status": "UNKNOWN", "reason": "NO_ACCEPTED_VEHICLE_CUSTODY",
            "items": [],
        }
        # SECURITY REGRESSION: shortage.create alone must not disclose UNKNOWN.
        missing_read = await client.get(URL, headers=employee, params=query)
        assert missing_read.status_code == 403, missing_read.text
        assert _code(missing_read) == "SHORTAGE_AVAILABILITY_CAPABILITY_DENIED"

        wrong_warehouse = await _grant_location(pg, tenant, tenant.ordinary, tenant.location_id)
        accepted_id = await _epoch(
            pg, tenant, representative, vehicle_id, location_id
        )
        wrong = await client.get(URL, headers=employee, params=query)
        assert wrong.status_code == 403, wrong.text
        before = await _state(pg, tenant)
        trusted = await client.get(URL, headers=owner, params=query)
        assert trusted.status_code == 200, trusted.text
        assert trusted.json()["status"] == "VERIFIED"
        assert trusted.json()["vehicle_id"] == vehicle_id
        assert trusted.json()["vehicle_location_id"] == location_id
        assert trusted.json()["custody_epoch_id"] == accepted_id
        assert trusted.json()["items"] == [{
            "product_id": str(product), "available_base": "12",
            "base_uom": "EACH",
        }]
        assert await _state(pg, tenant) == before

        outsider = await client.get(URL, headers=foreign_owner, params=query)
        assert outsider.status_code == 404, outsider.text
        assert _code(outsider) == "SHORTAGE_AVAILABILITY_REP_NOT_FOUND"
        foreign_product = await client.get(
            URL, headers=owner, params=_params(representative.driver.id, [foreign.variant_id])
        )
        assert foreign_product.status_code == 404
        assert _code(foreign_product) == "SHORTAGE_AVAILABILITY_PRODUCT_NOT_FOUND"
        assert await _state(pg, tenant) == before

        # Persisted location grant is re-evaluated with SAME signed employee token.
        async with pg.session() as db:
            grant = await db.get(UserLocationAccess, wrong_warehouse)
            grant.location_id = location_id
            await db.commit()
        yes = await client.get(URL, headers=employee, params=query)
        assert yes.status_code == 200 and yes.json()["items"] == trusted.json()["items"], yes.text
        async with pg.session() as db:
            grant = await db.get(UserLocationAccess, wrong_warehouse)
            grant.location_id = alternate_location
            await db.commit()
        assert (await client.get(URL, headers=employee, params=query)).status_code == 403
        async with pg.session() as db:
            await db.execute(delete(UserLocationAccess).where(
                UserLocationAccess.company_id == tenant.company_id,
                UserLocationAccess.id == wrong_warehouse,
            ))
            await db.commit()
        assert (await client.get(URL, headers=employee, params=query)).status_code == 403

        extra_epoch = await _epoch(
            pg, tenant, representative, alternate_vehicle, alternate_location
        )
        ambiguous = await client.get(URL, headers=owner, params=query)
        assert ambiguous.status_code == 200
        assert ambiguous.json() == {
            "status": "UNKNOWN", "reason": "AMBIGUOUS_VEHICLE_CUSTODY", "items": [],
        }
        async with pg.session() as db:
            record = await db.get(VehicleCustodyEpoch, extra_epoch)
            record.ended_at = utc_now()
            await db.commit()

        async with pg.session() as db:
            balance = await db.scalar(select(InventoryBalance).where(
                InventoryBalance.company_id == tenant.company_id,
                InventoryBalance.location_id == location_id,
                InventoryBalance.product_variant_id == product,
                InventoryBalance.stock_status == "AVAILABLE",
            ))
            assert balance is not None
            balance.reserved_quantity = Decimal("3")
            batch_id = int(balance.batch_id)
            await db.commit()
        reserved = await client.get(URL, headers=owner, params=query)
        assert reserved.status_code == 200
        assert reserved.json()["items"][0]["available_base"] == "9"

        async with pg.session() as db:
            batch = await db.get(ProductBatch, batch_id)
            batch.disposition = "BLOCKED"
            await db.commit()
        blocked = await client.get(URL, headers=owner, params=query)
        assert blocked.status_code == 200
        assert blocked.json()["items"][0]["available_base"] == "0"
        async with pg.session() as db:
            batch = await db.get(ProductBatch, batch_id)
            batch.disposition = "RELEASED"
            batch.expiry_date = date.today() - timedelta(days=1)
            await db.commit()
        expired = await client.get(URL, headers=owner, params=query)
        assert expired.status_code == 200
        assert expired.json()["items"][0]["available_base"] == "0"

        async with pg.session() as db:
            epoch = await db.get(VehicleCustodyEpoch, accepted_id)
            epoch.ended_at = utc_now()
            await db.commit()
        no_longer = await client.get(URL, headers=owner, params=query)
        assert no_longer.status_code == 200
        assert no_longer.json()["status"] == "UNKNOWN"
        no_other = await client.get(
            URL, headers=owner, params=_params(other_rep.driver.id, [product])
        )
        assert no_other.status_code == 200
        assert no_other.json()["status"] == "UNKNOWN"
        duplicate = await client.get(
            URL, headers=owner, params=_params(representative.driver.id, [product, product])
        )
        assert duplicate.status_code == 422
        assert _code(duplicate) == "SHORTAGE_AVAILABILITY_PRODUCT_IDS_INVALID"
        assert (await client.get(
            URL, headers=owner, params=_params(0, [product])
        )).status_code == 422


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_80_vs_240_ids_real_http_source_sql_and_bounded_snapshot(pg):
    await _assert_restricted_pg()
    tenant = pg.tenants[0]
    rep = await _seed_mobile_uom_and_field(pg, tenant)
    vehicle, location = await _vehicle_fixture(pg, tenant)
    await _epoch(pg, tenant, rep, vehicle, location)
    ids = [int(tenant.variant_id)]
    async with pg.session() as db:
        parent = await db.get(ProductVariant, tenant.variant_id)
        for _ in range(239):
            tag = "1059-" + uuid4().hex[:15]
            child = ProductVariant(
                company_id=tenant.company_id, product_id=parent.product_id,
                name=tag, sku=tag, base_uom_id=tenant.uom_id,
                quantity_scale=6, quantity_step=Decimal("0.000001"),
                lot_control_mode="OPTIONAL", expiry_control_mode="OPTIONAL",
                lifecycle_status="ACTIVE", published_at=utc_now(),
            )
            db.add(child)
            await db.flush()
            ids.append(int(child.id))
        await db.commit()
    assert len(ids) == len(set(ids)) == 240
    before = await _state(pg, tenant)
    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        measurements = []
        for count in (80, 240):
            statements = []
            def count_selects(conn, cursor, statement, parameters, context, executemany):
                if statement.lstrip().upper().startswith("SELECT"):
                    statements.append(statement)
            event.listen(http_engine.sync_engine, "before_cursor_execute", count_selects)
            try:
                started = perf_counter()
                response = await client.get(
                    URL, headers=owner, params=_params(rep.driver.id, ids[:count])
                )
                milliseconds = round((perf_counter() - started) * 1000, 1)
            finally:
                event.remove(http_engine.sync_engine, "before_cursor_execute", count_selects)
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "VERIFIED"
            assert len(response.json()["items"]) == count
            stock = [s for s in statements if "FROM inventory_balances" in s]
            moves = [s for s in statements if "FROM inventory_movements" in s]
            assert len(stock) == 1 and len(moves) == 0, "Selected-SKU quote must not scan lifetime inventory movements"
            assert "LIMIT" in stock[0].upper(), stock[0]
            measurements.append((count, len(statements), milliseconds, len(stock), len(moves)))
            print("1059_HTTP_SQL ids=%d selects=%d milliseconds=%.1f stock_reads=%d movement_reads=%d" % measurements[-1])
        assert measurements[1][1] <= measurements[0][1] + 3
        assert await _state(pg, tenant) == before
        too_many = await client.get(
            URL, headers=owner, params=_params(rep.driver.id, ids + [ids[0]])
        )
        assert too_many.status_code == 422, too_many.text
    print("1059_LEAD_DECISION catalog=80 quote_MAX_PRODUCTS=240 "
          "selected_stock_limit=10000 movement_history_reads=0 quote_is_not_authority")
