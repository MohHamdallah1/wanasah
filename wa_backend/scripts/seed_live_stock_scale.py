from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

HOT_PRODUCT_CODE = "__PERF_LIVE_STOCK_SCALE__"
HOT_SKU_PREFIX = "PERF-LIVE-"
NOISE_COMPANY_PREFIX = "PERFNOISE-"
NOISE_PRODUCT_CODE = "__PERF_NOISE_PRODUCT__"
NOISE_SKU_PREFIX = "PERF-NOISE-"


def find_backend_root() -> Path:
    here = Path(__file__).resolve()
    candidates = (
        Path.cwd() / "wa_backend",
        here.parent.parent / "wa_backend",
        here.parent.parent,
        here.parent,
    )
    for candidate in candidates:
        if (candidate / "models.py").is_file() and (candidate / ".env").is_file():
            return candidate.resolve()
    raise RuntimeError(
        "wa_backend not found. Run from repository root or place this file in wa_backend/scripts/."
    )


BACKEND_ROOT = find_backend_root()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env", override=False)


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


async def scalar(session, sql: str, params: dict | None = None):
    return await session.scalar(text(sql), params or {})


async def execute(session, sql: str, params: dict | None = None):
    return await session.execute(text(sql), params or {})


async def ensure_target(session, company_id: int, location_id: int) -> tuple[int, int, int]:
    company_exists = await scalar(
        session,
        "SELECT 1 FROM companies WHERE id=:company_id",
        {"company_id": company_id},
    )
    if company_exists is None:
        raise RuntimeError(f"Company {company_id} not found")

    location_exists = await scalar(
        session,
        """
        SELECT 1
        FROM inventory_locations
        WHERE id=:location_id
          AND company_id=:company_id
          AND location_type='WAREHOUSE'
          AND is_active IS TRUE
        """,
        {"company_id": company_id, "location_id": location_id},
    )
    if location_exists is None:
        raise RuntimeError(
            f"Warehouse {location_id} is not an active warehouse for company {company_id}"
        )

    each_id = await scalar(session, "SELECT id FROM uom WHERE code='EACH'")
    carton_id = await scalar(session, "SELECT id FROM uom WHERE code='CARTON'")
    actor_id = await scalar(
        session,
        """
        SELECT id
        FROM drivers
        WHERE company_id=:company_id AND is_active IS TRUE
        ORDER BY is_admin DESC, id ASC
        LIMIT 1
        """,
        {"company_id": company_id},
    )
    if each_id is None or carton_id is None or actor_id is None:
        raise RuntimeError("Target company must have EACH, CARTON and one active driver/admin")

    return int(each_id), int(carton_id), int(actor_id)


async def cleanup_hot(session, company_id: int) -> int:
    product_id = await scalar(
        session,
        "SELECT id FROM products WHERE company_id=:company_id AND code=:code",
        {"company_id": company_id, "code": HOT_PRODUCT_CODE},
    )
    if product_id is None:
        return 0

    count = int(
        await scalar(
            session,
            "SELECT count(*) FROM product_variants WHERE company_id=:company_id AND product_id=:product_id",
            {"company_id": company_id, "product_id": product_id},
        )
        or 0
    )

    params = {"company_id": company_id, "product_id": product_id}
    child_deletes = (
        """
        DELETE FROM inventory_cost_states s
        USING product_variants v
        WHERE s.company_id=:company_id
          AND s.company_id=v.company_id
          AND s.product_variant_id=v.id
          AND v.product_id=:product_id
        """,
        """
        DELETE FROM inventory_balances b
        USING product_variants v
        WHERE b.company_id=:company_id
          AND b.company_id=v.company_id
          AND b.product_variant_id=v.id
          AND v.product_id=:product_id
        """,
        """
        DELETE FROM inventory_stock_policies p
        USING product_variants v
        WHERE p.company_id=:company_id
          AND p.company_id=v.company_id
          AND p.product_variant_id=v.id
          AND v.product_id=:product_id
        """,
        """
        DELETE FROM product_locations p
        USING product_variants v
        WHERE p.company_id=:company_id
          AND p.company_id=v.company_id
          AND p.product_variant_id=v.id
          AND v.product_id=:product_id
        """,
        """
        DELETE FROM product_uom_conversions c
        USING product_variants v
        WHERE c.company_id=:company_id
          AND c.company_id=v.company_id
          AND c.product_variant_id=v.id
          AND v.product_id=:product_id
        """,
        """
        DELETE FROM product_batches b
        USING product_variants v
        WHERE b.company_id=:company_id
          AND b.company_id=v.company_id
          AND b.product_variant_id=v.id
          AND v.product_id=:product_id
        """,
    )
    for sql in child_deletes:
        await execute(session, sql, params)

    await execute(
        session,
        "DELETE FROM product_variants WHERE company_id=:company_id AND product_id=:product_id",
        params,
    )
    await execute(
        session,
        "DELETE FROM products WHERE company_id=:company_id AND id=:product_id",
        params,
    )
    return count


