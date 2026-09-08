from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import date, timedelta

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, func, select, text

# Run from repository root.
sys.path.insert(0, "wa_backend")

from context import tenant_context
from database import AsyncSessionLocal, engine
from models import (
    Company,
    Driver,
    InventoryBalance,
    InventoryLocation,
    InventoryMovement,
    InventoryMovementImpact,
    InventoryTransferHeader,
    InventoryTransferLine,
    OperationIdempotency,
    Product,
    ProductBatch,
    ProductVariant,
    UOM,
)
from schemas import UpgradedInboundRequest, UnifiedDispatchRequest
from api.warehouse import warehouse_inbound, unified_transfer_dispatch


async def set_tenant(db, company_id: int) -> None:
    tenant_context.set(company_id)
    await db.execute(
        text("SELECT set_config('app.current_tenant', :tenant, false)"),
        {"tenant": str(company_id)},
    )


async def ensure_schema_ready() -> None:
    async with AsyncSessionLocal() as db:
        table_exists = (
            await db.execute(
                text("SELECT to_regclass('operation_idempotency') IS NOT NULL")
            )
        ).scalar_one()
        if not table_exists:
            raise SystemExit(
                "SCHEMA_NOT_READY: operation_idempotency غير موجود. "
                "أعد بناء قاعدة التطوير من models.py أولاً."
            )

        rls = (
            await db.execute(
                text(
                    """
                    SELECT c.relrowsecurity, c.relforcerowsecurity,
                           EXISTS (
                               SELECT 1
                               FROM pg_policies p
                               WHERE p.schemaname = current_schema()
                                 AND p.tablename = 'operation_idempotency'
                                 AND p.policyname = 'tenant_isolation_policy'
                           ) AS has_policy
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = current_schema()
                      AND c.relname = 'operation_idempotency'
                    """
                )
            )
        ).one_or_none()

        if rls is None or not all(bool(x) for x in rls):
            raise AssertionError(
                f"operation_idempotency RLS incomplete: {rls}"
            )


async def setup_fixture():
    suffix = uuid.uuid4().hex[:10]

    async with AsyncSessionLocal() as db:
        company = Company(
            name=f"Warehouse Idempotency Test {suffix}",
            company_code=f"WID{suffix}",
            is_active=True,
            subscription_status="active",
            currency_code="JOD",
            timezone="Asia/Amman",
        )
        uom = UOM(
            name=f"Idempotency Unit {suffix}",
            code=f"I{suffix[:8]}",
        )
        db.add_all([company, uom])
        await db.flush()

        await set_tenant(db, company.id)

        admin = Driver(
            company_id=company.id,
            username=f"idemp_admin_{suffix}",
            password_hash="test-only",
            full_name="Idempotency Test Admin",
            is_active=True,
            is_admin=True,
        )
        product = Product(
            company_id=company.id,
            base_name=f"Idempotency Product {suffix}",
        )
        source = InventoryLocation(
            company_id=company.id,
            name="Idempotency Source",
            code=f"ISRC-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        destination = InventoryLocation(
            company_id=company.id,
            name="Idempotency Destination",
            code=f"IDST-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        db.add_all([admin, product, source, destination])
        await db.flush()

        inbound_variant = ProductVariant(
            company_id=company.id,
            product_id=product.id,
            base_uom_id=uom.id,
            variant_name=f"Inbound Variant {suffix}",
            sku=f"IN-{suffix}",
            price_per_carton=1,
            price_per_pack=1,
            packs_per_carton=10,
            is_active=True,
            default_max_samples_per_day=0,
        )
        transfer_variant = ProductVariant(
            company_id=company.id,
            product_id=product.id,
            base_uom_id=uom.id,
            variant_name=f"Transfer Variant {suffix}",
            sku=f"TR-{suffix}",
            price_per_carton=1,
            price_per_pack=1,
            packs_per_carton=10,
            is_active=True,
            default_max_samples_per_day=0,
        )
        db.add_all([inbound_variant, transfer_variant])
        await db.flush()

        today = date.today()
        transfer_batch = ProductBatch(
            company_id=company.id,
            product_variant_id=transfer_variant.id,
            batch_number=f"TRB-{suffix}",
            production_date=today - timedelta(days=30),
            expiry_date=today + timedelta(days=365),
            is_active=True,
        )
        db.add(transfer_batch)
        await db.flush()

        db.add(
            InventoryBalance(
                company_id=company.id,
                location_id=source.id,
                product_variant_id=transfer_variant.id,
                batch_id=transfer_batch.id,
                stock_status="AVAILABLE",
                on_hand_quantity=100,
                reserved_quantity=0,
            )
        )
        await db.commit()

        return {
            "company_id": company.id,
            "uom_id": uom.id,
            "admin_id": admin.id,
            "source_id": source.id,
            "destination_id": destination.id,
            "inbound_variant_id": inbound_variant.id,
            "transfer_variant_id": transfer_variant.id,
            "transfer_batch_id": transfer_batch.id,
            "suffix": suffix,
        }


async def cleanup_fixture(fx) -> None:
    company_id = fx["company_id"]

    async with AsyncSessionLocal() as db:
        await set_tenant(db, company_id)

        # Reverse dependency order. Test tenant is isolated and disposable.
        for table in (
            "inventory_movement_impacts",
            "inventory_movements",
            "inventory_transfer_lines",
            "inventory_transfer_headers",
            "operation_idempotency",
            "inventory_balances",
            "product_batches",
            "inventory_locations",
            "product_variants",
            "products",
            "drivers",
        ):
            await db.execute(
                text(f"DELETE FROM {table} WHERE company_id = :company_id"),
                {"company_id": company_id},
            )

        await db.execute(
            text("DELETE FROM companies WHERE id = :company_id"),
            {"company_id": company_id},
        )
        await db.execute(
            text("DELETE FROM uom WHERE id = :uom_id"),
            {"uom_id": fx["uom_id"]},
        )
        await db.commit()


async def load_admin(db, fx):
    await set_tenant(db, fx["company_id"])
    return (
        await db.execute(
            select(Driver).where(
                Driver.company_id == fx["company_id"],
                Driver.id == fx["admin_id"],
            )
        )
    ).scalar_one()


async def call_inbound(fx, payload: UpgradedInboundRequest):
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, fx)
        return await warehouse_inbound(
            payload=payload,
            db=db,
            current_admin=admin,
        )


