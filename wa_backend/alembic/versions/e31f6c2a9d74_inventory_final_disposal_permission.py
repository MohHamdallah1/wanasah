"""add final disposal confirmation permission

Revision ID: e31f6c2a9d74
Revises: d7c4a8e1f205
"""

from typing import Sequence, Union

from alembic import op

revision: str = "e31f6c2a9d74"
down_revision: Union[str, Sequence[str], None] = "d7c4a8e1f205"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO permissions (code) VALUES "
        "('inventory.disposal.confirm') "
        "ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    # Permission catalog rows are retained to avoid invalidating historical RBAC evidence.
    pass
