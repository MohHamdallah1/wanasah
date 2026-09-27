"""Own Product Import state taxonomy constraints.

Revision ID: c4d9e7a1b623
Revises: 8b7d2c4e9f61

The migration uses PostgreSQL NOT VALID + VALIDATE CONSTRAINT before each
metadata swap so existing rows are scanned without holding an
ACCESS EXCLUSIVE lock for the validation scan. Constraint replacement still
requires brief metadata locks, but no table rewrite is introduced.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "c4d9e7a1b623"
down_revision = "8b7d2c4e9f61"
branch_labels = None
depends_on = None


JOB_CONSTRAINT = (
    "ck_product_import_jobs_chk_product_import_job_status"
)
JOB_COMPAT_CONSTRAINT = (
    "chk_product_import_job_status"
)
JOB_PHASE3_CONSTRAINT = (
    "chk_product_import_job_status_phase3"
)
JOB_LEGACY_CONSTRAINT = (
    "chk_product_import_job_status_legacy"
)

ROW_CONSTRAINT = (
    "ck_product_import_rows_chk_product_import_row_status"
)
ROW_COMPAT_CONSTRAINT = (
    "chk_product_import_row_status"
)
ROW_BRIDGE_CONSTRAINT = (
    "chk_product_import_row_status_phase3_bridge"
)
ROW_PHASE3_CONSTRAINT = (
    "chk_product_import_row_status_phase3"
)
ROW_LEGACY_CONSTRAINT = (
    "chk_product_import_row_status_legacy"
)


JOB_PHASE3_CHECK = """
status IN (
    'QUEUED',
    'PARSING',
    'NEEDS_MAPPING',
    'VALIDATING',
    'VALIDATION_FAILED',
    'IMPORTING',
    'RETRYING',
    'COMPLETED',
    'COMPLETED_WITH_ERRORS',
    'FAILED'
)
"""

JOB_LEGACY_CHECK = """
status IN (
    'QUEUED',
    'PARSING',
    'NEEDS_MAPPING',
    'VALIDATING',
    'VALIDATION_FAILED',
    'IMPORTING',
    'RETRYING',
    'COMPLETED',
    'FAILED'
)
"""

ROW_BRIDGE_CHECK = """
status IN (
    'STAGED',
    'VALID',
    'FAILED',
    'INVALID',
    'IMPORT_FAILED',
    'IMPORTED'
)
"""

ROW_PHASE3_CHECK = """
status IN (
    'STAGED',
    'VALID',
    'INVALID',
    'IMPORT_FAILED',
    'IMPORTED'
)
"""

ROW_LEGACY_CHECK = """
status IN (
    'STAGED',
    'VALID',
    'FAILED',
    'IMPORTED'
)
"""


def _assert_ddl_role() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        text(
            """
            SELECT
                rel.relname AS table_name,
                current_user AS current_user,
                owner.rolname AS table_owner,
                current_setting('is_superuser') = 'on'
                    AS is_superuser
            FROM pg_class AS rel
            JOIN pg_namespace AS ns
              ON ns.oid = rel.relnamespace
            JOIN pg_roles AS owner
              ON owner.oid = rel.relowner
            WHERE ns.nspname = 'public'
              AND rel.relname IN (
                  'product_import_jobs',
                  'product_import_rows'
              )
              AND rel.relkind = 'r'
            ORDER BY rel.relname
            """
        )
    ).mappings().all()

    if len(rows) != 2:
        raise RuntimeError(
            "Product Import state migration requires both import tables."
        )

    for row in rows:
        if (
            str(row["current_user"])
            != str(row["table_owner"])
            and not bool(
                row["is_superuser"]
            )
        ):
            raise RuntimeError(
                "Migration requires the Product Import table owner "
                "or a superuser. Use DATABASE_URL_MIGRATION."
            )


def _add_not_valid(
    table_name: str,
    constraint_name: str,
    expression: str,
) -> None:
    op.execute(
        text(
            f"""
            ALTER TABLE {table_name}
            ADD CONSTRAINT {constraint_name}
            CHECK ({expression})
            NOT VALID
            """
        )
    )


def _validate(
    table_name: str,
    constraint_name: str,
) -> None:
    op.execute(
        text(
            f"""
            ALTER TABLE {table_name}
            VALIDATE CONSTRAINT {constraint_name}
            """
        )
    )


def _constraint_exists(
    table_name: str,
    constraint_name: str,
) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_constraint AS con
                    JOIN pg_class AS rel
                      ON rel.oid = con.conrelid
                    JOIN pg_namespace AS ns
                      ON ns.oid = rel.relnamespace
                    WHERE ns.nspname = 'public'
                      AND rel.relname = :table_name
                      AND con.conname = :constraint_name
                )
                """
            ),
            {
                "table_name": table_name,
                "constraint_name":
                    constraint_name,
            },
        ).scalar()
    )


