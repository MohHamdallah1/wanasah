"""Repair and canonicalize import tracking constraints.

Revision ID: e7a1c4d9b2f6
Revises: f3c8a1d4e6b2

Some development databases may already have f3c8a1d4e6b2 recorded from an
earlier copy that created the tracking columns/constraints using long logical
names. SQLAlchemy's naming convention can transform or truncate those names.
This repair detects the constraints by the columns they protect, validates
their semantics, and converges every database onto short canonical names.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "e7a1c4d9b2f6"
down_revision = "f3c8a1d4e6b2"
branch_labels = None
depends_on = None


_CONSTRAINTS = {
    "import_job_lot_mode": (
        "ck_product_import_jobs_import_job_lot_mode",
        "default_lot_control_mode",
    ),
    "import_job_expiry_mode": (
        "ck_product_import_jobs_import_job_expiry_mode",
        "default_expiry_control_mode",
    ),
}


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _invalid_value_exists(column_name: str) -> bool:
    if column_name not in {
        "default_lot_control_mode",
        "default_expiry_control_mode",
    }:
        raise RuntimeError(
            "Unexpected import tracking column."
        )

    bind = op.get_bind()
    return bool(
        bind.scalar(
            text(
                f"""
                SELECT EXISTS (
                    SELECT 1
                    FROM public.product_import_jobs
                    WHERE {column_name} IS NULL
                       OR {column_name}
                          NOT IN ('NONE','OPTIONAL','REQUIRED')
                )
                """
            )
        )
    )


def _column_constraints(
    column_name: str,
) -> list[tuple[str, str]]:
    bind = op.get_bind()
    rows = bind.execute(
        text(
            """
            SELECT
                c.conname,
                pg_get_constraintdef(c.oid) AS definition
            FROM pg_constraint AS c
            JOIN pg_attribute AS a
              ON a.attrelid = c.conrelid
             AND a.attnum = ANY(c.conkey)
            WHERE c.conrelid =
                  'public.product_import_jobs'::regclass
              AND c.contype = 'c'
              AND a.attname = :column_name
            ORDER BY c.oid
            """
        ),
        {"column_name": column_name},
    ).all()
    return [
        (str(row.conname), str(row.definition))
        for row in rows
    ]


def _validate_existing_constraint(
    *,
    column_name: str,
    definition: str,
) -> None:
    normalized = definition.upper()
    required_tokens = (
        column_name.upper(),
        "NONE",
        "OPTIONAL",
        "REQUIRED",
    )
    if not all(
        token in normalized
        for token in required_tokens
    ):
        raise RuntimeError(
            "Unexpected import tracking CHECK constraint "
            f"for {column_name}: {definition}"
        )


def _canonicalize_constraint(
    *,
    logical_name: str,
    database_name: str,
    column_name: str,
) -> None:
    if _invalid_value_exists(column_name):
        raise RuntimeError(
            "Cannot repair import tracking constraint: "
            f"{column_name} contains invalid values."
        )

    rows = _column_constraints(column_name)
    if len(rows) > 1:
        raise RuntimeError(
            "Ambiguous import tracking schema: multiple CHECK "
            f"constraints reference {column_name}."
        )

    if not rows:
        op.create_check_constraint(
            logical_name,
            "product_import_jobs",
            (
                f"{column_name} "
                "IN ('NONE','OPTIONAL','REQUIRED')"
            ),
        )
        return

    current_name, definition = rows[0]
    _validate_existing_constraint(
        column_name=column_name,
        definition=definition,
    )
    if current_name == database_name:
        return

    bind = op.get_bind()
    canonical_exists = bool(
        bind.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conrelid =
                          'public.product_import_jobs'::regclass
                      AND conname = :database_name
                )
                """
            ),
            {"database_name": database_name},
        )
    )
    if canonical_exists:
        raise RuntimeError(
            "Canonical import tracking constraint already exists "
            f"while {current_name} also protects {column_name}."
        )

    op.execute(
        text(
            "ALTER TABLE public.product_import_jobs "
            f"RENAME CONSTRAINT {_quote_ident(current_name)} "
            f"TO {_quote_ident(database_name)}"
        )
    )


def upgrade() -> None:
    for (
        logical_name,
        (database_name, column_name),
    ) in _CONSTRAINTS.items():
        _canonicalize_constraint(
            logical_name=logical_name,
            database_name=database_name,
            column_name=column_name,
        )


def downgrade() -> None:
    # Parent revision f3c8a1d4e6b2 now uses the same canonical names.
    # This repair only converges databases created from older copies.
    pass
