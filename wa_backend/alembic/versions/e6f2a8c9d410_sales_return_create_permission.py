"""Persist the frozen Sales Return creation capability.

Revision ID: e6f2a8c9d410
Revises: d3b7e1a4c920
"""
from alembic import op

revision = "e6f2a8c9d410"
down_revision = "d3b7e1a4c920"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO permissions (code) "
        "VALUES ('sales_return.create') "
        "ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    # Permission catalog rows are retained to avoid invalidating historical RBAC evidence.
    pass
