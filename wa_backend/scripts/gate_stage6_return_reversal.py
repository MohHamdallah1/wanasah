from __future__ import annotations

import asyncio
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

checks = 0
failures: list[str] = []


def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    print(("[PASS] " if condition else "[FAIL] ") + label)
    if not condition:
        failures.append(label)


def static_checks() -> None:
    from domains.sales_returns.service import cumulative_delta

    check(
        cumulative_delta(
            original_amount=Decimal("10.000000"),
            source_quantity=Decimal("3.000000"),
            prior_returned_quantity=Decimal("0"),
            requested_quantity=Decimal("1"),
            prior_reversed_amount=Decimal("0"),
        ) == Decimal("3.333333"),
        "Partial return uses exact cumulative allocation",
    )
    second = cumulative_delta(
        original_amount=Decimal("10.000000"),
        source_quantity=Decimal("3.000000"),
        prior_returned_quantity=Decimal("1"),
        requested_quantity=Decimal("2"),
        prior_reversed_amount=Decimal("3.333333"),
    )
    check(
        second == Decimal("6.666667"),
        "Final cumulative return consumes the exact original residual",
    )

    service = (BACKEND / "domains/sales_returns/service.py").read_text(encoding="utf-8")
    check(
        "domains.pricing" not in service
        and "domains.taxation.resolver" not in service
        and "resolve_driver_sale" not in service,
        "Sales Return never reprices or recalculates current offers/taxes",
    )
    check(
        "Visit.current_sales_revision_id == int(revision_id)" in service
        and "SalesLinePriceComponent" in service
        and "SalesLineAdjustment" in service
        and "SalesLineTaxComponent" in service,
        "Return authority is the current immutable original sale evidence",
    )
    check(
        "load_variant_uom_authorities" in service
        and "validate_step=True" in service,
        "Return quantities are validated against the authoritative product/UOM contract",
    )
    check(
        "pg_advisory_xact_lock" in service
        and service.count("request_id == payload.request_id") >= 2
        and "Re-check idempotency after serializing on the original sale" in service,
        "Return idempotency is serialized tenant-wide and rechecked after the source-sale lock",
    )
    check(
        "Shop.current_balance" not in service
        and '"settlement_status": "UNSETTLED"' in service
        and "document.settlement_status" not in service,
        "Posting a return creates an unsettled credit without mutating customer balance",
    )

    dashboard_page = (ROOT / "dashboard/src/pages/SalesReturnsDashboard.tsx").read_text(
        encoding="utf-8"
    )
    dashboard_semantics = " ".join(dashboard_page.split())
    check(
        (
            "الإشعار الدائن" in dashboard_semantics
            or "إشعار دائن" in dashboard_semantics
        )
        and "لا يتم دفع كاش" in dashboard_semantics
        and "تحويل بنكي" in dashboard_semantics
        and "اختيار عملية بيع" in dashboard_semantics,
        "Dashboard clearly explains return credit versus later refund settlement",
    )


