"""stage5e remove legacy product variant prices

Revision ID: e42b7c9d5a13
Revises: c74f1a2e6d90
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e42b7c9d5a13"
down_revision: Union[str, Sequence[str], None] = "c74f1a2e6d90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    legacy_rows = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM product_variants
            WHERE price_per_carton IS NOT NULL
               OR price_per_pack IS NOT NULL
            """
        )
    ).scalar_one()

    if int(legacy_rows) != 0:
        raise RuntimeError(
            "Refusing Stage5E migration: product_variants still contains "
            "non-NULL legacy price data. Verify/migrate those rows into the "
            "temporal PriceBook authority before dropping the columns."
        )

    # Remove the two known local checks explicitly. Column drops still use no
    # CASCADE, so any unknown external dependency fails closed.
    op.drop_constraint(
        "chk_product_variant_pack_price",
        "product_variants",
        type_="check",
    )
    op.drop_constraint(
        "chk_product_variant_carton_price",
        "product_variants",
        type_="check",
    )
    op.drop_column("product_variants", "price_per_pack")
    op.drop_column("product_variants", "price_per_carton")


def downgrade() -> None:
    # Schema compatibility can be restored, but dropped historical values cannot.
    op.add_column(
        "product_variants",
        sa.Column("price_per_carton", sa.Numeric(12, 3), nullable=True),
    )
    op.add_column(
        "product_variants",
        sa.Column("price_per_pack", sa.Numeric(12, 3), nullable=True),
    )
    op.create_check_constraint(
        "chk_product_variant_carton_price",
        "product_variants",
        "price_per_carton >= 0",
    )
    op.create_check_constraint(
        "chk_product_variant_pack_price",
        "product_variants",
        "price_per_pack IS NULL OR price_per_pack >= 0",
    )