def _drop_existing(
    table_name: str,
    *constraint_names: str,
) -> None:
    for constraint_name in constraint_names:
        if _constraint_exists(
            table_name,
            constraint_name,
        ):
            _drop_raw(
                table_name,
                constraint_name,
            )
            return
    raise RuntimeError(
        "Expected Product Import constraint was not found on "
        f"{table_name}: {constraint_names!r}"
    )


def _drop_raw(
    table_name: str,
    constraint_name: str,
) -> None:
    op.execute(
        text(
            f"""
            ALTER TABLE {table_name}
            DROP CONSTRAINT {constraint_name}
            """
        )
    )


def _rename(
    table_name: str,
    current_name: str,
    target_name: str,
) -> None:
    op.execute(
        text(
            f"""
            ALTER TABLE {table_name}
            RENAME CONSTRAINT {current_name}
            TO {target_name}
            """
        )
    )


def upgrade() -> None:
    _assert_ddl_role()

    _add_not_valid(
        "product_import_jobs",
        JOB_PHASE3_CONSTRAINT,
        JOB_PHASE3_CHECK,
    )
    _validate(
        "product_import_jobs",
        JOB_PHASE3_CONSTRAINT,
    )
    _drop_existing(
        "product_import_jobs",
        JOB_CONSTRAINT,
        JOB_COMPAT_CONSTRAINT,
    )
    _rename(
        "product_import_jobs",
        JOB_PHASE3_CONSTRAINT,
        JOB_CONSTRAINT,
    )

    _add_not_valid(
        "product_import_rows",
        ROW_BRIDGE_CONSTRAINT,
        ROW_BRIDGE_CHECK,
    )
    _validate(
        "product_import_rows",
        ROW_BRIDGE_CONSTRAINT,
    )
    _drop_existing(
        "product_import_rows",
        ROW_CONSTRAINT,
        ROW_COMPAT_CONSTRAINT,
    )

    op.execute(
        text(
            """
            UPDATE product_import_rows
            SET status = 'INVALID'
            WHERE status = 'FAILED'
            """
        )
    )

    _add_not_valid(
        "product_import_rows",
        ROW_PHASE3_CONSTRAINT,
        ROW_PHASE3_CHECK,
    )
    _validate(
        "product_import_rows",
        ROW_PHASE3_CONSTRAINT,
    )
    _drop_raw(
        "product_import_rows",
        ROW_BRIDGE_CONSTRAINT,
    )
    _rename(
        "product_import_rows",
        ROW_PHASE3_CONSTRAINT,
        ROW_CONSTRAINT,
    )


def downgrade() -> None:
    _assert_ddl_role()

    op.execute(
        text(
            """
            UPDATE product_import_jobs
            SET status = 'COMPLETED'
            WHERE status = 'COMPLETED_WITH_ERRORS'
            """
        )
    )
    _add_not_valid(
        "product_import_jobs",
        JOB_LEGACY_CONSTRAINT,
        JOB_LEGACY_CHECK,
    )
    _validate(
        "product_import_jobs",
        JOB_LEGACY_CONSTRAINT,
    )
    op.drop_constraint(
        JOB_CONSTRAINT,
        "product_import_jobs",
        type_="check",
    )
    _rename(
        "product_import_jobs",
        JOB_LEGACY_CONSTRAINT,
        JOB_CONSTRAINT,
    )

    _add_not_valid(
        "product_import_rows",
        ROW_BRIDGE_CONSTRAINT,
        ROW_BRIDGE_CHECK,
    )
    _validate(
        "product_import_rows",
        ROW_BRIDGE_CONSTRAINT,
    )
    op.drop_constraint(
        ROW_CONSTRAINT,
        "product_import_rows",
        type_="check",
    )

    op.execute(
        text(
            """
            UPDATE product_import_rows
            SET status = 'FAILED'
            WHERE status IN (
                'INVALID',
                'IMPORT_FAILED'
            )
            """
        )
    )

    _add_not_valid(
        "product_import_rows",
        ROW_LEGACY_CONSTRAINT,
        ROW_LEGACY_CHECK,
    )
    _validate(
        "product_import_rows",
        ROW_LEGACY_CONSTRAINT,
    )
    _drop_raw(
        "product_import_rows",
        ROW_BRIDGE_CONSTRAINT,
    )
    _rename(
        "product_import_rows",
        ROW_LEGACY_CONSTRAINT,
        ROW_CONSTRAINT,
    )
