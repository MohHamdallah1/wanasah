"""Opening inventory valuation financial bootstrap.

Revision ID: 9c4f8a2d7e31
Revises: e5a7c1d9f042
"""
from __future__ import annotations

import os
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import make_url

revision = "9c4f8a2d7e31"
down_revision = "e5a7c1d9f042"
branch_labels = None
depends_on = None

_TABLES = (
    "inventory_opening_valuations",
    "inventory_opening_valuation_lines",
)


def _runtime_role() -> str:
    raw = os.getenv("DATABASE_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL is required to grant the runtime database role.")
    role = make_url(raw).username
    if not role or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", role):
        raise RuntimeError("Runtime database role could not be resolved safely.")
    return role


def _install_rls(table: str) -> None:
    expr = "company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer"
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY {table}_tenant ON "{table}" '
        f'USING ({expr}) WITH CHECK ({expr})'
    )
    op.execute(
        f'CREATE POLICY {table}_tenant_guard ON "{table}" AS RESTRICTIVE '
        f'USING ({expr}) WITH CHECK ({expr})'
    )


def _install_append_only(table: str) -> None:
    op.execute(
        f"""
        CREATE TRIGGER trg_{table}_append_only
        BEFORE UPDATE OR DELETE
        ON {table}
        FOR EACH ROW
        EXECUTE FUNCTION prevent_inventory_cost_history_mutation()
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_{table}_truncate_guard
        BEFORE TRUNCATE
        ON {table}
        FOR EACH STATEMENT
        EXECUTE FUNCTION prevent_inventory_cost_history_mutation()
        """
    )


