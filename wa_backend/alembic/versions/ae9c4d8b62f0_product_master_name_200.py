"""Permit 200-character Product masters for 200-character sellable variant names.

Revision ID: ae9c4d8b62f0
Revises: f3b8c1d6a240
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "ae9c4d8b62f0"
down_revision = "f3b8c1d6a240"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Increasing varchar length does not discard existing values.
    op.alter_column(
        "products",
        "name",
        existing_type=sa.String(length=150),
        type_=sa.String(length=200),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Downgrade must fail closed instead of silently truncating a long name.
    connection = op.get_bind()
    oversized = connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM products WHERE char_length(name) > 150)")
    ).scalar()
    if oversized:
        raise RuntimeError(
            "Cannot downgrade products.name to 150: existing names exceed 150 characters."
        )
    op.alter_column(
        "products",
        "name",
        existing_type=sa.String(length=200),
        type_=sa.String(length=150),
        existing_nullable=False,
    )