async def cleanup_noise(session) -> tuple[int, int]:
    company_ids = [
        int(row[0])
        for row in (
            await execute(
                session,
                "SELECT id FROM companies WHERE company_code LIKE :prefix",
                {"prefix": f"{NOISE_COMPANY_PREFIX}%"},
            )
        ).all()
    ]
    if not company_ids:
        return 0, 0

    variants = int(
        await scalar(
            session,
            """
            SELECT count(*)
            FROM product_variants
            WHERE company_id = ANY(:company_ids)
            """,
            {"company_ids": company_ids},
        )
        or 0
    )

    # These tenants are created exclusively by this benchmark seeder.
    # Delete only the tables this seeder populates, then the companies.
    for table in (
        "inventory_cost_states",
        "inventory_balances",
        "inventory_stock_policies",
        "product_uom_conversions",
        "product_batches",
        "product_variants",
        "products",
        "inventory_locations",
    ):
        await execute(
            session,
            f"DELETE FROM {table} WHERE company_id = ANY(:company_ids)",
            {"company_ids": company_ids},
        )

    await execute(
        session,
        "DELETE FROM companies WHERE id = ANY(:company_ids)",
        {"company_ids": company_ids},
    )
    return len(company_ids), variants


async def seed_hot(
    session,
    *,
    company_id: int,
    location_id: int,
    count: int,
    alert_ratio: float,
    each_id: int,
    carton_id: int,
    actor_id: int,
) -> None:
    existing = await scalar(
        session,
        "SELECT 1 FROM products WHERE company_id=:company_id AND code=:code",
        {"company_id": company_id, "code": HOT_PRODUCT_CODE},
    )
    if existing is not None:
        raise RuntimeError("Scale data already exists. Run --cleanup-hot first.")

    alerts = int(round(count * alert_ratio))

    product_id = await scalar(
        session,
        """
        INSERT INTO products (
            company_id, code, name, description, brand, category,
            version, created_at, updated_at
        )
        VALUES (
            :company_id, :code, 'Live Stock Scale Benchmark',
            'Set-based benchmark data. Safe to remove by product code.',
            'PERF', 'BENCHMARK', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        RETURNING id
        """,
        {"company_id": company_id, "code": HOT_PRODUCT_CODE},
    )
    product_id = int(product_id)

    params = {
        "company_id": company_id,
        "location_id": location_id,
        "product_id": product_id,
        "count": count,
        "alerts": alerts,
        "each_id": each_id,
        "carton_id": carton_id,
        "actor_id": actor_id,
        "sku_prefix": HOT_SKU_PREFIX,
    }

    await execute(
        session,
        """
        INSERT INTO product_variants (
            company_id, product_id, base_uom_id, name, sku,
            quantity_scale, quantity_step, lot_control_mode,
            expiry_control_mode, lifecycle_status, operational_hold,
            lifecycle_revision, version, published_at,
            packs_per_carton, package_uses_base_barcode,
            default_max_samples_per_day, created_at, updated_at
        )
        SELECT
            :company_id, :product_id, :each_id,
            'PERF Live Product ' || lpad(gs::text, 6, '0'),
            :sku_prefix || lpad(gs::text, 6, '0'),
            0, 1, 'REQUIRED', 'REQUIRED', 'ACTIVE', 'NONE',
            1, 1, CURRENT_TIMESTAMP, 50, FALSE, 0,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM generate_series(1, :count) AS gs
        """,
        params,
    )

    await execute(
        session,
        """
        INSERT INTO product_locations (
            company_id, location_id, product_variant_id,
            operational_flags, version, created_by, created_at, updated_at
        )
        SELECT
            :company_id, :location_id, v.id,
            '{"inbound_enabled": true, "outbound_enabled": true}'::jsonb,
            1, :actor_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM product_variants v
        WHERE v.company_id=:company_id AND v.product_id=:product_id
        """,
        params,
    )

    await execute(
        session,
        """
        INSERT INTO product_uom_conversions (
            company_id, product_variant_id, from_uom_id, to_uom_id,
            numerator, denominator, quantity_scale, version,
            created_at, updated_at
        )
        SELECT
            :company_id, v.id, :carton_id, :each_id,
            50, 1, 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM product_variants v
        WHERE v.company_id=:company_id AND v.product_id=:product_id
        """,
        params,
    )

    await execute(
        session,
        """
        INSERT INTO product_batches (
            company_id, product_variant_id, batch_number,
            production_date, expiry_date, disposition,
            disposition_revision, is_active, created_at, updated_at
        )
        SELECT
            :company_id, v.id, 'PERF-A',
            CURRENT_DATE - 30, CURRENT_DATE + 365, 'RELEASED',
            1, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM product_variants v
        WHERE v.company_id=:company_id AND v.product_id=:product_id
        """,
        params,
    )

    await execute(
        session,
        """
        WITH ranked AS (
            SELECT id, row_number() OVER (ORDER BY id) AS rn
            FROM product_variants
            WHERE company_id=:company_id AND product_id=:product_id
        )
        INSERT INTO product_batches (
            company_id, product_variant_id, batch_number,
            production_date, expiry_date, disposition,
            disposition_revision, is_active, created_at, updated_at
        )
        SELECT
            :company_id, id, 'PERF-B',
            CURRENT_DATE - 15, CURRENT_DATE + 180, 'RELEASED',
            1, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM ranked
        WHERE rn % 5 = 0
        """,
        params,
    )

    await execute(
        session,
        """
        WITH ranked AS (
            SELECT id, row_number() OVER (ORDER BY id) AS rn
            FROM product_variants
            WHERE company_id=:company_id AND product_id=:product_id
        )
        INSERT INTO inventory_stock_policies (
            company_id, location_id, product_variant_id,
            minimum_quantity, target_quantity,
            minimum_remaining_shelf_life_days,
            is_active, created_at, updated_at
        )
        SELECT
            :company_id, :location_id, id,
            CASE WHEN rn <= :alerts THEN 6000 ELSE 1000 END,
            CASE WHEN rn <= :alerts THEN 7500 ELSE 6000 END,
            0, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM ranked
        """,
        params,
    )

    await execute(
        session,
        """
        WITH ranked AS (
            SELECT id, row_number() OVER (ORDER BY id) AS rn
            FROM product_variants
            WHERE company_id=:company_id AND product_id=:product_id
        )
        INSERT INTO inventory_balances (
            company_id, location_id, product_variant_id, batch_id,
            stock_status, on_hand_quantity, reserved_quantity, last_updated
        )
        SELECT
            :company_id, :location_id, r.id, b.id,
            'AVAILABLE', 5100,
            CASE WHEN r.rn % 5 = 0 THEN 100 ELSE 0 END,
            CURRENT_TIMESTAMP
        FROM ranked r
        JOIN product_batches b
          ON b.company_id=:company_id
         AND b.product_variant_id=r.id
         AND b.batch_number='PERF-A'
        """,
        params,
    )

    await execute(
        session,
        """
        WITH ranked AS (
            SELECT id, row_number() OVER (ORDER BY id) AS rn
            FROM product_variants
            WHERE company_id=:company_id AND product_id=:product_id
        )
        INSERT INTO inventory_balances (
            company_id, location_id, product_variant_id, batch_id,
            stock_status, on_hand_quantity, reserved_quantity, last_updated
        )
        SELECT
            :company_id, :location_id, r.id, b.id,
            'AVAILABLE', 400, 0, CURRENT_TIMESTAMP
        FROM ranked r
        JOIN product_batches b
          ON b.company_id=:company_id
         AND b.product_variant_id=r.id
         AND b.batch_number='PERF-B'
        WHERE r.rn % 5 = 0
        """,
        params,
    )

    for modulus, status, qty in (
        (7, "BLOCKED", 50),
        (13, "RECALLED", 25),
        (17, "DAMAGED", 10),
    ):
        await execute(
            session,
            f"""
            WITH ranked AS (
                SELECT id, row_number() OVER (ORDER BY id) AS rn
                FROM product_variants
                WHERE company_id=:company_id AND product_id=:product_id
            )
            INSERT INTO inventory_balances (
                company_id, location_id, product_variant_id, batch_id,
                stock_status, on_hand_quantity, reserved_quantity, last_updated
            )
            SELECT
                :company_id, :location_id, r.id, b.id,
                '{status}', {qty}, 0, CURRENT_TIMESTAMP
            FROM ranked r
            JOIN product_batches b
              ON b.company_id=:company_id
             AND b.product_variant_id=r.id
             AND b.batch_number='PERF-A'
            WHERE r.rn % {modulus} = 0
            """,
            params,
        )

    await execute(
        session,
        """
        INSERT INTO inventory_cost_states (
            company_id, product_variant_id, quantity,
            inventory_value, average_unit_cost, version,
            created_at, updated_at
        )
        SELECT
            :company_id, v.id, 5100, 510, 0.1, 1,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM product_variants v
        WHERE v.company_id=:company_id AND v.product_id=:product_id
        """,
        params,
    )


