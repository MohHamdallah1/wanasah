"""Stage 13 Product Import worker readiness registry.

Revision ID: e2c7b5d9a413
Revises: d1f4a8c6e2b9
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e2c7b5d9a413"
down_revision = "d1f4a8c6e2b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_import_worker_registry",
        sa.Column(
            "worker_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=False,
            server_default=
                sa.text(
                    "CURRENT_TIMESTAMP"
                ),
        ),
        sa.PrimaryKeyConstraint(
            "worker_id",
            name=
                "pk_product_import_worker_registry",
        ),
        sa.ForeignKeyConstraint(
            [
                "worker_id",
            ],
            [
                "procrastinate_workers.id",
            ],
            ondelete="CASCADE",
            name=
                "fk_product_import_worker_registry_worker",
        ),
    )
    op.create_index(
        "ix_product_import_worker_registry_seen",
        "product_import_worker_registry",
        [
            "last_seen_at",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_import_worker_registry_seen",
        table_name=
            "product_import_worker_registry",
    )
    op.drop_table(
        "product_import_worker_registry"
    )
