from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


def _backend_root() -> Path:
    here = Path(__file__).resolve()
    candidates = (Path.cwd() / "wa_backend", here.parent.parent, here.parent)
    for candidate in candidates:
        if (candidate / "models.py").is_file() and (candidate / ".env").is_file():
            return candidate.resolve()
    raise RuntimeError("wa_backend not found. Run from repository root.")


BACKEND_ROOT = _backend_root()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env", override=False)

from models import (  # noqa: E402
    InventoryLiveStockCompanySummary,
    InventoryLiveStockProjection,
    InventoryLiveStockWarehouseSummary,
)

EXPECTED_REVISION = "b3e91c7a4d20"
EXPECTED_TABLES = (
    "inventory_live_stock_company_summaries",
    "inventory_live_stock_warehouse_summaries",
    "inventory_live_stock_projection",
)
EXPECTED_INDEXES = {
    "ix_live_stock_projection_alert_seek",
    "ix_live_stock_projection_nonactive_seek",
    "ix_live_stock_projection_transition",
    "ix_live_stock_projection_variant",
}
EXPECTED_CONSTRAINTS = {
    "inventory_live_stock_warehouse_summaries": {
        "fk_live_stock_warehouse_summary_location",
        "chk_live_stock_warehouse_alert_within_rows",
        "chk_live_stock_warehouse_nonactive_within_rows",
    },
    "inventory_live_stock_projection": {
        "fk_live_stock_projection_location",
        "fk_live_stock_projection_variant",
        "chk_live_stock_projection_warehouse_presence",
        "chk_live_stock_projection_vehicle_presence",
        "chk_live_stock_projection_recalled_within_blocked",
        "chk_live_stock_projection_policy_minimum_consistency",
        "chk_live_stock_projection_sparse_reason",
        "chk_live_stock_projection_alert_exact",
        "chk_live_stock_projection_transition_after_compute",
    },
}


def _migration_url() -> str:
    raw = os.getenv("DATABASE_URL_MIGRATION")
    if not raw:
        raise RuntimeError("DATABASE_URL_MIGRATION is missing from wa_backend/.env")
    if raw.startswith("postgres://"):
        return raw.replace("postgres://", "postgresql+asyncpg://", 1)
    if raw.startswith("postgresql://") and "asyncpg" not in raw:
        return raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw


def _runtime_role() -> str:
    raw = os.getenv("DATABASE_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL is missing from wa_backend/.env")
    role = make_url(raw).username
    if not role or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", role):
        raise RuntimeError("Runtime database role could not be resolved safely.")
    return role


async def main() -> None:
    checks = 0
    failures: list[str] = []

    model_tables = {
        InventoryLiveStockCompanySummary.__table__.name,
        InventoryLiveStockWarehouseSummary.__table__.name,
        InventoryLiveStockProjection.__table__.name,
    }
    checks += 1
    if model_tables != set(EXPECTED_TABLES):
        failures.append(f"MODEL_TABLES:{sorted(model_tables)}")

    projection_pk = [
        column.name for column in InventoryLiveStockProjection.__table__.primary_key.columns
    ]
    checks += 1
    if projection_pk != ["company_id", "warehouse_location_id", "product_variant_id"]:
        failures.append(f"PROJECTION_PK:{projection_pk}")

    model_indexes = {index.name for index in InventoryLiveStockProjection.__table__.indexes}
    checks += 1
    if not EXPECTED_INDEXES.issubset(model_indexes):
        failures.append(f"MODEL_INDEXES:{sorted(model_indexes)}")

    engine = create_async_engine(_migration_url(), echo=False)
    try:
        async with engine.connect() as conn:
            revision = await conn.scalar(text("SELECT version_num FROM alembic_version"))
            checks += 1
            if str(revision) != EXPECTED_REVISION:
                failures.append(f"ALEMBIC_HEAD:{revision}")

            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = current_schema()
                          AND c.relname IN (
                              'inventory_live_stock_company_summaries',
                              'inventory_live_stock_warehouse_summaries',
                              'inventory_live_stock_projection'
                          )
                        ORDER BY c.relname
                        """
                    )
                )
            ).all()
            checks += 1
            if len(rows) != len(EXPECTED_TABLES):
                failures.append(f"TABLE_COUNT:{len(rows)}")
            for relname, rls, force_rls in rows:
                checks += 1
                if not bool(rls) or not bool(force_rls):
                    failures.append(f"RLS:{relname}:{rls}:{force_rls}")

            policies = set(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT tablename
                            FROM pg_policies
                            WHERE schemaname = current_schema()
                              AND tablename IN (
                                  'inventory_live_stock_company_summaries',
                                  'inventory_live_stock_warehouse_summaries',
                                  'inventory_live_stock_projection'
                              )
                              AND policyname = tablename || '_company_isolation'
                            """
                        )
                    )
                ).scalars().all()
            )
            checks += 1
            if policies != set(EXPECTED_TABLES):
                failures.append(f"POLICIES:{sorted(policies)}")

            indexes = set(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT indexname
                            FROM pg_indexes
                            WHERE schemaname = current_schema()
                              AND tablename = 'inventory_live_stock_projection'
                            """
                        )
                    )
                ).scalars().all()
            )
            checks += 1
            if not EXPECTED_INDEXES.issubset(indexes):
                failures.append(f"DB_INDEXES:{sorted(indexes)}")

            for table_name, required_constraints in EXPECTED_CONSTRAINTS.items():
                constraint_names = set(
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT conname
                                FROM pg_constraint
                                WHERE conrelid = to_regclass(:table_name)
                                """
                            ),
                            {"table_name": table_name},
                        )
                    ).scalars().all()
                )
                checks += 1
                if not required_constraints.issubset(constraint_names):
                    failures.append(
                        f"DB_CONSTRAINTS:{table_name}:{sorted(constraint_names)}"
                    )

            role = _runtime_role()
            for table in EXPECTED_TABLES:
                privileges = {}
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    value = await conn.scalar(
                        text("SELECT has_table_privilege(:role, :table_name, :privilege)"),
                        {"role": role, "table_name": table, "privilege": privilege},
                    )
                    privileges[privilege] = bool(value)
                checks += 1
                if not all(privileges[p] for p in ("SELECT", "INSERT", "UPDATE", "DELETE")):
                    failures.append(f"RUNTIME_PRIVILEGES:{table}:{privileges}")
                if privileges["TRUNCATE"]:
                    failures.append(f"RUNTIME_TRUNCATE:{table}")

                public_select = await conn.scalar(
                    text("SELECT has_table_privilege('public', :table_name, 'SELECT')"),
                    {"table_name": table},
                )
                checks += 1
                if bool(public_select):
                    failures.append(f"PUBLIC_SELECT:{table}")
    finally:
        await engine.dispose()

    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        raise SystemExit(1)
    print("STAGE82_LIVE_STOCK_PROJECTION_FOUNDATION=PASS")


if __name__ == "__main__":
    asyncio.run(main())
