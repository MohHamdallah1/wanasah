from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import bcrypt
from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url


def locate_project() -> tuple[Path, Path]:
    cwd = Path.cwd().resolve()
    here = Path(__file__).resolve().parent
    for root in (cwd, here, cwd.parent, here.parent):
        backend = root / "wa_backend"
        if backend.is_dir() and (backend / "models.py").is_file():
            return root, backend
        if root.name == "wa_backend" and (root / "models.py").is_file():
            return root.parent, root
    raise SystemExit("ERROR: wa_backend/models.py not found")


ROOT, BACKEND = locate_project()
sys.path.insert(0, str(BACKEND))

from config import Config  # noqa: E402
from context import tenant_context  # noqa: E402
from database import AsyncSessionLocal, engine  # noqa: E402
from models import (  # noqa: E402
    Base,
    Company,
    Driver,
    InventoryBalance,
    InventoryLocation,
    ProductBatch,
    ProductVariant,
    UOM,
)
from schemas import (  # noqa: E402
    AddProductVariantRequest,
    InboundBatchItem,
    StocktakeCancelRequest,
    StocktakeCountItem,
    UnifiedStocktakeCountRequest,
    UnifiedStocktakeStartRequest,
    UpgradedInboundRequest,
)
from services import get_company_local_date  # noqa: E402
from api.warehouse import (  # noqa: E402
    add_product_variant,
    cancel_stocktake_session,
    get_warehouse_ledger_cursor,
    start_unified_stocktake,
    submit_stocktake_count,
    warehouse_inbound,
)


TEST_PASSWORD = "FreezeAudit#2026"


