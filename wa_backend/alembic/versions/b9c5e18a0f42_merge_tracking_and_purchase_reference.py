"""Join optional tracking defaults and purchase-cost reference V1 migrations.

Revision ID: b9c5e18a0f42
Revises: a1d7f0c6e5b2, f1a6c8e2b940

Both historical migrations remain immutable. This revision has no DDL.
"""
revision = "b9c5e18a0f42"
down_revision = ("a1d7f0c6e5b2", "f1a6c8e2b940")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
