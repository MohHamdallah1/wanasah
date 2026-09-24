from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text


SCRIPTS = Path(__file__).resolve().parent
BACKEND = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(BACKEND))

import gate_products_read_contract_p2 as p2_gate
from audit_products_p4_performance import (
    QueryProbe,
    endpoint_kwargs,
    measure_scenario,
)
from models import Driver


DEFAULT_ROWS = 250_000
MIN_ROWS = 10_000
MAX_ROWS = 250_000
DEFAULT_CHUNK = 25_000
MIN_CHUNK = 5_000
MAX_CHUNK = 50_000
DEFAULT_RUNS = 5
MIN_RUNS = 3
MAX_RUNS = 10


def bounded_env_int(
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"{name} must be an integer."
        ) from exc
    if value < minimum or value > maximum:
        raise RuntimeError(
            f"{name} must be between {minimum} and {maximum}."
        )
    return value


async def seed_growth_catalog(
    ids: dict[str, int],
    *,
    prefix: str,
    row_count: int,
    chunk_size: int,
) -> int:
    company_id = int(ids["company_id"])
    each_uom_id = int(ids["each_uom_id"])

    async with p2_gate.SessionSU() as su:
        await su.begin()
        product_id = int(
            (
                await su.execute(
                    text(
                        "INSERT INTO products "
                        "(company_id, code, name, version, created_at, updated_at) "
                        "VALUES "
                        "(:company_id, :code, :name, 1, NOW(), NOW()) "
                        "RETURNING id"
                    ),
                    {
                        "company_id": company_id,
                        "code": prefix + "-FAMILY",
                        "name": "P8 Growth Family",
                    },
                )
            ).scalar_one()
        )
        await su.commit()

    print(
        "GROWTH_SEED_START "
        f"rows={row_count} chunk={chunk_size}"
    )

    for start in range(
        1,
        row_count + 1,
        chunk_size,
    ):
        end = min(
            start + chunk_size - 1,
            row_count,
        )
        async with p2_gate.SessionSU() as su:
            await su.begin()

            await su.execute(
                text(
                    "INSERT INTO product_variants "
                    "(company_id, product_id, base_uom_id, name, sku, "
                    "quantity_scale, quantity_step, lot_control_mode, "
                    "expiry_control_mode, lifecycle_status, operational_hold, "
                    "lifecycle_revision, version, published_at, retired_at, "
                    "archived_at, packs_per_carton, package_uses_base_barcode, "
                    "default_max_samples_per_day, created_at, updated_at) "
                    "SELECT "
                    ":company_id, :product_id, :uom_id, "
                    "'P8 Growth Item ' || LPAD(gs::text, 6, '0'), "
                    ":prefix || '-SKU-' || LPAD(gs::text, 6, '0'), "
                    "0, 1, "
                    "CASE WHEN gs % 4 IN (0, 1) "
                    "THEN 'REQUIRED' ELSE 'NONE' END, "
                    "CASE WHEN gs % 4 IN (1, 2) "
                    "THEN 'REQUIRED' ELSE 'NONE' END, "
                    "CASE WHEN gs % 10 = 0 "
                    "THEN 'RETIRING' ELSE 'ACTIVE' END, "
                    "'NONE', 1, 1, "
                    "NOW() - INTERVAL '2 days', "
                    "CASE WHEN gs % 10 = 0 "
                    "THEN NOW() - INTERVAL '1 day' ELSE NULL END, "
                    "NULL, 1, false, 0, NOW(), NOW() "
                    "FROM generate_series(:start_row, :end_row) AS gs"
                ),
                {
                    "company_id": company_id,
                    "product_id": product_id,
                    "uom_id": each_uom_id,
                    "prefix": prefix,
                    "start_row": start,
                    "end_row": end,
                },
            )

            await su.execute(
                text(
                    "INSERT INTO product_barcodes "
                    "(company_id, product_variant_id, uom_id, barcode, "
                    "barcode_type, is_primary, valid_from, valid_to, "
                    "is_active, version, created_at, updated_at) "
                    "SELECT "
                    ":company_id, pv.id, :uom_id, "
                    ":prefix || '-BC-' || LPAD(gs::text, 6, '0'), "
                    "'INTERNAL', true, NOW() - INTERVAL '1 day', NULL, "
                    "true, 1, NOW(), NOW() "
                    "FROM generate_series(:start_row, :end_row) AS gs "
                    "JOIN product_variants AS pv "
                    "ON pv.company_id = :company_id "
                    "AND pv.sku = "
                    ":prefix || '-SKU-' || LPAD(gs::text, 6, '0') "
                    "WHERE gs % 2 = 0"
                ),
                {
                    "company_id": company_id,
                    "uom_id": each_uom_id,
                    "prefix": prefix,
                    "start_row": start,
                    "end_row": end,
                },
            )
            await su.commit()

        print(
            "GROWTH_SEED_PROGRESS "
            f"variants={end}/{row_count}"
        )

    async with p2_gate.SessionSU() as su:
        await su.begin()
        for table_name in (
            "products",
            "product_variants",
            "product_barcodes",
            "product_uom_conversions",
        ):
            await su.execute(
                text(
                    f"ANALYZE {table_name}"
                )
            )
        await su.commit()

    print(
        "GROWTH_SEED_DONE "
        f"variants={row_count}"
    )
    return product_id


