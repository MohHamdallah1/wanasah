"""Drop the retired drivers.is_admin column.

Revision ID: f2c7a9d4e611
Revises: e4c8a1d6b203
"""
from alembic import op
import sqlalchemy as sa


revision = "f2c7a9d4e611"
down_revision = "e4c8a1d6b203"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("drivers", "is_admin")


def downgrade() -> None:
    op.add_column(
        "drivers",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
