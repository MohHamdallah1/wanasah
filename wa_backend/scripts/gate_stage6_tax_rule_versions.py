from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError
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


def rejected(callable_) -> bool:
    try:
        callable_()
        return False
    except (ValidationError, ValueError):
        return True


def domain_checks() -> None:
    from domains.taxation.contracts import TaxResolution
    from domains.taxation.core import (
        TAX_JURISDICTION_MAX_DEPTH,
        TaxError,
    )
    from domains.taxation.resolver import _pick_candidate
    from domains.taxation.schemas import (
        DeleteCommand,
        RuleSetCreate,
        TaxComponentInput,
        VersionCommand,
    )

    check(
        TAX_JURISDICTION_MAX_DEPTH == 64,
        "Tax jurisdiction hierarchy has one shared 64-level authority",
    )

    component_base = {
        "component_code": "VAT",
        "name": "VAT",
        "sequence": 1,
    }
    check(
        rejected(
            lambda: TaxComponentInput.model_validate(
                {**component_base, "rate": 1.0}
            )
        ),
        "Tax rate rejects float input",
    )
    check(
        rejected(
            lambda: TaxComponentInput.model_validate(
                {**component_base, "rate": True}
            )
        ),
        "Tax rate rejects bool input",
    )
    check(
        rejected(
            lambda: TaxComponentInput.model_validate(
                {**component_base, "rate": "1.000000001"}
            )
        ),
        "Tax rate rejects more than 8 decimal places",
    )
    check(
        rejected(
            lambda: TaxComponentInput.model_validate(
                {**component_base, "rate": "1000000000000"}
            )
        ),
        "Tax rate rejects NUMERIC(20,8) overflow",
    )

    request_id = uuid4()
    check(
        rejected(
            lambda: DeleteCommand(
                request_id=request_id,
                expected_version=1,
                reason="   ",
            )
        )
        and rejected(
            lambda: VersionCommand(
                request_id=request_id,
                expected_version=1,
                reason="\t \n",
            )
        ),
        "Tax lifecycle reasons reject whitespace-only values",
    )
    check(
        rejected(
            lambda: VersionCommand(
                request_id=request_id,
                expected_version=1,
                reason="abc\x00def",
            )
        ),
        "Tax lifecycle reasons reject NUL",
    )
    check(
        rejected(
            lambda: RuleSetCreate(
                request_id=request_id,
                code="VAT",
                name="VAT",
                description="bad\x00description",
            )
        ),
        "Tax descriptions reject PostgreSQL NUL",
    )

    now = datetime.now(timezone.utc)

    def resolution(
        version_id: int,
        *,
        priority: int,
        scope_types: tuple[str, ...],
        distance: int | None,
    ) -> TaxResolution:
        return TaxResolution(
            product_variant_id=10,
            tax_rule_set_id=version_id,
            tax_rule_set_version_id=version_id,
            tax_revision=version_id,
            definition_version=1,
            priority=priority,
            price_mode="EXCLUSIVE",
            scope_types=scope_types,
            matched_jurisdiction_id=(
                1 if distance is not None else None
            ),
            jurisdiction_distance=distance,
            components=(),
            resolved_at=now,
        )

    more_specific = resolution(
        1,
        priority=1,
        scope_types=("JURISDICTION", "PRODUCT_VARIANT"),
        distance=2,
    )
    less_specific = resolution(
        2,
        priority=999,
        scope_types=("JURISDICTION",),
        distance=0,
    )
    check(
        _pick_candidate(
            10,
            [less_specific, more_specific],
        )
        is more_specific,
        "Tax precedence chooses specificity before priority",
    )

    high_priority = resolution(
        3,
        priority=20,
        scope_types=("JURISDICTION",),
        distance=3,
    )
    low_priority = resolution(
        4,
        priority=10,
        scope_types=("JURISDICTION",),
        distance=0,
    )
    check(
        _pick_candidate(
            10,
            [low_priority, high_priority],
        )
        is high_priority,
        "Tax precedence chooses priority within equal specificity",
    )

    near = resolution(
        5,
        priority=10,
        scope_types=("JURISDICTION",),
        distance=1,
    )
    far = resolution(
        6,
        priority=10,
        scope_types=("JURISDICTION",),
        distance=3,
    )
    check(
        _pick_candidate(10, [far, near]) is near,
        "Tax precedence chooses nearest jurisdiction for equal scope shape",
    )

    tie_a = resolution(
        7,
        priority=10,
        scope_types=("CUSTOMER",),
        distance=None,
    )
    tie_b = resolution(
        8,
        priority=10,
        scope_types=("DOCUMENT_TYPE",),
        distance=None,
    )
    try:
        _pick_candidate(10, [tie_a, tie_b])
        tie_code = None
    except TaxError as exc:
        tie_code = exc.code
    check(
        tie_code == "TAX_RULE_TIE",
        "Ambiguous tax precedence fails closed instead of choosing arbitrarily",
    )

    publishing = (
        BACKEND / "domains/taxation/publishing.py"
    ).read_text(encoding="utf-8")
    for function_name in (
        "create_jurisdiction",
        "update_jurisdiction",
        "delete_jurisdiction",
    ):
        start = publishing.index(
            f"async def {function_name}("
        )
        next_start = publishing.find(
            "\nasync def ",
            start + 10,
        )
        section = (
            publishing[start:]
            if next_start < 0
            else publishing[start:next_start]
        )
        check(
            "await lock_company(db, company_id)"
            in section,
            f"{function_name} acquires tenant Company lock first",
        )

    check(
        "_validate_prospective_parent_chain"
        in publishing
        and "_ensure_topology_move_safe"
        in publishing,
        "Tax jurisdiction writes share hierarchy/topology guards",
    )

    resolver = (
        BACKEND / "domains/taxation/resolver.py"
    ).read_text(encoding="utf-8")
    check(
        "jurisdiction_chain(" in resolver
        and "_MAX_JURISDICTION_DEPTH"
        not in resolver,
        "Resolver uses shared jurisdiction hierarchy authority",
    )