def _grant_runtime() -> None:
    role = _runtime_role().replace('"', '""')
    quoted = f'"{role}"'
    op.execute(f"GRANT USAGE ON SCHEMA public TO {quoted}")
    for table in _TABLES:
        op.execute(f"GRANT SELECT, INSERT ON TABLE {table} TO {quoted}")
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON TABLE {table} FROM {quoted}")
    for sequence in (
        "inventory_opening_valuations_id_seq",
        "inventory_opening_valuation_lines_id_seq",
    ):
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {sequence} TO {quoted}")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE inventory_opening_valuations (
            id BIGSERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            request_id UUID NOT NULL,
            method VARCHAR(30) NOT NULL,
            currency_code VARCHAR(10) NOT NULL,
            inventory_snapshot_hash VARCHAR(64) NOT NULL,
            line_count INTEGER NOT NULL,
            total_quantity NUMERIC(20,6) NOT NULL,
            total_value NUMERIC(20,6) NOT NULL,
            posted_by INTEGER NOT NULL,
            posted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_inventory_opening_valuation_company UNIQUE (company_id),
            CONSTRAINT uq_inventory_opening_valuations_company_id UNIQUE (company_id, id),
            CONSTRAINT uq_inventory_opening_valuation_request UNIQUE (company_id, request_id),
            CONSTRAINT fk_inventory_opening_valuation_tenant_actor
                FOREIGN KEY (company_id, posted_by)
                REFERENCES drivers(company_id, id) ON DELETE RESTRICT,
            CONSTRAINT chk_inventory_opening_valuation_method
                CHECK (method IN ('MOVING_AVERAGE','FIFO')),
            CONSTRAINT chk_inventory_opening_valuation_currency
                CHECK (length(trim(currency_code)) BETWEEN 3 AND 10),
            CONSTRAINT chk_inventory_opening_valuation_snapshot_hash
                CHECK (length(inventory_snapshot_hash) = 64),
            CONSTRAINT chk_inventory_opening_valuation_line_count CHECK (line_count > 0),
            CONSTRAINT chk_inventory_opening_valuation_total_quantity CHECK (total_quantity > 0),
            CONSTRAINT chk_inventory_opening_valuation_total_value CHECK (total_value >= 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_inventory_opening_valuations_company_id "
        "ON inventory_opening_valuations(company_id)"
    )
    op.execute(
        "CREATE INDEX ix_inventory_opening_valuations_posted_by "
        "ON inventory_opening_valuations(posted_by)"
    )
    op.execute(
        "CREATE INDEX ix_inventory_opening_valuations_posted_at "
        "ON inventory_opening_valuations(posted_at)"
    )

    op.execute(
        """
        CREATE TABLE inventory_opening_valuation_lines (
            id BIGSERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            opening_valuation_id BIGINT NOT NULL,
            product_variant_id INTEGER NOT NULL,
            quantity NUMERIC(20,6) NOT NULL,
            unit_cost NUMERIC(20,6) NOT NULL,
            total_value NUMERIC(20,6) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_inventory_opening_valuation_lines_company_id UNIQUE (company_id, id),
            CONSTRAINT uq_inventory_opening_valuation_variant
                UNIQUE (company_id, opening_valuation_id, product_variant_id),
            CONSTRAINT fk_inventory_opening_line_tenant_header
                FOREIGN KEY (company_id, opening_valuation_id)
                REFERENCES inventory_opening_valuations(company_id, id)
                ON DELETE RESTRICT,
            CONSTRAINT fk_inventory_opening_line_tenant_variant
                FOREIGN KEY (company_id, product_variant_id)
                REFERENCES product_variants(company_id, id)
                ON DELETE RESTRICT,
            CONSTRAINT chk_inventory_opening_line_quantity CHECK (quantity > 0),
            CONSTRAINT chk_inventory_opening_line_unit_cost CHECK (unit_cost >= 0),
            CONSTRAINT chk_inventory_opening_line_total_value CHECK (total_value >= 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_inventory_opening_valuation_lines_company_id "
        "ON inventory_opening_valuation_lines(company_id)"
    )
    op.execute(
        "CREATE INDEX ix_inventory_opening_valuation_lines_opening_valuation_id "
        "ON inventory_opening_valuation_lines(opening_valuation_id)"
    )
    op.execute(
        "CREATE INDEX ix_inventory_opening_valuation_lines_product_variant_id "
        "ON inventory_opening_valuation_lines(product_variant_id)"
    )

    op.alter_column(
        "inventory_cost_events",
        "inventory_movement_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.execute(
        "ALTER TABLE inventory_cost_events "
        "ADD COLUMN opening_valuation_line_id BIGINT NULL"
    )
    op.execute(
        "CREATE INDEX ix_inventory_cost_events_opening_valuation_line_id "
        "ON inventory_cost_events(opening_valuation_line_id)"
    )
    op.execute(
        """
        ALTER TABLE inventory_cost_events
        ADD CONSTRAINT fk_inventory_cost_event_tenant_opening_line
        FOREIGN KEY (company_id, opening_valuation_line_id)
        REFERENCES inventory_opening_valuation_lines(company_id, id)
        ON DELETE RESTRICT
        """
    )
    op.execute(
        """
        ALTER TABLE inventory_cost_events
        ADD CONSTRAINT uq_inventory_cost_event_opening_batch
        UNIQUE (company_id, opening_valuation_line_id, batch_id)
        """
    )

    op.execute(
        "ALTER TABLE inventory_cost_events "
        "DROP CONSTRAINT chk_inventory_cost_event_type"
    )
    op.execute(
        """
        ALTER TABLE inventory_cost_events
        ADD CONSTRAINT chk_inventory_cost_event_type
        CHECK (
            event_type IN (
                'OPENING_BALANCE','PURCHASE_IN','OUTBOUND',
                'REVERSAL_IN','REVERSAL_OUT','ADJUSTMENT_IN'
            )
        )
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
                'LEGACY_FIFO_STATE_BRIDGE'
            )
        )
        """
    )
    op.execute(
        """
        ALTER TABLE inventory_cost_events
        ADD CONSTRAINT chk_inventory_cost_event_source_scope
        CHECK (
            (
                inventory_movement_id IS NOT NULL
                AND opening_valuation_line_id IS NULL
                AND event_type <> 'OPENING_BALANCE'
            )
            OR
            (
                inventory_movement_id IS NULL
                AND opening_valuation_line_id IS NOT NULL
                AND event_type = 'OPENING_BALANCE'
                AND cost_basis = 'OPENING_VALUATION'
            )
        )
        """
    )

    for table in _TABLES:
        _install_rls(table)
        _install_append_only(table)
    _grant_runtime()


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM inventory_opening_valuations LIMIT 1)
               OR EXISTS (
                    SELECT 1
                    FROM inventory_cost_events
                    WHERE opening_valuation_line_id IS NOT NULL
                    LIMIT 1
               )
            THEN
                RAISE EXCEPTION
                    'Cannot downgrade opening valuation foundation after financial evidence exists.';
            END IF;
        END
        $$;
        """
    )

    op.execute(
        "ALTER TABLE inventory_cost_events "
        "DROP CONSTRAINT chk_inventory_cost_event_source_scope"
    )
    op.execute(
        "ALTER TABLE inventory_cost_events "
        "DROP CONSTRAINT uq_inventory_cost_event_opening_batch"
    )
    op.execute(
        "ALTER TABLE inventory_cost_events "
        "DROP CONSTRAINT fk_inventory_cost_event_tenant_opening_line"
    )
    op.execute(
        "DROP INDEX IF EXISTS ix_inventory_cost_events_opening_valuation_line_id"
    )
    op.execute(
        "ALTER TABLE inventory_cost_events DROP COLUMN opening_valuation_line_id"
    )

    op.execute(
        "ALTER TABLE inventory_cost_events "
        "DROP CONSTRAINT chk_inventory_cost_event_type"
    )
    op.execute(
        """
        ALTER TABLE inventory_cost_events
        ADD CONSTRAINT chk_inventory_cost_event_type
        CHECK (
            event_type IN (
                'PURCHASE_IN','OUTBOUND','REVERSAL_IN','REVERSAL_OUT','ADJUSTMENT_IN'
            )
        )
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
                'PURCHASE_ACTUAL','MOVING_AVERAGE','FIFO_LAYER',
                'ORIGINAL_REVERSAL','CURRENT_AVERAGE_ESTIMATE',
                'LEGACY_FIFO_STATE_BRIDGE'
            )
        )
        """
    )
    op.execute(
        "ALTER TABLE inventory_cost_events "
        "ALTER COLUMN inventory_movement_id SET NOT NULL"
    )

    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE {table}")
