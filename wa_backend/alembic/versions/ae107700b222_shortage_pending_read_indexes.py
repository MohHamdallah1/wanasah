"""#1077: tenant-local Pending Visit and visit-leading assignment read indexes.

Performance only: no data rewrite or changes to tenant policies.
"""
from alembic import op

revision = "ae107700b222"
down_revision = "ae106700b221"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_shortage_assignment_company_visit_demand", "shortage_urgent_assignments",
        ["company_id", "visit_id", "shortage_id"],
    )
    op.create_index(
        "ix_visits_company_status_id", "visits", ["company_id", "status", "id"],
    )


def downgrade():
    op.drop_index("ix_visits_company_status_id", table_name="visits")
    op.drop_index(
        "ix_shortage_assignment_company_visit_demand",
        table_name="shortage_urgent_assignments",
    )