async def database_checks() -> None:
    from database import engine

    heads_cp = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=BACKEND,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    cli_heads = {
        line.split()[0]
        for line in heads_cp.stdout.splitlines()
        if "(head)" in line and line.split()
    }
    check(
        heads_cp.returncode == 0 and len(cli_heads) == 1,
        "Alembic exposes exactly one current head",
    )

    history_cp = subprocess.run(
        [sys.executable, "-m", "alembic", "history", "--verbose"],
        cwd=BACKEND,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    check(
        history_cp.returncode == 0
        and "d2a6c8e4f1b7" in history_cp.stdout,
        "Sales Return migration remains present in the current Alembic lineage",
    )

    tables = (
        "sales_return_documents",
        "sales_return_lines",
        "sales_return_quantity_components",
        "sales_return_adjustments",
        "sales_return_tax_components",
    )

    async with engine.connect() as conn:
        db_heads = set(
            (
                await conn.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalars().all()
        )
        check(
            bool(cli_heads) and db_heads == cli_heads,
            "Database is upgraded to the exact current Alembic head",
        )

        rls_rows = (
            await conn.execute(
                text(
                    """
                    SELECT relname, relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE relname = ANY(:tables)
                    """
                ),
                {"tables": list(tables)},
            )
        ).all()
        rls = {
            str(row.relname): (
                bool(row.relrowsecurity),
                bool(row.relforcerowsecurity),
            )
            for row in rls_rows
        }
        check(
            all(rls.get(table) == (True, True) for table in tables),
            "Every Sales Return table keeps ENABLE + FORCE RLS",
        )

        policies = (
            await conn.execute(
                text(
                    """
                    SELECT tablename, qual, with_check
                    FROM pg_policies
                    WHERE schemaname = current_schema()
                      AND tablename = ANY(:tables)
                    """
                ),
                {"tables": list(tables)},
            )
        ).all()
        policy_map = {
            str(row.tablename): (
                str(row.qual or ""),
                str(row.with_check or ""),
            )
            for row in policies
        }
        check(
            all(
                table in policy_map
                and "app.current_tenant" in policy_map[table][0]
                and "company_id" in policy_map[table][0]
                and "app.current_tenant" in policy_map[table][1]
                and "company_id" in policy_map[table][1]
                for table in tables
            ),
            "Sales Return tenant policies enforce USING + WITH CHECK",
        )

        constraints = (
            await conn.execute(
                text(
                    """
                    SELECT
                        cls.relname AS table_name,
                        c.contype::text AS constraint_type,
                        pg_get_constraintdef(c.oid, true) AS definition
                    FROM pg_constraint c
                    JOIN pg_class cls ON cls.oid = c.conrelid
                    WHERE cls.relname = ANY(:tables)
                    """
                ),
                {"tables": list(tables)},
            )
        ).all()
        definitions = [
            (str(row.table_name), str(row.constraint_type), str(row.definition))
            for row in constraints
        ]
        required = (
            ("sales_return_documents", "FOREIGN KEY (company_id, original_visit_id, original_sales_revision_id)"),
            ("sales_return_lines", "FOREIGN KEY (company_id, original_visit_item_id)"),
            ("sales_return_quantity_components", "FOREIGN KEY (company_id, original_price_component_id)"),
            ("sales_return_adjustments", "FOREIGN KEY (company_id, original_adjustment_id)"),
            ("sales_return_tax_components", "FOREIGN KEY (company_id, original_tax_component_id)"),
        )
        check(
            all(
                any(
                    table == expected_table
                    and ctype == "f"
                    and fragment in definition
                    for table, ctype, definition in definitions
                )
                for expected_table, fragment in required
            ),
            "Return evidence is tenant-bound to every original evidence source",
        )

        trigger_rows = (
            await conn.execute(
                text(
                    """
                    SELECT c.relname AS table_name, t.tgname, t.tgdeferrable, t.tginitdeferred
                    FROM pg_trigger t
                    JOIN pg_class c ON c.oid = t.tgrelid
                    WHERE NOT t.tgisinternal
                      AND c.relname = ANY(:tables)
                    """
                ),
                {"tables": list(tables)},
            )
        ).all()
        trigger_map = {
            (str(row.table_name), str(row.tgname)): (
                bool(row.tgdeferrable),
                bool(row.tginitdeferred),
            )
            for row in trigger_rows
        }
        check(
            all(
                (table, f"trg_{table}_immutable") in trigger_map
                for table in tables
            ),
            "Posted Sales Return evidence is DB-immutable",
        )
        check(
            all(
                trigger_map.get((table, f"trg_{table}_reconcile")) == (True, True)
                for table in tables
            ),
            "Every return layer participates in deferred commit reconciliation",
        )

        validator = await conn.scalar(
            text(
                """
                SELECT pg_get_functiondef(p.oid)
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = current_schema()
                  AND p.proname = 'validate_sales_return_document'
                """
            )
        )
        validator = str(validator or "")
        check(
            "cumulative returned quantity exceeds original sold quantity" in validator
            and "sales return header credit does not reconcile" in validator
            and "cumulative return credit exceeds original sale final amount" in validator
            and "cumulative return quantity reversal does not match original price evidence" in validator
            and "cumulative adjustment reversal does not match original offer evidence" in validator
            and "cumulative tax reversal does not match original tax evidence" in validator
            and "original_sales_revision_id" in validator,
            "DB validator caps and exactly reconciles cumulative reversal against original evidence",
        )

        source_trigger_rows = (
            await conn.execute(
                text(
                    """
                    SELECT c.relname AS table_name, t.tgname
                    FROM pg_trigger t
                    JOIN pg_class c ON c.oid = t.tgrelid
                    WHERE NOT t.tgisinternal
                      AND (
                          (c.relname = 'visits'
                           AND t.tgname = 'trg_visit_sales_return_source_guard')
                          OR
                          (c.relname = 'visit_items'
                           AND t.tgname = 'trg_visit_item_sales_return_source_guard')
                      )
                    """
                )
            )
        ).all()
        source_trigger_set = {
            (str(row.table_name), str(row.tgname))
            for row in source_trigger_rows
        }
        check(
            ("visits", "trg_visit_sales_return_source_guard") in source_trigger_set
            and (
                "visit_items",
                "trg_visit_item_sales_return_source_guard",
            ) in source_trigger_set,
            "Posted returns freeze their original Visit authority and source sale lines",
        )

    await engine.dispose()


def main() -> int:
    try:
        static_checks()
        asyncio.run(database_checks())
    except Exception as exc:
        check(False, "Return reversal gate completed without unexpected exception")
        print(f"UNEXPECTED_EXCEPTION={exc!r}")

    print()
    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL: {failure}")

    if failures:
        print("STAGE6_RETURN_REVERSAL_GATE=FAIL")
        return 1

    print("STAGE6_RETURN_REVERSAL_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
