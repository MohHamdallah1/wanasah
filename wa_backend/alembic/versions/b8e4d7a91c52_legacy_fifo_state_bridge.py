"""Allow explicit legacy FIFO state bridge evidence.

Revision ID: b8e4d7a91c52
Revises: a4c9e7d2f631
"""
from alembic import op

revision = "b8e4d7a91c52"
down_revision = "a4c9e7d2f631"
branch_labels = None
depends_on = None

_TABLE = "inventory_cost_events"
_CONSTRAINT = "chk_inventory_cost_event_basis"
_OLD = (
    "cost_basis IN ('PURCHASE_ACTUAL','MOVING_AVERAGE','FIFO_LAYER',"
    "'ORIGINAL_REVERSAL','CURRENT_AVERAGE_ESTIMATE')"
)
_NEW = (
    "cost_basis IN ('PURCHASE_ACTUAL','MOVING_AVERAGE','FIFO_LAYER',"
    "'ORIGINAL_REVERSAL','CURRENT_AVERAGE_ESTIMATE','LEGACY_FIFO_STATE_BRIDGE')"
)


def _replace(check_sql: str) -> None:
    # The constraint predates the ORM naming convention and this is already its
    # physical database name. Mark it fixed so Alembic does not rename it.
    fixed_name = op.f(_CONSTRAINT)
    op.drop_constraint(fixed_name, _TABLE, type_="check")
    op.create_check_constraint(fixed_name, _TABLE, check_sql)


def upgrade() -> None:
    _replace(_NEW)


def downgrade() -> None:
    # Never make immutable costing history invalid merely to permit a downgrade.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM inventory_cost_events
                WHERE cost_basis = 'LEGACY_FIFO_STATE_BRIDGE'
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade: legacy FIFO bridge cost evidence exists';
            END IF;
        END
        $$;
        """
    )
    _replace(_OLD)
