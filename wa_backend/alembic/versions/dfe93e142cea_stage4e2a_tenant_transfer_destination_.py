"""stage4e2a tenant transfer destination policy

Revision ID: dfe93e142cea
Revises: 07210d8e524e
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "dfe93e142cea"
down_revision: Union[str, Sequence[str], None] = "07210d8e524e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_operational_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("policy_code", sa.String(length=80), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "validated_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("effective_from", sa.DateTime(), nullable=True),
        sa.Column("effective_to", sa.DateTime(), nullable=True),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "length(trim(policy_code)) > 0",
            name="chk_tenant_operational_policy_code_not_blank",
        ),
        sa.CheckConstraint(
            "schema_version > 0",
            name="chk_tenant_operational_policy_schema_version",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="chk_tenant_operational_policy_revision",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT','PUBLISHED','SUPERSEDED')",
            name="chk_tenant_operational_policy_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(validated_payload) = 'object'",
            name="chk_tenant_operational_policy_payload_object",
        ),
        sa.CheckConstraint(
            "("
            "(status = 'DRAFT' AND effective_from IS NULL AND effective_to IS NULL "
            " AND approved_by IS NULL AND approved_at IS NULL)"
            " OR "
            "(status = 'PUBLISHED' AND effective_from IS NOT NULL AND effective_to IS NULL "
            " AND approved_by IS NOT NULL AND approved_at IS NOT NULL)"
            " OR "
            "(status = 'SUPERSEDED' AND effective_from IS NOT NULL AND effective_to IS NOT NULL "
            " AND approved_by IS NOT NULL AND approved_at IS NOT NULL "
            " AND effective_to >= effective_from)"
            ")",
            name="chk_tenant_operational_policy_state_metadata",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
            name="fk_tenant_operational_policy_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "created_by"],
            ["drivers.company_id", "drivers.id"],
            ondelete="RESTRICT",
            name="fk_tenant_operational_policy_creator",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "approved_by"],
            ["drivers.company_id", "drivers.id"],
            ondelete="RESTRICT",
            name="fk_tenant_operational_policy_approver",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "id",
            name="uq_tenant_operational_policies_company_id",
        ),
        sa.UniqueConstraint(
            "company_id",
            "policy_code",
            "revision",
            name="uq_tenant_operational_policy_revision",
        ),
    )

    op.create_index(
        "ix_tenant_operational_policy_lookup",
        "tenant_operational_policies",
        ["company_id", "policy_code", "status", "revision"],
        unique=False,
    )
    op.create_index(
        "uq_tenant_operational_policy_one_draft",
        "tenant_operational_policies",
        ["company_id", "policy_code"],
        unique=True,
        postgresql_where=sa.text("status = 'DRAFT'"),
    )
    op.create_index(
        "uq_tenant_operational_policy_one_published",
        "tenant_operational_policies",
        ["company_id", "policy_code"],
        unique=True,
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )

    # Tenant isolation is enforced at the database boundary as required by the plan.
    op.execute(
        "ALTER TABLE tenant_operational_policies ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE tenant_operational_policies FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_operational_policies_company_isolation
        ON tenant_operational_policies
        USING (
            company_id = NULLIF(
                current_setting('app.current_tenant', true),
                ''
            )::integer
        )
        WITH CHECK (
            company_id = NULLIF(
                current_setting('app.current_tenant', true),
                ''
            )::integer
        )
        """
    )


def downgrade() -> None:
    # Do not silently destroy tenant policy history on a downgrade.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM tenant_operational_policies LIMIT 1) THEN
                RAISE EXCEPTION
                    'Refusing destructive downgrade: tenant_operational_policies contains data';
            END IF;
        END
        $$;
        """
    )
    op.drop_table("tenant_operational_policies")
