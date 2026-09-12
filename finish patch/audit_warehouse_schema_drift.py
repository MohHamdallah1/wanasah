from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import inspect

ROOT = Path.cwd()
BACKEND = ROOT / "wa_backend"

if not BACKEND.is_dir():
    raise SystemExit("ERROR: شغّل السكربت من جذر مشروع wanasah.")

sys.path.insert(0, str(BACKEND))

from database import engine
from models import Base


CRITICAL_TABLES = [
    "dispatch_routes",
    "product_batches",
    "inventory_locations",
    "inventory_stock_policies",
    "inventory_balances",
    "inventory_movements",
    "inventory_movement_impacts",
    "inventory_transfer_headers",
    "inventory_transfer_lines",
    "stocktake_sessions",
    "stocktake_lines",
    "stocktake_count_attempts",
    "stocktake_count_attempt_lines",
    "inventory_locks",
]


def _model_named_indexes(table):
    return {
        idx.name
        for idx in table.indexes
        if idx.name
    }


def _model_named_uniques(table):
    return {
        constraint.name
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
        and constraint.name
    }


def _model_named_fks(table):
    return {
        constraint.name
        for constraint in table.constraints
        if constraint.__class__.__name__ == "ForeignKeyConstraint"
        and constraint.name
    }


def _model_named_checks(table, dialect):
    preparer = dialect.identifier_preparer
    return {
        preparer.format_constraint(constraint)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
        and constraint.name
    }


def audit_sync(sync_conn):
    inspector = inspect(sync_conn)
    db_tables = set(inspector.get_table_names())

    problems = []
    details = []

    for table_name in CRITICAL_TABLES:
        if table_name not in Base.metadata.tables:
            problems.append(f"[MODEL] missing critical table metadata: {table_name}")
            continue

        model_table = Base.metadata.tables[table_name]

        if table_name not in db_tables:
            problems.append(f"[DB] missing table: {table_name}")
            continue

        # -------------------------
        # Columns
        # -------------------------
        db_columns = {
            col["name"]: col
            for col in inspector.get_columns(table_name)
        }
        model_columns = {
            col.name: col
            for col in model_table.columns
        }

        missing_columns = sorted(set(model_columns) - set(db_columns))
        extra_columns = sorted(set(db_columns) - set(model_columns))

        if missing_columns:
            problems.append(
                f"[DB] {table_name}: missing columns: {', '.join(missing_columns)}"
            )

        if extra_columns:
            details.append(
                f"[INFO] {table_name}: DB-only columns: {', '.join(extra_columns)}"
            )

        # Nullable mismatch only when the column exists in both.
        for col_name in sorted(set(model_columns) & set(db_columns)):
            model_nullable = bool(model_columns[col_name].nullable)
            db_nullable = bool(db_columns[col_name].get("nullable", True))
            if model_nullable != db_nullable:
                problems.append(
                    f"[DB] {table_name}.{col_name}: nullable mismatch "
                    f"(model={model_nullable}, db={db_nullable})"
                )

        # -------------------------
        # Named indexes
        # -------------------------
        db_indexes = {
            idx.get("name")
            for idx in inspector.get_indexes(table_name)
            if idx.get("name")
        }
        model_indexes = _model_named_indexes(model_table)

        missing_indexes = sorted(model_indexes - db_indexes)
        if missing_indexes:
            problems.append(
                f"[DB] {table_name}: missing indexes: {', '.join(missing_indexes)}"
            )

        # -------------------------
        # Named UNIQUE constraints
        # -------------------------
        db_uniques = {
            item.get("name")
            for item in inspector.get_unique_constraints(table_name)
            if item.get("name")
        }
        model_uniques = _model_named_uniques(model_table)

        missing_uniques = sorted(model_uniques - db_uniques)
        if missing_uniques:
            problems.append(
                f"[DB] {table_name}: missing UNIQUE constraints: "
                f"{', '.join(missing_uniques)}"
            )

        # -------------------------
        # Named foreign keys
        # -------------------------
        db_fks = {
            item.get("name")
            for item in inspector.get_foreign_keys(table_name)
            if item.get("name")
        }
        model_fks = _model_named_fks(model_table)

        missing_fks = sorted(model_fks - db_fks)
        if missing_fks:
            problems.append(
                f"[DB] {table_name}: missing FK constraints: "
                f"{', '.join(missing_fks)}"
            )

        # -------------------------
        # Named CHECK constraints
        # -------------------------
        try:
            db_checks = {
                item.get("name")
                for item in inspector.get_check_constraints(table_name)
                if item.get("name")
            }
        except NotImplementedError:
            db_checks = set()

        model_checks = _model_named_checks(model_table, sync_conn.dialect)

        missing_checks = sorted(model_checks - db_checks)
        if missing_checks:
            problems.append(
                f"[DB] {table_name}: missing CHECK constraints: "
                f"{', '.join(missing_checks)}"
            )

    # Alembic state is diagnostic only.
    if "alembic_version" in db_tables:
        try:
            versions = sync_conn.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).fetchall()
            details.append(
                "[INFO] alembic_version: "
                + (", ".join(str(row[0]) for row in versions) if versions else "EMPTY")
            )
        except Exception as exc:
            details.append(f"[INFO] alembic_version unreadable: {exc}")
    else:
        details.append("[INFO] alembic_version table: NOT PRESENT")

    return problems, details


async def main():
    if engine.dialect.name != "postgresql":
        raise SystemExit("POSTGRESQL_REQUIRED_FOR_SCHEMA_DRIFT_AUDIT")

    async with engine.connect() as conn:
        problems, details = await conn.run_sync(audit_sync)

    print("WAREHOUSE_SCHEMA_DRIFT_AUDIT")
    for line in details:
        print(line)

    if problems:
        print(f"STATUS=DRIFT_FOUND ({len(problems)} issue groups)")
        for line in problems:
            print(line)
        raise SystemExit(2)

    print("STATUS=WAREHOUSE_SCHEMA_MATCH_OK")


async def _run():
    try:
        await main()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
