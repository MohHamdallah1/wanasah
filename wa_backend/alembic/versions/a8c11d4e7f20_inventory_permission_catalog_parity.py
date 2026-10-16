"""Persist canonical Inventory permission rows missing from clean bootstrap.

Revision ID: a8c11d4e7f20
Revises: f4c10a7e2d31

This is intentionally data-only. The canonical registry already owns these
capability codes; the migration only makes clean database bootstrap match it.
"""
from alembic import op

revision = "a8c11d4e7f20"
down_revision = "f4c10a7e2d31"
branch_labels = None
depends_on = None

PERMISSION_CODES = (
    "catalog.archive",
    "catalog.hold",
    "catalog.manage",
    "catalog.publish",
    "catalog.read",
    "catalog.restore",
    "catalog.retire",
    "dispatch.execute",
    "dispatch.read",
    "inbound.create",
    "inventory.costing.manage",
    "inventory.fefo_override",
    "inventory.read",
    "location.create",
    "location.read",
    "location.state",
    "location.update",
    "product_location.manage",
    "product_location.read",
    "stocktake.approve",
    "stocktake.cancel",
    "stocktake.count",
    "stocktake.read",
    "stocktake.recount",
    "stocktake.review",
    "stocktake.start",
    "transfer.cancel",
    "transfer.destination",
    "transfer.read",
    "transfer.receive",
    "transfer.reject",
    "transfer.send",
)


def upgrade() -> None:
    values = ",".join(f"('{code}')" for code in PERMISSION_CODES)
    op.execute(
        "INSERT INTO permissions (code) VALUES "
        + values
        + " ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    # Retain permission catalog history; downgrade must not invalidate grants.
    pass
