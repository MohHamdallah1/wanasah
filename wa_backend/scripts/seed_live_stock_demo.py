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

DEMO_PRODUCT_CODE_PREFIX = "__UI_LIVE_STOCK_DEMO__"
DEMO_SKU_PREFIX = "UI-LIVE-"
DEMO_FAMILIES = (
    ("مشروبات", "BEV"),
    ("وجبات خفيفة", "SNK"),
    ("حلويات", "SWT"),
    ("مواد غذائية", "FOD"),
    ("عناية شخصية", "PCR"),
    ("منظفات", "CLN"),
    ("معلبات", "CAN"),
    ("ألبان", "DRY"),
)


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

from domains.live_stock_projection.service import refresh_live_stock_keys  # noqa: E402
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


async def get_demo_products(session, company_id: int) -> list[Product]:
    return list(
        (
            await session.scalars(
                select(Product)
                .where(
                    Product.company_id == company_id,
                    Product.code.like(f"{DEMO_PRODUCT_CODE_PREFIX}%"),
                )
                .order_by(Product.id.asc())
            )
        ).all()
    )


async def cleanup(company_id: int, commit: bool) -> None:
    async with Session() as session:
        products = await get_demo_products(session, company_id)
        if not products:
            print("CLEANUP_NOTHING_TO_DO")
            return

        product_ids = [int(product.id) for product in products]
        variant_ids = list(
            (
                await session.scalars(
                    select(ProductVariant.id).where(
                        ProductVariant.company_id == company_id,
                        ProductVariant.product_id.in_(product_ids),
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

        await session.execute(
            delete(Product).where(
                Product.company_id == company_id,
                Product.id.in_(product_ids),
            )
        )

        if commit:
            await session.commit()
            print(
                f"CLEANUP_OK company_id={company_id} "
                f"families={len(product_ids)} variants={len(variant_ids)}"
            )
        else:
            await session.rollback()
            print(
                f"CLEANUP_DRY_RUN company_id={company_id} "
                f"families={len(product_ids)} variants={len(variant_ids)}"
            )


def _split_quantity(total: Decimal, batch_count: int) -> list[Decimal]:
    if batch_count <= 1:
        return [total]
    if batch_count == 2:
        first = (total * Decimal("0.62")).quantize(Decimal("1"))
        return [first, total - first]

    first = (total * Decimal("0.50")).quantize(Decimal("1"))
    second = (total * Decimal("0.30")).quantize(Decimal("1"))
    return [first, second, total - first - second]


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

        existing = await get_demo_products(session, company_id)
        if existing:
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

        family_count = min(len(DEMO_FAMILIES), max(1, count))
        families: list[Product] = []
        for family_index in range(family_count):
            family_name, family_code = DEMO_FAMILIES[family_index]
            product = Product(
                company_id=company_id,
                code=f"{DEMO_PRODUCT_CODE_PREFIX}{family_index + 1:02d}",
                name=f"{family_name} تجريبية",
                description=(
                    "بيانات تطوير مؤقتة لاختبار المخزون الحي والعائلات "
                    "والوحدات والدفعات والصلاحية والحالات."
                ),
                brand=f"UI {family_code}",
                category="DEMO",
            )
            session.add(product)
            families.append(product)

        await session.flush()

        today = utc_now().date()
        projection_keys: list[tuple[int, int]] = []
        carton_factors = (50, 24, 12, 6)
        remainders = (20, 0, 7, 1, 11, 23, 3, 5)

        for index in range(1, count + 1):
            family = families[(index - 1) % family_count]
            carton_factor = carton_factors[(index - 1) % len(carton_factors)]
            base_units_only = index % 11 == 0

            variant = ProductVariant(
                company_id=company_id,
                product_id=family.id,
                base_uom_id=each.id,
                name=f"{family.name} {index:04d}",
                sku=f"{DEMO_SKU_PREFIX}{index:04d}",
                quantity_scale=0,
                quantity_step=Decimal("1"),
                lot_control_mode="REQUIRED",
                expiry_control_mode="REQUIRED",
                lifecycle_status="ACTIVE",
                operational_hold="NONE",
                published_at=utc_now(),
                packs_per_carton=carton_factor,
            )
            session.add(variant)
            await session.flush()

            projection_keys.append((location_id, int(variant.id)))

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

            if not base_units_only:
                session.add(
                    ProductUomConversion(
                        company_id=company_id,
                        product_variant_id=variant.id,
                        from_uom_id=carton.id,
                        to_uom_id=each.id,
                        numerator=Decimal(str(carton_factor)),
                        denominator=Decimal("1"),
                        quantity_scale=0,
                    )
                )

            # The first row is intentionally 50 cartons + 20 eaches when factor=50.
            if index == 1:
                total_available = Decimal("2520")
            else:
                whole_cartons = 8 + (index % 95)
                remainder = remainders[(index - 1) % len(remainders)]
                remainder = min(remainder, carton_factor - 1)
                total_available = (
                    Decimal(str(whole_cartons * carton_factor + remainder))
                )

            batch_count = 1 + (index % 3)
            available_parts = _split_quantity(total_available, batch_count)

            for batch_index, available_part in enumerate(available_parts, start=1):
                expiry_offset = 365 - ((index * 9 + batch_index * 17) % 420)
                disposition = "RELEASED"
                stock_status = "AVAILABLE"

                if batch_index == batch_count and index % 13 == 0:
                    disposition = "RECALLED"
                    stock_status = "RECALLED"
                elif batch_index == batch_count and index % 17 == 0:
                    disposition = "QUARANTINED"
                    stock_status = "QUARANTINED"

                batch = ProductBatch(
                    company_id=company_id,
                    product_variant_id=variant.id,
                    batch_number=f"DEMO-{index:04d}-{batch_index:02d}",
                    production_date=today - timedelta(days=540 + batch_index * 30),
                    expiry_date=today + timedelta(days=expiry_offset),
                    disposition=disposition,
                    disposition_reason=(
                        "بيانات تطوير لاختبار السحب"
                        if disposition == "RECALLED"
                        else "بيانات تطوير لاختبار الحجر"
                        if disposition == "QUARANTINED"
                        else None
                    ),
                    is_active=True,
                )
                session.add(batch)
                await session.flush()

                if stock_status == "AVAILABLE":
                    reserved = (
                        min(Decimal("13"), available_part)
                        if index % 5 == 0 and batch_index == 1
                        else Decimal("0")
                    )
                    session.add(
                        InventoryBalance(
                            company_id=company_id,
                            location_id=location_id,
                            product_variant_id=variant.id,
                            batch_id=batch.id,
                            stock_status="AVAILABLE",
                            on_hand_quantity=available_part,
                            reserved_quantity=reserved,
                        )
                    )
                else:
                    session.add(
                        InventoryBalance(
                            company_id=company_id,
                            location_id=location_id,
                            product_variant_id=variant.id,
                            batch_id=batch.id,
                            stock_status=stock_status,
                            on_hand_quantity=max(Decimal("1"), available_part),
                            reserved_quantity=Decimal("0"),
                        )
                    )

            # Add independent restricted stock examples without hiding the sellable remainder.
            first_batch = await session.scalar(
                select(ProductBatch)
                .where(
                    ProductBatch.company_id == company_id,
                    ProductBatch.product_variant_id == variant.id,
                )
                .order_by(ProductBatch.id.asc())
                .limit(1)
            )
            if first_batch is None:
                raise RuntimeError("Demo batch creation failed")

            if index % 7 == 0 and first_batch.disposition == "RELEASED":
                session.add(
                    InventoryBalance(
                        company_id=company_id,
                        location_id=location_id,
                        product_variant_id=variant.id,
                        batch_id=first_batch.id,
                        stock_status="BLOCKED",
                        on_hand_quantity=Decimal("5"),
                        reserved_quantity=Decimal("0"),
                    )
                )
            if index % 19 == 0 and first_batch.disposition == "RELEASED":
                session.add(
                    InventoryBalance(
                        company_id=company_id,
                        location_id=location_id,
                        product_variant_id=variant.id,
                        batch_id=first_batch.id,
                        stock_status="DAMAGED",
                        on_hand_quantity=Decimal("3"),
                        reserved_quantity=Decimal("0"),
                    )
                )

            # Leave every ninth product without a policy to exercise the "unset" filter.
            if index % 9 != 0:
                is_alert = index <= alerts
                if base_units_only:
                    minimum = Decimal("40") if is_alert else Decimal("10")
                    target = Decimal("120") if is_alert else Decimal("80")
                else:
                    minimum_cartons = Decimal("60") if is_alert else Decimal("5")
                    target_cartons = Decimal("90") if is_alert else Decimal("30")
                    minimum = minimum_cartons * Decimal(str(carton_factor))
                    target = target_cartons * Decimal(str(carton_factor))

                session.add(
                    InventoryStockPolicy(
                        company_id=company_id,
                        location_id=location_id,
                        product_variant_id=variant.id,
                        minimum_quantity=minimum,
                        target_quantity=target,
                        minimum_remaining_shelf_life_days=0,
                        is_active=True,
                    )
                )

        await session.flush()
        await refresh_live_stock_keys(
            session,
            company_id=company_id,
            keys=projection_keys,
        )

        if commit:
            await session.commit()
            print(
                f"SEED_OK company_id={company_id} location_id={location_id} "
                f"families={family_count} count={count} alerts={alerts}"
            )
            print(
                "RICH_DEMO=carton_remainders,multiple_families,multiple_batches,"
                "reserved,blocked,recalled,quarantined,damaged,unset_minimum"
            )
            print(
                "EXAMPLE_FIRST_PRODUCT=2520 EACH => 50 CARTON + 20 EACH "
                "(when CARTON factor is 50)"
            )
        else:
            await session.rollback()
            print(
                f"SEED_DRY_RUN_OK company_id={company_id} location_id={location_id} "
                f"families={family_count} count={count} alerts={alerts}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Non-destructive rich Live Stock UI demo seeder. "
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
