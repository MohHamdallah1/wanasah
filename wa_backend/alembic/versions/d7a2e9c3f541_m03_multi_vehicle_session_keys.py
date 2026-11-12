"""M03: one WorkSession across vehicle locations and recurring route contexts.

Revision ID: d7a2e9c3f541
Revises: c8f4a5b6d721

Historical rows and FK constraints are preserved exactly. Only the original
two wrongly global UNIQUE constraints are changed. The new snapshot UNIQUE
remains tenant/session/physical-location/variant/status scoped; the historical
commercial context remains an immutable FK on each WorkSession but may be
referenced by another day's session after explicit financial settlement.
"""
from alembic import op
import sqlalchemy as sa

revision = "d7a2e9c3f541"
down_revision = "c8f4a5b6d721"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Transactional DDL: never expose an unprotected intermediate write.
    # The snapshot and commercial keys are tiny metadata-only rewrites;
    # PostgreSQL installs the new UNIQUE constraint before committing.
    op.execute(
        "LOCK TABLE work_sessions, session_inventory_snapshots "
        "IN ACCESS EXCLUSIVE MODE"
    )
    op.drop_constraint(
        "uq_session_inventory_snapshot_variant_status",
        "session_inventory_snapshots", type_="unique",
    )
    op.create_unique_constraint(
        "uq_session_inventory_snapshot_variant_status",
        "session_inventory_snapshots",
        [
            "company_id", "work_session_id", "location_id",
            "product_variant_id", "stock_status",
        ],
    )

    # No FK references this WorkSession uniqueness: its immutable tenant FK
    # references route_commercial_contexts(company_id,id), independently.
    op.drop_constraint(
        "uq_work_sessions_commercial_context",
        "work_sessions", type_="unique",
    )
    op.create_index(
        "ix_work_sessions_commercial_context", "work_sessions",
        ["company_id", "commercial_context_id"], unique=False,
    )


def downgrade() -> None:
    op.execute(
        "LOCK TABLE work_sessions, session_inventory_snapshots "
        "IN ACCESS EXCLUSIVE MODE"
    )
    bind = op.get_bind()

    # Restoring the obsolete keys would reject legitimate M03 facts. Do not
    # delete, merge, recode, or guess any historic custody/session evidence.
    same_sku_two_locations = bind.scalar(sa.text("""
        SELECT EXISTS (
            SELECT 1
            FROM session_inventory_snapshots
            GROUP BY company_id, work_session_id, product_variant_id, stock_status
            HAVING COUNT(*) > 1
        )
    """))
    context_reused_across_days = bind.scalar(sa.text("""
        SELECT EXISTS (
            SELECT 1
            FROM work_sessions
            WHERE commercial_context_id IS NOT NULL
            GROUP BY company_id, commercial_context_id
            HAVING COUNT(*) > 1
        )
    """))
    if same_sku_two_locations or context_reused_across_days:
        raise RuntimeError(
            "M03 downgrade refused: a session contains distinct vehicle "
            "snapshots or a frozen commercial context is referenced by more "
            "than one WorkSession; forward-only reviewed repair is required"
        )

    op.drop_index("ix_work_sessions_commercial_context", table_name="work_sessions")
    op.create_unique_constraint(
        "uq_work_sessions_commercial_context",
        "work_sessions", ["company_id", "commercial_context_id"],
    )
    op.drop_constraint(
        "uq_session_inventory_snapshot_variant_status",
        "session_inventory_snapshots", type_="unique",
    )
    op.create_unique_constraint(
        "uq_session_inventory_snapshot_variant_status",
        "session_inventory_snapshots",
        ["company_id", "work_session_id", "product_variant_id", "stock_status"],
    )
