"""D06 separate company-only Shop financial visibility permission.

Revision ID: f6c2a7d4e890
Revises: c9a1e4d7b630

No UserRole, RolePermission or UserLocationAccess rows are granted here.
Only an explicitly configured COMPANY role can expose Shop receivables.
"""
from alembic import op

revision = "f6c2a7d4e890"
down_revision = "c9a1e4d7b630"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO permissions (code) VALUES ('shop.financial.read') "
        "ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    # Keep the historical permission code; do not silently delete live grants.
    pass
