"""M04 signed per-vehicle custody checkpoints after merged M03.

Ordered migration: checkpoint/epoch/line evidence, FORCE RLS and immutable
signed history. Requires a distinct NOBYPASSRLS application role.
Revision ID: e4b7c9d2a601
Revises: d7a2e9c3f541
"""
import os

from alembic import op
from sqlalchemy.engine import make_url
from domains.representative_settlement_multi_vehicle.schema import (
    upgrade_checkpoint_schema, downgrade_checkpoint_schema,
)

revision = "e4b7c9d2a601"
down_revision = "d7a2e9c3f541"
branch_labels = None
depends_on = None


def upgrade():
    # Bind RLS grants to the configured restricted runtime account, never the
    # privileged migration identity. Clean bootstrap uses wanasah_runtime;
    # ordinary deployments may use wanasah_app. The domain DDL verifies the
    # actual role exists and is neither SUPERUSER nor BYPASSRLS.
    runtime_url = os.environ.get("DATABASE_URL")
    if not runtime_url:
        raise RuntimeError("M04 requires the configured DATABASE_URL runtime role")
    runtime_role = make_url(runtime_url).username
    if not runtime_role:
        raise RuntimeError("M04 requires a named runtime role")
    upgrade_checkpoint_schema(op, runtime_role=runtime_role)


def downgrade():
    downgrade_checkpoint_schema(op)
