"""Permit explicit per-base-unit Product Import cost references.

Revision ID: e5a7c1d9f042
Revises: c7f3a8e5d912

No data backfill or changes to import staging, indexes, job locks or queue.
"""
from alembic import op


revision = "e5a7c1d9f042"
down_revision = "c7f3a8e5d912"
branch_labels = None
depends_on = None


_OLD_SOURCE = (
    "(source = 'MANUAL_PRODUCT' AND source_cost_event_id IS NULL) OR "
    "(source = 'SUPPLIER_INBOUND' AND source_cost_event_id IS NOT NULL)"
)
_NEW_SOURCE = (
    "(source IN ('MANUAL_PRODUCT', 'PRODUCT_IMPORT') AND source_cost_event_id IS NULL) OR "
    "(source = 'SUPPLIER_INBOUND' AND source_cost_event_id IS NOT NULL)"
)


def upgrade() -> None:
    op.drop_constraint("pcrc_operation", "purchase_cost_reference_commands", type_="check")
    op.create_check_constraint(
        "pcrc_operation", "purchase_cost_reference_commands",
        "operation IN ('MANUAL_PRODUCT_SET','SUPPLIER_INBOUND_SET','PRODUCT_IMPORT_SET')",
    )
    for table, name in (
        ("purchase_cost_references", "pcr_source"),
        ("purchase_cost_reference_changes", "pcrh_source"),
    ):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, _NEW_SOURCE)


def downgrade() -> None:
    # Never silently discard or invalidate a committed imported reference.
    op.execute("""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM purchase_cost_references WHERE source = 'PRODUCT_IMPORT')
          OR EXISTS (SELECT 1 FROM purchase_cost_reference_changes WHERE source = 'PRODUCT_IMPORT')
          OR EXISTS (SELECT 1 FROM purchase_cost_reference_commands WHERE operation = 'PRODUCT_IMPORT_SET')
          THEN RAISE EXCEPTION 'Refusing downgrade with imported cost reference evidence';
          END IF;
        END
        $$;
    """)
    for table, name in (
        ("purchase_cost_references", "pcr_source"),
        ("purchase_cost_reference_changes", "pcrh_source"),
    ):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, _OLD_SOURCE)
    op.drop_constraint("pcrc_operation", "purchase_cost_reference_commands", type_="check")
    op.create_check_constraint(
        "pcrc_operation", "purchase_cost_reference_commands",
        "operation IN ('MANUAL_PRODUCT_SET','SUPPLIER_INBOUND_SET')",
    )
