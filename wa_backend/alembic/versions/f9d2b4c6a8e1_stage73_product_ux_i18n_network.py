"""Stage 7.3 product package vocabulary and shared-barcode intent.

Revision ID: f9d2b4c6a8e1
Revises: f8c4e6a2b1d9
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f9d2b4c6a8e1"
down_revision = "f8c4e6a2b1d9"
branch_labels = None
depends_on = None

_ADDED_UOMS = (
    ("PACK", "باكيت"),
    ("BAG", "كيس"),
    ("SACK", "شوال"),
    ("TRAY", "صينية"),
    ("CRATE", "قفص"),
    ("BUNDLE", "حزمة"),
)


def upgrade() -> None:
    op.add_column(
        "product_variants",
        sa.Column(
            "package_uses_base_barcode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    values = ", ".join(
        f"('{code}', '{name}')"
        for code, name in _ADDED_UOMS
    )
    op.execute(
        f"""
        INSERT INTO uom (code, name)
        VALUES {values}
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM product_variants
                WHERE package_uses_base_barcode IS TRUE
            ) THEN
                RAISE EXCEPTION
                    'Refusing downgrade: shared package barcode intent exists';
            END IF;
        END
        $$;
        """
    )

    codes = ", ".join(
        f"'{code}'"
        for code, _name in _ADDED_UOMS
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM uom u
                WHERE u.code IN ({codes})
                  AND (
                    EXISTS (
                        SELECT 1
                        FROM product_variants v
                        WHERE v.base_uom_id = u.id
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM product_uom_conversions c
                        WHERE c.from_uom_id = u.id
                           OR c.to_uom_id = u.id
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM product_barcodes b
                        WHERE b.uom_id = u.id
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM price_book_entries p
                        WHERE p.uom_id = u.id
                    )
                  )
            ) THEN
                RAISE EXCEPTION
                    'Refusing downgrade: Stage 7.3 UOMs are in use';
            END IF;
        END
        $$;
        """
    )

    op.drop_column(
        "product_variants",
        "package_uses_base_barcode",
    )
    op.execute(
        f"DELETE FROM uom WHERE code IN ({codes})"
    )
