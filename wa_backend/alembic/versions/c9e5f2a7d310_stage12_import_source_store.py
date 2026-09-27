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
        "product_import_global_source_capacity",
        sa.Column(
            "id",
            sa.SmallInteger(),
            nullable=False,
        ),
        sa.Column(
            "live_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "high_water_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=
                sa.text(
                    "CURRENT_TIMESTAMP"
                ),
        ),
        sa.CheckConstraint(
            "id = 1",
            name=
                "chk_product_import_global_capacity_singleton",
        ),
        sa.CheckConstraint(
            "live_bytes >= 0 AND high_water_bytes >= live_bytes",
            name=
                "chk_product_import_global_capacity_values",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=
                "pk_product_import_global_source_capacity",
        ),
    )
    op.execute(
        """
        INSERT INTO product_import_global_source_capacity (
            id,
            live_bytes,
            high_water_bytes,
            updated_at
        )
        VALUES (
            1,0,0,CURRENT_TIMESTAMP
        )
        """
    )

    op.create_table(
        "product_import_tenant_source_capacity",
        sa.Column(
            "company_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "live_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "high_water_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=
                sa.text(
                    "CURRENT_TIMESTAMP"
                ),
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
                "fk_product_import_tenant_capacity_company",
        ),
        sa.CheckConstraint(
            "live_bytes >= 0 AND high_water_bytes >= live_bytes",
            name=
                "chk_product_import_tenant_capacity_values",
        ),
        sa.PrimaryKeyConstraint(
            "company_id",
            name=
                "pk_product_import_tenant_source_capacity",
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

    # Existing live inline payloads are moved into the new immutable store
    # before application code starts depending on source_id. Job UUIDs are
    # already globally unique, so they are safe deterministic source ids for
    # this one-time bridge.
    op.execute(
        """
        INSERT INTO product_import_sources (
            id,
            company_id,
            sha256,
            byte_size,
            storage_backend,
            created_at,
            deleted_at
        )
        SELECT
            jobs.id,
            jobs.company_id,
            jobs.source_sha256,
            jobs.file_size,
            'POSTGRES_CHUNKS',
            jobs.created_at,
            NULL
        FROM product_import_jobs AS jobs
        WHERE jobs.source_payload IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO product_import_source_chunks (
            company_id,
            source_id,
            chunk_index,
            byte_size,
            payload,
            created_at
        )
        SELECT
            jobs.company_id,
            jobs.id,
            0,
            octet_length(jobs.source_payload),
            jobs.source_payload,
            jobs.created_at
        FROM product_import_jobs AS jobs
        WHERE jobs.source_payload IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE product_import_jobs
        SET source_id = id,
            source_payload = NULL
        WHERE source_payload IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO product_import_tenant_source_capacity (
            company_id,
            live_bytes,
            high_water_bytes,
            updated_at
        )
        SELECT
            sources.company_id,
            sum(sources.byte_size)::bigint,
            sum(sources.byte_size)::bigint,
            CURRENT_TIMESTAMP
        FROM product_import_sources AS sources
        WHERE sources.deleted_at IS NULL
        GROUP BY sources.company_id
        ON CONFLICT (company_id)
        DO UPDATE SET
            live_bytes = EXCLUDED.live_bytes,
            high_water_bytes =
                GREATEST(
                    product_import_tenant_source_capacity.high_water_bytes,
                    EXCLUDED.high_water_bytes
                ),
            updated_at = CURRENT_TIMESTAMP
        """
    )
    op.execute(
        """
        UPDATE product_import_global_source_capacity
        SET live_bytes = totals.live_bytes,
            high_water_bytes =
                GREATEST(
                    high_water_bytes,
                    totals.live_bytes
                ),
            updated_at = CURRENT_TIMESTAMP
        FROM (
            SELECT
                COALESCE(
                    sum(byte_size),
                    0
                )::bigint AS live_bytes
            FROM product_import_sources
            WHERE deleted_at IS NULL
        ) AS totals
        WHERE id = 1
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION product_import_source_metadata_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $body$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.company_id IS DISTINCT FROM OLD.company_id
               OR NEW.sha256 IS DISTINCT FROM OLD.sha256
               OR NEW.byte_size IS DISTINCT FROM OLD.byte_size
               OR NEW.storage_backend IS DISTINCT FROM OLD.storage_backend
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'Product Import source metadata is immutable';
            END IF;
            RETURN NEW;
        END;
        $body$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_product_import_source_metadata_immutable
        BEFORE UPDATE ON product_import_sources
        FOR EACH ROW
        EXECUTE FUNCTION product_import_source_metadata_immutable()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION product_import_source_chunk_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $body$
        BEGIN
            RAISE EXCEPTION 'Product Import source chunks are immutable';
        END;
        $body$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_product_import_source_chunk_immutable
        BEFORE UPDATE ON product_import_source_chunks
        FOR EACH ROW
        EXECUTE FUNCTION product_import_source_chunk_immutable()
        """
    )

    _enable_rls(
        "product_import_tenant_source_capacity"
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
    op.execute(
        "DROP TRIGGER IF EXISTS "
        "trg_product_import_source_chunk_immutable "
        "ON product_import_source_chunks"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "product_import_source_chunk_immutable()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS "
        "trg_product_import_source_metadata_immutable "
        "ON product_import_sources"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "product_import_source_metadata_immutable()"
    )
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
        "product_import_tenant_source_capacity",
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
        "product_import_tenant_source_capacity"
    )
    op.drop_table(
        "product_import_global_source_capacity"
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
