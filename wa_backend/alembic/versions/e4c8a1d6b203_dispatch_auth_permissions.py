"""Persist frozen Dispatch/session/settlement/shortage authorization permissions.

Revision ID: e4c8a1d6b203
Revises: e6f2a8c9d410
"""
from alembic import op

revision = "e4c8a1d6b203"
down_revision = "e6f2a8c9d410"
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