async def call_dispatch(fx, payload: UnifiedDispatchRequest):
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, fx)
        return await unified_transfer_dispatch(
            payload=payload,
            db=db,
            current_admin=admin,
        )


async def assert_http_409(awaitable) -> None:
    try:
        await awaitable
    except HTTPException as exc:
        assert exc.status_code == 409, (exc.status_code, exc.detail)
        return
    raise AssertionError("expected HTTP 409, request unexpectedly succeeded")


async def test_schema_requires_request_id(fx) -> None:
    common_inbound = {
        "location_id": fx["source_id"],
        "items": [{
            "product_variant_id": fx["inbound_variant_id"],
            "quantity_packs": 1,
            "batch_number": f"REQ-SCHEMA-{fx['suffix']}",
            "production_date": str(date.today() - timedelta(days=1)),
            "expiry_date": str(date.today() + timedelta(days=30)),
        }],
    }
    try:
        UpgradedInboundRequest(**common_inbound)
    except ValidationError:
        pass
    else:
        raise AssertionError("UpgradedInboundRequest accepts missing request_id")

    common_dispatch = {
        "source_location_id": fx["source_id"],
        "destination_location_id": fx["destination_id"],
        "items": [{
            "product_variant_id": fx["transfer_variant_id"],
            "quantity": 1,
        }],
    }
    try:
        UnifiedDispatchRequest(**common_dispatch)
    except ValidationError:
        pass
    else:
        raise AssertionError("UnifiedDispatchRequest accepts missing request_id")


async def test_inbound_replay_and_conflict(fx) -> None:
    request_id = uuid.uuid4()
    today = date.today()

    payload = UpgradedInboundRequest(
        request_id=request_id,
        location_id=fx["source_id"],
        reference_id=None,
        notes="idempotency sequential inbound",
        items=[{
            "product_variant_id": fx["inbound_variant_id"],
            "quantity_packs": 25,
            "batch_number": f"IN-SEQ-{fx['suffix']}",
            "production_date": today - timedelta(days=2),
            "expiry_date": today + timedelta(days=90),
        }],
    )

    first = await call_inbound(fx, payload)
    replay = await call_inbound(fx, payload)
    assert first == replay, (first, replay)

    changed = payload.model_copy(deep=True)
    changed.items[0].quantity_packs = 26
    await assert_http_409(call_inbound(fx, changed))

    expected_ref = f"AUTO-INB-{request_id.hex.upper()}"

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_id"])

        movements = (
            await db.execute(
                select(func.count(InventoryMovement.id)).where(
                    InventoryMovement.company_id == fx["company_id"],
                    InventoryMovement.reference_type == "INBOUND_SUPPLIER",
                    InventoryMovement.reference_id == expected_ref,
                )
            )
        ).scalar_one()
        assert movements == 1, movements

        qty = (
            await db.execute(
                select(func.sum(InventoryBalance.on_hand_quantity))
                .join(
                    ProductBatch,
                    (ProductBatch.company_id == InventoryBalance.company_id)
                    & (ProductBatch.product_variant_id == InventoryBalance.product_variant_id)
                    & (ProductBatch.id == InventoryBalance.batch_id),
                )
                .where(
                    InventoryBalance.company_id == fx["company_id"],
                    InventoryBalance.location_id == fx["source_id"],
                    InventoryBalance.product_variant_id == fx["inbound_variant_id"],
                    InventoryBalance.stock_status == "AVAILABLE",
                    ProductBatch.batch_number == f"IN-SEQ-{fx['suffix']}",
                )
            )
        ).scalar_one()
        assert int(qty or 0) == 25, qty

        records = (
            await db.execute(
                select(func.count(OperationIdempotency.id)).where(
                    OperationIdempotency.company_id == fx["company_id"],
                    OperationIdempotency.operation == "WAREHOUSE_INBOUND",
                    OperationIdempotency.request_id == str(request_id),
                )
            )
        ).scalar_one()
        assert records == 1, records


