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


def domain_checks() -> None:
    from domains.offers.contracts import (
        BasketLine,
        BasketPriceComponent,
        OfferCandidate,
        ProductTargetRef,
    )
    from domains.offers.engine import calculate_offers

    line = BasketLine(
        line_id=1,
        product_variant_id=101,
        base_uom_id=1,
        quantity=Decimal("3"),
        price_components=(
            BasketPriceComponent(
                uom_id=1,
                quantity=Decimal("1"),
                base_quantity=Decimal("1"),
                unit_price=Decimal("10"),
                price_entry_id=1,
                price_publication_revision=1,
                assignment_revision=1,
            ),
            BasketPriceComponent(
                uom_id=2,
                quantity=Decimal("1"),
                base_quantity=Decimal("2"),
                unit_price=Decimal("20"),
                price_entry_id=2,
                price_publication_revision=1,
                assignment_revision=1,
            ),
        ),
    )
    candidate = OfferCandidate(
        version_id=11,
        definition_id=21,
        revision=31,
        offer_type="PERCENTAGE_DISCOUNT",
        priority=10,
        stacking_mode="STACKABLE",
        payload={"percentage": "10"},
        product_targets=(
            ProductTargetRef(
                product_variant_id=101,
                uom_id=None,
            ),
        ),
        products=(),
    )
    result = calculate_offers(
        lines=(line,),
        candidates=(candidate,),
        catalog_prices={},
    )
    adjustments = tuple(result.adjustments)
    check(
        len(adjustments) == 2
        and {row.sequence for row in adjustments} == {1}
        and {row.uom_id for row in adjustments} == {1, 2},
        "Mixed-UOM offer legitimately emits same-sequence adjustments per UOM",
    )

    service = (
        BACKEND / "domains/sales_evidence/service.py"
    ).read_text(encoding="utf-8")
    check(
        "unrounded_basis_amount" in service
        and "unrounded_adjustment_amount" in service
        and "target_uom_id" in service,
        "Adjustment evidence preserves raw basis/amount and target UOM",
    )
    check(
        '"unrounded_basis_amount": component.unrounded_basis_amount'
        in service
        and '"unrounded_tax_amount": component.unrounded_tax_amount'
        in service,
        "Tax evidence preserves raw basis and tax calculation amounts",
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

    tables = (
        "sales_line_adjustments",
        "sales_line_tax_components",
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
            "Adjustment/tax evidence tables keep ENABLE + FORCE RLS",
        )

        policy_rows = (
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
        policy_map: dict[str, list[tuple[str, str]]] = {}
        for row in policy_rows:
            policy_map.setdefault(
                str(row.tablename),
                [],
            ).append(
                (
                    str(row.qual or ""),
                    str(row.with_check or ""),
                )
            )
        check(
            all(
                any(
                    "app.current_tenant" in qual
                    and "company_id" in qual
                    and "app.current_tenant" in with_check
                    and "company_id" in with_check
                    for qual, with_check in policy_map.get(table, [])
                )
                for table in tables
            ),
            "Typed line evidence policies enforce tenant USING + WITH CHECK",
        )

        constraint_rows = (
            await conn.execute(
                text(
                    """
                    SELECT
                        cls.relname AS table_name,
                        c.conname,
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
        defs = {
            (str(row.table_name), str(row.conname)): (
                str(row.constraint_type),
                str(row.definition),
            )
            for row in constraint_rows
        }

        check(
            any(
                table == "sales_line_adjustments"
                and name == "uq_sales_line_adjustment_sequence_uom"
                and constraint_type == "u"
                and "company_id" in definition
                and "visit_item_id" in definition
                and "sequence" in definition
                and "uom_id" in definition
                for (table, name), (
                    constraint_type,
                    definition,
                ) in defs.items()
            ),
            "Adjustment uniqueness represents same offer sequence across multiple UOMs",
        )

        required_fk_fragments = (
            (
                "sales_line_adjustments",
                "FOREIGN KEY (company_id, visit_item_id)",
            ),
            (
                "sales_line_adjustments",
                "FOREIGN KEY (company_id, offer_version_id, rule_id)",
            ),
            (
                "sales_line_tax_components",
                "FOREIGN KEY (company_id, visit_item_id)",
            ),
            (
                "sales_line_tax_components",
                "FOREIGN KEY (company_id, tax_rule_set_version_id, tax_rule_set_id)",
            ),
            (
                "sales_line_tax_components",
                "FOREIGN KEY (company_id, tax_component_id, tax_rule_set_version_id)",
            ),
            (
                "sales_line_tax_components",
                "FOREIGN KEY (company_id, matched_jurisdiction_id)",
            ),
        )
        check(
            all(
                any(
                    table == expected_table
                    and constraint_type == "f"
                    and fragment in definition
                    for (table, _), (
                        constraint_type,
                        definition,
                    ) in defs.items()
                )
                for expected_table, fragment in required_fk_fragments
            ),
            "Typed adjustment/tax references are tenant-bound by composite FKs",
        )

        check(
            any(
                table == "sales_line_tax_components"
                and constraint_type == "c"
                and "matched_jurisdiction_id" in definition
                and "jurisdiction_distance" in definition
                and "IS NULL" in definition
                and "IS NOT NULL" in definition
                for (table, _name), (
                    constraint_type,
                    definition,
                ) in defs.items()
            ),
            "Tax evidence enforces coherent matched-jurisdiction shape",
        )

        trigger_rows = (
            await conn.execute(
                text(
                    """
                    SELECT c.relname AS table_name,
                           t.tgname,
                           t.tgdeferrable,
                           t.tginitdeferred
                    FROM pg_trigger t
                    JOIN pg_class c ON c.oid = t.tgrelid
                    WHERE NOT t.tgisinternal
                      AND c.relname = ANY(:tables)
                    """
                ),
                {
                    "tables": [
                        "sales_line_adjustments",
                        "sales_line_tax_components",
                        "visit_items",
                    ]
                },
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
            (
                "sales_line_adjustments",
                "trg_sales_line_adjustment_insert_only",
            ) in trigger_map
            and (
                "sales_line_tax_components",
                "trg_sales_line_tax_component_insert_only",
            ) in trigger_map,
            "Typed line evidence remains insert-only",
        )
        check(
            trigger_map.get(
                (
                    "sales_line_adjustments",
                    "trg_sales_line_adjustment_parent_frozen",
                )
            ) == (True, True)
            and trigger_map.get(
                (
                    "sales_line_tax_components",
                    "trg_sales_line_tax_component_parent_frozen",
                )
            ) == (True, True)
            and trigger_map.get(
                (
                    "visit_items",
                    "trg_visit_item_evidence_reconcile",
                )
            ) == (True, True),
            "Parent freeze and line reconciliation remain deferred commit gates",
        )

        fn = await conn.scalar(
            text(
                """
                SELECT pg_get_functiondef(p.oid)
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = current_schema()
                  AND p.proname = 'validate_frozen_visit_item_evidence'
                """
            )
        )
        definition = str(fn or "")
        markers = (
            "typed adjustment semantics do not match immutable offer evidence",
            "typed adjustments do not match line offer snapshot",
            "one sales line must use one coherent tax resolution",
            "typed tax semantics do not match immutable tax configuration",
            "typed tax evidence does not match line tax snapshot",
            "offer_revision_ceiling",
            "tax_revision_ceiling",
            "sales_line_price_components",
        )
        check(
            all(marker in definition for marker in markers),
            "Deferred line validator enforces source semantics, ceilings and snapshots",
        )

        company_ids = list(
            (
                await conn.execute(
                    text("SELECT id FROM companies ORDER BY id")
                )
            ).scalars().all()
        )
        current_data_ok = True
        for company_id in company_ids:
            await conn.execute(
                text(
                    """
                    SELECT set_config(
                        'app.current_tenant',
                        :tenant_id,
                        true
                    )
                    """
                ),
                {"tenant_id": str(int(company_id))},
            )

            adjustment_mismatch = await conn.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM sales_line_adjustments a
                        JOIN visit_items i
                          ON i.company_id = a.company_id
                         AND i.id = a.visit_item_id
                        JOIN sales_visit_revisions r
                          ON r.company_id = i.company_id
                         AND r.visit_id = i.visit_id
                         AND r.id = i.sales_revision_id
                        JOIN offer_versions o
                          ON o.company_id = a.company_id
                         AND o.id = a.offer_version_id
                         AND o.offer_definition_id = a.rule_id
                        WHERE a.company_id = :company_id
                          AND (
                              a.rule_version IS DISTINCT FROM o.revision
                              OR a.rule_type IS DISTINCT FROM o.offer_type
                              OR o.revision > r.offer_revision_ceiling
                              OR NOT EXISTS (
                                  SELECT 1
                                  FROM sales_line_price_components pc
                                  WHERE pc.company_id = a.company_id
                                    AND pc.visit_item_id = a.visit_item_id
                                    AND pc.uom_id = a.uom_id
                              )
                          )
                    )
                    """
                ),
                {"company_id": int(company_id)},
            )
            tax_mismatch = await conn.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM sales_line_tax_components e
                        JOIN visit_items i
                          ON i.company_id = e.company_id
                         AND i.id = e.visit_item_id
                        JOIN sales_visit_revisions r
                          ON r.company_id = i.company_id
                         AND r.visit_id = i.visit_id
                         AND r.id = i.sales_revision_id
                        JOIN tax_rule_set_versions v
                          ON v.company_id = e.company_id
                         AND v.id = e.tax_rule_set_version_id
                         AND v.tax_rule_set_id = e.tax_rule_set_id
                        JOIN tax_rule_components c
                          ON c.company_id = e.company_id
                         AND c.id = e.tax_component_id
                         AND c.tax_rule_set_version_id = e.tax_rule_set_version_id
                        WHERE e.company_id = :company_id
                          AND (
                              e.tax_revision IS DISTINCT FROM v.revision
                              OR e.sequence IS DISTINCT FROM c.sequence
                              OR e.component_code IS DISTINCT FROM c.component_code
                              OR e.tax_name IS DISTINCT FROM c.name
                              OR e.rate IS DISTINCT FROM c.rate
                              OR e.basis_mode IS DISTINCT FROM c.basis_mode
                              OR e.reporting_code IS DISTINCT FROM c.reporting_code
                              OR v.revision > r.tax_revision_ceiling
                          )
                    )
                    """
                ),
                {"company_id": int(company_id)},
            )
            if bool(adjustment_mismatch) or bool(tax_mismatch):
                current_data_ok = False
                break

        await conn.execute(
            text(
                "SELECT set_config('app.current_tenant', '', true)"
            )
        )
        check(
            current_data_ok,
            "Existing typed line evidence matches immutable source authorities",
        )

    await engine.dispose()


def main() -> int:
    try:
        domain_checks()
        asyncio.run(database_checks())
    except Exception as exc:
        check(False, "Sales line evidence gate completed without unexpected exception")
        print(f"UNEXPECTED_EXCEPTION={exc!r}")

    print()
    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL: {failure}")

    if failures:
        print("STAGE6_SALES_LINE_EVIDENCE_GATE=FAIL")
        return 1

    print("STAGE6_SALES_LINE_EVIDENCE_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
