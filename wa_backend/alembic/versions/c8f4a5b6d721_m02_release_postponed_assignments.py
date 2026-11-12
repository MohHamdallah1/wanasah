"""M02: live legacy driver/vehicle reservations exclude postponed routes.

Revision ID: c8f4a5b6d721
Revises: b7e2c4a9d631

The zone's original uq_active_route_per_zone remains unchanged and protects
postponed territories. New M01 unique live execution-period indexes protect
the canonical current driver/vehicle assignments. The legacy route indexes
still protect *only* pre-M02 live route writers at assignment revision 1.
Cross-table race safety depends on the M02 endpoint+route-launch guards holding
the same sorted Driver and Vehicle row locks; never deploy this migration
without the accompanying route lifecycle writer.

The exact two ORM Index() metadata predicates must be kept in sync in
models.py by the owner of that file (LEAD/Worker1); do not disable Alembic
check to conceal metadata drift.
"""
from alembic import op
import sqlalchemy as sa

revision = "c8f4a5b6d721"
down_revision = "b7e2c4a9d631"
branch_labels = None
depends_on = None


def upgrade():
    # Transactional DDL: no interval without a DB unique live-route guard.
    # SHARE ROW EXCLUSIVE blocks concurrent route writes across predicate swap.
    op.execute("LOCK TABLE dispatch_routes IN SHARE ROW EXCLUSIVE MODE")
    op.drop_index("uq_active_route_per_driver", table_name="dispatch_routes")
    op.drop_index("uq_active_route_per_vehicle", table_name="dispatch_routes")
    op.create_index(
        "uq_active_route_per_driver",
        "dispatch_routes",
        ["company_id", "driver_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('active','waiting') AND assignment_context_revision = 1"
        ),
    )
    op.create_index(
        "uq_active_route_per_vehicle",
        "dispatch_routes",
        ["company_id", "vehicle_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('active','waiting') AND assignment_context_revision = 1"
        ),
    )


def downgrade():
    # Revert only while every M02 execution-period assignment has been
    # remediated; old route indexes cannot represent multiple periods/cars.
    bind = op.get_bind()
    in_use = bind.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM dispatch_routes WHERE assignment_context_revision > 1
        ) OR EXISTS (
            SELECT 1 FROM dispatch_route_execution_periods
            WHERE state IN ('PLANNED','ACTIVE','CLOSED')
              AND evidence_origin='CANONICAL'
        )
    """)).scalar()
    if in_use:
        raise RuntimeError(
            "M02 downgrade blocked: canonical assignments or route revisions "
            "require forward-only, reviewed repair; do not re-reserve old cars."
        )
    op.execute("LOCK TABLE dispatch_routes IN SHARE ROW EXCLUSIVE MODE")
    op.drop_index("uq_active_route_per_driver", table_name="dispatch_routes")
    op.drop_index("uq_active_route_per_vehicle", table_name="dispatch_routes")
    op.create_index(
        "uq_active_route_per_driver", "dispatch_routes",
        ["company_id", "driver_id"], unique=True,
        postgresql_where=sa.text("status IN ('active','waiting','postponed')"),
    )
    op.create_index(
        "uq_active_route_per_vehicle", "dispatch_routes",
        ["company_id", "vehicle_id"], unique=True,
        postgresql_where=sa.text("status IN ('active','waiting','postponed')"),
    )