async def test_inbound_concurrent_retry(fx) -> None:
    request_id = uuid.uuid4()
    today = date.today()
    payload = UpgradedInboundRequest(
        request_id=request_id,
        location_id=fx["source_id"],
        notes="idempotency concurrent inbound",
        items=[{
            "product_variant_id": fx["inbound_variant_id"],
            "quantity_packs": 11,
            "batch_number": f"IN-CONC-{fx['suffix']}",
            "production_date": today - timedelta(days=3),
            "expiry_date": today + timedelta(days=120),
        }],
    )

    r1, r2 = await asyncio.gather(
        call_inbound(fx, payload),
        call_inbound(fx, payload),
    )
    assert r1 == r2, (r1, r2)

    expected_ref = f"AUTO-INB-{request_id.hex.upper()}"

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_id"])

        movements = (
            await db.execute(
                select(func.count(InventoryMovement.id)).where(
                    InventoryMovement.company_id == fx["company_id"],
                    InventoryMovement.reference_type == "INBOUND_SUPPLIER",
                    InventoryMovement.reference_id == expected_ref,
                )
            )
        ).scalar_one()
        assert movements == 1, movements

        qty = (
            await db.execute(
                select(func.sum(InventoryBalance.on_hand_quantity))
                .join(
                    ProductBatch,
                    (ProductBatch.company_id == InventoryBalance.company_id)
                    & (ProductBatch.product_variant_id == InventoryBalance.product_variant_id)
                    & (ProductBatch.id == InventoryBalance.batch_id),
                )
                .where(
                    InventoryBalance.company_id == fx["company_id"],
                    InventoryBalance.location_id == fx["source_id"],
                    InventoryBalance.product_variant_id == fx["inbound_variant_id"],
                    InventoryBalance.stock_status == "AVAILABLE",
                    ProductBatch.batch_number == f"IN-CONC-{fx['suffix']}",
                )
            )
        ).scalar_one()
        assert int(qty or 0) == 11, qty


async def test_dispatch_replay_and_conflict(fx) -> None:
    request_id = uuid.uuid4()

    payload = UnifiedDispatchRequest(
        request_id=request_id,
        source_location_id=fx["source_id"],
        destination_location_id=fx["destination_id"],
        notes="idempotency sequential transfer",
        items=[{
            "product_variant_id": fx["transfer_variant_id"],
            "quantity": 30,
        }],
    )

    first = await call_dispatch(fx, payload)
    replay = await call_dispatch(fx, payload)

    assert first == replay, (first, replay)
    assert first["header_id"] == replay["header_id"]
    assert first["transfer_reference"] == replay["transfer_reference"]

    changed = payload.model_copy(deep=True)
    changed.items[0].quantity = 31
    await assert_http_409(call_dispatch(fx, changed))

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_id"])

        headers = (
            await db.execute(
                select(func.count(InventoryTransferHeader.id)).where(
                    InventoryTransferHeader.company_id == fx["company_id"],
                    InventoryTransferHeader.id == first["header_id"],
                )
            )
        ).scalar_one()
        assert headers == 1, headers

        dispatch_movements = (
            await db.execute(
                select(func.count(InventoryMovement.id)).where(
                    InventoryMovement.company_id == fx["company_id"],
                    InventoryMovement.transfer_header_id == first["header_id"],
                    InventoryMovement.reference_type == "TRANSFER_DISPATCH",
                )
            )
        ).scalar_one()
        assert dispatch_movements == 1, dispatch_movements

        source_qty = (
            await db.execute(
                select(InventoryBalance.on_hand_quantity).where(
                    InventoryBalance.company_id == fx["company_id"],
                    InventoryBalance.location_id == fx["source_id"],
                    InventoryBalance.product_variant_id == fx["transfer_variant_id"],
                    InventoryBalance.batch_id == fx["transfer_batch_id"],
                    InventoryBalance.stock_status == "AVAILABLE",
                )
            )
        ).scalar_one()
        assert int(source_qty) == 70, source_qty


