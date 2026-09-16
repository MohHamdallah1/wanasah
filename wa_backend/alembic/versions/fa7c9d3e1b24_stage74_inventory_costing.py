"""Stage 7.4 perpetual inventory costing.

Revision ID: fa7c9d3e1b24
Revises: f9d2b4c6a8e1
"""
from __future__ import annotations

import os
import re

from alembic import op
from sqlalchemy.engine import make_url

revision = "fa7c9d3e1b24"
down_revision = "f9d2b4c6a8e1"
branch_labels = None
depends_on = None

_TABLES = (
    "inventory_cost_policies",
    "inventory_cost_states",
    "inventory_cost_events",
    "inventory_cost_layers",
    "inventory_cost_allocations",
)


def _rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f"""
        CREATE POLICY {table}_company_isolation
        ON "{table}"
        FOR ALL
        USING (
            company_id =
            NULLIF(current_setting('app.current_tenant', true), '')::integer
        )
        WITH CHECK (
            company_id =
            NULLIF(current_setting('app.current_tenant', true), '')::integer
        )
        """
    )


def _runtime_role() -> str:
    raw = os.getenv("DATABASE_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL is required to grant the runtime database role.")
    role = make_url(raw).username
    if not role or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", role):
        raise RuntimeError("Runtime database role could not be resolved safely.")
    return role


