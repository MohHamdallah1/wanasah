"""Persist the frozen Representative management capability catalog.

Revision ID: b7a4c2d9e105
Revises: f2c7a9d4e611
"""
from alembic import op

revision = "b7a4c2d9e105"
down_revision = "f2c7a9d4e611"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO permissions (code) VALUES "
        "('representative.read'),"
        "('representative.manage'),"
        "('representative.credentials.reset') "
        "ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    # Permission catalog rows are retained to avoid invalidating historical RBAC evidence.
    pass
