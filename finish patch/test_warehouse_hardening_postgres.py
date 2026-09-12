from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import date, timedelta

from sqlalchemy import delete, event, select, text, update

# Run from repository root.
sys.path.insert(0, "wa_backend")

from context import tenant_context
from database import AsyncSessionLocal, engine
from models import (
    Company,
    Driver,
    InventoryBalance,
    InventoryLocation,
    InventoryLock,
    InventoryMovement,
    InventoryMovementImpact,
    Product,
    ProductBatch,
    ProductVariant,
    StocktakeCountAttempt,
    StocktakeSession,
    UOM,
    utc_now,
)
from services import (
    InventoryMutationError,
    allocate_fefo_inventory_batch,
    apply_inventory_movements_batch,
    get_company_local_date,
    post_approved_stocktake_adjustments,
)


TEST_VARIANTS = 120


async def set_tenant(db, company_id: int) -> None:
    tenant_context.set(company_id)
    await db.execute(
        text("SELECT set_config('app.current_tenant', :tenant, false)"),
        {"tenant": str(company_id)},
    )


async def setup_fixture():
    suffix = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        company = Company(
            name=f"Warehouse Hardening Test {suffix}",
            company_code=f"WHT{suffix}",
            is_active=True,
            subscription_status="active",
            currency_code="JOD",
            timezone="Asia/Amman",
        )
        uom = UOM(name=f"Hardening Unit {suffix}", code=f"H{suffix[:8]}")
        db.add_all([company, uom])
        await db.flush()

        await set_tenant(db, company.id)

        admin = Driver(
            company_id=company.id,
            username=f"hardening_{suffix}",
            password_hash="test-only",
            full_name="Hardening Test Admin",
            is_active=True,
            is_admin=True,
        )
        product = Product(
            company_id=company.id,
            base_name=f"Hardening Product {suffix}",
        )
        source = InventoryLocation(
            company_id=company.id,
            name="Hardening Source",
            code=f"HSRC-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        dest_a = InventoryLocation(
            company_id=company.id,
            name="Hardening Destination A",
            code=f"HDA-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        dest_b = InventoryLocation(
            company_id=company.id,
            name="Hardening Destination B",
            code=f"HDB-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        db.add_all([admin, product, source, dest_a, dest_b])
        await db.flush()

        variants = []
        for i in range(TEST_VARIANTS):
            variants.append(ProductVariant(
                company_id=company.id,
                product_id=product.id,
                base_uom_id=uom.id,
                variant_name=f"Hardening Variant {suffix}-{i}",
                price_per_carton=1,
                price_per_pack=1,
                packs_per_carton=10,
                is_active=True,
                default_max_samples_per_day=0,
            ))
        db.add_all(variants)
        await db.flush()

        expiry = date.today() + timedelta(days=365)
        batches = [
            ProductBatch(
                company_id=company.id,
                product_variant_id=variant.id,
                batch_number=f"HB-{suffix}-{i}",
                expiry_date=expiry,
                is_active=True,
            )
            for i, variant in enumerate(variants)
        ]
        db.add_all(batches)
        await db.flush()

        db.add_all([
            InventoryBalance(
                company_id=company.id,
                location_id=source.id,
                product_variant_id=variant.id,
                batch_id=batch.id,
                stock_status="AVAILABLE",
                on_hand_quantity=1000,
                reserved_quantity=0,
            )
            for variant, batch in zip(variants, batches)
        ])
        await db.commit()

        return {
            "company_id": company.id,
            "uom_id": uom.id,
            "admin_id": admin.id,
            "source_id": source.id,
            "dest_a_id": dest_a.id,
            "dest_b_id": dest_b.id,
            "pairs": [(v.id, b.id) for v, b in zip(variants, batches)],
            "suffix": suffix,
        }


async def cleanup_fixture(fx):
    company_id = fx["company_id"]
    async with AsyncSessionLocal() as db:
        await set_tenant(db, company_id)

        # Reverse dependency order. Test data is isolated by a unique company.
        for table in (
            "inventory_movement_impacts",
            "inventory_movements",
            "inventory_locks",
            "stocktake_count_attempt_lines",
            "stocktake_count_attempts",
            "stocktake_lines",
            "stocktake_sessions",
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


async def count_movement_queries(fx, count: int) -> int:
    counter = {"n": 0}

    def before_cursor_execute(*_args, **_kwargs):
        counter["n"] += 1

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_id"])
        specs = []
        for i, (variant_id, batch_id) in enumerate(fx["pairs"][:count]):
            specs.append({
                "product_variant_id": variant_id,
                "batch_id": batch_id,
                "quantity": 1,
                "movement_kind": "PHYSICAL",
                "reference_type": "HARDENING_QUERY_TEST",
                "reference_id": f"Q-{fx['suffix']}-{count}",
                "idempotency_key": f"HQ-{fx['suffix']}-{count}-{i}",
                "source_location_id": fx["source_id"],
                "destination_location_id": fx["dest_a_id"],
                "source_stock_status": "AVAILABLE",
                "destination_stock_status": "AVAILABLE",
            })

        event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
        try:
            await apply_inventory_movements_batch(
                db,
                company_id=fx["company_id"],
                performed_by=fx["admin_id"],
                movements=specs,
            )
            # Include pending movement-impact inserts in the measured SQL count.
            await db.flush()
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
            await db.rollback()

    return counter["n"]


async def count_fefo_queries(fx, count: int) -> int:
    counter = {"n": 0}

    def before_cursor_execute(*_args, **_kwargs):
        counter["n"] += 1

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_id"])
        business_date = await get_company_local_date(db, fx["company_id"])
        requests = {
            variant_id: 5
            for variant_id, _batch_id in fx["pairs"][:count]
        }

        event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
        try:
            allocations = await allocate_fefo_inventory_batch(
                db,
                company_id=fx["company_id"],
                location_id=fx["source_id"],
                requests=requests,
                as_of_date=business_date,
                require_full=True,
            )
            assert len(allocations) == count
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
            await db.rollback()

    return counter["n"]


async def test_empty_stocktake(fx):
    variant_id, _batch_id = fx["pairs"][0]
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_id"])
        now = utc_now()

        session = StocktakeSession(
            company_id=fx["company_id"],
            location_id=fx["dest_a_id"],
            reference_number=f"EMPTY-{fx['suffix']}",
            stocktake_type="CYCLE_COUNT",
            status="APPROVED",
            scope_product_variant_id=variant_id,
            scope_batch_id=None,
            snapshot_cutoff_at=now,
            started_by=fx["admin_id"],
            approved_by=fx["admin_id"],
            approved_at=now,
            created_at=now,
            updated_at=now,
            pending_independent_recount_required=False,
        )
        db.add(session)
        await db.flush()

        lock = InventoryLock(
            company_id=fx["company_id"],
            stocktake_session_id=session.id,
            location_id=fx["dest_a_id"],
            product_variant_id=variant_id,
            batch_id=None,
            created_by=fx["admin_id"],
        )
        attempt = StocktakeCountAttempt(
            company_id=fx["company_id"],
            stocktake_session_id=session.id,
            attempt_number=1,
            counted_by=fx["admin_id"],
            requires_independent_recount=False,
            submitted_at=now,
        )
        db.add_all([lock, attempt])
        await db.flush()

        movements = await post_approved_stocktake_adjustments(
            db,
            company_id=fx["company_id"],
            stocktake_session_id=session.id,
            stocktake_count_attempt_id=attempt.id,
            performed_by=fx["admin_id"],
        )
        await db.flush()
        await db.refresh(session)
        await db.refresh(lock)

        assert movements == [], "empty stocktake unexpectedly created movements"
        assert session.status == "POSTED", session.status
        assert session.posted_at is not None
        assert lock.released_at is not None
        assert lock.released_by == fx["admin_id"]
        assert lock.release_reason == "STOCKTAKE_POSTED"

        await db.rollback()


async def test_concurrency_oversell(fx):
    variant_id, batch_id = fx["pairs"][0]

    # Deterministic starting point.
    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_id"])
        await db.execute(
            update(InventoryBalance)
            .where(
                InventoryBalance.company_id == fx["company_id"],
                InventoryBalance.location_id == fx["source_id"],
                InventoryBalance.product_variant_id == variant_id,
                InventoryBalance.batch_id == batch_id,
                InventoryBalance.stock_status == "AVAILABLE",
            )
            .values(on_hand_quantity=100, reserved_quantity=0)
        )
        await db.execute(
            delete(InventoryBalance).where(
                InventoryBalance.company_id == fx["company_id"],
                InventoryBalance.location_id.in_([fx["dest_a_id"], fx["dest_b_id"]]),
                InventoryBalance.product_variant_id == variant_id,
                InventoryBalance.batch_id == batch_id,
                InventoryBalance.stock_status == "AVAILABLE",
            )
        )
        await db.commit()

    async def worker(dest_id: int, key_suffix: str):
        async with AsyncSessionLocal() as db:
            await set_tenant(db, fx["company_id"])
            try:
                await apply_inventory_movements_batch(
                    db,
                    company_id=fx["company_id"],
                    performed_by=fx["admin_id"],
                    movements=[{
                        "product_variant_id": variant_id,
                        "batch_id": batch_id,
                        "quantity": 80,
                        "movement_kind": "PHYSICAL",
                        "reference_type": "HARDENING_CONCURRENCY_TEST",
                        "reference_id": f"C-{fx['suffix']}",
                        "idempotency_key": f"HC-{fx['suffix']}-{key_suffix}",
                        "source_location_id": fx["source_id"],
                        "destination_location_id": dest_id,
                        "source_stock_status": "AVAILABLE",
                        "destination_stock_status": "AVAILABLE",
                    }],
                )
                await db.commit()
                return "committed"
            except InventoryMutationError:
                await db.rollback()
                return "rejected"

    results = await asyncio.gather(
        worker(fx["dest_a_id"], "A"),
        worker(fx["dest_b_id"], "B"),
    )
    assert results.count("committed") == 1, results
    assert results.count("rejected") == 1, results

    async with AsyncSessionLocal() as db:
        await set_tenant(db, fx["company_id"])
        source_qty = (
            await db.execute(
                select(InventoryBalance.on_hand_quantity).where(
                    InventoryBalance.company_id == fx["company_id"],
                    InventoryBalance.location_id == fx["source_id"],
                    InventoryBalance.product_variant_id == variant_id,
                    InventoryBalance.batch_id == batch_id,
                    InventoryBalance.stock_status == "AVAILABLE",
                )
            )
        ).scalar_one()
        dest_qtys = (
            await db.execute(
                select(InventoryBalance.on_hand_quantity).where(
                    InventoryBalance.company_id == fx["company_id"],
                    InventoryBalance.location_id.in_([fx["dest_a_id"], fx["dest_b_id"]]),
                    InventoryBalance.product_variant_id == variant_id,
                    InventoryBalance.batch_id == batch_id,
                    InventoryBalance.stock_status == "AVAILABLE",
                )
            )
        ).scalars().all()

    assert source_qty == 20, source_qty
    assert sum(dest_qtys) == 80, dest_qtys


async def check_physical_index() -> bool:
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    """
                    SELECT 1
                    FROM pg_indexes
                    WHERE schemaname = current_schema()
                      AND tablename = 'dispatch_routes'
                      AND indexname = 'ix_dispatch_route_company_vehicle_latest'
                    LIMIT 1
                    """
                )
            )
        ).scalar_one_or_none()
        return row is not None


