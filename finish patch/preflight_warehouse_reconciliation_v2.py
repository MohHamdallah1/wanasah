from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import inspect, text

ROOT = Path.cwd()
BACKEND = ROOT / "wa_backend"

if not BACKEND.is_dir():
    raise SystemExit("ERROR: شغّل السكربت من جذر مشروع wanasah.")

sys.path.insert(0, str(BACKEND))

from database import engine


LEGACY_TABLES = [
    "main_warehouse",
    "damaged_items_log",
    "inventory_transfers",
    "warehouse_ledger",
    "vehicle_loads",
    "session_inventory",
    "inventory_ledgers",
]


async def scalar(db, sql: str, **params):
    return (await db.execute(text(sql), params)).scalar()


async def rows(db, sql: str, **params):
    return (await db.execute(text(sql), params)).mappings().all()


async def table_exists(db, table_name: str) -> bool:
    return bool(await scalar(
        db,
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name = :table_name
        )
        """,
        table_name=table_name,
    ))


async def column_exists(db, table_name: str, column_name: str) -> bool:
    return bool(await scalar(
        db,
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = :table_name
              AND column_name = :column_name
        )
        """,
        table_name=table_name,
        column_name=column_name,
    ))


async def count_table(db, table_name: str) -> int:
    return int(await scalar(db, f'SELECT count(*) FROM "{table_name}"') or 0)


