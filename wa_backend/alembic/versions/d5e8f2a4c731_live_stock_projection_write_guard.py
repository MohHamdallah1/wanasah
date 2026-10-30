"""Fail closed on untrusted Live Stock projection row writes.

Revision ID: d5e8f2a4c731
Revises: c3e7a5d9b214
"""
from alembic import op

revision = "d5e8f2a4c731"
down_revision = "c3e7a5d9b214"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.live_stock_projection_untrusted_write_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            affected_company_id integer;
            affected_warehouse_id integer;
        BEGIN
            IF COALESCE(
                current_setting(
                    'app.live_stock_projection_trusted_write',
                    true
                ),
                'off'
            ) = 'on' THEN
                RETURN NULL;
            END IF;

            IF TG_OP = 'DELETE' THEN
                affected_company_id := OLD.company_id;
                affected_warehouse_id := OLD.warehouse_location_id;
            ELSE
                affected_company_id := NEW.company_id;
                affected_warehouse_id := NEW.warehouse_location_id;
            END IF;

            UPDATE inventory_live_stock_warehouse_summaries
            SET projection_state = 'DEGRADED',
                revision = revision + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE company_id = affected_company_id
              AND warehouse_location_id = affected_warehouse_id
              AND projection_state = 'READY';

            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_live_stock_projection_untrusted_write_guard
        AFTER INSERT OR UPDATE OR DELETE
        ON inventory_live_stock_projection
        FOR EACH ROW
        EXECUTE FUNCTION public.live_stock_projection_untrusted_write_guard()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_live_stock_projection_untrusted_write_guard
        ON inventory_live_stock_projection
        """
    )
    op.execute(
        """
        DROP FUNCTION IF EXISTS public.live_stock_projection_untrusted_write_guard()
        """
    )
