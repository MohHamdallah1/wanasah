from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env", override=False)

from domains.live_stock_projection.service import (
    apply_live_stock_active_variant_delta,
    apply_live_stock_balance_impacts,
    refresh_due_live_stock_transitions,
    refresh_live_stock_keys,
    refresh_live_stock_variants,
)

MIGRATION_URL = os.environ["DATABASE_URL_MIGRATION"]
APP_URL = os.environ["DATABASE_URL"]

engine_su = create_async_engine(MIGRATION_URL, pool_size=3, max_overflow=2)
engine_app = create_async_engine(APP_URL, pool_size=8, max_overflow=4)
SessionSU = async_sessionmaker(
    bind=engine_su, expire_on_commit=False, autobegin=False
)
SessionApp = async_sessionmaker(
    bind=engine_app, expire_on_commit=False, autobegin=False
)

RESULTS: list[tuple[str, bool, str]] = []
TEST_COMPANY_PREFIX = "S821-"


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(
        f"[{'PASS' if ok else 'FAIL'}] {name}"
        + (f" — {detail}" if detail else "")
    )


async def set_tenant(session, company_id: int) -> None:
    await session.execute(
        text("SELECT set_config('app.current_tenant', :tenant, true)"),
        {"tenant": str(company_id)},
    )


async def cleanup_test_companies() -> int:
    async with SessionSU() as su:
        await su.begin()
        company_ids = [
            int(value)
            for value in (
                await su.execute(
                    text(
                        "SELECT id FROM companies "
                        "WHERE company_code LIKE :prefix ORDER BY id"
                    ),
                    {"prefix": f"{TEST_COMPANY_PREFIX}%"},
                )
            ).scalars().all()
        ]
        if company_ids:
            await su.execute(
                text("DELETE FROM companies WHERE id = ANY(:ids)"),
                {"ids": company_ids},
            )
        await su.commit()

    async with SessionSU() as su:
        await su.begin()
        remaining = int(
            (
                await su.execute(
                    text(
                        "SELECT count(*) FROM companies "
                        "WHERE company_code LIKE :prefix"
                    ),
                    {"prefix": f"{TEST_COMPANY_PREFIX}%"},
                )
            ).scalar_one()
        )
        await su.rollback()
    if remaining:
        raise RuntimeError(
            f"Stage 8.2.1 runtime gate cleanup left {remaining} test companies."
        )
    return len(company_ids)