async def seed_noise(
    session,
    *,
    companies: int,
    products_per_company: int,
    each_id: int,
    carton_id: int,
) -> None:
    if companies <= 0 or products_per_company <= 0:
        return

    existing = await scalar(
        session,
        "SELECT 1 FROM companies WHERE company_code LIKE :prefix LIMIT 1",
        {"prefix": f"{NOISE_COMPANY_PREFIX}%"},
    )
    if existing is not None:
        raise RuntimeError("Noise companies already exist. Run --cleanup-noise first.")

    params = {
        "companies": companies,
        "products_per_company": products_per_company,
        "each_id": each_id,
        "carton_id": carton_id,
        "company_prefix": NOISE_COMPANY_PREFIX,
        "product_code": NOISE_PRODUCT_CODE,
        "sku_prefix": NOISE_SKU_PREFIX,
    }

    await execute(
        session,
        """
        INSERT INTO companies (
            name, company_code, is_active, subscription_status,
            currency_code, timezone, created_at
        )
        SELECT
            'PERF Noise ' || lpad(gs::text, 4, '0'),
            :company_prefix || lpad(gs::text, 4, '0'),
            TRUE, 'active', 'JOD', 'Asia/Amman', CURRENT_TIMESTAMP
        FROM generate_series(1, :companies) AS gs
        """,
        params,
    )

    await execute(
        session,
        """
        INSERT INTO inventory_locations (
            company_id, branch_id, name, code, location_type,
            vehicle_id, system_role, is_system_managed,
            version, is_active, created_at, updated_at
        )
        SELECT
            c.id, NULL, 'PERF Warehouse', 'PERF-WH', 'WAREHOUSE',
            NULL, NULL, FALSE, 1, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM companies c
        WHERE c.company_code LIKE :company_prefix || '%'
        """,
        params,
    )

    await execute(
        session,
        """
        INSERT INTO products (
            company_id, code, name, description, brand, category,
            version, created_at, updated_at
        )
        SELECT
            c.id, :product_code, 'PERF Noise Product Family',
            'Cross-tenant benchmark noise', 'PERF', 'BENCHMARK',
            1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM companies c
        WHERE c.company_code LIKE :company_prefix || '%'
        """,
        params,
    )

    await execute(
        session,
        """
        INSERT INTO product_variants (
            company_id, product_id, base_uom_id, name, sku,
            quantity_scale, quantity_step, lot_control_mode,
            expiry_control_mode, lifecycle_status, operational_hold,
            lifecycle_revision, version, published_at,
            packs_per_carton, package_uses_base_barcode,
            default_max_samples_per_day, created_at, updated_at
        )
        SELECT
            c.id, p.id, :each_id,
            'PERF Noise Product ' || lpad(gs::text, 6, '0'),
            :sku_prefix || c.id::text || '-' || lpad(gs::text, 6, '0'),
            0, 1, 'REQUIRED', 'REQUIRED', 'ACTIVE', 'NONE',
            1, 1, CURRENT_TIMESTAMP, 50, FALSE, 0,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM companies c
        JOIN products p
          ON p.company_id=c.id AND p.code=:product_code
        CROSS JOIN generate_series(1, :products_per_company) AS gs
        WHERE c.company_code LIKE :company_prefix || '%'
        """,
        params,
    )

    await execute(
        session,
        """
        INSERT INTO product_uom_conversions (
            company_id, product_variant_id, from_uom_id, to_uom_id,
            numerator, denominator, quantity_scale, version,
            created_at, updated_at
        )
        SELECT
            v.company_id, v.id, :carton_id, :each_id,
            50, 1, 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM product_variants v
        JOIN companies c ON c.id=v.company_id
        WHERE c.company_code LIKE :company_prefix || '%'
        """,
        params,
    )

    await execute(
        session,
        """
        INSERT INTO product_batches (
            company_id, product_variant_id, batch_number,
            production_date, expiry_date, disposition,
            disposition_revision, is_active, created_at, updated_at
        )
        SELECT
            v.company_id, v.id, 'PERF-NOISE',
            CURRENT_DATE - 30, CURRENT_DATE + 365, 'RELEASED',
            1, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM product_variants v
        JOIN companies c ON c.id=v.company_id
        WHERE c.company_code LIKE :company_prefix || '%'
        """,
        params,
    )

    await execute(
        session,
        """
        INSERT INTO inventory_stock_policies (
            company_id, location_id, product_variant_id,
            minimum_quantity, target_quantity,
            minimum_remaining_shelf_life_days,
            is_active, created_at, updated_at
        )
        SELECT
            v.company_id, l.id, v.id,
            1000, 6000, 0, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM product_variants v
        JOIN companies c ON c.id=v.company_id
        JOIN inventory_locations l
          ON l.company_id=v.company_id
         AND l.code='PERF-WH'
        WHERE c.company_code LIKE :company_prefix || '%'
        """,
        params,
    )

    await execute(
        session,
        """
        INSERT INTO inventory_balances (
            company_id, location_id, product_variant_id, batch_id,
            stock_status, on_hand_quantity, reserved_quantity, last_updated
        )
        SELECT
            v.company_id, l.id, v.id, b.id,
            'AVAILABLE', 5100, 0, CURRENT_TIMESTAMP
        FROM product_variants v
        JOIN companies c ON c.id=v.company_id
        JOIN inventory_locations l
          ON l.company_id=v.company_id
         AND l.code='PERF-WH'
        JOIN product_batches b
          ON b.company_id=v.company_id
         AND b.product_variant_id=v.id
         AND b.batch_number='PERF-NOISE'
        WHERE c.company_code LIKE :company_prefix || '%'
        """,
        params,
    )