def safety_gate() -> None:
    url = make_url(Config.SQLALCHEMY_DATABASE_URI)
    host = (url.host or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        if os.getenv("WANASAH_ALLOW_REMOTE_TEST_DB") != "YES":
            raise SystemExit(
                "REFUSED: DATABASE_URL is not local. This test writes temporary fixtures. "
                "Set WANASAH_ALLOW_REMOTE_TEST_DB=YES only for an intentional remote TEST DB."
            )


async def set_tenant(db, company_id: int | None) -> None:
    tenant_context.set(company_id)
    value = "" if company_id is None else str(company_id)
    await db.execute(
        text("SELECT set_config('app.current_tenant', :tenant, false)"),
        {"tenant": value},
    )


async def expect_http(awaitable, status: int) -> HTTPException:
    try:
        await awaitable
    except HTTPException as exc:
        if exc.status_code != status:
            raise AssertionError(
                f"Expected HTTP {status}, got {exc.status_code}: {exc.detail}"
            )
        return exc
    raise AssertionError(f"Expected HTTP {status}, call unexpectedly succeeded")


async def create_company_admin(label: str):
    suffix = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        await set_tenant(db, None)
        company = Company(
            name=f"Freeze {label} {suffix}",
            company_code=f"FZ{label}{suffix}",
            is_active=True,
            subscription_status="active",
            currency_code="JOD",
            timezone="Asia/Amman",
        )
        db.add(company)
        await db.flush()
        company_id = int(company.id)

        await set_tenant(db, company_id)
        admin = Driver(
            company_id=company_id,
            username=f"freeze_{label.lower()}_{suffix}",
            password_hash=bcrypt.hashpw(
                TEST_PASSWORD.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8"),
            full_name=f"Freeze Admin {label}",
            is_active=True,
            is_admin=True,
        )
        warehouse = InventoryLocation(
            company_id=company_id,
            name=f"Freeze Warehouse {label}",
            code=f"FZ-WH-{label}-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        stocktake_warehouse = InventoryLocation(
            company_id=company_id,
            name=f"Freeze Stocktake Warehouse {label}",
            code=f"FZ-STK-{label}-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        db.add_all([admin, warehouse, stocktake_warehouse])
        await db.commit()
        return (
            company_id, int(admin.id), int(warehouse.id),
            int(stocktake_warehouse.id), suffix
        )


async def load_admin(db, company_id: int, admin_id: int) -> Driver:
    await set_tenant(db, company_id)
    return (
        await db.execute(
            select(Driver).where(
                Driver.company_id == company_id,
                Driver.id == admin_id,
            )
        )
    ).scalar_one()


async def cleanup_company(company_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await set_tenant(db, company_id)
        # Reverse FK order from SQLAlchemy metadata. Every tenant row is deleted only
        # while RLS is set to that same company.
        for table in reversed(Base.metadata.sorted_tables):
            if table.name == "companies" or "company_id" not in table.c:
                continue
            await db.execute(
                delete(table).where(table.c.company_id == company_id)
            )
        await db.commit()

    async with AsyncSessionLocal() as db:
        await set_tenant(db, None)
        await db.execute(delete(Company).where(Company.id == company_id))
        await db.commit()


async def test_uom_and_inbound(fx: dict) -> None:
    company_id = fx["company_id"]
    admin_id = fx["admin_id"]
    warehouse_id = fx["warehouse_id"]
    suffix = fx["suffix"]

    async with AsyncSessionLocal() as db:
        await set_tenant(db, None)
        decoy = UOM(
            name=f"Freeze Decoy {suffix}",
            code=f"FZD{suffix[:8].upper()}",
        )
        db.add(decoy)
        await db.commit()
        fx["decoy_uom_id"] = int(decoy.id)

    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, company_id, admin_id)
        payload = AddProductVariantRequest(
            variant_name=f"Freeze Product {suffix}",
            sku=f"FZ-SKU-{suffix}",
            price_per_carton=Decimal("10.000"),
            packs_per_carton=50,
            price_per_pack=Decimal("0.200"),
            min_threshold_packs=5,
            default_max_samples_per_day=0,
        )
        result = await add_product_variant(
            payload=payload,
            db=db,
            current_admin=admin,
        )
        variant_id = int(result["product_id"])
        fx["variant_id"] = variant_id

    async with AsyncSessionLocal() as db:
        await set_tenant(db, company_id)
        row = (
            await db.execute(
                select(ProductVariant.base_uom_id, UOM.code)
                .join(UOM, UOM.id == ProductVariant.base_uom_id)
                .where(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id == fx["variant_id"],
                )
            )
        ).one()
        if str(row.code).upper() != "CARTON":
            raise AssertionError(f"Variant was assigned wrong UOM: {row}")
        if int(row.base_uom_id) == fx["decoy_uom_id"]:
            raise AssertionError("Arbitrary UOM fallback is still possible")

        as_of = await get_company_local_date(db, company_id)
        fx["as_of"] = as_of

    print("UOM_EXACT_CARTON=OK")

    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, company_id, admin_id)
        expired_number = f"EXP-{suffix}"
        await expect_http(
            warehouse_inbound(
                payload=UpgradedInboundRequest(
                    request_id=uuid.uuid4(),
                    location_id=warehouse_id,
                    reference_id=f"FZ-EXP-{suffix}",
                    items=[InboundBatchItem(
                        product_variant_id=fx["variant_id"],
                        quantity_packs=5,
                        batch_number=expired_number,
                        production_date=fx["as_of"] - timedelta(days=20),
                        expiry_date=fx["as_of"] - timedelta(days=1),
                    )],
                ),
                db=db,
                current_admin=admin,
            ),
            422,
        )
        inserted = (
            await db.execute(
                select(ProductBatch.id).where(
                    ProductBatch.company_id == company_id,
                    ProductBatch.product_variant_id == fx["variant_id"],
                    ProductBatch.batch_number == expired_number,
                )
            )
        ).scalar_one_or_none()
        if inserted is not None:
            raise AssertionError("Expired inbound created a batch despite rejection")

    print("INBOUND_EXPIRED=BLOCKED")

    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, company_id, admin_id)
        future_number = f"FUT-{suffix}"
        await expect_http(
            warehouse_inbound(
                payload=UpgradedInboundRequest(
                    request_id=uuid.uuid4(),
                    location_id=warehouse_id,
                    reference_id=f"FZ-FUT-{suffix}",
                    items=[InboundBatchItem(
                        product_variant_id=fx["variant_id"],
                        quantity_packs=5,
                        batch_number=future_number,
                        production_date=fx["as_of"] + timedelta(days=1),
                        expiry_date=fx["as_of"] + timedelta(days=30),
                    )],
                ),
                db=db,
                current_admin=admin,
            ),
            422,
        )
    print("INBOUND_FUTURE_PRODUCTION=BLOCKED")

    # Existing inactive batch must never receive new AVAILABLE stock.
    inactive_number = f"INA-{suffix}"
    async with AsyncSessionLocal() as db:
        await set_tenant(db, company_id)
        batch = ProductBatch(
            company_id=company_id,
            product_variant_id=fx["variant_id"],
            batch_number=inactive_number,
            production_date=fx["as_of"] - timedelta(days=10),
            expiry_date=fx["as_of"] + timedelta(days=40),
            is_active=False,
        )
        db.add(batch)
        await db.commit()
        inactive_batch_id = int(batch.id)

    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, company_id, admin_id)
        await expect_http(
            warehouse_inbound(
                payload=UpgradedInboundRequest(
                    request_id=uuid.uuid4(),
                    location_id=warehouse_id,
                    reference_id=f"FZ-INA-{suffix}",
                    items=[InboundBatchItem(
                        product_variant_id=fx["variant_id"],
                        quantity_packs=5,
                        batch_number=inactive_number,
                        production_date=fx["as_of"] - timedelta(days=10),
                        expiry_date=fx["as_of"] + timedelta(days=40),
                    )],
                ),
                db=db,
                current_admin=admin,
            ),
            409,
        )
        bal = (
            await db.execute(
                select(InventoryBalance.id).where(
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.location_id == warehouse_id,
                    InventoryBalance.batch_id == inactive_batch_id,
                )
            )
        ).scalar_one_or_none()
        if bal is not None:
            raise AssertionError("Inactive batch gained inventory after rejected inbound")
    print("INBOUND_INACTIVE_EXISTING_BATCH=BLOCKED")

    # Existing metadata mismatch must reject without mutating the existing batch.
    mismatch_number = f"MIS-{suffix}"
    original_expiry = fx["as_of"] + timedelta(days=60)
    async with AsyncSessionLocal() as db:
        await set_tenant(db, company_id)
        batch = ProductBatch(
            company_id=company_id,
            product_variant_id=fx["variant_id"],
            batch_number=mismatch_number,
            production_date=fx["as_of"] - timedelta(days=5),
            expiry_date=original_expiry,
            is_active=True,
        )
        db.add(batch)
        await db.commit()
        mismatch_batch_id = int(batch.id)

    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, company_id, admin_id)
        await expect_http(
            warehouse_inbound(
                payload=UpgradedInboundRequest(
                    request_id=uuid.uuid4(),
                    location_id=warehouse_id,
                    reference_id=f"FZ-MIS-{suffix}",
                    items=[InboundBatchItem(
                        product_variant_id=fx["variant_id"],
                        quantity_packs=5,
                        batch_number=mismatch_number,
                        production_date=fx["as_of"] - timedelta(days=5),
                        expiry_date=original_expiry + timedelta(days=1),
                    )],
                ),
                db=db,
                current_admin=admin,
            ),
            409,
        )
        current_expiry = (
            await db.execute(
                select(ProductBatch.expiry_date).where(
                    ProductBatch.company_id == company_id,
                    ProductBatch.id == mismatch_batch_id,
                )
            )
        ).scalar_one()
        if current_expiry != original_expiry:
            raise AssertionError("Rejected metadata mismatch mutated ProductBatch")
    print("INBOUND_EXISTING_BATCH_METADATA_CONFLICT=BLOCKED")

    # Two valid inbound operations create enough ledger rows for cursor-scope tests.
    valid_number = f"VAL-{suffix}"
    for seq in (1, 2):
        async with AsyncSessionLocal() as db:
            admin = await load_admin(db, company_id, admin_id)
            result = await warehouse_inbound(
                payload=UpgradedInboundRequest(
                    request_id=uuid.uuid4(),
                    location_id=warehouse_id,
                    reference_id=f"FZ-VALID-{suffix}-{seq}",
                    items=[InboundBatchItem(
                        product_variant_id=fx["variant_id"],
                        quantity_packs=5,
                        batch_number=valid_number,
                        production_date=fx["as_of"] - timedelta(days=2),
                        expiry_date=fx["as_of"] + timedelta(days=90),
                    )],
                ),
                db=db,
                current_admin=admin,
            )
            if "بنجاح" not in str(result.get("message", "")):
                raise AssertionError(f"Valid inbound failed: {result}")

    async with AsyncSessionLocal() as db:
        await set_tenant(db, company_id)
        balance = (
            await db.execute(
                select(InventoryBalance).join(
                    ProductBatch,
                    (ProductBatch.company_id == InventoryBalance.company_id)
                    & (ProductBatch.id == InventoryBalance.batch_id),
                ).where(
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.location_id == warehouse_id,
                    InventoryBalance.product_variant_id == fx["variant_id"],
                    ProductBatch.batch_number == valid_number,
                    InventoryBalance.stock_status == "AVAILABLE",
                )
            )
        ).scalar_one()
        if int(balance.on_hand_quantity) != 10:
            raise AssertionError(
                f"Valid inbound physical balance mismatch: {balance.on_hand_quantity} != 10"
            )
        fx["valid_batch_id"] = int(balance.batch_id)
    print("INBOUND_VALID_PHYSICAL_BALANCE=OK")


