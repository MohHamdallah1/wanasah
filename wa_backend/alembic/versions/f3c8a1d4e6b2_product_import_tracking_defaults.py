"""Persist product import tracking defaults.

Revision ID: f3c8a1d4e6b2
Revises: d4a7c9e2f1b5
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f3c8a1d4e6b2"
down_revision = "d4a7c9e2f1b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_import_jobs",
        sa.Column(
            "default_lot_control_mode",
            sa.String(length=20),
            nullable=True,
        ),
    )
    op.add_column(
        "product_import_jobs",
        sa.Column(
            "default_expiry_control_mode",
            sa.String(length=20),
            nullable=True,
        ),
    )

    # Historical import jobs were created before tracking configuration was
    # explicit and therefore behaved as REQUIRED/REQUIRED. Preserve that
    # historical truth instead of retroactively reinterpreting old jobs.
    op.execute(
        """
        UPDATE product_import_jobs
        SET
            default_lot_control_mode = 'REQUIRED',
            default_expiry_control_mode = 'REQUIRED'
        WHERE
            default_lot_control_mode IS NULL
            OR default_expiry_control_mode IS NULL
        """
    )

    op.alter_column(
        "product_import_jobs",
        "default_lot_control_mode",
        existing_type=sa.String(length=20),
        nullable=False,
    )
    op.alter_column(
        "product_import_jobs",
        "default_expiry_control_mode",
        existing_type=sa.String(length=20),
        nullable=False,
    )

    op.create_check_constraint(
        "import_job_lot_mode",
        "product_import_jobs",
        "default_lot_control_mode IN ('NONE','OPTIONAL','REQUIRED')",
    )
    op.create_check_constraint(
        "import_job_expiry_mode",
        "product_import_jobs",
        "default_expiry_control_mode IN ('NONE','OPTIONAL','REQUIRED')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "import_job_expiry_mode",
        "product_import_jobs",
        type_="check",
    )
    op.drop_constraint(
        "import_job_lot_mode",
        "product_import_jobs",
        type_="check",
    )
    op.drop_column(
        "product_import_jobs",
        "default_expiry_control_mode",
    )
    op.drop_column(
        "product_import_jobs",
        "default_lot_control_mode",
    )
