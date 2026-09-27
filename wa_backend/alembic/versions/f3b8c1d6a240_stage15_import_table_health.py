"""Stage 15 Product Import table-health tuning.

Revision ID: f3b8c1d6a240
Revises: e2c7b5d9a413
"""
from __future__ import annotations

from alembic import op


revision = "f3b8c1d6a240"
down_revision = "e2c7b5d9a413"
branch_labels = None
depends_on = None


_ROWS_OPTIONS = (
    "autovacuum_vacuum_scale_factor=0.05, "
    "autovacuum_vacuum_threshold=2500, "
    "autovacuum_analyze_scale_factor=0.02, "
    "autovacuum_analyze_threshold=1000, "
    "autovacuum_vacuum_insert_scale_factor=0.05, "
    "autovacuum_vacuum_insert_threshold=5000"
)

_JOBS_OPTIONS = (
    "autovacuum_vacuum_scale_factor=0.10, "
    "autovacuum_vacuum_threshold=25, "
    "autovacuum_analyze_scale_factor=0.05, "
    "autovacuum_analyze_threshold=25, "
    "autovacuum_vacuum_insert_scale_factor=0.10, "
    "autovacuum_vacuum_insert_threshold=100"
)

_BARCODE_OPTIONS = (
    "autovacuum_vacuum_scale_factor=0.05, "
    "autovacuum_vacuum_threshold=2500, "
    "autovacuum_analyze_scale_factor=0.02, "
    "autovacuum_analyze_threshold=1000, "
    "autovacuum_vacuum_insert_scale_factor=0.05, "
    "autovacuum_vacuum_insert_threshold=5000"
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE product_import_rows SET ("
        + _ROWS_OPTIONS
        + ")"
    )
    op.execute(
        "ALTER TABLE product_import_jobs SET ("
        + _JOBS_OPTIONS
        + ")"
    )
    op.execute(
        "ALTER TABLE product_import_row_barcodes SET ("
        + _BARCODE_OPTIONS
        + ")"
    )


def downgrade() -> None:
    options = (
        "autovacuum_vacuum_scale_factor, "
        "autovacuum_vacuum_threshold, "
        "autovacuum_analyze_scale_factor, "
        "autovacuum_analyze_threshold, "
        "autovacuum_vacuum_insert_scale_factor, "
        "autovacuum_vacuum_insert_threshold"
    )
    for table in (
        "product_import_rows",
        "product_import_jobs",
        "product_import_row_barcodes",
    ):
        op.execute(
            f"ALTER TABLE {table} RESET ({options})"
        )
