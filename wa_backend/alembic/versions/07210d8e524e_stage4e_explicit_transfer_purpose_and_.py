"""stage4e explicit transfer purpose and in-flight context

Revision ID: 07210d8e524e
Revises: 19c740dc40e8
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "07210d8e524e"
down_revision: Union[str, Sequence[str], None] = "19c740dc40e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Development baseline is intentionally strict: creation-time lifecycle evidence
    # cannot be reconstructed truthfully for historical transfer rows.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM inventory_transfer_headers LIMIT 1) THEN
                RAISE EXCEPTION
                    'Stage4E requires empty transfer tables; reset development/demo transfer data before migration';
            END IF;
        END
        $$;
        """
    )

    op.alter_column(
        "inventory_transfer_headers",
        "transfer_purpose",
        existing_type=sa.String(length=50),
        nullable=False,
        server_default=None,
    )
    op.add_column(
        "inventory_transfer_headers",
        sa.Column(
            "commercial_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
    )

    op.add_column(
        "inventory_transfer_lines",
        sa.Column("source_stock_status", sa.String(length=50), nullable=False),
    )
    op.add_column(
        "inventory_transfer_lines",
        sa.Column("lifecycle_revision_snapshot", sa.Integer(), nullable=False),
    )
    op.add_column(
        "inventory_transfer_lines",
        sa.Column("lifecycle_status_snapshot", sa.String(length=20), nullable=False),
    )
    op.add_column(
        "inventory_transfer_lines",
        sa.Column("operational_hold_snapshot", sa.String(length=20), nullable=False),
    )

    op.create_check_constraint(
        "chk_transfer_line_source_status",
        "inventory_transfer_lines",
        "source_stock_status IN "
        "('AVAILABLE','QUARANTINED','BLOCKED','RECALLED','DAMAGED','DISPOSAL_PENDING')",
    )
    op.create_check_constraint(
        "chk_transfer_line_lifecycle_revision_snapshot",
        "inventory_transfer_lines",
        "lifecycle_revision_snapshot > 0",
    )
    op.create_check_constraint(
        "chk_transfer_line_lifecycle_status_snapshot",
        "inventory_transfer_lines",
        "lifecycle_status_snapshot IN ('DRAFT','ACTIVE','RETIRING','ARCHIVED')",
    )
    op.create_check_constraint(
        "chk_transfer_line_operational_hold_snapshot",
        "inventory_transfer_lines",
        "operational_hold_snapshot IN ('NONE','SALES_HOLD','RECALL')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "chk_transfer_line_operational_hold_snapshot",
        "inventory_transfer_lines",
        type_="check",
    )
    op.drop_constraint(
        "chk_transfer_line_lifecycle_status_snapshot",
        "inventory_transfer_lines",
        type_="check",
    )
    op.drop_constraint(
        "chk_transfer_line_lifecycle_revision_snapshot",
        "inventory_transfer_lines",
        type_="check",
    )
    op.drop_constraint(
        "chk_transfer_line_source_status",
        "inventory_transfer_lines",
        type_="check",
    )

    op.drop_column("inventory_transfer_lines", "operational_hold_snapshot")
    op.drop_column("inventory_transfer_lines", "lifecycle_status_snapshot")
    op.drop_column("inventory_transfer_lines", "lifecycle_revision_snapshot")
    op.drop_column("inventory_transfer_lines", "source_stock_status")
    op.drop_column("inventory_transfer_headers", "commercial_context")

    op.alter_column(
        "inventory_transfer_headers",
        "transfer_purpose",
        existing_type=sa.String(length=50),
        nullable=False,
        server_default=sa.text("'WAREHOUSE_BALANCING'"),
    )