async def seed() -> dict[str, int]:
    as_of = datetime.now(ZoneInfo("Asia/Amman")).date()
    async with SessionSU() as su:
        await su.begin()
        required_tables = (
            "inventory_live_stock_company_summaries",
            "inventory_live_stock_warehouse_summaries",
            "inventory_live_stock_projection",
        )
        present = {
            row[0]
            for row in (
                await su.execute(
                    text(
                        """
                        SELECT c.relname
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = current_schema()
                          AND c.relname = ANY(CAST(:tables AS text[]))
                        """
                    ),
                    {"tables": list(required_tables)},
                )
            ).all()
        }
        if present != set(required_tables):
            raise RuntimeError(
                "Stage 8.2 foundation tables are missing. "
                f"present={sorted(present)}"
            )

        uom_id = (
            await su.execute(text("SELECT id FROM uom ORDER BY id LIMIT 1"))
        ).scalar_one_or_none()
        if uom_id is None:
            raise RuntimeError("No UOM row exists; runtime gate cannot seed variants.")

        async def company(label: str) -> int:
            return int(
                (
                    await su.execute(
                        text(
                            """
                            INSERT INTO companies
                                (name, company_code, is_active,
                                 subscription_status, currency_code,
                                 timezone, created_at)
                            VALUES
                                (:name, :code, true, 'active',
                                 'JOD', 'Asia/Amman', NOW())
                            RETURNING id
                            """
                        ),
                        {
                            "name": f"Stage821 {label}",
                            "code": f"{TEST_COMPANY_PREFIX}{uuid4().hex[:12]}",
                        },
                    )
                ).scalar_one()
            )

        async def branch(company_id: int, label: str) -> int:
            return int(
                (
                    await su.execute(
                        text(
                            """
                            INSERT INTO branches
                                (company_id, name, branch_code,
                                 is_active, created_at)
                            VALUES (:c, :name, :code, true, NOW())
                            RETURNING id
                            """
                        ),
                        {
                            "c": company_id,
                            "name": label,
                            "code": f"B-{uuid4().hex[:10]}",
                        },
                    )
                ).scalar_one()
            )

        async def warehouse(company_id: int, branch_id: int, label: str) -> int:
            return int(
                (
                    await su.execute(
                        text(
                            """
                            INSERT INTO inventory_locations
                                (company_id, branch_id, name, code,
                                 location_type, vehicle_id, system_role,
                                 is_system_managed, version, is_active,
                                 created_at, updated_at)
                            VALUES
                                (:c, :b, :name, :code, 'WAREHOUSE',
                                 NULL, NULL, false, 1, true, NOW(), NOW())
                            RETURNING id
                            """
                        ),
                        {
                            "c": company_id,
                            "b": branch_id,
                            "name": label,
                            "code": f"WH-{uuid4().hex[:10]}",
                        },
                    )
                ).scalar_one()
            )

        async def product(company_id: int, label: str) -> int:
            return int(
                (
                    await su.execute(
                        text(
                            """
                            INSERT INTO products
                                (company_id, code, name, version,
                                 created_at, updated_at)
                            VALUES (:c, :code, :name, 1, NOW(), NOW())
                            RETURNING id
                            """
                        ),
                        {
                            "c": company_id,
                            "code": f"P-{uuid4().hex[:10]}",
                            "name": label,
                        },
                    )
                ).scalar_one()
            )

        async def variant(company_id: int, product_id: int, label: str) -> int:
            return int(
                (
                    await su.execute(
                        text(
                            """
                            INSERT INTO product_variants
                                (company_id, product_id, base_uom_id,
                                 name, sku, quantity_scale, quantity_step,
                                 lot_control_mode, expiry_control_mode,
                                 lifecycle_status, operational_hold,
                                 lifecycle_revision, version, published_at,
                                 packs_per_carton, package_uses_base_barcode,
                                 default_max_samples_per_day,
                                 created_at, updated_at)
                            VALUES
                                (:c, :p, :u, :name, :sku, 0, 1,
                                 'REQUIRED', 'REQUIRED',
                                 'ACTIVE', 'NONE', 1, 1, NOW(),
                                 50, false, 0, NOW(), NOW())
                            RETURNING id
                            """
                        ),
                        {
                            "c": company_id,
                            "p": product_id,
                            "u": int(uom_id),
                            "name": label,
                            "sku": f"SKU-{uuid4().hex[:12]}",
                        },
                    )
                ).scalar_one()
            )

        async def batch(
            company_id: int,
            variant_id: int,
            label: str,
            production_date,
            expiry_date,
        ) -> int:
            return int(
                (
                    await su.execute(
                        text(
                            """
                            INSERT INTO product_batches
                                (company_id, product_variant_id,
                                 batch_number, production_date, expiry_date,
                                 disposition, disposition_revision, is_active,
                                 created_at, updated_at)
                            VALUES
                                (:c, :v, :batch, :production, :expiry,
                                 'RELEASED', 1, true, NOW(), NOW())
                            RETURNING id
                            """
                        ),
                        {
                            "c": company_id,
                            "v": variant_id,
                            "batch": label,
                            "production": production_date,
                            "expiry": expiry_date,
                        },
                    )
                ).scalar_one()
            )

        async def balance(
            company_id: int,
            warehouse_id: int,
            variant_id: int,
            batch_id: int,
            status: str,
            on_hand: int,
            reserved: int = 0,
        ) -> int:
            return int(
                (
                    await su.execute(
                        text(
                            """
                            INSERT INTO inventory_balances
                                (company_id, location_id, product_variant_id,
                                 batch_id, stock_status, on_hand_quantity,
                                 reserved_quantity, last_updated)
                            VALUES
                                (:c, :l, :v, :b, :status,
                                 :on_hand, :reserved, NOW())
                            RETURNING id
                            """
                        ),
                        {
                            "c": company_id,
                            "l": warehouse_id,
                            "v": variant_id,
                            "b": batch_id,
                            "status": status,
                            "on_hand": on_hand,
                            "reserved": reserved,
                        },
                    )
                ).scalar_one()
            )

        a = await company("Company A")
        b = await company("Company B")
        a_branch = await branch(a, "A Branch")
        b_branch = await branch(b, "B Branch")
        a_wh = await warehouse(a, a_branch, "A Warehouse")
        b_wh = await warehouse(b, b_branch, "B Warehouse")
        a_scrap = int(
            (
                await su.execute(
                    text(
                        """
                        INSERT INTO inventory_locations
                            (company_id, branch_id, name, code,
                             location_type, vehicle_id, system_role,
                             is_system_managed, version, is_active,
                             created_at, updated_at)
                        VALUES
                            (:c, :b, 'A Scrap', :code, 'SCRAP',
                             NULL, NULL, false, 1, true, NOW(), NOW())
                        RETURNING id
                        """
                    ),
                    {
                        "c": a,
                        "b": a_branch,
                        "code": f"SCRAP-{uuid4().hex[:10]}",
                    },
                )
            ).scalar_one()
        )

        a_product = await product(a, "A Product")
        b_product = await product(b, "B Product")
        a_variant = await variant(a, a_product, "A Variant")
        b_variant = await variant(b, b_product, "B Variant")
        b_variant_unprojected = await variant(b, b_product, "B Variant Hidden")

        a_batch1 = await batch(
            a, a_variant, f"A1-{uuid4().hex[:6]}",
            as_of - timedelta(days=10),
            as_of + timedelta(days=5),
        )
        a_batch2 = await batch(
            a, a_variant, f"A2-{uuid4().hex[:6]}",
            as_of - timedelta(days=5),
            as_of + timedelta(days=10),
        )
        a_batch3 = await batch(
            a, a_variant, f"A3-{uuid4().hex[:6]}",
            as_of + timedelta(days=2),
            as_of + timedelta(days=20),
        )

        a_bal1 = await balance(a, a_wh, a_variant, a_batch1, "AVAILABLE", 10, 2)
        a_bal2 = await balance(a, a_wh, a_variant, a_batch2, "AVAILABLE", 4, 0)
        await balance(a, a_wh, a_variant, a_batch3, "AVAILABLE", 6, 0)
        await balance(a, a_wh, a_variant, a_batch1, "BLOCKED", 3, 0)
        await balance(a, a_wh, a_variant, a_batch1, "DAMAGED", 1, 0)

        await su.execute(
            text(
                """
                INSERT INTO inventory_stock_policies
                    (company_id, location_id, product_variant_id,
                     minimum_quantity, target_quantity,
                     minimum_remaining_shelf_life_days,
                     is_active, created_at, updated_at)
                VALUES (:c, :l, :v, 12, 20, 3, true, NOW(), NOW())
                """
            ),
            {"c": a, "l": a_wh, "v": a_variant},
        )

        await su.execute(
            text(
                """
                INSERT INTO inventory_stock_policies
                    (company_id, location_id, product_variant_id,
                     minimum_quantity, target_quantity,
                     minimum_remaining_shelf_life_days,
                     is_active, created_at, updated_at)
                VALUES (:c, :l, :v, 1, 2, 0, true, NOW(), NOW())
                """
            ),
            {"c": b, "l": b_wh, "v": b_variant},
        )

        await su.commit()
        return {
            "a": a,
            "b": b,
            "a_wh": a_wh,
            "b_wh": b_wh,
            "a_scrap": a_scrap,
            "a_variant": a_variant,
            "a_batch1": a_batch1,
            "b_variant": b_variant,
            "b_variant_unprojected": b_variant_unprojected,
            "a_bal1": a_bal1,
            "a_bal2": a_bal2,
            "as_of_ordinal": as_of.toordinal(),
        }


