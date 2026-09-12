"""stage4 batch metadata and nullable expiry

Revision ID: c3f4e5a6b7d8
Revises: 9b1a6d4c2e70
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3f4e5a6b7d8"
down_revision: Union[str, Sequence[str], None] = "9b1a6d4c2e70"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "chk_product_batch_date_order",
        "product_batches",
        type_="check",
    )

    op.alter_column(
        "product_batches",
        "expiry_date",
        existing_type=sa.Date(),
        nullable=True,
    )

    op.add_column(
        "product_batches",
        sa.Column(
            "disposition_reason",
            sa.Text(),
            nullable=True,
        ),
    )

    op.add_column(
        "product_batches",
        sa.Column(
            "disposition_revision",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )

    op.add_column(
        "product_batches",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    op.execute(
        """
        UPDATE product_batches
        SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)
        WHERE updated_at IS NULL
        """
    )

    op.alter_column(
        "product_batches",
        "updated_at",
        existing_type=sa.DateTime(),
        nullable=False,
    )

    op.create_check_constraint(
        "chk_product_batch_date_order",
        "product_batches",
        "expiry_date IS NULL "
        "OR production_date IS NULL "
        "OR production_date <= expiry_date",
    )

    op.create_check_constraint(
        "chk_product_batch_disposition_revision",
        "product_batches",
        "disposition_revision > 0",
    )

    op.create_check_constraint(
        "chk_product_batch_disposition_reason",
        "product_batches",
        "disposition_reason IS NULL "
        "OR length(trim(disposition_reason)) > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "chk_product_batch_disposition_reason",
        "product_batches",
        type_="check",
    )

    op.drop_constraint(
        "chk_product_batch_disposition_revision",
        "product_batches",
        type_="check",
    )

    op.drop_constraint(
        "chk_product_batch_date_order",
        "product_batches",
        type_="check",
    )

    op.drop_column(
        "product_batches",
        "updated_at",
    )

    op.drop_column(
        "product_batches",
        "disposition_revision",
    )

    op.drop_column(
        "product_batches",
        "disposition_reason",
    )

    op.alter_column(
        "product_batches",
        "expiry_date",
        existing_type=sa.Date(),
        nullable=False,
    )

    op.create_check_constraint(
        "chk_product_batch_date_order",
        "product_batches",
        "production_date IS NULL "
        "OR production_date <= expiry_date",
    )