def _grant_runtime_privileges() -> None:
    role = _runtime_role().replace('"', '""')
    quoted = f'"{role}"'
    op.execute(f"GRANT USAGE ON SCHEMA public TO {quoted}")
    for table in (
        "inventory_cost_policies",
        "inventory_cost_states",
        "inventory_cost_layers",
    ):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON TABLE {table} TO {quoted}")
        op.execute(f"REVOKE DELETE, TRUNCATE ON TABLE {table} FROM {quoted}")
    for table in (
        "inventory_cost_events",
        "inventory_cost_allocations",
    ):
        op.execute(f"GRANT SELECT, INSERT ON TABLE {table} TO {quoted}")
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON TABLE {table} FROM {quoted}")
    for sequence in (
        "inventory_cost_policies_id_seq",
        "inventory_cost_states_id_seq",
        "inventory_cost_events_id_seq",
        "inventory_cost_layers_id_seq",
        "inventory_cost_allocations_id_seq",
    ):
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {sequence} TO {quoted}")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE inventory_cost_policies (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            method VARCHAR(30) NOT NULL DEFAULT 'MOVING_AVERAGE',
            is_active BOOLEAN NOT NULL DEFAULT FALSE,
            locked_at TIMESTAMP NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER NOT NULL,
            updated_by INTEGER NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_inventory_cost_policy_company UNIQUE (company_id),
            CONSTRAINT uq_inventory_cost_policies_company_id UNIQUE (company_id, id),
            CONSTRAINT fk_inventory_cost_policy_tenant_creator
                FOREIGN KEY (company_id, created_by)
                REFERENCES drivers(company_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_inventory_cost_policy_tenant_updater
                FOREIGN KEY (company_id, updated_by)
                REFERENCES drivers(company_id, id) ON DELETE RESTRICT,
            CONSTRAINT chk_inventory_cost_policy_method
                CHECK (method IN ('MOVING_AVERAGE','FIFO')),
            CONSTRAINT chk_inventory_cost_policy_lock_pair
                CHECK (
                    (is_active IS FALSE AND locked_at IS NULL)
                    OR (is_active IS TRUE AND locked_at IS NOT NULL)
                ),
            CONSTRAINT chk_inventory_cost_policy_version CHECK (version > 0)
        )
    """)
    op.execute("CREATE INDEX ix_inventory_cost_policies_company_id ON inventory_cost_policies(company_id)")

    op.execute("""
        CREATE TABLE inventory_cost_states (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            product_variant_id INTEGER NOT NULL,
            quantity NUMERIC(20,6) NOT NULL DEFAULT 0,
            inventory_value NUMERIC(20,6) NOT NULL DEFAULT 0,
            average_unit_cost NUMERIC(20,6) NOT NULL DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_inventory_cost_state_variant UNIQUE (company_id, product_variant_id),
            CONSTRAINT uq_inventory_cost_states_company_id UNIQUE (company_id, id),
            CONSTRAINT fk_inventory_cost_state_tenant_variant
                FOREIGN KEY (company_id, product_variant_id)
                REFERENCES product_variants(company_id, id) ON DELETE RESTRICT,
            CONSTRAINT chk_inventory_cost_state_quantity CHECK (quantity >= 0),
            CONSTRAINT chk_inventory_cost_state_value CHECK (inventory_value >= 0),
            CONSTRAINT chk_inventory_cost_state_average CHECK (average_unit_cost >= 0),
            CONSTRAINT chk_inventory_cost_state_zero_pair
                CHECK (quantity <> 0 OR (inventory_value = 0 AND average_unit_cost = 0)),
            CONSTRAINT chk_inventory_cost_state_version CHECK (version > 0)
        )
    """)
    op.execute("CREATE INDEX ix_inventory_cost_state_company_variant ON inventory_cost_states(company_id, product_variant_id)")

    op.execute("""
        CREATE TABLE inventory_cost_events (
            id BIGSERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            inventory_movement_id INTEGER NOT NULL,
            product_variant_id INTEGER NOT NULL,
            batch_id INTEGER NOT NULL,
            method VARCHAR(30) NOT NULL,
            event_type VARCHAR(30) NOT NULL,
            cost_basis VARCHAR(40) NOT NULL,
            quantity NUMERIC(20,6) NOT NULL,
            unit_cost NUMERIC(20,6) NOT NULL,
            total_cost NUMERIC(20,6) NOT NULL,
            quantity_before NUMERIC(20,6) NOT NULL,
            quantity_after NUMERIC(20,6) NOT NULL,
            value_before NUMERIC(20,6) NOT NULL,
            value_after NUMERIC(20,6) NOT NULL,
            input_uom_id INTEGER NULL REFERENCES uom(id) ON DELETE RESTRICT,
            input_quantity NUMERIC(20,6) NULL,
            input_unit_cost NUMERIC(20,6) NULL,
            reversal_of_cost_event_id BIGINT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_inventory_cost_events_company_id UNIQUE (company_id, id),
            CONSTRAINT uq_inventory_cost_event_movement UNIQUE (company_id, inventory_movement_id),
            CONSTRAINT fk_inventory_cost_event_tenant_movement
                FOREIGN KEY (company_id, inventory_movement_id)
                REFERENCES inventory_movements(company_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_inventory_cost_event_tenant_variant
                FOREIGN KEY (company_id, product_variant_id)
                REFERENCES product_variants(company_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_inventory_cost_event_tenant_batch
                FOREIGN KEY (company_id, product_variant_id, batch_id)
                REFERENCES product_batches(company_id, product_variant_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_inventory_cost_event_tenant_reversal
                FOREIGN KEY (company_id, reversal_of_cost_event_id)
                REFERENCES inventory_cost_events(company_id, id) ON DELETE RESTRICT,
            CONSTRAINT chk_inventory_cost_event_method CHECK (method IN ('MOVING_AVERAGE','FIFO')),
            CONSTRAINT chk_inventory_cost_event_type
                CHECK (event_type IN ('PURCHASE_IN','OUTBOUND','REVERSAL_IN','REVERSAL_OUT','ADJUSTMENT_IN')),
            CONSTRAINT chk_inventory_cost_event_basis
                CHECK (cost_basis IN ('PURCHASE_ACTUAL','MOVING_AVERAGE','FIFO_LAYER','ORIGINAL_REVERSAL','CURRENT_AVERAGE_ESTIMATE')),
            CONSTRAINT chk_inventory_cost_event_quantity CHECK (quantity > 0),
            CONSTRAINT chk_inventory_cost_event_unit_cost CHECK (unit_cost >= 0),
            CONSTRAINT chk_inventory_cost_event_total_cost CHECK (total_cost >= 0),
            CONSTRAINT chk_inventory_cost_event_quantities CHECK (quantity_before >= 0 AND quantity_after >= 0),
            CONSTRAINT chk_inventory_cost_event_values CHECK (value_before >= 0 AND value_after >= 0),
            CONSTRAINT chk_inventory_cost_event_purchase_input_scope
                CHECK (
                    (event_type = 'PURCHASE_IN' AND input_uom_id IS NOT NULL
                     AND input_quantity IS NOT NULL AND input_unit_cost IS NOT NULL
                     AND cost_basis = 'PURCHASE_ACTUAL')
                    OR
                    (event_type <> 'PURCHASE_IN' AND input_uom_id IS NULL
                     AND input_quantity IS NULL AND input_unit_cost IS NULL)
                ),
            CONSTRAINT chk_inventory_cost_event_reversal_scope
                CHECK (
                    (event_type IN ('REVERSAL_IN','REVERSAL_OUT')
                     AND reversal_of_cost_event_id IS NOT NULL
                     AND cost_basis = 'ORIGINAL_REVERSAL')
                    OR
                    (event_type NOT IN ('REVERSAL_IN','REVERSAL_OUT')
                     AND reversal_of_cost_event_id IS NULL)
                )
        )
    """)
    op.execute("CREATE INDEX ix_inventory_cost_event_variant_time ON inventory_cost_events(company_id, product_variant_id, created_at, id)")
    op.execute("CREATE INDEX ix_inventory_cost_event_batch_time ON inventory_cost_events(company_id, product_variant_id, batch_id, created_at, id)")

    op.execute("""
        CREATE TABLE inventory_cost_layers (
            id BIGSERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            product_variant_id INTEGER NOT NULL,
            batch_id INTEGER NOT NULL,
            source_cost_event_id BIGINT NOT NULL,
            original_quantity NUMERIC(20,6) NOT NULL,
            remaining_quantity NUMERIC(20,6) NOT NULL,
            unit_cost NUMERIC(20,6) NOT NULL,
            original_value NUMERIC(20,6) NOT NULL,
            remaining_value NUMERIC(20,6) NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_inventory_cost_layers_company_id UNIQUE (company_id, id),
            CONSTRAINT uq_inventory_cost_layer_source_event UNIQUE (company_id, source_cost_event_id),
            CONSTRAINT fk_inventory_cost_layer_tenant_variant
                FOREIGN KEY (company_id, product_variant_id)
                REFERENCES product_variants(company_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_inventory_cost_layer_tenant_batch
                FOREIGN KEY (company_id, product_variant_id, batch_id)
                REFERENCES product_batches(company_id, product_variant_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_inventory_cost_layer_tenant_event
                FOREIGN KEY (company_id, source_cost_event_id)
                REFERENCES inventory_cost_events(company_id, id) ON DELETE RESTRICT,
            CONSTRAINT chk_inventory_cost_layer_original_qty CHECK (original_quantity > 0),
            CONSTRAINT chk_inventory_cost_layer_remaining_qty
                CHECK (remaining_quantity >= 0 AND remaining_quantity <= original_quantity),
            CONSTRAINT chk_inventory_cost_layer_unit_cost CHECK (unit_cost >= 0),
            CONSTRAINT chk_inventory_cost_layer_original_value CHECK (original_value >= 0),
            CONSTRAINT chk_inventory_cost_layer_remaining_value
                CHECK (remaining_value >= 0 AND remaining_value <= original_value),
            CONSTRAINT chk_inventory_cost_layer_version CHECK (version > 0)
        )
    """)
    op.execute("""
        CREATE INDEX ix_inventory_cost_layer_fifo
        ON inventory_cost_layers(company_id, product_variant_id, created_at, id)
        WHERE remaining_quantity > 0
    """)

    op.execute("""
        CREATE TABLE inventory_cost_allocations (
            id BIGSERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            cost_event_id BIGINT NOT NULL,
            cost_layer_id BIGINT NOT NULL,
            allocation_type VARCHAR(20) NOT NULL,
            quantity NUMERIC(20,6) NOT NULL,
            amount NUMERIC(20,6) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_inventory_cost_allocations_company_id UNIQUE (company_id, id),
            CONSTRAINT uq_inventory_cost_allocation_event_layer_type
                UNIQUE (company_id, cost_event_id, cost_layer_id, allocation_type),
            CONSTRAINT fk_inventory_cost_allocation_tenant_event
                FOREIGN KEY (company_id, cost_event_id)
                REFERENCES inventory_cost_events(company_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_inventory_cost_allocation_tenant_layer
                FOREIGN KEY (company_id, cost_layer_id)
                REFERENCES inventory_cost_layers(company_id, id) ON DELETE RESTRICT,
            CONSTRAINT chk_inventory_cost_allocation_type
                CHECK (allocation_type IN ('CONSUME','RESTORE','UNWIND')),
            CONSTRAINT chk_inventory_cost_allocation_quantity CHECK (quantity > 0),
            CONSTRAINT chk_inventory_cost_allocation_amount CHECK (amount >= 0)
        )
    """)
    op.execute("CREATE INDEX ix_inventory_cost_allocation_event ON inventory_cost_allocations(company_id, cost_event_id, id)")

    for table in _TABLES:
        _rls(table)

    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_inventory_cost_history_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'inventory cost history is append-only'
                USING ERRCODE = '55000';
        END;
        $$;
    """)
    for table in ("inventory_cost_events", "inventory_cost_allocations"):
        op.execute(f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE OR TRUNCATE
            ON {table}
            FOR EACH STATEMENT
            EXECUTE FUNCTION prevent_inventory_cost_history_mutation()
        """)

    _grant_runtime_privileges()


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM inventory_cost_events LIMIT 1)
               OR EXISTS (SELECT 1 FROM inventory_cost_states LIMIT 1)
               OR EXISTS (SELECT 1 FROM inventory_cost_layers LIMIT 1)
               OR EXISTS (SELECT 1 FROM inventory_cost_allocations LIMIT 1)
               OR EXISTS (SELECT 1 FROM inventory_cost_policies WHERE is_active IS TRUE LIMIT 1)
            THEN
                RAISE EXCEPTION 'Refusing downgrade: inventory costing history/state exists';
            END IF;
        END
        $$;
    """)
    for table in ("inventory_cost_allocations", "inventory_cost_events"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS prevent_inventory_cost_history_mutation()")
    for table in reversed(_TABLES):
        op.drop_table(table)
