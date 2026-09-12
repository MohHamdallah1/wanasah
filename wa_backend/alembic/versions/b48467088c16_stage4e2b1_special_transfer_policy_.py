# stage4e2b1 special transfer policy snapshot contract
# Revision ID: b48467088c16
# Revises: 9c820e89ea24

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b48467088c16"
down_revision: Union[str, Sequence[str], None] = "9c820e89ea24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS ("
        "SELECT 1 FROM inventory_transfer_headers "
        "WHERE transfer_purpose IN "
        "('RETURN_TO_VENDOR','QUARANTINE','RECALL_RETURN','DISPOSAL') "
        "LIMIT 1"
        ") THEN "
        "RAISE EXCEPTION "
        "'Stage4E2B1 requires no pre-existing special-purpose transfers; historical policy evidence cannot be fabricated'; "
        "END IF; END $$;"
    )

    op.create_unique_constraint(
        "uq_tenant_operational_policy_identity_revision",
        "tenant_operational_policies",
        ["company_id", "id", "revision"],
    )

    op.add_column(
        "inventory_transfer_headers",
        sa.Column("tenant_policy_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "inventory_transfer_headers",
        sa.Column("tenant_policy_revision", sa.Integer(), nullable=True),
    )

    op.create_foreign_key(
        "fk_transfer_header_tenant_policy_snapshot",
        "inventory_transfer_headers",
        "tenant_operational_policies",
        ["company_id", "tenant_policy_id", "tenant_policy_revision"],
        ["company_id", "id", "revision"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "chk_transfer_header_policy_snapshot_pair",
        "inventory_transfer_headers",
        "((tenant_policy_id IS NULL AND tenant_policy_revision IS NULL) OR "
        "(tenant_policy_id IS NOT NULL AND tenant_policy_revision IS NOT NULL))",
    )
    op.create_check_constraint(
        "chk_transfer_header_special_policy_required",
        "inventory_transfer_headers",
        "transfer_purpose NOT IN "
        "('RETURN_TO_VENDOR','QUARANTINE','RECALL_RETURN','DISPOSAL') "
        "OR (tenant_policy_id IS NOT NULL AND tenant_policy_revision IS NOT NULL)",
    )
    op.create_index(
        "ix_transfer_header_policy_snapshot",
        "inventory_transfer_headers",
        ["company_id", "tenant_policy_id", "tenant_policy_revision"],
        unique=False,
    )

    op.execute(
        "INSERT INTO permissions (code) VALUES "
        "('transfer.special.quarantine'),"
        "('transfer.special.recall_return'),"
        "('transfer.special.return_to_vendor'),"
        "('transfer.special.disposal'),"
        "('transfer.warehouse_balancing_override') "
        "ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    # Do not erase immutable policy evidence. Permission catalog rows also stay.
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS ("
        "SELECT 1 FROM inventory_transfer_headers "
        "WHERE tenant_policy_id IS NOT NULL "
        "OR tenant_policy_revision IS NOT NULL "
        "LIMIT 1"
        ") THEN "
        "RAISE EXCEPTION "
        "'Refusing destructive downgrade: transfer policy snapshots exist'; "
        "END IF; END $$;"
    )

    op.drop_index(
        "ix_transfer_header_policy_snapshot",
        table_name="inventory_transfer_headers",
    )
    op.drop_constraint(
        "chk_transfer_header_special_policy_required",
        "inventory_transfer_headers",
        type_="check",
    )
    op.drop_constraint(
        "chk_transfer_header_policy_snapshot_pair",
        "inventory_transfer_headers",
        type_="check",
    )
    op.drop_constraint(
        "fk_transfer_header_tenant_policy_snapshot",
        "inventory_transfer_headers",
        type_="foreignkey",
    )
    op.drop_column("inventory_transfer_headers", "tenant_policy_revision")
    op.drop_column("inventory_transfer_headers", "tenant_policy_id")
    op.drop_constraint(
        "uq_tenant_operational_policy_identity_revision",
        "tenant_operational_policies",
        type_="unique",
    )
