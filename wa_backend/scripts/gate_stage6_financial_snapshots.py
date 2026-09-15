from __future__ import annotations

import asyncio
import subprocess
import sys
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
    service = (
        BACKEND / "domains/sales_evidence/service.py"
    ).read_text(encoding="utf-8")
    models = (
        BACKEND / "domains/sales_evidence/models.py"
    ).read_text(encoding="utf-8")

    check(
        ".with_for_update()" in service
        and "SALES_EVIDENCE_CURRENT_REVISION_EXISTS" in service,
        "Sales evidence freezes under a locked Visit and rejects an existing current revision",
    )
    check(
        "previous_revision" in service
        and "supersedes_revision_id=previous_revision_id" in service
        and "revision_number=next_revision_number" in service,
        "Service appends explicit correction revision lineage",
    )
    check(
        "_validate_commercial_context(" in service
        and "SALES_EVIDENCE_CONTEXT_MISMATCH" in service
        and "SALES_EVIDENCE_FUNCTIONAL_CURRENCY_MISMATCH" in service,
        "Service validates immutable commercial context before freezing evidence",
    )
    check(
        'name="sales_visit_revision_chain_shape"' in models,
        "ORM declares financial revision chain shape",
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
        "sales_visit_revisions",
        "sales_reward_evidence",
        "sales_line_price_components",
        "visits",
        "visit_items",
        "route_commercial_contexts",
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
            "Financial snapshot and parent tables keep ENABLE + FORCE RLS",
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
            "Financial snapshot RLS policies enforce tenant USING + WITH CHECK",
        )

        constraints = (
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
                    WHERE cls.relname = 'sales_visit_revisions'
                    """
                )
            )
        ).all()
        check(
            any(
                str(row.constraint_type) == "c"
                and "revision_number = 1" in str(row.definition)
                and "supersedes_revision_id IS NULL" in str(row.definition)
                and "revision_number > 1" in str(row.definition)
                and "supersedes_revision_id IS NOT NULL" in str(row.definition)
                for row in constraints
            ),
            "DB enforces revision-number/predecessor shape",
        )

        trigger_rows = (
            await conn.execute(
                text(
                    """
                    SELECT
                        c.relname AS table_name,
                        t.tgname,
                        t.tgdeferrable,
                        t.tginitdeferred
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
            (
                "sales_visit_revisions",
                "trg_sales_visit_revision_insert_contract",
            ) in trigger_map
            and (
                "sales_visit_revisions",
                "trg_sales_visit_revision_immutable",
            ) in trigger_map,
            "Sales revision insert contract and immutable guard are installed",
        )
        check(
            trigger_map.get(
                (
                    "sales_visit_revisions",
                    "trg_sales_visit_revision_must_freeze",
                )
            ) == (True, True)
            and trigger_map.get(
                (
                    "sales_visit_revisions",
                    "trg_sales_visit_revision_reconcile",
                )
            ) == (True, True),
            "Sales revision freeze/reconciliation remain deferred commit gates",
        )
        check(
            (
                "visits",
                "trg_visit_financial_evidence_immutable",
            ) in trigger_map
            and (
                "route_commercial_contexts",
                "trg_route_commercial_context_immutable",
            ) in trigger_map,
            "Visit projection and RouteCommercialContext immutability guards are installed",
        )
        check(
            (
                "sales_reward_evidence",
                "trg_sales_reward_evidence_insert_only",
            ) in trigger_map
            and trigger_map.get(
                (
                    "sales_reward_evidence",
                    "trg_sales_reward_evidence_parent_frozen",
                )
            ) == (True, True),
            "Reward evidence remains insert-only with deferred parent freeze",
        )
        check(
            (
                "sales_line_price_components",
                "trg_sales_line_price_component_insert_only",
            ) in trigger_map
            and trigger_map.get(
                (
                    "sales_line_price_components",
                    "trg_sales_line_price_component_parent_frozen",
                )
            ) == (True, True),
            "Price component evidence remains insert-only with deferred parent freeze",
        )

        fn_rows = (
            await conn.execute(
                text(
                    """
                    SELECT
                        p.proname,
                        pg_get_functiondef(p.oid) AS definition
                    FROM pg_proc p
                    JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = current_schema()
                      AND p.proname IN (
                          'validate_sales_visit_revision_insert',
                          'guard_visit_financial_evidence',
                          'assert_sales_visit_revision_snapshot',
                          'validate_sales_visit_revision_evidence'
                      )
                    """
                )
            )
        ).all()
        functions = {
            str(row.proname): str(row.definition)
            for row in fn_rows
        }

        insert_guard = functions.get(
            "validate_sales_visit_revision_insert",
            "",
        )
        visit_guard = functions.get(
            "guard_visit_financial_evidence",
            "",
        )
        snapshot_guard = functions.get(
            "assert_sales_visit_revision_snapshot",
            "",
        )
        reconcile_guard = functions.get(
            "validate_sales_visit_revision_evidence",
            "",
        )

        check(
            "sales revision chain must append exactly to the latest revision"
            in insert_guard
            and "sales revision does not match immutable route commercial context"
            in insert_guard
            and "FOR UPDATE" in insert_guard,
            "Revision insert is serialized and bound to the locked commercial context",
        )
        check(
            "visit identity is immutable once sales revisions exist"
            in visit_guard
            and "visit current sales revision must be the latest immutable revision"
            in visit_guard,
            "Historical Visit identity is immutable and current pointer must target latest revision",
        )

        snapshot_markers = (
            "sales revision snapshot does not match immutable route commercial context",
            "typed price evidence does not match immutable pricing authority",
            "frozen adjustment source was not valid at calculation time",
            "frozen tax source was not valid at calculation time",
            "document offer snapshot references invalid historical offer authority",
            "reward snapshot does not match immutable offer and pricing authority",
            "sales revision requires coherent frozen line envelopes",
        )
        check(
            all(marker in snapshot_guard for marker in snapshot_markers),
            "Snapshot authority validates context, line, price, offer, tax and reward provenance",
        )
        check(
            "assert_sales_visit_revision_snapshot" in reconcile_guard
            and "latest frozen sales revision must be the visit current revision at commit"
            in reconcile_guard,
            "Deferred revision reconciliation invokes snapshot authority and current-pointer gate",
        )

        company_ids = list(
            (
                await conn.execute(
                    text("SELECT id FROM companies ORDER BY id")
                )
            ).scalars().all()
        )

        history_ok = True
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

            chain_invalid = await conn.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM (
                            SELECT
                                r.visit_id,
                                r.id,
                                r.revision_number,
                                r.supersedes_revision_id,
                                row_number() OVER (
                                    PARTITION BY r.visit_id
                                    ORDER BY r.revision_number, r.id
                                ) AS expected_number,
                                lag(r.id) OVER (
                                    PARTITION BY r.visit_id
                                    ORDER BY r.revision_number, r.id
                                ) AS expected_predecessor
                            FROM sales_visit_revisions r
                            WHERE r.company_id = :company_id
                        ) chain
                        WHERE chain.revision_number <> chain.expected_number
                           OR (
                                chain.expected_number = 1
                                AND chain.supersedes_revision_id IS NOT NULL
                           )
                           OR (
                                chain.expected_number > 1
                                AND chain.supersedes_revision_id
                                    IS DISTINCT FROM chain.expected_predecessor
                           )
                    )
                    """
                ),
                {"company_id": int(company_id)},
            )

            stale_pointer = await conn.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM visits v
                        WHERE v.company_id = :company_id
                          AND v.current_sales_revision_id IS NOT NULL
                          AND v.current_sales_revision_id IS DISTINCT FROM (
                              SELECT r.id
                              FROM sales_visit_revisions r
                              WHERE r.company_id = v.company_id
                                AND r.visit_id = v.id
                              ORDER BY r.revision_number DESC, r.id DESC
                              LIMIT 1
                          )
                    )
                    """
                ),
                {"company_id": int(company_id)},
            )

            revision_ids = list(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT id
                            FROM sales_visit_revisions
                            WHERE company_id = :company_id
                            ORDER BY visit_id, revision_number
                            """
                        ),
                        {"company_id": int(company_id)},
                    )
                ).scalars().all()
            )

            if bool(chain_invalid) or bool(stale_pointer):
                history_ok = False
                break

            try:
                for revision_id in revision_ids:
                    await conn.execute(
                        text(
                            """
                            SELECT assert_sales_visit_revision_snapshot(
                                :company_id,
                                :revision_id
                            )
                            """
                        ),
                        {
                            "company_id": int(company_id),
                            "revision_id": int(revision_id),
                        },
                    )
            except Exception:
                history_ok = False
                break

        await conn.execute(
            text(
                "SELECT set_config('app.current_tenant', '', true)"
            )
        )

        check(
            history_ok,
            "Existing financial snapshot history passes chain, pointer and provenance validation",
        )

    await engine.dispose()


def main() -> int:
    try:
        static_checks()
        asyncio.run(database_checks())
    except Exception as exc:
        check(False, "Financial snapshot gate completed without unexpected exception")
        print(f"UNEXPECTED_EXCEPTION={exc!r}")

    print()
    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL: {failure}")

    if failures:
        print("STAGE6_FINANCIAL_SNAPSHOTS_GATE=FAIL")
        return 1

    print("STAGE6_FINANCIAL_SNAPSHOTS_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