async def balance_impact_metadata(
    session,
    *,
    company_id: int,
    balance_id: int,
) -> dict[str, object]:
    row = (
        await session.execute(
            text(
                """
                SELECT
                    b.id AS inventory_balance_id,
                    b.location_id,
                    l.location_type,
                    l.vehicle_id,
                    b.product_variant_id,
                    b.batch_id,
                    b.stock_status,
                    v.name AS variant_name,
                    v.lifecycle_status,
                    v.operational_hold,
                    v.expiry_control_mode,
                    pb.is_active AS batch_is_active,
                    pb.disposition AS batch_disposition,
                    pb.production_date,
                    pb.expiry_date
                FROM inventory_balances b
                JOIN inventory_locations l
                  ON l.company_id=b.company_id
                 AND l.id=b.location_id
                JOIN product_variants v
                  ON v.company_id=b.company_id
                 AND v.id=b.product_variant_id
                JOIN product_batches pb
                  ON pb.company_id=b.company_id
                 AND pb.product_variant_id=b.product_variant_id
                 AND pb.id=b.batch_id
                WHERE b.company_id=:company_id
                  AND b.id=:balance_id
                """
            ),
            {
                "company_id": company_id,
                "balance_id": balance_id,
            },
        )
    ).mappings().one()
    return dict(row)


