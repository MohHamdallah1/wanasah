"""Persist frozen Dispatch/session/settlement/shortage authorization permissions.

Revision ID: e4c8a1d6b203
Revises: d3b7e1a4c920
"""
from alembic import op

revision = "e4c8a1d6b203"
down_revision = "d3b7e1a4c920"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO permissions (code) VALUES "
        "('work_session.read'),"
        "('work_session.authorize_sale'),"
        "('work_session.reopen'),"
        "('settlement.read'),"
        "('settlement.execute'),"
        "('shortage.read'),"
        "('shortage.create'),"
        "('shortage.cancel'),"
        "('visit.read'),"
        "('reconciliation.execute') "
        "ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    # Permission catalog rows are retained to avoid invalidating historical RBAC evidence.
    pass