async def start_full_count(db, admin, fx: dict) -> int:
    result = await start_unified_stocktake(
        payload=UnifiedStocktakeStartRequest(
            location_id=fx["stocktake_warehouse_id"],
            stocktake_type="FULL_COUNT",
            notes="Freeze audit discovered policy",
        ),
        db=db,
        current_admin=admin,
    )
    return int(result["session_id"])


async def cancel_session(session_id: int, fx: dict) -> None:
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, fx["company_id"], fx["admin_id"])
        await cancel_stocktake_session(
            session_id=session_id,
            payload=StocktakeCancelRequest(
                password=TEST_PASSWORD,
                reason="Freeze audit cleanup",
            ),
            db=db,
            current_admin=admin,
        )


async def test_discovered_policy(fx: dict) -> None:
    company_id = fx["company_id"]
    as_of = fx["as_of"]
    variant_id = fx["variant_id"]
    suffix = fx["suffix"]

    batch_specs = {
        "valid": (as_of - timedelta(days=5), as_of + timedelta(days=30), True),
        "expired": (as_of - timedelta(days=40), as_of - timedelta(days=1), False),
        "future": (as_of + timedelta(days=1), as_of + timedelta(days=30), True),
    }
    batch_ids = {}
    async with AsyncSessionLocal() as db:
        await set_tenant(db, company_id)
        for key, (production, expiry, active) in batch_specs.items():
            batch = ProductBatch(
                company_id=company_id,
                product_variant_id=variant_id,
                batch_number=f"DISC-{key}-{suffix}",
                production_date=production,
                expiry_date=expiry,
                is_active=active,
            )
            db.add(batch)
            await db.flush()
            batch_ids[key] = int(batch.id)
        await db.commit()

    # Valid AVAILABLE discovered accepted.
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, company_id, fx["admin_id"])
        session_id = await start_full_count(db, admin, fx)
    try:
        async with AsyncSessionLocal() as db:
            admin = await load_admin(db, company_id, fx["admin_id"])
            result = await submit_stocktake_count(
                session_id=session_id,
                payload=UnifiedStocktakeCountRequest(items=[StocktakeCountItem(
                    product_variant_id=variant_id,
                    batch_id=batch_ids["valid"],
                    stock_status="AVAILABLE",
                    actual_quantity=3,
                )]),
                db=db,
                current_admin=admin,
            )
            if int(result.get("attempt_id", 0)) <= 0:
                raise AssertionError(f"Valid DISCOVERED was not recorded: {result}")
    finally:
        await cancel_session(session_id, fx)
    print("DISCOVERED_AVAILABLE_VALID=ALLOWED")

    # Expired/inactive AVAILABLE rejected.
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, company_id, fx["admin_id"])
        session_id = await start_full_count(db, admin, fx)
    try:
        async with AsyncSessionLocal() as db:
            admin = await load_admin(db, company_id, fx["admin_id"])
            await expect_http(
                submit_stocktake_count(
                    session_id=session_id,
                    payload=UnifiedStocktakeCountRequest(items=[StocktakeCountItem(
                        product_variant_id=variant_id,
                        batch_id=batch_ids["expired"],
                        stock_status="AVAILABLE",
                        actual_quantity=2,
                    )]),
                    db=db,
                    current_admin=admin,
                ),
                422,
            )
    finally:
        await cancel_session(session_id, fx)
    print("DISCOVERED_EXPIRED_AVAILABLE=BLOCKED")

    # The same expired/inactive batch is countable as DAMAGED physical stock.
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, company_id, fx["admin_id"])
        session_id = await start_full_count(db, admin, fx)
    try:
        async with AsyncSessionLocal() as db:
            admin = await load_admin(db, company_id, fx["admin_id"])
            result = await submit_stocktake_count(
                session_id=session_id,
                payload=UnifiedStocktakeCountRequest(items=[StocktakeCountItem(
                    product_variant_id=variant_id,
                    batch_id=batch_ids["expired"],
                    stock_status="DAMAGED",
                    actual_quantity=2,
                )]),
                db=db,
                current_admin=admin,
            )
            if int(result.get("attempt_id", 0)) <= 0:
                raise AssertionError("Expired DAMAGED discovered line was not recorded")
    finally:
        await cancel_session(session_id, fx)
    print("DISCOVERED_EXPIRED_DAMAGED=ALLOWED")

    # Future production rejected even for DAMAGED.
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, company_id, fx["admin_id"])
        session_id = await start_full_count(db, admin, fx)
    try:
        async with AsyncSessionLocal() as db:
            admin = await load_admin(db, company_id, fx["admin_id"])
            await expect_http(
                submit_stocktake_count(
                    session_id=session_id,
                    payload=UnifiedStocktakeCountRequest(items=[StocktakeCountItem(
                        product_variant_id=variant_id,
                        batch_id=batch_ids["future"],
                        stock_status="DAMAGED",
                        actual_quantity=2,
                    )]),
                    db=db,
                    current_admin=admin,
                ),
                422,
            )
    finally:
        await cancel_session(session_id, fx)
    print("DISCOVERED_FUTURE_PRODUCTION_DAMAGED=BLOCKED")

    # Zero DISCOVERED rejected.
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, company_id, fx["admin_id"])
        session_id = await start_full_count(db, admin, fx)
    try:
        async with AsyncSessionLocal() as db:
            admin = await load_admin(db, company_id, fx["admin_id"])
            await expect_http(
                submit_stocktake_count(
                    session_id=session_id,
                    payload=UnifiedStocktakeCountRequest(items=[StocktakeCountItem(
                        product_variant_id=variant_id,
                        batch_id=batch_ids["valid"],
                        stock_status="DAMAGED",
                        actual_quantity=0,
                    )]),
                    db=db,
                    current_admin=admin,
                ),
                422,
            )
    finally:
        await cancel_session(session_id, fx)
    print("DISCOVERED_ZERO_QUANTITY=BLOCKED")


