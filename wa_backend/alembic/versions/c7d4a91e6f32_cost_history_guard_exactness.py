"""Make append-only costing guards row-exact for DELETE/UPDATE.

Revision ID: c7d4a91e6f32
Revises: b3e91c7a4d20

The original statement-level DELETE trigger rejected even a zero-row cascade.
That made deletion of a tenant with no cost history impossible.  Keep the
append-only guarantee exact: UPDATE/DELETE fail only when a history row would
actually be mutated, while TRUNCATE remains blocked unconditionally.
"""
from __future__ import annotations

from alembic import op


revision = "c7d4a91e6f32"
down_revision = "b3e91c7a4d20"
branch_labels = None
depends_on = None


_TABLES = (
    "inventory_cost_events",
    "inventory_cost_allocations",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}"
        )
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_truncate_guard ON {table}"
        )
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


def downgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}"
        )
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_truncate_guard ON {table}"
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE OR TRUNCATE
            ON {table}
            FOR EACH STATEMENT
            EXECUTE FUNCTION prevent_inventory_cost_history_mutation()
            """
        )