async def analyze(session) -> None:
    # Statistics must reflect benchmark volume before measuring query plans.
    for table in (
        "product_variants",
        "product_uom_conversions",
        "product_batches",
        "inventory_balances",
        "inventory_stock_policies",
        "inventory_cost_states",
    ):
        await execute(session, f"ANALYZE {table}")


async def run(args: argparse.Namespace) -> None:
    async with Session() as session:
        try:
            if args.cleanup_hot:
                count = await cleanup_hot(session, args.company_id)
                if args.confirm_dev:
                    await session.commit()
                    print(f"CLEANUP_HOT_OK variants={count}")
                else:
                    await session.rollback()
                    print(f"CLEANUP_HOT_DRY_RUN variants={count}")
                return

            if args.cleanup_noise:
                companies, variants = await cleanup_noise(session)
                if args.confirm_dev:
                    await session.commit()
                    print(
                        f"CLEANUP_NOISE_OK companies={companies} variants={variants}"
                    )
                else:
                    await session.rollback()
                    print(
                        f"CLEANUP_NOISE_DRY_RUN companies={companies} variants={variants}"
                    )
                return

            each_id, carton_id, actor_id = await ensure_target(
                session, args.company_id, args.location_id
            )

            if args.hot_products:
                await seed_hot(
                    session,
                    company_id=args.company_id,
                    location_id=args.location_id,
                    count=args.hot_products,
                    alert_ratio=args.alert_ratio,
                    each_id=each_id,
                    carton_id=carton_id,
                    actor_id=actor_id,
                )

            if args.noise_companies and args.noise_products:
                await seed_noise(
                    session,
                    companies=args.noise_companies,
                    products_per_company=args.noise_products,
                    each_id=each_id,
                    carton_id=carton_id,
                )

            if args.confirm_dev:
                await session.commit()
                await analyze(session)
                await session.commit()
                print(
                    "SCALE_SEED_OK "
                    f"hot_products={args.hot_products} "
                    f"noise_companies={args.noise_companies} "
                    f"noise_products_per_company={args.noise_products}"
                )
            else:
                await session.rollback()
                print(
                    "SCALE_SEED_DRY_RUN_OK "
                    f"hot_products={args.hot_products} "
                    f"noise_companies={args.noise_companies} "
                    f"noise_products_per_company={args.noise_products}"
                )
        except Exception:
            await session.rollback()
            raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Set-based PostgreSQL Live Stock scale-data seeder. "
            "No per-row ORM loop; explicit commit guard."
        )
    )
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--location-id", type=int, required=True)
    parser.add_argument("--hot-products", type=int, default=10000)
    parser.add_argument("--alert-ratio", type=float, default=0.20)
    parser.add_argument("--noise-companies", type=int, default=0)
    parser.add_argument("--noise-products", type=int, default=0)
    parser.add_argument("--cleanup-hot", action="store_true")
    parser.add_argument("--cleanup-noise", action="store_true")
    parser.add_argument("--confirm-dev", action="store_true")
    args = parser.parse_args()

    if not 0 <= args.hot_products <= 50000:
        parser.error("--hot-products must be between 0 and 50000")
    if not 0 <= args.alert_ratio <= 1:
        parser.error("--alert-ratio must be between 0 and 1")
    if not 0 <= args.noise_companies <= 1000:
        parser.error("--noise-companies must be between 0 and 1000")
    if not 0 <= args.noise_products <= 10000:
        parser.error("--noise-products must be between 0 and 10000")
    return args


async def main() -> None:
    args = parse_args()
    try:
        await run(args)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
