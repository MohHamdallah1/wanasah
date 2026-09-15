"""pricing assignment offer interaction policy

Revision ID: e3b7a9c1d4f6
Revises: d2a6c8e4f1b7
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3b7a9c1d4f6"
down_revision: Union[str, Sequence[str], None] = "d2a6c8e4f1b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "price_book_assignments",
        sa.Column(
            "allow_offers",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("price_book_assignments", "allow_offers")
