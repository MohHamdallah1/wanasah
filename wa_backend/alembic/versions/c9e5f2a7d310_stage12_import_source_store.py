"""Stage 12 Product Import immutable source store and admission telemetry.

Revision ID: c9e5f2a7d310
Revises: b7d3e9f1c204
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c9e5f2a7d310"
down_revision = "b7d3e9f1c204"
branch_labels = None
depends_on = None


_TENANT_EXPR = (
    "company_id = "
    "NULLIF(current_setting('app.current_tenant', true), '')::integer"
)


def _enable_rls(
    table_name: str,
) -> None:
    op.execute(
        f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY'
    )
    op.execute(
        f"""
        CREATE POLICY {table_name}_company_isolation
        ON "{table_name}"
        FOR ALL
        USING ({_TENANT_EXPR})
        WITH CHECK ({_TENANT_EXPR})
        """
    )


def upgrade() -> None:
    op.create_table(
        "product_import_sources",
        sa.Column(
            "id",
            postgresql.UUID(
                as_uuid=True
            ),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "sha256",
            sa.String(
                length=64
            ),
            nullable=False,
        ),
        sa.Column(
            "byte_size",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "storage_backend",
            sa.String(
                length=40
            ),
            nullable=False,
            server_default=
                "POSTGRES_CHUNKS",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=
                sa.text(
                    "CURRENT_TIMESTAMP"
                ),
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.CheckConstraint(
            "byte_size > 0",
            name=
                "chk_product_import_source_size",
        ),
        sa.CheckConstraint(
            "char_length(sha256) = 64",
            name=
                "chk_product_import_source_sha256",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=
                "pk_product_import_sources",
        ),
        sa.UniqueConstraint(
            "company_id",
            "id",
            name=
                "uq_product_import_source_company_id",
        ),
        sa.ForeignKeyConstraint(
            [
                "company_id",
            ],
            [
                "companies.id",
            ],
            ondelete="CASCADE",
            name=
                "fk_product_import_source_company",
        ),
    )
    op.create_index(
        "ix_product_import_source_live",
        "product_import_sources",
        [
            "company_id",
            "created_at",
            "id",
        ],
        unique=False,
        postgresql_where=
            sa.text(
                "deleted_at IS NULL"
            ),
    )

    op.create_table(
        "product_import_source_chunks",
        sa.Column(
            "company_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(
                as_uuid=True
            ),
            nullable=False,
        ),
        sa.Column(
            "chunk_index",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "byte_size",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "payload",
            sa.LargeBinary(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=
                sa.text(
                    "CURRENT_TIMESTAMP"
                ),
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name=
                "chk_product_import_source_chunk_index",
        ),
        sa.CheckConstraint(
            "byte_size > 0",
            name=
                "chk_product_import_source_chunk_size",
        ),
        sa.PrimaryKeyConstraint(
            "company_id",
            "source_id",
            "chunk_index",
            name=
                "pk_product_import_source_chunks",
        ),
        sa.ForeignKeyConstraint(
            [
                "company_id",
                "source_id",
            ],
            [
                "product_import_sources.company_id",
                "product_import_sources.id",
            ],
            ondelete="CASCADE",
            name=
                "fk_product_import_source_chunk_source",
        ),
    )

    op.create_table(
        "product_import_admission_rejections",
        sa.Column(
            "id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "code",
            sa.String(
                length=100
            ),
            nullable=False,
        ),
        sa.Column(
            "current_value",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "limit_value",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "retry_after_seconds",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=
                sa.text(
                    "CURRENT_TIMESTAMP"
                ),
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=
                "pk_product_import_admission_rejections",
        ),
        sa.ForeignKeyConstraint(
            [
                "company_id",
            ],
            [
                "companies.id",
            ],
            ondelete="CASCADE",
            name=
                "fk_product_import_admission_company",
        ),
        sa.CheckConstraint(
            "current_value >= 0 AND limit_value > 0",
            name=
                "chk_product_import_admission_values",
        ),
        sa.CheckConstraint(
            "retry_after_seconds > 0",
            name=
                "chk_product_import_admission_retry_after",
        ),
    )
    op.create_index(
        "ix_product_import_admission_rejection_company_time",
        "product_import_admission_rejections",
        [
            "company_id",
            "created_at",
        ],
        unique=False,
    )

    op.add_column(
        "product_import_jobs",
        sa.Column(
            "source_id",
            postgresql.UUID(
                as_uuid=True
            ),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_product_import_job_source",
        "product_import_jobs",
        "product_import_sources",
        [
            "company_id",
            "source_id",
        ],
        [
            "company_id",
            "id",
        ],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_product_import_job_source",
        "product_import_jobs",
        [
            "company_id",
            "source_id",
        ],
        unique=False,
    )

    _enable_rls(
        "product_import_sources"
    )
    _enable_rls(
        "product_import_source_chunks"
    )
    _enable_rls(
        "product_import_admission_rejections"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_import_job_source",
        table_name=
            "product_import_jobs",
    )
    op.drop_constraint(
        "fk_product_import_job_source",
        "product_import_jobs",
        type_="foreignkey",
    )
    op.drop_column(
        "product_import_jobs",
        "source_id",
    )

    for table_name in (
        "product_import_admission_rejections",
        "product_import_source_chunks",
        "product_import_sources",
    ):
        op.execute(
            f'DROP POLICY IF EXISTS {table_name}_company_isolation '
            f'ON "{table_name}"'
        )

    op.drop_index(
        "ix_product_import_admission_rejection_company_time",
        table_name=
            "product_import_admission_rejections",
    )
    op.drop_table(
        "product_import_admission_rejections"
    )
    op.drop_table(
        "product_import_source_chunks"
    )
    op.drop_index(
        "ix_product_import_source_live",
        table_name=
            "product_import_sources",
    )
    op.drop_table(
        "product_import_sources"
    )