async def test_dispatch_concurrent_retry(fx) -> None:
    request_id = uuid.uuid4()

    payload = UnifiedDispatchRequest(
        request_id=request_id,
        source_location_id=fx["source_id"],
        destination_location_id=fx["destination_id"],
        notes="idempotency concurrent transfer",
        items=[{
            "product_variant_id": fx["transfer_variant_id"],
            "quantity": 10,
        }],
    )

    r1, r2 = await asyncio.gather(
        call_dispatch(fx, payload),
        call_dispatch(fx, payload),
    )
    assert r1 == r2, (r1, r2)
    assert r1["header_id"] == r2["header_id"]

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_id"])

        transfer_headers = (
            await db.execute(
                select(func.count(InventoryTransferHeader.id)).where(
                    InventoryTransferHeader.company_id == fx["company_id"],
                    InventoryTransferHeader.id == r1["header_id"],
                )
            )
        ).scalar_one()
        assert transfer_headers == 1, transfer_headers

        movements = (
            await db.execute(
                select(func.count(InventoryMovement.id)).where(
                    InventoryMovement.company_id == fx["company_id"],
                    InventoryMovement.transfer_header_id == r1["header_id"],
                    InventoryMovement.reference_type == "TRANSFER_DISPATCH",
                )
            )
        ).scalar_one()
        assert movements == 1, movements

        source_qty = (
            await db.execute(
                select(InventoryBalance.on_hand_quantity).where(
                    InventoryBalance.company_id == fx["company_id"],
                    InventoryBalance.location_id == fx["source_id"],
                    InventoryBalance.product_variant_id == fx["transfer_variant_id"],
                    InventoryBalance.batch_id == fx["transfer_batch_id"],
                    InventoryBalance.stock_status == "AVAILABLE",
                )
            )
        ).scalar_one()
        assert int(source_qty) == 60, source_qty

        transit_qty = (
            await db.execute(
                select(func.sum(InventoryBalance.on_hand_quantity))
                .join(
                    InventoryLocation,
                    (InventoryLocation.company_id == InventoryBalance.company_id)
                    & (InventoryLocation.id == InventoryBalance.location_id),
                )
                .where(
                    InventoryBalance.company_id == fx["company_id"],
                    InventoryBalance.product_variant_id == fx["transfer_variant_id"],
                    InventoryBalance.batch_id == fx["transfer_batch_id"],
                    InventoryBalance.stock_status == "AVAILABLE",
                    InventoryLocation.location_type == "IN_TRANSIT",
                )
            )
        ).scalar_one()
        assert int(transit_qty or 0) == 40, transit_qty

        all_headers = (
            await db.execute(
                select(func.count(InventoryTransferHeader.id)).where(
                    InventoryTransferHeader.company_id == fx["company_id"],
                    InventoryTransferHeader.workflow_type == "TRANSIT",
                )
            )
        ).scalar_one()
        assert all_headers == 2, all_headers

        op_records = (
            await db.execute(
                select(func.count(OperationIdempotency.id)).where(
                    OperationIdempotency.company_id == fx["company_id"],
                )
            )
        ).scalar_one()
        assert op_records == 4, op_records


async def main() -> None:
    if engine.dialect.name != "postgresql":
        raise SystemExit("POSTGRESQL_REQUIRED_FOR_IDEMPOTENCY_TEST")

    await ensure_schema_ready()
    fx = await setup_fixture()

    try:
        await test_schema_requires_request_id(fx)
        await test_inbound_replay_and_conflict(fx)
        await test_inbound_concurrent_retry(fx)
        await test_dispatch_replay_and_conflict(fx)
        await test_dispatch_concurrent_retry(fx)

        print("WAREHOUSE_REQUEST_IDEMPOTENCY_POSTGRES_OK")
        print("REQUEST_ID_REQUIRED=OK")
        print("INBOUND_SEQUENTIAL_REPLAY=OK")
        print("INBOUND_PAYLOAD_CONFLICT=BLOCKED")
        print("INBOUND_CONCURRENT_RETRY=ONE_EXECUTION")
        print("TRANSFER_SEQUENTIAL_REPLAY=OK")
        print("TRANSFER_PAYLOAD_CONFLICT=BLOCKED")
        print("TRANSFER_CONCURRENT_RETRY=ONE_EXECUTION")
        print("OPERATION_IDEMPOTENCY_RLS=ENABLED_FORCE_POLICY_OK")

    finally:
        await cleanup_fixture(fx)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
