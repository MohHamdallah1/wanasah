"""Linked customer-return financial cost provenance.

Revision ID: e1b7c4d9a203
Revises: d5e8f2a4c731
"""
from alembic import op

revision = "e1b7c4d9a203"
down_revision = "d5e8f2a4c731"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE inventory_cost_events "
        "ADD COLUMN source_cost_event_id BIGINT NULL"
    )
    op.execute(
        "CREATE INDEX ix_inventory_cost_events_source_cost_event_id "
        "ON inventory_cost_events(source_cost_event_id)"
    )
    op.execute(
        """
        ALTER TABLE inventory_cost_events
        ADD CONSTRAINT fk_inventory_cost_event_tenant_source_cost
        FOREIGN KEY (company_id, source_cost_event_id)
        REFERENCES inventory_cost_events(company_id, id)
        ON DELETE RESTRICT
        """
    )
    op.execute(
        """
        ALTER TABLE inventory_cost_events
        ADD CONSTRAINT uq_inventory_cost_event_source_cost
        UNIQUE (company_id, source_cost_event_id)
        """
    )
    op.execute(
        "ALTER TABLE inventory_cost_events "
        "DROP CONSTRAINT chk_inventory_cost_event_basis"
    )
    op.execute(
        """
        ALTER TABLE inventory_cost_events
        ADD CONSTRAINT chk_inventory_cost_event_basis
        CHECK (
            cost_basis IN (
                'OPENING_VALUATION','PURCHASE_ACTUAL','MOVING_AVERAGE',
                'FIFO_LAYER','ORIGINAL_REVERSAL','CURRENT_AVERAGE_ESTIMATE',
                'LINKED_RETURN_COST','LEGACY_FIFO_STATE_BRIDGE'
            )
        )
        """
    )
    op.execute(
        """
        ALTER TABLE inventory_cost_events
        ADD CONSTRAINT chk_inventory_cost_event_source_cost_scope
        CHECK (
            (
                cost_basis = 'LINKED_RETURN_COST'
                AND event_type = 'ADJUSTMENT_IN'
                AND source_cost_event_id IS NOT NULL
            )
            OR
            (
                cost_basis <> 'LINKED_RETURN_COST'
                AND source_cost_event_id IS NULL
            )
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM inventory_cost_events
                WHERE source_cost_event_id IS NOT NULL
                   OR cost_basis = 'LINKED_RETURN_COST'
                LIMIT 1
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade linked return cost provenance after financial evidence exists.';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        "ALTER TABLE inventory_cost_events "
        "DROP CONSTRAINT chk_inventory_cost_event_source_cost_scope"
    )
    op.execute(
        "ALTER TABLE inventory_cost_events "
        "DROP CONSTRAINT uq_inventory_cost_event_source_cost"
    )
    op.execute(
        "ALTER TABLE inventory_cost_events "
        "DROP CONSTRAINT fk_inventory_cost_event_tenant_source_cost"
    )
    op.execute(
        "DROP INDEX IF EXISTS ix_inventory_cost_events_source_cost_event_id"
    )
    op.execute(
        "ALTER TABLE inventory_cost_events DROP COLUMN source_cost_event_id"
    )
    op.execute(
        "ALTER TABLE inventory_cost_events "
        "DROP CONSTRAINT chk_inventory_cost_event_basis"
    )
    op.execute(
        """
        ALTER TABLE inventory_cost_events
        ADD CONSTRAINT chk_inventory_cost_event_basis
        CHECK (
            cost_basis IN (
                'OPENING_VALUATION','PURCHASE_ACTUAL','MOVING_AVERAGE',
                'FIFO_LAYER','ORIGINAL_REVERSAL','CURRENT_AVERAGE_ESTIMATE',
                'LEGACY_FIFO_STATE_BRIDGE'
            )
        )
        """
    )
