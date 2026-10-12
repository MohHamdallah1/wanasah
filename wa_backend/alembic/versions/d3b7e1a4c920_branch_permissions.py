"""Persist canonical Branch authorization permissions.

Revision ID: d3b7e1a4c920
Revises: c8a41d9e6f20
"""
from alembic import op

revision = "d3b7e1a4c920"
down_revision = "c8a41d9e6f20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO permissions (code) VALUES "
        "('branch.read'),"
        "('branch.create'),"
        "('branch.update'),"
        "('branch.state') "
        "ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    # Permission catalog rows are retained to avoid invalidating historical RBAC evidence.
    pass