async def database_checks() -> None:
    from database import engine
    from domains.taxation.core import (
        TAX_JURISDICTION_MAX_DEPTH,
    )

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
        heads_cp.returncode == 0
        and len(cli_heads) == 1,
        "Alembic exposes exactly one current head",
    )

    tables = (
        "tax_jurisdictions",
        "tax_rule_sets",
        "tax_rule_set_versions",
        "tax_rule_components",
        "tax_rule_scopes",
    )

    async with engine.connect() as conn:
        db_heads = set(
            (
                await conn.execute(
                    text(
                        "SELECT version_num "
                        "FROM alembic_version"
                    )
                )
            ).scalars().all()
        )
        check(
            bool(cli_heads)
            and db_heads == cli_heads,
            "Database is upgraded to the exact current Alembic head",
        )

        rls_rows = (
            await conn.execute(
                text(
                    """
                    SELECT
                        relname,
                        relrowsecurity,
                        relforcerowsecurity
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
            all(
                rls.get(table)
                == (True, True)
                for table in tables
            ),
            "All tax tables keep ENABLE + FORCE RLS",
        )

        policy_rows = (
            await conn.execute(
                text(
                    """
                    SELECT
                        tablename,
                        policyname,
                        qual,
                        with_check
                    FROM pg_policies
                    WHERE schemaname = current_schema()
                      AND tablename = ANY(:tables)
                    """
                ),
                {"tables": list(tables)},
            )
        ).all()
        policies = {
            str(row.tablename): (
                str(row.policyname),
                str(row.qual or ""),
                str(row.with_check or ""),
            )
            for row in policy_rows
            if str(row.policyname).endswith(
                "_company_isolation"
            )
        }
        check(
            all(
                table in policies
                and "app.current_tenant"
                in policies[table][1]
                and "company_id"
                in policies[table][1]
                and "app.current_tenant"
                in policies[table][2]
                and "company_id"
                in policies[table][2]
                for table in tables
            ),
            "Tax RLS policies enforce tenant USING + WITH CHECK",
        )

        constraint_rows = (
            await conn.execute(
                text(
                    """
                    SELECT
                        cls.relname AS table_name,
                        c.conname,
                        c.contype::text
                            AS constraint_type,
                        pg_get_constraintdef(
                            c.oid,
                            true
                        ) AS definition
                    FROM pg_constraint c
                    JOIN pg_class cls
                      ON cls.oid = c.conrelid
                    WHERE cls.relname = ANY(:tables)
                    """
                ),
                {"tables": list(tables)},
            )
        ).all()
        defs = {
            (
                str(row.table_name),
                str(row.conname),
            ): (
                str(row.constraint_type),
                str(row.definition),
            )
            for row in constraint_rows
        }

        required_composite_fks = (
            (
                "tax_jurisdictions",
                "FOREIGN KEY "
                "(company_id, parent_jurisdiction_id)",
            ),
            (
                "tax_rule_set_versions",
                "FOREIGN KEY "
                "(company_id, tax_rule_set_id)",
            ),
            (
                "tax_rule_components",
                "FOREIGN KEY "
                "(company_id, tax_rule_set_version_id)",
            ),
            (
                "tax_rule_scopes",
                "FOREIGN KEY "
                "(company_id, tax_rule_set_version_id)",
            ),
            (
                "tax_rule_scopes",
                "FOREIGN KEY "
                "(company_id, jurisdiction_id)",
            ),
            (
                "tax_rule_scopes",
                "FOREIGN KEY "
                "(company_id, product_variant_id)",
            ),
            (
                "tax_rule_scopes",
                "FOREIGN KEY "
                "(company_id, customer_id)",
            ),
        )
        check(
            all(
                any(
                    table == expected_table
                    and constraint_type == "f"
                    and fragment in definition
                    for (
                        table,
                        _name,
                    ), (
                        constraint_type,
                        definition,
                    ) in defs.items()
                )
                for (
                    expected_table,
                    fragment,
                ) in required_composite_fks
            ),
            "Tax relational references are tenant-bound by composite FKs",
        )

        rate_row = (
            await conn.execute(
                text(
                    """
                    SELECT
                        numeric_precision,
                        numeric_scale
                    FROM information_schema.columns
                    WHERE table_schema =
                        current_schema()
                      AND table_name =
                        'tax_rule_components'
                      AND column_name = 'rate'
                    """
                )
            )
        ).one_or_none()
        check(
            rate_row is not None
            and int(
                rate_row.numeric_precision
            ) == 20
            and int(
                rate_row.numeric_scale
            ) == 8,
            "Tax component rate is stored as NUMERIC(20,8)",
        )

        index_rows = (
            await conn.execute(
                text(
                    """
                    SELECT
                        indexname,
                        indexdef
                    FROM pg_indexes
                    WHERE schemaname =
                        current_schema()
                      AND tablename =
                        'tax_rule_set_versions'
                    """
                )
            )
        ).all()
        check(
            any(
                "uq_tax_version_one_published_rule_set"
                in str(row.indexname)
                and "UNIQUE"
                in str(row.indexdef).upper()
                and "PUBLISHED"
                in str(row.indexdef)
                for row in index_rows
            ),
            "DB permits only one currently PUBLISHED version per rule set",
        )

        trigger_rows = (
            await conn.execute(
                text(
                    """
                    SELECT
                        event_object_table,
                        trigger_name
                    FROM information_schema.triggers
                    WHERE event_object_table =
                        ANY(:tables)
                    """
                ),
                {"tables": list(tables)},
            )
        ).all()
        trigger_set = {
            (
                str(row.event_object_table),
                str(row.trigger_name),
            )
            for row in trigger_rows
        }
        check(
            (
                "tax_jurisdictions",
                "trg_tax_jurisdiction_cycle",
            ) in trigger_set
            and (
                "tax_jurisdictions",
                "trg_tax_jurisdiction_identity",
            ) in trigger_set
            and (
                "tax_rule_set_versions",
                "trg_tax_version_immutable",
            ) in trigger_set
            and (
                "tax_rule_components",
                "trg_tax_component_immutable",
            ) in trigger_set
            and (
                "tax_rule_scopes",
                "trg_tax_scope_immutable",
            ) in trigger_set,
            "Tax hierarchy/version/child DB guards are installed",
        )

        function_rows = (
            await conn.execute(
                text(
                    """
                    SELECT
                        p.proname,
                        pg_get_functiondef(p.oid)
                            AS definition
                    FROM pg_proc p
                    JOIN pg_namespace n
                      ON n.oid = p.pronamespace
                    WHERE n.nspname =
                        current_schema()
                      AND p.proname IN (
                        'guard_tax_jurisdiction_cycle',
                        'guard_tax_jurisdiction_identity'
                      )
                    """
                )
            )
        ).all()
        functions = {
            str(row.proname):
            str(row.definition)
            for row in function_rows
        }
        hierarchy_fn = functions.get(
            "guard_tax_jurisdiction_cycle",
            "",
        )
        identity_fn = functions.get(
            "guard_tax_jurisdiction_identity",
            "",
        )
        check(
            "same country"
            in hierarchy_fn
            and "active parent"
            in hierarchy_fn
            and "supported depth"
            in hierarchy_fn
            and str(
                TAX_JURISDICTION_MAX_DEPTH
            )
            in hierarchy_fn,
            "DB hierarchy guard enforces country/active/depth invariants",
        )
        check(
            "topology is referenced by immutable tax version"
            in identity_fn
            and "PENDING_APPROVAL"
            in identity_fn
            and "SUPERSEDED"
            in identity_fn,
            "DB blocks topology moves that mutate immutable tax semantics",
        )

        company_ids = list(
            (
                await conn.execute(
                    text(
                        "SELECT id FROM companies "
                        "ORDER BY id"
                    )
                )
            ).scalars().all()
        )
        hierarchy_data_ok = True
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
                {
                    "tenant_id":
                    str(int(company_id)),
                },
            )

            mismatch = await conn.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM tax_jurisdictions
                            child
                        JOIN tax_jurisdictions
                            parent
                          ON parent.company_id =
                             child.company_id
                         AND parent.id =
                             child.parent_jurisdiction_id
                        WHERE child.company_id =
                              :company_id
                          AND (
                              child.country_code
                                  IS DISTINCT FROM
                                  parent.country_code
                              OR (
                                  child.is_active
                                      IS TRUE
                                  AND parent.is_active
                                      IS FALSE
                              )
                          )
                    )
                    """
                ),
                {
                    "company_id":
                    int(company_id),
                },
            )
            if bool(mismatch):
                hierarchy_data_ok = False
                break

            broken_depth = await conn.scalar(
                text(
                    """
                    WITH RECURSIVE walk AS (
                        SELECT
                            j.id AS start_id,
                            j.id,
                            j.parent_jurisdiction_id
                                AS parent_id,
                            1 AS depth,
                            ARRAY[j.id] AS path,
                            false AS cycle
                        FROM tax_jurisdictions j
                        WHERE j.company_id =
                              :company_id

                        UNION ALL

                        SELECT
                            walk.start_id,
                            parent.id,
                            parent.parent_jurisdiction_id,
                            walk.depth + 1,
                            walk.path || parent.id,
                            parent.id =
                                ANY(walk.path)
                        FROM walk
                        JOIN tax_jurisdictions
                            parent
                          ON parent.company_id =
                             :company_id
                         AND parent.id =
                             walk.parent_id
                        WHERE walk.parent_id
                                  IS NOT NULL
                          AND walk.cycle IS FALSE
                          AND walk.depth <=
                              :max_depth
                    )
                    SELECT EXISTS (
                        SELECT 1
                        FROM walk
                        WHERE cycle IS TRUE
                           OR depth > :max_depth
                    )
                    """
                ),
                {
                    "company_id":
                    int(company_id),
                    "max_depth":
                    TAX_JURISDICTION_MAX_DEPTH,
                },
            )
            if bool(broken_depth):
                hierarchy_data_ok = False
                break

        await conn.execute(
            text(
                """
                SELECT set_config(
                    'app.current_tenant',
                    '',
                    true
                )
                """
            )
        )
        check(
            hierarchy_data_ok,
            "Existing tenant tax hierarchy satisfies country/active/depth invariants",
        )

    await engine.dispose()


def main() -> int:
    try:
        domain_checks()
        asyncio.run(database_checks())
    except Exception as exc:
        check(
            False,
            "Tax rule gate completed without unexpected exception",
        )
        print(
            f"UNEXPECTED_EXCEPTION={exc!r}"
        )

    print()
    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL: {failure}")

    if failures:
        print(
            "STAGE6_TAX_RULE_VERSIONS_GATE=FAIL"
        )
        return 1

    print(
        "STAGE6_TAX_RULE_VERSIONS_GATE=PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
