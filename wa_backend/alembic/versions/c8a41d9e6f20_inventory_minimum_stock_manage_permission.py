"""Persist canonical minimum-stock management permission.

Revision ID: c8a41d9e6f20
Revises: b7e3f6a1c902
"""
from alembic import op

revision = "c8a41d9e6f20"
down_revision = "b7e3f6a1c902"
branch_labels = None
depends_on = None

PERMISSION_CODE = "inventory.minimum_stock.manage"


def upgrade():
    op.execute(
        f"""
        INSERT INTO permissions (code)
        VALUES ('{PERMISSION_CODE}')
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade():
    # Permission catalog rows are retained to avoid invalidating RBAC catalog history.
    pass
