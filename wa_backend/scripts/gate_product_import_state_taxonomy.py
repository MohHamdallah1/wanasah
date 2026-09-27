from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
sys.path.insert(
    0,
    str(BACKEND),
)

from database import engine  # noqa: E402
from domains.simple_products.imports.application.state_machine import (  # noqa: E402
    JOB_STATUSES,
    ROW_STATUSES,
    JobStatus,
    RowStatus,
)


checks = 0
failures: list[str] = []


def check(
    condition: bool,
    label: str,
    detail: str = "",
) -> None:
    global checks
    checks += 1
    prefix = (
        "[PASS]"
        if condition
        else "[FAIL]"
    )
    suffix = (
        f" — {detail}"
        if detail
        else ""
    )
    print(
        f"{prefix} {label}{suffix}"
    )
    if not condition:
        failures.append(label)


def quoted_values(
    definition: str,
) -> set[str]:
    return set(
        re.findall(
            r"'([A-Z_]+)'",
            definition,
        )
    )


async def main() -> None:
    async with engine.connect() as conn:
        revision = await conn.scalar(
            text(
                "SELECT version_num "
                "FROM alembic_version"
            )
        )
        check(
            revision
            == "c4d9e7a1b623",
            "Database is upgraded to Product Import state taxonomy migration",
            str(revision),
        )

        rows = (
            await conn.execute(
                text(
                    """
                    SELECT
                        rel.relname AS table_name,
                        con.conname AS constraint_name,
                        pg_get_constraintdef(
                            con.oid
                        ) AS definition
                    FROM pg_constraint AS con
                    JOIN pg_class AS rel
                      ON rel.oid = con.conrelid
                    JOIN pg_namespace AS ns
                      ON ns.oid = rel.relnamespace
                    WHERE ns.nspname = 'public'
                      AND (
                        (
                          rel.relname = 'product_import_jobs'
                          AND con.conname = 'ck_product_import_jobs_chk_product_import_job_status'
                        )
                        OR
                        (
                          rel.relname = 'product_import_rows'
                          AND con.conname = 'ck_product_import_rows_chk_product_import_row_status'
                        )
                      )
                    ORDER BY rel.relname
                    """
                )
            )
        ).mappings().all()

        definitions = {
            str(row["table_name"]):
                str(row["definition"])
            for row in rows
        }

        job_values = quoted_values(
            definitions.get(
                "product_import_jobs",
                "",
            )
        )
        row_values = quoted_values(
            definitions.get(
                "product_import_rows",
                "",
            )
        )

        check(
            job_values == JOB_STATUSES,
            "Database job-state constraint exactly matches canonical state machine",
            repr(
                sorted(job_values)
            ),
        )
        check(
            row_values == ROW_STATUSES,
            "Database row-state constraint exactly matches canonical state machine",
            repr(
                sorted(row_values)
            ),
        )

        legacy_failed_rows = int(
            (
                await conn.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM product_import_rows
                        WHERE status = 'FAILED'
                        """
                    )
                )
            )
            or 0
        )
        check(
            legacy_failed_rows == 0,
            "Legacy FAILED row states were migrated to INVALID",
            str(
                legacy_failed_rows
            ),
        )

    models = (
        BACKEND / "models.py"
    ).read_text(
        encoding="utf-8"
    )
    check(
        "COMPLETED_WITH_ERRORS"
        in models
        and "IMPORT_FAILED"
        in models
        and "'INVALID'"
        in models,
        "ORM constraints expose the Phase 3 canonical taxonomy",
    )
    check(
        JobStatus.COMPLETED_WITH_ERRORS.value
        in JOB_STATUSES
        and RowStatus.INVALID.value
        in ROW_STATUSES
        and RowStatus.IMPORT_FAILED.value
        in ROW_STATUSES,
        "Canonical taxonomy exposes partial-success and distinct row failures",
    )

    if failures:
        print(
            f"CHECKS={checks}"
        )
        print(
            f"FAILURES={len(failures)}"
        )
        for failure in failures:
            print(
                f"FAIL: {failure}"
            )
        print(
            "PRODUCT_IMPORT_STATE_TAXONOMY_GATE=FAIL"
        )
        raise SystemExit(1)

    print(
        f"CHECKS={checks}"
    )
    print("FAILURES=0")
    print(
        "PRODUCT_IMPORT_STATE_TAXONOMY_GATE=PASS"
    )


if __name__ == "__main__":
    asyncio.run(main())
