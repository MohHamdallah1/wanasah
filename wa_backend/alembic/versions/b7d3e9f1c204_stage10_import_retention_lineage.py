"""Stage 10 Product Import retention and lineage metadata.

Revision ID: b7d3e9f1c204
Revises: f2a6d8c4b901
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b7d3e9f1c204"
down_revision = "f2a6d8c4b901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_import_jobs",
        sa.Column(
            "source_payload_cleared_at",
            sa.DateTime(),
            nullable=True,
        ),
    )
    op.add_column(
        "product_import_rows",
        sa.Column(
            "compacted_at",
            sa.DateTime(),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_product_import_job_retention",
        "product_import_jobs",
        [
            "company_id",
            "finished_at",
            "id",
        ],
        unique=False,
        postgresql_where=sa.text(
            "finished_at IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_import_job_retention",
        table_name=
            "product_import_jobs",
    )
    op.drop_column(
        "product_import_rows",
        "compacted_at",
    )
    op.drop_column(
        "product_import_jobs",
        "source_payload_cleared_at",
    )
