from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import event, text


def find_backend_root() -> Path:
    here = Path(__file__).resolve()
    candidates = (
        Path.cwd() / "wa_backend",
        here.parent.parent / "wa_backend",
        here.parent.parent,
        here.parent,
    )
    for candidate in candidates:
        if (
            (candidate / "main.py").is_file()
            and (candidate / "database.py").is_file()
        ):
            return candidate.resolve()
    raise RuntimeError("wa_backend not found.")


BACKEND_ROOT = find_backend_root()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import api.warehouse.live_stock as live_stock  # noqa: E402
from context import tenant_context  # noqa: E402
from database import engine  # noqa: E402
from scripts.gate_inventory_batches_pagination_performance import (  # noqa: E402
    add_scale_fixture,
)
from scripts.gate_inventory_batches_roundtrip import (  # noqa: E402
    prepare_session,
    resolve_driver_id,
    resolve_target,
)
from scripts.inspect_inventory_batches_pagination_plan import (  # noqa: E402
    capture_batch_sql,
    capture_endpoint_query,
    explain,
    print_plan,
)


EXPERIMENT_INDEX = "ix_experiment_product_batches_page_seek"


async def ddl_capability(db) -> tuple[str, str, bool]:
    row = (
        await db.execute(
            text(
                """
                SELECT
                    current_user AS current_user,
                    owner.rolname AS table_owner,
                    current_setting('is_superuser') = 'on' AS is_superuser
                FROM pg_class AS rel
                JOIN pg_namespace AS ns
                  ON ns.oid = rel.relnamespace
                JOIN pg_roles AS owner
                  ON owner.oid = rel.relowner
                WHERE ns.nspname = current_schema()
                  AND rel.relname = 'product_batches'
                  AND rel.relkind = 'r'
                """
            )
        )
    ).mappings().one_or_none()
    if row is None:
        raise RuntimeError("product_batches table metadata was not found.")

    return (
        str(row["current_user"]),
        str(row["table_owner"]),
        bool(row["is_superuser"]),
    )


async def index_exists(db) -> bool:
    return bool(
        await db.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_class AS idx
                    JOIN pg_namespace AS ns
                      ON ns.oid = idx.relnamespace
                    WHERE ns.nspname = current_schema()
                      AND idx.relname = :index_name
                      AND idx.relkind = 'i'
                )
                """
            ),
            {"index_name": EXPERIMENT_INDEX},
        )
    )


async def async_main(args: argparse.Namespace) -> None:
    driver_id = await resolve_driver_id(args.company_id, args.driver_id)
    location_id, product_variant_id = await resolve_target(
        args.company_id,
        args.location_id,
        args.product_variant_id,
    )

    db, driver, tenant_token = await prepare_session(
        args.company_id,
        driver_id,
    )
    try:
        if await index_exists(db):
            raise RuntimeError(
                f"Experiment index already exists: {EXPERIMENT_INDEX}"
            )

        current_user, table_owner, is_superuser = (
            await ddl_capability(db)
        )
        if current_user != table_owner and not is_superuser:
            print(
                "INDEX_DDL_UNAVAILABLE "
                f"current_user={current_user} "
                f"table_owner={table_owner} "
                f"is_superuser={str(is_superuser).lower()}"
            )
            print(
                "INVENTORY_BATCH_SEEK_INDEX_EXPERIMENT=SKIP "
                "reason=ddl_requires_table_owner "
                "database_unchanged=true"
            )
            return

        await add_scale_fixture(
            db=db,
            company_id=args.company_id,
            location_id=location_id,
            product_variant_id=product_variant_id,
            count=args.fixture_batches,
        )

        before_sql = await capture_endpoint_query(
            live_stock.get_warehouse_inventory_batches,
            target_label="batch_candidates",
            db=db,
            driver=driver,
            location_id=location_id,
            product_variant_id=product_variant_id,
            paginated=True,
        )
        before_plan = await explain(db, before_sql)

        await db.execute(
            text(
                f"""
                CREATE INDEX {EXPERIMENT_INDEX}
                ON product_batches (
                    company_id,
                    product_variant_id,
                    expiry_date ASC NULLS LAST,
                    id ASC
                )
                """
            )
        )

        if not await index_exists(db):
            raise RuntimeError(
                "Transactional experiment index was not created."
            )

        after_sql = await capture_endpoint_query(
            live_stock.get_warehouse_inventory_batches,
            target_label="batch_candidates",
            db=db,
            driver=driver,
            location_id=location_id,
            product_variant_id=product_variant_id,
            paginated=True,
        )
        after_plan = await explain(db, after_sql)

        print(
            "TARGET "
            f"company_id={args.company_id} "
            f"location_id={location_id} "
            f"product_variant_id={product_variant_id} "
            f"fixture_batches={args.fixture_batches}"
        )
        print_plan("BEFORE_INDEX", before_plan)
        print_plan("WITH_INDEX", after_plan)
        print(
            "INVENTORY_BATCH_SEEK_INDEX_EXPERIMENT=PASS "
            "rollback_only=true"
        )
    finally:
        await db.rollback()
        if await index_exists(db):
            raise RuntimeError(
                "Rollback failed: experiment index still exists."
            )
        tenant_context.reset(tenant_token)
        await db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a transactional rollback-only seek index, compare the "
            "exact batch candidate query plan before/after, then prove that "
            "the index was removed by rollback."
        )
    )
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--driver-id", type=int)
    parser.add_argument("--location-id", type=int)
    parser.add_argument("--product-variant-id", type=int)
    parser.add_argument("--fixture-batches", type=int, default=205)
    args = parser.parse_args()

    if args.company_id <= 0:
        parser.error("--company-id must be positive")
    if args.fixture_batches < 200:
        parser.error("--fixture-batches must be >= 200")
    return args


async def _run() -> None:
    event.listen(
        engine.sync_engine,
        "before_cursor_execute",
        capture_batch_sql,
    )
    try:
        await async_main(parse_args())
    finally:
        event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            capture_batch_sql,
        )
        await engine.dispose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
