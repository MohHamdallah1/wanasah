"""Allow the same authorized actor to receive or reject a transfer.

Revision ID: c3e7a5d9b214
Revises: b2f6c8e4a901
"""
from alembic import op

revision = "c3e7a5d9b214"
down_revision = "b2f6c8e4a901"
branch_labels = None
depends_on = None

CONSTRAINT = "ck_inventory_transfer_headers_chk_transfer_header_separation_of_duties"


def upgrade():
    op.drop_constraint(
        op.f(CONSTRAINT),
        "inventory_transfer_headers",
        type_="check",
    )


def downgrade():
    op.create_check_constraint(
        op.f(CONSTRAINT),
        "inventory_transfer_headers",
        (
            "workflow_type <> 'TRANSIT' "
            "OR status NOT IN ('POSTED', 'REJECTED') "
            "OR received_by <> dispatched_by"
        ),
    )
