"""Add optional Vehicle next maintenance business date.

Revision ID: d1a8f6c3b742
Revises: c9e7a41d2b60
"""
from alembic import op
import sqlalchemy as sa

revision = "d1a8f6c3b742"
down_revision = "c9e7a41d2b60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vehicles",
        sa.Column("next_maintenance_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("vehicles", "next_maintenance_date")
