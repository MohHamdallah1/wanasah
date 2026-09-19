from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

DEMO_PRODUCT_CODE = "__UI_LIVE_STOCK_DEMO__"
DEMO_SKU_PREFIX = "UI-LIVE-"


def find_backend_root() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        Path.cwd() / "wa_backend",
        here.parent / "wa_backend",
        here.parent.parent / "wa_backend",
        here.parent.parent,
    ]
    for candidate in candidates:
        if (candidate / "models.py").is_file() and (candidate / ".env").is_file():
            return candidate.resolve()
    raise RuntimeError(
        "wa_backend not found. Run from repository root or place this file in wa_backend/scripts/."
    )


BACKEND_ROOT = find_backend_root()
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env", override=False)

from models import (  # noqa: E402
    Company,
    Driver,
    InventoryBalance,
    InventoryLocation,
    InventoryStockPolicy,
    Product,
    ProductBatch,
    ProductLocation,
    ProductUomConversion,
    ProductVariant,
    UOM,
    utc_now,
)


def migration_url() -> str:
    url = os.getenv("DATABASE_URL_MIGRATION")
    if not url:
        raise RuntimeError("DATABASE_URL_MIGRATION is missing from wa_backend/.env")
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://") and "asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


engine = create_async_engine(migration_url(), echo=False)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def list_targets() -> None:
    async with Session() as session:
        companies = (
            await session.execute(
                select(Company.id, Company.name, Company.company_code)
                .order_by(Company.id.asc())
            )
        ).all()
        print("COMPANIES_AND_WAREHOUSES")
        for company_id, name, code in companies:
            print(f"\nCompany {company_id}: {name} ({code})")
            warehouses = (
                await session.execute(
                    select(
                        InventoryLocation.id,
                        InventoryLocation.name,
                        InventoryLocation.code,
                        InventoryLocation.is_active,
                    )
                    .where(
                        InventoryLocation.company_id == company_id,
                        InventoryLocation.location_type == "WAREHOUSE",
                    )
                    .order_by(InventoryLocation.id.asc())
                )
            ).all()
            for location_id, location_name, location_code, is_active in warehouses:
                state = "ACTIVE" if is_active else "INACTIVE"
                print(
                    f"  Warehouse {location_id}: {location_name} "
                    f"({location_code}) [{state}]"
                )


async def get_demo_product(session, company_id: int):
    return await session.scalar(
        select(Product).where(
            Product.company_id == company_id,
            Product.code == DEMO_PRODUCT_CODE,
        )
    )


async def cleanup(company_id: int, commit: bool) -> None:
    async with Session() as session:
        product = await get_demo_product(session, company_id)
        if product is None:
            print("CLEANUP_NOTHING_TO_DO")
            return

        variant_ids = list(
            (
                await session.scalars(
                    select(ProductVariant.id).where(
                        ProductVariant.company_id == company_id,
                        ProductVariant.product_id == product.id,
                        ProductVariant.sku.like(f"{DEMO_SKU_PREFIX}%"),
                    )
                )
            ).all()
        )

        if variant_ids:
            for model in (
                InventoryBalance,
                InventoryStockPolicy,
                ProductLocation,
                ProductUomConversion,
                ProductBatch,
            ):
                await session.execute(
                    delete(model).where(
                        model.company_id == company_id,
                        model.product_variant_id.in_(variant_ids),
                    )
                )
            await session.execute(
                delete(ProductVariant).where(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id.in_(variant_ids),
                )
            )

        await session.delete(product)
        if commit:
            await session.commit()
            print(f"CLEANUP_OK company_id={company_id} variants={len(variant_ids)}")
        else:
            await session.rollback()
            print(f"CLEANUP_DRY_RUN company_id={company_id} variants={len(variant_ids)}")


