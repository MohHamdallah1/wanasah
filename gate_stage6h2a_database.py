from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "wa_backend"))

from database import engine


EXPECTED_DB_HEAD = "c3f8a1d6e2b4"
checks = 0
failures: list[str] = []


def check(ok: bool, label: str) -> None:
    global checks
    checks += 1
    print(("  [PASS] " if ok else "  [FAIL] ") + label)
    if not ok:
        failures.append(label)


async def main() -> int:
    async with engine.connect() as conn:
        current = await conn.scalar(text("SELECT version_num FROM alembic_version"))
        check(
            str(current) == EXPECTED_DB_HEAD,
            "Database Alembic head is exactly Stage 6H.2A",
        )

        rows = (
            await conn.execute(
                text(
                    """
                    SELECT table_name, column_name, is_nullable, data_type
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND (
                        (table_name = 'offer_version_scopes'
                         AND column_name = 'uom_id')
                        OR
                        (table_name = 'offer_version_products'
                         AND column_name IN ('uom_id', 'quantity_per_application'))
                      )
                    ORDER BY table_name, column_name
                    """
                )
            )
        ).all()
        columns = {
            (str(row.table_name), str(row.column_name)):
            (str(row.is_nullable), str(row.data_type))
            for row in rows
        }
        check(
            columns.get(("offer_version_scopes", "uom_id")) == ("YES", "integer"),
            "Offer product scope supports optional explicit UOM",
        )
        check(
            columns.get(("offer_version_products", "uom_id")) == ("NO", "integer"),
            "Offer product term requires explicit UOM",
        )
        check(
            columns.get(
                ("offer_version_products", "quantity_per_application")
            ) == ("YES", "numeric"),
            "Offer product term stores typed quantity_per_application",
        )

        constraints = (
            await conn.execute(
                text(
                    """
                    SELECT
                        cls.relname AS table_name,
                        c.contype::text AS contype,
                        pg_get_constraintdef(c.oid, true) AS definition
                    FROM pg_constraint AS c
                    JOIN pg_class AS cls ON cls.oid = c.conrelid
                    WHERE cls.relname IN (
                        'offer_version_scopes',
                        'offer_version_products'
                    )
                    ORDER BY cls.relname, c.conname
                    """
                )
            )
        ).all()
        by_table: dict[str, list[tuple[str, str]]] = {}
        for row in constraints:
            by_table.setdefault(str(row.table_name), []).append(
                (str(row.contype), str(row.definition))
            )

        product_defs = [
            definition
            for ctype, definition in by_table.get("offer_version_products", [])
            if ctype in {"c", "f", "u"}
        ]
        scope_defs = [
            definition
            for ctype, definition in by_table.get("offer_version_scopes", [])
            if ctype in {"c", "f", "u"}
        ]
        check(
            any(
                "FOREIGN KEY (uom_id)" in definition
                and "REFERENCES uom(id)" in definition
                for definition in product_defs
            ),
            "Offer product UOM has DB foreign-key authority",
        )
        check(
            any(
                "FOREIGN KEY (uom_id)" in definition
                and "REFERENCES uom(id)" in definition
                for definition in scope_defs
            ),
            "Offer scope UOM has DB foreign-key authority",
        )
        check(
            any(
                "quantity_per_application" in definition
                and "REWARD" in definition
                and "BUNDLE_COMPONENT" in definition
                for definition in product_defs
            ),
            "DB enforces qualifying/reward/bundle quantity shape",
        )

        indexes = (
            await conn.execute(
                text(
                    """
                    SELECT tablename, indexname, indexdef
                    FROM pg_indexes
                    WHERE schemaname = current_schema()
                      AND tablename IN (
                        'offer_version_scopes',
                        'offer_version_products'
                      )
                    """
                )
            )
        ).all()
        index_map = {
            str(row.indexname): str(row.indexdef)
            for row in indexes
        }
        check(
            "uq_offer_scope_product_all_uom" in index_map
            and "uom_id IS NULL" in index_map["uq_offer_scope_product_all_uom"],
            "All-UOM product scope uniqueness is explicit",
        )
        check(
            "uq_offer_scope_product_specific_uom" in index_map
            and "uom_id IS NOT NULL"
            in index_map["uq_offer_scope_product_specific_uom"],
            "UOM-specific product scope uniqueness is explicit",
        )

        rls_rows = (
            await conn.execute(
                text(
                    """
                    SELECT relname, relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE relname IN (
                        'offer_version_scopes',
                        'offer_version_products'
                    )
                    """
                )
            )
        ).all()
        rls = {
            str(row.relname):
            (bool(row.relrowsecurity), bool(row.relforcerowsecurity))
            for row in rls_rows
        }
        for table in ("offer_version_scopes", "offer_version_products"):
            check(
                rls.get(table) == (True, True),
                f"{table} keeps ENABLE + FORCE RLS",
            )

        version_count = int(
            await conn.scalar(text("SELECT count(*) FROM offer_versions")) or 0
        )
        check(
            version_count == 0,
            "Clean-cut migration did not invent/backfill OfferVersion history",
        )

    await engine.dispose()

    print()
    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL: {failure}")
    print(
        "STAGE6H2A_DATABASE_GATE="
        + ("PASS" if not failures else "FAIL")
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
