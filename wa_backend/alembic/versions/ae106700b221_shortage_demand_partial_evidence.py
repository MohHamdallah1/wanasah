"""#1067: tenant-scoped durable shortage quantity/urgent evidence.

No data backfill: legacy fulfilled/pending rows have unknown quantitative history.
Revises the exact reviewed single migration head b77c4e2a1073.
"""
import os
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import make_url

revision = "ae106700b221"
down_revision = "b77c4e2a1073"
branch_labels = None
depends_on = None

TABLES = ("shortage_urgent_assignments", "shortage_delivery_events")


def _runtime_role():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Shortage quantity migration requires DATABASE_URL")
    role = make_url(url).username
    if not role or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", role):
        raise RuntimeError("Invalid runtime role")
    row = op.get_bind().execute(sa.text(
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=:name"
    ), {"name": role}).mappings().one_or_none()
    if row is None or row["rolsuper"] or row["rolbypassrls"]:
        raise RuntimeError("Runtime must be NOSUPERUSER/NOBYPASSRLS")
    return '"' + role + '"'


def upgrade():
    role = _runtime_role()
    op.add_column("shortage_requests", sa.Column("fulfillment_version", sa.Integer(), nullable=True))
    op.add_column("shortage_requests", sa.Column("fulfilled_base", sa.Integer(), nullable=True))
    op.create_unique_constraint(
        "uq_shortage_requests_company_id", "shortage_requests", ["company_id", "id"],
    )
    op.create_check_constraint(
        "ck_shortage_requests_chk_shortage_partial_quantity", "shortage_requests",
        "(fulfillment_version IS NULL AND fulfilled_base IS NULL) OR "
        "(fulfillment_version = 1 AND fulfilled_base IS NOT NULL "
        "AND fulfilled_base >= 0 AND fulfilled_base <= quantity)",
    )
    op.create_table(
        "shortage_urgent_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("shortage_id", sa.Integer(), nullable=False),
        sa.Column("visit_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("custody_epoch_id", sa.BigInteger(), nullable=False),
        sa.Column("approved_base", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("company_id", "id", name="uq_shortage_assignment_company_id"),
        sa.UniqueConstraint("company_id", "shortage_id", "visit_id", name="uq_shortage_assignment_visit"),
        sa.ForeignKeyConstraint(["company_id", "shortage_id"],
                                ["shortage_requests.company_id", "shortage_requests.id"],
                                ondelete="RESTRICT", name="fk_shortage_assignment_tenant_demand"),
        sa.ForeignKeyConstraint(["company_id", "visit_id"], ["visits.company_id", "visits.id"],
                                ondelete="RESTRICT", name="fk_shortage_assignment_tenant_visit"),
        sa.ForeignKeyConstraint(["company_id", "driver_id"], ["drivers.company_id", "drivers.id"],
                                ondelete="RESTRICT", name="fk_shortage_assignment_tenant_driver"),
        sa.CheckConstraint("approved_base > 0", name="ck_shortage_urgent_assignments_chk_shortage_assignment_positive"),
    )
    op.create_index("ix_shortage_assignment_company_demand", "shortage_urgent_assignments",
                    ["company_id", "shortage_id"])
    op.create_table(
        "shortage_delivery_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("assignment_id", sa.Integer(), nullable=False),
        sa.Column("visit_id", sa.Integer(), nullable=False),
        sa.Column("sales_revision_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(12), nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("reverses_event_id", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("company_id", "id", name="uq_shortage_delivery_company_id"),
        sa.UniqueConstraint("company_id", "assignment_id", "sales_revision_id", "event_type",
                            name="uq_shortage_delivery_revision_type"),
        sa.UniqueConstraint("company_id", "reverses_event_id", name="uq_shortage_delivery_reversal"),
        sa.ForeignKeyConstraint(["company_id", "assignment_id"],
                                ["shortage_urgent_assignments.company_id", "shortage_urgent_assignments.id"],
                                ondelete="RESTRICT", name="fk_shortage_delivery_tenant_assignment"),
        sa.ForeignKeyConstraint(["company_id", "visit_id"], ["visits.company_id", "visits.id"],
                                ondelete="RESTRICT", name="fk_shortage_delivery_tenant_visit"),
        sa.ForeignKeyConstraint(["company_id", "visit_id", "sales_revision_id"],
                                ["sales_visit_revisions.company_id", "sales_visit_revisions.visit_id",
                                 "sales_visit_revisions.id"], ondelete="RESTRICT",
                                name="fk_shortage_delivery_sale_revision"),
        sa.ForeignKeyConstraint(["company_id", "reverses_event_id"],
                                ["shortage_delivery_events.company_id", "shortage_delivery_events.id"],
                                ondelete="RESTRICT", name="fk_shortage_delivery_reverses"),
        sa.CheckConstraint(
            "(event_type = 'DELIVERY' AND quantity_delta > 0 AND reverses_event_id IS NULL) OR "
            "(event_type = 'REVERSAL' AND quantity_delta < 0 AND reverses_event_id IS NOT NULL)",
            name="ck_shortage_delivery_events_chk_shortage_delivery_direction",
        ),
    )
    op.create_index("ix_shortage_delivery_company_assignment", "shortage_delivery_events",
                    ["company_id", "assignment_id", "id"])
    for table in TABLES:
        guard = "company_id = NULLIF(current_setting('app.current_tenant',true),'')::integer"
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY {table}_tenant_access ON "{table}" '
                   f'USING ({guard}) WITH CHECK ({guard})')
        op.execute(f'CREATE POLICY {table}_tenant_guard ON "{table}" AS RESTRICTIVE '
                   f'USING ({guard}) WITH CHECK ({guard})')
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO {role}')
        op.execute(f'REVOKE TRUNCATE, REFERENCES, TRIGGER ON "{table}" FROM {role}')
        op.execute(f'GRANT USAGE, SELECT ON SEQUENCE {table}_id_seq TO {role}')
        op.execute(f'REVOKE UPDATE ON SEQUENCE {table}_id_seq FROM {role}')


def downgrade():
    # Do not delete actual visited/delivered audit on rollback.
    for table in TABLES:
        count = op.get_bind().execute(sa.text(f'SELECT count(*) FROM "{table}"')).scalar()
        if count:
            raise RuntimeError("Shortage delivery history exists; downgrade is blocked")
    op.drop_table("shortage_delivery_events")
    op.drop_table("shortage_urgent_assignments")
    op.drop_constraint("ck_shortage_requests_chk_shortage_partial_quantity",
                       "shortage_requests", type_="check")
    op.drop_constraint("uq_shortage_requests_company_id",
                       "shortage_requests", type_="unique")
    op.drop_column("shortage_requests", "fulfilled_base")
    op.drop_column("shortage_requests", "fulfillment_version")
