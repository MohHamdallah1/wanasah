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
PERMISSION_DESCRIPTION = "Manage inventory minimum-stock policy"


def upgrade():
    op.execute(
        f"""
        INSERT INTO permissions (code, description)
        VALUES ('{PERMISSION_CODE}', '{PERMISSION_DESCRIPTION}')
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade():
    op.execute(
        f"""
        DELETE FROM permissions
         WHERE code = '{PERMISSION_CODE}'
           AND NOT EXISTS (
               SELECT 1
                 FROM role_permissions rp
                WHERE rp.permission_id = permissions.id
           )
        """
    )