async def seed(
    company_id: int,
    location_id: int,
    count: int,
    alerts: int,
    commit: bool,
) -> None:
    if not 1 <= count <= 2000:
        raise RuntimeError("--count must be between 1 and 2000")
    if not 0 <= alerts <= count:
        raise RuntimeError("--alerts must be between 0 and --count")

    async with Session() as session:
        company = await session.scalar(select(Company).where(Company.id == company_id))
        if company is None:
            raise RuntimeError(f"Company {company_id} not found")

        location = await session.scalar(
            select(InventoryLocation).where(
                InventoryLocation.id == location_id,
                InventoryLocation.company_id == company_id,
                InventoryLocation.location_type == "WAREHOUSE",
                InventoryLocation.is_active.is_(True),
            )
        )
        if location is None:
            raise RuntimeError(
                f"Warehouse {location_id} is not an active warehouse for company {company_id}"
            )

        existing = await get_demo_product(session, company_id)
        if existing is not None:
            raise RuntimeError(
                "Demo data already exists. Run --cleanup first, then seed again."
            )

        actor = await session.scalar(
            select(Driver)
            .where(Driver.company_id == company_id, Driver.is_active.is_(True))
            .order_by(Driver.is_admin.desc(), Driver.id.asc())
            .limit(1)
        )
        if actor is None:
            raise RuntimeError("No active driver/admin exists for this company")

        each = await session.scalar(select(UOM).where(UOM.code == "EACH"))
        carton = await session.scalar(select(UOM).where(UOM.code == "CARTON"))
        if each is None or carton is None:
            raise RuntimeError("EACH/CARTON UOM is missing")

        product = Product(
            company_id=company_id,
            code=DEMO_PRODUCT_CODE,
            name="اختبار واجهة المخزون الحي",
            description="بيانات تطوير مؤقتة لاختبار السكرول والترقيم والتنبيهات.",
            brand="UI TEST",
            category="DEMO",
        )
        session.add(product)
        await session.flush()

        today = utc_now().date()

        for index in range(1, count + 1):
            variant = ProductVariant(
                company_id=company_id,
                product_id=product.id,
                base_uom_id=each.id,
                name=f"منتج تجريبي {index:04d}",
                sku=f"{DEMO_SKU_PREFIX}{index:04d}",
                quantity_scale=0,
                quantity_step=Decimal("1"),
                lot_control_mode="REQUIRED",
                expiry_control_mode="REQUIRED",
                lifecycle_status="ACTIVE",
                operational_hold="NONE",
                published_at=utc_now(),
                packs_per_carton=50,
            )
            session.add(variant)
            await session.flush()

            session.add(
                ProductLocation(
                    company_id=company_id,
                    location_id=location_id,
                    product_variant_id=variant.id,
                    operational_flags={
                        "inbound_enabled": True,
                        "outbound_enabled": True,
                    },
                    created_by=actor.id,
                )
            )
            session.add(
                ProductUomConversion(
                    company_id=company_id,
                    product_variant_id=variant.id,
                    from_uom_id=carton.id,
                    to_uom_id=each.id,
                    numerator=Decimal("50"),
                    denominator=Decimal("1"),
                    quantity_scale=0,
                )
            )

            batch = ProductBatch(
                company_id=company_id,
                product_variant_id=variant.id,
                batch_number="DEMO-01",
                production_date=today - timedelta(days=30),
                expiry_date=today + timedelta(days=365),
                disposition="RELEASED",
                is_active=True,
            )
            session.add(batch)
            await session.flush()

            reserved = Decimal("100") if index % 5 == 0 else Decimal("0")
            session.add(
                InventoryBalance(
                    company_id=company_id,
                    location_id=location_id,
                    product_variant_id=variant.id,
                    batch_id=batch.id,
                    stock_status="AVAILABLE",
                    on_hand_quantity=Decimal("5100"),
                    reserved_quantity=reserved,
                )
            )

            if index % 7 == 0:
                session.add(
                    InventoryBalance(
                        company_id=company_id,
                        location_id=location_id,
                        product_variant_id=variant.id,
                        batch_id=batch.id,
                        stock_status="BLOCKED",
                        on_hand_quantity=Decimal("50"),
                        reserved_quantity=Decimal("0"),
                    )
                )
            if index % 13 == 0:
                session.add(
                    InventoryBalance(
                        company_id=company_id,
                        location_id=location_id,
                        product_variant_id=variant.id,
                        batch_id=batch.id,
                        stock_status="RECALLED",
                        on_hand_quantity=Decimal("25"),
                        reserved_quantity=Decimal("0"),
                    )
                )
            if index % 17 == 0:
                session.add(
                    InventoryBalance(
                        company_id=company_id,
                        location_id=location_id,
                        product_variant_id=variant.id,
                        batch_id=batch.id,
                        stock_status="DAMAGED",
                        on_hand_quantity=Decimal("10"),
                        reserved_quantity=Decimal("0"),
                    )
                )

            is_alert = index <= alerts
            session.add(
                InventoryStockPolicy(
                    company_id=company_id,
                    location_id=location_id,
                    product_variant_id=variant.id,
                    minimum_quantity=Decimal("6000") if is_alert else Decimal("1000"),
                    target_quantity=Decimal("7500") if is_alert else Decimal("6000"),
                    minimum_remaining_shelf_life_days=0,
                    is_active=True,
                )
            )

        if commit:
            await session.commit()
            print(
                f"SEED_OK company_id={company_id} location_id={location_id} "
                f"count={count} alerts={alerts}"
            )
            print(
                f"DEMO_PAGES={(count + 49) // 50} "
                "(current Live Stock API limit is 50 rows per page)"
            )
            if alerts:
                print("Refresh Live Stock with an empty search to see the alert filter banner.")
        else:
            await session.rollback()
            print(
                f"SEED_DRY_RUN_OK company_id={company_id} location_id={location_id} "
                f"count={count} alerts={alerts}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Non-destructive Live Stock UI demo seeder. "
            "It never drops or rebuilds the schema."
        )
    )
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--company-id", type=int)
    parser.add_argument("--location-id", type=int)
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--alerts", type=int, default=18)
    parser.add_argument(
        "--confirm-dev",
        action="store_true",
        help="Commit seed/cleanup changes. Without it, changes are rolled back.",
    )
    return parser.parse_args()


async def run() -> None:
    args = parse_args()
    try:
        if args.list:
            await list_targets()
            return
        if args.cleanup:
            if args.company_id is None:
                raise RuntimeError("--cleanup requires --company-id")
            await cleanup(args.company_id, args.confirm_dev)
            return
        if args.company_id is None or args.location_id is None:
            raise RuntimeError(
                "Seeding requires --company-id and --location-id. Run --list first."
            )
        await seed(
            args.company_id,
            args.location_id,
            args.count,
            args.alerts,
            args.confirm_dev,
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
