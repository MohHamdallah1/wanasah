"""Persist canonical Ledger read and adjustment permissions.

Revision ID: f4c10a7e2d31
Revises: d1a8f6c3b742
"""
from alembic import op

revision = "f4c10a7e2d31"
down_revision = "d1a8f6c3b742"
branch_labels = None
depends_on = None

PERMISSION_CODES = (
    "ledger.read",
    "ledger.adjust",
)


def upgrade():
    for code in PERMISSION_CODES:
        op.execute(
            f"""
            INSERT INTO permissions (code)
            VALUES ('{code}')
            ON CONFLICT (code) DO NOTHING
            """
        )


def downgrade():
    # Permission catalog rows are retained to avoid invalidating RBAC history.
    pass
