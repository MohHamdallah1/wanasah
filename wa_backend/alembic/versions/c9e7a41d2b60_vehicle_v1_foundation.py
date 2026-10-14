"""Add Vehicle V1 optimistic concurrency and capabilities.

Revision ID: c9e7a41d2b60
Revises: b7a4c2d9e105
"""
from alembic import op
import sqlalchemy as sa

revision = "c9e7a41d2b60"
down_revision = "b7a4c2d9e105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vehicles",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_check_constraint(
        "version_positive",
        "vehicles",
        "version > 0",
    )
    op.execute(
        "INSERT INTO permissions (code) VALUES "
        "('vehicle.read'),"
        "('vehicle.manage') "
        "ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    # Permission rows are retained so historical RBAC evidence is never invalidated.
    op.drop_constraint("version_positive", "vehicles", type_="check")
    op.drop_column("vehicles", "version")