async def main():
    if engine.dialect.name != "postgresql":
        raise SystemExit("POSTGRESQL_REQUIRED_FOR_WAREHOUSE_HARDENING_TEST")

    fx = await setup_fixture()
    try:
        small_move = await count_movement_queries(fx, 1)
        large_move = await count_movement_queries(fx, 100)
        if large_move > small_move + 12:
            raise AssertionError(
                f"movement query slope is not bounded: 1={small_move}, 100={large_move}"
            )

        small_fefo = await count_fefo_queries(fx, 1)
        large_fefo = await count_fefo_queries(fx, 100)
        if large_fefo > small_fefo + 4:
            raise AssertionError(
                f"FEFO query slope is not bounded: 1={small_fefo}, 100={large_fefo}"
            )

        await test_empty_stocktake(fx)
        await test_concurrency_oversell(fx)
        physical_index = await check_physical_index()

        print("WAREHOUSE_HARDENING_POSTGRES_OK")
        print(f"MOVEMENT_QUERY_COUNT_1={small_move}")
        print(f"MOVEMENT_QUERY_COUNT_100={large_move}")
        print(f"FEFO_QUERY_COUNT_1={small_fefo}")
        print(f"FEFO_QUERY_COUNT_100={large_fefo}")
        print("CONCURRENCY_OVERSELL=BLOCKED")
        print("EMPTY_STOCKTAKE=POSTED_OK")
        print(
            "DISPATCH_ROUTE_LATEST_INDEX="
            + ("PRESENT" if physical_index else "PENDING_DATABASE_MIGRATION")
        )

    finally:
        await cleanup_fixture(fx)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