async def test_ledger_cursor_scope(fx: dict, fx_b: dict) -> None:
    async with AsyncSessionLocal() as db:
        admin = await load_admin(db, fx["company_id"], fx["admin_id"])
        page = await get_warehouse_ledger_cursor(
            location_id=fx["warehouse_id"],
            cursor=None,
            limit=1,
            search=None,
            reference_type=None,
            reference_id=None,
            db=db,
            current_admin=admin,
        )
        cursor = page.get("next_cursor")
        if not cursor:
            raise AssertionError("Ledger fixture did not produce a next_cursor")

        await expect_http(
            get_warehouse_ledger_cursor(
                location_id=fx["warehouse_id"],
                cursor=cursor,
                limit=1,
                search="freeze product",
                reference_type=None,
                reference_id=None,
                db=db,
                current_admin=admin,
            ),
            400,
        )

    async with AsyncSessionLocal() as db:
        admin_b = await load_admin(db, fx_b["company_id"], fx_b["admin_id"])
        await expect_http(
            get_warehouse_ledger_cursor(
                location_id=fx_b["warehouse_id"],
                cursor=cursor,
                limit=1,
                search=None,
                reference_type=None,
                reference_id=None,
                db=db,
                current_admin=admin_b,
            ),
            400,
        )

    print("LEDGER_CURSOR_FILTER_SCOPE=BLOCKED")
    print("LEDGER_CURSOR_CROSS_TENANT_SCOPE=BLOCKED")


