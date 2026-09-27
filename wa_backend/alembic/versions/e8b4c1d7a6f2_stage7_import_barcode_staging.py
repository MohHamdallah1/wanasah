"""Stage 7 Product Import barcode staging for set-based validation.

Revision ID: e8b4c1d7a6f2
Revises: c4d9e7a1b623
"""
from __future__ import annotations

import os
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import make_url


revision = "e8b4c1d7a6f2"
down_revision = "c4d9e7a1b623"
branch_labels = None
depends_on = None

_TABLE = "product_import_row_barcodes"


def _runtime_role() -> str:
    raw = os.getenv("DATABASE_URL")
    if not raw:
        raise RuntimeError(
            "DATABASE_URL is required to grant the runtime database role."
        )
    role = make_url(raw).username
    if (
        not role
        or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_$]*",
            role,
        )
    ):
        raise RuntimeError(
            "Runtime database role could not be resolved safely."
        )
    return role


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column(
            "company_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "row_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "barcode",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text(
                "CURRENT_TIMESTAMP"
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            [
                "company_id",
                "job_id",
                "row_number",
            ],
            [
                "product_import_rows.company_id",
                "product_import_rows.job_id",
                "product_import_rows.row_number",
            ],
            ondelete="CASCADE",
            name="fk_product_import_row_barcode_tenant_row",
        ),
        sa.PrimaryKeyConstraint(
            "company_id",
            "job_id",
            "row_number",
            "barcode",
            name="pk_product_import_row_barcodes",
        ),
    )
    op.create_index(
        "ix_product_import_row_barcode_job_barcode",
        _TABLE,
        [
            "company_id",
            "job_id",
            "barcode",
            "row_number",
        ],
        unique=False,
    )

    op.execute(
        f'ALTER TABLE "{_TABLE}" ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        f'ALTER TABLE "{_TABLE}" FORCE ROW LEVEL SECURITY'
    )
    op.execute(
        f"""
        CREATE POLICY {_TABLE}_company_isolation
        ON "{_TABLE}"
        FOR ALL
        USING (
            company_id =
            NULLIF(current_setting('app.current_tenant', true), '')::integer
        )
        WITH CHECK (
            company_id =
            NULLIF(current_setting('app.current_tenant', true), '')::integer
        )
        """
    )

    role = _runtime_role().replace(
        '"',
        '""',
    )
    quoted = f'"{role}"'
    op.execute(
        f"GRANT USAGE ON SCHEMA public TO {quoted}"
    )
    op.execute(
        f"GRANT SELECT, INSERT, DELETE ON TABLE {_TABLE} TO {quoted}"
    )
    op.execute(
        f"REVOKE UPDATE, TRUNCATE ON TABLE {_TABLE} FROM {quoted}"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_import_row_barcode_job_barcode",
        table_name=_TABLE,
    )
    op.drop_table(_TABLE)
