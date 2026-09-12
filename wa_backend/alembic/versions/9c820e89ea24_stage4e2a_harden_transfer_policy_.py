# stage4e2a harden transfer policy permission
# Revision ID: 9c820e89ea24
# Revises: dfe93e142cea

from typing import Sequence, Union

from alembic import op


revision: str = "9c820e89ea24"
down_revision: Union[str, Sequence[str], None] = "dfe93e142cea"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Dedicated governance permission: do not reuse location.state for policy administration.
    op.execute(
        "INSERT INTO permissions (code) "
        "VALUES ('inventory.transfer_policy.manage') "
        "ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    # Deliberately keep the permission catalog row. It may already be referenced
    # by role_permissions, and older application code safely ignores unknown codes.
    pass