async def cleanup_growth_catalog(
    ids: dict[str, int],
    *,
    prefix: str,
    product_id: int | None,
) -> tuple[bool, str]:
    company_id = ids.get("company_id")
    try:
        if (
            company_id is not None
            and product_id is not None
        ):
            async with p2_gate.SessionSU() as su:
                await su.begin()
                params = {
                    "company_id": int(company_id),
                    "prefix_like": prefix + "-%",
                    "product_id": int(product_id),
                }
                await su.execute(
                    text(
                        "DELETE FROM product_barcodes "
                        "WHERE company_id = :company_id "
                        "AND barcode LIKE :prefix_like"
                    ),
                    params,
                )
                await su.execute(
                    text(
                        "DELETE FROM product_variants "
                        "WHERE company_id = :company_id "
                        "AND product_id = :product_id "
                        "AND sku LIKE :prefix_like"
                    ),
                    params,
                )
                await su.execute(
                    text(
                        "DELETE FROM products "
                        "WHERE company_id = :company_id "
                        "AND id = :product_id"
                    ),
                    params,
                )
                await su.commit()

        cleanup_ok, cleanup_detail = (
            await p2_gate.cleanup(ids)
        )
        return cleanup_ok, cleanup_detail
    except Exception as exc:
        return (
            False,
            f"{type(exc).__name__}: {exc}",
        )


async def main() -> None:
    row_count = bounded_env_int(
        "P8_COMMON_FILTERS_GROWTH_ROWS",
        DEFAULT_ROWS,
        MIN_ROWS,
        MAX_ROWS,
    )
    chunk_size = bounded_env_int(
        "P8_COMMON_FILTERS_GROWTH_CHUNK",
        DEFAULT_CHUNK,
        MIN_CHUNK,
        MAX_CHUNK,
    )
    runs = bounded_env_int(
        "P8_COMMON_FILTERS_GROWTH_RUNS",
        DEFAULT_RUNS,
        MIN_RUNS,
        MAX_RUNS,
    )

    ids: dict[str, int] = {}
    prefix = (
        "P8GROWTH"
        + uuid4().hex[:8].upper()
    )
    product_id: int | None = None
    probe = QueryProbe()
    attached = False
    measured = False

    print(
        "P8_COMMON_FILTERS_GROWTH_ROWS="
        f"{row_count}"
    )
    print(
        "P8_COMMON_FILTERS_GROWTH_RUNS="
        f"{runs}"
    )

    try:
        ids = await p2_gate.bootstrap()
        product_id = await seed_growth_catalog(
            ids,
            prefix=prefix,
            row_count=row_count,
            chunk_size=chunk_size,
        )

        company_id = int(ids["company_id"])

        async with p2_gate.SessionApp() as app:
            await app.begin()
            await p2_gate.set_tenant(
                app,
                company_id,
            )
            await app.execute(
                text(
                    "SET LOCAL statement_timeout = '30s'"
                )
            )
            ids.update(
                await p2_gate.seed_tenant_transaction(
                    app,
                    ids,
                )
            )

            actor = await app.get(
                Driver,
                ids["pricing_driver_id"],
            )
            if actor is None:
                raise RuntimeError(
                    "Growth benchmark actor is not visible."
                )

            probe.attach()
            attached = True

            metrics, page = await measure_scenario(
                name="common_filters",
                app=app,
                actor=actor,
                probe=probe,
                kwargs=endpoint_kwargs(
                    lifecycle="ACTIVE",
                    tracking_type="LOT",
                    simple_compatible=True,
                    has_barcode=True,
                    lot_tracked=True,
                    expiry_tracked=False,
                    sort_by="name",
                    sort_dir="asc",
                    limit=50,
                ),
                runs=runs,
            )

            items = page.get("items")
            coherent = (
                isinstance(items, list)
                and len(items) == 50
                and all(
                    isinstance(item, dict)
                    and item.get("lifecycle_status")
                    == "ACTIVE"
                    and item.get("lot_control_mode")
                    != "NONE"
                    and item.get("expiry_control_mode")
                    == "NONE"
                    and item.get("unit_barcode")
                    is not None
                    and item.get("simple_compatible")
                    is True
                    for item in items
                )
            )
            if not coherent:
                raise RuntimeError(
                    "Growth common_filters result is not coherent."
                )

            print(
                "GROWTH_METRIC "
                f"p50_ms={metrics['p50_ms']:.3f} "
                f"p95_ms={metrics['p95_ms']:.3f} "
                f"p99_ms={metrics['p99_ms']:.3f} "
                f"query_count={metrics['query_count']} "
                f"items={metrics['item_count']}"
            )
            print(
                "P8_COMMON_FILTERS_GROWTH_MEASURED=PASS"
            )
            measured = True
            await app.rollback()

    finally:
        if attached:
            probe.detach()

        cleanup_ok, cleanup_detail = (
            await cleanup_growth_catalog(
                ids,
                prefix=prefix,
                product_id=product_id,
            )
        )
        print(
            "P8_COMMON_FILTERS_GROWTH_CLEANUP="
            + (
                "PASS"
                if cleanup_ok
                else "FAIL"
            )
            + (
                f" detail={cleanup_detail}"
                if cleanup_detail
                else ""
            )
        )

        await p2_gate.engine_app.dispose()
        await p2_gate.engine_su.dispose()

        if not measured or not cleanup_ok:
            print(
                "P8_COMMON_FILTERS_GROWTH_PROBE=FAIL"
            )
            raise SystemExit(1)

    print(
        "P8_COMMON_FILTERS_GROWTH_PROBE=PASS"
    )


if __name__ == "__main__":
    asyncio.run(main())
