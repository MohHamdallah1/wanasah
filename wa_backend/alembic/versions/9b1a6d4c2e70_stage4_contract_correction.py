"""stage4 contract correction

Revision ID: 9b1a6d4c2e70
Revises: 57e120ab83c1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9b1a6d4c2e70"
down_revision: Union[str, Sequence[str], None] = "57e120ab83c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "chk_product_variant_min_shelf_life",
        "product_variants",
        type_="check",
    )
    op.drop_column(
        "product_variants",
        "min_shelf_life_days",
    )

    op.add_column(
        "inventory_stock_policies",
        sa.Column(
            "minimum_remaining_shelf_life_days",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "chk_inventory_stock_policy_min_shelf_life",
        "inventory_stock_policies",
        "minimum_remaining_shelf_life_days >= 0",
    )

    op.drop_constraint(
        "chk_transfer_header_purpose",
        "inventory_transfer_headers",
        type_="check",
    )
    op.create_check_constraint(
        "chk_transfer_header_purpose",
        "inventory_transfer_headers",
        "transfer_purpose IN ("
        "'REPLENISHMENT', "
        "'ROUTE_LOAD', "
        "'ROUTE_RETURN', "
        "'WAREHOUSE_BALANCING', "
        "'RETURN_TO_VENDOR', "
        "'QUARANTINE', "
        "'RECALL_RETURN', "
        "'DISPOSAL'"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint(
        "chk_transfer_header_purpose",
        "inventory_transfer_headers",
        type_="check",
    )
    op.create_check_constraint(
        "chk_transfer_header_purpose",
        "inventory_transfer_headers",
        "transfer_purpose IN ("
        "'REPLENISHMENT', "
        "'ROUTE_LOAD', "
        "'ROUTE_RETURN', "
        "'WAREHOUSE_BALANCING', "
        "'RETURN_TO_VENDOR', "
        "'QUARANTINE', "
        "'DISPOSAL', "
        "'CONSUMPTION'"
        ")",
    )

    op.drop_constraint(
        "chk_inventory_stock_policy_min_shelf_life",
        "inventory_stock_policies",
        type_="check",
    )
    op.drop_column(
        "inventory_stock_policies",
        "minimum_remaining_shelf_life_days",
    )

    op.add_column(
        "product_variants",
        sa.Column(
            "min_shelf_life_days",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "chk_product_variant_min_shelf_life",
        "product_variants",
        "min_shelf_life_days IS NULL OR min_shelf_life_days >= 0",
    )