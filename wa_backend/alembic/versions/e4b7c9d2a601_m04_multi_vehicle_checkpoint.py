"""M04 signed per-vehicle custody checkpoints after merged M03.

Ordered migration: checkpoint/epoch/line evidence, FORCE RLS and immutable
signed history. Requires a distinct NOBYPASSRLS application role.
Revision ID: e4b7c9d2a601
Revises: d7a2e9c3f541
"""
from alembic import op
from domains.representative_settlement_multi_vehicle.schema import (
    upgrade_checkpoint_schema, downgrade_checkpoint_schema,
)

revision = "e4b7c9d2a601"
down_revision = "d7a2e9c3f541"
branch_labels = None
depends_on = None


def upgrade():
    upgrade_checkpoint_schema(op, runtime_role="wanasah_app")


def downgrade():
    downgrade_checkpoint_schema(op)