async def main():
    if engine.dialect.name != "postgresql":
        raise SystemExit("POSTGRESQL_REQUIRED_FOR_MIGRATION_PREFLIGHT")

    blockers = []
    warnings = []
    auto_safe = []

    async with engine.connect() as db:
        # ------------------------------------------------------------
        # 1) Legacy tables: deleting non-empty tables is never silent.
        # ------------------------------------------------------------
        for table_name in LEGACY_TABLES:
            if await table_exists(db, table_name):
                count = await count_table(db, table_name)
                if count:
                    blockers.append(
                        f"LEGACY_DATA {table_name}: {count} rows موجودة؛ ممنوع DROP قبل ترحيل/أرشفة البيانات."
                    )
                else:
                    auto_safe.append(
                        f"LEGACY_EMPTY {table_name}: الجدول فارغ ويمكن حذفه بعد اكتمال القيود."
                    )

        # ------------------------------------------------------------
        # 2) dispatch_routes.source_location_id
        # ------------------------------------------------------------
        if await table_exists(db, "dispatch_routes"):
            has_source = await column_exists(db, "dispatch_routes", "source_location_id")
            route_count = await count_table(db, "dispatch_routes")

            if not has_source and route_count:
                ambiguous = await rows(
                    db,
                    """
                    WITH companies_with_routes AS (
                        SELECT DISTINCT company_id
                        FROM dispatch_routes
                    ),
                    warehouse_counts AS (
                        SELECT
                            c.company_id,
                            count(il.id) FILTER (
                                WHERE il.location_type = 'WAREHOUSE'
                                  AND il.is_active IS TRUE
                            ) AS active_warehouse_count,
                            min(il.id) FILTER (
                                WHERE il.location_type = 'WAREHOUSE'
                                  AND il.is_active IS TRUE
                            ) AS only_warehouse_id
                        FROM companies_with_routes c
                        LEFT JOIN inventory_locations il
                          ON il.company_id = c.company_id
                        GROUP BY c.company_id
                    )
                    SELECT company_id, active_warehouse_count, only_warehouse_id
                    FROM warehouse_counts
                    WHERE active_warehouse_count <> 1
                    ORDER BY company_id
                    """
                )

                if ambiguous:
                    sample = ", ".join(
                        f"company={r['company_id']} warehouses={r['active_warehouse_count']}"
                        for r in ambiguous[:10]
                    )
                    blockers.append(
                        "DISPATCH_SOURCE_MAPPING: source_location_id غير موجود وهنالك شركات "
                        f"لا تملك مستودعاً فعالاً واحداً بالضبط. أمثلة: {sample}"
                    )
                else:
                    auto_safe.append(
                        "DISPATCH_SOURCE_MAPPING: كل شركة لها Routes تملك مستودعاً فعالاً واحداً؛ "
                        "يمكن Backfill source_location_id آلياً دون تخمين."
                    )

            elif not has_source:
                auto_safe.append(
                    "DISPATCH_SOURCE_MAPPING: dispatch_routes فارغ؛ يمكن إضافة source_location_id مباشرة."
                )

        # ------------------------------------------------------------
        # 3) inventory_locations.updated_at + driver_id removal
        # ------------------------------------------------------------
        if await table_exists(db, "inventory_locations"):
            if not await column_exists(db, "inventory_locations", "updated_at"):
                auto_safe.append(
                    "INVENTORY_LOCATIONS_UPDATED_AT: يمكن Backfill من created_at ثم جعله NOT NULL."
                )

            if await column_exists(db, "inventory_locations", "driver_id"):
                driver_rows = int(await scalar(
                    db,
                    """
                    SELECT count(*)
                    FROM inventory_locations
                    WHERE driver_id IS NOT NULL
                    """
                ) or 0)

                driver_without_vehicle = int(await scalar(
                    db,
                    """
                    SELECT count(*)
                    FROM inventory_locations
                    WHERE driver_id IS NOT NULL
                      AND vehicle_id IS NULL
                    """
                ) or 0)

                if driver_without_vehicle:
                    blockers.append(
                        "INVENTORY_LOCATION_DRIVER: "
                        f"{driver_without_vehicle} locations مرتبطة بمندوب بلا vehicle_id؛ "
                        "ممنوع إسقاط driver_id قبل تحديد علاقتها الجديدة."
                    )
                elif driver_rows:
                    warnings.append(
                        "INVENTORY_LOCATION_DRIVER: "
                        f"{driver_rows} rows تحمل driver_id؛ يوجد vehicle_id معها، "
                        "ويمكن إسقاط driver_id بعد التحقق من uniqueness للسيارات."
                    )
                else:
                    auto_safe.append(
                        "INVENTORY_LOCATION_DRIVER: driver_id غير مستخدم ويمكن إسقاطه بأمان."
                    )

        # ------------------------------------------------------------
        # 4) Batch NOT NULL migrations.
        # ------------------------------------------------------------
        for table_name in (
            "inventory_balances",
            "inventory_movements",
            "inventory_transfer_lines",
            "stocktake_lines",
        ):
            if (
                await table_exists(db, table_name)
                and await column_exists(db, table_name, "batch_id")
            ):
                null_count = int(await scalar(
                    db,
                    f'SELECT count(*) FROM "{table_name}" WHERE batch_id IS NULL'
                ) or 0)

                if null_count:
                    # Determine how many rows can be inferred uniquely from existing ProductBatch.
                    inferable = int(await scalar(
                        db,
                        f"""
                        SELECT count(*)
                        FROM "{table_name}" t
                        WHERE t.batch_id IS NULL
                          AND 1 = (
                              SELECT count(*)
                              FROM product_batches pb
                              WHERE pb.company_id = t.company_id
                                AND pb.product_variant_id = t.product_variant_id
                          )
                        """
                    ) or 0)

                    blockers.append(
                        f"BATCH_NULL {table_name}: {null_count} rows بلا batch_id "
                        f"(منها {inferable} فقط يمكن استنتاج Batch وحيد لها). "
                        "ممنوع تحويل العمود إلى NOT NULL قبل خطة ترحيل صريحة."
                    )
                else:
                    auto_safe.append(
                        f"BATCH_NULL {table_name}: لا توجد NULLs؛ تحويل NOT NULL آمن من ناحية البيانات."
                    )

        # ------------------------------------------------------------
        # 5) Existing stocktake history before dropping actual/variance.
        # ------------------------------------------------------------
        if await table_exists(db, "stocktake_lines"):
            has_actual = await column_exists(db, "stocktake_lines", "actual_quantity")
            has_variance = await column_exists(db, "stocktake_lines", "variance_quantity")

            if has_actual or has_variance:
                counted_rows = 0
                if has_actual:
                    counted_rows = int(await scalar(
                        db,
                        "SELECT count(*) FROM stocktake_lines WHERE actual_quantity IS NOT NULL"
                    ) or 0)

                if counted_rows:
                    blockers.append(
                        "STOCKTAKE_HISTORY: "
                        f"{counted_rows} stocktake_lines تحمل actual_quantity. "
                        "ممنوع DROP لهذه الأعمدة قبل تحويلها إلى "
                        "stocktake_count_attempts + stocktake_count_attempt_lines."
                    )
                else:
                    auto_safe.append(
                        "STOCKTAKE_HISTORY: لا توجد نتائج عد قديمة محفوظة في stocktake_lines."
                    )

        if await table_exists(db, "stocktake_sessions"):
            active_old_sessions = int(await scalar(
                db,
                """
                SELECT count(*)
                FROM stocktake_sessions
                WHERE status NOT IN ('POSTED', 'CANCELLED')
                """
            ) or 0)

            if active_old_sessions:
                blockers.append(
                    "ACTIVE_STOCKTAKES: "
                    f"{active_old_sessions} جلسات جرد قديمة غير نهائية؛ "
                    "يجب إغلاقها/ترحيلها قبل تغيير عقد الجرد."
                )
            else:
                auto_safe.append(
                    "ACTIVE_STOCKTAKES: لا توجد جلسات جرد قديمة مفتوحة."
                )

        # ------------------------------------------------------------
        # 6) Old inventory movement shape must be convertible.
        # ------------------------------------------------------------
        if await table_exists(db, "inventory_movements"):
            source_exists = await column_exists(db, "inventory_movements", "source_location_id")
            dest_exists = await column_exists(db, "inventory_movements", "destination_location_id")

            if source_exists and dest_exists:
                no_endpoint = int(await scalar(
                    db,
                    """
                    SELECT count(*)
                    FROM inventory_movements
                    WHERE source_location_id IS NULL
                      AND destination_location_id IS NULL
                    """
                ) or 0)
                same_endpoint = int(await scalar(
                    db,
                    """
                    SELECT count(*)
                    FROM inventory_movements
                    WHERE source_location_id IS NOT NULL
                      AND destination_location_id IS NOT NULL
                      AND source_location_id = destination_location_id
                    """
                ) or 0)

                if no_endpoint:
                    blockers.append(
                        f"MOVEMENT_SHAPE: {no_endpoint} historical movements بلا source/destination؛ "
                        "لا يمكن تحويلها تلقائياً إلى PHYSICAL."
                    )
                if same_endpoint:
                    blockers.append(
                        f"MOVEMENT_SHAPE: {same_endpoint} historical movements source=destination؛ "
                        "تحتاج تصنيف RESERVATION/STATUS_CHANGE أو تنظيف صريح."
                    )
                if not no_endpoint and not same_endpoint:
                    auto_safe.append(
                        "MOVEMENT_SHAPE: الحركات التاريخية لها endpoint صالح ويمكن Backfill "
                        "stock_status=AVAILABLE وmovement_kind=PHYSICAL مبدئياً."
                    )

        # ------------------------------------------------------------
        # 7) Transfer headers existing states.
        # ------------------------------------------------------------
        if await table_exists(db, "inventory_transfer_headers"):
            statuses = await rows(
                db,
                """
                SELECT status, count(*) AS n
                FROM inventory_transfer_headers
                GROUP BY status
                ORDER BY status
                """
            )
            if statuses:
                rendered = ", ".join(f"{r['status']}={r['n']}" for r in statuses)
                warnings.append(
                    "TRANSFER_HEADER_STATUS: الحالات الحالية: " + rendered
                )

        # ------------------------------------------------------------
        # 8) Duplicate blockers for composite UNIQUEs referenced by new FKs.
        # ------------------------------------------------------------
        duplicate_checks = [
            ("dispatch_routes", ["company_id", "id"]),
            ("work_sessions", ["company_id", "id", "driver_id"]),
            ("visits", ["company_id", "id"]),
            ("product_batches", ["company_id", "product_variant_id", "id"]),
            ("override_reasons", ["company_id", "id"]),
            ("system_audit_logs", ["company_id", "id"]),
        ]

        for table_name, cols in duplicate_checks:
            if not await table_exists(db, table_name):
                continue
            columns_present = [
                await column_exists(db, table_name, c)
                for c in cols
            ]
            if not all(columns_present):
                continue
            col_sql = ", ".join(f'"{c}"' for c in cols)
            duplicate_groups = int(await scalar(
                db,
                f"""
                SELECT count(*)
                FROM (
                    SELECT {col_sql}
                    FROM "{table_name}"
                    GROUP BY {col_sql}
                    HAVING count(*) > 1
                ) q
                """
            ) or 0)

            if duplicate_groups:
                blockers.append(
                    f"UNIQUE_PREREQ {table_name}({', '.join(cols)}): "
                    f"{duplicate_groups} duplicate groups تمنع إنشاء الـUNIQUE المطلوب."
                )
            else:
                auto_safe.append(
                    f"UNIQUE_PREREQ {table_name}({', '.join(cols)}): لا توجد duplicates."
                )

        # ------------------------------------------------------------
        # 9) Null company_id in tenantized tables.
        # ------------------------------------------------------------
        tenant_tables = [
            "dispatch_routes",
            "inventory_locations",
            "inventory_balances",
            "inventory_movements",
            "inventory_transfer_headers",
            "inventory_transfer_lines",
            "stocktake_sessions",
            "stocktake_lines",
            "work_sessions",
            "visits",
            "visit_items",
            "visit_returns",
        ]
        for table_name in tenant_tables:
            if (
                await table_exists(db, table_name)
                and await column_exists(db, table_name, "company_id")
            ):
                nulls = int(await scalar(
                    db,
                    f'SELECT count(*) FROM "{table_name}" WHERE company_id IS NULL'
                ) or 0)
                if nulls:
                    blockers.append(
                        f"TENANT_NULL {table_name}: {nulls} rows بلا company_id."
                    )

    print("WAREHOUSE_RECONCILIATION_PREFLIGHT")
    print(f"AUTO_SAFE={len(auto_safe)}")
    for item in auto_safe:
        print("[SAFE] " + item)

    print(f"WARNINGS={len(warnings)}")
    for item in warnings:
        print("[WARN] " + item)

    print(f"BLOCKERS={len(blockers)}")
    for item in blockers:
        print("[BLOCKER] " + item)

    if blockers:
        print("STATUS=BLOCKED_NEEDS_DATA_RECONCILIATION")
        raise SystemExit(2)

    print("STATUS=READY_FOR_MANUAL_RECONCILIATION_MIGRATION")


async def _run() -> None:
    try:
        await main()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
