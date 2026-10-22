"""Use OPTIONAL as the platform default for new product tracking.

Revision ID: a1d7f0c6e5b2
Revises: e6b4c2d9a731
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "a1d7f0c6e5b2"
down_revision = "e6b4c2d9a731"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing product rows and explicit company settings remain unchanged.
    # Only future rows that rely on the database default become OPTIONAL.
    op.alter_column(
        "product_variants",
        "lot_control_mode",
        existing_type=sa.String(length=20),
        server_default="OPTIONAL",
        existing_nullable=False,
    )
    op.alter_column(
        "product_variants",
        "expiry_control_mode",
        existing_type=sa.String(length=20),
        server_default="OPTIONAL",
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "product_variants",
        "lot_control_mode",
        existing_type=sa.String(length=20),
        server_default="REQUIRED",
        existing_nullable=False,
    )
    op.alter_column(
        "product_variants",
        "expiry_control_mode",
        existing_type=sa.String(length=20),
        server_default="REQUIRED",
        existing_nullable=False,
    )
