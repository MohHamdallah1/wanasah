"""stage6h2a mixed uom and flexible reward contracts

Revision ID: c3f8a1d6e2b4
Revises: 91e6b4c8d2f0
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3f8a1d6e2b4"
down_revision: Union[str, Sequence[str], None] = "91e6b4c8d2f0"
branch_labels = None
depends_on = None


_OFFER_TABLES = (
    "offer_versions",
    "offer_version_scopes",
    "offer_version_products",
)


def _disable_rls_for_admin_migration() -> None:
    # FORCE RLS can hide tenant rows from a normal app connection. The
    # migration transaction temporarily disables RLS only on the three offer
    # configuration tables so the empty-data assertion cannot produce a false
    # negative. Any failure rolls the DDL back atomically.
    for table_name in _OFFER_TABLES:
        op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')


def _restore_rls() -> None:
    for table_name in _OFFER_TABLES:
        op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')


def _assert_offer_tables_empty() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM offer_versions)
               OR EXISTS (SELECT 1 FROM offer_version_scopes)
               OR EXISTS (SELECT 1 FROM offer_version_products) THEN
                RAISE EXCEPTION
                    'Stage 6H.2A requires empty offer configuration tables; delete/reset test offer data before upgrading';
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    # Owner explicitly approved deleting/resetting the current test offer data.
    # We fail closed instead of inventing a compatibility/backfill path.
    _disable_rls_for_admin_migration()
    _assert_offer_tables_empty()

    op.add_column(
        "offer_version_scopes",
        sa.Column("uom_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_offer_scope_uom",
        "offer_version_scopes",
        "uom",
        ["uom_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_index(
        "uq_offer_scope_product",
        table_name="offer_version_scopes",
    )
    op.drop_constraint(
        "ck_offer_version_scopes_offer_scope_target_matches_type",
        "offer_version_scopes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_offer_version_scopes_offer_scope_target_matches_type",
        "offer_version_scopes",
        """
        (scope_type = 'PRODUCT_VARIANT' AND product_variant_id IS NOT NULL
            AND customer_id IS NULL AND branch_id IS NULL AND channel_code IS NULL)
        OR
        (scope_type = 'CUSTOMER' AND customer_id IS NOT NULL
            AND product_variant_id IS NULL AND uom_id IS NULL
            AND branch_id IS NULL AND channel_code IS NULL)
        OR
        (scope_type = 'BRANCH' AND branch_id IS NOT NULL
            AND product_variant_id IS NULL AND uom_id IS NULL
            AND customer_id IS NULL AND channel_code IS NULL)
        OR
        (scope_type = 'CHANNEL' AND channel_code IS NOT NULL
            AND length(trim(channel_code)) > 0
            AND product_variant_id IS NULL AND uom_id IS NULL
            AND customer_id IS NULL AND branch_id IS NULL)
        """,
    )
    op.create_index(
        "uq_offer_scope_product_all_uom",
        "offer_version_scopes",
        [
            "company_id",
            "offer_version_id",
            "product_variant_id",
        ],
        unique=True,
        postgresql_where=sa.text(
            "scope_type = 'PRODUCT_VARIANT' AND uom_id IS NULL"
        ),
    )
    op.create_index(
        "uq_offer_scope_product_specific_uom",
        "offer_version_scopes",
        [
            "company_id",
            "offer_version_id",
            "product_variant_id",
            "uom_id",
        ],
        unique=True,
        postgresql_where=sa.text(
            "scope_type = 'PRODUCT_VARIANT' AND uom_id IS NOT NULL"
        ),
    )

    op.add_column(
        "offer_version_products",
        sa.Column("uom_id", sa.Integer(), nullable=False),
    )
    op.add_column(
        "offer_version_products",
        sa.Column(
            "quantity_per_application",
            sa.Numeric(20, 6),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_offer_product_uom",
        "offer_version_products",
        "uom",
        ["uom_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_offer_version_product_role_variant",
        "offer_version_products",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_offer_version_product_role_variant_uom",
        "offer_version_products",
        [
            "company_id",
            "offer_version_id",
            "role",
            "product_variant_id",
            "uom_id",
        ],
    )
    op.create_check_constraint(
        "ck_offer_version_products_offer_product_quantity_shape",
        "offer_version_products",
        """
        (role = 'QUALIFYING' AND quantity_per_application IS NULL)
        OR
        (
            role IN ('REWARD','BUNDLE_COMPONENT')
            AND quantity_per_application IS NOT NULL
            AND quantity_per_application > 0
        )
        """,
    )

    _restore_rls()


def downgrade() -> None:
    # Reverse only before any offer data is created; otherwise downgrade would
    # silently destroy UOM/quantity semantics.
    _disable_rls_for_admin_migration()
    _assert_offer_tables_empty()

    op.drop_constraint(
        "ck_offer_version_products_offer_product_quantity_shape",
        "offer_version_products",
        type_="check",
    )
    op.drop_constraint(
        "uq_offer_version_product_role_variant_uom",
        "offer_version_products",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_offer_version_product_role_variant",
        "offer_version_products",
        [
            "company_id",
            "offer_version_id",
            "role",
            "product_variant_id",
        ],
    )
    op.drop_constraint(
        "fk_offer_product_uom",
        "offer_version_products",
        type_="foreignkey",
    )
    op.drop_column(
        "offer_version_products",
        "quantity_per_application",
    )
    op.drop_column(
        "offer_version_products",
        "uom_id",
    )

    op.drop_index(
        "uq_offer_scope_product_specific_uom",
        table_name="offer_version_scopes",
    )
    op.drop_index(
        "uq_offer_scope_product_all_uom",
        table_name="offer_version_scopes",
    )
    op.drop_constraint(
        "ck_offer_version_scopes_offer_scope_target_matches_type",
        "offer_version_scopes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_offer_version_scopes_offer_scope_target_matches_type",
        "offer_version_scopes",
        """
        (scope_type = 'PRODUCT_VARIANT' AND product_variant_id IS NOT NULL
            AND customer_id IS NULL AND branch_id IS NULL AND channel_code IS NULL)
        OR
        (scope_type = 'CUSTOMER' AND customer_id IS NOT NULL
            AND product_variant_id IS NULL AND branch_id IS NULL AND channel_code IS NULL)
        OR
        (scope_type = 'BRANCH' AND branch_id IS NOT NULL
            AND product_variant_id IS NULL AND customer_id IS NULL AND channel_code IS NULL)
        OR
        (scope_type = 'CHANNEL' AND channel_code IS NOT NULL
            AND length(trim(channel_code)) > 0
            AND product_variant_id IS NULL AND customer_id IS NULL AND branch_id IS NULL)
        """,
    )
    op.create_index(
        "uq_offer_scope_product",
        "offer_version_scopes",
        [
            "company_id",
            "offer_version_id",
            "product_variant_id",
        ],
        unique=True,
        postgresql_where=sa.text(
            "scope_type = 'PRODUCT_VARIANT'"
        ),
    )
    op.drop_constraint(
        "fk_offer_scope_uom",
        "offer_version_scopes",
        type_="foreignkey",
    )
    op.drop_column(
        "offer_version_scopes",
        "uom_id",
    )

    _restore_rls()
