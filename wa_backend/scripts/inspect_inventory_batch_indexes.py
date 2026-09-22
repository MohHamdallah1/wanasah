from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from sqlalchemy import text


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

from database import engine  # noqa: E402


TABLES = ("product_batches", "inventory_balances")


async def main() -> None:
    async with engine.connect() as conn:
        indexes = (
            await conn.execute(
                text(
                    """
                    SELECT
                        tbl.relname AS table_name,
                        idx.relname AS index_name,
                        i.indisunique AS is_unique,
                        i.indisprimary AS is_primary,
                        i.indisvalid AS is_valid,
                        i.indisready AS is_ready,
                        pg_size_pretty(
                            pg_relation_size(idx.oid)
                        ) AS index_size,
                        pg_get_indexdef(idx.oid) AS index_definition
                    FROM pg_index AS i
                    JOIN pg_class AS idx
                      ON idx.oid = i.indexrelid
                    JOIN pg_class AS tbl
                      ON tbl.oid = i.indrelid
                    JOIN pg_namespace AS ns
                      ON ns.oid = tbl.relnamespace
                    WHERE ns.nspname = current_schema()
                      AND tbl.relname = ANY(:tables)
                    ORDER BY tbl.relname, idx.relname
                    """
                ),
                {"tables": list(TABLES)},
            )
        ).mappings().all()

        constraints = (
            await conn.execute(
                text(
                    """
                    SELECT
                        rel.relname AS table_name,
                        con.conname AS constraint_name,
                        con.contype AS constraint_type,
                        con.convalidated AS is_validated,
                        pg_get_constraintdef(
                            con.oid,
                            true
                        ) AS definition
                    FROM pg_constraint AS con
                    JOIN pg_class AS rel
                      ON rel.oid = con.conrelid
                    JOIN pg_namespace AS ns
                      ON ns.oid = rel.relnamespace
                    WHERE ns.nspname = current_schema()
                      AND rel.relname = ANY(:tables)
                    ORDER BY rel.relname, con.conname
                    """
                ),
                {"tables": list(TABLES)},
            )
        ).mappings().all()

        usage = (
            await conn.execute(
                text(
                    """
                    SELECT
                        relname AS table_name,
                        indexrelname AS index_name,
                        idx_scan,
                        idx_tup_read,
                        idx_tup_fetch
                    FROM pg_stat_user_indexes
                    WHERE schemaname = current_schema()
                      AND relname = ANY(:tables)
                    ORDER BY relname, indexrelname
                    """
                ),
                {"tables": list(TABLES)},
            )
        ).mappings().all()

        table_stats = (
            await conn.execute(
                text(
                    """
                    SELECT
                        relname AS table_name,
                        n_live_tup,
                        n_dead_tup,
                        last_analyze,
                        last_autoanalyze
                    FROM pg_stat_user_tables
                    WHERE schemaname = current_schema()
                      AND relname = ANY(:tables)
                    ORDER BY relname
                    """
                ),
                {"tables": list(TABLES)},
            )
        ).mappings().all()

    print("=== INDEXES ===")
    for row in indexes:
        print(
            f"TABLE={row['table_name']} "
            f"INDEX={row['index_name']} "
            f"unique={row['is_unique']} "
            f"primary={row['is_primary']} "
            f"valid={row['is_valid']} "
            f"ready={row['is_ready']} "
            f"size={row['index_size']}"
        )
        print(f"  DEF={row['index_definition']}")

    print("=== CONSTRAINTS ===")
    for row in constraints:
        print(
            f"TABLE={row['table_name']} "
            f"CONSTRAINT={row['constraint_name']} "
            f"type={row['constraint_type']} "
            f"validated={row['is_validated']}"
        )
        print(f"  DEF={row['definition']}")

    print("=== INDEX USAGE ===")
    for row in usage:
        print(
            f"TABLE={row['table_name']} "
            f"INDEX={row['index_name']} "
            f"scans={row['idx_scan']} "
            f"read={row['idx_tup_read']} "
            f"fetch={row['idx_tup_fetch']}"
        )

    print("=== TABLE STATS ===")
    for row in table_stats:
        print(
            f"TABLE={row['table_name']} "
            f"live={row['n_live_tup']} "
            f"dead={row['n_dead_tup']} "
            f"last_analyze={row['last_analyze']} "
            f"last_autoanalyze={row['last_autoanalyze']}"
        )

    print("INVENTORY_BATCH_INDEX_INSPECTION=PASS")


if __name__ == "__main__":
    asyncio.run(main())
