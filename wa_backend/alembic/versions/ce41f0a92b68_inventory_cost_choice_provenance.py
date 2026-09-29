"""Attribute explicit costing-policy selection without rewriting legacy costing history.

Revision ID: ce41f0a92b68
Revises: ae9c4d8b62f0
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "ce41f0a92b68"
down_revision = "ae9c4d8b62f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing active policies MUST retain their method, version and lock date.
    # Existing inactive defaults cannot be proven selected: leave provenance NULL.
    op.add_column("inventory_cost_policies", sa.Column("selected_at", sa.DateTime(), nullable=True))
    op.add_column("inventory_cost_policies", sa.Column("selected_by", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_inventory_cost_policy_tenant_selector",
        "inventory_cost_policies",
        "drivers",
        ["company_id", "selected_by"],
        ["company_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "chk_inventory_cost_policy_selection_pair",
        "inventory_cost_policies",
        "(selected_at IS NULL AND selected_by IS NULL) "
        "OR (selected_at IS NOT NULL AND selected_by IS NOT NULL)",
    )


def downgrade() -> None:
    # Do not discard provenance of any newly confirmed company policy.
    confirmed = op.get_bind().execute(
        sa.text(
            "SELECT EXISTS ("
            " SELECT 1 FROM inventory_cost_policies "
            " WHERE selected_at IS NOT NULL OR selected_by IS NOT NULL)"
        )
    ).scalar()
    if confirmed:
        raise RuntimeError(
            "Cannot downgrade costing selection provenance: confirmed choices exist."
        )
    op.drop_constraint(
        "chk_inventory_cost_policy_selection_pair",
        "inventory_cost_policies",
        type_="check",
    )
    op.drop_constraint(
        "fk_inventory_cost_policy_tenant_selector",
        "inventory_cost_policies",
        type_="foreignkey",
    )
    op.drop_column("inventory_cost_policies", "selected_by")
    op.drop_column("inventory_cost_policies", "selected_at")
