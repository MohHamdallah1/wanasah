"""stage7 async product import staging

Revision ID: f7a1c3d5e9b2
Revises: e3b7a9c1d4f6
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f7a1c3d5e9b2"
down_revision: Union[str, Sequence[str], None] = "e3b7a9c1d4f6"
branch_labels = None
depends_on = None


def _enable_rls(table_name: str) -> None:
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(f"""
        CREATE POLICY {table_name}_company_isolation ON "{table_name}"
        USING (company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer)
        WITH CHECK (company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer)
    """)


def upgrade() -> None:
    op.create_table(
        "product_import_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=150), nullable=False),
        sa.Column("source_payload", sa.LargeBinary(), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="QUEUED", nullable=False),
        sa.Column("detected_headers", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("suggested_mapping", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("column_mapping", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_summary", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("total_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("processed_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("valid_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('QUEUED','PARSING','NEEDS_MAPPING','VALIDATING','VALIDATION_FAILED','IMPORTING','RETRYING','COMPLETED','FAILED')", name="chk_product_import_job_status"),
        sa.CheckConstraint("file_size > 0", name="chk_product_import_job_file_size"),
        sa.CheckConstraint("total_rows >= 0 AND processed_rows >= 0 AND valid_rows >= 0 AND failed_rows >= 0", name="chk_product_import_job_counts_nonnegative"),
        sa.CheckConstraint("version > 0", name="chk_product_import_job_version"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_product_import_job_company"),
        sa.ForeignKeyConstraint(["company_id", "created_by"], ["drivers.company_id", "drivers.id"], ondelete="RESTRICT", name="fk_product_import_job_tenant_creator"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_product_import_jobs_company_id"),
        sa.UniqueConstraint("company_id", "request_id", name="uq_product_import_job_request"),
    )
    op.create_index("ix_product_import_job_company_status", "product_import_jobs", ["company_id", "status", "created_at"], unique=False)

    op.create_table(
        "product_import_rows",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("normalized_data", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="STAGED", nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("product_variant_id", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("row_number >= 2", name="chk_product_import_row_number"),
        sa.CheckConstraint("status IN ('STAGED','VALID','FAILED','IMPORTED')", name="chk_product_import_row_status"),
        sa.CheckConstraint("version > 0", name="chk_product_import_row_version"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_product_import_row_company"),
        sa.ForeignKeyConstraint(["company_id", "job_id"], ["product_import_jobs.company_id", "product_import_jobs.id"], ondelete="CASCADE", name="fk_product_import_row_tenant_job"),
        sa.ForeignKeyConstraint(["company_id", "product_variant_id"], ["product_variants.company_id", "product_variants.id"], ondelete="RESTRICT", name="fk_product_import_row_tenant_variant"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "job_id", "row_number", name="uq_product_import_row_job_number"),
    )
    op.create_index("ix_product_import_row_job_status", "product_import_rows", ["company_id", "job_id", "status", "row_number"], unique=False)
    _enable_rls("product_import_jobs")
    _enable_rls("product_import_rows")


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM product_import_rows LIMIT 1)
               OR EXISTS (SELECT 1 FROM product_import_jobs LIMIT 1)
            THEN
                RAISE EXCEPTION 'Refusing destructive downgrade: product import staging contains data';
            END IF;
        END $$;
    """)
    op.drop_table("product_import_rows")
    op.drop_table("product_import_jobs")