async def projection_row(session, company_id: int, warehouse_id: int, variant_id: int):
    return (
        await session.execute(
            text(
                """
                SELECT
                    warehouse_on_hand,
                    warehouse_reserved,
                    warehouse_sellable_on_hand,
                    warehouse_sellable_reserved,
                    blocked_status_packs,
                    recalled_packs,
                    damaged_packs,
                    vehicle_packs,
                    minimum_quantity,
                    has_active_policy,
                    is_low_stock,
                    has_warehouse_presence,
                    has_vehicle_presence,
                    next_transition_date,
                    computed_for_date,
                    lifecycle_status,
                    operational_hold,
                    revision
                FROM inventory_live_stock_projection
                WHERE company_id=:c
                  AND warehouse_location_id=:w
                  AND product_variant_id=:v
                """
            ),
            {"c": company_id, "w": warehouse_id, "v": variant_id},
        )
    ).one_or_none()


async def main() -> None:
    ids: dict[str, int] = {}
    preclean_ok = False
    try:
        removed_before = await cleanup_test_companies()
        preclean_ok = True
        record(
            "runtime gate starts from a clean database",
            True,
            f"removed_stale_companies={removed_before}",
        )

        async with SessionSU() as su:
            await su.begin()
            trigger_defs = {
                str(row.name): str(row.definition)
                for row in (
                    await su.execute(
                        text(
                            """
                            SELECT t.tgname AS name,
                                   pg_get_triggerdef(t.oid) AS definition
                            FROM pg_trigger t
                            JOIN pg_class c ON c.oid=t.tgrelid
                            WHERE NOT t.tgisinternal
                              AND c.relname = ANY(
                                  CAST(:tables AS text[])
                              )
                              AND t.tgname = ANY(
                                  CAST(:triggers AS text[])
                              )
                            """
                        ),
                        {
                            "tables": [
                                "inventory_cost_events",
                                "inventory_cost_allocations",
                            ],
                            "triggers": [
                                "trg_inventory_cost_events_append_only",
                                "trg_inventory_cost_events_truncate_guard",
                                "trg_inventory_cost_allocations_append_only",
                                "trg_inventory_cost_allocations_truncate_guard",
                            ],
                        },
                    )
                ).all()
            }
            await su.rollback()
        guard_ok = (
            "FOR EACH ROW" in trigger_defs.get(
                "trg_inventory_cost_events_append_only", ""
            )
            and "FOR EACH ROW" in trigger_defs.get(
                "trg_inventory_cost_allocations_append_only", ""
            )
            and "FOR EACH STATEMENT" in trigger_defs.get(
                "trg_inventory_cost_events_truncate_guard", ""
            )
            and "FOR EACH STATEMENT" in trigger_defs.get(
                "trg_inventory_cost_allocations_truncate_guard", ""
            )
        )
        record(
            "append-only cost guards are row-exact",
            guard_ok,
            f"triggers={sorted(trigger_defs)}",
        )

        ids = await seed()
        a = ids["a"]
        b = ids["b"]
        a_wh = ids["a_wh"]
        b_wh = ids["b_wh"]
        a_variant = ids["a_variant"]
        b_variant = ids["b_variant"]
        as_of = datetime.fromordinal(ids["as_of_ordinal"]).date()

        # Build one exact sparse row and initialize company summary.
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            await refresh_live_stock_keys(
                app,
                company_id=a,
                keys=[(a_wh, a_variant)],
                computed_for_date=as_of,
            )
            await apply_live_stock_active_variant_delta(
                app,
                company_id=a,
                delta=0,
            )
            await app.commit()

        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, b)
            await refresh_live_stock_keys(
                app,
                company_id=b,
                keys=[(b_wh, b_variant)],
                computed_for_date=as_of,
            )
            await apply_live_stock_active_variant_delta(
                app,
                company_id=b,
                delta=0,
            )
            await app.commit()

        # 1-5: exact projection values and summaries.
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            row = await projection_row(app, a, a_wh, a_variant)
            summary = (
                await app.execute(
                    text(
                        """
                        SELECT alert_count, nonactive_visible_count,
                               projected_row_count, revision
                        FROM inventory_live_stock_warehouse_summaries
                        WHERE company_id=:c AND warehouse_location_id=:w
                        """
                    ),
                    {"c": a, "w": a_wh},
                )
            ).one()
            company_summary = (
                await app.execute(
                    text(
                        """
                        SELECT active_variant_count
                        FROM inventory_live_stock_company_summaries
                        WHERE company_id=:c
                        """
                    ),
                    {"c": a},
                )
            ).scalar_one()
            await app.rollback()

        record("projection row created", row is not None)
        if row is not None:
            record(
                "physical and sellable quantities are exact",
                (
                    int(row.warehouse_on_hand) == 20
                    and int(row.warehouse_reserved) == 2
                    and int(row.warehouse_sellable_on_hand) == 14
                    and int(row.warehouse_sellable_reserved) == 2
                    and int(row.blocked_status_packs) == 3
                    and int(row.damaged_packs) == 1
                    and int(row.vehicle_packs) == 0
                ),
                (
                    f"on_hand={row.warehouse_on_hand} "
                    f"sellable={row.warehouse_sellable_on_hand} "
                    f"blocked={row.blocked_status_packs} "
                    f"damaged={row.damaged_packs}"
                ),
            )
            record(
                "low-stock policy is exact",
                bool(row.has_active_policy)
                and int(row.minimum_quantity) == 12
                and bool(row.is_low_stock),
            )
            record(
                "next time boundary is exact",
                row.next_transition_date == as_of + timedelta(days=2),
                f"next={row.next_transition_date}",
            )
        record(
            "warehouse summary is exact",
            int(summary.alert_count) == 1
            and int(summary.nonactive_visible_count) == 0
            and int(summary.projected_row_count) == 1,
            (
                f"alerts={summary.alert_count} "
                f"nonactive={summary.nonactive_visible_count} "
                f"rows={summary.projected_row_count}"
            ),
        )
        record(
            "company active count is exact",
            int(company_summary) == 1,
            f"active={company_summary}",
        )

        # 6: idempotent recompute must not bump revision.
        revision_before = int(row.revision)
        summary_revision_before = int(summary.revision)
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            await refresh_live_stock_keys(
                app,
                company_id=a,
                keys=[(a_wh, a_variant)],
                computed_for_date=as_of,
            )
            row_after = await projection_row(app, a, a_wh, a_variant)
            summary_revision_after = int(
                (
                    await app.execute(
                        text(
                            """
                            SELECT revision
                            FROM inventory_live_stock_warehouse_summaries
                            WHERE company_id=:c AND warehouse_location_id=:w
                            """
                        ),
                        {"c": a, "w": a_wh},
                    )
                ).scalar_one()
            )
            await app.commit()
        record(
            "recompute is idempotent",
            int(row_after.revision) == revision_before
            and summary_revision_after == summary_revision_before,
            (
                f"row_revision={row_after.revision} "
                f"summary_revision={summary_revision_after}"
            ),
        )

        # 7-8: tenant A must neither read nor write tenant B projection.
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            visible_b = int(
                (
                    await app.execute(
                        text(
                            """
                            SELECT count(*)
                            FROM inventory_live_stock_projection
                            WHERE company_id=:b
                            """
                        ),
                        {"b": b},
                    )
                ).scalar_one()
            )
            cross_write_blocked = False
            try:
                await app.execute(
                    text(
                        """
                        INSERT INTO inventory_live_stock_projection
                            (company_id, warehouse_location_id,
                             product_variant_id, variant_name,
                             lifecycle_status, operational_hold,
                             warehouse_on_hand, warehouse_reserved,
                             warehouse_sellable_on_hand,
                             warehouse_sellable_reserved,
                             blocked_status_packs, recalled_packs,
                             damaged_packs, vehicle_packs,
                             minimum_quantity, has_active_policy,
                             is_low_stock, has_warehouse_presence,
                             has_vehicle_presence, next_transition_date,
                             computed_for_date, revision, updated_at)
                        VALUES
                            (:c, :w, :v, 'forbidden', 'ACTIVE', 'NONE',
                             0, 0, 0, 0, 0, 0, 0, 0,
                             0, true, false, false, false,
                             NULL, :day, 1, NOW())
                        """
                    ),
                    {
                        "c": b,
                        "w": b_wh,
                        "v": ids["b_variant_unprojected"],
                        "day": as_of,
                    },
                )
                await app.flush()
            except Exception:
                cross_write_blocked = True
            finally:
                await app.rollback()
        record("projection RLS read isolation", visible_b == 0, f"visible={visible_b}")
        record("projection RLS write isolation", cross_write_blocked)

        # 9: SCRAP is a valid inventory location but is intentionally
        # outside the warehouse-centric Live Stock projection.
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            scrap_before = await projection_row(
                app,
                a,
                a_wh,
                a_variant,
            )
            await apply_live_stock_balance_impacts(
                app,
                company_id=a,
                impacts=[
                    {
                        "inventory_balance_id": 1,
                        "location_id": ids["a_scrap"],
                        "location_type": "SCRAP",
                        "vehicle_id": None,
                        "product_variant_id": a_variant,
                        "batch_id": ids["a_batch1"],
                        "stock_status": "DISPOSAL_PENDING",
                        "on_hand_before": 0,
                        "on_hand_after": 2,
                        "reserved_before": 0,
                        "reserved_after": 0,
                        "variant_name": "A Variant",
                        "lifecycle_status": "ACTIVE",
                        "operational_hold": "NONE",
                        "expiry_control_mode": "REQUIRED",
                        "batch_is_active": True,
                        "batch_disposition": "RELEASED",
                        "production_date": None,
                        "expiry_date": None,
                    }
                ],
            )
            scrap_after = await projection_row(
                app,
                a,
                a_wh,
                a_variant,
            )
            await app.rollback()
        record(
            "SCRAP impact is accepted and remains outside Live Stock projection",
            scrap_before is not None
            and scrap_after is not None
            and int(scrap_after.revision) == int(scrap_before.revision)
            and scrap_after.warehouse_on_hand == scrap_before.warehouse_on_hand
            and scrap_after.vehicle_packs == scrap_before.vehicle_packs,
            (
                f"revision_before={None if scrap_before is None else scrap_before.revision} "
                f"revision_after={None if scrap_after is None else scrap_after.revision}"
            ),
        )

        # 10: a failed transaction must roll back both truth and projection.
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            meta = await balance_impact_metadata(
                app,
                company_id=a,
                balance_id=ids["a_bal1"],
            )
            after = (
                await app.execute(
                    text(
                        """
                        UPDATE inventory_balances
                        SET on_hand_quantity=on_hand_quantity + 5,
                            last_updated=NOW()
                        WHERE company_id=:c AND id=:id
                        RETURNING on_hand_quantity, reserved_quantity
                        """
                    ),
                    {"c": a, "id": ids["a_bal1"]},
                )
            ).one()
            meta.update(
                {
                    "on_hand_before": int(after.on_hand_quantity) - 5,
                    "on_hand_after": after.on_hand_quantity,
                    "reserved_before": after.reserved_quantity,
                    "reserved_after": after.reserved_quantity,
                }
            )
            await apply_live_stock_balance_impacts(
                app,
                company_id=a,
                impacts=[meta],
            )
            changed_in_tx = await projection_row(app, a, a_wh, a_variant)
            await app.rollback()

        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            rolled_row = await projection_row(app, a, a_wh, a_variant)
            rolled_balance = int(
                (
                    await app.execute(
                        text(
                            "SELECT on_hand_quantity FROM inventory_balances "
                            "WHERE company_id=:c AND id=:id"
                        ),
                        {"c": a, "id": ids["a_bal1"]},
                    )
                ).scalar_one()
            )
            await app.rollback()
        record(
            "rollback restores truth and projection",
            int(changed_in_tx.warehouse_on_hand) == 25
            and int(rolled_row.warehouse_on_hand) == 20
            and rolled_balance == 10,
            (
                f"in_tx={changed_in_tx.warehouse_on_hand} "
                f"after={rolled_row.warehouse_on_hand} "
                f"balance={rolled_balance}"
            ),
        )

        # 10: lifecycle change updates both company and warehouse counters, then rollback.
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            await app.execute(
                text(
                    """
                    UPDATE product_variants
                    SET lifecycle_status='RETIRING',
                        retired_at=NOW(),
                        lifecycle_revision=lifecycle_revision+1,
                        version=version+1,
                        updated_at=NOW()
                    WHERE company_id=:c AND id=:v
                    """
                ),
                {"c": a, "v": a_variant},
            )
            await apply_live_stock_active_variant_delta(
                app, company_id=a, delta=-1
            )
            await refresh_live_stock_variants(
                app,
                company_id=a,
                variant_ids=[a_variant],
                computed_for_date=as_of,
            )
            lifecycle_row = await projection_row(app, a, a_wh, a_variant)
            lifecycle_summary = (
                await app.execute(
                    text(
                        """
                        SELECT alert_count, nonactive_visible_count
                        FROM inventory_live_stock_warehouse_summaries
                        WHERE company_id=:c AND warehouse_location_id=:w
                        """
                    ),
                    {"c": a, "w": a_wh},
                )
            ).one()
            lifecycle_active = int(
                (
                    await app.execute(
                        text(
                            """
                            SELECT active_variant_count
                            FROM inventory_live_stock_company_summaries
                            WHERE company_id=:c
                            """
                        ),
                        {"c": a},
                    )
                ).scalar_one()
            )
            await app.rollback()
        record(
            "lifecycle projection and counters change atomically",
            lifecycle_row.lifecycle_status == "RETIRING"
            and not bool(lifecycle_row.is_low_stock)
            and int(lifecycle_summary.alert_count) == 0
            and int(lifecycle_summary.nonactive_visible_count) == 1
            and lifecycle_active == 0,
        )

        # 11: crossing the stored time boundary recomputes exact sellability.
        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            refreshed = await refresh_due_live_stock_transitions(
                app,
                company_id=a,
                as_of_date=as_of + timedelta(days=2),
                limit=100,
            )
            future_row = await projection_row(app, a, a_wh, a_variant)
            await app.rollback()
        record(
            "time boundary refresh is exact",
            refreshed == 1
            and int(future_row.warehouse_sellable_on_hand) == 20
            and int(future_row.warehouse_sellable_reserved) == 2
            and not bool(future_row.is_low_stock)
            and future_row.next_transition_date == as_of + timedelta(days=3),
            (
                f"refreshed={refreshed} "
                f"sellable={future_row.warehouse_sellable_on_hand} "
                f"next={future_row.next_transition_date}"
            ),
        )

        # 13: concurrent different-batch writes on one projection key must converge.
        ready = 0
        ready_lock = asyncio.Lock()
        both_ready = asyncio.Event()

        async def worker(balance_id: int, new_on_hand: int) -> None:
            nonlocal ready
            async with SessionApp() as app:
                await app.begin()
                await set_tenant(app, a)
                meta = await balance_impact_metadata(
                    app,
                    company_id=a,
                    balance_id=balance_id,
                )
                before = int(
                    (
                        await app.execute(
                            text(
                                """
                                SELECT on_hand_quantity
                                FROM inventory_balances
                                WHERE company_id=:c AND id=:id
                                """
                            ),
                            {"c": a, "id": balance_id},
                        )
                    ).scalar_one()
                )
                after = (
                    await app.execute(
                        text(
                            """
                            UPDATE inventory_balances
                            SET on_hand_quantity=:qty, last_updated=NOW()
                            WHERE company_id=:c AND id=:id
                            RETURNING on_hand_quantity, reserved_quantity
                            """
                        ),
                        {"qty": new_on_hand, "c": a, "id": balance_id},
                    )
                ).one()
                meta.update(
                    {
                        "on_hand_before": before,
                        "on_hand_after": after.on_hand_quantity,
                        "reserved_before": after.reserved_quantity,
                        "reserved_after": after.reserved_quantity,
                    }
                )
                async with ready_lock:
                    ready += 1
                    if ready == 2:
                        both_ready.set()
                await both_ready.wait()
                await apply_live_stock_balance_impacts(
                    app,
                    company_id=a,
                    impacts=[meta],
                )
                await app.commit()

        await asyncio.wait_for(
            asyncio.gather(
                worker(ids["a_bal1"], 11),
                worker(ids["a_bal2"], 6),
            ),
            timeout=30,
        )

        async with SessionApp() as app:
            await app.begin()
            await set_tenant(app, a)
            final_row = await projection_row(app, a, a_wh, a_variant)
            final_truth = int(
                (
                    await app.execute(
                        text(
                            """
                            SELECT COALESCE(SUM(on_hand_quantity), 0)
                            FROM inventory_balances
                            WHERE company_id=:c
                              AND location_id=:w
                              AND product_variant_id=:v
                              AND stock_status='AVAILABLE'
                            """
                        ),
                        {"c": a, "w": a_wh, "v": a_variant},
                    )
                ).scalar_one()
            )
            await app.rollback()
        record(
            "concurrent writes converge to exact projection",
            int(final_row.warehouse_on_hand) == final_truth == 23,
            f"projection={final_row.warehouse_on_hand} truth={final_truth}",
        )

    finally:
        if preclean_ok:
            try:
                removed_after = await cleanup_test_companies()
                record(
                    "runtime gate leaves zero test data behind",
                    True,
                    f"removed_companies={removed_after}",
                )
            except Exception as exc:
                record(
                    "runtime gate leaves zero test data behind",
                    False,
                    str(exc),
                )
        await engine_app.dispose()
        await engine_su.dispose()

    failures = [name for name, ok, _detail in RESULTS if not ok]
    print(f"CHECKS={len(RESULTS)}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAILED_CHECK={failure}")
    if failures:
        print("STAGE821_LIVE_STOCK_PROJECTOR_RUNTIME_GATE=FAIL")
        raise SystemExit(1)
    print("STAGE821_LIVE_STOCK_PROJECTOR_RUNTIME_GATE=PASS")


if __name__ == "__main__":
    asyncio.run(main())