async def cleanup_decoy_uom(fx: dict) -> None:
    uom_id = fx.get("decoy_uom_id")
    if not uom_id:
        return
    async with AsyncSessionLocal() as db:
        await set_tenant(db, None)
        await db.execute(delete(UOM).where(UOM.id == uom_id))
        await db.commit()


async def main() -> None:
    safety_gate()
    a = b = None
    fx_a = fx_b = None
    try:
        a = await create_company_admin("A")
        b = await create_company_admin("B")
        fx_a = {
            "company_id": a[0], "admin_id": a[1], "warehouse_id": a[2],
            "stocktake_warehouse_id": a[3], "suffix": a[4]
        }
        fx_b = {
            "company_id": b[0], "admin_id": b[1], "warehouse_id": b[2],
            "stocktake_warehouse_id": b[3], "suffix": b[4]
        }

        await test_uom_and_inbound(fx_a)
        await test_discovered_policy(fx_a)
        await test_ledger_cursor_scope(fx_a, fx_b)

        print("WAREHOUSE_FREEZE_SUPPLEMENT_POSTGRES_OK")
    finally:
        errors = []
        for fx in (fx_a, fx_b):
            if not fx:
                continue
            try:
                await cleanup_company(fx["company_id"])
            except Exception as exc:
                errors.append(f"company {fx['company_id']}: {exc}")
        if fx_a:
            try:
                await cleanup_decoy_uom(fx_a)
            except Exception as exc:
                errors.append(f"decoy uom: {exc}")
        if errors:
            raise RuntimeError("FREEZE_TEST_CLEANUP_FAILED: " + " | ".join(errors))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        asyncio.run(engine.dispose())
