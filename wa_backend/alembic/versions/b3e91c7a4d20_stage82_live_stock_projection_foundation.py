"""Stage 8.2 Live Stock projection foundation.

Revision ID: b3e91c7a4d20
Revises: fa7c9d3e1b24
"""
from __future__ import annotations

import os
import re

from alembic import op
from sqlalchemy.engine import make_url


revision = "b3e91c7a4d20"
down_revision = "fa7c9d3e1b24"
branch_labels = None
depends_on = None

_TABLES = (
    "inventory_live_stock_company_summaries",
    "inventory_live_stock_warehouse_summaries",
    "inventory_live_stock_projection",
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
    for table in _TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {quoted}")
        op.execute(f"REVOKE TRUNCATE ON TABLE {table} FROM {quoted}")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE inventory_live_stock_company_summaries (
            company_id INTEGER PRIMARY KEY
                REFERENCES companies(id) ON DELETE CASCADE,
            active_variant_count BIGINT NOT NULL DEFAULT 0,
            projection_state VARCHAR(20) NOT NULL DEFAULT 'BUILDING',
            projection_version INTEGER NOT NULL DEFAULT 1,
            revision BIGINT NOT NULL DEFAULT 1,
            last_rebuilt_at TIMESTAMP NULL,
            last_verified_at TIMESTAMP NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT chk_live_stock_company_active_count
                CHECK (active_variant_count >= 0),
            CONSTRAINT chk_live_stock_company_state
                CHECK (projection_state IN ('BUILDING', 'READY', 'DEGRADED')),
            CONSTRAINT chk_live_stock_company_projection_version
                CHECK (projection_version > 0),
            CONSTRAINT chk_live_stock_company_revision
                CHECK (revision > 0)
        )
    """)

    op.execute("""
        CREATE TABLE inventory_live_stock_warehouse_summaries (
            company_id INTEGER NOT NULL
                REFERENCES companies(id) ON DELETE CASCADE,
            warehouse_location_id INTEGER NOT NULL,
            alert_count BIGINT NOT NULL DEFAULT 0,
            nonactive_visible_count BIGINT NOT NULL DEFAULT 0,
            projected_row_count BIGINT NOT NULL DEFAULT 0,
            projection_state VARCHAR(20) NOT NULL DEFAULT 'BUILDING',
            projection_version INTEGER NOT NULL DEFAULT 1,
            revision BIGINT NOT NULL DEFAULT 1,
            last_rebuilt_at TIMESTAMP NULL,
            last_verified_at TIMESTAMP NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (company_id, warehouse_location_id),
            CONSTRAINT fk_live_stock_warehouse_summary_location
                FOREIGN KEY (company_id, warehouse_location_id)
                REFERENCES inventory_locations(company_id, id)
                ON DELETE CASCADE,
            CONSTRAINT chk_live_stock_warehouse_alert_count
                CHECK (alert_count >= 0),
            CONSTRAINT chk_live_stock_warehouse_nonactive_count
                CHECK (nonactive_visible_count >= 0),
            CONSTRAINT chk_live_stock_warehouse_row_count
                CHECK (projected_row_count >= 0),
            CONSTRAINT chk_live_stock_warehouse_alert_within_rows
                CHECK (alert_count <= projected_row_count),
            CONSTRAINT chk_live_stock_warehouse_nonactive_within_rows
                CHECK (nonactive_visible_count <= projected_row_count),
            CONSTRAINT chk_live_stock_warehouse_state
                CHECK (projection_state IN ('BUILDING', 'READY', 'DEGRADED')),
            CONSTRAINT chk_live_stock_warehouse_projection_version
                CHECK (projection_version > 0),
            CONSTRAINT chk_live_stock_warehouse_revision
                CHECK (revision > 0)
        )
    """)

    op.execute("""
        CREATE TABLE inventory_live_stock_projection (
            company_id INTEGER NOT NULL
                REFERENCES companies(id) ON DELETE CASCADE,
            warehouse_location_id INTEGER NOT NULL,
            product_variant_id INTEGER NOT NULL,
            variant_name VARCHAR(200) NOT NULL,
            lifecycle_status VARCHAR(20) NOT NULL,
            operational_hold VARCHAR(20) NOT NULL,
            warehouse_on_hand NUMERIC(20,6) NOT NULL DEFAULT 0,
            warehouse_reserved NUMERIC(20,6) NOT NULL DEFAULT 0,
            warehouse_sellable_on_hand NUMERIC(20,6) NOT NULL DEFAULT 0,
            warehouse_sellable_reserved NUMERIC(20,6) NOT NULL DEFAULT 0,
            blocked_status_packs NUMERIC(20,6) NOT NULL DEFAULT 0,
            recalled_packs NUMERIC(20,6) NOT NULL DEFAULT 0,
            damaged_packs NUMERIC(20,6) NOT NULL DEFAULT 0,
            vehicle_packs NUMERIC(20,6) NOT NULL DEFAULT 0,
            minimum_quantity NUMERIC(20,6) NOT NULL DEFAULT 0,
            has_active_policy BOOLEAN NOT NULL DEFAULT FALSE,
            is_low_stock BOOLEAN NOT NULL DEFAULT FALSE,
            has_warehouse_presence BOOLEAN NOT NULL DEFAULT FALSE,
            has_vehicle_presence BOOLEAN NOT NULL DEFAULT FALSE,
            next_transition_date DATE NULL,
            computed_for_date DATE NOT NULL,
            revision BIGINT NOT NULL DEFAULT 1,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (company_id, warehouse_location_id, product_variant_id),
            CONSTRAINT fk_live_stock_projection_location
                FOREIGN KEY (company_id, warehouse_location_id)
                REFERENCES inventory_locations(company_id, id)
                ON DELETE CASCADE,
            CONSTRAINT fk_live_stock_projection_variant
                FOREIGN KEY (company_id, product_variant_id)
                REFERENCES product_variants(company_id, id)
                ON DELETE CASCADE,
            CONSTRAINT chk_live_stock_projection_lifecycle
                CHECK (lifecycle_status IN ('DRAFT', 'ACTIVE', 'RETIRING', 'ARCHIVED')),
            CONSTRAINT chk_live_stock_projection_hold
                CHECK (operational_hold IN ('NONE', 'SALES_HOLD', 'RECALL')),
            CONSTRAINT chk_live_stock_projection_name
                CHECK (length(trim(variant_name)) > 0),
            CONSTRAINT chk_live_stock_projection_warehouse_on_hand
                CHECK (warehouse_on_hand >= 0),
            CONSTRAINT chk_live_stock_projection_warehouse_reserved
                CHECK (warehouse_reserved >= 0),
            CONSTRAINT chk_live_stock_projection_reserved_within_on_hand
                CHECK (warehouse_reserved <= warehouse_on_hand),
            CONSTRAINT chk_live_stock_projection_sellable_on_hand
                CHECK (warehouse_sellable_on_hand >= 0),
            CONSTRAINT chk_live_stock_projection_sellable_reserved
                CHECK (warehouse_sellable_reserved >= 0),
            CONSTRAINT chk_live_stock_projection_sellable_within_on_hand
                CHECK (warehouse_sellable_on_hand <= warehouse_on_hand),
            CONSTRAINT chk_live_stock_projection_sellable_reserved_within_reserved
                CHECK (warehouse_sellable_reserved <= warehouse_reserved),
            CONSTRAINT chk_live_stock_projection_sellable_reserved_within_sellable
                CHECK (warehouse_sellable_reserved <= warehouse_sellable_on_hand),
            CONSTRAINT chk_live_stock_projection_blocked
                CHECK (blocked_status_packs >= 0),
            CONSTRAINT chk_live_stock_projection_recalled
                CHECK (recalled_packs >= 0),
            CONSTRAINT chk_live_stock_projection_recalled_within_blocked
                CHECK (recalled_packs <= blocked_status_packs),
            CONSTRAINT chk_live_stock_projection_damaged
                CHECK (damaged_packs >= 0),
            CONSTRAINT chk_live_stock_projection_vehicle
                CHECK (vehicle_packs >= 0),
            CONSTRAINT chk_live_stock_projection_minimum
                CHECK (minimum_quantity >= 0),
            CONSTRAINT chk_live_stock_projection_policy_minimum_consistency
                CHECK (has_active_policy IS TRUE OR minimum_quantity = 0),
            CONSTRAINT chk_live_stock_projection_warehouse_presence
                CHECK (
                    has_warehouse_presence =
                    (warehouse_on_hand > 0 OR blocked_status_packs > 0 OR damaged_packs > 0)
                ),
            CONSTRAINT chk_live_stock_projection_vehicle_presence
                CHECK (has_vehicle_presence = (vehicle_packs > 0)),
            CONSTRAINT chk_live_stock_projection_sparse_reason
                CHECK (
                    has_active_policy IS TRUE
                    OR has_warehouse_presence IS TRUE
                    OR has_vehicle_presence IS TRUE
                ),
            CONSTRAINT chk_live_stock_projection_alert_exact
                CHECK (
                    is_low_stock =
                    (
                        has_active_policy IS TRUE
                        AND minimum_quantity > 0
                        AND lifecycle_status = 'ACTIVE'
                        AND operational_hold = 'NONE'
                        AND (warehouse_sellable_on_hand - warehouse_sellable_reserved)
                            <= minimum_quantity
                    )
                ),
            CONSTRAINT chk_live_stock_projection_transition_after_compute
                CHECK (
                    next_transition_date IS NULL
                    OR next_transition_date > computed_for_date
                ),
            CONSTRAINT chk_live_stock_projection_revision
                CHECK (revision > 0)
        )
    """)

    op.execute("""
        CREATE INDEX ix_live_stock_projection_alert_seek
        ON inventory_live_stock_projection
            (company_id, warehouse_location_id, variant_name, product_variant_id)
        WHERE is_low_stock IS TRUE
    """)
    op.execute("""
        CREATE INDEX ix_live_stock_projection_nonactive_seek
        ON inventory_live_stock_projection
            (company_id, warehouse_location_id, variant_name, product_variant_id)
        WHERE lifecycle_status <> 'ACTIVE'
          AND (has_warehouse_presence IS TRUE OR has_vehicle_presence IS TRUE)
    """)
    op.execute("""
        CREATE INDEX ix_live_stock_projection_transition
        ON inventory_live_stock_projection
            (company_id, next_transition_date, warehouse_location_id, product_variant_id)
        WHERE next_transition_date IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX ix_live_stock_projection_variant
        ON inventory_live_stock_projection
            (company_id, product_variant_id, warehouse_location_id)
    """)

    for table in _TABLES:
        _rls(table)
    _grant_runtime_privileges()


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inventory_live_stock_projection")
    op.execute("DROP TABLE IF EXISTS inventory_live_stock_warehouse_summaries")
    op.execute("DROP TABLE IF EXISTS inventory_live_stock_company_summaries")
